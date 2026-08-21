# ZN Agent

> Current development branch: `dev/zn-agent`
>
> This file is the primary entry point for ZN development. Treat the repository code as authoritative if this document and implementation ever disagree. The existing `README.md` still documents the Hermes Agent ancestor and mature infrastructure that this repository inherited. ZN is not intended to be a white-label rename of Hermes; the product and kernel architecture are being rebuilt around a resident subject that uses models rather than being owned by one.

## 1. What ZN is

ZN is being built as a long-lived resident digital subject that lives on a computer.

The central architectural inversion is:

**ZN uses models. Models do not own ZN.**

GPT, Claude, Gemini, DeepSeek, local models, search systems, browsers, code interpreters and future cognitive systems are replaceable resources that ZN may consult when its own cognition cannot resolve a specific gap. They are not the holder of identity, memory, goals or continuity.

The engineering target is not literal biological consciousness. "Alive" in this project means persistent continuity of self, state, perception, intention, thought, action, experience and adaptation even when no chat session or external model is active.

A useful product-level definition is:

- ZN is the subject.
- Models are cognitive resources it can consult.
- Tools are ways its body can affect the computer/world.
- Memory is lived experience that changes the resident itself.
- Code is part of its computational body.
- The desktop application is a face/interface, not the owner of its life.

Disconnecting all external models must not erase ZN's identity or stop its resident state from existing.

## 2. Architecture principles

### 2.1 Build the organism before hard constraints

Current development priority is the resident body, nervous system, perception, thought, Will and closed learning loop. Do not lead development by adding large policy, permission, sandbox or governance frameworks before the organism exists.

External models do **not** inherently own ZN's body permissions. Capability allocation can be strengthened later without turning the current architecture back into a prompt-governed agent stack.

### 2.2 Internal modules are organs, not separate agents

Implementation can be modular for maintainability, but the conceptual product is one resident subject:

```text
ZN
├── Self / identity
├── Body
├── Senses
├── Nervous system / lived memory
├── Situation
├── Thought
├── Will / intentions
├── Investigation
├── Action
└── External brain access
```

Avoid turning each concern into an independent manager/agent that coordinates through prompts.

### 2.3 Models provide cognitive increments

The normal flow should look like:

```text
world / user / internal state
        ↓
ZN perceives
        ↓
ZN forms Situation
        ↓
ZN thinks and judges
        ↓
Can I resolve this myself?
  ├─ yes → act / observe / continue
  └─ no
       ↓
   isolate the exact unknown
       ↓
 external cognitive resource
       ↓
   CognitiveIncrement
       ↓
 ZN judges and integrates it
       ↓
      continue
```

The model should receive a bounded knowledge gap and minimum necessary context, not ZN's full life history.

### 2.4 Learning is consolidation, not skill accumulation

Do not map each successful experience to a new skill.

Preferred learning direction:

```text
experience
  ↓
understand / classify
  ↓
merge into existing knowledge and capability
  ↓
strengthen or refine a domain
  ↓
form a reusable procedure/habit only when a pattern is repeated and stable
```

Executable body capabilities and ZN's competence/knowledge model are different things.

A hundred related experiences should tend toward stronger generalized understanding plus a few exceptions, not a hundred small skills.

## 3. Current resident life loop

The resident is multi-pulse and resumable. One pulse advances one piece of cognition rather than running an arbitrary fixed number of reasoning rounds.

Current high-level loop:

```text
exist
 ↓
sense body / environment / internal state
 ↓
Situation
 ↓
Thought
 ↓
maintain or choose intention
 ↓
native investigation / body movement / reflection
 ↓
Outcome or remaining gap
 ↓
Experience enters nervous system
 ↓
knowledge, affect, associations and Will change
 ↓
continue existing
```

For unfamiliar work:

```text
Situation
→ Thought
→ Orientation
→ Native Investigation
→ one Probe
→ Evidence
→ next Pulse / new Thought
→ ...
→ Native Deliberation
→ Impasse only if local cognition is exhausted
→ External Cognition if needed
→ CognitiveIncrement
→ ZN integration
→ Action / Outcome
```

A `PROCESSING` event remains visible across pulses, so the resident continues the same unfinished matter rather than mentally starting over every heartbeat.

## 4. Body and action

