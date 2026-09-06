# ZN Learning / Continual-Learning Source Research

> Date: 2026-08-23
>
> Canonical branch: `main`
>
> Active development: short-lived `work/*` branches from current `main`; `dev/zn-agent` is historical compatibility only.
>
> Governing architecture: [`../ZN.md`](../ZN.md)
>
> Memory/learning contract: [`ZN-MEMORY-LEARNING.md`](ZN-MEMORY-LEARNING.md)
>
> Current implementation facts: [`ZN-IMPLEMENTATION-STATUS.md`](ZN-IMPLEMENTATION-STATUS.md)

## 1. Purpose

ZN should not reimplement decades of continual-learning, imitation-learning, world-model and embodied-control research from scratch.

The goal of this document is narrower and safer than “pick an AI framework”:

```text
find mature mechanisms / research / benchmark infrastructure
→ understand what problem each mechanism actually solves
→ map it to a real ZN organ/call chain
→ borrow algorithms, tests or bounded components where useful
→ keep ZN as the owner of Self / memory / action / verification
```

The governing rule remains:

> **Models may help ZN learn. Mature capability must belong to ZN.**

There is no single external project in this survey that should become ZN's brain or resident control plane.

The useful result is a set of reusable mechanisms that can shorten development of resident-owned learning.

## 2. Current ZN attachment points found in real code

This research is not being mapped onto an empty design.

### 2.1 Verified action/outcome labels already exist

The active embodied path already has:

```text
Situation / Investigation evidence
→ NativeActionIntent
→ Body
→ BodyActionResult
→ durable postcondition when available
→ independent Body observation
→ verified / contradicted
```

`EmbodiedResidentRuntime._native_verification_step()` produces resident-owned verification evidence, and `_complete_successful_body_action()` only completes verified postconditions where a verification contract exists.

This is the correct source of learning labels. A model answer or action return value alone is not enough.

### 2.2 Associative memory and prediction-error machinery already exist

`PersistentNervousSystem` already provides persistent traces, repetition, association, cue activation, consolidation, fading and schema formation.

`SchemaReconsolidator` already compares schema predictions with current evidence and records support / refinement / contradiction plus prediction error.

Therefore ZN does not need a separate LLM-memory product to obtain the basic concepts of association and reconsolidation.

### 2.3 A capability execution boundary already exists

`CallableCapability` explicitly supports deterministic zero-token capabilities and already documents the future possibility of compiling learned procedures into capabilities.

`PromotedCapabilityLoader` also already establishes a safety boundary:

```text
candidate / generated procedure
≠ live capability

candidate
→ tests / benchmarks / promotion / rollback
→ promoted capability directory
→ resident startup loading
```

Procedural learning should use this boundary rather than inventing a second executable-skill system.

### 2.4 The current LearningCandidate is not yet the target learning unit

`ZNLifeCore.LearningCandidate` is currently a compact record of a resolved impasse:

```text
task
+ resolution source
+ resolution summary
+ required capabilities
```

It can be useful context, but it is not yet causal procedural evidence. In particular it does not bind the full:

```text
Situation / evidence
→ concrete action
→ expected outcome
→ independently observed result
```

External-cognition success can also resolve an impasse and stage a candidate. Therefore the existing object must not be re-labelled as mature resident skill.

The L1 verified-experience record should sit below/alongside this older candidate concept and give future learning a stronger evidence unit.

## 3. Strongest reusable research ideas

### 3.1 Complementary Learning Systems: fast experience, slow competence

Sources:

- McClelland / complementary learning systems literature.
- DualNet / “Continual Learning, Fast and Slow”.
- CLS-ER / “Learning Fast, Learning Slow”.
- DeepMind `Progress & Compress`.

Relevant idea:

```text
fast learner
→ captures specific recent experience quickly

slow learner
→ integrates repeated experience gradually
→ extracts more stable structure
→ does not overwrite itself from every single event
```

This maps unusually well to ZN.

Recommended ZN interpretation:

```text
VerifiedExperience / episodic evidence       = fast side
PersistentNervousSystem traces/schema        = associative/consolidation side
Procedural tendency / mature capability      = slow competence side
```

