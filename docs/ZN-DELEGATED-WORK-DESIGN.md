# ZN Delegated Work and Resource Routing Design

> Design snapshot: 2026-09-06
>
> Canonical branch: `main`; active development uses short-lived `work/*` branches from current `main`.
>
> This document combines the delegated-work target design with a narrow current-state overlay. It does not claim that every target structure below is product-closed. Current implementation facts remain authoritative in `docs/ZN-IMPLEMENTATION-STATUS.md`, and real acceptance status remains authoritative in `docs/ZN-REAL-TASK-E2E-CATALOG.md`.

## 1. Design objective

Enable one ZN Resident to own and supervise long-running user goals that may require:

- clarification;
- web investigation;
- files and documents;
- browser and desktop work;
- terminal/Git/code changes;
- one or more specialist models;
- multiple isolated workers;
- user steering during execution;
- restart/cross-day continuation;
- independent completion verification.

The design must preserve the current architecture:

```text
Self owns identity
Will owns intention
Work owns durable task continuity
Situation owns current task/world interpretation
Thought / Investigation choose what to do next
CognitiveResource supplies bounded external cognition
Body / tools act and sense
Recovery protects uncertain side effects
Memory preserves lived context/learning
```

No new top-level orchestrator subject is introduced.

## 2. Current implementation baseline

As of 2026-09-06, the following are present in the active product/runtime substrate:

- durable `WorkThread`, `WorkMessage`, `WorkArtifact`, `WorkRun` in `ResidentWorkLedger`;
- explicit Work lifecycle control in `ResidentWorkControl`;
- resident event/outcome persistence and restart recovery;
- non-replay / fresh-evidence safety disciplines;
- plan-version and stale-result foundations for active Work steering/continuation;
- bounded delegation admission owned by Resident rather than keyword coincidence alone;
- a Resident-internal `DelegatedWorkCoordinator` that materializes/supervises delegated WorkItem/WorkerRun state without owning a second store/router/control plane;
- durable WorkerRun lifecycle records for the flat delegated-worker path;
- `Goal.required_capabilities`;
- kernel-owned `ModelRouter` with hard eligibility gates before soft scoring;
- route pin/deny, capability, declared availability/health, locality/privacy and authority-policy filtering;
- evidence-backed external route learning in `SelfModel`;
- multiple provider protocols and hot reconfiguration;
- bounded `CognitiveResource` calls;
- strict recursive `WorkerContextPack` serialization/sanitization boundary with provenance/data-classification support;
- action-time WorkerRun authority admission at the existing Body boundary;
- E2E-29 **CLOSED / VERIFIED** for the narrow `single-route multi-WorkerRun` substrate: one real route can serve multiple durable research/coding/review WorkerRuns and Root completion remains independently verified.

Still not product-closed as coherent general capability:

- general hierarchical SubWork trees or recursive delegation; current implementation intentionally remains flat/bounded;
- broad dependency-graph scheduling/readiness beyond the current narrow delegated phases;
- dynamic `ResidentHealthJournal` → route eligibility/reroute integration;
- systematic heartbeat/no-progress/stall supervision and restart-safe replacement WorkerRun behavior;
- real E2E-30 multi-route task-specific routing under user policy;
- real E2E-42 privacy/locality routing acceptance;
- E2E-27/E2E-33 normal-language active steering/continuation product acceptance across the delegated supervision path;
- long-task user progress UX at broad product quality.

Important distinction:

```text
substrate exists
≠ named real-task E2E is product-closed
```

Unit tests or CI proving routing/context/authority primitives do not, by themselves, close E2E-30, E2E-42, E2E-27 or E2E-33.

## 3. Core data model

The smallest useful extension is to keep durable WorkItems below an existing WorkThread.

### 3.1 WorkItem

Target conceptual fields:

```text
WorkItem
- item_id
- thread_id
- parent_item_id?          # optional hierarchy; keep shallow initially
- title / objective
- status                   # proposed / ready / running / blocked / completed / cancelled / superseded
- plan_version
- priority
- required_capabilities
- dependency_ids
- executor_policy
- authority_scope
- acceptance_criteria
- result_summary
- blocker_reason
- created_at / updated_at / completed_at
```

Important constraints:

