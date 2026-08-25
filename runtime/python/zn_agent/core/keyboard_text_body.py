from __future__ import annotations

"""Bounded real keyboard-text movement for ZN's Windows computer body."""

import hashlib
import platform
from typing import Any

from .body import BodyAction, BodyActionResult, NativeBody
from .models import utc_now


class KeyboardTextBody(NativeBody):
    """Extend the native body with one bounded Unicode text movement.

    This primitive deliberately has no target-selection logic, shortcuts,
    deletion, selection, Enter/Tab, or replay policy. The resident must prove an
    exact focused target before calling it and independently verify the effect.
    """

    MAX_UTF16_UNITS = 512

    def _dispatch(self, action: BodyAction, started: str) -> BodyActionResult:
        if action.kind == "keyboard_text":
            return self._keyboard_text(action, started)
        return super()._dispatch(action, started)

    @classmethod
    def validate_text(cls, value: Any) -> tuple[str, tuple[int, ...]]:
        if not isinstance(value, str):
            raise ValueError("keyboard_text requires an explicit string text argument")
        text = value
        if not text:
            raise ValueError("keyboard_text text must not be empty")
        if any(ord(char) < 0x20 or ord(char) == 0x7F for char in text):
            raise ValueError(
                "keyboard_text currently accepts text characters only; control keys are unsupported"
            )
        try:
            encoded = text.encode("utf-16-le")
        except UnicodeEncodeError as exc:
            raise ValueError("keyboard_text contains an invalid Unicode scalar sequence") from exc
        units = tuple(
            int.from_bytes(encoded[index : index + 2], "little")
            for index in range(0, len(encoded), 2)
        )
        if not units or len(units) > cls.MAX_UTF16_UNITS:
            raise ValueError(
                f"keyboard_text is limited to {cls.MAX_UTF16_UNITS} UTF-16 code units"
            )
        return text, units

    def _keyboard_text(self, action: BodyAction, started: str) -> BodyActionResult:
        raw_text = (
            action.args["text"]
            if "text" in action.args
            else action.args.get("content")
        )
        text, units = self.validate_text(raw_text)
        text_sha256 = hashlib.sha256(text.encode("utf-8")).hexdigest()
        sent, expected = self._send_keyboard_text(text)
        data = {
            "text_chars": len(text),
            "utf16_units": len(units),
            "text_sha256": text_sha256,
            "input_events_expected": int(expected),
            "input_events_sent": int(sent),
        }
        if sent != expected:
            return BodyActionResult(
                action_id=action.action_id,
                kind=action.kind,
                success=False,
                data=data,
                error=(
                    "Windows Unicode keyboard input was rejected or only partially accepted; "
                    "the resident must investigate current text state and must not replay blindly"
                ),
                event_id=action.event_id,
                started_at=started,
                completed_at=utc_now(),
            )
        return self._ok(action, started, data=data)

    def _send_keyboard_text(self, text: str) -> tuple[int, int]:
        if platform.system() != "Windows":
            raise RuntimeError("keyboard_text body is currently supported only on Windows")

        text, units = self.validate_text(text)
        del text

        import ctypes
        from ctypes import wintypes

        ulong_ptr = (
            ctypes.c_ulonglong
            if ctypes.sizeof(ctypes.c_void_p) == 8
            else ctypes.c_ulong
        )

        class KeyboardInput(ctypes.Structure):
            _fields_ = [
                ("wVk", wintypes.WORD),
                ("wScan", wintypes.WORD),
                ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD),
                ("dwExtraInfo", ulong_ptr),
            ]

        class InputUnion(ctypes.Union):
            _fields_ = [("ki", KeyboardInput)]

        class Input(ctypes.Structure):
            _anonymous_ = ("union",)
            _fields_ = [
                ("type", wintypes.DWORD),
                ("union", InputUnion),
            ]

        input_keyboard = 1
        keyeventf_keyup = 0x0002
        keyeventf_unicode = 0x0004
        event_values: list[Input] = []
        for unit in units:
            event_values.append(
                Input(
                    type=input_keyboard,
                    ki=KeyboardInput(0, unit, keyeventf_unicode, 0, 0),
                )
            )
            event_values.append(
                Input(
                    type=input_keyboard,
                    ki=KeyboardInput(
                        0,
                        unit,
                        keyeventf_unicode | keyeventf_keyup,
                        0,
                        0,
                    ),
                )
            )

        events = (Input * len(event_values))(*event_values)
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.SendInput.argtypes = [
            wintypes.UINT,
            ctypes.POINTER(Input),
            ctypes.c_int,
        ]
        user32.SendInput.restype = wintypes.UINT
        sent = int(user32.SendInput(len(events), events, ctypes.sizeof(Input)))
        return sent, len(events)