The important thing to borrow is **different learning time-scales**, not biological labels or a literal reproduction of hippocampus/neocortex.

Decision: **ADOPT AS CORE DESIGN PRINCIPLE.**

Do not import DualNet/CLS-ER training code into the resident runtime merely to claim biological inspiration.

### 3.2 Experience Replay: bounded rehearsal instead of endless memory growth

Avalanche, Mammoth, CLS-ER, Dark Experience Replay and many continual-learning methods use replay/rehearsal to reduce forgetting.

ZN-relevant lesson:

```text
new verified experience
+ bounded representative old experience
→ consolidation / training update
```

This is preferable to either extreme:

```text
keep every event forever
```

or:

```text
train only on the newest event
```

For ZN, a replay store must preserve provenance and contradiction. It should not be a bag of model-generated text.

Initial replay policy should be simple and inspectable. Candidate mechanisms include:

- bounded reservoir sampling for broad lifetime representation;
- explicit retention of contradictions/failures;
- novelty/salience weighting;
- representative verified successes per skill/context family;
- bounded recent examples for adapting to current environment.

Decision: **ADOPT THE MECHANISM; IMPLEMENT RESIDENT-NATIVELY FOR L1.**

Do not add Avalanche/Mammoth to the installed runtime just to obtain a replay buffer.

### 3.3 DAgger: external model/human as teacher, local ZN as student

Source: `HumanCompatibleAI/imitation`, DAgger (Dataset Aggregation).

DAgger's useful pattern is:

```text
student policy encounters states it actually visits
→ expert gives the action for those states
→ observation/action examples are aggregated
→ student is retrained
→ repeat
```

This is one of the closest existing algorithmic patterns to ZN's model relationship.

ZN adaptation:

```text
ZN reaches a genuinely novel/uncertain Situation
→ external model or human may propose a candidate movement
→ ZN evaluates/executes through its own Body
→ independent reality verification labels the attempt
→ verified trajectory becomes resident-owned training evidence
→ local skill/policy improves
→ familiar states need fewer teacher calls
→ novel/prediction-error states can ask the teacher again
```

Critical differences from standard DAgger:

- model advice is not ground truth until reality verifies it;
- the teacher can be wrong;
- high-risk movement still requires normal authorization;
- ZN must retain causal evidence and contradictions;
- the student does not need to be one monolithic neural policy.

Decision: **ADOPT AS THE PRIMARY MODEL-AS-TEACHER LEARNING PATTERN.**

The `imitation` package is useful in an isolated research/training harness when ZN has a bounded Gymnasium-like skill environment. It should not become a resident dependency now.

### 3.4 Online learning + drift detection: River / ADWIN

Source: `online-ml/river`.

River is an actively maintained BSD-3-Clause online/incremental ML library with `predict_one` / `learn_one` style streaming updates plus drift detection, bandits, anomaly detection, classifiers and other online algorithms.

ADWIN is particularly relevant because it detects statistically significant change in a stream using an adaptive window.

Possible ZN use:

```text
mature skill attempts
→ stream of verified 1/0 outcomes or calibrated errors
→ drift detector
→ reliability distribution changes
→ inhibit / lower maturity / return to Thought
```

It can also support tiny resident-local predictors without retraining a large neural model.

Decision: **PROTOTYPE, DO NOT YET ADD AS CORE RUNTIME DEPENDENCY.**

Reason:

- River is a much better fit than a huge continual-learning framework for lightweight online adaptation;
- current releases include compiled/Rust-backed pieces, so packaging cost across ZN's Windows/macOS/Linux runtime must be measured before adoption;
- L1 does not require an ML dependency at all.

First experiment should compare:

1. a minimal resident-native reliability statistic;
2. River incremental predictor/drift detector in a dev-only harness;
3. whether ADWIN produces meaningfully better stale-skill detection on ZN benchmark streams.

Only measured value justifies adding a runtime dependency or source-extracting a smaller mechanism.

### 3.5 Continual-learning research frameworks: Avalanche and Mammoth

