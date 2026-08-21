"""ZN Agent resident kernel.

The resident kernel is the persistent agent. Language models are replaceable,
on-demand cognitive resources rather than the holder of identity or continuity.
"""

from .action import NativeActionIntent, derive_native_action_intent
from .body import BodyAction, BodyActionResult, NativeBody
from .budget import CognitiveBudgetManager
from .capabilities import CapabilityRegistry, CallableCapability, ExactTaskCapability
from .capability_loader import LoadedCapability, PromotedCapabilityLoader
from .cognition import CognitiveIncrement
from .critic import DefaultCritic
from .embodied_investigation import EmbodiedInvestigator
from .embodied_life import CognitiveSituation, EmbodiedLifeCore
from .embodied_resident import EmbodiedResidentRuntime
from .home import get_zn_home
from .intentional_resident import IntentionalResidentRuntime
from .investigation import InvestigationResult, InvestigationState, NativeInvestigator
from .life import (
    BodyState,
    ImpasseState,
    LearningCandidate,
    LifePulse,
    LivingState,
    SituationModel,
    ThoughtFrame,
    ZNLifeCore,
)
from .memory import FactMatch, StructuredMemory
from .provider_bridge import (
    build_resident_runtime_from_existing_stack,
    build_runtime_from_existing_stack,
    resolve_model_routes,
    route_from_spec,
)
from .models import (
    AgentEvent,
    AgentIdentity,
    Assessment,
    CapabilityEstimate,
    CapabilityResult,
    CognitionRequest,
    CognitiveDecision,
    EventOutcome,
    EventStatus,
    ExecutionPath,
    Experience,
    Goal,
    GoalStatus,
    ImprovementProposal,
    KernelRunResult,
    ModelRoute,
    ResidentRunResult,
    RuntimeMetrics,
    WorkerResult,
    WorkingState,
)
from .resident import ZNResidentRuntime
from .router import ModelRouter, NoRouteAvailable
from .runtime import ZNKernelRuntime
from .service import ResidentAlreadyRunning, ResidentService
from .self_model import DomainReadiness, SelfModel, TaskReadiness
from .store import KernelStore
from .will import NativeWill, ResidentIntention
from .worker import LegacyAIAgentWorkerFactory, Worker, WorkerFactory

__all__ = [
    "AgentEvent",
    "AgentIdentity",
    "Assessment",
    "BodyAction",
    "BodyActionResult",
    "BodyState",
    "build_resident_runtime_from_existing_stack",
    "build_runtime_from_existing_stack",
    "CapabilityEstimate",
    "CapabilityRegistry",
    "CapabilityResult",
    "CallableCapability",
    "CognitionRequest",
    "CognitiveBudgetManager",
    "CognitiveDecision",
    "CognitiveIncrement",
    "CognitiveSituation",
    "DefaultCritic",
    "derive_native_action_intent",
    "DomainReadiness",
    "EmbodiedInvestigator",
    "EmbodiedLifeCore",
    "EmbodiedResidentRuntime",
    "EventOutcome",
    "EventStatus",
    "ExactTaskCapability",
    "ExecutionPath",
    "Experience",
    "FactMatch",
    "get_zn_home",
    "Goal",
    "GoalStatus",
    "ImpasseState",
    "IntentionalResidentRuntime",
    "InvestigationResult",
    "InvestigationState",
    "LegacyAIAgentWorkerFactory",
    "ImprovementProposal",
    "KernelRunResult",
    "KernelStore",
    "LearningCandidate",
    "LifePulse",
    "LivingState",
    "LoadedCapability",
    "ModelRoute",
    "ModelRouter",
    "NativeActionIntent",
    "NativeBody",
    "NativeInvestigator",
    "NativeWill",
    "NoRouteAvailable",
    "PromotedCapabilityLoader",
    "ResidentAlreadyRunning",
    "ResidentIntention",
    "ResidentRunResult",
    "ResidentService",
    "resolve_model_routes",
    "route_from_spec",
    "RuntimeMetrics",
    "SelfModel",
    "SituationModel",
    "StructuredMemory",
    "TaskReadiness",
    "ThoughtFrame",
    "Worker",
    "WorkerFactory",
    "WorkerResult",
    "WorkingState",
    "ZNKernelRuntime",
    "ZNLifeCore",
    "ZNResidentRuntime",
]
