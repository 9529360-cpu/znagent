# ZN Orchestration Research

> Research snapshot: 2026-09-04; current-ZN-facts overlay synchronized 2026-09-08.
>
> This document records external product research and the resulting ZN adoption decisions. It is not proof that the described ZN mechanisms are already implemented. Real code, Git state and contract/integration evidence remain authoritative.

## 1. Why this research exists

ZN is being built as a long-lived general-purpose personal assistant, not as an office-only agent, coding-only agent, browser agent or generic multi-agent framework.

The research question is:

> Which mature mechanisms have proved useful in long-running, delegated, multi-tool or multi-model work, and where should those mechanisms live inside ZN’s existing Self / Work / Will / Situation / Thought / CognitiveResource / Body architecture?

## 2. Current ZN facts that constrain the design

The following are current code facts as of 2026-09-08, not future plans:

- `ResidentWorkLedger` / existing Work storage owns durable Root Work, WorkItems, messages, artifacts and run facts.
- `ResidentWorkControl` owns Work lifecycle/reconciliation and preserves non-replay discipline.
- `ModelRouter` already exists and is kernel-owned. Models do not select themselves.
- `ModelRouter` applies hard eligibility before soft scoring and now incorporates durable route/privacy policy plus dynamic health-aware routing.
- provider construction supports multiple `ModelRoute` entries and hot reconfiguration without replacing ZN identity/store.
- `CognitiveResource` returns bounded cognition rather than becoming the Resident subject.
- `DelegatedWorkCoordinator` exists inside the same Resident; no second store/router/orchestrator subject is introduced.
- durable WorkerRun progress/supervision, heartbeat/no-progress/stall detection, bounded retry/fallback/reassignment and restart reconciliation are connected for the bounded delegated path.
- natural-language same-Work steering, plan-version stale gating and restart continuation are connected for representative paths.
- delegated progress is projected from durable Work facts into the existing `work_progress` contract/Resident UI; there is no second progress truth.
- `WorkItem.dependency_ids` now provides a durable **bounded flat current-plan sibling dependency/readiness substrate** with fan-in and invalid-graph fail-closed behavior.

The old research-snapshot statement that Work had no durable dependency/delegated-executor structure is no longer current.

The remaining boundary is important: ZN still does not claim a general recursive delegation tree, arbitrary DAG scheduler, critical-path/resource-pool scheduler or generic workflow product.

Therefore:

```text
DO NOT build a second model router.
DO NOT introduce a new resident/orchestrator identity.
DO NOT replace Work with a workflow framework.
DO NOT interpret the bounded dependency substrate as a general DAG runtime.

Extend existing Work when a real task needs broader durable structure.
Extend existing ModelRouter policy/health mechanisms when a real task needs broader routing.
Keep supervision inside the existing Resident life loop.
```

## 3. OpenClaw lessons

Useful mature mechanisms from sub-agent systems include:

- isolated worker context by default;
- push/event completion rather than model polling;
- bounded fan-out;
- parent verification of child output;
- per-run model/thinking overrides;
- narrower worker tool exposure;
- inspectable run metadata/status.

ZN adoption:

1. Purpose-built worker context, not full transcript/Memory.
2. Push/event completion.
3. Bounded concurrency/liveness.
4. Root/parent verification remains mandatory.
5. Model count and worker count remain independent.
6. Scoped tools and authority.

Do not let worker sessions become durable user Work owners.

## 4. Hermes-style delegation lessons

Useful mechanisms include fresh child contexts, final-summary-only parent ingestion, bounded parallelism, independent workspaces, non-recursive leaf workers by default and restricted high-impact tools.

ZN adoption:

- planner quality and worker economy are separate concerns;
- flat delegation remains the preferred default;
- workers should not automatically gain Memory writes, direct user messaging, scheduling or further-spawn authority;
- coding/system workers may need isolated workspaces while remaining subordinate to Root Work authority.

## 5. OpenHuman-style long-task lessons

Useful mechanisms include durable goals/tasks, acceptance criteria/evidence, blockers, background continuation, active steering, pause/approval/resume and user-readable progress.

ZN has now implemented bounded versions of several of these ideas inside existing Work: durable delegated facts, active steering, restart reconciliation and progress projection.

Remaining lesson: improve product breadth/UX without creating a second task-board/workflow product.

## 6. Magentic-One / AutoGen lessons

The important transferable pattern is separating task truth/plan from execution progress and treating repeated lack of progress as a replanning signal.

In ZN terms:

```text
task truth/plan -> Work + current verified facts + plan/acceptance
execution progress -> WorkItem / WorkerRun facts + Situation
orchestrator reasoning -> ZN Thought / Investigation
specialists -> bounded workers/resources under Work
```

Current main now has bounded no-progress/stall supervision; the research lesson remains useful for broader tasks.

Do not introduce an Orchestrator Agent persona or worker group-chat control plane.

## 7. LangGraph lessons

Useful ideas:

- durable checkpoints;
- pause/resume and restart continuation;
- do not rerun successful work merely because sibling work failed;
- idempotency/non-replay discipline around interruption;
- persistent child state only when product need justifies it.

