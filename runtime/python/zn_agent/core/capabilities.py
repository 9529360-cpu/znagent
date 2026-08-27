from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Callable, Protocol

from .models import AgentEvent, CapabilityResult, WorkingState
from .side_effect_journal import ResidentSideEffectJournal


class LocalCapability(Protocol):
    name: str
    priority: int
    replay_safe: bool

    def match(self, event: AgentEvent) -> float: ...

    def execute(self, event: AgentEvent, state: WorkingState) -> CapabilityResult: ...


@dataclass(slots=True)
class CallableCapability:
    """Small zero-token capability backed by normal program code.

    The matcher is deliberately deterministic. Learned procedures can later be
    compiled into capabilities of this shape instead of being replayed as long
    prompt text on every task.

    ``replay_safe`` is deliberately false by default. A compiled procedure may
    touch the outside world, so interruption after its durable execution boundary
    must never cause a blind retry unless the capability explicitly promises that
    repeating the same event is safe.
    """

    name: str
    matcher: Callable[[AgentEvent], float]
    handler: Callable[[AgentEvent, WorkingState], CapabilityResult]
    priority: int = 0
    replay_safe: bool = False

    def match(self, event: AgentEvent) -> float:
        try:
            return max(0.0, min(1.0, float(self.matcher(event))))
        except Exception:
            return 0.0

    def execute(self, event: AgentEvent, state: WorkingState) -> CapabilityResult:
        return self.handler(event, state)


class ExactTaskCapability(CallableCapability):
    """Convenience capability for stable commands/intents learned by the agent."""

    def __init__(
        self,
        *,
        name: str,
        triggers: tuple[str, ...],
        handler: Callable[[AgentEvent, WorkingState], CapabilityResult],
        priority: int = 0,
        replay_safe: bool = False,
    ):
        normalized = {self._normalize(item) for item in triggers if item.strip()}

        def matcher(event: AgentEvent) -> float:
            return 1.0 if self._normalize(event.task) in normalized else 0.0

        super().__init__(
            name=name,
            matcher=matcher,
            handler=handler,
            priority=priority,
            replay_safe=bool(replay_safe),
        )

    @staticmethod
    def _normalize(value: str) -> str:
        return " ".join(str(value or "").strip().lower().split())


