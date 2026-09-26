from __future__ import annotations

"""User-visible desktop execution mode at the durable Work/event boundary."""

from typing import Any


EXECUTION_MODE_AGENT = "agent"
EXECUTION_MODE_ASK = "ask"
_EXECUTION_MODES = frozenset({EXECUTION_MODE_AGENT, EXECUTION_MODE_ASK})

# These Body movements observe current reality without intentionally changing it.
ASK_READ_ONLY_BODY_ACTIONS = frozenset(
    {
        "sense",
        "inspect_path", "path", "read_text", "read_file", "list_directory", "list_dir",
        "process_state", "process", "pointer_state", "git_state", "git", "git_diff",
        "terminal_poll", "command_poll", "browser_observe", "browser_close",
        "windows_screen_capture", "windows_desktop_scene_capture",
        "automation_controls_list", "automation_control_read",
        "office_session_read", "office_excel_cell_read", "office_word_selection_read",
        "windows_companion_context", "windows_audio_volume_read",
        "windows_display_brightness_read", "windows_network_wifi_read",
    }
)


def normalize_execution_mode(value: Any, *, default: str = EXECUTION_MODE_AGENT) -> str:
    normalized = str(value or "").strip().lower()
    if not normalized:
        normalized = default
    if normalized not in _EXECUTION_MODES:
        raise ValueError("execution_mode must be 'ask' or 'agent'")
    return normalized


def execution_mode_from_payload(payload: Any) -> str:
    if not isinstance(payload, dict):
        return EXECUTION_MODE_AGENT
    return normalize_execution_mode(payload.get("execution_mode"))


def execution_mode_for_event(event: Any) -> str:
    return execution_mode_from_payload(getattr(event, "payload", None))


def event_allows_effects(event: Any) -> bool:
    return execution_mode_for_event(event) == EXECUTION_MODE_AGENT


def body_action_allowed_for_event(event: Any, kind: str) -> bool:
    return body_action_allowed(execution_mode_for_event(event), kind)


def body_action_allowed(mode: str, kind: str) -> bool:
    normalized_mode = normalize_execution_mode(mode)
    if normalized_mode == EXECUTION_MODE_AGENT:
        return True
    return str(kind or "").strip().lower() in ASK_READ_ONLY_BODY_ACTIONS
