from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from .intentional_resident import IntentionalResidentRuntime
from .reconsolidation import SchemaReconsolidator
from .schema_structure import SchemaStructurePlasticity

if TYPE_CHECKING:
    from .life import BodyState, SituationModel
    from .nervous_system import NeuralActivation, PersistentNervousSystem
    from .will import ResidentIntention


@dataclass(slots=True)
class NativeIntentionCandidate:
    """One resident-native next-step candidate grounded in lived structure."""

    kind: str
    step: str
    reason: str
    support: tuple[str, ...]
    payload: dict[str, Any]
    probe_key: str = "experience"
    relation_family: str | None = None
    relation_value: str | None = None


class NativeIntentionFormation:
    """Shape one useful Will candidate from schema plus current Situation.

    This is not a planner and does not call a model. It translates structured
    expectations already present in a consolidated schema into a concrete
    observation that ZN's existing Investigation/sensory loop can perform.
    Reality feedback is part of formation: an already-tested relation is not
    selected again unless the latest prediction error still needs one confirming
    recheck, and a restructured emerging relation can become the next single
    candidate.
    """

    _PROBE_BY_FAMILY = {
        "workspace": "git",
        "branch": "git",
        "changes": "git",
        "system": "body",
        "architecture": "body",
        "disk_state": "body",
        "path_state": "paths",
        "path_type": "paths",
        "presence": "paths",
        "process_state": "processes",
        "visual_change": "vision",
        "luminance": "vision",
    }
    _FAMILY_BONUS = {
        "workspace": 0.08,
        "branch": 0.07,
        "changes": 0.06,
        "system": 0.09,
        "architecture": 0.08,
        "disk_state": 0.10,
        "path_state": 0.10,
        "path_type": 0.08,
        "presence": 0.08,
        "process_state": 0.10,
        "visual_change": 0.12,
        "luminance": 0.07,
    }
    _PATH_RE = re.compile(
        r"(?:[A-Za-z]:[\\/][^\s'\"]+|(?:\.{0,2}/|/)[^\s'\"]+)"
    )
    _PID_RE = re.compile(r"\bpid\s*[:=#]?\s*(\d+)\b", flags=re.IGNORECASE)
    _EXPECTATION_RE = re.compile(r"schema expectation ([0-9a-f]{10})")

    def __init__(
        self,
        nervous: PersistentNervousSystem,
        *,
        resident: IntentionalResidentRuntime | None = None,
    ):
        self.nervous = nervous
        self.resident = resident
        self.reconsolidator = SchemaReconsolidator(nervous)

    def form(
        self,
        intention: ResidentIntention,
        activation: NeuralActivation,
        *,
        situation: SituationModel | None,
        body: BodyState | None,
    ) -> NativeIntentionCandidate | None:
        schema = activation.trace
        profile = self.reconsolidator._profile(schema)
        support = (
            schema.trace_id,
            *tuple(
                str(item)
                for item in schema.metadata.get("source_trace_ids", ())
                if str(item).strip()
            )[:6],
        )
        common_payload = {
            "model_policy": "never",
            "incubated_event_kind": "intention_probe",
            "schema_trace_id": schema.trace_id,
            "schema_summary": schema.summary[:700],
            "native_step_source": "will+schema+situation",
            "native_situation_context": self._situation_context(situation, body),
        }

        targeted = self._targeted_expectation_signatures(intention)
        tested = self._tested_expectation_signatures(
            intention,
            schema.metadata,
        )
        recheck = self._recheck_expectation_signatures(
            schema.metadata,
            intention=intention,
        )
        # A single observation can test several relations at once, but only the
        # relation Will deliberately targeted earns one confirming recheck after
        # prediction error. Incidental relations are lived evidence, not new
        # micro-plans.
        allowed_rechecks = targeted.intersection(recheck)
        relation = self._select_relation(
            profile,
            intention.description,
            body=body,
            excluded_signatures=tested - allowed_rechecks,
        )
        if relation is not None:
            family = str(relation.get("family") or "")
            value = str(relation.get("value") or "")
            probe_key = self._PROBE_BY_FAMILY[family]
            target = self._probe_target(
                probe_key,
                intention.description,
                body=body,
            )
            if target is not None:
                signature = self._expectation_signature(family, value)
                is_recheck = signature in allowed_rechecks
                # ``attempt`` describes Will's lived probe history, not the
                # schema node's aggregate conflict count. Structural compaction
                # may merge several equivalent schema representations and sum
                # their conflict counters after a single observation. The one
                # confirming recheck therefore follows the first lived probe as
                # attempt 2 regardless of that neural bookkeeping detail.
                attempt = 2 if is_recheck else 1
                confidence = round(
                    max(
                        0.0,
                        min(
                            1.0,
                            float(relation.get("confidence") or 0.0),
                        ),
                    ),
                    5,
                )
                support_ratio = round(
                    max(
                        0.0,
                        min(
                            1.0,
                            float(relation.get("support_ratio") or 0.0),
                        ),
                    ),
                    5,
                )
                status = str(relation.get("status") or "expected")
                payload = {
                    **common_payload,
                    **target,
                    "native_probe_key": probe_key,
                    "schema_expectation": {
                        "family": family,
                        "value": value,
                        "confidence": confidence,
                        "support_ratio": support_ratio,
                        "status": status,
                        "signature": signature,
                        "recheck": is_recheck,
                        "attempt": attempt,
                    },
                    "tested_schema_expectations": sorted(tested)[-12:],
                }
                # Body relations existed before situated formation and already
                # have a structured Investigation contract. Preserve that
                # outward shape while letting the relation itself be selected by
                # Will + schema + current Situation. Vision deliberately opts in
                # to prediction-first ordering because a current frame is useful
                # only after the lived schema has been activated as a prediction.
                if probe_key == "body":
                    payload.update(
                        {
                            "schema_probe_observation": "body",
                            "schema_probe_relation": {
                                "family": family,
                                "value": value,
                                "support_ratio": support_ratio,
                                "status": status,
                            },
                            "schema_probe_confidence": confidence,
                        }
                    )
                elif probe_key == "vision":
                    payload["schema_probe_observation"] = "vision"
                return NativeIntentionCandidate(
                    kind="situated_schema_probe",
                    step=self._step_text(
                        probe_key,
                        family,
                        value,
                        signature,
                        target,
                        recheck=is_recheck,
                        attempt=attempt,
                    ),
                    reason=self._reason_text(
                        probe_key,
                        family,
                        situation=situation,
                        body=body,
                        recheck=is_recheck,
                    ),
                    support=support,
                    payload=payload,
                    probe_key=probe_key,
                    relation_family=family,
                    relation_value=value,
                )

        # Once this enduring intention has already tested a structured relation,
        # exhausting the currently testable structure is meaningful. Do not fall
        # back to a generic applicability probe and accidentally restart the same
        # loop under different wording. Another activated schema may still offer
        # a genuinely new relation, which the resident runtime can select.
        if tested and self._select_relation(
            profile,
            intention.description,
            body=body,
            excluded_signatures=set(),
        ) is not None:
            return None

        return NativeIntentionCandidate(
            kind="schema_probe",
            step=(
                "test whether this consolidated pattern applies to my current "
                f"intention: {schema.summary[:420]}"
            ),
            reason=(
                "the same consolidated lived pattern repeatedly activates while "
                "this intention holds attention"
            ),
            support=support,
            payload=common_payload,
        )

    def _select_relation(
        self,
        profile: dict[str, Any],
        intention_text: str,
        *,
        body: BodyState | None,
        excluded_signatures: set[str] | None = None,
    ) -> dict[str, Any] | None:
        text = str(intention_text or "").lower()
        excluded = excluded_signatures or set()
        ranked: list[tuple[float, str, str, dict[str, Any]]] = []
        for relation in profile.get("relations") or ():
            family = str(relation.get("family") or "")
            value = str(relation.get("value") or "")
            probe_key = self._PROBE_BY_FAMILY.get(family)
            if not probe_key or not value:
                continue
            if str(relation.get("status") or "") == "contested":
                continue
            signature = self._expectation_signature(family, value)
            if signature in excluded:
                continue
            if self._probe_target(probe_key, text, body=body) is None:
                continue
            confidence = max(
                0.0,
                min(1.0, float(relation.get("confidence") or 0.0)),
            )
            support = max(
                0.0,
                min(1.0, float(relation.get("support_ratio") or 0.0)),
            )
            weight = max(
                0.0,
                min(1.0, float(relation.get("weight") or 0.0)),
            )
            if confidence < 0.40 and support < 0.55:
                continue
            score = 0.46 * confidence + 0.30 * support + 0.16 * weight
            score += 0.08 if bool(relation.get("anchor")) else 0.0
            score += self._FAMILY_BONUS.get(family, 0.04)
            if family in text or value in text:
                score += 0.05
            ranked.append((score, family, value, relation))
        if not ranked:
            return None
        ranked.sort(key=lambda item: (-item[0], item[1], item[2]))
        return ranked[0][3]

    @classmethod
    def _targeted_expectation_signatures(
        cls,
        intention: ResidentIntention,
    ) -> set[str]:
        if not intention.last_outcome:
            return set()
        texts = [
            str(intention.current_step or ""),
            *(str(item) for item in intention.progress),
        ]
        return {
            match.group(1)
            for text in texts
            for match in cls._EXPECTATION_RE.finditer(text)
        }

    @classmethod
    def _tested_expectation_signatures(
        cls,
        intention: ResidentIntention,
        metadata: dict[str, Any] | None = None,
    ) -> set[str]:
        targeted = cls._targeted_expectation_signatures(intention)
        if not targeted:
            return set()
        tested = set(targeted)
        feedback = (metadata or {}).get("last_prediction_feedback")
        if not isinstance(feedback, dict):
            return tested
        if not cls._feedback_belongs_to_intention(feedback, intention):
            return tested

        for item in feedback.get("support") or ():
            signature = cls._feedback_relation_signature(item)
            if signature:
                tested.add(signature)
        for item in feedback.get("contradictions") or ():
            signature = cls._feedback_relation_signature(item)
            if signature:
                tested.add(signature)
        return tested

    @classmethod
    def _feedback_relation_signature(cls, raw: Any) -> str | None:
        expected, _, _observed = str(raw or "").partition("->")
        family, separator, value = expected.partition(":")
        family = family.strip().lower()
        value = value.strip().lower()
        if (
            not separator
            or family not in cls._PROBE_BY_FAMILY
            or not value
        ):
            return None
        return cls._expectation_signature(family, value)

    @staticmethod
    def _feedback_belongs_to_intention(
        feedback: dict[str, Any],
        intention: ResidentIntention,
    ) -> bool:
        event_id = str(feedback.get("event_id") or "").strip()
        if not event_id or not intention.last_outcome:
            return False
        marker = f"event {event_id} "
        return any(marker in str(item) for item in intention.progress)

    @classmethod
    def _recheck_expectation_signatures(
        cls,
        metadata: dict[str, Any],
        *,
        intention: ResidentIntention | None = None,
    ) -> set[str]:
        feedback = metadata.get("last_prediction_feedback")
        if not isinstance(feedback, dict):
            return set()
        if intention is not None and not cls._feedback_belongs_to_intention(
            feedback,
            intention,
        ):
            return set()
        if str(feedback.get("status") or "") not in {"refined", "contradicted"}:
            return set()
        signatures: set[str] = set()
        for item in feedback.get("contradictions") or ():
            signature = cls._feedback_relation_signature(item)
            if signature:
                signatures.add(signature)
        return signatures

    def _probe_target(
        self,
        probe_key: str,
        intention_text: str,
        *,
        body: BodyState | None,
    ) -> dict[str, Any] | None:
        if probe_key in {"git", "body"}:
            return {}
        if probe_key == "vision":
            return {} if self._vision_ready() else None
        if probe_key == "paths":
            match = self._PATH_RE.search(str(intention_text or ""))
            if match is None:
                return None
            path = match.group(0).rstrip(".,;:!?)]}")
            return {"path": path} if path else None
        if probe_key == "processes":
            match = self._PID_RE.search(str(intention_text or ""))
            if match is None:
                return None
            try:
                pid = int(match.group(1))
            except (TypeError, ValueError):
                return None
            return {"pid": pid} if pid > 0 else None
        return None

    def _vision_ready(self) -> bool:
        vision = getattr(self.resident, "vision", None) if self.resident is not None else None
        if vision is None:
            return False
        try:
            state = vision.status()
        except Exception:
            return False
        return bool(
            getattr(state, "enabled", False)
            and str(getattr(state, "last_frame_hash", "") or "").strip()
        )

    @staticmethod
    def _step_text(
        probe_key: str,
        family: str,
        value: str,
        signature: str,
        target: dict[str, Any],
        *,
        recheck: bool = False,
        attempt: int = 1,
    ) -> str:
        prefix = f"recheck {attempt} " if recheck else "inspect "
        suffix = f"for my current intention (schema expectation {signature})"
        if probe_key == "git":
            return f"{prefix}current git workspace relation {family} {suffix}"
        if probe_key == "body":
            return (
                f"{prefix}current body state relation {family}:{value} {suffix}"
            )
        if probe_key == "vision":
            return f"{prefix}current resident vision relation {family}:{value} {suffix}"
        if probe_key == "paths":
            return f"{prefix}path {target.get('path')} relation {family} {suffix}"
        if probe_key == "processes":
            return f"{prefix}pid {target.get('pid')} relation {family} {suffix}"
        return f"{prefix}current state relation {family} {suffix}"

    @staticmethod
    def _reason_text(
        probe_key: str,
        family: str,
        *,
        situation: SituationModel | None,
        body: BodyState | None,
        recheck: bool = False,
    ) -> str:
        context: list[str] = []
        cwd = str(getattr(body, "cwd", "") or "").strip()
        if cwd and probe_key == "git":
            context.append(f"current cwd {cwd}")
        if body is not None and probe_key == "body":
            system = str(getattr(body, "system", "") or "").strip()
            architecture = str(getattr(body, "architecture", "") or "").strip()
            if system or architecture:
                context.append(
                    "current body "
                    f"system={system or 'unknown'} architecture={architecture or 'unknown'}"
                )
        if probe_key == "vision":
            context.append("resident retina has a prior frame for comparison")
        if situation is not None:
            changes = tuple(getattr(situation, "changes", ()) or ())
            if changes:
                context.append(f"{len(changes)} current situation change(s)")
        basis = "; ".join(context) if context else "the current Situation"
        if recheck:
            return (
                f"the last reality check produced prediction error for structured {family}; "
                f"one confirming {probe_key} recheck against {basis} can determine whether "
                "the relation should restructure instead of being repeated indefinitely"
            )
        return (
            f"the activated schema carries a structured {family} expectation and "
            f"{basis} provides a concrete {probe_key} observation path"
        )

    @staticmethod
    def _situation_context(
        situation: SituationModel | None,
        body: BodyState | None,
    ) -> dict[str, Any]:
        context: dict[str, Any] = {}
        if situation is not None:
            context["sequence"] = int(getattr(situation, "sequence", 0) or 0)
            context["body_health"] = str(
                getattr(situation, "body_health", "") or ""
            )
            context["changes"] = [
                str(item)[:300]
                for item in tuple(getattr(situation, "changes", ()) or ())[:6]
            ]
            recent = str(getattr(situation, "recent_outcome", "") or "").strip()
            if recent:
                context["recent_outcome"] = recent[:500]
        if body is not None:
            context["body_cwd"] = str(getattr(body, "cwd", "") or "")
            context["body_system"] = str(getattr(body, "system", "") or "")
            context["body_architecture"] = str(
                getattr(body, "architecture", "") or ""
            )
            try:
                context["body_disk_free_ratio"] = round(
                    float(getattr(body, "disk_free_ratio", 0.0) or 0.0),
                    6,
                )
            except (TypeError, ValueError):
                pass
        return context

    @staticmethod
    def _expectation_signature(family: str, value: str) -> str:
        return hashlib.sha256(f"{family}:{value}".encode()).hexdigest()[:10]


