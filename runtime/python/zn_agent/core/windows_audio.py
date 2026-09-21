from __future__ import annotations

"""Minimal Windows Core Audio boundary for ZN-owned master-volume actions.

The implementation intentionally stays below Action Fabric and Body policy. It
only opens the current default render endpoint and reads or writes its normalized
master-volume scalar through IAudioEndpointVolume.
"""

import ctypes
import math
import os
import uuid
from contextlib import contextmanager
from typing import Iterator


class WindowsAudioUnavailable(RuntimeError):
    """The current host/session has no usable Windows render-volume endpoint."""


class WindowsAudioError(RuntimeError):
    """A native Core Audio operation failed after the endpoint was available."""


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_uint32),
        ("Data2", ctypes.c_uint16),
        ("Data3", ctypes.c_uint16),
        ("Data4", ctypes.c_ubyte * 8),
    ]

    @classmethod
    def from_text(cls, value: str) -> "_GUID":
        raw = uuid.UUID(value)
        data = raw.bytes_le
        return cls(
            int.from_bytes(data[0:4], "little"),
            int.from_bytes(data[4:6], "little"),
            int.from_bytes(data[6:8], "little"),
            (ctypes.c_ubyte * 8)(*data[8:16]),
        )

_CLSID_MMDEVICE_ENUMERATOR = _GUID.from_text(
    "bcde0395-e52f-467c-8e3d-c4579291692e"
)
_IID_IMMDEVICE_ENUMERATOR = _GUID.from_text(
    "a95664d2-9614-4f35-a746-de8db63617e6"
)
_IID_IAUDIO_ENDPOINT_VOLUME = _GUID.from_text(
    "5cdf2c82-841e-4546-9722-0cf74078229a"
)

_CLSCTX_ALL = 23
_ERENDER = 0
_EMULTIMEDIA = 1
_COINIT_MULTITHREADED = 0x0
_RPC_E_CHANGED_MODE = -2147417850
_HRESULT = ctypes.c_long
_ULONG = ctypes.c_ulong
_DWORD = ctypes.c_ulong
_WIN_FUNCTYPE = getattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE)


def _require_windows() -> None:
    if os.name != "nt":
        raise WindowsAudioUnavailable(
            "Windows Core Audio is available only on Windows"
        )


def _hresult_hex(value: int) -> str:
    return f"0x{int(value) & 0xFFFFFFFF:08X}"


def _raise_hresult(
    value: int,
    operation: str,
    *,
    unavailable: bool = False,
) -> None:
    if int(value) >= 0:
        return
    error_type = WindowsAudioUnavailable if unavailable else WindowsAudioError
    raise error_type(f"{operation} failed with HRESULT {_hresult_hex(value)}")


def _com_method(pointer: ctypes.c_void_p, index: int, restype, *argtypes):
    if not pointer or not pointer.value:
        raise WindowsAudioError("COM interface pointer is null")
    vtable = ctypes.cast(
        pointer,
        ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)),
    ).contents
    address = vtable[index]
    prototype = _WIN_FUNCTYPE(restype, ctypes.c_void_p, *argtypes)
    return prototype(address)

def _release(pointer: ctypes.c_void_p | None) -> None:
    if pointer is None or not pointer.value:
        return
    release = _com_method(pointer, 2, _ULONG)
    release(pointer)


