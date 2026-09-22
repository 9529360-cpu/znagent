from __future__ import annotations

"""ZN-owned Windows screen capture artifact boundary.

This module owns only native capture and artifact identity. Action authority,
replay policy, and postcondition verification remain in Body / Action Fabric.
"""

import hashlib
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .home import get_zn_home


class WindowsScreenCaptureUnavailable(RuntimeError):
    """The current host/session cannot expose the Windows desktop."""


class WindowsScreenCaptureError(RuntimeError):
    """A screen capture failed after the platform boundary was available."""


@dataclass(frozen=True, slots=True)
class ScreenCaptureArtifact:
    local_path: str
    width: int
    height: int
    size_bytes: int
    sha256: str
    source: str = "primary_screen"


def screen_capture_artifact_root(home: str | Path | None = None) -> Path:
    root = Path(home).expanduser() if home is not None else get_zn_home()
    return root / "artifacts" / "screenshots"


def screen_capture_artifact_path(
    event_id: str,
    *,
    home: str | Path | None = None,
) -> Path:
    normalized = str(event_id or "").strip()
    if not normalized:
        raise ValueError("screen capture requires a stable event_id")
    digest = hashlib.sha256(
        f"windows.screen.capture:{normalized}".encode("utf-8")
    ).hexdigest()[:24]
    return screen_capture_artifact_root(home) / f"screen-{digest}.png"


def screen_capture_support() -> tuple[bool, str, dict[str, Any]]:
    if os.name != "nt":
        return False, "screen capture is available only on Windows", {
            "source": "pillow_imagegrab",
            "platform_supported": False,
        }
    try:
        from PIL import ImageGrab  # noqa: F401
    except Exception as exc:
        return False, f"Pillow ImageGrab is unavailable: {type(exc).__name__}", {
            "source": "pillow_imagegrab",
            "platform_supported": True,
        }
    return True, "Windows Pillow ImageGrab capture boundary is available", {
        "source": "pillow_imagegrab",
        "platform_supported": True,
    }


def capture_primary_screen_artifact(
    event_id: str,
    *,
    home: str | Path | None = None,
    capture_fn: Callable[[], Any] | None = None,
) -> ScreenCaptureArtifact:
    if os.name != "nt":
        raise WindowsScreenCaptureUnavailable(
            "screen capture is available only on Windows"
        )

    from PIL import ImageGrab

    target = screen_capture_artifact_path(event_id, home=home)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    capture = capture_fn or ImageGrab.grab
    image = None
    try:
        image = capture()
        width, height = image.size
        if int(width) <= 0 or int(height) <= 0:
            raise WindowsScreenCaptureError(
                "screen capture returned an empty image"
            )
        image.save(temp, format="PNG")
        os.replace(temp, target)
        metadata = inspect_screen_capture_artifact(target, home=home)
        return ScreenCaptureArtifact(
            local_path=metadata["local_path"],
            width=metadata["width"],
            height=metadata["height"],
            size_bytes=metadata["size_bytes"],
            sha256=metadata["sha256"],
        )
    except WindowsScreenCaptureError:
        raise
    except Exception as exc:
        raise WindowsScreenCaptureError(
            f"screen capture failed: {type(exc).__name__}: {exc}"
        ) from exc
    finally:
        if image is not None:
            close = getattr(image, "close", None)
            if callable(close):
                close()
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass


def inspect_screen_capture_artifact(
    local_path: str | Path,
    *,
    home: str | Path | None = None,
) -> dict[str, Any]:
    root = screen_capture_artifact_root(home).resolve(strict=False)
    path = Path(local_path).expanduser().resolve(strict=True)
    if root not in path.parents:
        raise WindowsScreenCaptureError(
            "screen capture artifact escaped the ZN screenshot root"
        )
    if not path.is_file() or path.suffix.casefold() != ".png":
        raise WindowsScreenCaptureError(
            "screen capture artifact is not a PNG file"
        )

    payload = path.read_bytes()
    if not payload:
        raise WindowsScreenCaptureError("screen capture artifact is empty")

    from PIL import Image

    with Image.open(path) as image:
        width, height = image.size
        image.verify()
    if int(width) <= 0 or int(height) <= 0:
        raise WindowsScreenCaptureError(
            "screen capture artifact has invalid dimensions"
        )
    return {
        "local_path": str(path),
        "width": int(width),
        "height": int(height),
        "size_bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "source": "zn_screen_capture_artifact",
    }
