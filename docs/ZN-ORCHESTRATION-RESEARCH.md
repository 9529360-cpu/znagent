# ZN Orchestration Research

> Research snapshot: 2026-09-04
>
> This document records external product research and the resulting ZN adoption decisions. It is not proof that the described ZN mechanisms are already implemented. Real code, Git state, tests and E2E remain authoritative.

## 1. Why this research exists

ZN is being built as a long-lived general-purpose personal assistant, not as an office-only agent, coding-only agent, browser agent or a generic multi-agent framework.

A mature user should be able to say:

```text
“帮我开发一个个人记账产品。你先调研一下市场，跟我确认关键方向，然后自己推进，做出能运行的第一版。”
```

ZN should remain the single user-facing resident owner while it investigates, decomposes the goal, uses tools, delegates bounded work, routes cognition, supervises progress, reacts to user steering, recovers across interruption, and independently verifies the real result.

The research question is therefore not “which agent framework should ZN copy?” It is:

> Which mature mechanisms have already proved useful in long-running, delegated, multi-tool or multi-model work, and where should those mechanisms live inside ZN’s existing Self / Work / Will / Situation / Thought / CognitiveResource / Body architecture?

## 2. Existing ZN facts that constrain the design

The following are current code facts, not future plans:

- `ResidentWorkLedger` already owns durable Work threads, messages, artifacts and Work runs.
- `ResidentWorkControl` already owns explicit Work lifecycle controls such as cancellation/reconciliation and preserves non-replay discipline.
- `ModelRouter` already exists and is kernel-owned. Models do not select themselves.
- `ModelRouter` already scores routes from required capabilities, evidence-backed route performance in `SelfModel`, route reliability, cost weight and latency weight.
- `provider_bridge.py` already supports multiple `ModelRoute` entries, OpenAI-compatible/Anthropic/Gemini resource construction, and hot reconfiguration without replacing ZN identity/store.
- `CognitiveResource` already returns bounded cognition rather than becoming the Resident subject.
- Work currently has no durable hierarchical `SubWork` / dependency / delegated-executor / acceptance-evidence structure.

Therefore:

```text
DO NOT build a second model router.
DO NOT introduce a new resident/orchestrator identity.
DO NOT replace Work with a workflow framework.

Extend existing Work for durable delegated task structure.
Extend existing ModelRouter policy for per-SubWork cognition selection.
Keep supervision inside the existing Resident life loop.
```

## 3. OpenClaw

Primary reference:

- https://docs.openclaw.ai/tools/subagents

Relevant mature mechanisms:

- Sub-agents are background runs in their own sessions.
- Isolation is the default; transcript fork is explicit and used only when the child genuinely needs parent conversational context.
- Child completion is push/event driven rather than a model repeatedly polling status.
- Parent remains responsible for reviewing the child result before deciding whether the original task is done.
- Child runs have configurable model/thinking overrides and can use a cheaper model than the main session.
- Concurrency is bounded and visible rather than unlimited fan-out.
- Tool exposure is narrower for children; session/message tools are not automatically available.
- Run metadata/status/logs are user-inspectable.
- Child results are treated as internal reports/evidence, not as new user instructions.
- External harnesses such as coding agents can be supervised as bounded child runs.

What ZN should adopt:

1. **Isolated worker context by default.** A delegated worker should receive a purpose-built context pack, not the user’s entire transcript and Memory.
2. **Push/event completion.** Do not burn model tokens polling children in a loop.
3. **Bounded fan-out and liveness.** Concurrency must be controlled at the Work/supervision level.
4. **Parent verification.** A worker `done` is only candidate completion.
5. **Per-run resource override.** Worker count and model count stay independent.
6. **Scoped tools.** Delegation is not an excuse to grant broad communication, Memory, credentials or computer authority.

What ZN should not copy:

- Do not let sub-agent sessions become the durable user Work owner.
- Do not make every non-trivial action a sub-agent session.
- Do not fork the complete conversation by default.
- Do not expose internal session machinery as the primary user experience.

## 4. Hermes Agent

Primary references:

- https://hermes-agent.nousresearch.com/docs/user-guide/features/delegation
- https://hermes-agent.nousresearch.com/docs/guides/delegation-patterns

Relevant mature mechanisms:

- `delegate_task` creates fresh child contexts; only the final summary normally returns to the parent.
- Parallel batches are bounded by default.
- Children have independent terminal sessions.
- Leaf workers cannot recursively delegate by default; deeper orchestration is opt-in.
- Some high-impact tools are deliberately removed from leaf workers.
- Hermes explicitly recommends a strong planner/frontier model with cheaper worker models when appropriate because child runs consume much of the token budget.
- Worker cancellation and ownership follow a parent/child lifecycle.

What ZN should adopt:

