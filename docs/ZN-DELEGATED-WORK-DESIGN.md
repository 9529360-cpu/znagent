# ZN Delegated Work and Resource Routing Design

> Design snapshot: 2026-09-06; current implementation overlay synchronized 2026-09-08.
>
> Canonical branch: `main`; active development uses short-lived `work/*` branches from current `main`.
>
> This document preserves the delegated-work architecture/design and records what part of that design current `main` now implements. It does not claim that every target structure below is product-closed. Current implementation facts remain authoritative in `docs/ZN-IMPLEMENTATION-STATUS.md`, and current capability status remains authoritative in `docs/ZN-PRODUCT-CAPABILITY-MAP.md`.

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

## 2. Current implementation status

As of current `main` on 2026-09-08, the bounded delegated-work substrate has moved beyond the 2026-09-06 foundation state.

Implemented and verified in the active path:

- durable `WorkThread`, Work items, messages, artifacts and run facts owned by existing Work/Resident storage;
- explicit Work lifecycle control and restart recovery;
- plan versioning and stale-result protection;
- bounded delegation admission owned by Resident;
- Resident-internal `DelegatedWorkCoordinator`; no second Resident/store/router/control plane;
- durable flat WorkerRun lifecycle and provenance;
- strict bounded `WorkerContextPack` sanitation/classification boundary;
- action-time WorkerRun/WorkItem/plan/workspace authority revalidation at the existing Body boundary;
- existing kernel-owned `ModelRouter` hard eligibility before soft scoring;
- durable Work route/privacy policy, provider/model pin/deny, locality/privacy, policy-tag and authority-scope gates;
- route/provider provenance bound to delegated runs;
- dynamic `ResidentHealthJournal` observations wired into health-aware routing;
- durable worker progress supervision with heartbeat/no-progress/stall detection;
- bounded retry and policy-safe fallback/reassignment;
- restart-safe delegated reconciliation and no-replay recovery;
- natural-language same-Work steering, current-plan replanning and stale old-worker result gating;
- restart continuation that does not replay already completed historical effects;
- privacy-safe bounded delegated progress projection through the existing `work_progress` contract and Resident UI;
- durable `WorkItem.dependency_ids` with bounded flat current-plan sibling dependency/readiness semantics, fan-in, restart durability and invalid-graph fail-closed behavior.

Representative acceptance now closed:

- one-route/multi-worker contract — one real model route serving multiple isolated WorkerRuns;
- route/privacy contract — route policy/privacy under current acceptance semantics, with an explicit environment waiver for the missing second real provider family;
- supervision/recovery contract — dynamic health, stall/no-progress supervision, bounded retry/reassign and restart reconciliation;
- steering/continuation contract — natural-language steering and restart continuation with stale-plan/non-replay discipline.

The accurate boundary is:

```text
bounded delegated substrate implemented + representative paths verified
!= general-purpose long-task scheduler
!= recursive multi-agent platform
!= general DAG/workflow engine
!= every long-horizon task product-closed
```

Any older statement in this design that treated dynamic health routing, systematic stall supervision, restart-safe delegated reconciliation, route/privacy contract or steering/continuation contract as wholly unimplemented is superseded by this current implementation overlay.

## 3. Ownership invariants

The design remains governed by these invariants:

```text
Resident owns Root Work.
Worker/model is a replaceable cognition/execution resource.
Worker done != Root completion.
A worker cannot grant itself authority.
Real-world effect requires current authority.
Fresh evidence beats model/worker assertion.
Completed/uncertain effects are not blindly replayed.
There is one ModelRouter.
There is one durable Work/progress truth.
There is no second Resident or orchestration subject.
```

Delegation is a Work mechanism, not a new identity architecture.

## 4. Root Work, WorkItem and WorkerRun

### 4.1 Root Work

Root Work is the durable user task/project owned by ZN. It survives model replacement and can survive Resident restart when current evidence permits safe continuation.

Root Work owns or references:

- user goal / current acceptance target;
- current plan version;
- durable task facts and artifacts;
- current blockers and user-presence state;
- WorkItems;
- current outcome/completion evidence.

A child worker never becomes the Root Work owner.

### 4.2 WorkItem

A WorkItem is a bounded unit under Root Work. It can represent direct Resident work, deterministic capability work or delegated specialist work.

