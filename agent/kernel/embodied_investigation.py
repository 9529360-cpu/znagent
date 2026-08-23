from __future__ import annotations

from typing import Any

from .action import derive_native_action_intent
from .investigation import NativeInvestigator
from .models import AgentEvent
from .procedural_applicability import (
    current_expected_outcome,
    evaluate_candidate_applicability,
)
from .reconsolidation import SchemaReconsolidator
from .schema_structure import SchemaStructurePlasticity
from .self_model import TaskReadiness
from .visual_sense import NativeVisualSense


class EmbodiedInvestigator(NativeInvestigator):
    """Native investigation whose probes are movements of ZN's Body.

    The parent class owns hypothesis selection, evidence accumulation and the
    multi-pulse reasoning loop. This subclass changes *how* a concrete probe
    touches the computer and lets consolidated neural schemas become native
    predictions. Perception, action, and prior lived structure therefore meet
    inside one investigation instead of becoming separate agent components.
    """

    _PROBE_LABELS = {
        **NativeInvestigator._PROBE_LABELS,
        "vision": "sample current resident vision state",
    }

    def investigate(
        self,
        event: AgentEvent,
        readiness: TaskReadiness,
        *,
        learning_evidence: list[dict[str, Any]] | None = None,
        local_failure: str | None = None,
    ):
        result = super().investigate(
            event,
            readiness,
            learning_evidence=learning_evidence,
            local_failure=local_failure,
        )
        self._surface_procedural_applicability(event, readiness, result)

        predictions = result.state.facts.get("schema_predictions")
        nervous = getattr(self.resident, "nervous", None)
        if not isinstance(predictions, list) or not predictions or nervous is None:
            return result

        feedback = SchemaReconsolidator(nervous).evaluate(
            predictions,
            result.state.facts,
            event_id=event.event_id,
        )
        if not feedback:
            return result

        self._bind_prediction_feedback_to_event(
            nervous,
            feedback,
            event.event_id,
        )
        structural_merges = SchemaStructurePlasticity(nervous).compact(
            seed_ids=[item.schema_trace_id for item in feedback],
        )
        existing = result.state.facts.get("schema_prediction_feedback")
        records = list(existing) if isinstance(existing, list) else []
        known_keys = {
            str(item.get("reconsolidation_key") or "")
            for item in records
            if isinstance(item, dict)
        }
        evidence = list(result.state.evidence)
        for item in feedback:
            if item.reconsolidation_key not in known_keys:
                records.append(item.to_dict())
                known_keys.add(item.reconsolidation_key)
            if item.status == "supported":
                note = (
                    f"prediction error {item.prediction_error:.3f}: current evidence "
                    f"supports schema {item.schema_trace_id}; the schema was reinforced"
                )
            elif item.status == "refined":
                note = (
                    f"prediction error {item.prediction_error:.3f}: current evidence "
                    f"partly contradicts schema {item.schema_trace_id}; the schema was "
                    "reconsolidated and the exception was preserved"
                )
            elif item.status == "contradicted":
                note = (
                    f"prediction error {item.prediction_error:.3f}: current evidence "
                    f"contradicts schema {item.schema_trace_id}; the schema was weakened "
                    "and the exception was preserved"
                )
            else:
                note = (
                    f"current {', '.join(item.observation_channels) or 'body'} evidence "
                    f"did not directly test schema {item.schema_trace_id}; no neural "
                    "prediction strength was changed"
                )
            self._append_unique(evidence, note)

        merge_records = [item.to_dict() for item in structural_merges]
        for item in structural_merges:
            self._append_unique(
                evidence,
                "structural neural plasticity merged redundant schema "
                f"{item.absorbed_schema_id} into {item.canonical_schema_id} "
                f"(shared lived support={item.source_overlap:.3f}, "
                f"shared structure={item.feature_overlap:.3f})",
            )

        result.state.facts["schema_prediction_feedback"] = records[-16:]
        if merge_records:
            prior_merges = result.state.facts.get("schema_structural_merges")
            merged_history = (
                list(prior_merges)
                if isinstance(prior_merges, list)
                else []
            )
            merged_history.extend(merge_records)
            result.state.facts["schema_structural_merges"] = merged_history[-16:]
        result.state.evidence = tuple(evidence[-64:])
        result.state.updated_at = (
            structural_merges[-1].at
            if structural_merges
            else feedback[-1].at
        )

        if event.kind == "intention_probe" and result.resolved:
            changed = [item for item in feedback if item.status != "untested"]
            if changed:
                latest = changed[-1]
                suffix = (
                    f" Reality feedback {latest.status} the activated pattern "
                    f"(prediction error={latest.prediction_error:.3f}); the result was "
                    "written back into my persistent neural state."
                )
            else:
                suffix = (
                    " The current observation did not test a structured expectation "
                    "inside the schema, so I left its neural strength unchanged."
                )
            if structural_merges:
                suffix += (
                    f" I also collapsed {len(structural_merges)} redundant schema "
                    "representation(s) into the surviving lived pattern."
                )
            result.response = f"{result.response}{suffix}"
            result.state.resolution = result.response

        self._save(result.state)
        return result

    def _surface_procedural_applicability(self, event, readiness, result) -> None:
        """Compare L2 candidates with current facts without granting action authority."""
        working = self.store.get_working_state()
        if working.current_event_id != event.event_id:
            return

        evaluations: list[dict[str, Any]] = []
        intent = derive_native_action_intent(event, facts=result.state.facts)
        if intent is not None:
            expected = current_expected_outcome(event, intent)
            candidates = self.resident.verified_experiences.candidate_tendencies(limit=16)
            relevant = [
                item for item in candidates if item.action_kind == intent.kind
            ][:8]
            for candidate in relevant:
                evaluation = evaluate_candidate_applicability(
                    candidate,
                    current_domains=readiness.domains,
                    action_kind=intent.kind,
                    action_args=intent.args,
                    expected_outcome=expected,
                    facts=result.state.facts,
                )
                evaluations.append(evaluation.to_dict())

        working.data["procedural_applicability"] = evaluations[-8:]
        self.store.save_working_state(working)

        if not evaluations:
            return
        evidence = list(result.state.evidence)
        for item in evaluations[-4:]:
            tendency_id = str(item.get("tendency_id") or "unknown")
            status = str(item.get("status") or "untested")
            reality_fields = item.get("reality_matched_fields")
            mismatch_fields = item.get("mismatched_fields")
            if status == "supported":
                fields = ",".join(str(value) for value in reality_fields or ()) or "reality"
                note = (
                    f"procedural candidate {tendency_id} is supported by current "
                    f"independent evidence ({fields}); it remains observational"
                )
            elif status == "mismatch":
                fields = ",".join(str(value) for value in mismatch_fields or ()) or "context"
                note = (
                    f"procedural candidate {tendency_id} mismatches current evidence "
                    f"({fields}) and must not qualify"
                )
            else:
                note = (
                    f"procedural candidate {tendency_id} remains untested by current "
                    "independent evidence and must not qualify"
                )
            self._append_unique(evidence, note)
        result.state.evidence = tuple(evidence[-64:])
        self._save(result.state)

    @staticmethod
    def _bind_prediction_feedback_to_event(nervous, feedback, event_id: str) -> None:
        """Bind the latest neural reality check to the lived event that caused it."""
        for item in feedback:
            if item.status == "untested":
                continue
            schema = nervous._get_trace(item.schema_trace_id)
            if schema is None or schema.channel != "schema":
                continue
            record = schema.metadata.get("last_prediction_feedback")
            if not isinstance(record, dict):
                continue
            if str(record.get("reconsolidation_key") or "") != str(
                item.reconsolidation_key
            ):
                continue
            bound = dict(record)
            bound["event_id"] = str(event_id)
            schema.metadata["last_prediction_feedback"] = bound
            nervous._save_trace(schema)

    def _seed_hypotheses(
        self,
        hypotheses: list[str],
        readiness: TaskReadiness,
        *,
        learning_evidence: list[dict[str, Any]],
        local_failure: str | None,
    ) -> None:
        super()._seed_hypotheses(
            hypotheses,
            readiness,
            learning_evidence=learning_evidence,
            local_failure=local_failure,
        )
        for schema in self._schema_evidence(learning_evidence)[:2]:
            summary = str(schema.get("resolution_summary") or "").strip()
            if not summary:
                continue
            self._append_unique(
                hypotheses,
                "a consolidated lived pattern predicts relevant structure here: "
                f"{summary[:520]}",
            )

    def _derive_hypotheses_from_facts(
        self,
        hypotheses: list[str],
        facts: dict[str, Any],
    ) -> None:
        super()._derive_hypotheses_from_facts(hypotheses, facts)
        predictions = facts.get("schema_predictions")
        if not isinstance(predictions, list) or not predictions:
            return
        feedback = facts.get("schema_prediction_feedback")
        if isinstance(feedback, list) and feedback:
            latest = feedback[-1] if isinstance(feedback[-1], dict) else {}
            status = str(latest.get("status") or "")
            error = float(latest.get("prediction_error") or 0.0)
            if status == "supported":
                self._append_unique(
                    hypotheses,
                    "current reality supports the activated schema with "
                    f"prediction error {error:.3f}",
                )
            elif status == "refined":
                self._append_unique(
                    hypotheses,
                    f"current reality partly contradicts the activated schema; its "
                    f"prediction structure was reconsolidated (error={error:.3f})",
                )
            elif status == "contradicted":
                self._append_unique(
                    hypotheses,
                    f"current reality contradicts the activated schema; the old pattern "
                    f"was weakened and an exception retained (error={error:.3f})",
                )

        concrete_keys = {
            key
            for key in facts
            if key
            not in {
                "related_experience_count",
                "schema_predictions",
                "schema_prediction_feedback",
                "schema_reconsolidation_keys",
                "schema_structural_merges",
            }
        }
        if concrete_keys:
            self._append_unique(
                hypotheses,
                "current resident evidence should confirm, refine, or contradict the "
                "activated consolidated pattern rather than assuming it is correct",
            )

    def _run_probe(
        self,
        key: str,
        event: AgentEvent,
        readiness: TaskReadiness,
        *,
        facts: dict[str, Any],
        learning_evidence: list[dict[str, Any]],
    ) -> list[str]:
        if key == "experience":
            schemas = self._schema_evidence(learning_evidence)
            facts["related_experience_count"] = len(learning_evidence)
            if schemas:
                predictions = [
                    {
                        "trace_id": str(item.get("neural_trace_id") or ""),
                        "summary": str(item.get("resolution_summary") or "")[:700],
                        "similarity": float(item.get("similarity") or 0.0),
                        "salience": float(item.get("salience") or 0.0),
                    }
                    for item in schemas[:3]
                ]
                facts["schema_predictions"] = predictions
                evidence = [
                    "consolidated schema prediction activated: "
                    f"{item['summary']}"
                    for item in predictions
                    if item["summary"]
                ]
                ordinary = len(learning_evidence) - len(schemas)
                if ordinary > 0:
                    evidence.append(
                        f"additional related lived experience records available: {ordinary}"
                    )
                return evidence or [
                    f"related experience records available: {len(learning_evidence)}"
                ]

        if key == "vision":
            vision = getattr(self.resident, "vision", None)
            if vision is None:
                facts["vision"] = {"available": False}
                return ["resident vision is currently unavailable"]
            try:
                observation = vision.sample()
            except Exception as exc:
                message = f"{type(exc).__name__}: {exc}"
                facts["vision"] = {"available": False, "error": message}
                return [f"resident vision probe failed: {message}"]
            if observation is None:
                facts["vision"] = {"available": False, "error": "no visual observation"}
                return ["resident vision produced no current observation"]
            state = vision.status()
            areas = NativeVisualSense._visual_areas(
                tuple(observation.changed_region_indices),
                int(getattr(state, "last_grid_columns", 0) or 0),
                int(getattr(state, "last_grid_rows", 0) or 0),
            )
            luminance = NativeVisualSense._luminance_direction(
                observation.luminance_delta
            )
            facts["vision"] = {
                "available": True,
                "changed": bool(observation.changed),
                "change_scale": str(observation.change_scale or "none"),
                "change_ratio": float(observation.change_ratio or 0.0),
                "changed_region_indices": list(observation.changed_region_indices),
                "visual_areas": list(areas),
                "luminance_delta": observation.luminance_delta,
                "luminance": luminance,
                "source": observation.source,
                "width": observation.width,
                "height": observation.height,
                "captured_at": observation.captured_at,
            }
            return [
                "vision: "
                f"changed={observation.changed}; scale={observation.change_scale}; "
                f"ratio={observation.change_ratio:.3f}; "
                f"areas={','.join(areas) or 'none'}; "
                f"luminance={luminance or 'unknown'}"
            ]

        body = getattr(self.resident, "body", None)
        if body is None:
            return super()._run_probe(
                key,
                event,
                readiness,
                facts=facts,
                learning_evidence=learning_evidence,
            )

        if key == "body":
            result = body.act("sense", event_id=event.event_id)
            if not result.success:
                return [f"body probe failed: {result.error or 'unknown error'}"]
            total = int(result.data.get("disk_total_bytes") or 0)
            free = int(result.data.get("disk_free_bytes") or 0)
            ratio = (free / total) if total > 0 else 0.0
            facts["body"] = {
                "hostname": result.data.get("hostname"),
                "pid": result.data.get("pid"),
                "cwd": result.data.get("cwd"),
                "system": result.data.get("system"),
                "architecture": result.data.get("architecture"),
                "disk_free_ratio": ratio,
            }
            return [
                "body: "
                f"host={result.data.get('hostname')}; pid={result.data.get('pid')}; "
                f"cwd={result.data.get('cwd')}; system={result.data.get('system')}; "
                f"disk_free={ratio:.3f}"
            ]

        if key == "paths":
            path_facts: list[dict[str, Any]] = []
            evidence: list[str] = []
            for raw in self._path_candidates(event):
                result = body.act(
                    "inspect_path",
                    event_id=event.event_id,
                    path=raw,
                )
                if result.success:
                    item = dict(result.data)
                else:
                    item = {
                        "path": str(raw),
                        "exists": False,
                        "type": "unavailable",
                        "error": result.error,
                    }
                path_facts.append(item)
                evidence.append(
                    "path: "
                    f"{item.get('path')} exists={item.get('exists')} "
                    f"type={item.get('type', 'missing')} size={item.get('size_bytes', 0)}"
                )
            facts["paths"] = path_facts
            return evidence or ["path probe found no concrete referenced path"]

        if key == "file_preview":
            previews: list[dict[str, Any]] = []
            evidence: list[str] = []
            for item in self._previewable_paths(facts):
                path = str(item.get("path") or "")
                result = body.act(
                    "read_text",
                    event_id=event.event_id,
                    path=path,
                    max_chars=16384,
                )
                if not result.success:
                    continue
                preview = {
                    "path": path,
                    "preview": result.output,
                    "chars": int(result.data.get("chars") or len(result.output)),
                    "truncated": bool(result.data.get("truncated", False)),
                }
                previews.append(preview)
                evidence.append(
                    f"file content observed locally: {path} chars={preview['chars']} "
                    f"truncated={preview['truncated']}"
                )
            facts["file_previews"] = previews
            return evidence or ["referenced files did not yield readable text content"]

        if key == "git":
            workspace = (
                event.payload.get("workspace_path")
                or event.payload.get("project_path")
                or event.payload.get("repo_path")
            )
            if not workspace:
                sensed = body.sense()
                workspace = sensed.get("cwd")
            result = body.act(
                "git_state",
                event_id=event.event_id,
                path=str(workspace or "."),
            )
            if not result.success:
                facts["git"] = {"available": False, "error": result.error}
                return ["git workspace probe did not find a repository"]
            git_fact = dict(result.data)
            git_fact["available"] = True
            facts["git"] = git_fact
            return [
                "git: "
                f"root={git_fact.get('root')}; branch={git_fact.get('branch')}; "
                f"dirty={git_fact.get('dirty')}; changed_files={git_fact.get('changed_files')}"
            ]

        if key == "processes":
            process_facts: list[dict[str, Any]] = []
            evidence: list[str] = []
            for pid in self._process_candidates(event):
                result = body.act(
                    "process_state",
                    event_id=event.event_id,
                    pid=pid,
                )
                item = (
                    dict(result.data)
                    if result.success
                    else {
                        "pid": pid,
                        "alive": False,
                        "error": result.error,
                    }
                )
                process_facts.append(item)
                evidence.append(
                    f"process: pid={pid} alive={item.get('alive')}"
                )
            facts["processes"] = process_facts
            return evidence or ["process probe found no referenced process"]

        # Experience comparison is cognition over ZN-owned state, not a body
        # movement, so keep the parent's resident-side implementation when no
        # consolidated schema was activated.
        return super()._run_probe(
            key,
            event,
            readiness,
            facts=facts,
            learning_evidence=learning_evidence,
        )

    @staticmethod
    def _answer_from_native_facts(event: AgentEvent, facts: dict[str, Any]) -> str:
        response = NativeInvestigator._answer_from_native_facts(event, facts)
        if response:
            return response
        if event.kind != "intention_probe":
            return ""

        predictions = facts.get("schema_predictions")
        if not isinstance(predictions, list) or not predictions:
            return ""
        concrete = {
            key: value
            for key, value in facts.items()
            if key not in {
                "related_experience_count",
                "schema_predictions",
                "schema_prediction_feedback",
                "schema_reconsolidation_keys",
                "schema_structural_merges",
            }
            and value not in (None, [], {}, "")
        }
        if not concrete:
            return ""

        prediction = predictions[0]
        summary = str(prediction.get("summary") or "a consolidated pattern")[:360]
        observed = ", ".join(sorted(concrete.keys()))[:180]
        return (
            "Native intention probe completed. I activated the consolidated "
            f"pattern '{summary}' and checked current {observed} evidence. "
            "The pattern remains a hypothesis: this observation updates my "
            "current state without treating past experience as proof."
        )

    @staticmethod
    def _schema_evidence(
        learning_evidence: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        schemas = [
            item
            for item in learning_evidence
            if item.get("consolidated") is True
            or item.get("resolution_source") == "neural:schema"
        ]
        schemas.sort(
            key=lambda item: (
                float(item.get("similarity") or 0.0),
                float(item.get("salience") or 0.0),
            ),
            reverse=True,
        )
        return schemas