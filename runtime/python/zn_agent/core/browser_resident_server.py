from __future__ import annotations

import argparse
import os
from pathlib import Path

from .channel_runtime import build_zn_channel_adapters
from .recurring_will_rpc import RecurringWillResidentRpcServer
from .resident_server import ResidentSocketService, _serve_with_sigterm_cleanup


# Keep the established formal-entrypoint patch/import seam stable while the
# concrete product RPC gains recurring-Will controls through subclassing.
BrowserResidentRpcServer = RecurringWillResidentRpcServer

_FORMAL_RPC_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost"})


def _formal_rpc_host(value: object) -> str:
    host = str(value or "127.0.0.1").strip().lower() or "127.0.0.1"
    if host not in _FORMAL_RPC_LOOPBACK_HOSTS:
        raise ValueError(
            "formal ZN resident RPC must remain loopback-only; "
            f"refusing host {host!r}"
        )
    return host


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="zn-resident-server", add_help=True)
    parser.add_argument("--home", default=None)
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    args = parser.parse_args(argv)

    if args.home:
        os.environ["ZN_AGENT_HOME"] = str(Path(args.home).expanduser().resolve())

    host = _formal_rpc_host(args.host or os.getenv("ZN_RESIDENT_HOST") or "127.0.0.1")
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
