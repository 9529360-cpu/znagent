# ZN Delegated Work and Resource Routing Design

> Design snapshot: 2026-09-04
>
> This document is a target design for the next product stages. It does not claim that all structures below already exist. Current implementation facts remain in `docs/ZN-IMPLEMENTATION-STATUS.md`.

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

Already present:

- durable `WorkThread`, `WorkMessage`, `WorkArtifact`, `WorkRun` in `ResidentWorkLedger`;
- explicit Work lifecycle control in `ResidentWorkControl`;
- resident event/outcome persistence and restart recovery;
- non-replay / fresh-evidence safety disciplines;
- `Goal.required_capabilities`;
- `ModelRoute` capability, reliability, cost and latency metadata;
- kernel-owned `ModelRouter`;
- evidence-backed external route learning in `SelfModel`;
- multiple provider protocols and hot reconfiguration;
- bounded `CognitiveResource` calls.

Not currently present as a coherent product capability:

- durable hierarchical SubWork/WorkItem records;
- dependency readiness;
- per-item acceptance criteria/evidence;
- delegated executor lifecycle;
- one-model-many-worker semantics;
- per-SubWork model-policy routing;
- stall/no-progress supervision;
- active user steering over delegated work;
- stale-result rejection after plan changes;
- long-task user progress UX.

## 3. Core data model

The smallest useful extension is to add durable WorkItems below an existing WorkThread.

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

### 3.2 WorkerRun

One WorkItem can have multiple attempts/runs.

```text
WorkerRun
- worker_run_id
- item_id
- plan_version
- executor_kind
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

### 8.1 Existing score inputs

Current code already combines:

- required capability score;
- evidence-backed learned route performance;
- reliability;
- cost weight;
- latency weight.

Preserve this base.

### 8.2 Additional policy gates before scoring

A route should be eligible only when it satisfies user/project constraints such as:

```text
allowed provider/model
required modality/capability
data locality / cloud restriction
context/tool compatibility
budget ceiling
concurrency/rate-limit health
user pin/deny policy
```

Hard policy filters happen before soft scoring.

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

### 8.5 Multi-model routing

With multiple allowed routes:

- code work can prefer coding-strength routes;
- visual interpretation can prefer vision-capable routes;
- bounded classification can prefer cheaper/smaller routes;
- hard planning can stay on the preferred strong reasoning route;
- route failure may trigger another eligible route;
- route learning can update `SelfModel` from verified outcomes.

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

PR #166's natural Work continuation should be reconciled rather than duplicated; active steering is the next layer on top of that continuity work.

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

## 19. Phased implementation order

### Stage A — Root Work steering + durable WorkItem minimum

Real E2E:

> “昨天那个产品继续。登录先别做，先把核心记账跑起来。”

Need:

- reconcile/land natural Work continuation work;
- minimal WorkItem records;
- active steering/plan version;
- preserve non-replay of completed effects.

### Stage B — Single-model delegated coding/research task

Real E2E:

> “帮我调研并开发一个小产品第一版。”

Need:

- at least research + coding WorkItems;
- same model route may execute both in isolated worker contexts;
- tools differ per worker;
- root verification remains ZN-owned.

### Stage C — Multi-model routing under user policy

Real E2E:

> “平时你用 GPT 跟我沟通，代码优先 Codex，调研你自己选，项目内容不要发给其他未授权模型。”

Need:

- user route policy;
- per-WorkItem required capabilities;
- existing `ModelRouter` policy filtering + selection;
- route fallback/health handling;
- route provenance in WorkerRun.

### Stage D — Supervision, stall detection, reroute

Real E2E:

> coding worker fails twice; ZN detects no progress, gathers fresh error evidence, changes route or approach and continues without asking the user for each mechanical retry.

### Stage E — Restart/background long task

Real E2E:

> “这个产品你继续做，我先去忙。” Resident restarts; ZN resumes from durable Work, reconciles attempts, continues safely, and later reports verified progress.

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

ZN remains one long-lived personal assistant. Complex work is represented as one durable Root Work with bounded WorkItems. ZN may create zero, one or many WorkerRuns; those workers may share one model or use different models. The existing kernel-owned ModelRouter chooses eligible cognition resources under user policy and learned performance. Tools provide real-world execution. ZN supervises, replans, verifies and remains the only owner of the user's task.