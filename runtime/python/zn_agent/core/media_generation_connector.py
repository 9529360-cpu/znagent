from __future__ import annotations

"""Media generation connector (R9): images and text-to-speech behind a
pluggable provider interface, video as interface + docs only.

Two approval-gated write tools ride the same Fabric/Body capability path as
the document-artifact connector (R8):

- ``media.generate_image`` — prompt-driven image generation (PNG/JPEG/WebP),
  written to the configured workspace directory.
- ``media.generate_tts`` — text-to-speech synthesis (MP3/WAV/…), written to
  the configured workspace directory.

Providers are pluggable and OpenAI-compatible in shape:

- :class:`OpenAICompatibleMediaProvider` talks to ``POST {base_url}/images/generations``
  (``response_format: b64_json``) and ``POST {base_url}/audio/speech`` (raw
  audio bytes) over stdlib ``urllib``. The API key comes from a ZN credential
  reference resolved through :class:`~zn_agent.core.credentials.CredentialStore`
  at call time; with no credential store — or no secret behind the reference —
  every call raises :class:`MediaGenerationNotConfigured` explicitly instead of
  pretending to work. Nothing secret is ever committed to the repository.
- :class:`MockMediaGenerationProvider` produces deterministic in-memory
  bytes for tests and for host smoke checks.

Video generation is intentionally NOT implemented: the provider protocol
carries :meth:`MediaGenerationProvider.generate_video` as an interface whose
default implementation raises :class:`MediaVideoNotImplemented`, and the skill
says so. Wiring a real video endpoint is a later item.

The M-8 OpenAPI adapter was considered and deliberately not used: an
OpenAPI REST tool returns a JSON/text payload, but media generation is a
binary-response write whose contract (atomic file write, format re-read
verification, approval-scoped output path) is exactly the R8 document-artifact
shape, so this connector copies R8's approval-gated Body write path instead of
inventing a parallel mechanism.
"""

import base64
import binascii
import hashlib
import json
import os
import struct
import tempfile
import urllib.error
import urllib.request
import zlib
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol, Sequence

from .action_execution import (
    ActionExecutionRuntime,
    ActionObservation,
    ActionRequest,
    ActionVerification,
)
from .action_fabric import (
    ActionAvailability,
    ActionDescriptor,
    ActionFabricRegistry,
)
from .approval_cards import APPROVAL_KINDS
from .body import BodyAction, BodyActionResult, NativeBody
from .credential_isolation import is_credential_reference
from .mcp_capability_adapter import mcp_write_replay_identity
from .models import utc_now

__all__ = [
    "APPROVAL_KIND",
    "IMAGE_ACTION_ID",
    "PROVIDER_ID",
    "TTS_ACTION_ID",
    "MediaBytes",
    "MediaGenerationError",
    "MediaGenerationNotConfigured",
    "MediaGenerationProvider",
    "MediaProviderConfig",
    "MediaVideoNotImplemented",
    "GeneratedMedia",
    "MockMediaGenerationProvider",
    "OpenAICompatibleMediaProvider",
    "attach_media_generation_tools",
    "register_media_generation_runtime",
    "verify_audio_bytes",
    "verify_image_bytes",
    "write_image",
    "write_tts_audio",
]

PROVIDER_ID = "zn_media_generation"
IMAGE_ACTION_ID = "media.generate_image"
TTS_ACTION_ID = "media.generate_tts"

APPROVAL_KIND = "production_change"
assert APPROVAL_KIND in APPROVAL_KINDS

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class MediaGenerationError(Exception):
    """Explicit failure for media generation/verification."""


class MediaGenerationNotConfigured(MediaGenerationError):
    """Raised when no credential (or no credential store) is configured.

    The message always says the provider is not configured — the connector
    never pretends a generation worked.
    """


class MediaVideoNotImplemented(MediaGenerationError):
    """Raised by the video leg: interface and docs only in R9."""


# ---------------------------------------------------------------------------
# Bounds: one call cannot run away.
# ---------------------------------------------------------------------------

MAX_FILENAME_LEN = 120
MAX_PROMPT_CHARS = 4_000
MAX_TTS_CHARS = 4_096
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_AUDIO_BYTES = 25 * 1024 * 1024

IMAGE_SIZES = ("256x256", "512x512", "1024x1024", "1792x1024", "1024x1792")
IMAGE_FORMATS = ("png", "jpeg", "webp")
IMAGE_SUFFIX = {"png": ".png", "jpeg": ".jpg", "webp": ".webp"}
AUDIO_FORMATS = ("mp3", "wav", "opus", "aac", "flac", "pcm")
AUDIO_SUFFIX = {
    "mp3": ".mp3",
    "wav": ".wav",
    "opus": ".opus",
    "aac": ".aac",
    "flac": ".flac",
    "pcm": ".pcm",
}

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
JPEG_MAGIC = b"\xff\xd8\xff"
RIFF_MAGIC = b"RIFF"
WEBP_MAGIC = b"WEBP"
ID3_MAGIC = b"ID3"
MP3_FRAME_SYNC = b"\xff\xfb"
MP3_FRAME_SYNC_ALT = b"\xff\xf3"
MP3_FRAME_SYNC_ALT2 = b"\xff\xf2"

