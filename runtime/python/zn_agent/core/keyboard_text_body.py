from __future__ import annotations

"""Bounded real keyboard input movements for ZN's Windows computer body."""

import hashlib
import platform
from typing import Any

from .body import BodyAction, BodyActionResult, NativeBody
from .models import utc_now


class KeyboardTextBody(NativeBody):
    """Extend the native body with bounded text, key, and chord movements.

    These primitives never choose a target or claim application-level completion.
    The resident/competence layer must prove the focused target before dispatch and
    independently verify the application effect afterward.
    """

    MAX_UTF16_UNITS = 512
    MAX_CHORD_KEYS = 4
    _KEY_ALIASES = {
        "esc": "escape",
        "return": "enter",
        "control": "ctrl",
        "windows": "win",
        "meta": "win",
        "pgup": "page_up",
        "pgdn": "page_down",
        "pagedown": "page_down",
        "pageup": "page_up",
        "del": "delete",
        "ins": "insert",
    }
    _NAMED_VK = {
        "backspace": 0x08,
        "tab": 0x09,
        "enter": 0x0D,
        "shift": 0x10,
        "ctrl": 0x11,
        "alt": 0x12,
        "pause": 0x13,
        "caps_lock": 0x14,
        "escape": 0x1B,
        "space": 0x20,
        "page_up": 0x21,
        "page_down": 0x22,
        "end": 0x23,
        "home": 0x24,
        "left": 0x25,
        "up": 0x26,
        "right": 0x27,
        "down": 0x28,
        "insert": 0x2D,
        "delete": 0x2E,
        "win": 0x5B,
    }
    _MODIFIER_KEYS = frozenset({"ctrl", "shift", "alt", "win"})
    _EXTENDED_KEYS = frozenset(
        {"page_up", "page_down", "end", "home", "left", "up", "right", "down", "insert", "delete"}
    )

    def _dispatch(self, action: BodyAction, started: str) -> BodyActionResult:
        if action.kind == "keyboard_text":
            return self._keyboard_text(action, started)
        if action.kind == "keyboard_key":
            return self._keyboard_key(action, started)
        if action.kind == "keyboard_chord":
            return self._keyboard_chord(action, started)
        return super()._dispatch(action, started)

    def _record(self, action: BodyAction, result: BodyActionResult) -> None:
        if action.kind != "keyboard_text":
            super()._record(action, result)
            return

        raw_text = (
            action.args["text"]
            if "text" in action.args
            else action.args.get("content")
        )
        safe_args: dict[str, Any] = {"redacted": True}
        if isinstance(raw_text, str):
            safe_args["text_chars"] = len(raw_text)
            try:
                text, units = self.validate_text(raw_text)
            except ValueError:
                pass
            else:
                safe_args.update(
                    {
                        "utf16_units": len(units),
                        "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                    }
                )
        elif raw_text is not None:
            safe_args["text_type"] = type(raw_text).__name__

        super()._record(
            BodyAction(
                action_id=action.action_id,
                kind=action.kind,
                args=safe_args,
                event_id=action.event_id,
                created_at=action.created_at,
            ),
            result,
        )

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

    @classmethod
    def normalize_key(cls, value: Any) -> str:
        if not isinstance(value, str):
            raise ValueError("keyboard key must be a string")
        key = value.strip().lower().replace("-", "_").replace(" ", "_")
        key = cls._KEY_ALIASES.get(key, key)
        if len(key) == 1 and (key.isdigit() or "a" <= key <= "z"):
            return key
        if key.startswith("f") and key[1:].isdigit():
            number = int(key[1:])
            if 1 <= number <= 12:
                return f"f{number}"
        if key not in cls._NAMED_VK:
            raise ValueError(f"unsupported keyboard key: {value}")
        return key

    @classmethod
    def normalize_keyboard_action_args(
        cls,
        kind: str,
        args: dict[str, Any],
    ) -> dict[str, Any]:
        normalized = dict(args)
        action_kind = str(kind or "").strip().lower()
        if action_kind == "keyboard_key":
            normalized["key"] = cls.normalize_key(normalized.get("key"))
            return normalized
        if action_kind == "keyboard_chord":
            normalized["keys"] = list(cls.validate_chord(normalized.get("keys")))
            return normalized
        return normalized

    @classmethod
    def validate_chord(cls, value: Any) -> tuple[str, ...]:
        if not isinstance(value, (list, tuple)):
            raise ValueError("keyboard_chord keys must be a list or tuple")
        keys = tuple(cls.normalize_key(item) for item in value)
        if not keys or len(keys) > cls.MAX_CHORD_KEYS:
            raise ValueError(
                f"keyboard_chord requires 1..{cls.MAX_CHORD_KEYS} keys"
            )
        if len(set(keys)) != len(keys):
            raise ValueError("keyboard_chord keys must not contain duplicates")
        if len(keys) > 1:
            if keys[-1] in cls._MODIFIER_KEYS:
                raise ValueError("keyboard_chord final key must be non-modifier")
            if any(key not in cls._MODIFIER_KEYS for key in keys[:-1]):
                raise ValueError(
                    "keyboard_chord requires modifiers first and one final non-modifier key"
                )
        return keys

    @classmethod
    def _virtual_key(cls, key: str) -> int:
        if len(key) == 1 and "a" <= key <= "z":
            return ord(key.upper())
        if len(key) == 1 and key.isdigit():
            return ord(key)
        if key.startswith("f") and key[1:].isdigit():
            return 0x70 + int(key[1:]) - 1
        return cls._NAMED_VK[key]

    def _keyboard_key(self, action: BodyAction, started: str) -> BodyActionResult:
        normalized = self.normalize_keyboard_action_args(action.kind, action.args)
        return self._keyboard_key_sequence(
            action,
            started,
            (str(normalized["key"]),),
        )

    def _keyboard_chord(self, action: BodyAction, started: str) -> BodyActionResult:
        normalized = self.normalize_keyboard_action_args(action.kind, action.args)
        return self._keyboard_key_sequence(
            action,
            started,
            tuple(str(key) for key in normalized["keys"]),
        )

    def _keyboard_key_sequence(
        self,
        action: BodyAction,
        started: str,
        keys: tuple[str, ...],
    ) -> BodyActionResult:
        held_before = self._keyboard_keys_down(keys)
        base_data = {
            "keys": list(keys),
            "key_count": len(keys),
            "held_before": list(held_before),
            "dispatch_sent": False,
            "side_effect_uncertain": False,
        }
        if held_before:
            return BodyActionResult(
                action_id=action.action_id,
                kind=action.kind,
                success=False,
                data=base_data,
                error=(
                    "keyboard input refused because one or more target keys are already "
                    "physically/logically down; refusing to interfere with current user input"
                ),
                event_id=action.event_id,
                started_at=started,
                completed_at=utc_now(),
            )

        dispatch = dict(self._send_keyboard_keys(keys))
        sent = int(dispatch.get("input_events_sent") or 0)
        expected = int(dispatch.get("input_events_expected") or 0)
        cleanup_sent = int(dispatch.get("cleanup_events_sent") or 0)
        cleanup_expected = int(dispatch.get("cleanup_events_expected") or 0)
        keys_down_after = tuple(
            str(key) for key in (dispatch.get("keys_down_after") or ())
        )
        release_verified = not keys_down_after
        complete_send = expected > 0 and sent == expected
        data = {
            **base_data,
            "input_events_expected": expected,
            "input_events_sent": sent,
            "cleanup_events_expected": cleanup_expected,
            "cleanup_events_sent": cleanup_sent,
            "keys_down_after": list(keys_down_after),
            "key_release_verified": release_verified,
            "dispatch_sent": sent > 0,
            "side_effect_uncertain": bool(sent > 0 and (not complete_send or not release_verified)),
        }
        if not complete_send or not release_verified:
            return BodyActionResult(
                action_id=action.action_id,
                kind=action.kind,
                success=False,
                data=data,
                error=(
                    "Windows keyboard input was rejected, partially accepted, or could not "
                    "prove all injected keys were released; application state must be "
                    "investigated before replay"
                ),
                event_id=action.event_id,
                started_at=started,
                completed_at=utc_now(),
            )
        return self._ok(action, started, data=data)

    def _keyboard_keys_down(self, keys: tuple[str, ...]) -> tuple[str, ...]:
        if platform.system() != "Windows":
            raise RuntimeError("keyboard key body is currently supported only on Windows")

        import ctypes
        from ctypes import wintypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.GetAsyncKeyState.argtypes = [wintypes.INT]
        user32.GetAsyncKeyState.restype = wintypes.SHORT
        return tuple(
            key
            for key in keys
            if int(user32.GetAsyncKeyState(self._virtual_key(key))) & 0x8000
        )

    def _send_keyboard_keys(self, keys: tuple[str, ...]) -> dict[str, Any]:
        if platform.system() != "Windows":
            raise RuntimeError("keyboard key body is currently supported only on Windows")
        if not keys:
            raise ValueError("keyboard key sequence must not be empty")

        import ctypes
        from ctypes import wintypes

        ulong_ptr = (
            ctypes.c_ulonglong
            if ctypes.sizeof(ctypes.c_void_p) == 8
            else ctypes.c_ulong
        )

        class MouseInput(ctypes.Structure):
            _fields_ = [
                ("dx", wintypes.LONG),
                ("dy", wintypes.LONG),
                ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD),
                ("dwExtraInfo", ulong_ptr),
            ]

        class KeyboardInput(ctypes.Structure):
            _fields_ = [
                ("wVk", wintypes.WORD),
                ("wScan", wintypes.WORD),
                ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD),
                ("dwExtraInfo", ulong_ptr),
            ]

        class HardwareInput(ctypes.Structure):
            _fields_ = [
                ("uMsg", wintypes.DWORD),
                ("wParamL", wintypes.WORD),
                ("wParamH", wintypes.WORD),
            ]

        class InputUnion(ctypes.Union):
            _fields_ = [
                ("mi", MouseInput),
                ("ki", KeyboardInput),
                ("hi", HardwareInput),
            ]

        class Input(ctypes.Structure):
            _anonymous_ = ("union",)
            _fields_ = [
                ("type", wintypes.DWORD),
                ("union", InputUnion),
            ]

        input_keyboard = 1
        keyeventf_extendedkey = 0x0001
        keyeventf_keyup = 0x0002
        event_values: list[Input] = []
        for key in keys:
            flags = keyeventf_extendedkey if key in self._EXTENDED_KEYS else 0
            event_values.append(
                Input(
                    type=input_keyboard,
                    ki=KeyboardInput(self._virtual_key(key), 0, flags, 0, 0),
                )
            )
        for key in reversed(keys):
            flags = keyeventf_keyup
            if key in self._EXTENDED_KEYS:
                flags |= keyeventf_extendedkey
            event_values.append(
                Input(
                    type=input_keyboard,
                    ki=KeyboardInput(self._virtual_key(key), 0, flags, 0, 0),
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
        expected = len(events)

        cleanup_sent = 0
        cleanup_expected = 0
        keys_down_after = self._keyboard_keys_down(keys)
        if sent != expected or keys_down_after:
            cleanup_values: list[Input] = []
            for key in reversed(keys):
                flags = keyeventf_keyup
                if key in self._EXTENDED_KEYS:
                    flags |= keyeventf_extendedkey
                cleanup_values.append(
                    Input(
                        type=input_keyboard,
                        ki=KeyboardInput(self._virtual_key(key), 0, flags, 0, 0),
                    )
                )
            cleanup_expected = len(cleanup_values)
            cleanup_events = (Input * cleanup_expected)(*cleanup_values)
            cleanup_sent = int(
                user32.SendInput(
                    cleanup_expected,
                    cleanup_events,
                    ctypes.sizeof(Input),
                )
            )
            keys_down_after = self._keyboard_keys_down(keys)

        return {
            "input_events_sent": sent,
            "input_events_expected": expected,
            "cleanup_events_sent": cleanup_sent,
            "cleanup_events_expected": cleanup_expected,
            "keys_down_after": list(keys_down_after),
        }

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

        class MouseInput(ctypes.Structure):
            _fields_ = [
                ("dx", wintypes.LONG),
                ("dy", wintypes.LONG),
                ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD),
                ("dwExtraInfo", ulong_ptr),
            ]

        class KeyboardInput(ctypes.Structure):
            _fields_ = [
                ("wVk", wintypes.WORD),
                ("wScan", wintypes.WORD),
                ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD),
                ("dwExtraInfo", ulong_ptr),
            ]

        class HardwareInput(ctypes.Structure):
            _fields_ = [
                ("uMsg", wintypes.DWORD),
                ("wParamL", wintypes.WORD),
                ("wParamH", wintypes.WORD),
            ]

        class InputUnion(ctypes.Union):
            # INPUT's size is defined by its largest union member. Including the
            # real MOUSEINPUT and HARDWAREINPUT members is required on Win64;
            # a keyboard-only union would make ctypes.sizeof(INPUT) too small
            # and Windows SendInput rejects the cbSize argument.
            _fields_ = [
                ("mi", MouseInput),
                ("ki", KeyboardInput),
                ("hi", HardwareInput),
            ]

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
