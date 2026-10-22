"""T3-5: 新手路径走查脚本化（验收固化，非功能项）。

把 TERM-3 验收「空 home → 交办 → 审批 → 完成无死胡同」落成一个可重跑的
走查脚本。只新增本文件与走查记录，不碰任何产品代码。

诚实度选择（规格允许二选一）：用「真 resident 沙箱 home」，不用
test_zn_cli 的 fake socket 模式。fake 只能验证 CLI 渲染，走查要的是新手
真实会撞到的东西（连接失败文案、空态提示、审批卡指引），必须走真
daemon RPC + 真 ``zn`` 入口 + 真 PTY（T3-3/T3-4 的提示只在真终端上出现）。

走查剧本（除特别注明外，每一步都是独立子进程，像新手一次次敲命令）：
  S1  全新机器：``zn help``（T3-1 场景帮助 + T3-3 三行上手提示）
  S2  常驻还没起：``zn work list``（连接失败是否给了下一步）
  S3  新手启动常驻服务（harness 代劳：与 zn-resident 服务同样的方式，
      在沙箱 ZN_HOME 里起一个真 resident）
  S4  正门：``zn`` → ``/help`` → ``/exit``（TERM-1 REPL 可进可出）
  S5  ``zn status`` 一屏总览
  S6  ``zn work list`` 空态（T3-4 下一步提示）
  S7  交办：``zn work submit --task …``
  S8  ``zn work list`` 看到活
  S9  ``zn work get`` 看结果（完成）
  S10 审批到达（harness 经 RPC 模拟一次常驻行动产生审批卡——审批本就
      来自常驻的行动，与真审批同源）→ ``zn approval list``
  S11 ``zn approval show`` 看卡
  S12 ``zn approval decide --allow`` 拍板
  S13 ``zn approval list`` 再次清空
  S14 收尾探针：``zn work cancel`` 关掉已结束的活
  S15 ``zn work list`` 闭环

每一步记录：命令、退出码、完整终端输出（ANSI 已剥离、易变 id/时间已
归一化，便于 diff）。检查分两类：
  - 硬检查：失败直接断言失败（主干回归）。
  - 缺陷探针：失败记入缺陷清单（卡点：需要猜命令 / 报错没给下一步），
    走查继续。缺陷清单随走查记录落盘，并由工人回填 backlog TERM-3；
    本项不碰产品代码，缺陷留给后续条目修。

走查记录落盘：环境变量 ``T35_WRITE_RECORD`` 指向路径则写入该处；
否则写临时目录并打印路径（CI 只跑检查不落盘）。

已知局限（写进记录，不藏着）：
  - 沙箱常驻无模型配置，run 在 1s 内以 success=False 结束；
    「执行中取消」(mid-run cancel) 路径本次未覆盖。
  - 完整 15 步走查需要 POSIX pty（真终端模拟在 Windows 控制台上不
    诚实，不硬凑）。Windows CI 上跑管道变体：真实断言 T3-3 首行提示与
    T3-4 空态尾巴在非 TTY 下沉默（不是跳过，断言不减少）。
"""

from __future__ import annotations

import os
import re
import select
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "runtime" / "python"))

from zn_agent.core.daemon import ResidentRpcServer
from zn_agent.core.provider_bridge import (
    build_resident_runtime_from_existing_stack,
)
from zn_agent.core.resident_server import ResidentSocketService
from zn_agent.core.zn_cli import ResidentClient, load_endpoint

_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]")
_THREAD_RE = re.compile(r"work-[0-9a-f]{8,}")
_REQUEST_RE = re.compile(r"approval-[0-9a-f]{8,}")
_EVENT_RE = re.compile(r"evt-[0-9a-zA-Z_-]{6,}")
_TS_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?")