_DEFAULT_IMAGE_MODEL = "gpt-image-1"
_DEFAULT_TTS_MODEL = "gpt-4o-mini-tts"


# ---------------------------------------------------------------------------
# Provider configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MediaProviderConfig:
    """Host-owned configuration for an OpenAI-compatible media provider.

    ``credential_ref`` is a ZN credential-store reference such as
    ``provider:openai-media`` — never a secret value.
    """

    name: str
    base_url: str = "https://api.openai.com/v1"
    credential_ref: str = ""
    image_model: str = _DEFAULT_IMAGE_MODEL
    tts_model: str = _DEFAULT_TTS_MODEL
    timeout_seconds: float = 60.0

    def __post_init__(self) -> None:
        name = str(self.name or "").strip()
        if not name:
            raise MediaGenerationError("provider name must not be empty")
        base = str(self.base_url or "").strip().rstrip("/")
        if not (base.startswith("https://") or base.startswith("http://")):
            raise MediaGenerationError(
                f"provider base_url must be an http(s) URL, got {self.base_url!r}"
            )
        ref = str(self.credential_ref or "").strip()
        if ref and not is_credential_reference(ref):
            raise MediaGenerationError(
                "credential_ref must be an opaque credential reference, "
                "never a credential value"
            )
        timeout = float(self.timeout_seconds)
        if not 1.0 <= timeout <= 300.0:
            raise MediaGenerationError(
                "timeout_seconds must be between 1 and 300"
            )


# ---------------------------------------------------------------------------
# Provider interface
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MediaBytes:
    """Raw bytes produced by a provider plus the report used for verification."""

    kind: str  # "image" | "audio"
    data: bytes
    media_format: str
    report: Mapping[str, Any] = field(default_factory=dict)


class MediaGenerationProvider(Protocol):
    """Pluggable media provider, OpenAI-compatible in shape.

    ``generate_image`` and ``synthesize_speech`` return raw media bytes;
    the connector writes and verifies them. ``generate_video`` is part of
    the interface for forward compatibility but has no R9 implementation —
    providers keep the default, which raises :class:`MediaVideoNotImplemented`.
    """

    @property
    def provider_name(self) -> str: ...

    def capabilities(self) -> tuple[str, ...]:
        """Subset of ("image", "audio") this provider can produce."""
        ...

    def generate_image(
        self,
        prompt: str,
        *,
        size: str = "1024x1024",
        output_format: str = "png",
    ) -> MediaBytes: ...

    def generate_video(
        self,
        prompt: str,
        *,
        duration_seconds: float = 5.0,
    ) -> MediaBytes:
        """Interface only in R9: always raises (see the Protocol note)."""
        raise MediaVideoNotImplemented(
            "video generation is not implemented (R9 keeps the interface "
            "and docs only); no provider leg is wired"
        )

    def synthesize_speech(
        self,
        text: str,
        *,
        voice: str = "alloy",
        response_format: str = "mp3",
    ) -> MediaBytes: ...


# ---------------------------------------------------------------------------
# Mock provider: deterministic bytes for tests and host smoke checks.
# ---------------------------------------------------------------------------


