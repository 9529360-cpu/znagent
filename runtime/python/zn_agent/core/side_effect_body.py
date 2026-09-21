from __future__ import annotations

"""Durable pre-dispatch guard for generic non-replayable body side effects."""

import hashlib
import json
import uuid
from contextlib import closing
from typing import Any

from . import side_effect_attempts
from .body import BodyAction, BodyActionResult
from .file_identity import DEFAULT_MAX_HASH_BYTES, read_text_for_exact_file_identity
from .keyboard_text_body import KeyboardTextBody
from .models import utc_now


class SideEffectAwareBody(KeyboardTextBody):
    """Keep the real KeyboardTextBody contract while guarding generic side effects.

    Pointer clicks and focused keyboard text already own richer resident-level
    non-replayable lifecycles. This body deliberately leaves those contracts
    unchanged. It adds a durable pre-dispatch boundary around generic command
    execution, interactive terminal input, structured fallback input gestures,
    and append-style text writes.

    A ``started`` attempt is committed before dispatch. If the process dies after
    that commit, the next resident refuses the same event/action signature rather
    than guessing whether the outside-world side effect happened. For guarded
    commands, terminal input, and append writes, an ``observed`` dispatch also
    remains replay-blocking if a stale ``native_action`` checkpoint is reconstructed.
    Append recovery may prove current reality; generic commands and terminal input
    remain blocked for an explicit lifecycle decision. No raw command, text,
    environment or other action arguments are copied into the side-effect ledger;
    only a deterministic signature hash and bounded execution metadata are persisted.
    """

    _TABLE = side_effect_attempts.TABLE
    _MAX_COMPLETED_ATTEMPTS = side_effect_attempts.MAX_COMPLETED_ATTEMPTS
    _COMMAND_KINDS = frozenset({"command", "terminal", "shell"})
    _TERMINAL_INPUT_KINDS = frozenset(
        {"terminal_input", "terminal_write", "command_input"}
    )
    _TEXT_WRITE_KINDS = frozenset({"write_text", "write_file"})
    _INPUT_GESTURE_KINDS = frozenset(
        {"pointer_scroll", "pointer_drag", "keyboard_key", "keyboard_chord"}
    )
    _IDENTITY_BOUND_READ_KINDS = frozenset({"read_text", "read_file"})
    _APPEND_KINDS = _TEXT_WRITE_KINDS
    _RECOVERY_STATUSES = frozenset({"verified_effect", "verified_absent"})

    def _read_text(self, action: BodyAction, started: str) -> BodyActionResult:
        expected = action.args.get("expected_file_identity")
        if expected is None:
            return super()._read_text(action, started)

        path = self._path_arg(action.args)
        max_chars = max(1, int(action.args.get("max_chars", 20000)))
        max_bytes = max(
            0,
            int(action.args.get("max_bytes", DEFAULT_MAX_HASH_BYTES)),
        )
        encoding = str(action.args.get("encoding") or "utf-8")
        text, identity, error = read_text_for_exact_file_identity(
            path,
            expected if isinstance(expected, dict) else None,
            max_bytes=max_bytes,
            encoding=encoding,
        )
        if error is not None or text is None:
            return BodyActionResult(
                action_id=action.action_id,
                kind=action.kind,
                success=False,
                data={"path": str(path), "identity_bound": True},
                error=error or "exact file identity could not be read",
                event_id=action.event_id,
                started_at=started,
                completed_at=utc_now(),
            )

        truncated = len(text) > max_chars
        output = text[:max_chars]
        return self._ok(
            action,
            started,
            output=output,
            data={
                "path": str(path),
                "chars": len(text),
                "returned_chars": len(output),
                "truncated": truncated,
                "encoding": encoding,
                "identity_bound": True,
                "content_sha256": str((identity or {}).get("content_sha256") or ""),
            },
        )

    def _record(self, action: BodyAction, result: BodyActionResult) -> None:
        """Keep sensitive input payloads out of generic durable Body history.

        Replay identity is computed from the real pre-dispatch arguments before
        this method runs. The ``native_body_actions.action_json`` row is history,
        not replay authority, so it only needs bounded audit metadata for values
        that commonly carry credentials, interactive secrets, or full file data.

        Interactive stdin is additionally special because PTYs commonly echo what
        was typed. The live caller still receives the real Body result, but the
        durable result row drops output and terminal command text for input actions
        so the same secret is not silently copied back into long-lived Body/Work
        history through terminal echo.
        """

        safe_args = dict(action.args)
        safe_result = result
        changed = False
        if action.kind in self._COMMAND_KINDS and "env" in safe_args:
            raw_env = safe_args.pop("env")
            env_keys = (
                sorted(str(key) for key in raw_env)
                if isinstance(raw_env, dict)
                else []
            )
            safe_args["env_redacted"] = True
            safe_args["env_keys"] = env_keys
            safe_args["env_count"] = len(env_keys)
            changed = True

        if action.kind in self._TERMINAL_INPUT_KINDS:
            source_key = "data" if "data" in safe_args else "input" if "input" in safe_args else None
            if source_key is not None:
                raw_input = safe_args.pop(source_key)
                safe_args["input_redacted"] = True
                safe_args["input_source"] = source_key
                safe_args["input_chars"] = len(str(raw_input))
                changed = True

            safe_data = dict(result.data or {})
            persisted_output = str(result.output or safe_data.get("output") or "")
            safe_data.pop("output", None)
            safe_data.pop("command", None)
            safe_data["terminal_input_output_redacted"] = True
            safe_data["terminal_input_output_chars"] = len(persisted_output)
            safe_result = BodyActionResult(
                action_id=result.action_id,
                kind=result.kind,
                success=result.success,
                output="",
                data=safe_data,
                error=result.error,
                event_id=result.event_id,
                started_at=result.started_at,
                completed_at=result.completed_at,
            )

        if (
            action.kind in self._IDENTITY_BOUND_READ_KINDS
            and "expected_file_identity" in safe_args
        ):
            raw_identity = safe_args.pop("expected_file_identity")
            expected_digest = (
                str(raw_identity.get("content_sha256") or "")
                if isinstance(raw_identity, dict)
                else ""
            )
            safe_args["expected_file_identity_bound"] = True
            if expected_digest:
                safe_args["expected_content_sha256"] = expected_digest
            safe_data = dict(safe_result.data or {})
            persisted_output = str(safe_result.output or "")
            safe_data["read_text_output_redacted"] = True
            safe_data["read_text_output_chars"] = len(persisted_output)
            safe_result = BodyActionResult(
                action_id=safe_result.action_id,
                kind=safe_result.kind,
                success=safe_result.success,
                output="",
                data=safe_data,
                error=safe_result.error,
                event_id=safe_result.event_id,
                started_at=safe_result.started_at,
                completed_at=safe_result.completed_at,
            )
            changed = True

        if action.kind in self._TEXT_WRITE_KINDS:
            source_key = "content" if "content" in safe_args else "text" if "text" in safe_args else None
            if source_key is not None:
                raw_content = safe_args.pop(source_key)
                safe_args["content_redacted"] = True
                safe_args["content_source"] = source_key
                safe_args["content_chars"] = len(str(raw_content))
                changed = True

        if changed:
            action = BodyAction(
                action_id=action.action_id,
                kind=action.kind,
                args=safe_args,
                event_id=action.event_id,
                created_at=action.created_at,
            )
        super()._record(action, safe_result)

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
            # A normal exception cannot establish that a guarded side effect
            # produced no outside-world effect. Keep the durable attempt in
            # ``started`` state and return uncertainty so the resident
            # investigates rather than terminalizing or replaying the movement.
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
        if (
            kind in cls._COMMAND_KINDS
            or kind in cls._TERMINAL_INPUT_KINDS
            or kind in cls._INPUT_GESTURE_KINDS
        ):
            return True
        if kind == "pointer_click":
            return str(args.get("button") or "left").strip().lower() in {"right", "middle"}
        return kind in cls._APPEND_KINDS and bool(args.get("append", False))

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

        A ``started`` attempt has no durable dispatch result. An append attempt
        may also be ``observed`` while a stale ``native_action`` checkpoint remains
        after a crash. Exact read-only append recovery may close either state
        without replay. Existing dispatch completion metadata is preserved.

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