Useful semantics include:

- purpose / expected result;
- plan version;
- executor/resource requirements;
- required capability/policy/authority;
- acceptance evidence;
- progress/blocker state;
- bounded dependency IDs where current implementation supports them.

### 4.3 WorkerRun

A WorkerRun is one bounded execution attempt for a WorkItem. It is not a permanent agent identity.

A WorkerRun should retain enough durable facts for:

- selected route/provider provenance;
- bounded input/context provenance;
- progress/heartbeat state;
- attempt/retry identity;
- terminal result or failure/blocker;
- verification status;
- restart reconciliation;
- stale-plan gating.

A semantic retry gets a new run identity rather than pretending the failed/uncertain run did not happen.

## 5. Flat dependency/readiness design and current boundary

The design originally called for dependency/readiness semantics without turning ZN into a workflow product. Current `main` now implements a bounded first slice.

### Current implementation

`WorkItem.dependency_ids` is durable. Dependency edges are validated as bounded current-plan sibling references under the same Root Work/work thread.

Readiness is derived from durable Work facts; it is not persisted as a second truth.

Current guards include:

- bounded dependency list/graph traversal;
- same Root / thread / current plan;
- immutable dependency edges for the current item semantics;
- fan-in;
- WorkerRun creation readiness gate;
- coordinator cognition-binding readiness gate;
- child completion gate;
- restart durability;
- corrupt/cyclic/dangling/cross-plan graph fail closed.

Dependencies do **not** transfer or inherit worker authority, tool scope or privacy policy.

### Remaining boundary

The current substrate does not claim:

- recursive delegation trees;
- arbitrary DAG execution;
- a general-purpose workflow engine;
- critical-path scheduling;
- resource-pool scheduling;
- generic dependency editing/visualization UX;
- automatic parallelism merely because two items are dependency-independent.

If a future real task requires broader scheduling semantics, it should extend the existing Work truth instead of adding a separate scheduler truth.

## 6. Delegation admission

Delegation should occur only when it has a concrete benefit such as:

- parallelizable independent work;
- context isolation;
- specialist cognition;
- long-running separation;
- independent review;
- isolated tool/workspace execution.

Small/sequential/context-heavy work should stay direct when delegation adds no value.

The current `BoundedDelegationPlanner` is deliberately conservative. Explicit negation and current task evidence must beat keyword coincidence.

Correct design:

```text
Root Work
-> inspect actual need
-> direct path OR bounded WorkItems
-> only delegate items where delegation helps
```

Incorrect design:

```text
long prompt
-> spawn many workers because multi-agent looks capable
```

## 7. Worker context and privacy boundary

Workers should receive a purpose-built context pack, not the entire transcript, all Memory or every credential-bearing detail available to the Resident.

Current `WorkerContextPack` enforces bounded recursive serialization and privacy/safety checks such as:

- depth/node/item/string/final-size limits;
- nested sensitive-key rejection;
- secret-like value rejection;
- provenance/data classification;
- valid plan-version binding.

Important semantics:

- `private` does not automatically mean `cloud forbidden`;
- locality/privacy eligibility is driven by explicit Work/user policy;
- workers do not gain Memory-write, credential, user-message or spawn authority just because they receive context;
- a context filter is not complete DLP.

## 8. Resource routing

### 8.1 Keep one ModelRouter

All delegated cognition continues through the existing kernel-owned `ModelRouter`.

Do not add:

- a worker-only router;
- provider-specific orchestration state that competes with `ModelRouter`;
- a model-selected model handoff that bypasses kernel eligibility.

### 8.2 Hard eligibility before soft scoring

The intended and current selection shape is:

```text
WorkItem requirements + user/Work policy + current route facts
-> hard eligibility
-> only legal candidates remain
-> dynamic health / SelfModel / reliability / cost / latency scoring
-> selected route
-> provenance retained on WorkerRun
```

Hard eligibility includes capability, pin/deny, declared availability, locality/privacy, policy tags, authority scopes and malformed-policy fail-closed handling.

No legal route means fail closed (`NoRouteAvailable`), not “pick an illegal fallback with a low score”.

### 8.3 Dynamic health

The earlier design left runtime health observation unwired. That is no longer current fact.

