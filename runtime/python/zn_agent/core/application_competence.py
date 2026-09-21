from __future__ import annotations

"""Version-gated, evidence-only application competence contracts.

Competence data can describe reusable app/version UI knowledge, but it never
selects or executes a Body action and never grants authority. Runtime callers
must independently observe the current application/UI and pass ordinary ZN
authority, Action Fabric and completion-verification boundaries.
"""

from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime
from pathlib import PureWindowsPath
from typing import Any, Literal, Mapping, Sequence

ApplicabilityStatus = Literal["supported", "mismatched", "untested"]
CompletionCondition = Literal["target_present", "target_absent", "progress_complete"]

_MAX_TEXT = 240
_MAX_VERSIONS = 16
_MAX_STAGES = 24
_MAX_SELECTORS = 8
_MAX_EVIDENCE_VERSIONS = 16


def _text(value: Any, *, field_name: str, required: bool = False) -> str:
    text = str(value or "").strip()
    if required and not text:
        raise ValueError(f"{field_name} is required")
    if len(text) > _MAX_TEXT:
        raise ValueError(f"{field_name} exceeds {_MAX_TEXT} characters")
    return text


def _unknown_keys(raw: Mapping[str, Any], allowed: set[str], *, scope: str) -> None:
    unknown = sorted(str(key) for key in set(raw) - allowed)
    if unknown:
        raise ValueError(f"{scope} contains unsupported fields: {unknown}")


def _boolean(value: Any, *, field_name: str, default: bool) -> bool:
    if value is None:
        return default
    if not isinstance(value, bool):
        raise ValueError(f"{field_name} must be a boolean")
    return value


def _mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if is_dataclass(value):
        return dict(asdict(value))
    raise TypeError(f"expected mapping/dataclass evidence, got {type(value).__name__}")