ZN should continue to implement these semantics through Work/Recovery rather than adopting a graph runtime as the product architecture.

## 8. OpenAI Agents SDK lesson

The useful distinction is manager-style specialists versus handoff-style ownership transfer.

ZN chooses manager-style semantics:

```text
user keeps talking to ZN
-> ZN delegates bounded specialist work
-> specialists do not replace Resident identity/root ownership
-> ZN combines evidence and applies common guardrails
```

## 9. Specialist coding-agent lesson

Delegate only when delegation has concrete benefit:

- parallelism;
- context isolation;
- specialist cognition;
- long-running separation;
- independent review;
- isolated tool/workspace execution.

Otherwise keep work direct inside the Resident task loop.

This protects ZN from making “multi-agent” a vanity metric.

## 10. Model gateway lessons

Provider gateways demonstrate useful transport, retry/fallback, usage/cost and health mechanisms.

ZN already owns route selection through its existing provider bridge + `ModelRouter`, so adoption rule remains:

- borrow missing mechanisms when a real integration evidence proves the need;
- do not insert a second routing control plane merely because gateways exist.

## 11. Cross-product synthesis

| Mature pattern | ZN owner | Current decision |
| --- | --- | --- |
| One user-facing manager | Self / Resident / Work | Keep one ZN subject |
| Durable root goal | Will + Work | Existing Work remains owner |
| Child decomposition | Work | Durable bounded WorkItems exist |
| Worker isolation | Work supervision + resource/Body policy | Bounded scoped context/tools |
| Model selection | existing ModelRouter + SelfModel/health | One router; policy + health aware |
| Tool execution | Body / Browser / Desktop / File / Terminal / APIs | Explicit bounded authority |
| Progress/stall detection | Situation + Work | Bounded supervision implemented; broaden by real task |
| Human steering | Work control + Will | Representative same-Work steering verified |
| Checkpoint/resume | Work + Recovery | Representative restart/non-replay verified |
| Child completion | Work evidence | Candidate result, not Root completion |
| Dependency readiness | Work | Bounded flat current-plan sibling substrate; not general DAG |
| User progress UX | Resident UI | Existing progress projection; broader UX remains |

## 12. ZN vocabulary

Use ZN-owned terms:

- **Root Work** — durable user task/project owned by ZN.
- **WorkItem / SubWork** — bounded durable unit under Root Work.
- **WorkerRun** — one bounded execution attempt; not another Resident identity.
- **Executor kind** — direct Resident path, deterministic capability, specialist model/agent, Browser/Desktop/File/Terminal/API resource or bounded combination.
- **ModelRoute** — existing ZN cognitive route.
- **Acceptance evidence** — current-world evidence required before accepting completion.
- **Plan version** — stale-result/steering guard.
- **Dependency readiness** — current derived WorkItem readiness from bounded durable sibling dependencies, not a second scheduler truth.

Do not add permanent “Orchestrator Agent”, “Manager Agent” or specialist identities unless a future real task proves existing ownership cannot express the need.

## 13. Target long-task loop

```text
user gives broad human goal
-> ZN restores/creates Root Work
-> clarify only material ambiguity
-> investigate current reality
-> define current acceptance target
-> create/update bounded WorkItems
-> derive dependency readiness where used
-> determine direct vs delegated
-> choose tool/resource bundle
-> route cognition through existing ModelRouter under user policy/current health
-> execute bounded work
-> receive progress/result events
-> detect stall/no-progress where applicable
-> verify current-world evidence
-> accept / reject / block / replan / reassign
-> user steering may supersede current plan safely
-> restart reconciliation preserves non-replay
-> continue until Root acceptance is verified
-> retain durable context for future continuation
```

## 14. Anti-goals

This research must not cause ZN to become:

- a generic multi-agent framework;
- a model gateway product;
- a DAG/workflow engine product;
- an agent-chatroom product;
- a coding-agent wrapper;
- a recursively spawning agent tree by default;
- a system where LLMs own authority/facts/completion;
- a system with a second ModelRouter or second durable progress truth.

## 15. Current acceptance context

The research snapshot predated several now-merged acceptance slices. Current docs should not send maintainers back to reimplement them:

- one-route/multi-worker contract — closed;
- route policy/privacy contract — closed under current acceptance policy with documented environment waiver for missing second real provider family;
- dynamic health/stall/restart supervision contract — representative path closed;
- active steering/continuation contract — representative path closed;
- delegated progress projection — connected/verified narrow;
- bounded flat dependency/readiness — implemented/verified narrow.

Future work should expand real-task breadth and UX where current evidence shows a gap, not rebuild these substrates under a new framework name.

## 16. Product decision

The direction remains:

> **ZN remains the long-lived personal assistant and Root Work owner. Existing Work owns durable decomposition, bounded dependency/readiness, supervision, steering and progress. Existing ModelRouter owns cognition routing under explicit policy and current health. Workers remain replaceable scoped execution contexts. Body/tools make changes in the real world. ZN independently verifies results and keeps continuity.**

The implementation design is in `docs/ZN-DELEGATED-WORK-DESIGN.md`; current capability status is in `docs/ZN-PRODUCT-CAPABILITY-MAP.md`.
