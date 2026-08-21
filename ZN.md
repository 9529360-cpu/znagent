# ZN Agent

> Current development branch: `dev/zn-agent`
>
> This file is the primary entry point for ZN development. The existing `README.md` still documents the Hermes Agent ancestor and mature infrastructure that this repository inherited. ZN is not intended to be a white-label rename of Hermes; the long-term product and kernel architecture are being rebuilt around a different subject/model relationship while retaining useful mature infrastructure and the upstream MIT attribution.

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

Current development priority is the body, nervous system, perception, thought, will and closed life loop. Do not lead development by adding large policy, permission, sandbox or governance frameworks before the organism exists.

External models do **not** inherently own ZN's body permissions, but this should remain a capability decision made by ZN/runtime architecture rather than a prematurely hard-coded permanent prohibition.

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

Avoid turning each concern into an independent manager/agent that must coordinate through prompts.

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

The resident is now multi-pulse and resumable. One pulse advances one piece of cognition rather than running an arbitrary fixed number of reasoning rounds.

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

The embodied investigator routes host observation through the Body so investigation does not maintain a parallel hidden filesystem/process implementation.

A failed body movement returns new evidence to Investigation/Thought rather than being treated as terminal success or blindly retried forever.

## 5. Persistent nervous system

The primary lived-memory direction is `PersistentNervousSystem`, not a conventional conversation-memory layer.

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

### 5.2 Consolidation and forgetting

Neural memory now supports local consolidation without any model call.

The direction is:

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

A schema is still a neural trace in the same network, not a second memory database.

Schemas participate in resident-side recall, native deliberation, attention and reflection. They are not automatically serialized into an external model prompt.

Forgetting is intentionally conservative: weak, isolated, old and unreactivated details may fade; repeated or important lived structure should remain.

## 6. Experience → prediction → reality

Consolidated schemas have begun to act as native predictions.

When a current task activates a relevant schema, Investigation can form an explicit hypothesis such as:

```text
a consolidated lived pattern predicts relevant structure here
```

This is **not** treated as truth.

The next step remains reality checking through current body/environment evidence:

```text
past experience / schema
       ↓
     prediction
       ↓
 current body/world probe
       ↓
 evidence confirms, refines or contradicts prediction
```

The next major memory/cognition step is reconsolidation: reality feedback should be able to strengthen, weaken or restructure an existing schema instead of allowing old experience to become permanent bias.

## 7. Will and self-initiated work

`NativeWill` owns persistent `ResidentIntention` objects. An intention is not a model Goal and not a prompt queue.

A long-lived intention survives restarts and can outlive individual events used to advance it.

### 7.1 Explicit next steps

If an intention already has a concrete `next_task`, Thought may convert it into an internal event and run it through the same resident cognition/body loop.

### 7.2 Incubating a next step

When no concrete next step exists, ZN no longer has to wait forever.

Will now supports one durable incubating candidate rather than a growing plan list. The candidate keeps:

- candidate kind
- candidate step
- reason
- support trace IDs
- confidence
- repetition count
- maturity
- incubation count

The same candidate becoming relevant repeatedly strengthens the one slot instead of creating many micro-plans.

Current autonomous path:

```text
long-term intention
  ↓
related schema / lived traces repeatedly activate
  ↓
one candidate next step incubates
  ↓
repeated support raises maturity
  ↓
ZN commits the candidate when sufficiently mature
  ↓
internal `intention_probe` event
  ↓
Experience + Body observation
  ↓
local Outcome
  ↓
Outcome returns to the same Will
```

Initial self-initiated schema probes are deliberately local and use zero model calls. The resident does not spend an external-model token merely because an internal thought appeared.

A completed probe is recorded so the exact same schema does not immediately trigger an infinite repeat loop.

## 8. Native reflection and endogenous attention

When idle, ZN can perform low-frequency native association/reflection without creating a self-prompt or calling a model.

Will, affect and salient neural traces compete for attention.

Real user/internal events and open impasses remain higher priority than idle reflection.

Reflection can leave another neural trace, meaning internal processing can influence future thought while remaining resident-native.

This is intentionally not a general-purpose Planner.

## 9. World sense and visual sense

### World

ZN can hold durable world focuses and periodically observe outside information without requiring the user to repeat the prompt each time.

World sensing has its own rhythm instead of blocking the main heartbeat. Observations enter the nervous system first; they do not become model answers automatically.

### Vision

The Electron desktop currently provides a first low-level retina-like screen-change sensor. It detects lightweight screen-frame changes/fingerprints and sends a visual stimulus into the nervous system without automatically shipping screenshots to a multimodal model.

Current limitation: the retina still relies on Electron capture APIs. If the desktop process is closed, the resident can continue living but this visual sensor currently stops. A future persistent visual helper should let vision continue independently of the UI process.

## 10. Resident process and desktop lifecycle

The resident is no longer conceptually owned by the Electron window.

Current lifecycle direction:

```text
Resident service = life/process continuity
Electron = face/client
```

Electron connects to a local resident endpoint. If a resident is already running, the UI reconnects to it. Closing the desktop disconnects the face rather than sending a shutdown command.