- `thread_id` remains the Root Work identity.
- `parent_item_id` does not create a new Resident or conversation identity.
- completed WorkItems are not rerun merely because another item fails.
- a user plan change may supersede a pending/running item without erasing its historical evidence.
- current active implementation should remain flat unless a real caller/E2E proves hierarchy is necessary.

### 3.2 WorkerRun

One WorkItem can have multiple attempts/runs.

```text
WorkerRun
- worker_run_id
- item_id
- plan_version
- executor_kind / profile_id
- model_route_id?
- tool_scope
- authority_scope
- state                 # queued / running / waiting / completed / failed / cancelled / stale
- started_at / heartbeat_at / finished_at
- result_summary
- artifact_refs
- claimed_completion
- verification_status
- error / blocker
- token/cost/latency metrics
```

A WorkerRun is disposable execution state. It is not a durable personal identity.

Current code has the narrow WorkerRun lifecycle needed by the flat delegated path. Heartbeat/stall/replacement semantics remain future supervision work and must not be inferred merely because a `running` record survives restart.

## 4. Plan version and stale result discipline

Every delegated run binds to the plan version that created it.

Example:

```text
plan v3: build login + ledger
worker A starts coding login under v3
user: “登录先别做，先把核心记账跑起来”
ZN forms plan v4
worker A later returns “login complete”
```

ZN must not silently merge A into v4.

Expected behavior:

```text
returned plan_version < current relevant plan_version
→ mark result stale/pending review
→ preserve artifacts/evidence
→ determine whether any output remains reusable
→ never let stale completion advance root Work automatically
```

This is the delegated-work equivalent of ZN's existing fresh-target discipline.

The plan-version/stale-result control substrate already exists in narrow form. That is not the same as claiming E2E-27/E2E-33 are product-closed across all delegated scenarios.

## 5. Decomposition policy

Do not ask a model to produce an enormous fixed DAG at the beginning of every task.

Use rolling decomposition:

```text
root goal
→ determine current acceptance target
→ identify a small set of next meaningful WorkItems
→ execute/investigate
→ fresh Situation
→ revise/add/cancel WorkItems as reality changes
```

This better matches real computer work and ZN’s Sense/Situation/Thought loop.

Delegation is appropriate when at least one is true:

- work can proceed independently in parallel;
- the subtask would otherwise pollute the root cognition context;
- a specialist model/agent provides clear advantage;
- the task is long-running and benefits from an isolated lifecycle;
- independent review is valuable;
- isolated terminal/workspace execution is safer.

Keep work direct when:

- it is a short deterministic action;
- it needs constant access to the exact evolving root context;
- delegation overhead exceeds the work;
- another worker would contend for the same unsafe mutable resource;
- sequencing is strict and immediate.

Current admission code is intentionally conservative and includes negative/direct semantics. For example, a request equivalent to “不要调研，也不要 review，直接实现” must not manufacture research/review WorkerRuns merely because those words appear in the sentence.

Model-proposed decomposition remains a proposal. Resident owns admission/materialization and must validate objective, acceptance criteria, current plan version, tool/authority scope and relevance before creating WorkerRun state.

## 6. Dependency and readiness

A WorkItem becomes `ready` only when:

```text
all required dependencies are accepted/completed
+ required current-world evidence is fresh enough
+ authority needed for the intended effect exists
+ required resource class is available
+ no current blocker invalidates the item
```

Dependencies are task dependencies, not permission inheritance.

Example:

```text
research market        -> no write authority
choose product scope   -> may use research evidence
develop MVP            -> file/workspace authority
run tests              -> terminal authority
publish/deploy          -> separate explicit external-effect authority
```

Completion of research never grants deployment authority.

Current product code supports the bounded flat sequence needed by E2E-29; a general dependency scheduler/DAG is intentionally not introduced by this remediation.

## 7. Resource stack selection

For every ready WorkItem, ZN chooses a resource stack, not merely a model.

```text
WorkItem
→ cognition requirement?
→ sensing requirement?
→ action tools?
→ data/privacy constraints?
→ authority?
→ verification path?
→ direct vs delegated?
```

Examples:

```text
research competitor pricing
= Web/Browser + optional research cognition + citation verification

fix Python bug
= File/Git/Terminal + coding cognition + tests/runtime verification

rename 200 known files deterministically
= File capability + preview/authority + postcondition verification

inspect why a UI flow changed
= Desktop/Browser Sense + optional vision/reasoning cognition + fresh re-ground
```

