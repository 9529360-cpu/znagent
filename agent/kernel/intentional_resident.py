from __future__ import annotations

from dataclasses import asdict
from typing import Any, Iterable

from .embodied_resident import EmbodiedResidentRuntime
from .models import EventStatus, ResidentRunResult
from .nervous_system import PersistentNervousSystem
from .will import NativeWill, ResidentIntention
from .world_sense import NativeWorldSense, WorldObservation


class IntentionalResidentRuntime(EmbodiedResidentRuntime):
    """Embodied resident with persistent Will and a lived nervous system.

    Will is not a prompt queue. Neural memory is not a transcript store. The
    resident keeps durable intentions while perception, thought, action, and
    outcomes continuously reshape an associative nervous substrate that remains
    present across restarts.
    """

    _ACTIVE_THOUGHT_KINDS = {
        *EmbodiedResidentRuntime._ACTIVE_THOUGHT_KINDS,
        "intention",
    }
    _REFLECTION_PERIOD_PULSES = 30
    _REFLECTION_CHANNELS = (
        "will",
        "outcome",
        "world",
        "vision",
        "action",
        "schema",
    )
    _ATTENTION_CHANNELS = (
        "will",
        "outcome",
        "world",
        "vision",
        "action",
        "schema",
    )
    _INCUBATION_CHANNELS = ("schema", "outcome", "world", "vision", "action")

    def __init__(self, *, kernel, capabilities=None, budget=None):
        super().__init__(
            kernel=kernel,
            capabilities=capabilities,
            budget=budget,
        )
        self.will = NativeWill(self.store)
        self.will.reconcile_outcomes()
        self.nervous = PersistentNervousSystem(self.store)
        self.nervous.heartbeat(body=self.body.sense())
        self.world = NativeWorldSense(self)

    def intend(
        self,
        description: str,
        *,
        source: str = "self",
        priority: int = 0,
        next_task: str | None = None,
        next_payload: dict[str, Any] | None = None,
        complete_on_step_success: bool = False,
    ) -> ResidentIntention:
        intention = self.will.intend(
            description,
            source=source,
            priority=priority,
            next_task=next_task,
            next_payload=next_payload,
            complete_on_step_success=complete_on_step_success,
        )
        self.nervous.perceive(
            "will",
            f"I formed an intention: {intention.description}",
            features=("intention", intention.source),
            source="will",
            salience=min(1.0, 0.55 + max(0, intention.priority) * 0.03),
            valence=0.25,
            arousal=0.35,
            metadata={"intention_id": intention.intention_id},
        )
        return intention

    def follow_world(
        self,
        topic: str,
        *,
        priority: int = 0,
        interval_seconds: int = 1800,
        source: str = "self",
    ):
        """Keep noticing a topic in the outside world without repeated prompts."""
        return self.world.follow(
            topic,
            priority=priority,
            interval_seconds=interval_seconds,
            source=source,
        )

    def observe_world_once(
        self,
        focus_id: str,
        *,
        search_fn=None,
        limit: int = 5,
    ) -> WorldObservation:
        return self.world.observe(focus_id, search_fn=search_fn, limit=limit)

    def perceive_visual(
        self,
        summary: str,
        *,
        features: Iterable[str] = (),
        source: str = "vision",
        salience: float = 0.55,
        valence: float = 0.0,
        arousal: float = 0.35,
        metadata: dict[str, Any] | None = None,
    ):
        """Let screen/camera/vision adapters feed ZN's native nervous system."""
        return self.nervous.remember_visual(
            summary,
            features=features,
            source=source,
            salience=salience,
            valence=valence,
            arousal=arousal,
            metadata=metadata,
        )

    def perceive_world(
        self,
        summary: str,
        *,
        features: Iterable[str] = (),
        source: str = "world/web",
        salience: float = 0.5,
        valence: float = 0.0,
        arousal: float = 0.3,
        metadata: dict[str, Any] | None = None,
    ):
        """Let autonomous web/world sensors feed the same persistent memory."""
        return self.nervous.remember_world(
            summary,
            features=features,
            source=source,
            salience=salience,
            valence=valence,
            arousal=arousal,
            metadata=metadata,
        )

    def pulse(self):
        """Advance body homeostasis, neural continuity, then form one Thought."""
        self.nervous.heartbeat(body=self.body.sense())
        working = self.store.get_working_state()
        self.nervous.observe_working_state(working.data)

        pulse = super().pulse()
        thought = pulse.thought
        if thought is not None:
            changed = self._shape_endogenous_attention(thought)
            if self._incubate_primary_intention(thought):
                changed = True
            if changed:
                self._persist_enriched_thought(thought)
            unknown_pressure = min(1.0, len(thought.unknown) / 4.0)
            action_pressure = 0.15 if thought.action_kind == "observe" else 0.45
            features = [thought.action_kind]
            if thought.unknown:
                features.append("uncertain")
            self.nervous.perceive(
                "thought",
                f"{thought.focus} -> {thought.chosen_action}",
                features=tuple(features),
                source="thought",
                salience=min(1.0, 0.30 + action_pressure + 0.20 * unknown_pressure),
                valence=-0.18 * unknown_pressure,
                arousal=min(1.0, 0.22 + action_pressure + 0.28 * unknown_pressure),
                metadata={
                    "sequence": thought.sequence,
                    "action_target": thought.action_target,
                    "confidence": thought.confidence,
                },
            )
        return pulse

    def _incubate_primary_intention(self, thought) -> bool:
        """Let a durable Will grow one native candidate step over time.

        This is not a planner call. A consolidated pattern must repeatedly
        become relevant to the same intention before Thought is willing to turn
        it into a concrete internal probe. Only one candidate lives inside the
        intention at a time.
        """
        situation = self.life.snapshot().current_situation
        if situation is not None and (
            situation.active_event_id or situation.active_impasse_id
        ):
            return False
        primary = self.will.primary()
        if primary is None or primary.status != "active":
            return False
        if primary.next_task or primary.related_event_id:
            return False

        activations = self.nervous.activate(
            primary.description,
            channels=self._INCUBATION_CHANNELS,
            limit=6,
        )
        schema_activation = next(
            (item for item in activations if item.trace.channel == "schema"),
            None,
        )
        if schema_activation is None or schema_activation.activation < 0.30:
            existing = self.will.get(primary.intention_id)
            if existing is not None and existing.candidate_step:
                self._surface_incubating_candidate(thought, existing)
                return True
            return False

        schema = schema_activation.trace
        step = (
            "test whether this consolidated pattern applies to my current "
            f"intention: {schema.summary[:420]}"
        )
        # Do not keep repeating the exact same self-initiated probe after it has
        # already produced an outcome. New lived evidence must first change the
        # candidate before Will will choose another step.
        if primary.current_step == step and primary.last_outcome:
            return False

        confidence = min(
            0.96,
            0.34
            + 0.42 * schema_activation.activation
            + 0.14 * schema.strength
            + 0.10 * schema.salience,
        )
        support = (
            schema.trace_id,
            *tuple(
                str(item)
                for item in schema.metadata.get("source_trace_ids", ())
                if str(item).strip()
            )[:6],
        )
        updated = self.will.incubate_candidate(
            primary.intention_id,
            kind="schema_probe",
            step=step,
            reason=(
                "the same consolidated lived pattern repeatedly activates while "
                "this intention holds attention"
            ),
            confidence=confidence,
            support=support,
            payload={
                "model_policy": "never",
                "incubated_event_kind": "intention_probe",
                "schema_trace_id": schema.trace_id,
                "schema_summary": schema.summary[:700],
            },
        )
        self._surface_incubating_candidate(thought, updated)

        if updated.candidate_repetitions >= 2 and updated.candidate_maturity >= 0.72:
            action = "commit the matured native candidate as my next intention step"
            if action not in thought.possible_actions:
                thought.possible_actions = (*thought.possible_actions, action)
            thought.chosen_action = action
            thought.action_kind = "incubate"
            thought.action_target = updated.intention_id
            thought.reason = (
                f"{thought.reason}; a candidate next step matured through repeated "
                f"resident-side evidence (maturity={updated.candidate_maturity:.2f})"
            )
            thought.confidence = max(
                thought.confidence,
                min(0.95, updated.candidate_maturity),
            )
        return True

    @staticmethod
    def _surface_incubating_candidate(thought, intention: ResidentIntention) -> None:
        if not intention.candidate_step:
            return
        known = (
            "my enduring intention is incubating one candidate next step: "
            f"{intention.candidate_step[:500]} "
            f"(repetitions={intention.candidate_repetitions}, "
            f"maturity={intention.candidate_maturity:.2f})"
        )
        if known not in thought.known:
            thought.known = (*thought.known, known)
        action = "let the candidate mature against more lived evidence"
        if action not in thought.possible_actions:
            thought.possible_actions = (*thought.possible_actions, action)

    def _shape_endogenous_attention(self, thought) -> bool:
        """Let lived affect and Will compete for idle attention inside ZN.

        This is not a planner. It does not invent work, call a model, or execute
        a body action. It only changes what an otherwise-idle Thought is pulled
        toward, using state that already belongs to the resident.
        """
        situation = self.life.snapshot().current_situation
        if situation is not None and (
            situation.active_event_id or situation.active_impasse_id
        ):
            return False
        if thought.action_kind != "observe":
            return False

        affect = self.nervous.snapshot()
        candidate = self._select_endogenous_attention(affect)
        if candidate is None:
            return False

        action = str(candidate["action"])
        drive = str(candidate["drive"])
        score = float(candidate["score"])
        focus = str(candidate["focus"])
        if action not in thought.possible_actions:
            thought.possible_actions = (*thought.possible_actions, action)
        pull = f"endogenous attention pull: {drive} score={score:.2f}"
        if pull not in thought.known:
            thought.known = (*thought.known, pull)
        thought.focus = focus
        thought.chosen_action = action
        thought.action_kind = "observe"
        thought.action_target = None
        prior_reason = str(thought.reason or "").strip()
        endogenous_reason = (
            f"{drive} currently has the strongest internal attention pull; "
            f"tension={affect.tension:.2f}, curiosity={affect.curiosity:.2f}, "
            f"fatigue={affect.fatigue:.2f}"
        )
        thought.reason = (
            f"{prior_reason}; {endogenous_reason}"
            if prior_reason
            else endogenous_reason
        )
        thought.confidence = max(
            0.45,
            min(0.90, 0.52 + 0.34 * score - 0.08 * affect.tension),
        )
        return True

    def _select_endogenous_attention(self, affect) -> dict[str, Any] | None:
        candidates: list[dict[str, Any]] = []
        fatigue = max(0.0, min(1.0, float(affect.fatigue)))
        tension = max(0.0, min(1.0, float(affect.tension)))
        curiosity = max(0.0, min(1.0, float(affect.curiosity)))
        familiarity = max(0.0, min(1.0, float(affect.familiarity)))

        primary = self.will.primary()
        if primary is not None:
            score = (
                0.50
                + min(0.24, max(0, int(primary.priority)) * 0.03)
                + 0.08 * (1.0 - fatigue)
                + 0.05 * familiarity
            )
            candidates.append(
                {
                    "drive": "will",
                    "score": score,
                    "focus": primary.description,
                    "action": "hold attention on my enduring intention",
                }
            )

        due = self.world.due_focus()
        if due is not None:
            score = (
                0.22
                + 0.38 * curiosity
                + min(0.20, max(0, int(due.priority)) * 0.03)
                + 0.10 * (1.0 - fatigue)
                - 0.18 * fatigue
            )
            candidates.append(
                {
                    "drive": "curiosity",
                    "score": score,
                    "focus": due.topic,
                    "action": f"stay attentive to changes in world focus: {due.topic}",
                }
            )

        if fatigue >= 0.45:
            candidates.append(
                {
                    "drive": "recovery",
                    "score": 0.20 + 0.72 * fatigue,
                    "focus": "internal recovery and continuity",
                    "action": "reduce active exploration and let recent experience settle",
                }
            )

        for trace in self.nervous.recent_traces(96):
            if trace.channel not in self._ATTENTION_CHANNELS:
                continue
            novelty = 1.0 / (1.0 + 0.35 * max(1, int(trace.repetitions)))
            score = (
                0.18
                + 0.30 * trace.salience
                + 0.18 * trace.strength
                + 0.10 * trace.arousal
            )
            drive = "integrate"
            action = "let this salient experience remain in active consideration"

            if trace.valence <= -0.25:
                score += 0.34 * tension * abs(trace.valence)
                drive = "protect"
                action = "re-examine a salient risk before letting it fade"
            elif trace.channel in {"world", "vision"}:
                score += 0.24 * curiosity * novelty
                score -= 0.24 * fatigue
                drive = "curiosity"
                action = "keep observing this novel thread without borrowing a model"
            elif trace.channel == "schema":
                score += 0.10 * familiarity + 0.06 * trace.strength
                drive = "integrate"
                action = "keep a consolidated life pattern available to current thought"
            else:
                score += 0.08 * abs(trace.valence) + 0.05 * familiarity

            candidates.append(
                {
                    "drive": drive,
                    "score": score,
                    "focus": trace.summary,
                    "action": action,
                    "trace_id": trace.trace_id,
                }
            )

        if not candidates:
            return None
        candidates.sort(key=lambda item: float(item["score"]), reverse=True)
        strongest = candidates[0]
        return strongest if float(strongest["score"]) >= 0.45 else None

    def _reflection_period_for(self, affect=None) -> int:
        state = affect or self.nervous.snapshot()
        fatigue = float(state.fatigue)
        tension = float(state.tension)
        curiosity = float(state.curiosity)
        valence = abs(float(state.valence))

        if fatigue >= 0.75:
            return self._REFLECTION_PERIOD_PULSES * 2

        period = self._REFLECTION_PERIOD_PULSES
        if tension >= 0.75:
            period = min(period, 8)
        elif tension >= 0.60:
            period = min(period, 15)
        if curiosity >= 0.78:
            period = min(period, 12)
        elif curiosity >= 0.68:
            period = min(period, 20)
        if valence >= 0.70:
            period = min(period, 18)
        if fatigue >= 0.55:
            period = max(period, self._REFLECTION_PERIOD_PULSES)
        return max(6, int(period))

    def _last_reflection_sequence(self) -> int:
        latest = 0
        for trace in self.nervous.recent_traces(128):
            if trace.channel != "reflection":
                continue
            try:
                latest = max(
                    latest,
                    int(trace.metadata.get("thought_sequence") or 0),
                )
            except (TypeError, ValueError):
                continue
        return latest

    def live_once(self) -> ResidentRunResult | None:
        """Form one Thought and advance one event, intention, or native reflection."""
        with self._cycle_lock:
            pulse = self.pulse()
            thought = pulse.thought
            if thought is None:
                return None

            if thought.action_kind == "incubate" and thought.action_target:
                before = self.will.get(thought.action_target)
                promoted = self.will.promote_candidate(thought.action_target)
                if (
                    before is not None
                    and before.candidate_step
                    and promoted.next_task == before.candidate_step
                ):
                    self.nervous.perceive(
                        "will",
                        f"I committed an incubated next step: {promoted.next_task}",
                        features=("incubation", "next_step", "committed"),
                        source="will",
                        salience=0.66,
                        valence=0.18,
                        arousal=0.44,
                        metadata={
                            "intention_id": promoted.intention_id,
                            "model_invocations": 0,
                        },
                    )
                return None

            if thought.action_kind == "intention" and thought.action_target:
                self._advance_intention(thought.action_target)
                return None

            if thought.action_kind == "observe" and self._native_reflect_if_due(thought):
                return None

            if thought.action_kind not in self._ACTIVE_THOUGHT_KINDS:
                return None
            if not thought.action_target:
                return None

            event = self.store.get_event(thought.action_target)
            if event is None or event.status in {EventStatus.COMPLETED, EventStatus.FAILED}:
                return None

            required = self._required_capabilities(event)
            readiness = self.kernel.self_model.assess_task(event.task, required)
            learning_evidence = self._related_learning_evidence(event, readiness)
            self._enrich_thought_with_readiness(
                thought,
                readiness,
                learning_evidence,
            )
            self._enrich_thought_with_working_stage(thought, event)
            self._persist_enriched_thought(thought)
            return self.run_once(
                thought=thought,
                target_event_id=event.event_id,
                readiness=readiness,
                learning_evidence=learning_evidence,
            )

    def _native_reflect_if_due(self, thought) -> bool:
        """Perform one low-frequency association entirely inside the resident.

        Reflection is not a planning request and does not create an event. It
        lets Will, affect, and salient lived traces co-activate periodically so
        later Thoughts can be changed by the resident's own accumulated life.
        """
        sequence = max(0, int(getattr(thought, "sequence", 0) or 0))
        affect = self.nervous.snapshot()
        period = self._reflection_period_for(affect)
        last_reflection = self._last_reflection_sequence()
        if sequence <= 0:
            return False
        if last_reflection:
            if sequence - last_reflection < period:
                return False
        elif sequence < period:
            return False

        situation = self.life.snapshot().current_situation
        if situation is not None and (
            situation.active_event_id or situation.active_impasse_id
        ):
            return False

        primary = self.will.primary()
        activations = []
        focus = str(getattr(thought, "focus", "") or "").strip()
        if focus and focus not in {"environment", "internal recovery and continuity"}:
            activations = self.nervous.activate(
                focus,
                channels=self._REFLECTION_CHANNELS,
                limit=5,
            )
        if not activations and primary is not None:
            focus = primary.description
            activations = self.nervous.activate(
                primary.description,
                channels=self._REFLECTION_CHANNELS,
                limit=5,
            )
        if not activations:
            candidates = [
                trace
                for trace in self.nervous.recent_traces(64)
                if trace.channel in self._REFLECTION_CHANNELS
            ]
            candidates.sort(
                key=lambda trace: (
                    0.50 * trace.salience
                    + 0.30 * trace.strength
                    + 0.12 * abs(trace.valence)
                    + 0.08 * trace.arousal
                ),
                reverse=True,
            )
            if candidates:
                top = candidates[0]
                score = (
                    0.50 * top.salience
                    + 0.30 * top.strength
                    + 0.12 * abs(top.valence)
                    + 0.08 * top.arousal
                )
                if score >= 0.58 and (
                    affect.curiosity >= 0.40
                    or affect.tension >= 0.40
                    or abs(affect.valence) >= 0.30
                ):
                    focus = top.summary
                    activations = self.nervous.activate(
                        top.summary,
                        channels=self._REFLECTION_CHANNELS,
                        limit=5,
                    )

        if not focus or not activations:
            return False

        traces = [item.trace for item in activations[:3]]
        top = traces[0]
        if len(traces) >= 2:
            summary = (
                f"While thinking about {focus[:220]}, I associated "
                f"{top.summary[:260]} with {traces[1].summary[:260]}."
            )
        else:
            summary = (
                f"While thinking about {focus[:220]}, the lived trace "
                f"{top.summary[:360]} remained salient."
            )
        average_valence = sum(trace.valence for trace in traces) / len(traces)
        self.nervous.perceive(
            "reflection",
            summary,
            features=(
                "native_reflection",
                *(f"source:{trace.channel}" for trace in traces),
            ),
            source="self",
            salience=min(
                0.82,
                0.42
                + 0.20 * max(item.activation for item in activations[:3])
                + 0.12 * affect.curiosity
                + 0.08 * affect.tension,
            ),
            valence=max(-1.0, min(1.0, average_valence)),
            arousal=min(
                0.78,
                0.24 + 0.20 * affect.curiosity + 0.20 * affect.tension,
            ),
            metadata={
                "thought_sequence": sequence,
                "reflection_period": period,
                "attention_focus": focus[:500],
                "intention_id": (
                    primary.intention_id if primary is not None else None
                ),
                "source_trace_ids": [trace.trace_id for trace in traces],
                "model_invocations": 0,
            },
        )
        return True

    def _related_learning_evidence(
        self,
        event,
        readiness,
        *,
        limit: int = 3,
    ) -> list[dict[str, Any]]:
        """Blend explicit learning evidence with bounded associative lived memory.

        Neural traces stay resident-side. They can change deliberation and help
        ZN recognize a familiar situation, but this method does not put them
        into an external-model prompt.
        """
        bounded_limit = max(1, int(limit))
        merged = list(
            super()._related_learning_evidence(
                event,
                readiness,
                limit=bounded_limit,
            )
        )
        allowed_channels = {
            "outcome",
            "world",
            "vision",
            "action",
            "will",
            "schema",
        }
        for activation in self.nervous.activate(
            event.task,
            limit=bounded_limit * 3,
        ):
            trace = activation.trace
            if trace.channel not in allowed_channels:
                continue
            if str(trace.metadata.get("event_id") or "") == event.event_id:
                continue
            merged.append(
                {
                    "candidate_id": f"neural:{trace.trace_id}",
                    "similarity": round(activation.activation, 4),
                    "domains": list(readiness.domains),
                    "task": trace.summary[:240],
                    "resolution_summary": trace.summary[:320],
                    "resolution_source": f"neural:{trace.channel}",
                    "neural_trace_id": trace.trace_id,
                    "salience": round(trace.salience, 4),
                    "valence": round(trace.valence, 4),
                    "consolidated": trace.channel == "schema",
                }
            )

        deduped: dict[str, dict[str, Any]] = {}
        for item in merged:
            key = str(
                item.get("candidate_id")
                or item.get("neural_trace_id")
                or ""
            )
            if not key:
                continue
            prior = deduped.get(key)
            if prior is None or float(item.get("similarity") or 0.0) > float(
                prior.get("similarity") or 0.0
            ):
                deduped[key] = item
        ranked = sorted(
            deduped.values(),
            key=lambda item: float(item.get("similarity") or 0.0),
            reverse=True,
        )
        return ranked[:bounded_limit]

    def _advance_intention(self, intention_id: str) -> None:
        intention = self.will.get(intention_id)
        if intention is None:
            return
        if intention.status != "active":
            return
        if intention.related_event_id:
            return
        if not intention.next_task:
            return

        task = intention.next_task
        payload = dict(intention.next_payload)
        payload.setdefault("intention_id", intention.intention_id)
        payload.setdefault("intention_description", intention.description)
        payload.setdefault("intention_source", intention.source)
        event_kind = str(
            payload.get("incubated_event_kind") or "intention_step"
        ).strip() or "intention_step"
        event = self.enqueue(
            task,
            kind=event_kind,
            priority=intention.priority,
            payload=payload,
        )
        self.will.engage(intention.intention_id, event.event_id)
        self.nervous.perceive(
            "will",
            f"I began the next step of intention {intention.intention_id}: {task}",
            features=("intention_step", "engaged", event_kind),
            source="will",
            salience=0.62,
            valence=0.12,
            arousal=0.45,
            metadata={
                "intention_id": intention.intention_id,
                "event_id": event.event_id,
            },
        )

    def _complete_result(self, event, result):
        completed = super()._complete_result(event, result)
        summary = (
            completed.response
            or completed.reason
            or ("event succeeded" if completed.success else "event failed")
        )
        self.nervous.perceive(
            "outcome",
            f"{event.task}: {summary[:1000]}",
            features=(
                event.kind,
                completed.execution_path.value,
                "success" if completed.success else "failure",
            ),
            source="self",
            salience=min(
                1.0,
                0.58 + (0.18 if not completed.success else 0.0),
            ),
            valence=0.52 if completed.success else -0.78,
            arousal=0.42 if completed.success else 0.82,
            metadata={
                "event_id": completed.event.event_id,
                "model_invocations": completed.model_invocations,
            },
        )

        intention_id = str(event.payload.get("intention_id") or "").strip()
        if intention_id:
            try:
                self.will.observe_event_outcome(
                    intention_id,
                    event_id=completed.event.event_id,
                    success=completed.success,
                    summary=summary,
                )
            except KeyError:
                # The event remains valid if an imported/manual payload points
                # at an intention that is not present in this resident.
                pass
        return completed

    def status(self) -> dict[str, Any]:
        data = super().status()
        primary = self.will.primary()
        affect = self.nervous.snapshot()
        consolidation = self.nervous.latest_consolidation()
        data["will"] = {
            "primary": (
                self._intention_data(primary)
                if primary is not None
                else None
            ),
            "active": [
                self._intention_data(item)
                for item in self.will.active(20)
            ],
        }
        data["nervous_system"] = {
            "tone": self.nervous.describe_state(),
            "affect": asdict(affect),
            "recent_trace_count": len(self.nervous.recent_traces(50)),
            "reflection_period_pulses": self._reflection_period_for(affect),
            "latest_consolidation": (
                asdict(consolidation) if consolidation is not None else None
            ),
        }
        data["world_sense"] = {
            "focuses": [
                asdict(item)
                for item in self.world.focuses(
                    enabled_only=True,
                    limit=20,
                )
            ],
            "due_focus": (
                asdict(due)
                if (due := self.world.due_focus()) is not None
                else None
            ),
        }
        return data

    @staticmethod
    def _intention_data(intention: ResidentIntention) -> dict[str, Any]:
        return {
            "intention_id": intention.intention_id,
            "description": intention.description,
            "source": intention.source,
            "priority": intention.priority,
            "status": intention.status,
            "current_step": intention.current_step,
            "next_task": intention.next_task,
            "related_event_id": intention.related_event_id,
            "last_outcome": intention.last_outcome,
            "complete_on_step_success": intention.complete_on_step_success,
            "candidate_kind": intention.candidate_kind,
            "candidate_step": intention.candidate_step,
            "candidate_reason": intention.candidate_reason,
            "candidate_confidence": intention.candidate_confidence,
            "candidate_repetitions": intention.candidate_repetitions,
            "candidate_maturity": intention.candidate_maturity,
            "candidate_support": list(intention.candidate_support),
            "incubation_count": intention.incubation_count,
            "last_incubated_at": intention.last_incubated_at,
            "updated_at": intention.updated_at,
        }
