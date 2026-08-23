from __future__ import annotations

"""Resident-owned causal learning records grounded in independent verification."""

import hashlib
import json
import sqlite3
from collections.abc import Mapping, Sequence
from contextlib import closing
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Any

from .models import utc_now
from .result_semantics import normalize_action_result

if TYPE_CHECKING:
    from .store import KernelStore

_MAX_VERIFIED_EXPERIENCES = 2048


def _stable_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(_stable_json(value).encode("utf-8")).hexdigest()


def _optional_text_fingerprint(value: Any) -> str | None:
    text = str(value or "").strip()
    return _fingerprint(text) if text else None


def _safe_source(value: str | None) -> str:
    source = str(value or "native").strip().lower()
    if source in {"native", "external-cognition-assisted", "human-assisted"}:
        return source
    return "assisted"


def _safe_expected_outcome(raw: Mapping[str, Any]) -> dict[str, Any]:
    kind = str(raw.get("kind") or "unknown").strip().lower() or "unknown"
    summary: dict[str, Any] = {"kind": kind}
    if kind == "text_equals":
        path = str(raw.get("path") or "").strip()
        summary["target_fingerprint"] = _fingerprint(path) if path else None
        summary["expected_chars"] = max(
            0,
            int(raw.get("expected_chars") or len(str(raw.get("expected_text") or ""))),
        )
        return summary

    if kind == "command":
        command = str(raw.get("command") or "").strip()
        workdir = str(raw.get("workdir") or "").strip()
        try:
            expected_exit_code = int(raw.get("expected_exit_code", 0))
        except (TypeError, ValueError):
            expected_exit_code = 0
        output = raw.get("output_contains")
        if isinstance(output, str):
            output_count = 1 if output else 0
        elif isinstance(output, Sequence) and not isinstance(
            output, (str, bytes, bytearray)
        ):
            output_count = sum(1 for item in output if str(item))
        else:
            output_count = 0
        summary.update(
            {
                "verification_signature_hash": _fingerprint(
                    {"command": command, "workdir": workdir or None}
                )
                if command
                else None,
                "workdir_fingerprint": _fingerprint(workdir) if workdir else None,
                "expected_exit_code": expected_exit_code,
                "required_output_count": output_count,
            }
        )
        return summary

    return summary


def _safe_verification(
    raw: Mapping[str, Any],
    *,
    expected_outcome: Mapping[str, Any],
) -> dict[str, Any]:
    kind = str(raw.get("kind") or "unknown").strip().lower() or "unknown"
    observation_raw = raw.get("observation")
    observation = dict(observation_raw) if isinstance(observation_raw, Mapping) else {}
    summary: dict[str, Any] = {
        "kind": kind,
        "verified": bool(raw.get("verified")),
        "observation_kind": str(observation.get("kind") or "unknown").strip().lower()
        or "unknown",
        "observation_success": bool(observation.get("success")),
    }

    if kind == "text_equals":
        path = str(raw.get("path") or expected_outcome.get("path") or "").strip()
        observed_data_raw = observation.get("data")
        observed_data = (
            dict(observed_data_raw)
            if isinstance(observed_data_raw, Mapping)
            else {}
        )
        summary.update(
            {
                "target_fingerprint": _fingerprint(path) if path else None,
                "expected_chars": max(0, int(raw.get("expected_chars") or 0)),
                "observed_chars": (
                    int(raw.get("observed_chars"))
                    if raw.get("observed_chars") is not None
                    else None
                ),
                "truncated": bool(observed_data.get("truncated", False)),
            }
        )
        return summary

    if kind == "command":
        command = str(expected_outcome.get("command") or "").strip()
        result_features_raw = raw.get("result_features")
        result_features = (
            dict(result_features_raw)
            if isinstance(result_features_raw, Mapping)
            else normalize_action_result(observation, command=command)
        )
        missing = raw.get("missing_output_contains")
        missing_count = (
            len(missing)
            if isinstance(missing, Sequence)
            and not isinstance(missing, (str, bytes, bytearray))
            else 0
        )
        summary.update(
            {
                "expected_exit_code": (
                    int(raw.get("expected_exit_code"))
                    if raw.get("expected_exit_code") is not None
                    else None
                ),
                "observed_exit_code": (
                    int(raw.get("observed_exit_code"))
                    if raw.get("observed_exit_code") is not None
                    else None
                ),
                "missing_output_count": missing_count,
                "result_features": result_features,
            }
        )
        return summary

    return summary