def _minimal_png_bytes(width: int = 64, height: int = 64) -> bytes:
    """Build a minimal valid truecolor PNG with stdlib only (deterministic)."""
    def chunk(tag: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + tag
            + payload
            + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    raw = b"".join(b"\x00" + b"\x00\x00\x00" * width for _ in range(height))
    return (
        PNG_MAGIC
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def _minimal_wav_bytes(seconds: float = 1.0, sample_rate: int = 8000) -> bytes:
    """Build a minimal valid mono 16-bit WAV of silence (deterministic)."""
    frames = int(seconds * sample_rate)
    data = b"\x00\x00" * frames
    fmt = struct.pack("<HHIIHH", 1, 1, sample_rate, sample_rate * 2, 2, 16)
    return (
        RIFF_MAGIC
        + struct.pack("<I", 36 + len(data))
        + b"WAVE"
        + b"fmt "
        + struct.pack("<I", 16)
        + fmt
        + b"data"
        + struct.pack("<I", len(data))
        + data
    )


class MockMediaGenerationProvider:
    """Deterministic in-memory provider for tests and host smoke checks.

    Image bytes are a real minimal PNG (magic + IHDR/IDAT/IEND with valid
    CRCs), audio bytes a real minimal WAV — so the connector's read-back
    verification runs against honest format bytes, not placeholders.
    """

    def __init__(self, name: str = "mock") -> None:
        self._name = str(name or "mock").strip() or "mock"

    @property
    def provider_name(self) -> str:
        return self._name

    def capabilities(self) -> tuple[str, ...]:
        return ("image", "audio")

    def generate_video(
        self,
        prompt: str,
        *,
        duration_seconds: float = 5.0,
    ) -> MediaBytes:
        # Interface only in R9 (see MediaGenerationProvider): no leg is wired.
        raise MediaVideoNotImplemented(
            "video generation is not implemented (R9 keeps the interface "
            "and docs only); no provider leg is wired"
        )

    def generate_image(
        self,
        prompt: str,
        *,
        size: str = "1024x1024",
        output_format: str = "png",
    ) -> MediaBytes:
        if output_format != "png":
            raise MediaGenerationError(
                f"mock provider only produces png, got {output_format!r}"
            )
        data = _minimal_png_bytes()
        return MediaBytes(
            kind="image",
            data=data,
            media_format="png",
            report={
                "format": "png",
                "width": 64,
                "height": 64,
                "byte_size": len(data),
                "mock": True,
            },
        )

    def synthesize_speech(
        self,
        text: str,
        *,
        voice: str = "alloy",
        response_format: str = "mp3",
    ) -> MediaBytes:
        if response_format != "wav":
            raise MediaGenerationError(
                f"mock provider only produces wav, got {response_format!r}"
            )
        data = _minimal_wav_bytes()
        return MediaBytes(
            kind="audio",
            data=data,
            media_format="wav",
            report={
                "format": "wav",
                "sample_rate": 8000,
                "seconds": 1.0,
                "byte_size": len(data),
                "mock": True,
            },
        )


# ---------------------------------------------------------------------------
# OpenAI-compatible provider (stdlib urllib transport)
# ---------------------------------------------------------------------------


class OpenAICompatibleMediaProvider:
    """HTTP provider for OpenAI-compatible ``/images/generations`` and
    ``/audio/speech`` endpoints.

    The API key is resolved from ``credential_store`` through
    ``config.credential_ref`` at call time. With no store configured, or no
    secret behind the reference, calls raise
    :class:`MediaGenerationNotConfigured`.
    """

    def __init__(
        self,
        config: MediaProviderConfig,
        *,
        credential_store: Any | None = None,
    ) -> None:
        self._config = config
        self._credential_store = credential_store

    @property
    def provider_name(self) -> str:
        return self._config.name

    def capabilities(self) -> tuple[str, ...]:
        return ("image", "audio")

    def generate_video(
        self,
        prompt: str,
        *,
        duration_seconds: float = 5.0,
    ) -> MediaBytes:
        # Interface only in R9 (see MediaGenerationProvider): no leg is wired.
        raise MediaVideoNotImplemented(
            "video generation is not implemented (R9 keeps the interface "
            "and docs only); no provider leg is wired"
        )

    def _api_key(self) -> str:
        config = self._config
        ref = config.credential_ref
        if not ref:
            raise MediaGenerationNotConfigured(
                f"media provider {config.name!r} is not configured: no "
                "credential reference is set on the provider config"
            )
        store = self._credential_store
        if store is None:
            raise MediaGenerationNotConfigured(
                f"media provider {config.name!r} is not configured: no "
                f"credential store is available to resolve {ref!r}"
            )
        try:
            secret = store.get(ref)
        except Exception as exc:
            raise MediaGenerationNotConfigured(
                f"media provider {config.name!r} is not configured: "
                f"credential lookup failed ({type(exc).__name__})"
            ) from exc
        if not secret:
            raise MediaGenerationNotConfigured(
                f"media provider {config.name!r} is not configured: no "
                f"secret behind credential reference {ref!r}"
            )
        return str(secret)

    def _post_json(
        self, path: str, payload: Mapping[str, Any]
    ) -> urllib.request.addinfourl:
        config = self._config
        body = json.dumps(dict(payload)).encode("utf-8")
        request = urllib.request.Request(
            config.base_url + path,
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._api_key()}",
                "User-Agent": "znagent-media-generation/1.0",
            },
        )
        try:
            return urllib.request.urlopen(
                request, timeout=config.timeout_seconds
            )
        except urllib.error.HTTPError as exc:
            raise MediaGenerationError(
                f"media provider {config.name!r} request to {path} failed: "
                f"HTTP {exc.code}"
            ) from exc
        except urllib.error.URLError as exc:
            raise MediaGenerationError(
                f"media provider {config.name!r} request to {path} failed: "
                f"transport error ({exc.reason})"
            ) from exc

    @staticmethod
    def _read_json_response(
        response: urllib.request.addinfourl, *, what: str
    ) -> Any:
        raw = response.read(MAX_IMAGE_BYTES + 1_048_576)
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise MediaGenerationError(
                f"media provider {what} returned an unreadable JSON payload"
            ) from exc

    def generate_image(
        self,
        prompt: str,
        *,
        size: str = "1024x1024",
        output_format: str = "png",
    ) -> MediaBytes:
        prompt = str(prompt or "").strip()
        if not prompt:
            raise MediaGenerationError("image prompt must not be empty")
        response = self._post_json(
            "/images/generations",
            {
                "model": self._config.image_model,
                "prompt": prompt,
                "size": size,
                "response_format": "b64_json",
            },
        )
        payload = self._read_json_response(response, what="images/generations")
        try:
            b64 = payload["data"][0]["b64_json"]
        except (KeyError, IndexError, TypeError) as exc:
            raise MediaGenerationError(
                "media provider images/generations response has no "
                "data[0].b64_json"
            ) from exc
        try:
            data = base64.b64decode(b64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise MediaGenerationError(
                "media provider images/generations returned invalid base64"
            ) from exc
        return MediaBytes(
            kind="image",
            data=data,
            media_format=output_format,
            report={
                "format": output_format,
                "byte_size": len(data),
                "model": self._config.image_model,
                "size": size,
            },
        )

    def synthesize_speech(
        self,
        text: str,
        *,
        voice: str = "alloy",
        response_format: str = "mp3",
    ) -> MediaBytes:
        text = str(text or "").strip()
        if not text:
            raise MediaGenerationError("tts text must not be empty")
        response = self._post_json(
            "/audio/speech",
            {
                "model": self._config.tts_model,
                "input": text,
                "voice": voice,
                "response_format": response_format,
            },
        )
        data = response.read(MAX_AUDIO_BYTES + 1)
        if len(data) > MAX_AUDIO_BYTES:
            raise MediaGenerationError(
                f"tts audio response exceeds the {MAX_AUDIO_BYTES}-byte bound"
            )
        return MediaBytes(
            kind="audio",
            data=data,
            media_format=response_format,
            report={
                "format": response_format,
                "byte_size": len(data),
                "model": self._config.tts_model,
                "voice": voice,
            },
        )

# ---------------------------------------------------------------------------
# Output path safety (same contract as the document-artifact connector)
# ---------------------------------------------------------------------------


def _validate_output_name(name: Any, expected_suffix: str) -> str:
    """A plain filename only: no separators, no traversal, right suffix."""
    text = str(name or "").strip()
    if not text:
        raise MediaGenerationError("output_name must not be empty")
    if len(text) > MAX_FILENAME_LEN:
        raise MediaGenerationError(
            f"output_name is too long ({len(text)} > {MAX_FILENAME_LEN})"
        )
    if "/" in text or "\\" in text or text in (".", ".."):
        raise MediaGenerationError(
            f"output_name must be a plain filename, got {text!r}"
        )
    if ".." in text:
        raise MediaGenerationError(
            f"output_name must not contain '..', got {text!r}"
        )
    if "\x00" in text:
        raise MediaGenerationError("output_name must not contain NUL bytes")
    lowered = text.lower()
    if lowered.endswith(expected_suffix):
        return text
    if "." in Path(text).name and Path(text).suffix:
        raise MediaGenerationError(
            f"output_name must end with {expected_suffix}, got {text!r}"
        )
    return text + expected_suffix


def _resolve_target(output_dir: Any, output_name: str) -> Path:
    root = Path(str(output_dir or "")).expanduser()
    if not str(output_dir or "").strip():
        raise MediaGenerationError("no output directory configured")
    if not root.is_dir():
        raise MediaGenerationError(
            f"output directory does not exist or is not a directory: {root}"
        )
    resolved_root = root.resolve()
    target = (resolved_root / output_name).resolve()
    try:
        target.relative_to(resolved_root)
    except ValueError:
        raise MediaGenerationError(
            f"output_name {output_name!r} escapes the output directory"
        ) from None
    return target


def _atomic_write_bytes(target: Path, data: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=str(target.parent), prefix=".zn-media-", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.replace(tmp_name, target)
    except OSError as exc:
        with suppress(OSError):
            os.unlink(tmp_name)
        raise MediaGenerationError(
            f"cannot write media artifact to {target}: {exc}"
        ) from exc


# ---------------------------------------------------------------------------
# Input validation (explicit failures, never silent defaults)
# ---------------------------------------------------------------------------


def _require_text(mapping: Mapping[str, Any], key: str, *, what: str) -> str:
    value = mapping.get(key)
    text = str(value or "").strip()
    if not text:
        raise MediaGenerationError(f"{what} requires a non-empty '{key}'")
    return text


def _bounded_text(text: str, *, what: str, limit: int) -> str:
    if len(text) > limit:
        raise MediaGenerationError(
            f"{what} is too long ({len(text)} > {limit} characters)"
        )
    return text


def _require_output_dir(args: Mapping[str, Any], default: str | None) -> str:
    raw = args.get("output_dir") or default
    if not str(raw or "").strip():
        raise MediaGenerationError(
            "no output directory: pass 'output_dir' or attach with one"
        )
    return str(raw)


def _validate_image_args(args: Mapping[str, Any]) -> dict[str, Any]:
    prompt = _bounded_text(
        _require_text(args, "prompt", what="media.generate_image"),
        what="image prompt",
        limit=MAX_PROMPT_CHARS,
    )
    size = str(args.get("size") or "1024x1024").strip()
    if size not in IMAGE_SIZES:
        raise MediaGenerationError(
            f"image size must be one of {IMAGE_SIZES}, got {size!r}"
        )
    output_format = str(args.get("format") or "png").strip().lower()
    if output_format not in IMAGE_FORMATS:
        raise MediaGenerationError(
            f"image format must be one of {IMAGE_FORMATS}, "
            f"got {output_format!r}"
        )
    return {"prompt": prompt, "size": size, "format": output_format}


def _validate_tts_args(args: Mapping[str, Any]) -> dict[str, Any]:
    text = _bounded_text(
        _require_text(args, "text", what="media.generate_tts"),
        what="tts text",
        limit=MAX_TTS_CHARS,
    )
    voice = str(args.get("voice") or "alloy").strip()
    if not voice or len(voice) > 64:
        raise MediaGenerationError("tts voice must be 1-64 characters")
    response_format = str(args.get("format") or "mp3").strip().lower()
    if response_format not in AUDIO_FORMATS:
        raise MediaGenerationError(
            f"tts format must be one of {AUDIO_FORMATS}, "
            f"got {response_format!r}"
        )
    return {"text": text, "voice": voice, "format": response_format}


# ---------------------------------------------------------------------------
# Read-back verification: format bytes are honest, not placeholders.
# ---------------------------------------------------------------------------


def verify_image_bytes(
    data: bytes, expected: Mapping[str, Any]
) -> dict[str, Any]:
    """Verify image bytes by format magic (and PNG structure when png)."""
    fmt = str(expected.get("format") or "png").lower()
    if not data:
        raise MediaGenerationError("image bytes are empty")
    observed: dict[str, Any] = {"format": fmt, "byte_size": len(data)}
    if fmt == "png":
        if not data.startswith(PNG_MAGIC):
            raise MediaGenerationError("image bytes are not a PNG")
        try:
            width, height = struct.unpack(">II", data[16:24])
        except struct.error as exc:
            raise MediaGenerationError(
                "PNG is truncated before the IHDR dimensions"
            ) from exc
        if width == 0 or height == 0 or width > 16384 or height > 16384:
            raise MediaGenerationError(
                f"PNG dimensions are implausible: {width}x{height}"
            )
        observed.update({"width": width, "height": height})
    elif fmt == "jpeg":
        if not data.startswith(JPEG_MAGIC):
            raise MediaGenerationError("image bytes are not a JPEG")
    elif fmt == "webp":
        if not (
            data.startswith(RIFF_MAGIC) and data[8:12] == WEBP_MAGIC
        ):
            raise MediaGenerationError("image bytes are not a WebP")
    else:
        raise MediaGenerationError(f"unknown image format {fmt!r}")
    return observed


def verify_audio_bytes(
    data: bytes, expected: Mapping[str, Any]
) -> dict[str, Any]:
    """Verify audio bytes by container magic (structural for WAV)."""
    fmt = str(expected.get("format") or "mp3").lower()
    if not data:
        raise MediaGenerationError("audio bytes are empty")
    observed: dict[str, Any] = {"format": fmt, "byte_size": len(data)}
    if fmt == "wav":
        if not (data.startswith(RIFF_MAGIC) and data[8:12] == b"WAVE"):
            raise MediaGenerationError("audio bytes are not a WAV")
    elif fmt == "mp3":
        if not (
            data.startswith(ID3_MAGIC)
            or data[:2] in (MP3_FRAME_SYNC, MP3_FRAME_SYNC_ALT,
                            MP3_FRAME_SYNC_ALT2)
        ):
            raise MediaGenerationError(
                "audio bytes are not MP3 (no ID3 tag or frame sync)"
            )
    elif fmt == "flac":
        if not data.startswith(b"fLaC"):
            raise MediaGenerationError("audio bytes are not FLAC")
    elif fmt == "opus":
        if not data.startswith(b"OggS"):
            raise MediaGenerationError("audio bytes are not Ogg/Opus")
    elif fmt in ("aac", "pcm"):
        # AAC (ADTS) and raw PCM have no reliable short magic; the byte
        # bound and the provider's declared format are the honest signal.
        observed["magic_check"] = "skipped"
    else:
        raise MediaGenerationError(f"unknown audio format {fmt!r}")
    return observed


class GeneratedMedia:
    """A generated media file plus the structural report used for verification."""

    def __init__(
        self, path: Path, *, report: Mapping[str, Any], byte_size: int
    ) -> None:
        self.path = path
        self.report = dict(report)
        self.byte_size = byte_size

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "byte_size": self.byte_size,
            "report": dict(self.report),
        }


def _write_media_bytes(
    media: MediaBytes,
    output_dir: str,
    output_name: str,
    *,
    bound: int,
) -> GeneratedMedia:
    if len(media.data) > bound:
        raise MediaGenerationError(
            f"generated {media.kind} exceeds the {bound}-byte bound"
        )
    target = _resolve_target(output_dir, output_name)
    _atomic_write_bytes(target, media.data)
    return GeneratedMedia(
        target,
        report={**dict(media.report), "path": str(target)},
        byte_size=len(media.data),
    )


def write_image(
    media: MediaBytes, output_dir: str, output_name: str
) -> GeneratedMedia:
    """Validate the name, write provider image bytes, verify the format."""
    if media.kind != "image":
        raise MediaGenerationError(
            f"write_image needs image bytes, got kind {media.kind!r}"
        )
    try:
        suffix = IMAGE_SUFFIX[media.media_format]
    except KeyError:
        raise MediaGenerationError(
            f"unknown image format {media.media_format!r}"
        ) from None
    name = _validate_output_name(output_name, suffix)
    verify_image_bytes(media.data, {"format": media.media_format})
    return _write_media_bytes(media, output_dir, name, bound=MAX_IMAGE_BYTES)


def write_tts_audio(
    media: MediaBytes, output_dir: str, output_name: str
) -> GeneratedMedia:
    """Validate the name, write provider audio bytes, verify the format."""
    if media.kind != "audio":
        raise MediaGenerationError(
            f"write_tts_audio needs audio bytes, got kind {media.kind!r}"
        )
    try:
        suffix = AUDIO_SUFFIX[media.media_format]
    except KeyError:
        raise MediaGenerationError(
            f"unknown audio format {media.media_format!r}"
        ) from None
    name = _validate_output_name(output_name, suffix)
    verify_audio_bytes(media.data, {"format": media.media_format})
    return _write_media_bytes(media, output_dir, name, bound=MAX_AUDIO_BYTES)


def _provider_or_raise(provider: Any) -> MediaGenerationProvider:
    if provider is None:
        raise MediaGenerationNotConfigured(
            "media generation is not configured: no provider was attached "
            "(attach with a provider, e.g. OpenAICompatibleMediaProvider)"
        )
    return provider

# ---------------------------------------------------------------------------
# Fabric/Body attachment (R8 shape: approval-gated writes)
# ---------------------------------------------------------------------------


def _body_kind(action_id: str) -> str:
    digest = hashlib.sha256(action_id.encode("utf-8")).hexdigest()[:24]
    return f"zn_rest_write_{digest}"


class MediaGenerationAttachment:
    """Handle returned by :func:`attach_media_generation_tools`; call detach()."""

    def __init__(
        self,
        fabric: ActionFabricRegistry,
        body: NativeBody,
        kinds: list[str],
        action_ids: list[str],
    ) -> None:
        self._fabric = fabric
        self._body = body
        self._kinds = kinds
        self._action_ids = action_ids
        self._detached = False

    @property
    def action_ids(self) -> tuple[str, ...]:
        return tuple(self._action_ids)

    def detach(self) -> None:
        if self._detached:
            return
        self._detached = True
        for action_id in self._action_ids:
            self._fabric.unregister(action_id)
        for kind in self._kinds:
            self._body.unregister_external_write_handler(kind)


def _result_data(
    tool: str, artifact: GeneratedMedia, verification: Mapping[str, Any]
) -> dict[str, Any]:
    return {
        "provider_id": PROVIDER_ID,
        "tool": tool,
        "path": str(artifact.path),
        "byte_size": artifact.byte_size,
        "verification": {
            "format": tool.rsplit(".", 1)[-1],
            "expected": dict(artifact.report),
            "observed": dict(verification),
        },
        "untrusted_external_evidence": False,
    }


def _probe(provider: Any, default_output_dir: str | None):
    def probe(item) -> ActionAvailability:
        if not _probe_output_ok(default_output_dir):
            return ActionAvailability(
                item.action_id,
                "unavailable",
                reason=(
                    "no output directory configured: attach with output_dir "
                    "or pass 'output_dir' per call"
                ),
            )
        if provider is None:
            return ActionAvailability(
                item.action_id,
                "unavailable",
                reason=(
                    "no media provider attached: attach with a provider "
                    "(media generation is not configured)"
                ),
            )
        return ActionAvailability(
            item.action_id,
            "available",
            reason="media provider and output directory configured",
            evidence={"output_dir": default_output_dir},
        )

    return probe


def _probe_output_ok(default_output_dir: str | None) -> bool:
    return bool(
        default_output_dir and Path(default_output_dir).is_dir()
    )


def attach_media_generation_tools(
    fabric: ActionFabricRegistry,
    body: NativeBody,
    *,
    provider: MediaGenerationProvider | None = None,
    output_dir: str | None = None,
) -> MediaGenerationAttachment:
    """Attach the two media-generation tools to a Body/Fabric pair.

    Both tools are approval-gated writes (``approval:production_change``):
    the runtime opens an approval card before dispatch, and a denied or
    undecided generation never calls the provider and never touches the
    disk. Each handler validates its inputs, calls the provider, writes the
    bytes atomically, and read-back-verifies the file before reporting
    success.

    ``provider`` is host configuration (for example an
    :class:`OpenAICompatibleMediaProvider` or the deterministic
    :class:`MockMediaGenerationProvider`); with ``None`` the tools attach
    but report themselves unavailable, and dispatch raises
    :class:`MediaGenerationNotConfigured`.
    """
    prepared: list[tuple[ActionDescriptor, Callable]] = []

    # -- image -------------------------------------------------------------
    def call_generate_image(
        action: BodyAction, started: str
    ) -> BodyActionResult:
        validated = _validate_image_args(action.args)
        output = _require_output_dir(action.args, output_dir)
        active = _provider_or_raise(provider)
        if "image" not in active.capabilities():
            raise MediaGenerationError(
                f"provider {active.provider_name!r} cannot generate images"
            )
        media = active.generate_image(
            validated["prompt"],
            size=validated["size"],
            output_format=validated["format"],
        )
        artifact = write_image(media, output, action.args.get("output_name"))
        verification = verify_image_bytes(
            artifact.path.read_bytes(), {"format": validated["format"]}
        )
        return BodyActionResult(
            action_id=action.action_id,
            kind=action.kind,
            success=True,
            output=json.dumps(
                _result_data("generate_image", artifact, verification),
                ensure_ascii=False,
                indent=2,
            ),
            data=_result_data("generate_image", artifact, verification),
            event_id=action.event_id,
            started_at=started,
            completed_at=utc_now(),
        )

    prepared.append((
        ActionDescriptor(
            action_id=IMAGE_ACTION_ID,
            provider=PROVIDER_ID,
            description=(
                "Generate an image from a text prompt through the attached "
                "media provider (OpenAI-compatible) and save it under "
                "output_dir. Requires user approval before dispatch."
            ),
            body_action_kind=_body_kind(IMAGE_ACTION_ID),
            input_schema={
                "type": "object",
                "required": ["output_name", "prompt"],
                "properties": {
                    "output_name": {
                        "type": "string",
                        "description": (
                            "Plain filename (e.g. 'cover.png'); the right "
                            "suffix is appended when missing"
                        ),
                    },
                    "output_dir": {
                        "type": "string",
                        "description": (
                            "Destination directory; defaults to the attached one"
                        ),
                    },
                    "prompt": {
                        "type": "string",
                        "description": "Image prompt (max 4000 characters)",
                    },
                    "size": {
                        "type": "string",
                        "description": (
                            "One of 256x256, 512x512, 1024x1024, "
                            "1792x1024, 1024x1792"
                        ),
                    },
                    "format": {
                        "type": "string",
                        "description": "One of png, jpeg, webp (default png)",
                    },
                },
                "additionalProperties": False,
            },
            effect_class="reversible_side_effect",
            required_authority=("body_action",),
            sensitivity="external_media",
            preconditions=(
                "media provider configured with a credential",
                "user approved the generation via an approval card",
            ),
            postconditions=(
                "the image file is readable back with the expected format",
            ),
            verification=(
                "independent re-read of the file bytes (format magic)",
            ),
            reversibility="delete the generated file",
            replay_semantics="verify_before_replay",
            tags=(
                "media",
                "image",
                "media_generation_write",
                f"approval:{APPROVAL_KIND}",
            ),
        ),
        call_generate_image,
    ))

    # -- tts ---------------------------------------------------------------
    def call_generate_tts(
        action: BodyAction, started: str
    ) -> BodyActionResult:
        validated = _validate_tts_args(action.args)
        output = _require_output_dir(action.args, output_dir)
        active = _provider_or_raise(provider)
        if "audio" not in active.capabilities():
            raise MediaGenerationError(
                f"provider {active.provider_name!r} cannot synthesize audio"
            )
        media = active.synthesize_speech(
            validated["text"],
            voice=validated["voice"],
            response_format=validated["format"],
        )
        artifact = write_tts_audio(media, output, action.args.get("output_name"))
        verification = verify_audio_bytes(
            artifact.path.read_bytes(), {"format": validated["format"]}
        )
        return BodyActionResult(
            action_id=action.action_id,
            kind=action.kind,
            success=True,
            output=json.dumps(
                _result_data("generate_tts", artifact, verification),
                ensure_ascii=False,
                indent=2,
            ),
            data=_result_data("generate_tts", artifact, verification),
            event_id=action.event_id,
            started_at=started,
            completed_at=utc_now(),
        )

    prepared.append((
        ActionDescriptor(
            action_id=TTS_ACTION_ID,
            provider=PROVIDER_ID,
            description=(
                "Synthesize speech from text through the attached media "
                "provider (OpenAI-compatible) and save the audio under "
                "output_dir. Requires user approval before dispatch."
            ),
            body_action_kind=_body_kind(TTS_ACTION_ID),
            input_schema={
                "type": "object",
                "required": ["output_name", "text"],
                "properties": {
                    "output_name": {
                        "type": "string",
                        "description": (
                            "Plain filename (e.g. 'intro.mp3'); the right "
                            "suffix is appended when missing"
                        ),
                    },
                    "output_dir": {
                        "type": "string",
                        "description": (
                            "Destination directory; defaults to the attached one"
                        ),
                    },
                    "text": {
                        "type": "string",
                        "description": "Text to speak (max 4096 characters)",
                    },
                    "voice": {
                        "type": "string",
                        "description": "Provider voice name (default 'alloy')",
                    },
                    "format": {
                        "type": "string",
                        "description": (
                            "One of mp3, wav, opus, aac, flac, pcm "
                            "(default mp3)"
                        ),
                    },
                },
                "additionalProperties": False,
            },
            effect_class="reversible_side_effect",
            required_authority=("body_action",),
            sensitivity="external_media",
            preconditions=(
                "media provider configured with a credential",
                "user approved the generation via an approval card",
            ),
            postconditions=(
                "the audio file is readable back with the expected format",
            ),
            verification=(
                "independent re-read of the file bytes (container magic)",
            ),
            reversibility="delete the generated file",
            replay_semantics="verify_before_replay",
            tags=(
                "media",
                "audio",
                "tts",
                "media_generation_write",
                f"approval:{APPROVAL_KIND}",
            ),
        ),
        call_generate_tts,
    ))

    # -- registration with rollback ---------------------------------------
    registered: list[ActionDescriptor] = []
    attached_kinds: list[str] = []
    action_ids: list[str] = []
    try:
        for descriptor in [prepared_item[0] for prepared_item in prepared]:
            assert descriptor.body_action_kind is not None
            if descriptor.body_action_kind in body._external_write_handlers:
                raise ValueError("Body extension identifier collision")

        completed_identities: set[str] = set()
        probe = _probe(provider, output_dir)

        for descriptor, handler in prepared:
            kind = descriptor.body_action_kind
            assert kind is not None

            def guarded(
                action: BodyAction,
                started: str,
                *,
                inner=handler,
                action_id=descriptor.action_id,
                tool=descriptor.action_id.split(".")[-1],
            ) -> BodyActionResult:
                identity = mcp_write_replay_identity(
                    provider_id=PROVIDER_ID,
                    tool_name=tool,
                    args=action.args,
                    event_id=action.event_id,
                )
                if identity in completed_identities:
                    raise RuntimeError(
                        "media generation replay refused: this exact "
                        "generation occurrence already completed; re-read "
                        "the file before retrying instead of redispatching"
                    )
                result = inner(action, started)
                completed_identities.add(identity)
                return result

            body.register_external_write_handler(kind, guarded)
            attached_kinds.append(kind)
            fabric.register(descriptor, availability_probe=probe)
            registered.append(descriptor)
            action_ids.append(descriptor.action_id)
    except Exception:
        for descriptor in registered:
            fabric.unregister(descriptor.action_id)
        for kind in attached_kinds:
            body.unregister_external_write_handler(kind)
        raise
    return MediaGenerationAttachment(fabric, body, attached_kinds, action_ids)


# ---------------------------------------------------------------------------
# Runtime binding: approval scopes + postcondition verifiers
# ---------------------------------------------------------------------------


def _write_scope(action_id: str, default_output_dir: str | None):
    def resolver(args: Mapping[str, Any]) -> tuple[str, str, str]:
        output = str(args.get("output_dir") or default_output_dir or "")
        name = str(args.get("output_name") or "(no name)")
        target = f"{output}/{name}" if output else name
        return (
            "media-file",
            target,
            f"generate {action_id} media {name!r} at {target}",
        )

    return resolver


def _verifier_for(action_id: str) -> Callable[[Path, Mapping[str, Any]], Mapping[str, Any]]:
    if action_id == IMAGE_ACTION_ID:
        return verify_image_bytes
    return verify_audio_bytes


def register_media_generation_runtime(
    runtime: ActionExecutionRuntime,
    *,
    output_dir: str | None = None,
) -> None:
    """Bind approval scopes and postcondition verifiers.

    Canonical scopes keep an ``always_allow`` rule from blessing anything
    beyond the one output file; the verifiers re-read the generated file
    (format magic plus structural checks) so a Body success is never taken
    as proof of the effect.
    """
    for action_id in (IMAGE_ACTION_ID, TTS_ACTION_ID):
        runtime.register_approval_scope(
            action_id, _write_scope(action_id, output_dir)
        )
        verifier = _verifier_for(action_id)

        def observe(
            request: ActionRequest,
            result: BodyActionResult | None,
            *,
            _action_id=action_id,
            _verifier=verifier,
            _default_dir=output_dir,
        ) -> ActionObservation:
            data = dict((result.data or {}) if result is not None else {})
            args = dict(request.args or {})
            output = str(args.get("output_dir") or _default_dir or "")
            name = str(args.get("output_name") or "")
            observed: dict[str, Any] = {"path": f"{output}/{name}"}
            expected = ((data.get("verification") or {}).get("expected")) or {}
            try:
                target = _resolve_target(output, name) if name else None
                if target is not None and target.is_file():
                    observed["reread"] = dict(
                        _verifier(target.read_bytes(), expected)
                    )
                    observed["byte_size"] = target.stat().st_size
            except MediaGenerationError as exc:
                observed["reread_error"] = str(exc)
            return ActionObservation(
                _action_id, "media_generation_reread",
                data={**data, **observed}
            )

        def verify(
            request: ActionRequest,
            observation: ActionObservation,
            result: BodyActionResult | None,
            *,
            _action_id=action_id,
        ) -> ActionVerification:
            data = (observation.data or {})
            reread = data.get("reread")
            if isinstance(reread, dict) and reread:
                return ActionVerification(
                    "verified",
                    f"fresh re-read of the generated file at "
                    f"{data.get('path')} matches the expected media format",
                )
            return ActionVerification(
                "failed",
                f"fresh re-read of {data.get('path')} failed: "
                f"{data.get('reread_error', 'file missing or unreadable')}",
            )

        runtime.register_verification(
            action_id, observe=observe, verify=verify
        )
