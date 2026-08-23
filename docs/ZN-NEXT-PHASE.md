# ZN next phase — Self + mature execution + resident competence

> Date: 2026-08-23
>
> Active branch: `dev/zn-agent`
>
> Governing architecture: [`../ZN.md`](../ZN.md)
>
> Memory/learning architecture: [`ZN-MEMORY-LEARNING.md`](ZN-MEMORY-LEARNING.md)
>
> Current implementation facts: [`ZN-IMPLEMENTATION-STATUS.md`](ZN-IMPLEMENTATION-STATUS.md)
>
> Self-maintenance contract: [`ZN-SELF-MAINTENANCE.md`](ZN-SELF-MAINTENANCE.md)

## 1. Product target for this phase

The organism-first architecture remains the governing design.

The concrete target is now:

> **ZN must keep its own durable Self, finish complex real-world/computer work through reality-based execution, and gradually turn verified experience into resident-owned competence that remains useful when external models are gone.**

The combination is:

```text
durable ZN Self
+ mature task-execution depth
+ reality-based verification
+ resident-owned learning / procedural competence
= the ZN we are building
```

Two failure modes are equally unacceptable:

```text
Self without practical competence
→ persistent but not useful enough
```

```text
impressive model/tool execution without resident ownership
→ conventional model-owned Agent architecture
```

The direction is not “call models more intelligently.” External models are replaceable cognitive resources. Skills that ZN has genuinely learned must increasingly belong to ZN itself.

## 2. Core invariants

Implementation work must preserve these invariants:

1. The same resident Self owns the task before, during and after model calls.
2. Work continuity lives in ZN-owned durable state, not in a model context window.
3. Investigation advances from current evidence, not from a giant static LLM plan.
4. Body actions are movements of ZN, not tools owned by an external planner.
5. **Action success is not task success.** Completion requires observed reality evidence.
6. Failure becomes new evidence and must not create uncontrolled retry loops.
7. Past memory/schema/skill is a prediction source, not proof; current reality can contradict it.
8. External models may suggest hypotheses/procedures/code, but ZN must test them.
9. A model response alone cannot create a mature resident skill.
10. Mature resident-owned competence should survive provider replacement and full model removal.
11. Familiar execution may become faster, but prediction error must interrupt automatic behavior and return control to Thought/Investigation.
12. Familiarity never bypasses safety/authorization boundaries.
13. No new capability may reintroduce Hermes or another agent framework as ZN’s control plane.

## 3. Current verified foundation

The current repository already has substantial foundations:

- persistent resident life and identity;
- meaningful zero-model operation;
- Situation / Thought / Will;
- durable events and `WorkingState`;
- multi-pulse native Investigation;
- native Action intents and Body movement;
- bounded external cognition through ZN-owned resources;
- `PersistentNervousSystem` with persistent traces;
- repeated experience strengthening an existing trace instead of endless duplicate entries;
- co-active associative links and spreading activation;
- local consolidation and schema formation;
- fading/pruning of weak isolated detail;
- reality-gated transfer/reconsolidation;
- internal lived/schema evidence influencing Situation/Thought without dumping private memory into external model context;
- structured read-only Git repository sense;
- exact text and explicit command postcondition verification;
- compact durable execution context;
- evidence-bound failed-action history;
- A → B → A blind replay suppression under unchanged Investigation evidence;
- changed reality facts can requalify an old movement;
- blocked post-cognition movement cannot falsely complete the task;
- ZN-owned local filesystem/process/terminal/PTTY and web paths;
- independent ZN runtime/package/desktop ownership.

These are real foundations. They do **not** yet prove mature procedural memory or mature general computer-use competence.

## 4. Current major gap

Current memory is already more than transcript storage, but the missing transition is still large:

```text
verified lived experience
→ reusable resident-owned competence
→ repeated verified practice
→ mature procedural tendency
→ familiar low-latency perception/action route
→ prediction-error interrupt / relearning
```

At present ZN can retain lived neural traces and schemas, but the project does not yet claim a first-class procedural skill substrate that can execute learned competence without asking an external model to reinterpret it.

Therefore stronger alternative-action recovery should no longer be developed as an isolated tactic generator. It should become an early consumer of the learning architecture.

## 5. Immediate implementation sequence

### P0 — Verified experience as a learning unit

Define and implement the smallest bounded resident-owned record connecting:

```text
Situation / evidence
+ goal or current gap
+ concrete action
+ expected outcome
+ observed verification result
+ success / contradiction
```

Requirements:

- survives resident restart;
- does not become a transcript dump;
- does not copy unnecessary raw command/content/secrets into broad long-term memory;
- model text alone cannot mark the experience successful;
- independent reality verification remains authority.

### P1 — Candidate procedural tendency

Allow repeated compatible verified experiences to produce a candidate resident-owned tendency.

Requirements:

- no one-shot skill creation;
- applicability/context remains explicit;
- success and contradiction both affect maturity;
- current reality gates activation;
- the representation can be used locally without an external model merely decoding it.

### P2 — Alternative-action recovery as learning consumer

Then strengthen recovery:

```text
movement A fails under evidence E
→ A remains blocked under E
→ Investigation establishes current reality
→ resident derives/selects genuinely different movement B
→ B executes through normal Body path
→ B is independently verified
→ E + failure(A) + verified success(B) becomes learning evidence
```

Later similar evidence should make B easier to activate without converting the system into a planner/task tree.

### P3 — Skill maturity, inhibition and de-proceduralization

Repeated verified use may mature a tendency. Repeated contradiction must weaken/narrow/inhibit it.

Prediction error must be able to interrupt familiar execution and return control to Thought/Investigation.

### P4 — Practical engineering competence

Use Git/repository work as an early benchmark because it exposes clear evidence and verification:

- inspect current repository reality;
- follow code/test call chains;
- change files through Body;
- run relevant tests;
- inspect diff/repository state;
- recover from contradiction;
- verify final requested state.

Then extend into safe Git mutation and GitHub repo/PR/CI sense.

### P5 — Computer-use competence

After a clean browser/visual/keyboard/mouse Body/Senses seam exists, apply the same learning architecture to computer use.

The goal is not screenshot-by-screenshot model control forever. Repeated verified interaction should gradually create resident-owned structural familiarity and procedural competence.

### P6 — Real growth benchmarks

Measure whether experience actually changes ZN:

- fewer external cognition calls on familiar task classes;
- fewer explicit deliberative steps where appropriate;
- lower latency / higher reliability;
- verification quality preserved;
- learned competence survives process/runtime restart;
- learned competence survives provider replacement and all-model removal;
- changed context prevents blind execution;
- prediction error interrupts automatic behavior;
- repeated contradiction weakens stale competence.

Do not optimize for minimum model calls at the expense of truth or safety.

## 6. Relationship to external models

The desired maturity gradient is:

```text
young / unfamiliar ZN
→ more Investigation, explicit Thought and optional external cognition

experienced ZN
→ more resident recall and learned procedural tendency

mature familiar competence
→ lower-cost resident-owned execution
→ external cognition reserved for genuine novelty / hard reasoning gaps
```

A model can teach or help solve a new problem. The verified experience produced by ZN’s own Body/Senses is what can become resident competence.

## 7. Reference engineering benchmark

A representative benchmark remains:

```text
Give ZN an unfamiliar repository and a real failing CI result:

“Find why CI is failing, fix the defect, run the relevant validation,
check the resulting diff/state, and report the evidence.”
```

A mature resident should eventually be able to:

```text
inspect repository/Git/CI
→ identify an unknown
→ inspect code/tests/logs
→ form a hypothesis
→ modify through its Body
→ run tests
→ observe result
→ verify diff/repository state
→ revise tactic if contradicted
→ learn from the verified relationship between Situation/action/outcome
→ repeat until the original goal is satisfied
→ report concrete evidence
```

The benchmark still counts if ZN consults GPT/Claude/Gemini for genuine novelty, provided the model never owns identity, work continuity, action authority, truth or learned competence.

## 8. UI / release boundary

Pure UI polish remains paused.

Desktop work is justified when required for:

- body/sense permissions;
- visible evidence/approval;
- browser/computer-use interaction;
- maintenance approval;
- a real usability defect blocking core work.

M8/release remains a bounded continuity/release lane. Real identity/data-integrity/update-safety defects should still be fixed when discovered.

## 9. Phase success signal

This phase is moving correctly when repository evidence increasingly supports:

```text
ZN receives a durable task
→ same Self owns it throughout
→ investigates using owned senses
→ acts through owned Body
→ verifies reality
→ stores verified experience rather than only text history
→ repeated compatible experience changes future resident behavior
→ familiar work needs less external cognition
→ mature skill still works with external models removed
→ stale skill is interrupted by prediction error
→ new evidence causes relearning
→ original task is truthfully completed and learned from
```

The objective is not a bigger prompt, a larger vector database, a more elaborate planner or a larger catalog of model-called tools.

The objective is **a persistent ZN subject that gets better at living and doing because of what it has actually experienced.**
