# Vendored Veteran Engineer runtime

This directory is a source snapshot of `9529360-cpu/veteran-engineer` used by ZN's
bounded engineering sidecar capability. ZN remains authoritative for Work,
permissions, user-facing progress, and long-term memory. Veteran owns only the
repository-local engineering Mission it is explicitly given.

The exact upstream identity is recorded in `VENDOR.json`. The V1 integration
uses Veteran's standalone newline-delimited JSON-RPC/MCP fallback and forces a
ZN-owned state directory. It does not require the optional MCP SDK packages.

The embedded runtime intentionally excludes upstream `src/installer/`: host
installation adapters are not part of ZN's embedded Mission runtime.

Do not edit vendored runtime files as ZN-specific code. ZN-specific policy and
bridging belong under `runtime/python/zn_agent/core/`.