def _sanitize(text: str) -> str:
    """Strip ANSI and normalize volatile ids/timestamps for a stable record."""
    text = _ANSI_RE.sub("", text)
    text = _TS_RE.sub("<ts>", text)
    text = _THREAD_RE.sub("work-<thread-id>", text)
    text = _REQUEST_RE.sub("approval-<request-id>", text)
    text = _EVENT_RE.sub("evt-<event-id>", text)
    return text


class _PtyProc:
    """One CLI invocation on a real PTY, like a novice typing at a terminal."""

    def __init__(
        self, argv: list[str], env: dict[str, str], pty_module: ModuleType
    ) -> None:
        master, slave = pty_module.openpty()
        self.master = master
        self.captured = bytearray()
        self.proc = subprocess.Popen(
            argv, stdin=slave, stdout=slave, stderr=slave, env=env, close_fds=True
        )
        os.close(slave)

    def _read_chunk(self) -> bytes:
        try:
            return os.read(self.master, 65536)
        except OSError:
            return b""  # EIO: child is gone, this is EOF on a pty

    def read_until(self, marker: bytes, timeout: float = 30.0) -> None:
        deadline = time.monotonic() + timeout
        while marker not in self.captured:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(
                    f"marker {marker!r} not seen within {timeout}s; "
                    f"tail={bytes(self.captured)[-1500:]!r}"
                )
            ready, _, _ = select.select([self.master], [], [], min(remaining, 0.5))
            if not ready:
                continue
            chunk = self._read_chunk()
            if not chunk:
                raise TimeoutError(
                    f"EOF before marker {marker!r}; tail={bytes(self.captured)[-1500:]!r}"
                )
            self.captured += chunk

    def run_to_exit(self, timeout: float = 120.0) -> tuple[int, str]:
        deadline = time.monotonic() + timeout
        while True:
            if time.monotonic() >= deadline:
                self.proc.kill()
                raise TimeoutError(
                    f"child did not exit within {timeout}s; "
                    f"tail={bytes(self.captured)[-1500:]!r}"
                )
            ready, _, _ = select.select([self.master], [], [], 0.5)
            if ready:
                chunk = self._read_chunk()
                if chunk:
                    self.captured += chunk
                    continue
            # No data right now: EOF (empty read) means the child is gone.
            if not ready:
                if self.proc.poll() is not None:
                    # Exited but the pty may still hold output; one more lap.
                    continue
                continue
            break
        code = self.proc.wait(timeout=10)
        os.close(self.master)
        return code, self.captured.decode("utf-8", "replace")

    def interact(self, script: list[tuple[bytes, bytes]], timeout: float = 30.0) -> tuple[int, str]:
        """Drive an interactive session: [(expect_marker, send_bytes), ...]."""
        for marker, send in script:
            self.read_until(marker, timeout)
            os.write(self.master, send)
        return self.run_to_exit(timeout)


@dataclass
class _Check:
    name: str
    passed: bool
    detail: str = ""


@dataclass
class _Defect:
    step: str
    title: str
    observed: str
    why_novice_stuck: str


@dataclass
class _Step:
    key: str
    title: str
    narrative: str
    command: str
    exit_code: int | None
    output: str = ""
    raw_output: str = ""  # pre-sanitization stream; only for id extraction
    checks: list[_Check] = field(default_factory=list)