## 8. Model routing policy

Do not create a second router. Extend the existing `ModelRouter` input policy and route metadata only as real E2Es require.

### 8.1 Current two-stage routing

Current code now performs:

```text
all ModelRoutes
→ hard eligibility gates
→ eligible routes only
→ SelfModel/reliability/cost/latency soft scoring
→ selected route
```

Hard eligibility currently covers the narrow implemented contracts for:

- required capability declarations;
- user-pinned provider/model;
- denied provider/model;
- declared availability/health metadata;
- local-only / cloud-forbidden / `cloud_denied` data policy;
- required policy tags;
- required authority-policy scopes.

Malformed policy/classification input fails closed. If no route is eligible, routing raises `NoRouteAvailable` rather than silently selecting a forbidden fallback.

The internal zero-model sentinel remains a control-state compatibility path to the existing unavailable-model worker; it is not a real unavailable route that participates in normal route eligibility.

Dynamic runtime health observations from `ResidentHealthJournal` are **not yet** wired into this eligibility layer. That remains part of E2E-28/E2E-34 supervision/reroute work.

### 8.2 Additional policy evolution

Future real E2Es may add hard gates or admission checks such as:

```text
budget ceiling
concurrency/rate-limit state
latency ceiling
richer user/project routing policy
```

The invariant is unchanged: forbidden/ineligible must mean removed from the candidate set, not merely scored lower.

### 8.3 Primary reasoning preference

Users may configure:

```text
primary_reasoning = GPT
coding_preference = Codex/Claude/GPT candidates
research_preference = GPT/Gemini candidates
vision_preference = GPT/Gemini candidates
```

`primary_reasoning` means preferred ZN conversation/general cognition, not exclusive ownership of all WorkItems.

### 8.4 One model, many workers

With one connected model:

```text
worker count can still be > 1
model routes = 1
```

Workers have isolated WorkItem contexts and tool scopes even if they invoke the same model route.

This specific narrow invariant is now real E2E evidence: E2E-29 is CLOSED / VERIFIED. Do not generalize that result into “multi-model routing is complete.”

### 8.5 Multi-model routing

With multiple allowed routes, the target remains:

- code work can prefer coding-strength routes;
- visual interpretation can prefer vision-capable routes;
- bounded classification can prefer cheaper/smaller routes;
- hard planning can stay on the preferred strong reasoning route;
- route failure may trigger another eligible route;
- route learning can update `SelfModel` from verified outcomes.

The hard-eligibility substrate for policy/capability filtering exists. E2E-30 and E2E-42 remain the required real acceptance evidence for true multi-route task-specific/privacy routing.

### 8.6 Routing is not completion authority

A route is selected because it is a good cognitive resource. It never gains authority to:

- approve its own external side effects;
- treat its own text as factual evidence;
- mark Root Work complete;
- persist arbitrary user Memory;
- override user routing/privacy policy.

## 9. Worker context packs

Default worker context should be minimal and explicit.

Conceptual pack:

```text
- root goal summary
- WorkItem objective
- current plan version
- bounded relevant facts/evidence
- relevant artifacts/paths/URLs
- acceptance criteria
- allowed tools
- authority scope
- forbidden actions
- expected result/report schema
```

Avoid by default:

- complete user transcript;
- entire Memory store;
- unrelated project files;
- all credentials;
- all browser tabs;
- hidden internal reasoning from other workers;
- every prior tool log.

This reduces token cost, privacy exposure and cross-task contamination.

Current implementation now uses a strict recursive `WorkerContextPack` boundary rather than relying on every caller to hand-truncate nested evidence. The boundary enforces bounded fields/items/strings, rejects malformed types and sensitive keys, and preserves provenance/data-classification semantics needed by later privacy routing.

## 10. Worker tool/authority scopes

Default principle: least authority needed for the WorkItem.

Example coding worker:

```text
may:
- read selected workspace
- modify scoped files
- run bounded terminal/test commands
- inspect Git diff/status

may not automatically:
- push/merge/release
- access unrelated user files
- message external recipients
- read browser credentials
- modify long-term Memory
- spawn unlimited workers
```

A worker that needs a new side effect requests/escalates through ZN supervision.

