from __future__ import annotations

import argparse
import os
from pathlib import Path

from .browser_rpc import BrowserResidentRpcServer
from .channel_runtime import build_zn_channel_adapters
from .resident_server import ResidentSocketService, _serve_with_sigterm_cleanup


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="zn-resident-server", add_help=True)
    parser.add_argument("--home", default=None)
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    args = parser.parse_args(argv)

    if args.home:
        os.environ["ZN_AGENT_HOME"] = str(Path(args.home).expanduser().resolve())

    host = str(args.host or os.getenv("ZN_RESIDENT_HOST") or "127.0.0.1").strip() or "127.0.0.1"
    if args.port is not None:
        port = max(0, int(args.port))
    else:
        try:
            port = max(0, int(os.getenv("ZN_RESIDENT_PORT") or "0"))
        except ValueError:
            port = 0

    service = ResidentSocketService(
        BrowserResidentRpcServer(),
        host=host,
        port=port,
        channel_adapters=build_zn_channel_adapters(),
    )
    return _serve_with_sigterm_cleanup(service)


if __name__ == "__main__":
    raise SystemExit(main())