Sources:

- `ContinualAI/avalanche` — MIT, PyTorch, continual-learning strategies/benchmarks/evaluation.
- `aimagelab/mammoth` — MIT, research framework with 70+ methods and 20 datasets as of this survey.

Useful mechanisms to study/test include:

- Experience Replay;
- EWC;
- Synaptic Intelligence;
- GEM / A-GEM;
- DER / DER++;
- replay-buffer policies;
- continual-learning metrics and forgetting evaluation.

Decision: **USE AS RESEARCH/BASELINE QUARRIES, NOT ZN RUNTIME.**

They solve experimental neural continual-learning workflows. Importing either as a production control plane would add a large PyTorch research stack while still not give ZN a lived causal experience model.

When ZN eventually trains local neural skill models, an offline/dev benchmark harness may run candidate methods from these projects against the same ZN experience stream before choosing a much smaller production mechanism.

### 3.6 EWC and Progress & Compress: protect old competence while acquiring new competence

DeepMind's EWC work shows a concrete anti-forgetting mechanism: parameters important to old tasks are protected more strongly while learning new tasks.

`Progress & Compress` uses an active learner and a knowledge base, then consolidates new learning into the stable knowledge base while preserving previous capability.

Decision: **KEEP AS LATER NEURAL-SKILL OPTIONS.**

They become relevant only when ZN has actual trainable local neural skill/prediction models. L1/L2 should not introduce parameter-consolidation machinery before there are parameters worth consolidating.

The conceptual lesson—fast current learner followed by slow protected consolidation—is already useful now.

### 3.7 Voyager: reusable skill artifacts + feedback, but wrong ownership model for ZN

Source: `MineDojo/Voyager`, MIT.

Useful ideas:

- temporally extended reusable skills;
- compositional skill reuse;
- environment feedback and execution errors;
- explicit self-verification before considering a skill successful.

Rejected ownership pattern:

```text
GPT-4
→ curriculum / decomposition / skill generation / correction
→ executable skill library
```

For ZN the analogous path must be:

```text
ZN Situation / Thought / Investigation
→ optional model advice
→ resident-owned action
→ resident-owned verification
→ verified skill evidence
→ bounded promotion
```

Decision: **SOURCE/CONCEPT QUARRY ONLY; NEVER EMBED THE FULL VOYAGER LOOP.**

Also preserve ZN's existing rule that generated executable code cannot go directly into the promoted capability directory.

### 3.8 World models: DreamerV3 and related model-based control

Source: `danijar/dreamerv3`, MIT; Nature 2025 work on world models.

Core concept:

```text
experience
→ learn transition/prediction model
→ predict future latent state/reward under candidate actions
→ train/control using imagined trajectories
```

This is directly relevant to the long-term phrase “prediction-backed reflex”.

But desktop/computer-use actions are not currently a well-defined continuous control domain and ZN does not yet have enough verified interaction data to justify a Dreamer-class stack.

Decision: **LONG-TERM RESEARCH; NOT A CURRENT DEPENDENCY.**

Borrow the principle that a mature action tendency should predict its expected next state. Do not replace ZN's Situation/Thought/Will with a world-model RL agent.

### 3.9 Nested Learning: multiple update time-scales

Google Research's 2025 Nested Learning work treats learning systems as nested optimization processes and proposes a continuum memory system whose components update at different frequencies.

ZN-relevant interpretation:

```text
current WorkingState             very fast update
VerifiedExperience               fast episodic update
associative/schema structure     medium consolidation
procedural maturity              slower update
promoted executable capability   very slow / high evidence threshold
```

Decision: **USE AS A RESEARCH LENS, NOT AS A CLAIMED SOLUTION.**

Nested Learning / Hope is recent research oriented around model architectures and long-context memory. It does not by itself solve ZN's embodied procedural-learning problem.

## 4. Benchmarks/training environments worth using instead of inventing our own

### 4.1 BrowserGym

Source: `ServiceNow/BrowserGym`, Apache-2.0.

It provides a Gym-style browser task environment and integrations for MiniWoB, WebArena, VisualWebArena, WorkArena, AssistantBench, OpenApps and others.