Current `ResidentHealthJournal` observations enter health-aware routing and delegated supervision. Representative supervision/recovery contract verifies policy-safe fallback/reassignment under health/stall conditions.

This remains bounded health/supervision logic, not a promise of perfect provider outage handling across every provider and every long task.

## 9. Multi-route privacy acceptance

route/privacy contract is closed under the repository’s current acceptance policy.

The closure proves the current policy/eligibility/provenance path and guarded multiroute acceptance semantics. It also records an **owner-approved environment waiver** because the acceptance environment did not have a second real provider family configured.

Therefore the design/status language must remain exact:

```text
policy/privacy acceptance path closed under current policy
+ two-provider guard retained
+ environment waiver explicitly recorded
!= two real provider families fully production-validated
```

When two real provider families are configured, the guarded acceptance is expected to run without skip and fail closed if the required evidence is absent.

The important invariant remains that a forbidden provider must not receive restricted context merely because it scores well.

## 10. Worker authority

Delegation never widens authority automatically.

Before a real Body effect, the active path revalidates current durable facts such as:

- Root Work / WorkItem identity;
- WorkerRun identity/state;
- current plan version;
- admitted action/tool class;
- attached workspace/resource scope;
- relevant user/Work policy.

Examples:

- research/review workers do not acquire arbitrary workspace mutation;
- coding writes stay within the admitted workspace boundary;
- stale-plan workers cannot keep mutating merely because they started under an older plan;
- dependency completion does not transfer authority.

This is an action-admission boundary. It is not a process sandbox or blanket OS security boundary.

## 11. Progress and supervision

### 11.1 Progress truth

Execution progress is subordinate to Work truth. The system must not create a second progress database whose state can diverge from WorkItem/WorkerRun facts.

Current delegated progress is projected from durable delegated facts into the existing `work_progress` contract and Resident UI using bounded privacy-safe normalization.

Status is best described as:

```text
CONNECTED + VERIFIED NARROW / PARTIAL UX
```

The remaining problem is user-level quality and breadth, not absence of a progress path.

### 11.2 No-progress / stall supervision

The earlier open design requirement is now implemented for the bounded delegated path.

Current supervision includes:

- durable progress/heartbeat observation;
- no-progress/stall detection;
- bounded retry budget;
- health-aware routing/fallback;
- policy-safe reassignment;
- restart reconciliation;
- stale-result protection;
- no blind replay of completed historical effects.

Representative supervision/recovery contract closes this path.

Remaining product work is broader long-duration, multi-workstream and real-environment coverage, not re-adding the same supervision architecture.

## 12. Restart and non-replay

Restart must treat durable facts as evidence about what was recorded, not as proof that every external effect is still current.

The desired/current bounded pattern is:

```text
Resident restarts
-> restore Root Work / current plan / WorkerRun facts
-> reconcile active/terminal attempts
-> retain completed durable evidence
-> do not replay completed historical effects
-> unresolved/uncertain effects remain uncertain
-> stale old-plan results cannot advance current plan
-> use fresh current-world evidence before continuing
```

supervision/recovery contract verifies delegated restart reconciliation and steering/continuation contract verifies continuation/non-replay under steering for representative paths.

This does not mean every cross-day real-world task is already solved.

## 13. User steering

User steering belongs to Root Work/Will, not to a worker conversation.

A user can change the current plan in normal language. The bounded current implementation supports representative same-Work steering:

```text
user updates goal/direction
-> current plan version changes
-> affected pending work is superseded/replanned
-> completed still-valid effects can be retained
-> old-plan worker results become stale for current completion
-> already completed historical effects are not replayed
-> Resident continues the same Root Work from fresh evidence
```

steering/continuation contract closes the representative real-model acceptance path.

Remaining work is broader task classes, longer time spans and user-facing explanation of what was retained/superseded.

## 14. Worker completion and Root completion

A worker can only produce candidate evidence/result.

Correct flow:

```text
WorkerRun reports result
-> Resident/Work verifies required evidence
-> WorkItem may become accepted/completed
-> Root Work independently evaluates root acceptance
-> user goal completes only when current evidence proves it
```

Incorrect flow:

```text
worker says "done"
-> Root Work complete
```

This invariant was exercised by one-route/multi-worker contract and remains mandatory across all later delegated work.

## 15. One model, many workers