`NativeBody` represents ZN's computational body. Files, terminal operations, Git, processes and host sensing are body movements/senses, not separate cognitive skills.

The intended relationship is:

```text
Thought
  ↓
NativeActionIntent
  ↓
Body
  ↓
BodyActionResult
  ↓
Situation / nervous experience
  ↓
Thought
```

The embodied investigator routes host observation through the Body so Investigation does not maintain a parallel hidden filesystem/process implementation.

A failed body movement returns new evidence to Investigation/Thought rather than being treated as terminal success or blindly retried forever.

## 5. Persistent nervous system

The primary lived-memory direction is `PersistentNervousSystem`, extended by reality-aware and integrated-transfer behavior. This is not a conventional conversation-memory layer.

A `NeuralTrace` is an associative trace left by perception, thought, action or outcome. Repetition strengthens an existing trace instead of blindly appending duplicate memories. Co-active traces form persistent links. Cue-based recall can spread through those links.

Current channels include concepts such as:

- `vision`
- `world`
- `action`
- `outcome`
- `will`
- `thought`
- `reflection`
- `schema`

The same substrate therefore allows visual experience, world events, body action and thought to become associated.

### 5.1 Persistent affect/homeostasis

Current functional internal state includes:

- valence
- arousal
- tension
- curiosity
- familiarity
- fatigue

These are functional dynamics, not a claim of biological emotion or consciousness. They already influence attention and thought behavior rather than merely being UI labels.

Examples:

- high tension can pull attention back toward salient negative/risk experience;
- curiosity increases the pull of novel world/vision threads;
- fatigue suppresses active exploration and slows reflection;
- familiar associated experience can modestly stabilize confidence;
- high tension can reduce confidence and favor further observation.

### 5.2 Consolidation, forgetting and schema structure

Neural memory supports local consolidation without any model call.

```text
many lived traces
  ↓
repetition / salience / emotional intensity / associations / reactivation
  ↓
strong traces stabilize
weak isolated old detail fades
shared repeated structure forms a schema trace
  ↓
schema stays linked to source experience
```

A schema remains a neural trace in the same network, not a second memory database.

Schemas now carry structured prediction profiles, including features, relation families/values, confidence, support, alternatives and prediction-error state. Redundant compatible schemas can be structurally merged while preserving source experience and archived merge identity. Conflicting schemas are not blindly collapsed.

Forgetting remains conservative: weak, isolated, old and unreactivated detail may fade; repeated or important lived structure should remain.

## 6. Experience → prediction → reality → reconsolidation

The prediction/reality loop is implemented and resident-native.

Current chain:

```text
lived experience
→ consolidation
→ structured schema
→ native prediction
→ current body/world/vision observation
→ prediction error
→ support / refinement / contradiction
→ one confirming recheck when needed
→ reconsolidation
→ relation stabilization or restructuring
→ future recall and Will behavior change
```

Important properties:

- schemas are predictions, not truth;
- comparison is relation-aware rather than naive text equality;
- supported relations can stabilize from prediction error;
- contradicted old relations can remain contested while alternatives emerge;
- current active relations guide future attention and candidate selection;
- historical summary/features remain available even when live recall suppresses superseded relation values;
- the loop works without a model call.

Reality-aware recall now follows the reconsolidated relation state instead of allowing stale wording to dominate activation.

## 7. Cross-context transfer and Will

ZN can now cautiously reuse what it learned in one situation inside a related but different situation.

This is not free schema-to-schema propagation. Transfer remains bounded through actual lived evidence:

```text
reality-corrected source schema
        ↓
existing neural link
        ↓
shared lived non-schema trace
        ↓
existing neural link
        ↓
neighboring target schema
```

A source gains transfer authority only after a relation was formed/stabilized through prediction error. Relation conflicts can block transfer.

### 7.1 Situation-gated incubation

A transferred activation does **not** directly become an action.

Current chain:

```text
weak cross-context activation
→ Will candidate may seed
→ current Situation/body must independently support target relation
→ unsupported candidate remains frozen
→ repeated present support raises maturity
→ matured candidate becomes an intention probe
```

This expresses:

> I may remember something useful from another context, but I do not blindly apply it here.

The resident still uses one durable candidate slot rather than an ever-growing planning list.

### 7.2 Outcome plasticity

