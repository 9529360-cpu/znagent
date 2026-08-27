# ZN resident intelligence — built-in competence, lived learning and external cognition

> Governing architecture: [`../ZN.md`](../ZN.md)
>
> Learning architecture: [`ZN-MEMORY-LEARNING.md`](ZN-MEMORY-LEARNING.md)
>
> Current implementation truth: [`ZN-IMPLEMENTATION-STATUS.md`](ZN-IMPLEMENTATION-STATUS.md)
>
> This document defines product/architecture direction. It does **not** claim the runtime already implements the whole contract.

## 1. Product goal

ZN should feel increasingly like a capable long-lived person living in the computer, not like a stateless agent that becomes intelligent only while a powerful model is answering.

The desired intelligence stack is:

```text
resident-owned built-in competence
+ resident-owned learned competence
+ replaceable external cognition for novelty
= ZN intelligence
```

A stronger external model may improve difficult reasoning, but replacing, degrading or disconnecting that model must not erase ZN's identity or the mature competence it already owns.

## 2. Do not build a newborn Agent every turn

A recurring failure mode in agent systems is:

```text
new task
→ assemble prompt
→ ask model what to do
→ call tools
→ forget most operational knowledge
→ repeat from scratch next time
```

That may produce impressive first-run demonstrations, but it is not the desired ZN product.

ZN should not repeatedly pay a model to rediscover mature low-level facts that the system itself can know and verify.

Examples include:

- a file write needs conflict-aware current-state evidence;
- process exit code is not proof that the user's goal succeeded;
- a browser target may become stale after navigation or DOM replacement;
- a popup/new tab changes page situation;
- a side effect may have happened even if the process crashed before recording completion;
- the same action must not be blindly replayed when outside-world outcome is unknown;
- an expected postcondition must be checked after mutation;
- current environment drift can invalidate a previously successful procedure.

When these are known engineering realities, they should become resident mechanisms and tests rather than recurring prompt instructions.

## 3. Three sources of intelligence

### 3.1 Built-in resident competence

Built-in competence is mature domain knowledge expressed as ZN-owned executable structure.

It can live in:

- typed state and action contracts;
- Body/Senses implementations;
- deterministic state machines;
- verification/postcondition rules;
- retry and uncertainty semantics;
- crash/restart recovery;
- conflict detection;
- provider abstraction boundaries;
- anomaly detection;
- capability implementations;
- tests and CI guards.

This is where general software-engineering knowledge should crystallize when it is stable, testable and appropriate to ZN.

A useful rule for maintainers is:

> If we already understand a recurring class of failure well enough to express and verify it deterministically, do not leave it as a prompt-level reminder unless there is a good reason.

### 3.2 Learned resident competence

Learned competence belongs to ZN's lived history.

It includes things that cannot be correctly hard-coded for every user or environment, such as:

- recurring project-specific workflows;
- familiar application structures;
- user-preferred working conventions;
- repeated anomaly patterns;
- reliable recovery paths discovered through experience;
- expected outcomes for familiar procedures;
- context in which a formerly useful tactic became unreliable.

Learned competence must come from verified experience, not from merely storing model prose.

### 3.3 External cognition

External models are powerful cognitive resources for:

- unfamiliar situations;
- broad knowledge retrieval;
- complex reasoning;
- hypothesis generation;
- code/procedure suggestions;
- interpretation when local competence is insufficient.

The correct boundary is:

```text
ZN identifies a real gap
→ optional external cognition
→ candidate explanation / tactic / code
→ ZN checks reality
→ ZN acts through owned Body
→ ZN observes and verifies
→ verified experience may become resident competence
```

A model response alone is never enough to create a permanent skill, fact, completion result or action authority.

## 4. Knowledge crystallization

The project should continuously convert applicable mature knowledge into ZN-owned behavior.

```text
known recurring problem
→ identify the invariant and observable evidence
→ encode the smallest useful resident mechanism
→ test normal and adversarial cases
→ make it survive restart/provider replacement where appropriate
→ remove repeated dependence on prompt rediscovery
```

