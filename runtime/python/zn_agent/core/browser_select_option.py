from __future__ import annotations

"""Provider-neutral validation for one explicit browser select-option request."""

import hashlib
from dataclasses import dataclass
from typing import Any, Mapping


_MAX_OPTION_UTF16_UNITS = 256


class BrowserSelectOptionContractError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class BrowserSelectOptionRequest:
    mode: str
    requested: str
    length: int
    sha256: str
    utf16_units: int

    def __post_init__(self) -> None:
        if self.mode not in {"value", "label"}:
            raise BrowserSelectOptionContractError("unsupported browser select-option mode")


def browser_select_option_request(args: Mapping[str, Any]) -> BrowserSelectOptionRequest:
    """Accept exactly one HTML option value or visible option label."""

    has_value = "value" in args
    has_label = "label" in args
    if has_value == has_label:
        raise BrowserSelectOptionContractError(
            "browser select_option requires exactly one explicit string value or label argument"
        )

    mode = "value" if has_value else "label"
    raw = args.get(mode)
    if not isinstance(raw, str) or not raw:
        raise BrowserSelectOptionContractError(
            f"browser select_option {mode} must be one non-empty explicit string"
        )
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in raw):
        raise BrowserSelectOptionContractError(
            f"browser select_option {mode} must not contain control characters"
        )
    try:
        encoded = raw.encode("utf-16-le")
    except UnicodeEncodeError as exc:
        raise BrowserSelectOptionContractError(
            f"browser select_option {mode} contains an invalid Unicode scalar sequence"
        ) from exc
    units = len(encoded) // 2
    if units > _MAX_OPTION_UTF16_UNITS:
        raise BrowserSelectOptionContractError(
            f"browser select_option {mode} is limited to {_MAX_OPTION_UTF16_UNITS} UTF-16 code units"
        )
    return BrowserSelectOptionRequest(
        mode=mode,
        requested=raw,
        length=len(raw),
        sha256=hashlib.sha256(raw.encode("utf-8")).hexdigest(),
        utf16_units=units,
    )
