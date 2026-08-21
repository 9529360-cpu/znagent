from __future__ import annotations

"""ZN-owned resident configuration.

The resident must be able to boot, select resources and keep living without
loading another product's CLI configuration layer.  This module deliberately
starts small: one YAML document under ZN home, with an explicit path override
for tests/portable deployments.
"""

import os
from pathlib import Path
from typing import Any, Mapping

import yaml

from .home import get_zn_home


def zn_config_path(
    *,
    environ: Mapping[str, str] | None = None,
    home: str | Path | None = None,
) -> Path:
    env = environ if environ is not None else os.environ
    explicit = str(env.get("ZN_CONFIG_PATH") or "").strip()
    if explicit:
        return Path(explicit).expanduser()
    root = Path(home).expanduser() if home is not None else get_zn_home()
    return root / "config.yaml"


def load_zn_config(
    path: str | Path | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    config_path = Path(path).expanduser() if path is not None else zn_config_path(environ=environ)
    if not config_path.exists():
        return {}
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError(f"ZN config must be a mapping: {config_path}")
    return dict(raw)