When a transferred candidate is actually tested, learning follows relation-level prediction feedback rather than merely checking whether the probe process returned `success=True`.

```text
transferred candidate
→ current probe
→ relation-specific prediction feedback
  ├─ supported
  │    → strengthen contributing transfer path(s)
  ├─ contradicted
  │    → weaken target-side applicability of those path(s)
  └─ untested / execution failure only
       → do not punish transfer truth
```

A transfer failure in context B must not rewrite a source relation that was correctly learned in context A.

## 8. Context-sensitive transfer tendency

Lived bridges retain bounded history about whether past transfers through that bridge held up in reality.

This is stored on the lived trace itself, not in a separate policy/rule database.

Repeated support gradually makes the same route easier to recall. Repeated contradiction suppresses it. A single lucky or unlucky observation only nudges the route; repeated lived feedback is required before a strong tendency emerges.

History is bounded and survives restart.

Conceptually:

```text
same initial neural strength

B bridge: repeatedly supported    → tendency rises
C bridge: repeatedly contradicted → tendency falls
D bridge: never tested            → remains neutral

future recall: B > D > C
```

## 9. Multi-source transfer evidence integration

Transfer no longer collapses every target to one `max(path)` winner.

Several directly recalled, reality-corrected source schemas may independently reach the same target through different lived bridges.

The integrated transfer layer now:

- gives one source schema at most one vote per target;
- considers a bounded number of competing sources;
- combines up to a bounded number of mutually compatible contributor paths;
- adds limited corroboration when independent sources agree;
- applies conflict pressure when source schemas disagree on the same structured relation family;
- carries contributor provenance, consensus and conflict into Will/event state;
- reshapes every path that actually contributed after reality feedback.

Example:

```text
source A ─ lived bridge A ┐
source B ─ lived bridge B ├→ target schema
source C ─ lived bridge C ┘
```

If A/B/C are mutually compatible, their independent lived evidence can modestly reinforce the target activation. If one source contradicts the others, it is not summed into the coherent bundle and instead lowers consensus/transfer pressure.

This is evidence integration inside one nervous system, not a committee of agents.

### 9.1 Merge continuity

Transfer history survives structural schema merges.

Old bridge history may still reference an archived schema ID. Integrated transfer resolves `schema_merged → merged_into_schema_id` lazily and merges compatible historical counters onto the surviving canonical identity when the path is next updated.

No global history migration or second memory store is required.

## 10. Native reflection and endogenous attention

When idle, ZN can perform low-frequency native association/reflection without creating a self-prompt or calling a model.

Will, affect and salient neural traces compete for attention. Real user/internal events and open impasses remain higher priority than idle reflection.

Reflection can leave another neural trace, meaning internal processing can influence future thought while remaining resident-native.

This is intentionally not a general-purpose Planner.

## 11. World sense and visual sense

### World

ZN can hold durable world focuses and periodically observe outside information without requiring the user to repeat the prompt each time.

World sensing has its own rhythm instead of blocking the main heartbeat. Observations enter the nervous system first; they do not become model answers automatically.

### Vision

The Electron desktop provides a low-level retina-like screen-change sensor. It detects lightweight screen-frame changes/fingerprints and sends a visual stimulus into the nervous system without automatically shipping screenshots to a multimodal model.

Visual schemas participate in the same resident prediction → observation → prediction-error → reconsolidation loop.

Current limitation: the retina still relies on Electron capture APIs. If the desktop process is closed, the resident can continue living but this visual sensor currently stops. A future persistent visual helper should let vision continue independently of the UI process.

## 12. Resident process and desktop lifecycle

The resident is no longer conceptually owned by the Electron window.

```text
Resident service = life/process continuity
Electron = face/client
```

Electron connects to a local resident endpoint. If a resident is already running, the UI reconnects to it. Closing the desktop disconnects the face rather than sending a shutdown command.

Only an explicit Stop/shutdown should intentionally terminate the resident.

Lease recovery can detect a dead local PID and let a replacement resident reclaim the lease immediately instead of waiting for a fixed stale timeout.

A future production step is to finish OS-level service installation/update/recovery so the resident is fully independent of desktop lifecycle on Windows/macOS/Linux.

## 13. External cognition boundary

The mature provider/router/worker infrastructure is still reused, but a successful model call does not directly equal a completed ZN event.