class T35NoviceWalkthroughTest(unittest.TestCase):
    """Scripted walkthrough of the TERM-3 novice path. See module docstring."""

    def test_novice_path_walkthrough(self):
        if os.name == "nt":
            # No POSIX pty on Windows: assert the pipe-mode contract instead.
            # This is a real coverage variant, not a skip (Floor Guard bans
            # skip markers on new code): off a TTY the T3-3 first-run hint
            # and the T3-4 empty-list tail must stay silent.
            self._test_novice_path_pipe_mode()
            return
        # Local import on purpose: pty only exists on POSIX, and this
        # branch never executes on Windows. No module-level suppression.
        import pty

        wt = _NoviceWalkthrough(pty_module=pty)
        record_path = os.environ.get("T35_WRITE_RECORD") or str(
            Path(tempfile.gettempdir()) / "t35-novice-walkthrough-record.md"
        )
        try:
            wt.run_all()
        finally:
            wt.write_record(record_path)
        print(f"\n[T3-5] walkthrough: {len(wt.steps)} steps, {len(wt.defects)} defect(s)")
        print(f"[T3-5] record: {record_path}")
        for d in wt.defects:
            print(f"[T3-5] defect [{d.step}] {d.title}")

    def _test_novice_path_pipe_mode(self) -> None:
        """Pipe-mode (non-TTY) variant of the T3-3/T3-4 acceptance contract.

        Real assertions about scripted usage: the onboarding hint (the ①②③
        lines) and the empty-list "下一步" tail are terminal-only affordances
        and must not leak into piped/scripted output.
        """
        import faulthandler

        # Windows CI once killed this test's whole shard process with no
        # output (silent exit 1). faulthandler turns a native crash into a
        # traceback; the phase markers below (flushed, CI is unbuffered)
        # pinpoint which step the process died in.
        faulthandler.enable()

        def _mark(phase: str) -> None:
            print(f"[t35-pipe] {phase}", flush=True)

        _mark("enter")
        wt = _NoviceWalkthrough()  # env + resident harness only, no pty
        _mark("harness-init-ok")

        # T3-3: fresh ZN_HOME on purpose (no kernel/ yet, so the first-run
        # probe is armed). On pipes the hint must stay silent.
        _mark("help-spawn-begin")
        help_proc = subprocess.run(
            wt._cli_argv(["help"]),
            env=wt.child_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=60,
        )
        _mark(f"help-spawn-ok rc={help_proc.returncode}")
        self.assertEqual(help_proc.returncode, 0, help_proc.stderr)
        self.assertIn("交办", help_proc.stdout)  # help content itself intact
        self.assertNotIn("①", help_proc.stdout, "T3-3 首行提示必须在管道下沉默")
        self.assertNotIn("③", help_proc.stdout, "T3-3 首行提示必须在管道下沉默")
        _mark("t33-asserts-ok")

        # T3-4: empty home + running resident => empty list; the "下一步"
        # tail is terminal-only and must stay silent on pipes.
        # The resident boots as a real subprocess (like the zn-resident
        # service), not in-process: spawning CLI children from a process
        # that already hosts the resident's daemon threads silently killed
        # the whole Windows CI shard (exit 1, no output). The subprocess
        # pattern is the one test_resident_socket_service uses on Windows.
        _mark("boot-resident-begin")
        try:
            wt._boot_resident_subprocess()
            _mark("boot-resident-ok")
            _mark("list-spawn-begin")
            list_proc = subprocess.run(
                wt._cli_argv(["work", "list"]),
                env=wt.child_env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=60,
            )
            _mark(f"list-spawn-ok rc={list_proc.returncode}")
            self.assertEqual(list_proc.returncode, 0, list_proc.stderr)
            self.assertIn("no work threads", list_proc.stdout)
            self.assertNotIn("下一步", list_proc.stdout, "T3-4 空态尾巴必须在管道下沉默")
            _mark("t34-asserts-ok")
        finally:
            wt._stop_resident_subprocess()
            _mark("resident-stopped-ok")


