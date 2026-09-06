from __future__ import annotations

"""Strict serialization boundary for delegated Worker context.

Workers receive a small task-scoped projection, never the Resident's whole
transcript, Memory, SelfModel, credentials, or another Worker's internals. The
boundary is recursive and fail-closed so callers cannot bypass it by placing a
sensitive value inside nested evidence or artifact metadata.
"""

import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable, ClassVar


_ALLOWED_CLASSIFICATIONS = frozenset({
    "public",
    "private",
    "local_only",
    "cloud_allowed",
    "cloud_denied",
})
_FORBIDDEN_KEY_PARTS = frozenset({
    "secret",
    "password",
    "passwd",
    "credential",
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "session_token",
    "access_token",
    "refresh_token",
    "transcript",
    "memory",
    "self_model",
    "other_worker",
    "worker_run_id",
    "model_route_id",
})
_SECRET_VALUE_PATTERNS = (
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{16,}"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}"),
)


class WorkerContextBoundaryError(ValueError):
    pass


@dataclass(slots=True)
class _Budget:
    nodes: int = 0


@dataclass(slots=True)
class WorkerContextPack:
    """Bounded, classification-aware projection for one transient WorkerRun."""

    root_goal_summary: str
    work_item_objective: str
    acceptance_criteria: tuple[str, ...]
    plan_version: int
    relevant_evidence: tuple[dict[str, Any], ...]
    artifact_refs: tuple[dict[str, Any], ...]
    tool_scope: tuple[str, ...]
    authority_scope: tuple[str, ...]
    forbidden_actions: tuple[str, ...]
    expected_result_schema: dict[str, Any]
    provenance: dict[str, Any] = field(
        default_factory=lambda: {
            "source": "resident_work_ledger",
            "boundary": "worker_context_pack_v1",
        }
    )
    data_classification: str = "private"

    MAX_SERIALIZED_BYTES: ClassVar[int] = 48 * 1024
    MAX_DEPTH: ClassVar[int] = 6
    MAX_NODES: ClassVar[int] = 256
    MAX_MAPPING_ITEMS: ClassVar[int] = 32
    MAX_SEQUENCE_ITEMS: ClassVar[int] = 32
    MAX_STRING_CHARS: ClassVar[int] = 2048
    classification_hook: ClassVar[Callable[[dict[str, Any], str], str] | None] = None

    @classmethod
    def set_classification_hook(
        cls,
        hook: Callable[[dict[str, Any], str], str] | None,
    ) -> None:
        cls.classification_hook = hook

    def to_dict(self) -> dict[str, Any]:
        raw: dict[str, Any] = {
            "root_goal_summary": self.root_goal_summary,
            "work_item_objective": self.work_item_objective,
            "acceptance_criteria": list(self.acceptance_criteria),
            "plan_version": int(self.plan_version),
            "relevant_evidence": list(self.relevant_evidence),
            "artifact_refs": list(self.artifact_refs),
            "tool_scope": list(self.tool_scope),
            "authority_scope": list(self.authority_scope),
            "forbidden_actions": list(self.forbidden_actions),
            "expected_result_schema": self.expected_result_schema,
            "provenance": self.provenance,
            "data_classification": self.data_classification,
        }
        self._validate_top_level_counts(raw)
        sanitized = self._sanitize(raw, depth=0, budget=_Budget(), path="worker_context_pack")
        assert isinstance(sanitized, dict)

        classification = str(sanitized.get("data_classification") or "").strip()
        if classification not in _ALLOWED_CLASSIFICATIONS:
            raise WorkerContextBoundaryError("WorkerContextPack data classification is invalid")
        hook = type(self).classification_hook
        if hook is not None:
            classification = str(hook(sanitized, classification) or "").strip()
            if classification not in _ALLOWED_CLASSIFICATIONS:
                raise WorkerContextBoundaryError("WorkerContextPack classification hook returned invalid policy")
            sanitized["data_classification"] = classification

        encoded = json.dumps(
            sanitized,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        if len(encoded) > self.MAX_SERIALIZED_BYTES:
            raise WorkerContextBoundaryError("WorkerContextPack exceeds serialized size limit")
        return sanitized

    @classmethod
    def _validate_top_level_counts(cls, raw: dict[str, Any]) -> None:
        limits = {
            "acceptance_criteria": 8,
            "relevant_evidence": 8,
            "artifact_refs": 12,
            "tool_scope": 32,
            "authority_scope": 32,
            "forbidden_actions": 32,
        }
        for key, limit in limits.items():
            value = raw[key]
            if not isinstance(value, list) or len(value) > limit:
                raise WorkerContextBoundaryError(f"WorkerContextPack {key} exceeds item limit")
        if int(raw["plan_version"]) < 1:
            raise WorkerContextBoundaryError("WorkerContextPack plan_version is invalid")

    @classmethod
    def _sanitize(cls, value: Any, *, depth: int, budget: _Budget, path: str) -> Any:
        if depth > cls.MAX_DEPTH:
            raise WorkerContextBoundaryError(f"WorkerContextPack nesting is too deep at {path}")
        budget.nodes += 1
        if budget.nodes > cls.MAX_NODES:
            raise WorkerContextBoundaryError("WorkerContextPack exceeds recursive node limit")

        if value is None or isinstance(value, (bool, int, float)):
            return value
        if isinstance(value, str):
            if len(value) > cls.MAX_STRING_CHARS:
                raise WorkerContextBoundaryError(f"WorkerContextPack string exceeds limit at {path}")
            if any(pattern.search(value) for pattern in _SECRET_VALUE_PATTERNS):
                raise WorkerContextBoundaryError(f"WorkerContextPack secret-like value rejected at {path}")
            return value
        if isinstance(value, dict):
            if len(value) > cls.MAX_MAPPING_ITEMS:
                raise WorkerContextBoundaryError(f"WorkerContextPack mapping exceeds item limit at {path}")
            clean: dict[str, Any] = {}
            for raw_key, item in value.items():
                key = str(raw_key or "").strip()
                if not key or len(key) > 120:
                    raise WorkerContextBoundaryError(f"WorkerContextPack key is invalid at {path}")
                normalized = key.casefold().replace("-", "_")
                if any(part in normalized for part in _FORBIDDEN_KEY_PARTS):
                    raise WorkerContextBoundaryError(f"WorkerContextPack forbidden sensitive key at {path}.{key}")
                clean[key] = cls._sanitize(
                    item,
                    depth=depth + 1,
                    budget=budget,
                    path=f"{path}.{key}",
                )
            return clean
        if isinstance(value, (list, tuple)):
            if len(value) > cls.MAX_SEQUENCE_ITEMS:
                raise WorkerContextBoundaryError(f"WorkerContextPack sequence exceeds item limit at {path}")
            return [
                cls._sanitize(
                    item,
                    depth=depth + 1,
                    budget=budget,
                    path=f"{path}[{index}]",
                )
                for index, item in enumerate(value)
            ]
        raise WorkerContextBoundaryError(
            f"WorkerContextPack contains unsupported value type at {path}: {type(value).__name__}"
        )