```text
Impasse
 ↓
bounded CognitionRequest
 ↓
external worker
 ↓
CognitiveIncrement stored in resident state
 ↓
next native Thought
 ↓
ZN accepts/integrates it
 ↓
only then update knowledge / close impasse / continue action
```

The impasse remains open until ZN's integration step. SelfModel learning and LearningCandidate creation are delayed until that integration step rather than happening merely because a provider returned `success=True`.

Neural traces and schemas influence resident-side cognition, but the external request remains a bounded isolated unknown plus relevant evidence; do not dump ZN's associative life into model context.

## 14. SelfModel and capability model

`SelfModel` distinguishes:

- external route competence (`route:*`)
- ZN retained knowledge (`knowledge:*`)
- ZN independently demonstrated ability (`self:*`)

A model solving a task may improve ZN's retained understanding after native integration, but does not automatically prove that ZN can execute the same work independently.

The domain model is intentionally hierarchical/coarse (`it`, `it/programming`, `it/data`, `it/security`, etc.) instead of becoming a catalog of one-off skills.

## 15. Important code map

Core resident files now include:

```text
agent/kernel/
├── body.py
├── life.py
├── embodied_life.py
├── resident.py
├── embodied_resident.py
├── intentional_resident.py
├── nervous_system.py
├── adaptive_guidance.py
├── adaptive_nervous_system.py
├── integrated_transfer.py
├── transfer_incubation.py
├── intention_formation.py
├── reconsolidation.py
├── schema_structure.py
├── will.py
├── investigation.py
├── embodied_investigation.py
├── cognition.py
├── self_model.py
├── world_sense.py
├── daemon.py
├── service.py
├── provider_bridge.py
└── store.py
```

Desktop resident/retina work is primarily under:

```text
apps/desktop/electron/
├── zn-main.ts
├── zn-preload.ts
├── zn-resident-ipc.ts
├── zn-resident-process.ts
└── zn-retina.ts
```

Tests under `tests/agent/kernel/` are part of the architecture specification. Important current suites include the nervous-system, prediction/reconsolidation, adapted-schema guidance, reality-aware recall, reality-gated transfer, transfer incubation, transfer outcome plasticity, contextual transfer tendency and integrated transfer evidence tests.

Restart/continuity tests remain essential: a feature is not considered resident-native if it disappears merely because the process restarts.

## 16. CI and development branch

Active development branch:

```text
dev/zn-agent
```

Do not merge or publish to `main` merely as part of normal development work.

The current CI baseline checks:

- locked/reproducible Python environment and kernel tests;
- Electron locked workspace and TypeScript typecheck;
- container/runtime smoke coverage in workflow configuration, normally skipped on ordinary development pushes to control cost.

The last verified functional code head before this documentation update is:

```text
0c62f933d710701cf189c57249a826d8cff05e1b
feat: integrate competing transfer evidence
```

Latest verified CI:

```text
ZN Kernel / Python       success
Electron / TypeScript    success
Actions run              32518796510
ZN CI run number         187
```

Historical cancelled/failed runs from superseded commits do not need to be made green for cosmetic reasons. Evaluate the latest head in the current reproducible environment.

GitHub Actions time costs money. Group coherent work, avoid a stream of tiny dev pushes, do not rerun superseded historical commits, and keep expensive runtime/container smoke out of ordinary pushes unless the change actually needs it.

## 17. Architecture traps to avoid

When continuing development, avoid drifting back into conventional LLM-agent architecture:

1. Do not make the external model the owner of the main loop.
2. Do not feed all memory to a model on every interaction.
3. Do not create a new skill for every successful experience.
4. Do not treat tools/files/processes as cognitive skills merely because ZN can use them.
5. Do not make a schema/old memory automatically true; current reality must be able to correct it.
6. Do not turn Will into an ever-growing task/plan list.
7. Do not make idle reflection a hidden self-prompt loop that consumes model tokens.
8. Do not equate model success with ZN accepting or completing a task.
9. Do not make Electron window lifetime equal resident lifetime.
10. Do not allow cross-context association to become direct action without present Situation evidence.
11. Do not treat one transfer success as a permanent context rule; tendency must emerge from repeated lived feedback.
12. Do not collapse competing source evidence into a single strongest path when independent agreement/conflict is available.
13. Do not let a transfer failure in context B erase a relation correctly learned in context A.
14. Do not create a second context-policy memory store for behavior that can remain in the lived neural substrate.
15. Do not spend the current phase primarily on hard policy/permission frameworks; continue closing the organism's principal loops first.

