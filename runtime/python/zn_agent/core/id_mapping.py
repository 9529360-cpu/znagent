from __future__ import annotations

"""Anti-hallucination ID mapping for structured model outputs (M0-3).

The pain: ZN's parsers used to be extremely strict, and a model asked to
reference a prior record (an old memory, a source, an evidence entry) had to
reproduce its opaque identifier verbatim. Models cannot do that reliably --
they hallucinate IDs, and a strict parser then either rejects a good answer
or, worse, trusts a fabricated one.

The fix: the model never sees, and never outputs, a real identifier.

- Call sites render the candidate records through :class:`IndexedReferences`
  as ordinal indices (``[0]``, ``[1]``, ...) plus a short display label.
  The real IDs stay in code-side memory only.
- The model refers to a record by its index (``"1"``, ``1``, ``"[1]"``).
- :meth:`IndexedReferences.resolve` maps the index back to the real ID.
- Anything that looks like an ID -- a UUID in any common shape, a bare
  32-hex string, or any other non-index value -- is *rejected*, never
  trusted. Even a UUID that happens to equal a real ID is rejected: a
  model outputting IDs means the ID leaked into the prompt, and the
  correct response is to fix the prompt, not to accept the output.

Use with :class:`OutputContract` via its opt-in ``indexed_id_fields``:
extract the payload, call ``resolve_ids`` to swap index refs for real
IDs, then validate the resolved payload. When ``indexed_id_fields`` is
empty (the default), ``resolve_ids`` is a no-op and every existing
contract behaves exactly as before.
"""

import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

__all__ = [
    "IndexedReferences",
    "IdResolution",
    "is_uuid_shaped",
]

_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
_BRACED_UUID_RE = re.compile(
    r"^\{[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\}$"
)
_BARE_HEX32_RE = re.compile(r"^[0-9a-fA-F]{32}$")
_INDEX_RE = re.compile(r"^[0-9]+$")
_BRACKET_INDEX_RE = re.compile(r"^\[\s*([0-9]+)\s*\]$")


def is_uuid_shaped(value: Any) -> bool:
    """Does this value look like a UUID (or a bare 32-hex ID)?

    The check is purely syntactic: it never consults the mapping, so a
    model cannot smuggle an ID past it by guessing a real one.
    """
    if not isinstance(value, str):
        return False
    text = value.strip()
    return bool(
        _UUID_RE.match(text) or _BRACED_UUID_RE.match(text) or _BARE_HEX32_RE.match(text)
    )


@dataclass(frozen=True, slots=True)
class IdResolution:
    """One resolved model reference: exactly one of the two is set."""

    real_id: str | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and self.real_id is not None


@dataclass(frozen=True, slots=True)
class IndexedReferences:
    """Ordinal-index view over prior records for one model call.

    ``entries`` is the ordered list of ``(real_id, label)`` pairs, in the
    order the model sees them. The mapping is frozen at construction: the
    model cannot mutate it, and neither can later code by accident.
    """

    entries: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        seen: set[str] = set()
        for real_id, _label in self.entries:
            if not isinstance(real_id, str) or not real_id.strip():
                raise ValueError("each entry needs a non-empty real_id string")
            if real_id in seen:
                raise ValueError(f"duplicate real_id in index mapping: {real_id!r}")
            seen.add(real_id)

    def __len__(self) -> int:
        return len(self.entries)

    def instruction(self) -> str:
        """Format instruction: indices only, never IDs."""
        return (
            "Refer to entries ONLY by their index numbers "
            f"(0 to {len(self.entries) - 1}). "
            "Never output an ID, UUID, key, or any other identifier: "
            "any ID-looking value will be rejected, not trusted."
        )

    def render(self) -> str:
        """Prompt block: numbered entries, real IDs never shown."""
        lines = [self.instruction()]
        for index, (_real_id, label) in enumerate(self.entries):
            lines.append(f"[{index}] {label}")
        return "\n".join(lines)

    def resolve(self, ref: Any) -> IdResolution:
        """Map one model-output reference back to its real ID.

        Accepted: an int index, a digit string, or a bracketed ``"[n]"``.
        Everything else is rejected -- in particular any UUID-shaped value
        is treated as a hallucinated ID, even if it equals a real one.
        """
        if isinstance(ref, bool):
            return IdResolution(error=f"invalid index reference: {ref!r} (not an index)")
        if isinstance(ref, int):
            index = ref
        elif isinstance(ref, str):
            text = ref.strip()
            if is_uuid_shaped(text):
                return IdResolution(
                    error=(
                        "rejected hallucinated ID: model must reference entries "
                        f"by index, never by ID (got {text!r})"
                    )
                )
            bracket = _BRACKET_INDEX_RE.match(text)
            if bracket is not None:
                index = int(bracket.group(1))
            elif _INDEX_RE.match(text):
                index = int(text)
            else:
                return IdResolution(
                    error=f"invalid index reference: {ref!r} (not an index)"
                )
        else:
            return IdResolution(
                error=f"invalid index reference: {ref!r} (not an index)"
            )
        if index < 0 or index >= len(self.entries):
            return IdResolution(
                error=(
                    f"index out of range: {index} "
                    f"(valid indices are 0 to {len(self.entries) - 1})"
                )
            )
        return IdResolution(real_id=self.entries[index][0])

    def resolve_all(self, refs: Sequence[Any]) -> tuple[list[str], list[str]]:
        """Resolve many refs. Good refs resolve; bad refs are reported.

        Fail-closed per ref: one bad ref never poisons the good ones, and
        a bad ref never yields an ID.
        """
        resolved: list[str] = []
        errors: list[str] = []
        for ref in refs:
            result = self.resolve(ref)
            if result.ok and result.real_id is not None:
                resolved.append(result.real_id)
            else:
                errors.append(result.error or f"invalid index reference: {ref!r}")
        return resolved, errors


def resolve_structured_id_refs(
    payload: Mapping[str, Any],
    *,
    field_mappings: Mapping[str, IndexedReferences],
) -> tuple[dict[str, Any], list[str]]:
    """Swap index refs in a parsed payload for real IDs.

    ``field_mappings`` names the payload fields that hold index refs and
    the mapping for each. A field value may be a single ref or a list of
    refs. On success the field is replaced by the real ID(s). On failure
    the field is left unreplaced and the error is reported -- the caller
    must not use an unresolved field. Returns ``(resolved_payload, errors)``.
    """
    resolved = dict(payload)
    errors: list[str] = []
    for field, mapping in field_mappings.items():
        if field not in resolved:
            continue
        value = resolved[field]
        if isinstance(value, list):
            ids, field_errors = mapping.resolve_all(value)
            if field_errors:
                errors.extend(f"{field}: {err}" for err in field_errors)
            else:
                resolved[field] = ids
        else:
            result = mapping.resolve(value)
            if result.ok and result.real_id is not None:
                resolved[field] = result.real_id
            else:
                errors.append(f"{field}: {result.error or 'invalid index reference'}")
    return resolved, errors
