"""ZN Agent resident kernel.

The resident kernel is the persistent agent. Language models are replaceable,
on-demand cognitive resources rather than the holder of identity or continuity.
"""

from .action import NativeActionIntent, derive_native_action_intent
from .action_execution import (
    ActionExecution,
    ActionExecutionRuntime,
    ActionObservation,
    ActionRequest,
    ActionVerification,
    build_machine_action_execution_runtime,
)
from .action_fabric import (
    ActionAvailability,
    ActionDescriptor,
    ActionFabricRegistry,
    build_machine_action_fabric,
)
from .app_competence import AppCompetenceBinding, AppCompetencePack, AppCompetenceRegistry
from .body import BodyAction, BodyActionResult, NativeBody
from .visual_action_reasoner import (
    GeminiVisualActionReasoner,
    VisualActionDecision,
    VisualActionInference,
    parse_visual_action_decision,
)
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
from .nervous_system import (
    AffectiveState,
    NeuralActivation,
    NeuralConsolidationReport,
    NeuralTrace,
    PersistentNervousSystem,
)
from .provider_bridge import (
    build_resident_runtime,
    build_resident_runtime_from_existing_stack,
    build_runtime,
    build_runtime_from_existing_stack,
    resolve_zn_routes,
    route_from_spec,
)
from .resident import ZNResidentRuntime
from .router import ModelRouter, NoRouteAvailable
from .runtime import ZNKernelRuntime
from .service import ResidentAlreadyRunning, ResidentService
from .self_model import DomainReadiness, SelfModel, TaskReadiness
from .store import KernelStore
from .will import NativeWill, ResidentIntention
from .worker import Worker, WorkerFactory
from .world_sense import NativeWorldSense, WorldFocus, WorldObservation

__all__ = [
    "ActionAvailability",
    "ActionDescriptor",
    "ActionExecution",
    "ActionExecutionRuntime",
    "ActionFabricRegistry",
    "ActionObservation",
    "ActionRequest",
    "ActionVerification",
    "AffectiveState",
    "AgentEvent",
    "AgentIdentity",
    "AppCompetenceBinding",
    "AppCompetencePack",
    "AppCompetenceRegistry",
    "Assessment",
    "BodyAction",
    "BodyActionResult",
    "GeminiVisualActionReasoner",
    "BodyState",
    "build_resident_runtime",
    "build_resident_runtime_from_existing_stack",
    "build_runtime",
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
    "NativeWorldSense",
    "NeuralActivation",
    "NeuralConsolidationReport",
    "NeuralTrace",
    "NoRouteAvailable",
    "PersistentNervousSystem",
    "PromotedCapabilityLoader",
    "ResidentAlreadyRunning",
    "ResidentIntention",
    "ResidentRunResult",
    "ResidentService",
    "resolve_zn_routes",
    "route_from_spec",
    "RuntimeMetrics",
    "SelfModel",
    "SituationModel",
    "StructuredMemory",
    "TaskReadiness",
    "ThoughtFrame",
    "VisualActionDecision",
    "VisualActionInference",
    "Worker",
    "WorkerFactory",
    "parse_visual_action_decision",
    "WorkerResult",
    "WorkingState",
    "WorldFocus",
    "WorldObservation",
    "build_machine_action_execution_runtime",
    "build_machine_action_fabric",
    "ZNKernelRuntime",
    "ZNLifeCore",
    "ZNResidentRuntime",
]
