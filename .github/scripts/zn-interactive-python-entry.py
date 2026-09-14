from __future__ import annotations

import os
import runpy
import sys
import time
from pathlib import Path


def _fail(message: str) -> "NoReturn":
    raise RuntimeError(message)


def _wait_for_gate(gate_path: Path, *, timeout_seconds: float = 10.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if gate_path.is_file():
            return
        time.sleep(0.01)
    _fail(f"interactive launcher gate was not released: {gate_path}")


def _run_original(args: list[str]) -> None:
    if not args:
        _fail("interactive Python entry requires an original Python command")

    if args[0] == "-m":
        if len(args) < 2 or not args[1]:
            _fail("interactive Python entry received -m without a module")
        module = args[1]
        sys.argv = [module, *args[2:]]
        runpy.run_module(module, run_name="__main__", alter_sys=True)
        return

    if args[0].startswith("-"):
        _fail(f"unsupported interactive Python invocation mode: {args[0]}")

    script = args[0]
    sys.argv = [script, *args[1:]]
    runpy.run_path(script, run_name="__main__")


def main() -> None:
    if len(sys.argv) < 4:
        _fail("usage: entry.py READY_PATH GATE_PATH ORIGINAL_PYTHON_ARGS...")

    ready_path = Path(sys.argv[1])
    gate_path = Path(sys.argv[2])
    original_args = list(sys.argv[3:])

    ready_path.parent.mkdir(parents=True, exist_ok=True)
    ready_path.write_text(
        f"pid={os.getpid()}\n",
        encoding="utf-8",
    )
    _wait_for_gate(gate_path)
    _run_original(original_args)


if __name__ == "__main__":
    main()
