from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from threading import Lock
from typing import Any


_UTC_NOW_LOCK = Lock()
_LAST_UTC_NOW: datetime | None = None


def utc_now() -> str:
    """Return a process-monotonic UTC timestamp suitable for freshness identity.

    Wall-clock reads can repeat at microsecond resolution (or move backwards after
    a clock adjustment). Several resident authority contracts use exact timestamp
    equality as freshness evidence, so every in-process observation timestamp must
    advance even when the platform clock does not.
    """

    global _LAST_UTC_NOW
    with _UTC_NOW_LOCK:
        now = datetime.now(timezone.utc)
        if _LAST_UTC_NOW is not None and now <= _LAST_UTC_NOW:
            now = _LAST_UTC_NOW + timedelta(microseconds=1)
        _LAST_UTC_NOW = now
        return now.isoformat()


class GoalStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ProposalStatus(str, Enum):
    PROPOSED = "proposed"
    EXPERIMENTING = "experimenting"
    REJECTED = "rejected"
    PROMOTED = "promoted"


class EventStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class ExecutionPath(str, Enum):
    MEMORY = "memory"
    CAPABILITY = "capability"
    INVESTIGATION = "investigation"
    BODY = "body"
    MODEL = "model"
    BUDGET_BLOCKED = "budget_blocked"


@dataclass(slots=True)
class AgentIdentity:
    name: str = "ZN Agent"
    version: str = "0.2.0"
    purpose: str = (
        "Persist as a resident digital agent, pursue goals, solve routine work "
        "without model calls when possible, and use models only as replaceable "
        "cognitive resources for novel or difficult work."
    )
    principles: tuple[str, ...] = (
        "The resident kernel owns identity, goals, state, and decisions; models are tools.",
        "Prefer learned local capability over repeated model reasoning.",
        "Minimize model dependency without sacrificing verified task success.",
        "Do not claim improvement without evidence.",
        "Never replace the live runtime with an unverified candidate.",
        "Prefer reversible changes and preserve rollback paths.",
    )
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)


@dataclass(slots=True)
class ModelRoute:
    route_id: str
    provider: str
    model: str
    capabilities: dict[str, float] = field(default_factory=dict)
    reliability: float = 0.8
    cost_weight: float = 0.5
    latency_weight: float = 0.5
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Goal:
    goal_id: str
    task: str
    required_capabilities: tuple[str, ...] = ("general",)
    priority: int = 0
    status: GoalStatus = GoalStatus.PENDING
    attempts: int = 0
    route_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)


@dataclass(slots=True)
class WorkerResult:
    success: bool
    response: str = ""
    verification_passed: bool | None = None
    error: str | None = None
    metrics: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Assessment:
    success: bool
    quality: float
    confidence: float
    reasons: tuple[str, ...] = ()


@dataclass(slots=True)
class Experience:
    experience_id: str
    goal_id: str
    route_id: str
    task: str
    required_capabilities: tuple[str, ...]
    assessment: Assessment
    response_excerpt: str = ""
    error: str | None = None
    metrics: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now)


@dataclass(slots=True)
class CapabilityEstimate:
    name: str
    score: float = 0.5
    evidence_count: int = 0
    confidence: float = 0.0
    updated_at: str = field(default_factory=utc_now)


@dataclass(slots=True)
class ImprovementProposal:
    proposal_id: str
    goal_id: str
    capability: str
    hypothesis: str
    experiment: str
    scope: str = "skill_or_policy"
    benchmark_required: bool = True
    status: ProposalStatus = ProposalStatus.PROPOSED
    created_at: str = field(default_factory=utc_now)


@dataclass(slots=True)
class KernelRunResult:
    goal: Goal
    route: ModelRoute
    worker_result: WorkerResult
    assessment: Assessment
    experiences: tuple[Experience, ...]
    proposal: ImprovementProposal | None = None


@dataclass(slots=True)
class AgentEvent:
    event_id: str
    task: str
    kind: str = "user_task"
    priority: int = 0
    payload: dict[str, Any] = field(default_factory=dict)
    status: EventStatus = EventStatus.PENDING
    attempts: int = 0
    last_error: str | None = None
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)


@dataclass(slots=True)
class WorkingState:
    current_event_id: str | None = None
    current_goal_id: str | None = None
    stage: str = "idle"
    next_action: str | None = None
    blocked_by: str | None = None
    data: dict[str, Any] = field(default_factory=dict)
    updated_at: str = field(default_factory=utc_now)


@dataclass(slots=True)
class CapabilityResult:
    success: bool
    response: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    verification_passed: bool | None = None


@dataclass(slots=True)
class CognitiveDecision:
    use_model: bool
    max_model_calls: int
    reason: str


@dataclass(slots=True)
class CognitionRequest:
    """A bounded question ZN sends to an external cognitive resource.

    It carries the local gap and only the context ZN judged necessary for that
    gap. It is not a serialization of ZN's identity, memory, or full internal
    state.
    """

    request_id: str
    impasse_id: str
    event_id: str
    question: str
    required_capabilities: tuple[str, ...] = ("general",)
    context: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now)


@dataclass(slots=True)
class RuntimeMetrics:
    tasks_total: int = 0
    tasks_model: int = 0
    model_invocations: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    updated_at: str = field(default_factory=utc_now)

    @property
    def model_dependency_ratio(self) -> float:
        if self.tasks_total <= 0:
            return 0.0
        return self.tasks_model / self.tasks_total


@dataclass(slots=True)
class EventOutcome:
    """Durable outcome of one body action, independent of the caller that observed it."""

    event_id: str
    success: bool
    execution_path: ExecutionPath
    response: str = ""
    model_invocations: int = 0
    capability_name: str | None = None
    reason: str = ""
    completed_at: str = field(default_factory=utc_now)


@dataclass(slots=True)
class ResidentRunResult:
    event: AgentEvent
    execution_path: ExecutionPath
    success: bool
    response: str = ""
    model_invocations: int = 0
    capability_name: str | None = None
    reason: str = ""
    kernel_result: KernelRunResult | None = None