def _timestamp(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed


def _after(value: Any, boundary: str | None) -> bool | None:
    if boundary is None:
        return True
    observed = _timestamp(value)
    required = _timestamp(boundary)
    if observed is None or required is None:
        return None
    return observed >= required


def _status(mismatched: Sequence[str], untested: Sequence[str]) -> ApplicabilityStatus:
    if mismatched:
        return "mismatched"
    if untested:
        return "untested"
    return "supported"


@dataclass(frozen=True, slots=True)
class ApplicationIdentityContract:
    canonical_name: str
    accepted_versions: tuple[str, ...]
    executable_name: str = ""
    publisher: str = ""
    package_identity: str = ""

    def __post_init__(self) -> None:
        if not self.canonical_name.strip():
            raise ValueError("application canonical_name is required")
        if not self.accepted_versions:
            raise ValueError("competence application requires at least one exact accepted version")
        if len(self.accepted_versions) > _MAX_VERSIONS:
            raise ValueError(f"competence application supports at most {_MAX_VERSIONS} versions")
        if any(not str(value).strip() or len(str(value).strip()) > _MAX_TEXT for value in self.accepted_versions):
            raise ValueError("accepted_versions must contain bounded non-empty exact version strings")
        for field_name in ("canonical_name", "executable_name", "publisher", "package_identity"):
            if len(str(getattr(self, field_name) or "")) > _MAX_TEXT:
                raise ValueError(f"{field_name} exceeds {_MAX_TEXT} characters")


@dataclass(frozen=True, slots=True)
class UiDescriptor:
    descriptor_id: str
    control_type: int
    name_equals: str = ""
    automation_id_equals: str = ""
    class_name_equals: str = ""
    framework_id_equals: str = ""
    require_enabled: bool = True
    require_onscreen: bool = True

    def __post_init__(self) -> None:
        if not self.descriptor_id.strip():
            raise ValueError("descriptor_id is required")
        if int(self.control_type) <= 0:
            raise ValueError("control_type must be positive")
        anchors = (
            self.name_equals,
            self.automation_id_equals,
            self.class_name_equals,
        )
        if not any(str(value).strip() for value in anchors):
            raise ValueError("UI descriptor requires name, automation id, or class-name anchor")
        for field_name in (
            "descriptor_id",
            "name_equals",
            "automation_id_equals",
            "class_name_equals",
            "framework_id_equals",
        ):
            if len(str(getattr(self, field_name) or "")) > _MAX_TEXT:
                raise ValueError(f"{field_name} exceeds {_MAX_TEXT} characters")


@dataclass(frozen=True, slots=True)
class ApplicationCompetenceStage:
    stage_id: str
    label: str
    selectors: tuple[UiDescriptor, ...]
    completion_condition: CompletionCondition = "target_present"
    requires_progress_observation: bool = False

    def __post_init__(self) -> None:
        if not self.stage_id.strip() or not self.label.strip():
            raise ValueError("competence stage_id and label are required")
        if not self.selectors or len(self.selectors) > _MAX_SELECTORS:
            raise ValueError(f"competence stage requires 1..{_MAX_SELECTORS} selector variants")
        if self.completion_condition not in {"target_present", "target_absent", "progress_complete"}:
            raise ValueError(f"unsupported completion_condition: {self.completion_condition}")
        if len(self.stage_id) > _MAX_TEXT or len(self.label) > _MAX_TEXT:
            raise ValueError("competence stage id/label exceeds the bounded text limit")
        if self.requires_progress_observation != (self.completion_condition == "progress_complete"):
            raise ValueError("progress observation must be explicit exactly for progress_complete stages")


@dataclass(frozen=True, slots=True)
class ApplicationCompetencePack:
    schema_version: int
    pack_id: str
    revision: int
    action_id: str
    application: ApplicationIdentityContract
    stages: tuple[ApplicationCompetenceStage, ...]
    evidence_versions: tuple[tuple[str, int], ...] = ()

    def __post_init__(self) -> None:
        if int(self.schema_version) != 1:
            raise ValueError("only application competence schema_version=1 is supported")
        if not self.pack_id.strip() or not self.action_id.strip():
            raise ValueError("pack_id and action_id are required")
        if len(self.pack_id) > _MAX_TEXT or len(self.action_id) > _MAX_TEXT:
            raise ValueError("pack_id/action_id exceeds the bounded text limit")
        if int(self.revision) <= 0:
            raise ValueError("competence revision must be positive")
        if not self.stages or len(self.stages) > _MAX_STAGES:
            raise ValueError(f"competence pack requires 1..{_MAX_STAGES} stages")
        stage_ids = [stage.stage_id for stage in self.stages]
        if len(set(stage_ids)) != len(stage_ids):
            raise ValueError("competence stage ids must be unique")
        if len(self.evidence_versions) > _MAX_EVIDENCE_VERSIONS:
            raise ValueError("too many evidence version contracts")
        for name, version in self.evidence_versions:
            if not str(name).strip() or len(str(name)) > _MAX_TEXT or int(version) <= 0:
                raise ValueError("evidence_versions must be bounded names with positive integer versions")

    def stage(self, stage_id: str) -> ApplicationCompetenceStage:
        target = str(stage_id or "").strip()
        for stage in self.stages:
            if stage.stage_id == target:
                return stage
        raise KeyError(f"unknown competence stage: {stage_id}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "pack_id": self.pack_id,
            "revision": self.revision,
            "action_id": self.action_id,
            "application": asdict(self.application),
            "stages": [asdict(stage) for stage in self.stages],
            "evidence_versions": dict(self.evidence_versions),
        }


@dataclass(frozen=True, slots=True)
class ApplicabilityEvaluation:
    status: ApplicabilityStatus
    matched_fields: tuple[str, ...]
    mismatched_fields: tuple[str, ...]
    untested_fields: tuple[str, ...]
    selected_descriptor_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _evaluation(
    *,
    matched: Sequence[str],
    mismatched: Sequence[str],
    untested: Sequence[str],
    selected_descriptor_id: str = "",
) -> ApplicabilityEvaluation:
    return ApplicabilityEvaluation(
        status=_status(mismatched, untested),
        matched_fields=tuple(dict.fromkeys(matched)),
        mismatched_fields=tuple(dict.fromkeys(mismatched)),
        untested_fields=tuple(dict.fromkeys(untested)),
        selected_descriptor_id=selected_descriptor_id,
    )


def evaluate_application_identity(
    contract: ApplicationIdentityContract,
    application: Any,
    *,
    observed_after: str | None = None,
) -> ApplicabilityEvaluation:
    raw = _mapping(application)
    matched: list[str] = []
    mismatched: list[str] = []
    untested: list[str] = []
    current_name = str(raw.get("canonical_name") or raw.get("display_name") or "").strip()
    if not current_name:
        untested.append("canonical_name")
    elif current_name.casefold() != contract.canonical_name.strip().casefold():
        mismatched.append("canonical_name")
    else:
        matched.append("canonical_name")

    current_version = str(raw.get("version") or "").strip()
    accepted_versions = {str(value).strip() for value in contract.accepted_versions}
    if not current_version:
        untested.append("version")
    elif current_version not in accepted_versions:
        mismatched.append("version")
    else:
        matched.append("version")

    if contract.executable_name:
        executable = str(raw.get("executable_path") or "").strip()
        if not executable:
            untested.append("executable_name")
        elif PureWindowsPath(executable).name.casefold() != contract.executable_name.casefold():
            mismatched.append("executable_name")
        else:
            matched.append("executable_name")

    for field_name in ("publisher", "package_identity"):
        required = str(getattr(contract, field_name) or "").strip()
        if not required:
            continue
        current = str(raw.get(field_name) or "").strip()
        if not current:
            untested.append(field_name)
        elif current.casefold() != required.casefold():
            mismatched.append(field_name)
        else:
            matched.append(field_name)

    fresh = _after(raw.get("observed_at"), observed_after)
    if fresh is None:
        untested.append("application_freshness")
    elif fresh is False:
        mismatched.append("application_freshness")
    elif observed_after is not None:
        matched.append("application_freshness")

    return _evaluation(matched=matched, mismatched=mismatched, untested=untested)


def evaluate_ui_descriptor(
    descriptor: UiDescriptor,
    observation: Any,
    *,
    captured_after: str | None = None,
) -> ApplicabilityEvaluation:
    raw = _mapping(observation)
    matched: list[str] = []
    mismatched: list[str] = []
    untested: list[str] = []
    try:
        current_control_type = int(raw.get("control_type") or 0)
    except (TypeError, ValueError):
        current_control_type = 0
    if current_control_type <= 0:
        untested.append("control_type")
    elif current_control_type != int(descriptor.control_type):
        mismatched.append("control_type")
    else:
        matched.append("control_type")

    comparisons = (
        ("name", descriptor.name_equals, "name", False),
        ("automation_id", descriptor.automation_id_equals, "automation_id", False),
        ("class_name", descriptor.class_name_equals, "class_name", True),
        ("framework_id", descriptor.framework_id_equals, "framework_id", True),
    )
    for label, expected, raw_key, casefold in comparisons:
        expected_text = str(expected or "").strip()
        if not expected_text:
            continue
        current = str(raw.get(raw_key) or "").strip()
        if not current:
            untested.append(label)
            continue
        left = current.casefold() if casefold else current
        right = expected_text.casefold() if casefold else expected_text
        if left != right:
            mismatched.append(label)
        else:
            matched.append(label)

    if descriptor.require_enabled:
        if "is_enabled" not in raw:
            untested.append("enabled")
        elif raw.get("is_enabled") is not True:
            mismatched.append("enabled")
        else:
            matched.append("enabled")
    if descriptor.require_onscreen:
        if "is_offscreen" not in raw:
            untested.append("onscreen")
        elif raw.get("is_offscreen") is not False:
            mismatched.append("onscreen")
        else:
            matched.append("onscreen")

    captured_at = raw.get("captured_at") or raw.get("observed_at")
    fresh = _after(captured_at, captured_after)
    if fresh is None:
        untested.append("ui_freshness")
    elif fresh is False:
        mismatched.append("ui_freshness")
    elif captured_after is not None:
        matched.append("ui_freshness")

    return _evaluation(
        matched=matched,
        mismatched=mismatched,
        untested=untested,
        selected_descriptor_id=descriptor.descriptor_id if not mismatched and not untested else "",
    )


def _selector_evaluations(
    stage: ApplicationCompetenceStage,
    observations: Sequence[Any],
    *,
    captured_after: str | None,
) -> list[ApplicabilityEvaluation]:
    return [
        evaluate_ui_descriptor(descriptor, observation, captured_after=captured_after)
        for descriptor in stage.selectors
        for observation in observations
    ]


def evaluate_competence_stage(
    stage: ApplicationCompetenceStage,
    observations: Sequence[Any],
    *,
    captured_after: str | None = None,
    observation_complete: bool = False,
    progress_complete: bool | None = None,
) -> ApplicabilityEvaluation:
    if isinstance(observations, (str, bytes, Mapping)):
        raise TypeError("observations must be a sequence of current UI evidence")
    rows = _selector_evaluations(stage, observations, captured_after=captured_after)
    supported = next((row for row in rows if row.status == "supported"), None)
    potentially_supported = any(row.status == "untested" for row in rows)

    if stage.completion_condition == "target_present":
        if supported is not None:
            return supported
        if not observations or potentially_supported:
            return _evaluation(matched=(), mismatched=(), untested=("target_present",))
        return _evaluation(matched=(), mismatched=("target_present",), untested=())

    if stage.completion_condition == "target_absent":
        if supported is not None:
            return _evaluation(
                matched=(),
                mismatched=("target_absent",),
                untested=(),
                selected_descriptor_id=supported.selected_descriptor_id,
            )
        if not observation_complete:
            return _evaluation(matched=(), mismatched=(), untested=("complete_ui_enumeration",))
        if potentially_supported:
            return _evaluation(matched=(), mismatched=(), untested=("target_absent",))
        return _evaluation(matched=("target_absent",), mismatched=(), untested=())

    if supported is None:
        if not observations or potentially_supported:
            return _evaluation(matched=(), mismatched=(), untested=("progress_target",))
        return _evaluation(matched=(), mismatched=("progress_target",), untested=())
    if progress_complete is None:
        return _evaluation(
            matched=("progress_target",),
            mismatched=(),
            untested=("progress_complete",),
            selected_descriptor_id=supported.selected_descriptor_id,
        )
    if progress_complete is not True:
        return _evaluation(
            matched=("progress_target",),
            mismatched=("progress_complete",),
            untested=(),
            selected_descriptor_id=supported.selected_descriptor_id,
        )
    return _evaluation(
        matched=("progress_target", "progress_complete"),
        mismatched=(),
        untested=(),
        selected_descriptor_id=supported.selected_descriptor_id,
    )


def evaluate_evidence_versions(
    pack: ApplicationCompetencePack,
    current_versions: Mapping[str, Any] | None,
) -> ApplicabilityEvaluation:
    matched: list[str] = []
    mismatched: list[str] = []
    untested: list[str] = []
    current = current_versions if isinstance(current_versions, Mapping) else {}
    for name, expected_version in pack.evidence_versions:
        if name not in current:
            untested.append(f"evidence_version:{name}")
            continue
        try:
            observed_version = int(current[name])
        except (TypeError, ValueError):
            mismatched.append(f"evidence_version:{name}")
            continue
        if observed_version != expected_version:
            mismatched.append(f"evidence_version:{name}")
        else:
            matched.append(f"evidence_version:{name}")
    return _evaluation(matched=matched, mismatched=mismatched, untested=untested)


def evaluate_competence(
    pack: ApplicationCompetencePack,
    application: Any,
    *,
    stage_id: str,
    observations: Sequence[Any],
    application_observed_after: str | None = None,
    ui_captured_after: str | None = None,
    observation_complete: bool = False,
    progress_complete: bool | None = None,
    current_evidence_versions: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    app = evaluate_application_identity(
        pack.application,
        application,
        observed_after=application_observed_after,
    )
    evidence = evaluate_evidence_versions(pack, current_evidence_versions)
    stage = pack.stage(stage_id)
    stage_result = evaluate_competence_stage(
        stage,
        observations,
        captured_after=ui_captured_after,
        observation_complete=observation_complete,
        progress_complete=progress_complete,
    )
    overall = (
        "mismatched"
        if "mismatched" in {app.status, evidence.status, stage_result.status}
        else "untested"
        if "untested" in {app.status, evidence.status, stage_result.status}
        else "supported"
    )
    return {
        "status": overall,
        "pack_id": pack.pack_id,
        "revision": pack.revision,
        "action_id": pack.action_id,
        "stage_id": stage.stage_id,
        "application": app.to_dict(),
        "evidence": evidence.to_dict(),
        "stage": stage_result.to_dict(),
        "evidence_versions": dict(pack.evidence_versions),
    }


def application_competence_from_dict(raw: Mapping[str, Any]) -> ApplicationCompetencePack:
    _unknown_keys(
        raw,
        {"schema_version", "pack_id", "revision", "action_id", "application", "stages", "evidence_versions"},
        scope="competence pack",
    )
    app_raw = raw.get("application")
    if not isinstance(app_raw, Mapping):
        raise ValueError("competence application must be an object")
    _unknown_keys(
        app_raw,
        {"canonical_name", "accepted_versions", "executable_name", "publisher", "package_identity"},
        scope="competence application",
    )
    versions_raw = app_raw.get("accepted_versions")
    if isinstance(versions_raw, (str, bytes)) or not isinstance(versions_raw, Sequence):
        raise ValueError("accepted_versions must be an ordered sequence")
    application = ApplicationIdentityContract(
        canonical_name=_text(app_raw.get("canonical_name"), field_name="canonical_name", required=True),
        accepted_versions=tuple(str(value).strip() for value in versions_raw),
        executable_name=_text(app_raw.get("executable_name"), field_name="executable_name"),
        publisher=_text(app_raw.get("publisher"), field_name="publisher"),
        package_identity=_text(app_raw.get("package_identity"), field_name="package_identity"),
    )

    stages_raw = raw.get("stages")
    if isinstance(stages_raw, (str, bytes, Mapping)) or not isinstance(stages_raw, Sequence):
        raise ValueError("competence stages must be an ordered sequence")
    stages: list[ApplicationCompetenceStage] = []
    for index, stage_raw in enumerate(stages_raw, start=1):
        if not isinstance(stage_raw, Mapping):
            raise ValueError(f"competence stage {index} must be an object")
        _unknown_keys(
            stage_raw,
            {"stage_id", "label", "selectors", "completion_condition", "requires_progress_observation"},
            scope=f"competence stage {index}",
        )
        selectors_raw = stage_raw.get("selectors")
        if isinstance(selectors_raw, (str, bytes, Mapping)) or not isinstance(selectors_raw, Sequence):
            raise ValueError(f"competence stage {index} selectors must be an ordered sequence")
        selectors: list[UiDescriptor] = []
        for selector_index, selector_raw in enumerate(selectors_raw, start=1):
            if not isinstance(selector_raw, Mapping):
                raise ValueError(f"stage {index} selector {selector_index} must be an object")
            _unknown_keys(
                selector_raw,
                {
                    "descriptor_id", "control_type", "name_equals", "automation_id_equals",
                    "class_name_equals", "framework_id_equals", "require_enabled", "require_onscreen",
                },
                scope=f"stage {index} selector {selector_index}",
            )
            selectors.append(
                UiDescriptor(
                    descriptor_id=_text(selector_raw.get("descriptor_id"), field_name="descriptor_id", required=True),
                    control_type=int(selector_raw.get("control_type") or 0),
                    name_equals=_text(selector_raw.get("name_equals"), field_name="name_equals"),
                    automation_id_equals=_text(selector_raw.get("automation_id_equals"), field_name="automation_id_equals"),
                    class_name_equals=_text(selector_raw.get("class_name_equals"), field_name="class_name_equals"),
                    framework_id_equals=_text(selector_raw.get("framework_id_equals"), field_name="framework_id_equals"),
                    require_enabled=_boolean(selector_raw.get("require_enabled"), field_name="require_enabled", default=True),
                    require_onscreen=_boolean(selector_raw.get("require_onscreen"), field_name="require_onscreen", default=True),
                )
            )
        stages.append(
            ApplicationCompetenceStage(
                stage_id=_text(stage_raw.get("stage_id"), field_name="stage_id", required=True),
                label=_text(stage_raw.get("label"), field_name="stage label", required=True),
                selectors=tuple(selectors),
                completion_condition=str(stage_raw.get("completion_condition") or "target_present"),  # type: ignore[arg-type]
                requires_progress_observation=_boolean(stage_raw.get("requires_progress_observation"), field_name="requires_progress_observation", default=False),
            )
        )

    evidence_raw = raw.get("evidence_versions") or {}
    if not isinstance(evidence_raw, Mapping):
        raise ValueError("evidence_versions must be an object")
    evidence_versions = tuple(
        sorted(
            (_text(name, field_name="evidence version name", required=True), int(version))
            for name, version in evidence_raw.items()
        )
    )
    return ApplicationCompetencePack(
        schema_version=int(raw.get("schema_version") or 0),
        pack_id=_text(raw.get("pack_id"), field_name="pack_id", required=True),
        revision=int(raw.get("revision") or 0),
        action_id=_text(raw.get("action_id"), field_name="action_id", required=True),
        application=application,
        stages=tuple(stages),
        evidence_versions=evidence_versions,
    )