1. **Planner quality and worker economy are different concerns.** The preferred primary reasoning resource does not have to be the worker model.
2. **Final-summary-only parent ingestion.** Keep worker transcript/context growth bounded.
3. **Independent working environments for coding/system work where isolation matters.**
4. **Flat delegation first.** Do not start with recursively spawning agent trees.
5. **Leaf capability restriction.** Workers should not automatically get Memory writes, direct user messaging, scheduling or further spawn authority.

What ZN should improve on rather than copy:

- ZN should eventually route cognition per SubWork using the existing `ModelRouter`; a single global child model is too coarse for ZN’s general-assistant target.
- A coding worker’s terminal/session is still subordinate to ZN Work authority and independent result verification.

## 5. OpenHuman

Primary reference:

- https://github.com/tinyhumansai/OpenHuman

Relevant mature mechanisms:

- The product explicitly positions itself as an orchestrator rather than only a chatbot.
- Goals and task boards are durable and include status, plans, acceptance criteria, evidence and blockers.
- Background work can continue without keeping a foreground chat turn open.
- Agent/worker runs can be steered, waited on, reused or closed.
- Checkpointed work survives restart and can pause for human input/approval.
- User-visible orchestration is centered on goals/tasks rather than provider internals.
- Long-running autonomy uses bounded continuation behavior rather than an uncontrolled infinite loop.

What ZN should adopt:

1. **Durable goal + task-board semantics** inside existing `Work`.
2. **Acceptance criteria/evidence and blocker reason** as first-class Work data.
3. **Active steering**: “这个先别做”, “先做核心功能”, “按刚才的新方向改”.
4. **User-readable progress** across long tasks and restarts.
5. **Pause/approval/resume** without losing the root goal.

What ZN should not copy:

- Do not replace ZN with a graph runtime or a new external orchestrator framework.
- Do not add a separate “subconscious agent” subject; background continuation belongs to ZN Will/Work.
- Do not create a second workflow product beside normal Resident Work.

## 6. Microsoft Magentic-One / AutoGen

Primary reference:

- https://www.microsoft.com/en-us/research/articles/magentic-one-a-generalist-multi-agent-system-for-solving-complex-tasks/

Relevant mature mechanisms:

- The orchestrator distinguishes a higher-level task ledger from a progress ledger.
- It explicitly records what is known, what must be discovered, a plan, and current progress.
- Repeated lack of progress is treated as a signal to update the plan rather than continuing the same loop indefinitely.
- Specialist roles cover web, files, terminal/code and computer interaction.

What ZN should adopt:

1. Separate **task truth/plan** from **execution progress**.
2. Treat repeated non-progress as a Situation/Thought event that triggers Investigation/replanning.
3. Make “what remains unknown?” explicit so ZN can choose Sense/Search/Model rather than blindly continue.

What ZN should not copy:

- Do not introduce a separate Orchestrator Agent persona.
- Do not turn workers into a shared group-chat where every worker receives every message.
- Do not let agent-role taxonomy become the product architecture.

In ZN terms:

```text
Magentic task ledger   -> Work + current verified facts + plan/acceptance
Magentic progress      -> WorkItem / WorkerRun progress + Situation
orchestrator reasoning -> ZN Thought / Investigation
specialists            -> bounded workers/resources under Work
```

## 7. LangGraph

Primary references:

- https://docs.langchain.com/oss/python/langgraph/persistence
- https://docs.langchain.com/oss/python/langgraph/interrupts

Relevant mature mechanisms:

- Durable checkpoints make pause/resume and restart continuation explicit.
- Work that already completed successfully need not be blindly rerun after sibling failure.
- Interrupt/resume semantics force developers to think carefully about idempotency because code before an interrupt can execute again.
- Per-invocation child state is often safer than persistent shared child state unless persistent child memory is genuinely needed.

What ZN should adopt:

1. **Durable progress checkpoints** after meaningful Work state transitions.
2. **Do not rerun successful child work just because another child failed.**
3. **Pause/resume with non-replay discipline.**
4. **Worker persistence only when product need justifies it.** Most delegated runs should be per-WorkItem attempts, not permanent personalities.

What ZN should not copy:

- Do not replace the Resident architecture with an explicit DAG/graph framework.
- Do not weaken current ZN fresh-evidence and uncertain-side-effect rules merely to fit a graph execution model.

## 8. OpenAI Agents SDK

Primary references:

- https://openai.github.io/openai-agents-python/multi_agent/
- https://openai.github.io/openai-agents-python/agents/

Relevant mature mechanism:

The SDK explicitly distinguishes:

```text
manager / agents-as-tools
vs
handoff / specialist takes over the conversation
```

For ZN, the manager-style lesson is the important one: specialists can work behind the user-facing owner while the owner combines results and applies common guardrails.

What ZN should adopt:

- **Manager-style semantics.** The user keeps talking to ZN; delegated specialists do not replace the resident subject.
- Mix deterministic code orchestration and model judgment instead of forcing all orchestration through an LLM.
- Trace which resource/tool/worker contributed to a result so failures and cost are observable.

