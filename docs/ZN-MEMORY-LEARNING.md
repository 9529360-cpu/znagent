# ZN Memory, Learning and Procedural Competence

> Date: 2026-08-23
>
> Active branch: `dev/zn-agent`
>
> Governing architecture: [`../ZN.md`](../ZN.md)
>
> Current implementation facts: [`ZN-IMPLEMENTATION-STATUS.md`](ZN-IMPLEMENTATION-STATUS.md)

## 1. Purpose

ZN is not intended to be an LLM wrapper whose memory exists mainly to feed old text back into a model.

The target is a long-lived resident subject whose own competence changes through experience.

The governing principle is:

> **Models may help ZN learn. Mature capability must belong to ZN.**

A mature ZN should become more capable through repeated verified experience even if every external model is later disconnected.

This document defines the memory/learning direction needed to make that true.

It is not a claim that the current implementation already has mature procedural learning. Current code already has useful lived-memory foundations, but the path from experience to reusable resident-owned skill remains incomplete.

## 2. What ZN must not become

The project must not collapse back into this pattern:

```text
experience
→ save transcript / summary / embedding
→ future task
→ retrieve text
→ inject into LLM context
→ LLM decides what to do
```

That pattern can be useful as support memory, but it does not make the learned ability belong to ZN.

Likewise, these are insufficient:

```text
successful model answer
→ cache answer
→ call cache a skill
```

```text
successful shell command
→ store exact command forever
→ replay on matching keywords
```

```text
successful mouse click
→ store screen coordinates
→ replay regardless of current visual structure
```

Those approaches can create brittle automation, not resident competence.

## 3. Memory layers

ZN should distinguish several related but different memory roles.

### 3.1 Working / current-event memory

Purpose:

- maintain the current goal;
- current Situation;
- active Investigation;
- current gap;
- attempted actions;
- expected outcome;
- verification evidence;
- current Will/attention.

This must stay bounded and task-relevant. It is not long-term memory and must not become an ever-growing plan tree.

Current implementation already has meaningful foundations through durable events, `WorkingState`, Investigation and compact execution context.

### 3.2 Episodic / lived experience memory

An episode should eventually preserve the causal shape of an experience, not merely the text around it.

Conceptually:

```text
Situation before action
→ goal / gap
→ evidence available at the time
→ action or probe
→ expected result
→ actual observed result
→ verification verdict
→ consequence for Situation / Will
```

A useful episode lets ZN later answer questions such as:

- what did I encounter;
- what did I believe then;
- what did I try;
- what actually happened;
- what changed my understanding;
- what finally worked or failed;
- why I considered the outcome verified.

Not every pulse or log line deserves a permanent episode. Episodes must be compact, evidence-oriented and subject to consolidation/fading.

### 3.3 Semantic / structured knowledge

This includes stable facts, relations and reusable conceptual knowledge that are not tied to one episode.

Examples:

- a repository uses a certain test command;
- a user-approved project convention;
- a known API constraint;
- a recurring software relationship;
- a stable local machine fact.

Structured fact stores and future semantic retrieval may support this layer.

Semantic memory is still prediction/support, not authority over current reality.

### 3.4 Associative nervous memory

This is the current `PersistentNervousSystem` direction:

```text
experience
→ traces
→ repetition strengthens traces
→ co-activation strengthens relations
→ cue-driven activation spreads through relations
→ recurring structure consolidates
→ weak isolated detail can fade
→ present reality can support or contradict old structure
→ reconsolidation changes future activation
```

This layer is important because it allows experience to change ZN locally without requiring an external model to encode or retrieve every memory.

### 3.5 Procedural memory / learned competence

This is the major missing layer.

Procedural memory means ZN does not merely remember that a procedure exists. It becomes able to perform a class of behavior through its own resident machinery.

Conceptually a learned competence needs at least:

```text
applicability pattern
+ goal/gap pattern
+ action/procedure tendency
+ expected outcome model
+ confidence/maturity
+ supporting verified evidence
+ contradictory evidence
+ inhibition/staleness state
+ risk/safety boundary
```

The representation does not need to look exactly like this, but these semantics must exist somewhere.

A mature skill must not require an external model call merely to interpret or execute it.

### 3.6 Perception-action familiarity / reflex

The fastest learned route is a familiar Situation directly activating a mature action tendency.

```text
familiar perception / Situation
→ mature procedural tendency
→ resident Body movement
→ immediate feedback
→ prediction check
```

This is called a reflex only in a computational/product sense. It is not a claim that ZN reproduces human neurobiology.

A reflex is valid only while reality continues to match its prediction.

## 4. From novel work to mature competence

