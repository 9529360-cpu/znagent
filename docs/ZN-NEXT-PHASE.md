# ZN next phase — Self + mature execution + resident competence

> Date: 2026-08-23
>
> Active branch: `dev/zn-agent`
>
> Governing architecture: [`../ZN.md`](../ZN.md)
>
> Memory/learning architecture: [`ZN-MEMORY-LEARNING.md`](ZN-MEMORY-LEARNING.md)
>
> Current facts: [`ZN-IMPLEMENTATION-STATUS.md`](ZN-IMPLEMENTATION-STATUS.md)
>
> Self-maintenance: [`ZN-SELF-MAINTENANCE.md`](ZN-SELF-MAINTENANCE.md)

## 1. Product target

The organism-first architecture remains the governing design.

> **ZN must keep its own durable Self, finish complex real-world/computer work through reality-based execution, and gradually turn verified experience into resident-owned competence that remains useful when external models are gone.**

```text
durable ZN Self
+ mature task-execution depth
+ reality-based verification
+ resident-owned learning / procedural competence
= the ZN we are building
```

Persistent identity without practical competence is insufficient. Impressive model/tool execution without resident ownership is also insufficient.

## 2. Core invariants

1. The same resident Self owns work before, during and after model calls.
2. Work continuity lives in ZN-owned durable state, not in a model context window.
3. Investigation advances from current evidence, not from a giant static LLM plan.
4. Body actions are movements of ZN, not tools owned by an external planner.
5. Action success is not task success; completion requires observed reality evidence.
6. Failure becomes new evidence and must not create uncontrolled retry loops.
7. Past memory/schema/skill is prediction/support, never proof over current reality.
8. External models may suggest hypotheses, procedures or code; ZN must test them.
9. A model response alone cannot create mature resident skill.
10. Mature competence should survive provider replacement and full model removal.
11. Prediction error must interrupt stale automatic behavior and return control to Thought/Investigation.
12. Familiarity never bypasses safety or authorization boundaries.
13. No new capability may introduce another product/agent framework as ZN's runtime or control plane.
14. The active repository must remain source-independent and ZN-only.

## 3. Current verified foundation

The current repository already has substantial foundations:

- persistent resident life and identity;
- meaningful zero-model operation;
- Situation / Thought / Will;
- durable events and WorkingState;
- multi-pulse native Investigation;
- native Action intents and Body movement;
- bounded external cognition through ZN-owned resources;
- persistent nervous traces, associations and schema formation;
- fading/pruning and reality-gated reconsolidation;
- structured Git repository and scoped diff senses;
- exact text and explicit command postcondition verification;
- compact durable execution context;
- evidence-bound failed-action history;
- current-reality-gated alternative choices;
- independently verified experience records;
- candidate procedural tendencies and bounded procedural influence;
- tracked exact-replacement repository-delta verification;
- targeted Python unittest verification and a narrow resident-owned test-identity formation contract;
- ZN-owned local filesystem/process/terminal/PTTY/web/channel paths;
- independent ZN runtime/package/desktop/build/release ownership;
- physical core source under `runtime/python/zn_agent/core` and tests under `tests/zn_agent/core`.

These are real foundations. They do not yet prove mature general procedural memory or mature general computer-use competence.

## 4. Repository-boundary work is no longer the main lane

Physical reference-source evacuation is complete on `dev/zn-agent`. Do not continue treating migration cleanup as the product roadmap.

Steady-state rule:

```text
need mature mechanism
→ inspect Git history or external reference
→ understand it
→ adapt behind ZN ownership
→ test current ZN behavior
→ keep the active tree source-independent
```

The main engineering lane can therefore return to resident competence and release continuity.

## 5. Immediate implementation sequence

### P0 — Protect the ZN-only boundary

Keep normal CI, ownership tests and package/runtime verifiers green. A regression that restores a foreign product path/control plane is an architecture defect, not a compatibility requirement.

### P1 — Broaden resident-owned engineering verification carefully

The existing exact-replacement + repository-delta + Python unittest contract is intentionally narrow.

Next work should search for repo-owned structured verifier mappings that current evidence can prove, for example configuration/manifest/CI relationships. Do not guess arbitrary commands from filenames or model suggestions.

Required negatives before widening execution authority include:

- ambiguous mapping;
- stale config;
- dirty verifier/config evidence;
- cross-target identity;
- symlink/path escape;
- HEAD drift;
- restart after execution-start marker;
- output/exit-code success without current-world proof.

### P2 — Turn verified recovery into broader competence

Desired loop:

```text
movement A fails under evidence E
→ A remains blocked under E
→ Investigation establishes current reality
→ resident forms/selects genuinely different movement B
→ B executes through normal Body path
→ B is independently verified
→ E + failure(A) + verified success(B) becomes learning evidence
```

Similar future evidence may make B easier to activate, but learned memory must not become stored raw side-effect replay.

### P3 — Skill maturity, inhibition and relearning

Repeated verified use may mature a tendency. Repeated contradiction must weaken, narrow or inhibit it.

Prediction error must be able to interrupt familiar execution and return control to Thought/Investigation.

### P4 — Browser/computer-use Body and Senses

Establish a genuinely ZN-owned browser/visual/keyboard/mouse seam before adding computer-use competence.

The goal is not screenshot-by-screenshot model control forever. Repeated verified interaction should gradually create resident-owned structural familiarity and procedural competence.

### P5 — M8 release continuity

Close the remaining release lane deliberately:

- installed N → N+1 application/runtime/resident handoff;
- intended-platform clean-install/login continuity evidence;
- rollback across a real version transition;
- signing/notarization through secure repository-defined release infrastructure.

Do not let release debt quietly become “done” because package ownership is already strong.

### P6 — SM1+ self-maintenance

Advance ZN's ability to detect, investigate and prepare its own fixes only behind the existing branch/PR/CI and human-approval boundaries.

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

A model can teach or help solve a new problem. The verified experience produced by ZN's own Body/Senses is what can become resident competence.

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
→ run a reality-proven verifier
→ observe result
→ verify diff/repository state
→ revise tactic if contradicted
→ learn from Situation/action/outcome
→ repeat until the original goal is satisfied
→ report concrete evidence
```

Consulting an external model for genuine novelty is allowed, provided the model never owns identity, work continuity, action authority, truth or learned competence.

## 8. Growth benchmarks

For the same task family after verified practice, look for:

- fewer external cognition calls when novelty decreases;
- fewer explicit deliberative steps where appropriate;
- lower latency and higher reliability;
- verification quality preserved;
- competence surviving resident restart;
- competence surviving runtime replacement;
- competence surviving provider replacement/all-model removal;
- changed context preventing blind execution;
- prediction error interrupting stale behavior;
- repeated contradiction weakening stale competence.

Do not optimize model-call count at the expense of truth or safety.

## 9. Phase success signal

This phase is moving correctly when repository evidence increasingly supports:

```text
ZN receives durable work
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

The objective is not a bigger prompt, vector database, planner or catalog of model-called tools. The objective is a persistent ZN subject that gets better because of what it has actually experienced.