@contextmanager
def _default_render_endpoint_volume() -> Iterator[ctypes.c_void_p]:
    _require_windows()
    ole32 = ctypes.OleDLL("ole32")
    ole32.CoInitializeEx.argtypes = [ctypes.c_void_p, _DWORD]
    ole32.CoInitializeEx.restype = _HRESULT
    ole32.CoUninitialize.argtypes = []
    ole32.CoUninitialize.restype = None
    ole32.CoCreateInstance.argtypes = [
        ctypes.POINTER(_GUID),
        ctypes.c_void_p,
        _DWORD,
        ctypes.POINTER(_GUID),
        ctypes.POINTER(ctypes.c_void_p),
    ]
    ole32.CoCreateInstance.restype = _HRESULT

    init_hr = int(ole32.CoInitializeEx(None, _COINIT_MULTITHREADED))
    initialized_here = init_hr in (0, 1)
    if init_hr < 0 and init_hr != _RPC_E_CHANGED_MODE:
        _raise_hresult(init_hr, "CoInitializeEx", unavailable=True)

    enumerator = ctypes.c_void_p()
    endpoint = ctypes.c_void_p()
    volume = ctypes.c_void_p()
    try:
        hr = int(
            ole32.CoCreateInstance(
                ctypes.byref(_CLSID_MMDEVICE_ENUMERATOR),
                None,
                _CLSCTX_ALL,
                ctypes.byref(_IID_IMMDEVICE_ENUMERATOR),
                ctypes.byref(enumerator),
            )
        )
        _raise_hresult(hr, "CoCreateInstance(MMDeviceEnumerator)", unavailable=True)

        get_default = _com_method(
            enumerator,
            4,
            _HRESULT,
            _DWORD,
            _DWORD,
            ctypes.POINTER(ctypes.c_void_p),
        )

        hr = int(
            get_default(
                enumerator,
                _ERENDER,
                _EMULTIMEDIA,
                ctypes.byref(endpoint),
            )
        )
        _raise_hresult(hr, "GetDefaultAudioEndpoint", unavailable=True)

        activate = _com_method(
            endpoint,
            3,
            _HRESULT,
            ctypes.POINTER(_GUID),
            _DWORD,
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_void_p),
        )
        hr = int(
            activate(
                endpoint,
                ctypes.byref(_IID_IAUDIO_ENDPOINT_VOLUME),
                _CLSCTX_ALL,
                None,
                ctypes.byref(volume),
            )
        )
        _raise_hresult(hr, "IMMDevice.Activate(IAudioEndpointVolume)", unavailable=True)
        yield volume
    finally:
        _release(volume)
        _release(endpoint)
        _release(enumerator)
        if initialized_here:
            ole32.CoUninitialize()


def _read_scalar(volume: ctypes.c_void_p) -> float:
    get_scalar = _com_method(
        volume,
        9,
        _HRESULT,
        ctypes.POINTER(ctypes.c_float),
    )
    scalar = ctypes.c_float()
    hr = int(get_scalar(volume, ctypes.byref(scalar)))
    _raise_hresult(hr, "IAudioEndpointVolume.GetMasterVolumeLevelScalar")
    value = float(scalar.value)
    if not math.isfinite(value) or value < 0.0 or value > 1.0:
        raise WindowsAudioError(
            f"Core Audio returned invalid master-volume scalar: {value!r}"
        )
    return value

def read_default_render_volume_percent() -> float:
    """Return the default multimedia render endpoint volume on a 0..100 scale."""

    with _default_render_endpoint_volume() as volume:
        return round(_read_scalar(volume) * 100.0, 3)


def validate_volume_percent(level_percent: object) -> float:
    """Normalize one explicit 0..100 volume request without clamping."""

    if isinstance(level_percent, bool):
        raise ValueError("level_percent must be a number from 0 through 100")
    try:
        value = float(level_percent)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "level_percent must be a number from 0 through 100"
        ) from exc
    if not math.isfinite(value) or value < 0.0 or value > 100.0:
        raise ValueError("level_percent must be a finite number from 0 through 100")
    return value


def set_default_render_volume_percent(level_percent: object) -> float:
    """Set master volume and return a fresh observed percentage from the endpoint."""

    requested = validate_volume_percent(level_percent)
    with _default_render_endpoint_volume() as volume:
        set_scalar = _com_method(
            volume,
            7,
            _HRESULT,
            ctypes.c_float,
            ctypes.c_void_p,
        )
        hr = int(
            set_scalar(
                volume,
                ctypes.c_float(requested / 100.0),
                None,
            )
        )
        _raise_hresult(hr, "IAudioEndpointVolume.SetMasterVolumeLevelScalar")

    # Reopen the default endpoint instead of trusting dispatch success. This also
    # handles a default-device switch that races the write.
    return read_default_render_volume_percent()