@dataclass(slots=True, frozen=True)
class VerifiedExperience:
    """One privacy-safe causal episode labeled by independent Body observation."""

    experience_id: str
    event_id: str
    source: str
    situation_evidence_fingerprint: str
    goal_fingerprint: str
    gap_fingerprint: str | None
    domains: tuple[str, ...]
    action_kind: str
    action_signature_hash: str
    expected_outcome: dict[str, Any]
    result_features: dict[str, Any]
    verification: dict[str, Any]
    verdict: str
    group_key: str
    created_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["domains"] = list(self.domains)
        return data

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "VerifiedExperience":
        data = dict(raw)
        data["domains"] = tuple(str(item) for item in data.get("domains") or ())
        return cls(**data)


def build_verified_experience(
    *,
    event_id: str,
    goal: str,
    gap: str | None,
    source: str | None,
    domains: Sequence[str],
    situation_evidence_fingerprint: str,
    action_kind: str,
    action_signature_hash: str,
    primary_action_result: Mapping[str, Any] | None,
    primary_command: str | None,
    expected_outcome: Mapping[str, Any] | None,
    verification_result: Mapping[str, Any] | None,
) -> VerifiedExperience | None:
    """Build a learning episode only when an independent observation really occurred."""

    if not isinstance(expected_outcome, Mapping) or not isinstance(
        verification_result, Mapping
    ):
        return None
    kind = str(verification_result.get("kind") or "").strip().lower()
    if kind not in {"text_equals", "command"}:
        return None

    observation_raw = verification_result.get("observation")
    if not isinstance(observation_raw, Mapping):
        return None
    observation = dict(observation_raw)
    observation_id = str(observation.get("action_id") or "").strip()
    primary = dict(primary_action_result or {})
    primary_id = str(primary.get("action_id") or "").strip()
    if not observation_id or (primary_id and observation_id == primary_id):
        return None

    expected = _safe_expected_outcome(expected_outcome)
    result_features = normalize_action_result(primary, command=primary_command)
    verification = _safe_verification(
        verification_result,
        expected_outcome=expected_outcome,
    )

    verifier_result = verification.get("result_features")
    verifier_masked = bool(
        isinstance(verifier_result, Mapping) and verifier_result.get("masked_success")
    )
    verdict = (
        "verified"
        if bool(verification_result.get("verified")) and not verifier_masked
        else "contradicted"
    )
    verification["verified"] = verdict == "verified"

    safe_domains = tuple(
        sorted(
            {
                _fingerprint(str(item).strip())
                for item in domains
                if str(item).strip()
            }
        )
    )
    evidence_fp = str(situation_evidence_fingerprint or "").strip() or _fingerprint({})
    action_kind_safe = str(action_kind or "unknown").strip().lower() or "unknown"
    action_sig = str(action_signature_hash or "").strip() or _fingerprint(
        {"kind": action_kind_safe, "event_id": event_id}
    )
    group_key = _fingerprint(
        {
            "domains": safe_domains,
            "action_kind": action_kind_safe,
            "expected_kind": expected.get("kind"),
            "expected_exit_code": expected.get("expected_exit_code"),
            "effect_class": result_features.get("effect_class"),
            "failure_class": result_features.get("failure_class"),
        }
    )
    experience_id = "vx-" + _fingerprint(
        {
            "event_id": str(event_id),
            "evidence": evidence_fp,
            "action_signature": action_sig,
            "expected": expected,
            "verdict": verdict,
        }
    )[:24]

    return VerifiedExperience(
        experience_id=experience_id,
        event_id=str(event_id),
        source=_safe_source(source),
        situation_evidence_fingerprint=evidence_fp,
        goal_fingerprint=_fingerprint(str(goal or "")),
        gap_fingerprint=_optional_text_fingerprint(gap),
        domains=safe_domains,
        action_kind=action_kind_safe,
        action_signature_hash=action_sig,
        expected_outcome=expected,
        result_features=result_features,
        verification=verification,
        verdict=verdict,
        group_key=group_key,
    )


