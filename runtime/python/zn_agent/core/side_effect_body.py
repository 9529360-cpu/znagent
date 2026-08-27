from __future__ import annotations

"""Durable pre-dispatch guard for generic non-replayable body side effects."""

import hashlib
import json
import uuid
from contextlib import closing
from typing import Any

from . import side_effect_attempts
from .body import BodyActionResult
from .keyboard_text_body import KeyboardTextBody
from .models import utc_now


class SideEffectAwareBody(KeyboardTextBody):
    """Keep the real KeyboardTextBody contract while guarding generic side effects.

    Pointer clicks and focused keyboard text already own richer resident-level
    non-replayable lifecycles. This body deliberately leaves those contracts
    unchanged. It adds a durable pre-dispatch boundary around generic command
    execution and text-file mutations.

    A ``started`` attempt is committed before dispatch. If the process dies after
    that commit, the next resident refuses the same event/action signature rather
    than guessing whether the outside-world side effect happened. For guarded
    commands and writes, an ``observed`` dispatch also remains replay-blocking if
    a stale ``native_action`` checkpoint is reconstructed. Exact text recovery may
    prove current reality; generic commands remain blocked for an explicit
    lifecycle decision. No raw command, text, environment or other action
    arguments are copied into this ledger; only a deterministic signature hash
    and bounded execution metadata are persisted.
    """

    _TABLE = side_effect_attempts.TABLE
    _MAX_COMPLETED_ATTEMPTS = side_effect_attempts.MAX_COMPLETED_ATTEMPTS
    _COMMAND_KINDS = frozenset({"command", "terminal", "shell"})
    _WRITE_KINDS = frozenset({"write_text", "write_file"})
    _RECOVERY_STATUSES = frozenset({"verified_effect", "verified_absent"})

    def act(
        self,
        kind: str,
        *,
        event_id: str | None = None,
        **args: Any,
    ) -> BodyActionResult:
        normalized_kind = str(kind or "").strip().lower()
        normalized_event = str(event_id or "").strip()
        if not normalized_event or not self._requires_guard(normalized_kind, args):
            return super().act(kind, event_id=event_id, **args)

        signature_hash = self._signature_hash(normalized_kind, args)
        prior = self._replay_blocking_attempt(
            normalized_event,
            signature_hash,
            include_observed=True,
        )
        if prior is not None:
            prior_status = str(prior["status"] or "").strip().lower()
            if prior_status == "observed":
                error = (
                    f"{normalized_kind} dispatch already returned before resident checkpoint "
                    "reconstruction; refusing blind replay until current reality proves what "
                    "happened"
                )
            else:
                error = (
                    f"{normalized_kind} may already have started before resident interruption; "
                    "refusing blind replay until current reality proves what happened"
                )
            return self._uncertain_result(
                normalized_kind,
                normalized_event,
                attempt_id=str(prior["attempt_id"]),
                signature_hash=signature_hash,
                error=error,
            )

        attempt_id = f"sidefx-{uuid.uuid4().hex[:12]}"
        self._start_attempt(
            attempt_id=attempt_id,
            event_id=normalized_event,
            kind=normalized_kind,
            signature_hash=signature_hash,
        )

        try:
            result = super().act(kind, event_id=event_id, **args)
        except Exception as exc:
            # A normal exception cannot establish that a command/write produced
            # no side effect. Keep the durable attempt in ``started`` state and
            # return uncertainty as evidence so the resident investigates rather
            # than terminalizing or replaying the movement.
            return self._uncertain_result(
                normalized_kind,
                normalized_event,
                attempt_id=attempt_id,
                signature_hash=signature_hash,
                error=(
                    "body dispatch ended without a durable result after the non-replayable "
                    f"boundary: {type(exc).__name__}: {exc}; outside-world effect is uncertain"
                ),
            )
        except BaseException:
            # SystemExit/KeyboardInterrupt stand in for process interruption in
            # tests and real shutdown paths. The committed ``started`` marker is
            # intentionally left behind for the next resident.
            raise

        try:
            self._finish_attempt(attempt_id, result)
        except Exception as exc:
            return self._uncertain_result(
                normalized_kind,
                normalized_event,
                attempt_id=attempt_id,
                signature_hash=signature_hash,
                error=(
                    "body dispatch returned but its side-effect attempt could not be durably "
                    f"closed: {type(exc).__name__}: {exc}; outside-world effect is uncertain"
                ),
            )

        result.data = {
            **dict(result.data or {}),
            "side_effect_attempt_id": attempt_id,
            "side_effect_dispatch_observed": True,
        }
        return result

    @classmethod
    def _requires_guard(cls, kind: str, args: dict[str, Any]) -> bool:
        del args
        return kind in cls._COMMAND_KINDS or kind in cls._WRITE_KINDS

    @staticmethod
    def _signature_hash(kind: str, args: dict[str, Any]) -> str:
        # Historical Body identity. Do not normalize this to the compiled-
        # capability signature format: persisted rows depend on these exact bytes.
        encoded = json.dumps(
            {"kind": kind, "args": args},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def _init_schema(self) -> None:
        super()._init_schema()
        with closing(self._connect()) as conn:
            side_effect_attempts.ensure_schema(conn)
            conn.commit()

    def _start_attempt(
        self,
        *,
        attempt_id: str,
        event_id: str,
        kind: str,
        signature_hash: str,
    ) -> None:
        with closing(self._connect()) as conn:
            side_effect_attempts.start_attempt(
                conn,
                attempt_id=attempt_id,
                event_id=event_id,
                kind=kind,
                signature_hash=signature_hash,
            )
            conn.commit()

    def _finish_attempt(self, attempt_id: str, result: BodyActionResult) -> None:
        with closing(self._connect()) as conn:
            changed = side_effect_attempts.observe_started_attempt(
                conn,
                attempt_id=attempt_id,
                completed_at=result.completed_at or utc_now(),
                result_action_id=result.action_id,
                success=result.success,
            )
            if changed != 1:
                raise RuntimeError("side-effect attempt lost its active started record")
            side_effect_attempts.prune_terminal_attempts(
                conn,
                max_completed=self._MAX_COMPLETED_ATTEMPTS,
            )
            conn.commit()

    def resolve_uncertain_attempt(
        self,
        attempt_id: str,
        *,
        event_id: str,
        status: str,
        evidence_action_id: str | None = None,
    ) -> bool:
        """Close one replay-blocking attempt after resident-owned recovery evidence.

        Repeating the same event/attempt/final status is an idempotent
        acknowledgement of a previously committed recovery decision. This closes
        the crash window where the attempt commit succeeds but the resident
        WorkingState transition has not been saved yet. A conflicting final
        status still fails closed and no action arguments are stored here.

        A ``started`` attempt has no durable dispatch result. A write attempt may
        also be ``observed`` while a stale ``native_action`` checkpoint remains
        after a crash. Exact read-only recovery may close either state without
        replay. Existing dispatch completion metadata is preserved.

        This method grants no mutation authority and stores no action arguments.
        ``verified_effect`` means current reality independently satisfies the
        intended effect; ``verified_absent`` means an action-specific recovery
        check proved the pre-dispatch baseline still exists. Lifecycle cancellation
        is intentionally not accepted here because it must be committed atomically
        with the resident event and WorkingState transition.
        """

        normalized_attempt = str(attempt_id or "").strip()
        normalized_event = str(event_id or "").strip()
        normalized_status = str(status or "").strip().lower()
        if (
            not normalized_attempt
            or not normalized_event
            or normalized_status not in self._RECOVERY_STATUSES
        ):
            return False
        evidence_id = str(evidence_action_id or "").strip() or None
        with closing(self._connect()) as conn:
            changed = side_effect_attempts.resolve_attempt(
                conn,
                attempt_id=normalized_attempt,
                event_id=normalized_event,
                status=normalized_status,
                evidence_action_id=evidence_id,
            )
            if changed != 1:
                row = side_effect_attempts.attempt(conn, normalized_attempt)
                conn.rollback()
                return bool(
                    row is not None
                    and str(row["event_id"]) == normalized_event
                    and str(row["status"]) == normalized_status
                )
            side_effect_attempts.prune_terminal_attempts(
                conn,
                max_completed=self._MAX_COMPLETED_ATTEMPTS,
            )
            conn.commit()
            return True

    def _replay_blocking_attempt(
        self,
        event_id: str,
        signature_hash: str,
        *,
        include_observed: bool = False,
    ):
        statuses = ("started", "observed") if include_observed else ("started",)
        with closing(self._connect()) as conn:
            return side_effect_attempts.replay_blocking_attempt(
                conn,
                event_id=event_id,
                signature_hash=signature_hash,
                statuses=statuses,
            )

    def uncertain_attempts(self, event_id: str) -> list[dict[str, Any]]:
        """Return bounded, argument-free uncertainty evidence for one event."""

        normalized = str(event_id or "").strip()
        if not normalized:
            return []
        with closing(self._connect()) as conn:
            rows = side_effect_attempts.event_attempts(
                conn,
                event_id=normalized,
                statuses=("started",),
                limit=32,
            )
        return [dict(row) for row in rows]

    @staticmethod
    def _uncertain_result(
        kind: str,
        event_id: str,
        *,
        attempt_id: str,
        signature_hash: str,
        error: str,
    ) -> BodyActionResult:
        now = utc_now()
        return BodyActionResult(
            action_id=f"guard-{uuid.uuid4().hex[:12]}",
            kind=kind,
            success=False,
            data={
                "side_effect_uncertain": True,
                "replay_blocked": True,
                "side_effect_attempt_id": attempt_id,
                "side_effect_signature": signature_hash[:16],
            },
            error=error,
            event_id=event_id,
            started_at=now,
            completed_at=now,
        )