The desired learning gradient is:

```text
novel situation
→ explicit Thought
→ Investigation
→ optional external cognition
→ concrete resident action
→ observe reality
→ verify / contradict
→ episodic evidence
→ associative integration
→ recurring pattern
→ candidate procedural tendency
→ repeated verified use
→ mature skill
→ familiar perception-action route
```

As maturity increases, familiar work should require less explicit deliberation and fewer external cognition calls.

The target is not zero reasoning. The target is to stop re-solving already learned work from scratch.

## 5. Verification is part of learning

ZN must not learn from action return values alone.

Bad learning unit:

```text
command exited 0
→ reinforce skill
```

Better learning unit:

```text
Situation
→ action
→ expected outcome
→ independent observation
→ verified outcome
→ reinforce relationship
```

Contradiction is equally important:

```text
Situation
→ familiar action
→ predicted result
→ reality disagrees
→ weaken / inhibit old tendency
→ return to Thought / Investigation
```

This is why the existing action/postcondition verification work is a foundation for future learning rather than a separate concern.

## 6. Prediction error must interrupt automatic behavior

A mature ZN must be able to become less automatic when the world changes.

```text
familiar skill activates
→ action
→ expected sensory/result pattern does not appear
→ prediction error
→ stop or inhibit automatic continuation
→ elevate uncertainty
→ Thought / Investigation regains control
```

Repeated contradiction should be able to:

- reduce confidence;
- narrow applicability context;
- temporarily inhibit a tactic;
- de-proceduralize a previously automatic route;
- trigger reconsolidation or relearning.

A behavior that only strengthens and never weakens is unsafe and not human-like in the useful sense.

## 7. External cognition and learning ownership

External models can be valuable teachers/advisers for unfamiliar work.

Correct relationship:

```text
ZN identifies a genuine gap
→ asks bounded external cognition
→ receives candidate explanation/tactic/code
→ ZN checks it against current reality
→ ZN acts through its own Body
→ ZN independently observes result
→ verified experience enters learning
```

Incorrect relationship:

```text
model proposes procedure once
→ procedure immediately becomes trusted permanent skill
```

Model output is not learning evidence by itself.

The long-term success condition is that provider replacement or total model removal does not erase already learned resident-owned competence.

## 8. Computer-use competence

Computer use should become progressively familiar rather than remain screenshot-by-screenshot LLM control.

Early/unfamiliar use may look like:

```text
visual observation
→ deliberate interpretation
→ decide one action
→ click/type
→ observe again
```

With verified familiarity, reusable structure should emerge:

```text
application/window structure
+ focus state
+ control relationships
+ keyboard/mouse patterns
+ expected visual transitions
→ procedural competence
```

Mature computer-use learning should prefer structural anchors and current visual state over absolute coordinates.

Examples of eventual resident-owned competence:

- navigating familiar application layouts;
- focusing common input surfaces;
- using stable keyboard shortcuts;
- handling common dialogs;
- opening/closing contextual tools;
- recognizing expected post-action visual transitions;
- recovering when the UI no longer matches the learned structure.

## 9. Engineering competence

Programming and repository work should also proceduralize.

A mature ZN should not need to ask an external model how to perform every recurring engineering routine.

Examples of learnable engineering competence:

- establish current repository reality before modification;
- inspect failing diagnostics before guessing;
- follow a real call chain before editing behavior;
- identify and run the most relevant test first;
- verify diff/repository state after modification;
- distinguish action success from goal success;
- change tactic when evidence contradicts the current hypothesis;
- preserve branch/safety boundaries;
- recognize recurring project-specific workflows.

These should not be stored as one giant hard-coded checklist. Repeated verified use should gradually make the relevant tendencies easier to activate in matching contexts.

## 10. Skill maturity

A future implementation should make maturity explicit enough to test.

A useful conceptual progression is:

```text
candidate
→ supported
→ practiced
→ mature
→ procedural
```

And in the other direction:

```text
procedural
→ contradicted
→ inhibited
→ weakened
→ relearning / retired
```

Exact names and thresholds are implementation details.

Important invariants:

- one success does not create a mature skill;
- repeated success without independent verification is insufficient;
- maturity is context-sensitive;
- high-risk behavior requires authorization regardless of maturity;
- new evidence can lower maturity;
- skills survive process/runtime restarts when they are truly resident-owned.

## 11. Relationship to current `PersistentNervousSystem`

Current code already provides real foundations:

- persistent `NeuralTrace` records;
- repeated experience strengthening one trace instead of endless duplicate memories;
- co-active trace association;
- cue-driven activation with associative spreading;
- salience/strength/repetition/recency effects;
- persistent affective tone;
- local consolidation;
- abstraction/schema formation;
- fading/pruning of weak isolated detail;
- restart continuity;
- reality-gated transfer/reconsolidation behavior;
- internal trace/schema influence on Situation/Thought without dumping private memory into external model context.

These are not yet equivalent to mature procedural memory.

The missing transition is roughly:

```text
activated lived/schema evidence
→ candidate action/procedure tendency
→ reality-gated practice
→ explicit maturity
→ reusable resident-owned competence
→ faster familiar execution
→ prediction-error inhibition/relearning
```

Future work should extend the existing nervous architecture rather than bolt a conventional LLM skill database beside it and call the problem solved.

## 12. Relationship to alternative-action recovery

Alternative-action recovery remains important, but it should become part of learning rather than a disconnected tactic generator.

Desired loop:

```text
movement A fails under evidence E
→ A remains inhibited under E
→ Investigation establishes additional reality
→ resident derives/selects genuinely different movement B
→ B executes through normal Body path
→ B's postcondition is independently verified
→ the relationship E + failure(A) + success(B) becomes learning evidence
```

Later:

```text
similar evidence E'
→ B is easier to activate as a candidate
→ repeated verified success matures the tendency
```

This creates real accumulated competence instead of repeatedly asking a model for a new plan.

## 13. First implementation slices

Do not attempt full human-like memory at once.

The first coherent learning sequence should be:

### L0 — Architecture contract

Status: **DEFINED by `ZN.md` and this document**.

No runtime behavior is claimed by this status.

### L1 — Verified experience record

Create one bounded resident-owned structure that links:

- Situation/evidence fingerprint;
- goal/gap class;
- concrete action identity;
- expected outcome;
- observed verification result;
- success/contradiction;
- source event/time;
- privacy/safety-safe summaries rather than unnecessary raw payloads.

The record must survive restart and must not be a transcript dump.

### L2 — Candidate procedural tendency

Repeated compatible verified experiences can form a candidate tendency.

Requirements:

- no one-shot skill creation;
- model text alone cannot create it;
- context/applicability remains explicit;
- contradiction is retained;
- raw secrets/unsafe command payloads are not copied into broad memory.

### L3 — Reality-gated skill activation

A candidate/mature tendency can influence resident deliberation only when current Situation provides enough matching evidence.

Current reality remains authoritative.

### L4 — Procedural fast path

Mature low-risk competence may bypass some explicit deliberative stages while still preserving:

- authorization;
- expected outcome;
- Body execution;
- observation;
- verification;
- prediction-error interrupt.

### L5 — Inhibition / de-proceduralization / relearning

Contradictions weaken or inhibit stale competence and return control to Investigation.

### L6 — Computer-use and engineering competence benchmarks

Prove that repeated verified experience causes measurable improvements without model dependence.

## 14. Benchmarks for real growth

The following are better growth metrics than raw memory count.

For the same task family after verified practice:

- external cognition calls decrease when novelty decreases;
- explicit Thought/Investigation steps decrease when appropriate;
- completion latency decreases;
- success/recovery reliability improves;
- verification quality does not decrease;
- the competence survives resident restart;
- the competence survives runtime replacement;
- the competence survives switching model providers;
- the competence still works with all external models disabled;
- changed context prevents blind replay;
- prediction error interrupts the fast path;
- repeated contradiction weakens the stale tendency;
- successful alternative tactics become easier to select in similar situations.

Do not optimize for minimum model calls if doing so lowers truthfulness or safety.

## 15. Safety and privacy boundaries

Proceduralization must never bypass existing high-risk boundaries.

Familiarity does not authorize:

- destructive filesystem operations;
- force pushes/history rewrite;
- credential access or permission expansion;
- identity or long-term-memory destructive migration;
- updater/rollback/signing integrity changes;
- self-maintenance approval-rule changes;
- irreversible user-data changes.

Procedural memory should store the minimum information necessary to reproduce competence. Raw secrets, arbitrary private content and full shell histories should not be copied into long-lived learned structures merely because they appeared during successful work.

## 16. Completion signal

This direction is working when ZN increasingly behaves like a long-term resident who has become practiced at its environment:

```text
first encounter
→ slow / investigative / may need models

repeated verified encounters
→ more resident recall and learned tendency

mature familiar case
→ mostly resident-owned skill / low-latency action

world changes
→ prediction error
→ automatic path stops
→ Thought / Investigation resumes
→ new verified experience updates competence
```

The end goal is not to imitate a biological brain literally.

The end goal is a resident subject that can truthfully say, in computational terms: **I learned how to do this, and I still know how even when the models are gone.**