class VerifiedExperienceStore:
    """Bounded restart-safe episode store sharing the resident kernel SQLite file."""

    def __init__(
        self,
        store: KernelStore,
        *,
        max_records: int = _MAX_VERIFIED_EXPERIENCES,
    ):
        self.path = store.path
        self.max_records = max(1, int(max_records))
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def _init_schema(self) -> None:
        with closing(self._connect()) as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS verified_experiences(
                    experience_id TEXT PRIMARY KEY,
                    event_id TEXT NOT NULL,
                    verdict TEXT NOT NULL,
                    group_key TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    data TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_verified_experiences_event
                    ON verified_experiences(event_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_verified_experiences_verdict
                    ON verified_experiences(verdict, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_verified_experiences_group
                    ON verified_experiences(group_key, created_at DESC);
                """
            )
            conn.commit()

    def record(self, experience: VerifiedExperience) -> bool:
        payload = _stable_json(experience.to_dict())
        with closing(self._connect()) as conn:
            cursor = conn.execute(
                "INSERT OR IGNORE INTO verified_experiences"
                "(experience_id,event_id,verdict,group_key,created_at,data) "
                "VALUES(?,?,?,?,?,?)",
                (
                    experience.experience_id,
                    experience.event_id,
                    experience.verdict,
                    experience.group_key,
                    experience.created_at,
                    payload,
                ),
            )
            self._prune(conn)
            conn.commit()
            return bool(cursor.rowcount)

    def recent(self, limit: int = 100) -> list[VerifiedExperience]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT data FROM verified_experiences "
                "ORDER BY created_at DESC, experience_id DESC LIMIT ?",
                (max(1, int(limit)),),
            ).fetchall()
        return [VerifiedExperience.from_dict(json.loads(row["data"])) for row in rows]

    def for_event(self, event_id: str, limit: int = 100) -> list[VerifiedExperience]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT data FROM verified_experiences WHERE event_id=? "
                "ORDER BY created_at DESC, experience_id DESC LIMIT ?",
                (str(event_id), max(1, int(limit))),
            ).fetchall()
        return [VerifiedExperience.from_dict(json.loads(row["data"])) for row in rows]

    def count(self) -> int:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM verified_experiences"
            ).fetchone()
        return int(row["n"] if row else 0)

    def _prune(self, conn: sqlite3.Connection) -> None:
        rows = conn.execute(
            "SELECT experience_id, verdict, group_key, created_at "
            "FROM verified_experiences ORDER BY created_at DESC, experience_id DESC"
        ).fetchall()
        if len(rows) <= self.max_records:
            return

        keep: list[str] = []
        kept: set[str] = set()

        contradiction_quota = max(1, self.max_records // 4)
        for row in rows:
            if row["verdict"] != "contradicted":
                continue
            experience_id = str(row["experience_id"])
            keep.append(experience_id)
            kept.add(experience_id)
            if len(keep) >= contradiction_quota:
                break

        seen_groups: set[str] = set()
        for row in rows:
            if len(keep) >= self.max_records:
                break
            experience_id = str(row["experience_id"])
            group_key = str(row["group_key"])
            if experience_id in kept or group_key in seen_groups:
                continue
            keep.append(experience_id)
            kept.add(experience_id)
            seen_groups.add(group_key)

        for row in rows:
            if len(keep) >= self.max_records:
                break
            experience_id = str(row["experience_id"])
            if experience_id in kept:
                continue
            keep.append(experience_id)
            kept.add(experience_id)

        placeholders = ",".join("?" for _ in keep)
        conn.execute(
            f"DELETE FROM verified_experiences WHERE experience_id NOT IN ({placeholders})",
            keep,
        )
