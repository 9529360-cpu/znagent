# ZN next phase — Self + mature execution depth

> Date: 2026-08-23
>
> Active branch: `dev/zn-agent`
>
> Governing architecture: [`../ZN.md`](../ZN.md)
>
> Current implementation facts: [`ZN-IMPLEMENTATION-STATUS.md`](ZN-IMPLEMENTATION-STATUS.md)
>
> Self-maintenance contract: [`ZN-SELF-MAINTENANCE.md`](ZN-SELF-MAINTENANCE.md)

## 1. Product target for this phase

The current organism-first architecture remains the governing design. This phase is a priority reset, not a return to a conventional model-owned agent architecture.

The concrete product target is now:

> **ZN must keep its own durable Self and continuity while gaining the practical execution depth of a mature general-purpose Agent: it must be able to take a complex real-world/computer task and reliably carry it through to a verified outcome.**

The project is not complete merely because ZN has Self, memory, Thought, Will and a resident loop. It is also not complete if a model/tool stack can perform impressive tasks while the model owns the plan and continuity.

The target is the combination:

```text
durable ZN Self
+ mature task-execution depth
+ reality-based verification
= the ZN we are building
```

A useful shorthand is:

**Self without execution depth is incomplete. Execution depth without Self ownership is the architecture ZN rejects.**

## 2. What “finish a complex task” means

A complex task is not one successful tool call. It can require many observations, hypotheses, body actions, failures and course corrections over many resident pulses or process restarts.

The desired resident-owned loop is:

```text
Goal / durable event
→ current Situation
→ establish current reality
→ identify the next important unknown
→ Investigation / evidence
→ choose one concrete next action
→ record the expected result
→ Body action
→ observe the actual result
→ compare expectation with reality
→ verified / contradicted / uncertain
→ update Situation / Investigation / Will / memory
→ continue the same work across pulses and restarts
→ verify the original goal against current reality
→ Outcome
```

External cognition may help at any genuine knowledge gap, but it does not own this loop:

```text
exact gap
→ bounded model request
→ CognitiveIncrement
→ ZN evaluates it against current evidence
→ ZN decides whether to investigate, reject, revise or act
```

A model response, a zero exit code, a successful write syscall or a successful body call is evidence. None of those facts alone automatically means the user’s goal is complete.

## 3. Core invariants

The next implementation work must preserve these invariants:

1. The same resident Self owns the task before, during and after model calls.
2. Work continuity lives in ZN-owned durable state, not in a model context window.
3. Investigation advances from current evidence, not from a giant static LLM plan.
4. Body actions are movements of ZN, not tools owned by an external planner.
5. **Action success is not task success.** Completion requires an observed postcondition or other task-level verification evidence.
6. Failure becomes new evidence. It must not trigger an uncontrolled retry loop.
7. Past memory/schema is a prediction source, not proof; current reality can contradict it.
8. External models may suggest hypotheses/procedures/code, but ZN must test them.
9. Zero-model operation remains meaningful even when some complex tasks cannot be completed without external cognition.
10. No new capability may reintroduce Hermes or another agent framework as ZN’s control plane.

## 4. Priority reset

Until this execution gap is substantially reduced:

- do not spend a development phase on cosmetic UI polish;
- do not add dashboard surfaces merely because information can be displayed;
- do not broaden desktop behavior unless it exposes, operates, debugs or safely authorizes a real core capability;
- do not rebuild already-proven packaging gates only to recreate evidence;
- keep M8/release work as a bounded continuity/release lane;
- continue to fix genuine release, security, data-integrity and resident-continuity defects when encountered;
- prefer work that measurably increases the resident’s ability to finish real tasks.

Desktop remains ZN’s face/work surface. It is not the current intelligence/agency development center.

## 5. Current foundation

The repository already has substantial ZN-native foundations:

- persistent resident life and identity;
- Situation / Thought / Will;
- nervous memory, schema and reconsolidation;
- durable events and working state;
- multi-pulse native Investigation with retained hypotheses/evidence/facts;
- native Action intents and Body actions;
- bounded external cognition through ZN-owned resource adapters;
- meaningful zero-model operation;
- ZN-owned filesystem/process/terminal/PTTY body paths;
- ZN-owned web search/extract sensing and network safety;
- practical Git repository sensing is being strengthened;
- durable work/thread/workspace/active-run state;
- resident-owned provider/settings and communication lifecycle;
- independent ZN runtime/package/desktop ownership.

These foundations are real. They do **not** yet prove mature-Agent-level complex task completion.

The most important current execution gap found in the active call chain is representative: a successful `BodyActionResult` can currently cause the resident event to complete immediately. That means the system still needs a stronger action → observation → verification loop before it can honestly claim robust long-horizon execution.

## 6. Ordered capability priorities

The mainline priority order is now explicit.

### P0 — Durable complex-task execution spine

Strengthen the existing resident event / WorkingState / Investigation / Action loop so one task remains one continuing cognitive process across many pulses and restarts.

Required properties include:

- retained goal and current gap;
- retained evidence and attempted actions;
- one concrete next action at a time;
- durable action intent/result;
- explicit expected outcome / verification state where applicable;
- final verification against the original requested state;
- no cognitive restart merely because one pulse or one model call ended.

Do not implement this as an ever-growing planner/task database.

### P1 — Reality verification and failure recovery

Turn the resident’s existing evidence discipline into a general execution discipline:

```text
intention
→ expected result
→ action
→ observed result
→ compare
→ verified / contradicted / uncertain
```

When verification fails:

```text
preserve the evidence
→ update Situation
→ revise the hypothesis / next action
→ avoid repeating the identical failed movement blindly
→ continue or surface a truthful unresolved outcome
```

### P2 — Practical Git + GitHub/repository work

Build enough resident-owned repository sense/body capability to perform real engineering tasks:

- branch/HEAD/upstream/worktree state;
- diffs and file changes;
- commits/history when relevant;
- safe Git mutation with explicit boundaries;
- GitHub repository/PR/CI read-only sense first;
- later controlled branch/PR write capability following self-maintenance risk rules.

This capability should later support SM2–SM4; it must not become a separate “coding agent” personality.

### P3 — Browser body/sense

Establish a clean ZN-owned browser lifecycle and structured observation/action contract. Do not embed the inherited browser/session product control plane.

### P4 — Visual + computer use

Add screen/visual evidence and mouse/keyboard/application movement where platform permissions allow it. Visual failure remains a sensory failure, not resident death.

### P5 — Broader practical capability composition

Add capabilities only because real tasks expose a missing body/sense seam. Breadth is useful when the same resident can compose it into sustained work.

### P6 — Real complex-task benchmark suite

Evaluate ZN on tasks that require many steps and verification, not on class/interface presence.

### P7 — Self-maintenance on top of the stronger execution spine

Continue SM1 → SM4 and later stages using the same resident execution architecture rather than building a separate maintenance brain.

## 7. Reference benchmark

A representative benchmark is:

```text
Give ZN an unfamiliar repository and a real failing CI result:

“Find why CI is failing, fix the defect, run the relevant validation,
check the resulting diff/state, and report the evidence.”
```

A mature result requires ZN to be able to continue something like:

```text
inspect repository/Git/CI
→ identify an unknown
→ inspect relevant code/tests/logs
→ form a hypothesis
→ modify through its Body
→ run tests
→ observe failure or success
→ verify the intended code/repository state
→ revise if contradicted
→ repeat until the original goal is actually satisfied
→ report concrete evidence
```

The benchmark still counts if ZN consults GPT/Claude/Gemini for a hard reasoning gap, provided the model never becomes owner of identity, work continuity, action authority or truth.

## 8. Immediate implementation sequence

The first concrete work after this direction update is:

1. close the current Git-sense CI failure honestly; the observed failure is a test-isolation defect caused by SQLite WAL/SHM files appearing inside the temporary Git workspace;
2. strengthen the active embodied call chain so successful state-changing Body movement does not immediately imply task completion;
3. add a durable post-action verification stage, beginning with filesystem text mutation where the requested postcondition is explicit and can be re-observed through `NativeBody`;
4. prove that verification survives a resident restart and still belongs to the same event;
5. prove a contradicted postcondition returns to investigation/failure recovery instead of silently completing or blindly repeating the same action;
6. then widen the same execution contract into practical repository work and GitHub/CI sensing;
7. use real benchmark failures to decide the next body/sense breadth rather than feature fashion.

This sequence is deliberately narrow: establish the execution spine first, then widen the body.

## 9. Capability-gap ledger

Current high-level expectation, always subject to code/test/CI evidence:

| Capability area | Current status |
| --- | --- |
| Persistent subject / zero-model life | strong foundation |
| Durable event/working-state continuity | strong foundation |
| Multi-pulse native investigation | active, breadth limited |
| Action → independent postcondition verification | **material gap / first target** |
| Failure recovery across many task steps | partial |
| Files/process/terminal body | active; composition depth incomplete |
| Git repository sense | active slice in progress |
| Git mutation for general resident work | incomplete |
| GitHub/PR/CI resident sense | missing as general resident capability |
| Web search/extract | active |
| Browser interaction | missing clean owned seam |
| Visual/screen sensing | foundation/partial, not mature computer use |
| Mouse/keyboard/application control | not mature/owned end-to-end |
| Long-horizon complex-task completion | **partial; main phase objective** |
| Self-maintenance | SM0 complete; SM1+ planned |

Use `DONE / PARTIAL / MISSING / DO NOT COPY` when a detailed repository-backed audit is performed. Never infer DONE merely from an interface or class existing.

## 10. M8/release lane boundary

M8 is not abandoned. Installation, resident continuity, update integrity, rollback and signing are necessary because a Self that cannot survive a body/runtime upgrade is not a complete product.

But release breadth no longer defines the main development lane while complex-task execution remains materially incomplete.

If M8 exposes a real continuity, identity, data-integrity or update-safety bug, fix it. Otherwise record the remaining release evidence explicitly and return to the core execution mainline.

## 11. UI boundary

UI work is allowed only when it is the minimum necessary surface for a core capability, for example:

- permission/approval for a body action;
- evidence needed to understand an ongoing resident task;
- browser/computer-use observation/control;
- a required maintenance approval surface;
- a real usability bug that blocks task completion.

Pure visual polish, layout churn and extra dashboarding are paused.

## 12. Phase success signal

This phase is moving correctly when repository evidence increasingly supports:

```text
ZN receives a complex durable task
→ the same Self owns it throughout
→ it investigates using owned senses
→ acts through owned Body capabilities
→ uses external cognition only when useful
→ observes what actually happened
→ does not confuse an action return value with goal completion
→ recovers from failure by changing its understanding/action
→ survives pulse/process/model interruption without losing the work
→ verifies the original requested state
→ records a truthful outcome and learns from it
```

The objective is not a more decorated desktop, a larger tool list, or a more elaborate planner.

The objective is **a persistent ZN subject that can actually finish hard things.**