class SituatedIntentionalResidentRuntime(IntentionalResidentRuntime):
    """The resident whose Will can form one situated native next step."""

    def __init__(self, *, kernel, capabilities=None, budget=None):
        super().__init__(
            kernel=kernel,
            capabilities=capabilities,
            budget=budget,
        )
        self.intention_formation = NativeIntentionFormation(
            self.nervous,
            resident=self,
        )

    def _incubate_primary_intention(self, thought) -> bool:
        life_state = self.life.snapshot()
        situation = life_state.current_situation
        if situation is not None and (
            situation.active_event_id or situation.active_impasse_id
        ):
            return False
        primary = self.will.primary()
        if primary is None or primary.status != "active":
            return False
        if primary.next_task or primary.related_event_id:
            return False

        activations = [
            item
            for item in self.nervous.activate(
                primary.description,
                channels=self._INCUBATION_CHANNELS,
                limit=6,
            )
            if item.trace.channel == "schema" and item.activation >= 0.30
        ]
        if not activations:
            existing = self.will.get(primary.intention_id)
            if existing is not None and existing.candidate_step:
                self._surface_incubating_candidate(thought, existing)
                return True
            return False

        formed: list[tuple[NeuralActivation, NativeIntentionCandidate]] = []
        for activation in activations:
            candidate = self.intention_formation.form(
                primary,
                activation,
                situation=situation,
                body=life_state.body,
            )
            if candidate is not None:
                formed.append((activation, candidate))
        if not formed:
            return False

        selected = next(
            (
                item
                for item in formed
                if item[1].kind == "situated_schema_probe"
            ),
            formed[0],
        )
        schema_activation, candidate = selected
        schema = schema_activation.trace
        step = candidate.step
        if primary.current_step == step and primary.last_outcome:
            return False

        confidence = min(
            0.96,
            0.34
            + 0.42 * schema_activation.activation
            + 0.14 * schema.strength
            + 0.10 * schema.salience,
        )
        updated = self.will.incubate_candidate(
            primary.intention_id,
            kind=candidate.kind,
            step=step,
            reason=candidate.reason,
            confidence=confidence,
            support=candidate.support,
            payload=candidate.payload,
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

    def _related_learning_evidence(
        self,
        event,
        readiness,
        *,
        limit: int = 3,
    ) -> list[dict[str, Any]]:
        bounded_limit = max(1, int(limit))
        merged = list(
            super()._related_learning_evidence(
                event,
                readiness,
                limit=bounded_limit,
            )
        )
        explicit_schema_id = str(
            event.payload.get("schema_trace_id") or ""
        ).strip()
        if explicit_schema_id:
            schema = SchemaStructurePlasticity(self.nervous).resolve_schema(
                explicit_schema_id
            )
            if schema is not None and schema.channel == "schema":
                merged.append(
                    {
                        "candidate_id": f"neural:{schema.trace_id}",
                        "similarity": 1.0,
                        "domains": list(readiness.domains),
                        "task": schema.summary[:240],
                        "resolution_summary": schema.summary[:320],
                        "resolution_source": "neural:schema",
                        "neural_trace_id": schema.trace_id,
                        "salience": round(schema.salience, 4),
                        "valence": round(schema.valence, 4),
                        "consolidated": True,
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
