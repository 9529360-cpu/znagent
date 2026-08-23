from __future__ import annotations

"""ZN-owned authorization boundary for outbound local media.

Channel adapters must not interpret an arbitrary local path as permission to
upload that file. This module separates path authorization from platform media
transport: the resident may nominate a local file, but an adapter can only send
it after this policy resolves the real file inside an explicitly allowed ZN
root.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .home import get_zn_home


class OutboundMediaAuthorizationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class AuthorizedOutboundMediaPath:
    path: Path
    allowed_root: Path
    size_bytes: int


def default_outbound_media_roots(home: str | Path | None = None) -> tuple[Path, ...]:
    root = Path(home).expanduser() if home is not None else get_zn_home()
    return (
        root / "artifacts",
        root / "channels" / "outbound",
    )


class OutboundMediaPathPolicy:
    """Authorize regular files contained by explicit ZN-owned roots.

    The policy resolves both roots and candidates before containment checks, so
    ``..`` traversal and symlinks that escape an allowed directory cannot turn
    a channel attachment into arbitrary host-file exfiltration. Transport size
    limits remain adapter-specific; ``max_bytes`` is an optional earlier bound
    for callers that already know their platform limit.
    """

    def __init__(
        self,
        allowed_roots: Iterable[str | Path],
        *,
        max_bytes: int | None = None,
    ) -> None:
        roots: list[Path] = []
        for value in allowed_roots:
            raw = Path(value).expanduser()
            if not raw.is_absolute():
                raise ValueError(f"outbound media root must be absolute: {raw}")
            resolved = raw.resolve(strict=False)
            if resolved.exists() and not resolved.is_dir():
                raise ValueError(f"outbound media root is not a directory: {resolved}")
            if resolved not in roots:
                roots.append(resolved)
        if not roots:
            raise ValueError("outbound media policy requires at least one allowed root")
        if max_bytes is not None and int(max_bytes) <= 0:
            raise ValueError("outbound media max_bytes must be positive")
        self.allowed_roots = tuple(roots)
        self.max_bytes = int(max_bytes) if max_bytes is not None else None

    @classmethod
    def for_zn_home(
        cls,
        home: str | Path | None = None,
        *,
        extra_roots: Iterable[str | Path] = (),
        max_bytes: int | None = None,
    ) -> "OutboundMediaPathPolicy":
        roots = list(default_outbound_media_roots(home))
        roots.extend(extra_roots)
        return cls(roots, max_bytes=max_bytes)

    def authorize(self, local_path: str | Path) -> AuthorizedOutboundMediaPath:
        raw_text = str(local_path or "").strip()
        if not raw_text:
            raise OutboundMediaAuthorizationError("outbound media path must not be empty")

        raw = Path(raw_text).expanduser()
        if not raw.is_absolute():
            raise OutboundMediaAuthorizationError(
                f"outbound media path must be absolute: {raw}"
            )
        try:
            resolved = raw.resolve(strict=True)
        except OSError as exc:
            raise OutboundMediaAuthorizationError(
                f"outbound media path does not resolve to a readable file: {raw}"
            ) from exc

        matched_root = next(
            (
                root
                for root in self.allowed_roots
                if resolved == root or root in resolved.parents
            ),
            None,
        )
        if matched_root is None:
            raise OutboundMediaAuthorizationError(
                f"outbound media path is outside ZN-authorized roots: {resolved}"
            )
        if not resolved.is_file():
            raise OutboundMediaAuthorizationError(
                f"outbound media path is not a regular file: {resolved}"
            )

        try:
            size_bytes = resolved.stat().st_size
        except OSError as exc:
            raise OutboundMediaAuthorizationError(
                f"outbound media file cannot be inspected: {resolved}"
            ) from exc
        if size_bytes <= 0:
            raise OutboundMediaAuthorizationError(
                f"outbound media file is empty: {resolved}"
            )
        if self.max_bytes is not None and size_bytes > self.max_bytes:
            raise OutboundMediaAuthorizationError(
                f"outbound media file exceeds limit: {size_bytes} > {self.max_bytes} bytes"
            )

        return AuthorizedOutboundMediaPath(
            path=resolved,
            allowed_root=matched_root,
            size_bytes=size_bytes,
        )