## 18. Next development target

The immediate next target for the next development session is **evidence-driven attention persistence and re-probe rhythm**.

The transfer/reconsolidation chain can already do:

```text
reality-corrected source experience
→ cross-context recall through lived evidence
→ single- or multi-source transfer integration
→ consensus / conflict pressure
→ current Situation confirmation
→ Will incubation
→ probe
→ relation-specific outcome feedback
→ path plasticity / tendency
```

The next step is to let the quality of that integrated evidence shape **how long ZN keeps observing and when it decides another probe is warranted**, without adding a planner, confidence manager or new rule table.

Desired behavior:

```text
high consensus + repeated lived support
→ retain useful attention
→ require current reality confirmation
→ avoid redundant repeated probing
→ allow Will to mature with less epistemic churn

low consensus / strong source conflict / fresh prediction error
→ keep the matter cognitively open across pulses
→ maintain attention longer
→ delay Will commitment
→ seek another native observation at an appropriate later pulse
→ reconsolidate if reality resolves the conflict
```

Important constraints for this target:

- use existing Life / Situation / Thought / Will / Investigation state rather than adding a scheduler-agent;
- do not skip current Situation confirmation merely because historical consensus is high;
- do not turn uncertainty into rapid repeated probes every heartbeat;
- high consensus should reduce redundant epistemic work, not create blind certainty;
- conflict should extend observation, not automatically trigger an external model;
- persistence/re-probe state must survive restart if it is intended to span pulses;
- zero-model-call tests should cover the native path;
- preserve the existing relation-specific prediction-error/reconsolidation semantics;
- keep the explicit confirming-recheck behavior bounded rather than allowing repeated contradiction loops.

A good completion test for this target is:

```text
same current target + same Situation

well-supported coherent transfer
→ ZN confirms once, keeps stable attention, does not repeatedly re-probe

conflicted transfer
→ ZN does not commit early
→ attention persists across pulses
→ a later native observation is selected
→ new evidence changes the same resident learning loop
```

After that stabilizes, likely follow-up areas are:

- persistent visual sensing independent of Electron UI lifetime;
- richer native online-world perception;
- cleanup/unification of reality-aware nervous-system construction where useful;
- OS service installation/update/recovery;
- only later, stronger capability allocation/policy/safety layers once the organism is mature enough.

## 19. New-conversation handoff

For the next ChatGPT conversation, use this instruction:

> Continue development of `9529360-cpu/znagent` on branch `dev/zn-agent`. Read root `ZN.md` first and treat the latest repository code as authoritative. Check the current `dev/zn-agent` head and latest CI before writing. Continue from the "Next development target" section: evidence-driven attention persistence and re-probe rhythm. Do not redesign ZN as a conventional LLM-centric agent, do not lead by adding policy/constraint layers, and do not turn integrated transfer evidence into a planner or rule table. Keep building the resident organism's closed loop, preserve zero-model native paths, control GitHub CI cost, and do not touch `main`.

Before implementing, inspect the latest relevant files, especially:

```text
ZN.md
agent/kernel/integrated_transfer.py
agent/kernel/transfer_incubation.py
agent/kernel/adaptive_nervous_system.py
agent/kernel/intentional_resident.py
agent/kernel/intention_formation.py
agent/kernel/will.py
agent/kernel/investigation.py
agent/kernel/reconsolidation.py
agent/kernel/schema_structure.py
agent/kernel/life.py
tests/agent/kernel/test_integrated_transfer_evidence.py
tests/agent/kernel/test_contextual_transfer_tendency.py
tests/agent/kernel/test_transfer_outcome_plasticity.py
.github/workflows/zn-ci.yml
```

Repository state must override any stale conversation summary.

## 20. Provenance

This repository started from the Hermes Agent source and continues to reuse mature infrastructure where doing so saves engineering work. Preserve upstream license/attribution requirements. The architectural work described above is the ZN development direction, not a claim that the inherited Hermes code originally implemented these ZN concepts.