The remediation now revalidates WorkerRun authority at the existing Body/action-admission boundary. This means research/review restrictions are not only proposal-parser conventions: the action boundary binds current Work/WorkerRun, plan version, tool/authority/target scope before real effect admission. This is an application authority boundary, not a claim of Windows OS sandbox isolation.

## 11. Supervision loop

ZN supervision should be mostly event/state driven, not a large model repeatedly polling all workers.

```text
worker event / timer / tool result / user message / environment change
→ update Work progress
→ cheap deterministic checks
→ only invoke Thought/model if a real decision gap exists
```

Key supervision events:

- worker completed;
- worker failed;
- worker heartbeat missing;
- waiting on dependency;
- waiting on user permission;
- acceptance verification failed;
- root user changed requirements;
- outside-world state changed;
- resource/model unavailable;
- repeated no-progress.

`DelegatedWorkCoordinator` now owns the bounded delegated lifecycle/reconciliation inside the existing Resident. It does not own a second store, router, Body or identity system.

## 12. Stall/no-progress detection

A long task must not spin forever.

Minimum indicators:

- repeated identical failure category;
- same WorkItem attempt count without new evidence;
- repeated target-not-found with no changed Investigation hypothesis;
- worker heartbeat absent beyond policy;
- model route retry without new context/evidence;
- repeated verification failure.

Response:

```text
stall detected
→ stop blind continuation
→ fresh Sense / inspect current Work evidence
→ Situation
→ Thought / Investigation
→ change hypothesis, resource, route, tool or plan
→ if genuinely blocked, surface one clear blocker to user
```

Current restart reconciliation preserves durable WorkerRun facts and avoids treating old state as proof of current success. A full heartbeat/no-progress/stall/replacement/reroute loop remains open and is specifically part of E2E-28/E2E-34; do not call persistence alone “automatic worker recovery.”

## 13. Acceptance and verification

Each WorkItem should define what evidence makes it complete.

Examples:

```text
research item:
- required questions answered
- sources/provenance present
- contradictions acknowledged

coding item:
- expected diff exists
- relevant tests pass
- target runtime behavior verified

browser mutation:
- fresh page/server/business-state evidence proves saved effect

file task:
- exact destination identity
- bytes/content/metadata checked after write
```

Worker self-report is not acceptance evidence.

Root Work completion requires all root acceptance conditions, not necessarily every historical WorkItem. Superseded/cancelled items may remain intentionally incomplete.

E2E-29 explicitly preserved this distinction: WorkerRun completion and worker self-report were not accepted as Root Work completion without the independent verifier.

## 14. User steering

Steering must modify the active Work rather than create a disconnected new task when the user clearly refers to the current project.

Examples:

- “登录先不做了。”
- “这个方案太复杂，改简单一点。”
- “先别发布，给我看能运行的版本。”
- “测试先用 Claude 看一下，代码继续让 Codex 做。”

Target behavior:

```text
resolve active Root Work
→ interpret steering against current plan
→ increment/revise plan version
→ cancel/supersede affected pending work
→ do not replay completed side effects
→ decide what running workers should continue/cancel/become stale
→ resume from fresh current evidence
```

Natural continuation, active steering, plan-version and stale-result foundations are already implemented in the control substrate. The remaining acceptance gap is broader normal-language E2E-27/E2E-33 proof on the current integrated delegated/supervision path; do not describe the foundation as “not implemented,” but also do not product-close the named E2Es without real runs.

## 15. Restart and cross-day continuity

Persist enough to reconstruct:

- Root Work goal and current acceptance target;
- active/current plan version;
- WorkItems and dependencies;
- running/waiting WorkerRuns;
- accepted evidence;
- unresolved blockers;
- uncertain side effects;
- user routing/privacy policy references;
- relevant artifacts.

On restart:

```text
load durable Work
→ inspect actual worker/process/tool state where possible
→ reconcile completed/unknown attempts
→ re-Sense external world
→ never infer that an old worker heartbeat means current success
→ continue only from reconciled evidence
```

Current code has restart-safe durable Work/WorkerRun reconciliation foundations. If an external side effect outcome is unknown, the governing behavior remains fail closed / do not blindly replay.

## 16. Background autonomy

Background autonomy means ZN can continue a user-authorized Root Work while the UI is not focused or across resident pulses. It does not mean unlimited self-directed activity.

Boundaries:

- Work goal must already exist from user intent or an explicitly authorized recurring rule;
- no silent expansion into unrelated goals;
- external side effects remain authority-gated;
- rate/cost/concurrency budgets apply;
- user can pause/cancel/steer;
- long inactivity or uncertainty can park Work rather than inventing more work.

## 17. User-facing progress model

User should see something like:

```text
正在做：个人记账产品 MVP

已完成
✓ 调研 6 个同类产品
✓ 确定第一版范围

进行中
• 核心记账功能开发
• 数据存储测试

等待
• 发布：需要你的授权

ZN 当前判断
核心功能可以继续推进，不需要你操作。
```

Avoid exposing:

- worker_run_id;
- provider RPC internals;
- semantic target IDs;
- Work recovery internals;
- route-score formulas.

The user may optionally inspect advanced execution detail, but it is not the normal product surface.

## 18. Metrics that matter

Product metrics:

- root Work completion rate;
- long-task completion after user steering;
- restart/cross-day continuation success;
- worker result rejection rate when verification fails;
- recovery from worker/model/tool failure;
- time/cost/token per successful root task;
- percentage of model calls attached to genuine cognition gaps;
- percentage of deterministic mechanics completed without unnecessary large-model calls.

Do not optimize for:

- number of workers spawned;
- number of providers supported;
- raw tool-call count;
- raw token reduction at the expense of success quality.

## 19. Phased implementation / acceptance status

### Stage A — Root Work steering + durable WorkItem minimum

Target E2E:

> “昨天那个产品继续。登录先别做，先把核心记账跑起来。”

Current status:

- natural continuation / active steering / plan-version / stale-result foundations exist;
- bounded WorkItem/WorkerRun substrate exists;
- E2E-27/E2E-33 still require current integrated real-task acceptance before product-close.

### Stage B — Single-model delegated coding/research task

Target E2E:

> “帮我调研并开发一个小产品第一版。”

Current status: **E2E-29 CLOSED / VERIFIED (narrow substrate)**.

Verified invariant:

- research/coding/review WorkerRuns may share one real ModelRoute;
- worker count is independent of route count;
- contexts/tool scopes remain bounded;
- Root completion remains ZN-owned and independently verified.

This does not mean a general-purpose multi-agent platform is complete.

### Stage C — Multi-model routing under user policy

Target E2E:

> “平时你用 GPT 跟我沟通，代码优先 Codex，调研你自己选，项目内容不要发给其他未授权模型。”

Current status:

- hard capability/pin/deny/privacy/locality/authority eligibility substrate is implemented;
- strict WorkerContextPack data classification can feed routing policy;
- real E2E-30/E2E-42 multi-route/privacy acceptance remains open;
- dynamic health-driven reroute remains open.

### Stage D — Supervision, stall detection, reroute

Target E2E:

> coding worker fails twice; ZN detects no progress, gathers fresh error evidence, changes route or approach and continues without asking the user for each mechanical retry.

Current status: reconciliation foundations exist; E2E-28/E2E-34 heartbeat/no-progress/dynamic-health/replacement/reroute loop remains open.

### Stage E — Restart/background long task

Target E2E:

> “这个产品你继续做，我先去忙。” Resident restarts; ZN resumes from durable Work, reconciles attempts, continues safely, and later reports verified progress.

Current status: durable restart/reconciliation foundations exist; broader background long-task product acceptance remains future work.

## 20. Architectural stop signs

Stop and reevaluate if implementation starts producing:

- a new permanent Orchestrator/Manager agent identity;
- another router beside `ModelRouter`;
- a separate graph/workflow persistence store beside Work;
- unrestricted worker inheritance of user context/credentials;
- worker self-report treated as completion;
- recursive agent trees before flat delegation has real E2E value;
- polling loops that repeatedly call large models just to check status;
- routing driven only by model brand names rather than capabilities/policy/evidence;
- abstractions that cannot name a real E2E they unblock.

## 21. Final design statement

ZN remains one long-lived personal assistant. Complex work is represented as one durable Root Work with bounded WorkItems. ZN may create zero, one or many WorkerRuns; those workers may share one model or use different models. The existing kernel-owned ModelRouter first removes ineligible cognition resources under user policy/privacy/capability/authority constraints, then softly ranks only legal candidates using learned performance and route quality signals. Tools provide real-world execution through the existing Body/authority path. ZN supervises, replans, verifies and remains the only owner of the user's task.