one-route/multi-worker contract closed the architectural question of whether multiple workers require multiple model routes.

They do not.

```text
one model route
-> research WorkerRun
-> coding WorkerRun
-> review WorkerRun
```

can be valid when the route satisfies each WorkItem’s eligibility requirements.

Worker count and model/provider count remain independent dimensions.

Multi-route support should improve capability/privacy/cost/reliability choices, not become a requirement for delegation itself.

## 16. Current user-facing progress design

The user-facing surface should explain goals/tasks/blockers/required presence/completion evidence, not provider internals.

Current implementation already projects delegated progress to the Resident UI. Future UX work may improve:

- human-readable current goal and current workstream;
- completed vs running vs waiting-for-user vs blocked;
- meaningful retry/reassignment explanation without raw route plumbing;
- which direction changed after steering;
- what evidence supports completion;
- what remains unresolved.

Do not expose a task-board merely because internal WorkerRuns exist. UX should follow real user value.

## 17. Relationship to Browser/Desktop/File/Terminal

Delegated Work is not useful without real Body capability.

A WorkerRun may contribute cognition or bounded execution, but real operations remain governed by the corresponding ZN-owned Body/Sense/authority/verification contracts.

Recent Browser/Windows slices strengthen the Body available to Root Work:

- bounded BrowserScene and exact semantic actions;
- tab/history lifecycle;
- causal popup attribution;
- authority-safe managed file transfer;
- stateless/stateful bounded control clicks;
- USER Browser authenticated research/mutation and causal child-tab paths;
- representative OTP user-presence handoff;
- Windows application inventory/identity/launch and exact existing-window activation.

These are representative bounded capabilities, not permission to turn delegated workers into unrestricted browser/desktop agents.

## 18. Cost and cognition budgeting

ZN should spend strong cognition where it improves outcome quality, not on deterministic waiting/polling/mechanical checks.

Useful accounting can remain attached to WorkerRun/route provenance:

- route/provider/model;
- latency;
- usage/cost where available;
- retries/failures;
- task class/outcome evidence.

Cost optimization must never bypass capability/privacy/authority eligibility or downgrade hard tasks so aggressively that task quality collapses.

## 19. Anti-goals

This design must not evolve ZN into:

- a generic multi-agent framework;
- a workflow/DAG engine product;
- a model gateway product;
- an agent chatroom;
- recursively spawning autonomous personalities;
- a system where workers own Memory/identity/authority;
- a system where model confidence is completion evidence;
- a system with a second router or second Work truth;
- a system that replays uncertain external effects to “make progress”.

## 20. Current implementation status versus remaining boundary

### Implemented + verified narrow

- one ZN / one Root Work owner;
- bounded delegation admission;
- durable WorkItem/WorkerRun facts;
- isolated bounded worker context;
- worker action authority revalidation;
- one-route multi-worker (one-route/multi-worker contract);
- hard policy/privacy routing;
- dynamic health-aware routing;
- stall/no-progress supervision;
- bounded retry/fallback/reassignment;
- restart reconciliation/no-replay;
- active steering / stale-plan protection / continuation;
- delegated user progress projection;
- bounded flat dependency/readiness;
- route/privacy contract, 28/34, 27/33 representative acceptance closures with their documented limitations.

### Remaining boundary

- broader long-horizon/cross-day real-task coverage;
- complex multi-workstream user UX and explanation quality;
- more cross-surface Browser/Desktop/File/Terminal/Application tasks;
- broader real-site Browser/User Browser complexity;
- broader Windows/application semantic capability when a real integration evidence requires it;
- general recursive delegation / arbitrary DAG scheduling remains intentionally unimplemented unless a future real task proves it necessary.

## 21. Product acceptance rule

The end state is not “delegation code exists”. It is:

```text
normal human goal
-> ZN keeps one durable Root Work
-> delegates only useful bounded work
-> routes cognition under explicit policy and current health
-> workers act only within admitted authority
-> progress/stall/restart/steering remain Resident-owned
-> real Body effects use fresh evidence and non-replay discipline
-> worker output is independently accepted/rejected
-> Root Work completes only from current-world evidence
```

That is the delegated-work design. The implementation now covers a meaningful bounded subset of it; future work should expand real-task breadth without creating a second orchestration product.
