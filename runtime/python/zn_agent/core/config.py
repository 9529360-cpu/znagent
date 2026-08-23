from __future__ import annotations

"""ZN-owned resident configuration.

Configuration belongs to the resident product boundary. Non-secret settings live
in one YAML document under ZN home; credentials are referenced from that file
but stored by the resident credential boundary instead of being written there.
"""

import os
import uuid
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


def save_zn_config(
    config: Mapping[str, Any],
    path: str | Path | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> Path:
    """Atomically persist ZN-owned non-secret configuration.

    Provider secrets must already have been replaced by credential references
    before this function is called. A best-effort owner-only file mode narrows
    accidental disclosure of the remaining configuration metadata.
    """

    if not isinstance(config, Mapping):
        raise ValueError("ZN config must be a mapping")
    config_path = Path(path).expanduser() if path is not None else zn_config_path(environ=environ)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    rendered = yaml.safe_dump(
        dict(config),
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    )
    temporary = config_path.with_name(f".{config_path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(rendered, encoding="utf-8")
        try:
            temporary.chmod(0o600)
        except OSError:
            pass
        os.replace(temporary, config_path)
        try:
            config_path.chmod(0o600)
        except OSError:
            pass
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
    return config_path