What ZN should not copy:

- A handoff must not replace ZN’s durable user-facing identity or root Work owner.

## 9. Claude Code / specialist coding agents

Relevant current lesson from mature coding-agent practice:

- Subagents are useful when independent exploration, parallel workstreams, context isolation or specialist review provide a real benefit.
- Over-delegating simple/sequential/context-heavy work can make systems slower, more expensive and less coherent.

ZN adoption rule:

```text
delegate only when delegation has a concrete benefit:
- parallelism,
- context isolation,
- specialist cognition,
- long-running separation,
- independent review,
- or isolated tool/workspace execution.

otherwise keep the work direct inside the current Resident task loop.
```

This protects ZN from turning “multi-agent” into a vanity metric.

## 10. LiteLLM / model gateways

Useful mature ideas include provider unification, retry/fallback, load balancing, usage/cost accounting and budgets.

ZN already owns provider selection through `provider_bridge.py` + `ModelRouter`. Therefore the adoption rule is:

- borrow missing transport/usage/health mechanisms when a real E2E proves the need;
- do not insert a second routing control plane simply because model gateways exist.

## 11. Cross-product synthesis

Across these products and frameworks, the mature pattern is converging on several principles:

| Mature pattern | ZN owner | ZN decision |
| --- | --- | --- |
| One user-facing manager | Self / Resident / Work | Keep one ZN subject |
| Durable root goal | Will + Work | Extend existing Work, no new workflow product |
| Child task decomposition | Work | Add durable WorkItem/SubWork |
| Worker isolation | Work supervision + Body/resource policy | Default scoped context/tools |
| Model selection | existing ModelRouter + SelfModel | Extend per SubWork, do not replace |
| Tool execution | Body / Browser / Desktop / File / Terminal / APIs | Workers use explicit bounded authority |
| Progress/stall detection | Situation + Work | Replan on non-progress |
| Human steering | Work control + Will | Change plan safely, preserve completed effects |
| Checkpoint/resume | Work + Recovery | Durable and non-replaying |
| Child completion | Work evidence | Candidate result, not root completion |
| Cost/token accounting | Cognitive budget + WorkerRun metrics | Spend cognition where valuable |
| User progress UX | ZN desktop/face | Show goals/tasks/blockers, hide internal plumbing |

## 12. Proposed ZN vocabulary

To avoid importing other products’ identities into ZN:

- **Root Work** — the durable user task/project owned by ZN.
- **WorkItem / SubWork** — a durable unit of work under Root Work.
- **WorkerRun** — one bounded execution attempt for a WorkItem. It is not another Resident identity.
- **Executor kind** — direct resident path, deterministic capability, specialist model/agent, Browser/Desktop/File/Terminal/API resource, or a bounded combination.
- **ModelRoute** — existing ZN cognitive route.
- **Acceptance evidence** — current-world evidence required before ZN marks a WorkItem completed.
- **Plan version** — guards against stale delegated results after user steering/replanning.

Do not add “Orchestrator Agent”, “Manager Agent”, “Research Agent identity”, or similar permanent subjects unless a future real task proves that the existing ownership model cannot express the need.

## 13. The target long-task loop

```text
user gives broad human goal
→ ZN restores/creates Root Work
→ clarify only material ambiguity
→ investigate current reality
→ define current acceptance target
→ create/update WorkItems
→ determine which ready item should be direct vs delegated
→ choose tool/resource bundle
→ if cognition needed, route through existing ModelRouter under user policy
→ execute bounded work
→ receive result/event
→ verify current-world evidence
→ accept / reject / block / replan
→ detect stall or changed reality
→ user steering can supersede the current plan safely
→ continue until root acceptance is verified
→ retain durable context for future continuation
```

## 14. Anti-goals

This research must not cause ZN to become:

- a generic multi-agent framework;
- a model gateway product;
- a DAG/workflow engine product;
- an agent-chatroom product;
- a coding-agent wrapper;
- a “spawn as many agents as possible” benchmark;
- a system where the LLM owns authority/facts/completion;
- a system that reduces token cost by refusing necessary strong cognition;
- a system that spends strong-model tokens on deterministic waiting/polling/mechanical checks.

## 15. Product decision

The direction is:

> **ZN remains the long-lived personal assistant and root task owner. Work becomes capable of durable decomposition and supervision. Existing ModelRouter becomes capable of routing cognition for each bounded SubWork under explicit user policy. Workers remain replaceable scoped execution contexts. Body/tools make changes in the real world. ZN independently verifies results and keeps continuity.**

The detailed implementation design is in `docs/ZN-DELEGATED-WORK-DESIGN.md`. The product acceptance tasks are in `docs/ZN-REAL-TASK-E2E-CATALOG.md`.