Decision: **SELECTED FUTURE BROWSER BENCHMARK/TRAINING HARNESS.**

ZN should not ship BrowserGym as its consumer browser runtime. It is valuable in development to collect reproducible trajectories and measure whether browser skills actually improve.

### 4.2 OSWorld V2

Source: `xlang-ai/OSWorld-V2`, Apache-2.0.

The June 2026 V2 release provides 108 long-horizon real-world computer-use tasks and explicitly pins code/tasks/assets/websites/provider images for reproducible comparisons.

Decision: **SELECTED FUTURE DESKTOP COMPUTER-USE BENCHMARK.**

Two things are worth copying conceptually:

1. real long-horizon task diversity;
2. release-pinned evaluation inputs so “skill got better” is not confused with environment drift.

For ZN, future repeated-practice evaluation should additionally test retention and model independence, not only one-shot benchmark score.

## 5. Proposed ZN learning stack after this survey

No single imported framework becomes the stack.

The coherent target is:

```text
Body/Senses current reality
        ↓
Situation / Investigation
        ↓
concrete action + expected outcome
        ↓
independent verification
        ↓
VerifiedExperience                [fast learning]
        ↓
bounded replay / representative rehearsal
        ↓
PersistentNervousSystem + schema / tendency aggregation
        ↓
CandidateProcedure                [slow consolidation]
        ↓
reality-gated practice
        ↓
maturity / reliability / drift state
        ↓
resident-owned procedural capability
        ↓
fast familiar path
        ↓
result prediction + reality check
        ↓
reinforce OR inhibit/relearn
```

External cognition sits outside this ownership chain as a teacher/adviser:

```text
novel state / uncertainty / impasse
→ model or human suggestion
→ ZN action + verification
→ only verified experience changes competence
```

## 6. L1 implementation consequence: do not add an ML framework yet

The next true code target remains a resident-native `VerifiedExperience` store.

A first useful record should bind, in privacy-safe bounded form:

- experience ID;
- source event ID;
- source/teacher involvement (`native`, `external-cognition-assisted`, `human-assisted`, etc.);
- Situation/evidence fingerprint;
- domains / task or gap class;
- action signature and kind;
- expected-outcome summary;
- verification summary;
- verdict (`verified`, `contradicted`, `uncertain` when supported later);
- provenance/timestamps;
- enough safe metadata to group compatible experiences later.

Do not persist unnecessary raw private content, credentials, full command histories or model transcripts merely for learning.

The existing `native_action_failure_records` remains execution anti-replay state. Do not silently convert it into the new learning store. L1 may consume/distill its evidence, but ownership and retention semantics are different.

### 6.1 Initial bounded replay policy

For L1, start deterministic and inspectable rather than ML-heavy.

Suggested first policy:

```text
per skill/context family:
  retain recent contradictions
  retain representative verified successes
  retain limited novel/rare cases

global:
  fixed hard bound
  deterministic pruning
  provenance preserved
```

Reservoir sampling or more sophisticated replay selection can be added only after tests show the simple policy biases learning badly.

## 7. L2/L3 experiment path

After L1 has real data, compare candidate mechanisms instead of choosing by fashion.

### Experiment A — resident-native counts/bayesian-style reliability

Use repeated compatible experiences to form a candidate with:

```text
support_count
contradiction_count
recent_reliability
last_supported_at
last_contradicted_at
applicability fingerprint/features
```

This gives a transparent baseline.

### Experiment B — River online predictor / drift detector

Use the same stream to test whether an online model or ADWIN detects stale competence more reliably and quickly than the transparent baseline.

Keep this in dev/research dependencies until packaging and performance value are proven.

### Experiment C — DAgger-style local student

For a bounded domain with explicit observations/actions:

```text
teacher suggestion
→ ZN verified interaction
→ aggregate observation/action/outcome
→ train local student
→ let student act when confidence/context permits
→ query teacher at uncertainty/prediction error
```

Good first domains are synthetic/benchmark environments, not unrestricted desktop mutation.