This is not a mandate to hard-code everything. It is a mandate to stop wasting model cognition on solved mechanics.

Examples:

### File mutation

A naive implementation is:

```text
model asks to write
→ write bytes
```

A mature resident path may need to reason about:

```text
current file identity/state
→ intended mutation
→ durable effect ownership where replay matters
→ safe write semantics
→ fresh post-write observation
→ intended-state verification
→ conflict/external-change detection
→ restart recovery without blind overwrite
```

### Browser interaction

A naive implementation is:

```text
model sees screenshot
→ click coordinate
→ assume success
```

A mature resident path should increasingly know about:

- page/session identity;
- stale DOM/accessibility/UIA targets;
- navigation and redirects;
- new tabs/popups;
- frame boundaries;
- focus state;
- semantic postconditions;
- the need to re-sense after significant UI transitions.

### Repeated workflows

A naive implementation is:

```text
same task tomorrow
→ send almost the same prompt again
```

A mature resident path is:

```text
recognize familiar Situation
→ activate learned procedure
→ check applicability/current evidence
→ execute familiar steps efficiently
→ verify expected transitions
→ detect exceptions
→ stop automatic continuation on contradiction
→ investigate/relearn when required
```

## 5. Reliability is intelligence

For a long-lived computer resident, intelligence is not just one-shot reasoning quality.

A useful product definition of intelligence includes:

- repeated-task success rate;
- consistency across long time periods;
- ability to detect when today's situation differs from yesterday's;
- ability to know when evidence is insufficient;
- self-correction after unexpected outcomes;
- refusal to fabricate completion;
- restart continuity;
- side-effect idempotency/uncertainty handling;
- retention of learned competence;
- provider independence;
- reduction in unnecessary deliberation on familiar work.

A task succeeding once in a polished demo is weak evidence. The stronger benchmark is whether ZN can perform the same task family many times, become more efficient, and still stop when reality no longer matches the learned pattern.

## 6. The hundred-and-first repetition rule

A particularly important benchmark is repeated work.

Suppose ZN has completed a workflow successfully one hundred times.

The desired behavior on attempt 101 is **not** blind replay.

It is:

```text
strong familiarity
+ fast recognition
+ low unnecessary reasoning cost
+ current-state checks
+ explicit expected outcomes
+ anomaly interrupt
```

If the environment changed, confidence from prior success must not override current evidence.

A mature ZN should be able to say, conceptually:

> This looks like the familiar job, but today's input differs at a point that matters. I will not continue using the old procedure until I re-establish what is true.

That ability is more important than merely increasing the number of autonomous actions.

## 7. Familiarity should reduce cognition cost, not verification quality

Learning should eventually move common work along this gradient:

```text
unfamiliar
→ explicit Thought
→ Investigation
→ possible external model use
→ careful stepwise Action

practiced
→ resident recall
→ fewer deliberative steps
→ less model use

mature familiar competence
→ fast resident procedure
→ continuing current-state sensing and verification
```

The wrong optimization is:

```text
familiar task
→ skip sensing/verification
```

The right optimization is:

```text
familiar task
→ reduce redundant deliberation
→ preserve evidence and prediction checks
```

## 8. Prediction error is a first-class control signal

ZN must recognize when a familiar procedure stops matching reality.

```text
expected transition
≠ observed transition
→ prediction error
→ stop automatic continuation
→ invalidate/narrow current assumption
→ Thought / Investigation resumes
→ adapt, recover or relearn
```

This should apply across computer use, engineering workflows, files, browser behavior and learned routines.

Repeated contradiction should be able to weaken or inhibit procedural competence. A system that only accumulates confidence and never forgets bad habits is not mature.

## 9. Model quality must not equal ZN quality

It is acceptable for difficult novel reasoning to improve when a better model is available.

It is not acceptable for routine resident competence to vary wildly just because provider routing changed.

For mature task families, important behavior should increasingly be stable across:

- model providers;
- provider versions;
- short-term outages;
- context-window changes;
- resident restarts;
- runtime upgrades.

This does not imply identical natural-language reasoning. It means the ZN-owned operational invariants and learned capabilities remain intact.

## 10. Questions that must be answered by reality, not model confidence

Some facts must be established through owned state or fresh observation.

Examples:

```text
Did the side effect already happen?
Did the file actually reach the intended content?
Did the browser submission really succeed?
Is this still the same page/control/file/process?
Did the user or another process change the object after our checkpoint?
Is this event terminal?
Did restart leave an unresolved outside-world effect?
```

A model may help interpret evidence, but it cannot manufacture that evidence.

## 11. Product-manager test for every major feature

When adding a capability, maintainers should ask two sets of questions.

Engineering correctness:

- What is the active caller?
- Who owns state and lifecycle?
- What evidence proves success?
- What happens across crash/restart?
- What happens when the provider lies/fails/changes?

Resident intelligence:

- Does this make ZN less dependent on repeated model rediscovery?
- What general knowledge should become built-in competence?
- What user/project-specific part should be learnable through experience?
- Can ZN notice when the learned pattern no longer applies?
- Does the capability become more reliable after repeated verified use?
- Does mature capability survive provider replacement?

A feature that passes its API test but makes ZN more stateless or more model-owned can still be a product regression.

## 12. Benchmarks

Future evaluation should include more than one-shot capability tests.

### 12.1 Repetition benchmark

Run a task family many times with realistic variation.

Measure:

- success rate;
- duplicate side effects;
- unnecessary model calls;
- time/steps to completion;
- anomaly detection;
- correction behavior;
- whether verification quality remains stable.

### 12.2 Drift benchmark

After familiarity develops, intentionally change a relevant environmental condition.

Pass condition:

- ZN detects the mismatch;
- old procedure does not continue blindly;
- Investigation resumes;
- stale competence is weakened/narrowed if evidence warrants it.

### 12.3 Model replacement benchmark

Repeat mature familiar work with:

- preferred model;
- alternate provider;
- weaker provider where feasible;
- no external model for bounded learned tasks.

Pass condition: resident-owned competence remains materially useful and operational invariants remain stable.

### 12.4 Restart benchmark

Interrupt familiar work at meaningful points and restart.

Pass condition:

- ZN knows what was durably established;
- unknown external effects stay unknown rather than being blindly replayed;
- learned competence and identity survive;
- work resumes or fails closed based on real evidence.

## 13. Relationship to current implementation

The repository already has real foundations that fit this direction, including:

- model-independent resident identity/state;
- Situation / Thought / Will;
- durable Work/event/WorkingState paths;
- independent post-action verification on several Body/browser paths;
- side-effect attempt ownership and replay blocking;
- persistent nervous memory/reconsolidation;
- bounded candidate procedural influence;
- crash/restart recovery evidence;
- resident-owned browser action/evidence contracts.

These foundations do **not** mean this document is fully implemented.

Important missing work still includes broader procedural learning, wider computer-use competence, long-horizon repeated-task benchmarks, broader Work restore/recovery, richer anomaly handling, scheduled/active resident behavior and many product-level integrations.

Current implementation status remains authoritative in `docs/ZN-IMPLEMENTATION-STATUS.md`.

## 14. Maintenance rule

The maintainer's own knowledge should be used proactively, but only through an engineering transfer process:

```text
known mature mechanism / cross-domain insight
→ verify that ZN has the concrete need
→ inspect current ZN ownership/call chain
→ adapt the mechanism to ZN semantics
→ test against real behavior and failure modes
→ record verified implementation truth
```

Do not preserve useful knowledge only in chat. If a principle changes how future ZN should be built, put it into repository architecture/documentation. If it becomes implemented behavior, encode it in code and tests.

The goal is simple:

> Over time, more of the intelligence needed for reliable everyday computer life should belong to ZN itself, while models remain powerful but replaceable cognitive resources.
