from __future__ import annotations

"""Cross-platform pseudo-terminal bridge owned by ZN.

Source-extracted from the mature POSIX ptyprocess and Windows pywinpty bridges.
The old dashboard/WebSocket ownership is intentionally absent: this is a small
computer-body primitive used by ``agent.kernel.terminal``.
"""

import errno
import os
import signal
import sys
import time
from typing import Any, Protocol, Sequence


_MIN_DIMENSION = 1
_MAX_COLS = 2000
_MAX_ROWS = 1000


class PtyUnavailableError(RuntimeError):
    pass


class ZNPty(Protocol):
    @property
    def pid(self) -> int: ...

    def is_alive(self) -> bool: ...

    def read(self, timeout: float = 0.2) -> bytes | None: ...

    def write(self, data: bytes) -> None: ...

    def resize(self, cols: int, rows: int) -> None: ...

    def exit_code(self) -> int | None: ...

    def close(self) -> None: ...


def _clamp(value: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        return _MIN_DIMENSION
    return max(_MIN_DIMENSION, min(maximum, parsed))


class PosixPty:
    def __init__(self, proc: Any):
        self._proc = proc
        self._fd = int(proc.fd)
        self._closed = False
        self._exit_code: int | None = None

    @classmethod
    def spawn(
        cls,
        argv: Sequence[str],
        *,
        cwd: str | None,
        env: dict[str, str],
        cols: int = 80,
        rows: int = 24,
    ) -> "PosixPty":
        if sys.platform.startswith("win"):
            raise PtyUnavailableError("POSIX PTY is unavailable on Windows")
        try:
            import ptyprocess
        except ImportError as exc:
            raise PtyUnavailableError("ptyprocess is not installed") from exc
        spawn_env = dict(env)
        spawn_env.setdefault("TERM", "xterm-256color")
        proc = ptyprocess.PtyProcess.spawn(
            list(argv),
            cwd=cwd,
            env=spawn_env,
            dimensions=(_clamp(rows, _MAX_ROWS), _clamp(cols, _MAX_COLS)),
        )
        return cls(proc)

    @property
    def pid(self) -> int:
        return int(self._proc.pid)

    def is_alive(self) -> bool:
        if self._closed:
            return False
        try:
            return bool(self._proc.isalive())
        except Exception:
            return False

    def read(self, timeout: float = 0.2) -> bytes | None:
        if self._closed:
            return None
        import select

        try:
            readable, _, _ = select.select([self._fd], [], [], max(0.0, float(timeout)))
        except (OSError, ValueError):
            return None
        if not readable:
            return b""
        try:
            data = os.read(self._fd, 65536)
        except OSError as exc:
            if exc.errno in {errno.EIO, errno.EBADF}:
                self._capture_exit_code()
                return None
            raise
        if not data:
            self._capture_exit_code()
            return None
        return data

    def write(self, data: bytes) -> None:
        if self._closed or not data:
            return
        view = memoryview(data)
        while view:
            try:
                count = os.write(self._fd, view)
            except OSError as exc:
                if exc.errno in {errno.EIO, errno.EBADF, errno.EPIPE}:
                    return
                raise
            if count <= 0:
                return
            view = view[count:]

    def resize(self, cols: int, rows: int) -> None:
        if self._closed:
            return
        import fcntl
        import struct
        import termios

        winsize = struct.pack(
            "HHHH",
            _clamp(rows, _MAX_ROWS),
            _clamp(cols, _MAX_COLS),
            0,
            0,
        )
        try:
            fcntl.ioctl(self._fd, termios.TIOCSWINSZ, winsize)
        except OSError:
            pass

    def exit_code(self) -> int | None:
        self._capture_exit_code()
        return self._exit_code

    def _capture_exit_code(self) -> None:
        if self._exit_code is not None or self.is_alive():
            return
        try:
            self._proc.wait()
        except Exception:
            pass
        status = getattr(self._proc, "exitstatus", None)
        if status is not None:
            try:
                self._exit_code = int(status)
                return
            except (TypeError, ValueError):
                pass
        signal_status = getattr(self._proc, "signalstatus", None)
        if signal_status is not None:
            try:
                self._exit_code = 128 + int(signal_status)
            except (TypeError, ValueError):
                pass

    def close(self) -> None:
        if self._closed:
            return
        try:
            pgid = os.getpgid(self._proc.pid)
        except Exception:
            pgid = None
        for sig in (signal.SIGHUP, signal.SIGTERM, signal.SIGKILL):
            if not self.is_alive():
                break
            try:
                if pgid is not None:
                    os.killpg(pgid, sig)
                else:
                    self._proc.kill(sig)
            except Exception:
                pass
            deadline = time.monotonic() + 0.5
            while self.is_alive() and time.monotonic() < deadline:
                time.sleep(0.02)
        self._capture_exit_code()
        self._closed = True
        try:
            self._proc.close(force=True)
        except Exception:
            pass


class WindowsPty:
    def __init__(self, proc: Any):
        self._proc = proc
        self._closed = False
        self._exit_code: int | None = None

    @classmethod
    def spawn(
        cls,
        argv: Sequence[str],
        *,
        cwd: str | None,
        env: dict[str, str],
        cols: int = 80,
        rows: int = 24,
    ) -> "WindowsPty":
        if not sys.platform.startswith("win"):
            raise PtyUnavailableError("ConPTY is only available on Windows")
        try:
            from winpty import PtyProcess
        except ImportError as exc:
            raise PtyUnavailableError("pywinpty is not installed") from exc
        spawn_env = dict(env)
        spawn_env.setdefault("TERM", "xterm-256color")
        proc = PtyProcess.spawn(
            list(argv),
            cwd=cwd,
            env=spawn_env,
            dimensions=(_clamp(rows, _MAX_ROWS), _clamp(cols, _MAX_COLS)),
        )
        return cls(proc)

    @property
    def pid(self) -> int:
        return int(self._proc.pid)

    def is_alive(self) -> bool:
        if self._closed:
            return False
        try:
            return bool(self._proc.isalive())
        except Exception:
            return False

    def read(self, timeout: float = 0.2) -> bytes | None:
        if self._closed:
            return None
        try:
            data = self._proc.read(65536)
        except EOFError:
            self._capture_exit_code()
            return None
        except Exception:
            if not self.is_alive():
                self._capture_exit_code()
                return None
            return b""
        if not data:
            if not self.is_alive():
                self._capture_exit_code()
                return None
            time.sleep(min(max(0.0, float(timeout)), 0.02))
            return b""
        if isinstance(data, bytes):
            return data
        return str(data).encode("utf-8", errors="replace")

    def write(self, data: bytes) -> None:
        if self._closed or not data:
            return
        try:
            self._proc.write(data.decode("utf-8", errors="replace"))
        except Exception:
            return

    def resize(self, cols: int, rows: int) -> None:
        if self._closed:
            return
        try:
            self._proc.setwinsize(
                _clamp(rows, _MAX_ROWS),
                _clamp(cols, _MAX_COLS),
            )
        except Exception:
            pass

    def exit_code(self) -> int | None:
        self._capture_exit_code()
        return self._exit_code

    def _capture_exit_code(self) -> None:
        if self._exit_code is not None or self.is_alive():
            return
        for name in ("exitstatus", "exit_status", "returncode"):
            raw = getattr(self._proc, name, None)
            if raw is None:
                continue
            try:
                self._exit_code = int(raw)
                return
            except (TypeError, ValueError):
                continue

    def close(self) -> None:
        if self._closed:
            return
        try:
            self._proc.terminate(force=True)
        except Exception:
            pass
        self._capture_exit_code()
        self._closed = True


def spawn_zn_pty(
    argv: Sequence[str],
    *,
    cwd: str | None,
    env: dict[str, str],
    cols: int = 80,
    rows: int = 24,
) -> ZNPty:
    if sys.platform.startswith("win"):
        return WindowsPty.spawn(argv, cwd=cwd, env=env, cols=cols, rows=rows)
    return PosixPty.spawn(argv, cwd=cwd, env=env, cols=cols, rows=rows)
