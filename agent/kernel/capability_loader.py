from __future__ import annotations

import hashlib
import importlib.util
from dataclasses import dataclass
from pathlib import Path

from .capabilities import CapabilityRegistry
from .home import get_zn_home


@dataclass(slots=True)
class LoadedCapability:
    name: str
    path: Path
    sha256: str


class PromotedCapabilityLoader:
    """Load only capabilities that have reached the promoted directory.

    Candidate/self-generated code must never be placed here directly. The
    future evolution pipeline is responsible for tests, benchmarks, promotion,
    and rollback before a file becomes eligible for resident startup loading.
    """

    def __init__(self, root: str | Path | None = None):
        self.root = Path(root) if root is not None else get_zn_home() / "capabilities" / "promoted"

    def load_into(self, registry: CapabilityRegistry) -> list[LoadedCapability]:
        self.root.mkdir(parents=True, exist_ok=True)
        loaded: list[LoadedCapability] = []
        for path in sorted(self.root.glob("*.py")):
            if path.name.startswith("_"):
                continue
            source = path.read_bytes()
            digest = hashlib.sha256(source).hexdigest()
            module_name = f"zn_promoted_{path.stem}_{digest[:12]}"
            spec = importlib.util.spec_from_file_location(module_name, path)
            if spec is None or spec.loader is None:
                raise RuntimeError(f"cannot load promoted capability: {path}")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            builder = getattr(module, "build_capability", None)
            if not callable(builder):
                raise ValueError(f"promoted capability {path} must define build_capability()")
            capability = builder()
            registry.register(capability)
            loaded.append(LoadedCapability(capability.name, path, digest))
        return loaded