class _JournaledCapability:
    """Resident execution wrapper around one registered compiled capability."""

    _STATE_KEY = "capability_execution"

    def __init__(self, capability: LocalCapability, journal: ResidentSideEffectJournal):
        self._capability = capability
        self._journal = journal
        self.name = capability.name
        self.priority = int(getattr(capability, "priority", 0))
        self.replay_safe = bool(getattr(capability, "replay_safe", False))

    def match(self, event: AgentEvent) -> float:
        return self._capability.match(event)

    def execute(self, event: AgentEvent, state: WorkingState) -> CapabilityResult:
        signature_hash = self._journal.signature_hash(
            "capability",
            {
                "event_id": event.event_id,
                "capability_name": self.name,
            },
        )
        current = state.data.get(self._STATE_KEY)
        checkpoint = dict(current) if isinstance(current, dict) else {}
        attempt_id = str(checkpoint.get("attempt_id") or "").strip()
        if (
            str(checkpoint.get("capability_name") or "") != self.name
            or str(checkpoint.get("signature_hash") or "") != signature_hash
        ):
            checkpoint = {}
            attempt_id = ""

        attempt = self._journal.attempt(attempt_id) if attempt_id else None
        if (
            attempt is not None
            and str(attempt.get("event_id") or "") == event.event_id
            and str(attempt.get("signature_hash") or "") == signature_hash
            and str(attempt.get("status") or "") == "observed"
        ):
            raw_result = checkpoint.get("result")
            if isinstance(raw_result, dict):
                return self._result_from_dict(raw_result)
            return self._uncertain_result(
                attempt_id,
                signature_hash,
                "compiled capability dispatch returned before interruption, but its durable result checkpoint is incomplete",
            )

        if attempt is None:
            prior = self._journal.replay_blocking_attempt(event.event_id, signature_hash)
            if prior is not None:
                attempt = prior
                attempt_id = str(prior.get("attempt_id") or "")
            else:
                attempt_id = f"capfx-{uuid.uuid4().hex[:12]}"
                checkpoint = {
                    "attempt_id": attempt_id,
                    "capability_name": self.name,
                    "signature_hash": signature_hash,
                    "replay_safe": self.replay_safe,
                    "status": "started",
                }
                state.data[self._STATE_KEY] = checkpoint
                state.stage = "native_capability"
                state.next_action = self.name
                self._journal.start_with_checkpoint(
                    attempt_id=attempt_id,
                    event_id=event.event_id,
                    kind="capability",
                    signature_hash=signature_hash,
                    state=state,
                )
                attempt = self._journal.attempt(attempt_id)

        if attempt is not None and str(attempt.get("status") or "") == "started":
            if not self.replay_safe and checkpoint.get("status") == "started":
                # A freshly created attempt is allowed to enter the handler once.
                # After restart the same durable marker is reconstructed with no
                # in-memory admission token, so it must fail closed instead.
                checkpoint["status"] = "admitted"
                state.data[self._STATE_KEY] = checkpoint
            elif not self.replay_safe:
                return self._uncertain_result(
                    attempt_id,
                    signature_hash,
                    "compiled capability may already have started before resident interruption; refusing blind replay until current reality proves what happened",
                )

        try:
            result = self._capability.execute(event, state)
        except Exception as exc:
            if not self.replay_safe:
                return self._uncertain_result(
                    attempt_id,
                    signature_hash,
                    "compiled capability ended without a durable result after the non-replayable boundary: "
                    f"{type(exc).__name__}: {exc}; outside-world effect is uncertain",
                )
            result = CapabilityResult(
                success=False,
                error=f"{type(exc).__name__}: {exc}",
            )
        except BaseException:
            # Process interruption intentionally leaves ``started`` durable.
            raise

        checkpoint = {
            "attempt_id": attempt_id,
            "capability_name": self.name,
            "signature_hash": signature_hash,
            "replay_safe": self.replay_safe,
            "status": "observed",
            "result": self._result_dict(result),
        }
        state.data[self._STATE_KEY] = checkpoint
        self._journal.observe_with_checkpoint(
            attempt_id=attempt_id,
            event_id=event.event_id,
            state=state,
            success=result.success,
        )
        return result

    @staticmethod
    def _result_dict(result: CapabilityResult) -> dict:
        return {
            "success": bool(result.success),
            "response": str(result.response or ""),
            "data": dict(result.data or {}),
            "error": result.error,
            "verification_passed": result.verification_passed,
        }

    @staticmethod
    def _result_from_dict(raw: dict) -> CapabilityResult:
        return CapabilityResult(
            success=bool(raw.get("success")),
            response=str(raw.get("response") or ""),
            data=dict(raw.get("data") or {}),
            error=(str(raw.get("error")) if raw.get("error") is not None else None),
            verification_passed=raw.get("verification_passed"),
        )

    @staticmethod
    def _uncertain_result(
        attempt_id: str,
        signature_hash: str,
        error: str,
    ) -> CapabilityResult:
        return CapabilityResult(
            success=False,
            data={
                "side_effect_uncertain": True,
                "replay_blocked": True,
                "side_effect_attempt_id": attempt_id,
                "side_effect_signature": signature_hash[:16],
                "side_effect_kind": "capability",
            },
            error=error,
        )


class CapabilityRegistry:
    def __init__(self, *, match_threshold: float = 0.75):
        self.match_threshold = max(0.0, min(1.0, float(match_threshold)))
        self._capabilities: dict[str, LocalCapability] = {}
        self._journal: ResidentSideEffectJournal | None = None

    def bind_store(self, store) -> None:
        """Bind resident durability without giving capabilities store authority."""
        self._journal = ResidentSideEffectJournal(store)

    def register(self, capability: LocalCapability) -> None:
        name = str(capability.name or "").strip()
        if not name:
            raise ValueError("capability name must not be empty")
        self._capabilities[name] = capability

    def unregister(self, name: str) -> None:
        self._capabilities.pop(name, None)

    def resolve(self, event: AgentEvent) -> tuple[LocalCapability, float] | None:
        ranked: list[tuple[float, int, str, LocalCapability]] = []
        for capability in self._capabilities.values():
            score = capability.match(event)
            if score < self.match_threshold:
                continue
            ranked.append((score, int(getattr(capability, "priority", 0)), capability.name, capability))
        if not ranked:
            return None
        ranked.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
        score, _priority, _name, capability = ranked[0]
        if self._journal is not None:
            capability = _JournaledCapability(capability, self._journal)
        return capability, score

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._capabilities))