class _NoviceWalkthrough:
    """Drives the walkthrough. Raises AssertionError on hard-check failure."""

    TASK_TEXT = "帮我整理今天的三件事"

    def __init__(self, pty_module: ModuleType | None = None) -> None:
        self._pty_module = pty_module
        self.tmp = Path(tempfile.mkdtemp(prefix="t35-walkthrough-"))
        self.home = self.tmp / "home"  # sandbox ZN_HOME; kernel/ appears at boot
        self.steps: list[_Step] = []
        self.defects: list[_Defect] = []
        self._old_env: dict[str, str | None] = {}
        repo_root = Path(__file__).resolve().parents[3]
        self.child_env = dict(os.environ)
        self.child_env.update(
            {
                "ZN_HOME": str(self.home),
                "ZN_AGENT_HOME": str(self.home),
                "TERM": "xterm-256color",
                "LANG": "C.UTF-8",
                "LC_ALL": "C.UTF-8",
                "PYTHONPATH": str(repo_root / "runtime" / "python"),
                "PYTHONIOENCODING": "utf-8",
            }
        )
        self.child_env.pop("NO_COLOR", None)

    # -- harness ---------------------------------------------------------
    def _cli_argv(self, args: list[str]) -> list[str]:
        # No --endpoint flag on purpose: the novice uses default discovery
        # via ZN_HOME, exactly like the real product.
        return [sys.executable, "-m", "zn_agent.core.zn_cli", *args]

    def _boot_resident(self) -> ResidentClient:
        kernel = self.home / "kernel"
        kernel.mkdir(parents=True, exist_ok=True)
        resident = build_resident_runtime_from_existing_stack(
            config={"model": {}}, store_path=kernel / "kernel.db"
        )
        rpc = ResidentRpcServer(resident=resident, life_interval=0.1)
        endpoint_path = kernel / "resident-endpoint.json"
        service = ResidentSocketService(rpc, endpoint_path=endpoint_path)
        thread = threading.Thread(
            target=service.serve_forever, name="t35-walkthrough-resident", daemon=True
        )
        thread.start()
        deadline = time.monotonic() + 15.0
        while not endpoint_path.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        if not endpoint_path.exists():
            raise AssertionError("sandbox resident did not publish its endpoint")
        return ResidentClient(load_endpoint(str(endpoint_path)))

    def _boot_resident_subprocess(self) -> subprocess.Popen:
        """Boot the sandbox resident as a real subprocess (pipe-mode only).

        Same resident, same sandbox home -- but a separate OS process, like
        the real zn-resident service. Keeps the test process free of the
        resident's daemon threads while it spawns CLI children.
        """
        kernel = self.home / "kernel"
        kernel.mkdir(parents=True, exist_ok=True)
        endpoint_path = kernel / "resident-endpoint.json"
        if endpoint_path.exists():
            endpoint_path.unlink()
        proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "zn_agent.core.resident_server",
                "--home",
                str(self.home),
            ],
            env=self.child_env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
        self._resident_proc = proc
        deadline = time.monotonic() + 30.0
        while not endpoint_path.exists() and time.monotonic() < deadline:
            if proc.poll() is not None:
                err = proc.stderr.read() if proc.stderr else ""
                raise AssertionError(
                    "sandbox resident subprocess died on boot: "
                    f"rc={proc.returncode}\n{err[-2000:]}"
                )
            time.sleep(0.05)
        if not endpoint_path.exists():
            self._stop_resident_subprocess()
            raise AssertionError("sandbox resident did not publish its endpoint")
        return proc

    def _stop_resident_subprocess(self) -> None:
        proc = getattr(self, "_resident_proc", None)
        self._resident_proc = None
        if proc is None or proc.poll() is not None:
            return
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=10)

    # -- step plumbing ----------------------------------------------------
    def _record_step(
        self,
        key: str,
        title: str,
        narrative: str,
        command: str,
        exit_code: int | None,
        raw_output: str,
    ) -> _Step:
        step = _Step(
            key=key,
            title=title,
            narrative=narrative,
            command=command,
            exit_code=exit_code,
            output=_sanitize(raw_output),
            raw_output=raw_output,
        )
        self.steps.append(step)
        return step

    def _check(self, step: _Step, name: str, cond: bool, detail: str = "") -> None:
        step.checks.append(_Check(name, bool(cond), detail))
        if not cond:
            raise AssertionError(
                f"[{step.key}] 硬检查失败：{name}。{detail}\n"
                f"命令：{step.command}\n输出：\n{step.output[:2000]}"
            )

    def _probe(self, step: _Step, name: str, cond: bool, defect: _Defect) -> None:
        """A novice-experience probe: failure becomes a defect, not a crash."""
        step.checks.append(_Check(name, bool(cond), "缺陷探针"))
        if not cond:
            self.defects.append(defect)

    def _run_cli(self, args: list[str], timeout: float = 120.0) -> tuple[int, str]:
        if self._pty_module is None:
            raise AssertionError("_run_cli needs a POSIX pty module")
        proc = _PtyProc(self._cli_argv(args), self.child_env, self._pty_module)
        return proc.run_to_exit(timeout)

    def _step_cli(
        self,
        key: str,
        title: str,
        narrative: str,
        args: list[str],
        timeout: float = 120.0,
    ) -> _Step:
        code, raw = self._run_cli(args, timeout)
        return self._record_step(
            key, title, narrative, "zn " + " ".join(args), code, raw
        )

    # -- the walkthrough --------------------------------------------------
    def run_all(self) -> None:
        # S1/S2: brand-new machine, no resident yet. ZN_HOME is fresh on
        # purpose: kernel/ does not exist, so the T3-3 first-run probe fires.
        s = self._step_cli(
            "S1", "上手帮助", "全新机器，新手先看帮助。", ["help"]
        )
        self._check(s, "exit 0", s.exit_code == 0)
        self._check(s, "场景化帮助出现", "交办" in s.output)
        self._check(s, "T3-3 三行上手提示出现", "①" in s.output and "③" in s.output)
        self._check(s, "帮助给出真实示例", "zn work submit --task" in s.output)

        s = self._step_cli(
            "S2",
            "常驻未启动先查活",
            "新手还没起常驻服务就查活——看报错是否指路而非死胡同。",
            ["work", "list"],
        )
        self._check(s, "exit 非 0（诚实失败）", s.exit_code not in (0, None))
        self._check(s, "报错给了下一步", "下一步" in s.output, "连接失败必须告诉新手怎么办")
        self._check(s, "下一步提到常驻服务", "zn-resident" in s.output)
        self._check(s, "无 traceback 泄漏", "Traceback" not in s.output)

        # S3: the novice starts the resident service (the harness does it the
        # same way the zn-resident service would: a real resident on the
        # sandbox ZN_HOME).
        client = self._boot_resident()
        self._record_step(
            "S3",
            "启动常驻服务",
            "新手按 S2 的指引启动常驻服务（走查 harness 代劳，起真 resident）。",
            "(harness) boot resident in sandbox ZN_HOME",
            0,
            "endpoint published at <home>/kernel/resident-endpoint.json",
        )

        # S4: the front door. Bare `zn` opens the TERM-1 REPL.
        if self._pty_module is None:
            raise AssertionError("run_all needs a POSIX pty module")
        proc = _PtyProc(self._cli_argv([]), self.child_env, self._pty_module)
        code, raw = proc.interact(
            [(b"zn> ", b"/help\n"), (b"zn> ", b"/exit\n")]
        )
        s = self._record_step(
            "S4", "正门 REPL", "听从上手提示①，直接运行 `zn` 进对话，再退出。", "zn",
            code, raw,
        )
        self._check(s, "/exit 后干净退出", s.exit_code == 0)
        self._check(s, "/help 列出会话命令", "/exit" in s.output)

        s = self._step_cli("S5", "整体状态", "`zn status` 一屏看服务/模型/审批。", ["status"])
        self._check(s, "exit 0", s.exit_code == 0)
        self._check(s, "常驻活着", "ok" in s.output)

        s = self._step_cli("S6", "空活列表", "空 home 查活，看 T3-4 下一步提示。", ["work", "list"])
        self._check(s, "exit 0", s.exit_code == 0)
        self._check(
            s, "T3-4 空态下一步提示", "下一步" in s.output and "zn work submit" in s.output
        )

        s = self._step_cli(
            "S7", "交办", "新手交办第一件事。", ["work", "submit", "--task", self.TASK_TEXT]
        )
        self._check(s, "exit 0", s.exit_code == 0)
        m = re.search(r"work-[0-9a-f]{8,}", _ANSI_RE.sub("", s.raw_output))
        self._check(s, "输出给出 thread id", m is not None, "新手要凭它跟进")
        if m:
            self._raw_thread_id = m.group(0)
        em = re.search(r"evt-[0-9a-zA-Z_-]{6,}", _ANSI_RE.sub("", s.raw_output))
        if em:
            self._raw_event_id = em.group(0)
        self._probe(
            s,
            "失败时给出下一步（当前沙箱无模型，run 以 success=False 结束）",
            "success=False" not in s.output or "zn work get" in s.output,
            _Defect(
                "S7",
                "work submit 报 success=False 时无下一步指引",
                "输出只有 `run event=… success=False …` 一行，新手不知道该干什么。",
                "应提示用 `zn work get --thread-id <id>` 看详情/原因，否则像死胡同。",
            ),
        )

        # Re-extract raw ids from the un-sanitized stream for later steps.
        s = self._step_cli("S8", "查活看到任务", "交办后查活，任务应在列表里。", ["work", "list"])
        self._check(s, "exit 0", s.exit_code == 0)
        self._check(s, "任务在列表里", "work-<thread-id>" in s.output)

        s = self._step_cli(
            "S9", "看结果（完成）", "用 work get 看交办事项的结果。", ["work", "get", "--thread-id", self._raw_thread_id]
        )
        self._check(s, "exit 0", s.exit_code == 0)
        self._check(s, "能看到任务原文", self.TASK_TEXT in s.output)

        # S10: an approval arrives. Approvals originate from resident actions;
        # the harness simulates one resident action over RPC (same source).
        created = client.call(
            "approval_request",
            {
                "action_kind": "send",
                "target": "walkthrough-target",
                "scope": "walkthrough",
                "value_text": "",
                "source": "resident",
            },
        )
        self._raw_request_id = created["request"]["request_id"]
        s = self._step_cli(
            "S10", "审批到达", "常驻产生一张审批卡，新手查卡。", ["approval", "list"]
        )
        self._check(s, "exit 0", s.exit_code == 0)
        self._check(s, "卡在列表里", "approval-<request-id>" in s.output)
        self._probe(
            s,
            "pending 卡给出下一步",
            "decide" in s.output or "下一步" in s.output,
            _Defect(
                "S10",
                "approval list 有 pending 卡时无下一步提示",
                "卡只展示 target/scope/expires，新手第一眼不知道敲什么命令拍板。",
                "`approval show` 有 `下一步：用 'zn approval decide …'`，list 漏了；"
                "新手需自行发现 show/decide，算一次猜命令。",
            ),
        )

        s = self._step_cli(
            "S11", "看卡详情", "先看清再拍板。", ["approval", "show", self._raw_request_id]
        )
        self._check(s, "exit 0", s.exit_code == 0)
        self._check(s, "详情给出拍板指引", "decide" in s.output)

        s = self._step_cli(
            "S12",
            "拍板批准",
            "新手批准这张卡。",
            ["approval", "decide", "--request-id", self._raw_request_id, "--allow"],
        )
        self._check(s, "exit 0", s.exit_code == 0)
        self._check(s, "批准生效", "approved" in s.output)

        s = self._step_cli(
            "S13", "审批清空", "拍板后复查：不应再有 pending。", ["approval", "list"]
        )
        self._check(s, "exit 0", s.exit_code == 0)
        self._check(s, "无 pending", "(none)" in s.output)
        self._probe(
            s,
            "空态给出下一步",
            "下一步" in s.output,
            _Defect(
                "S13",
                "approval list 空态无下一步提示",
                "只打印 `(none)`；T3-4 给 work/memory/team/suggestions 四个列表加了"
                "下一步尾巴，approval list 漏了。",
                "新手看到 (none) 不知道审批从哪来、接下来能干什么。",
            ),
        )

        # S14: closing probe — the novice tries to cancel the finished thread.
        s = self._step_cli(
            "S14",
            "收尾探针：取消已结束的活",
            "活已结束，新手试着 cancel 收尾（用交办时拿到的 event id）——看报错是否指路。",
            ["work", "cancel", "--thread-id", self._raw_thread_id, "--event-id", self._raw_event_id],
        )
        self._check(s, "exit 非 0（已结束，诚实失败）", s.exit_code not in (0, None))
        self._probe(
            s,
            "报错给出下一步而非裸异常",
            "下一步" in s.output and "RuntimeError" not in s.output,
            _Defect(
                "S14",
                "work cancel 对已结束 run 透出裸 RuntimeError 且无下一步",
                "输出 `zn: error: 服务端返回错误（work_cancel）：RuntimeError: work "
                "cancellation requires an active Work run`。",
                "应人话化并指引：活已结束，用 `zn work get --thread-id <id>` 看结果。",
            ),
        )

        s = self._step_cli("S15", "闭环", "最后查活：任务留痕、无进行中，路径闭环。", ["work", "list"])
        self._check(s, "exit 0", s.exit_code == 0)
        self._check(s, "任务留痕", "work-<thread-id>" in s.output)
        self._check(s, "无进行中", "active=no" in s.output)

    # -- raw id capture ---------------------------------------------------
    # Outputs are sanitized at record time; raw ids for later steps are
    # captured from each step's pre-sanitization stream (see S7/S10).
    _raw_thread_id: str = ""
    _raw_event_id: str = ""
    _raw_request_id: str = ""

    def write_record(self, path: str) -> None:
        lines = [
            "# T3-5 新手路径走查记录",
            "",
            f"- 走查时间：{time.strftime('%Y-%m-%d %H:%M %Z')}",
            "- 基线：T3-4 #641（`17e0aa176bb22f4958b072193b3898585e31cb59`）",
            "- 方式：真 resident 沙箱 ZN_HOME + 真 PTY + 真 `zn` 入口（非 fake socket）",
            "- 场景：空 home → 上手提示 → 交办 → 审批 → 完成",
            "- 约定：输出中 `<thread-id>` / `<request-id>` / `<event-id>` / `<ts>` 为归一化占位；",
            "  ANSI 已剥离；每步独立子进程。",
            "",
            "## 步骤",
            "",
        ]
        for st in self.steps:
            lines += [
                f"### {st.key} {st.title}",
                "",
                f"- 叙事：{st.narrative}",
                f"- 命令：`{st.command}`",
                f"- 退出码：{st.exit_code}",
                "- 检查：",
            ]
            for c in st.checks:
                mark = "✓" if c.passed else "✗（记入缺陷清单）"
                extra = f"——{c.detail}" if c.detail and c.detail != "缺陷探针" else ""
                lines.append(f"  - [{mark}] {c.name}{extra}")
            lines += ["", "<details>", "<summary>完整输出</summary>", "", "```text", st.output.rstrip(), "```", "", "</details>", ""]
        lines += ["## 缺陷清单", ""]
        if not self.defects:
            lines.append("本次走查未发现卡点。")
        else:
            for i, d in enumerate(self.defects, 1):
                lines += [
                    f"### D{i} [{d.step}] {d.title}",
                    "",
                    f"- 实际看到：{d.observed}",
                    f"- 新手卡点：{d.why_novice_stuck}",
                    "",
                ]
        lines += [
            "## 已知局限",
            "",
            "- 沙箱常驻无模型配置，run 在 1s 内以 success=False 结束；"
            "「执行中取消」(mid-run cancel) 路径本次未覆盖。",
            "- 审批卡由 harness 经 RPC 模拟常驻行动产生（与真审批同源）；",
            "  真实场景中审批来自常驻自主行动或消息渠道。",
            "",
        ]
        Path(path).write_text("\n".join(lines), encoding="utf-8")