Only an explicit Stop/shutdown should intentionally terminate the resident.

Lease recovery can detect a dead local PID and let a replacement resident reclaim the lease immediately instead of waiting for a fixed stale timeout.

A future production step is to finish OS-level service installation/update/recovery so the resident is fully independent of the desktop lifecycle on Windows/macOS/Linux.

## 11. External cognition boundary

The mature provider/router/worker infrastructure is still reused, but the embodied resident changed the meaning of a successful model call.

A model success no longer directly equals a completed ZN event.

Current path:

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

Neural traces and consolidated schemas can influence resident-side deliberation, but the external request is still built from the isolated unknown plus bounded native checks/evidence; it does not dump the resident's full associative life into the model context.

## 12. SelfModel and capability model

`SelfModel` distinguishes:

- external route competence (`route:*`)
- ZN retained knowledge (`knowledge:*`)
- ZN independently demonstrated ability (`self:*`)

A model solving a task may improve ZN's retained understanding after native integration, but does not automatically prove that ZN can execute the same work independently.

The domain model is intentionally hierarchical/coarse (`it`, `it/programming`, `it/data`, `it/security`, etc.) instead of becoming a catalog of one-off skills.

## 13. Important code map

Core resident files currently include:

```text
agent/kernel/
├── body.py
├── life.py
├── embodied_life.py
├── resident.py
├── embodied_resident.py
├── intentional_resident.py
├── nervous_system.py
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

Tests under `tests/agent/kernel/` are part of the architecture specification. In particular, restart/continuity tests are important: a feature is not considered resident-native if it disappears merely because the process restarts.

## 14. CI and development branch

Active development branch:

```text
dev/zn-agent
```

Do not merge or publish to `main` merely as part of normal development work.

The current CI baseline checks:

- locked/reproducible Python environment and kernel tests;
- Electron locked workspace and TypeScript typecheck;
- container/runtime smoke coverage in the workflow configuration.

The last verified functional code head before this documentation update was:

```text
aaccdd3691c38106b20a9143067546e9d66a5fcf
```

Its latest reported core statuses were:

```text
ZN Kernel / Python       success
Electron / TypeScript    success
Actions run              32471738863
```

Historical cancelled/failed runs from earlier incomplete CI environments do not need to be made green for cosmetic reasons. Evaluate the latest head in the current reproducible environment.

GitHub Actions time costs money. Use normal CI practice: do not rerun superseded historical commits just to clean the history, and avoid a stream of tiny commits that repeatedly starts expensive runs when changes can be grouped coherently.

## 15. Architecture traps to avoid

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
10. Do not spend the current phase primarily on hard policy/permission frameworks; finish the organism's principal closed loops first.

## 16. Next development target

The immediate next major step is **prediction error and neural reconsolidation**.

Current code can already do:

```text
experience
→ consolidation
→ schema
→ native prediction/hypothesis
→ body/world observation
```

The next loop should become:

```text
schema prediction
        ↓
current evidence
        ↓
comparison / prediction error
  ├─ supported      → strengthen/reinforce schema
  ├─ partly wrong   → refine/restructure schema
  └─ contradicted   → weaken schema and preserve the exception/new pattern
        ↓
future Thought changes
```

Important: do not implement this as naive text equality or string similarity. Schema metadata should increasingly represent shared features/channels/relations so current sensory/body evidence can produce a meaningful native prediction error.

After this stabilizes, likely follow-up targets are:

- richer schema restructuring/merging so schemas themselves do not proliferate forever;
- more native formation of useful next steps from Will + schema + current Situation;
- persistent visual sensing independent of Electron UI lifetime;
- richer native perception of the online world;
- eventual OS service lifecycle and upgrade/recovery integration;
- later, only when the organism is mature enough, stronger capability allocation/policy/safety layers.

## 17. New-conversation handoff

If a new ChatGPT conversation is used to continue development, start with the following instruction:

> Continue development of `9529360-cpu/znagent` on branch `dev/zn-agent`. Read `ZN.md` first and treat the repository as authoritative. Do not redesign this as a conventional LLM-centric agent. Check the latest branch head and CI before writing. Continue from the "Next development target" section unless newer repository code supersedes it. Make repository changes directly on `dev/zn-agent`; do not merge to `main` or create a PR unless explicitly requested. Keep normal CI cost in mind.

Then inspect the latest versions of at least:

```text
ZN.md
agent/kernel/nervous_system.py
agent/kernel/intentional_resident.py
agent/kernel/will.py
agent/kernel/embodied_investigation.py
agent/kernel/embodied_resident.py
tests/agent/kernel/test_nervous_system.py
tests/agent/kernel/test_intention_incubation.py
.github/workflows/zn-ci.yml
```

Repository state must override any stale conversation summary.

## 18. Provenance

This repository started from the Hermes Agent source and continues to reuse mature infrastructure where doing so saves engineering work. Preserve upstream license/attribution requirements. The architectural work described above is the ZN development direction, not a claim that the inherited Hermes code originally implemented these ZN concepts.