### Experiment D — neural continual-learning methods only if forgetting is observed

If a local neural policy learns skill B and measurably loses skill A, benchmark replay/EWC/DER/etc. using Avalanche/Mammoth or isolated reproductions.

Do not solve catastrophic forgetting before ZN has a trainable model that actually exhibits it.

## 8. Growth metrics to import from continual-learning discipline

ZN needs more than task success rate.

Track at least:

- task-family success rate over time;
- external cognition calls per successful task;
- resident deliberation/action steps per successful familiar task;
- verification failure / recovery rate;
- retention after learning new task families;
- forgetting: performance drop on previously mature skills;
- forward transfer: whether old skill helps new related work;
- negative transfer / contradiction rate;
- time to recover after environment drift;
- performance after resident/runtime restart;
- performance after provider replacement;
- performance with all external models disabled;
- maturity calibration: does high skill confidence actually predict verified success?

This turns “ZN seems to be learning” into a testable claim.

## 9. Source classification / adoption ledger

```text
CLS / DualNet / CLS-ER          ADOPT DESIGN PRINCIPLE      fast episodes + slow consolidation
Progress & Compress             ADOPT DESIGN PRINCIPLE      active learner → stable knowledge
Experience Replay               ADOPT MECHANISM             bounded verified replay
DAgger / imitation              PROTOTYPE                    model/human as teacher, ZN as student
River / ADWIN                   PROTOTYPE                    online adaptation + stale-skill drift
Avalanche                       RESEARCH HARNESS             CL baselines/metrics, not runtime
Mammoth                         RESEARCH HARNESS             70+ CL methods, not runtime
EWC / DER / SI / GEM            LATER ALGORITHM OPTIONS      only after real neural forgetting
Voyager                         SOURCE QUARRY                skill reuse/feedback; reject LLM ownership
DreamerV3                       LATER RESEARCH               prediction/world-model skill domains
Nested Learning                 RESEARCH LENS                multi-timescale updating
BrowserGym                      FUTURE DEV BENCHMARK         browser learning/evaluation
OSWorld V2                      FUTURE DEV BENCHMARK         desktop learning/evaluation
```

## 10. Explicit non-adoptions

Do not:

- replace ZN Resident with Avalanche/Mammoth training loops;
- make Dreamer or another RL agent the owner of Self/Will/Thought;
- use Voyager's GPT-centered loop as ZN's control plane;
- treat embedding retrieval as procedural competence;
- let a teacher model write a permanent skill solely because its answer looked plausible;
- load generated executable skills directly into `PromotedCapabilityLoader`;
- add PyTorch/JAX/Rust-heavy runtime dependencies before a measured resident use requires them;
- train on unverified action success labels;
- make benchmark-specific policies the product architecture.

## 11. Licensing / provenance notes

Surveyed codebases with permissive licenses relevant to possible future reuse include:

- Avalanche — MIT;
- Mammoth — MIT;
- HumanCompatibleAI/imitation — MIT;
- River — BSD-3-Clause;
- Voyager — MIT;
- DreamerV3 repository — MIT;
- BrowserGym — Apache-2.0;
- OSWorld V2 — Apache-2.0.

Before copying any source into ZN, re-check the exact file/revision license and preserve required copyright/notice/provenance.

Papers/algorithms can guide an independent implementation; copying code is a separate provenance decision.

## 12. Immediate next decision

This survey does **not** change L1 into “install a continual-learning framework”. It makes L1 more concrete and reduces future invention.

Next real implementation target:

```text
verified Body / verification outcome
→ resident-native VerifiedExperience
→ bounded durable store
→ restart-safe retrieval
→ privacy-safe provenance
→ tests proving model text/action-return alone cannot create positive learning evidence
```

After real verified-experience data exists, run the first learning experiment:

```text
transparent resident-native aggregation
vs
River/ADWIN online adaptation/drift
```

Then use evidence to decide whether any external learning library belongs in the runtime.

The project should reuse mature learning science aggressively while preserving the one boundary that defines ZN:

> **external systems can teach, benchmark and provide algorithms; they do not become the resident subject.**
