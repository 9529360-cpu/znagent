# ZN Agent

> Current active development branch: `dev/zn-agent`
>
> This document is the primary architecture/development handoff for ZN. Repository code is authoritative whenever implementation and this document disagree.
>
> ZN began from uploaded Hermes Agent source because mature engineering should be reused where it avoids pointless reinvention. Hermes is a reference/upstream source, not the owner of ZN's product, runtime, release channel, bootstrap path, update channel, identity, memory or lifecycle.

## 1. Core product direction

ZN is being built as a long-lived resident digital subject that lives on a computer.

The central architectural inversion is:

**ZN uses models. Models do not own ZN.**

GPT, Claude, Gemini, DeepSeek, local models, search systems, browsers, code interpreters and future cognitive systems are replaceable cognitive resources. They are not the holder of ZN's identity, memory, intentions or continuity.

The engineering target is not literal biological consciousness. "Alive" means persistent continuity of self, state, perception, intention, thought, action, experience and adaptation even when no chat session or external model is active.

Product-level definition:

- ZN is the subject.
- Models are cognitive resources ZN may consult.
- Tools are ways ZN's body can affect the computer/world.
- Memory is lived experience that changes the resident itself.
- Code is part of ZN's computational body.
- Electron/Desktop is a face and control surface, not the owner of ZN's life.
- ZN's repository/release infrastructure owns ZN distribution and updates.

Disconnecting all external models must not erase ZN's identity or stop its resident state from existing.

## 2. Hermes boundary: reference, not dependency

Hermes source is a mature engineering reference and inherited implementation base. It must not remain an upstream control plane for ZN.

The intended reuse rule is:

```text
mature solved engineering problem
→ inspect inherited/reference implementation
→ keep/adapt the useful mechanism if it genuinely saves work
→ move ownership into ZN
→ maintain and publish from ZN
```

Not:

```text
Hermes has an update/bootstrap/runtime channel
→ point ZN at it forever
→ Hermes updates therefore become ZN updates
```

Concrete rules:

- ZN releases come from `9529360-cpu/znagent`.
- ZN bootstrap/install artifacts must come from ZN-controlled repository refs or ZN-controlled release artifacts.
- A ZN commit SHA must never be resolved against the Hermes repository.
- ZN desktop/runtime updates track ZN releases, not Hermes releases.
- New product-facing IPC/RPC/network/update surfaces should use ZN ownership/namespaces.
- Inherited Hermes internals may remain temporarily during migration, but they are implementation debt rather than product authority.
- Provider integrations, Telegram/WhatsApp paths and mature desktop infrastructure may be retained where they are useful, but only as code ZN chooses to maintain.
- Unused inherited Hermes product code should be removed gradually rather than preserved merely because it existed upstream.
- Originality does not require rewriting solved low-level infrastructure for cosmetic reasons.

### 2.1 Intended upstream-reference branch

The desired repository topology is:

```text
main              = ZN formal release/product branch
dev/zn-agent      = active ZN development branch
upstream/hermes   = mirror/reference of NousResearch/hermes-agent
```

`upstream/hermes` is for diffing and borrowing useful mature ideas. It may be periodically force-synchronized from Hermes upstream, but must **never auto-merge into ZN**.

At the time of this documentation sync, that topology is not fully enacted yet: `main` still points at the original Hermes-derived snapshot and `dev/zn-agent` is 222 commits ahead. Do not confuse desired branch ownership with current branch state.

## 3. Architecture principles

### 3.1 Build the organism before hard constraints

Current development priority remains the resident body, nervous system, perception, thought, Will and closed learning loop. Do not lead development by adding large policy, permission, sandbox or governance frameworks before the organism exists.

External models do not inherently own ZN's body permissions. Capability allocation can be strengthened later without reverting to a prompt-governed agent stack.

### 3.2 Internal modules are organs, not separate agents

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

Do not turn each concern into a separate prompt-driven manager/agent.

### 3.3 Models provide cognitive increments

Normal unfamiliar-task flow:

```text
world / user / internal state
        ↓
ZN perceives
        ↓
Situation
        ↓
Thought / native judgment
        ↓
Can ZN resolve the gap itself?
  ├─ yes → observe / act / continue
  └─ no
       ↓
 isolate the exact unknown
       ↓
 external cognitive resource
       ↓
 CognitiveIncrement
       ↓
 ZN judges/integrates it
       ↓
 continue
```

External models should receive a bounded knowledge gap plus minimum useful context, not ZN's entire associative life.

### 3.4 Learning is consolidation, not skill accumulation

Do not map each successful experience to a new skill.

```text
experience
  ↓
understand / classify
  ↓
merge into existing knowledge/capability
  ↓
strengthen/refine a domain
  ↓
form a reusable procedure/habit only when repeated and stable
```

Executable body capabilities and ZN's competence/knowledge model are different things.

## 4. Current resident life loop

The resident is multi-pulse and resumable. One pulse advances one piece of cognition rather than running an arbitrary fixed number of LLM reasoning rounds.

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

A `PROCESSING` event remains visible across pulses so the resident continues the same unfinished matter instead of mentally starting over every heartbeat.

The production constructor `build_resident_runtime_from_existing_stack()` currently returns `WorldAwareTransferResidentRuntime`. World sensing, transfer, situated intention formation and reconsolidation are therefore wired into the actual resident runtime rather than existing as detached experiments.

## 5. Body and action

`NativeBody` represents ZN's computational body. Files, terminal operations, Git, processes and host sensing are body movements/senses, not separate cognitive skills.

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

The embodied investigator routes host observation through Body. A failed movement becomes new evidence and returns to Investigation/Thought rather than being treated as success or blindly retried.

## 6. Persistent nervous system

`PersistentNervousSystem` is the primary lived-memory substrate, extended by reality-aware adaptation and integrated transfer. It is not a conversation transcript store.

A `NeuralTrace` is an associative trace left by perception, thought, action or outcome. Repetition strengthens existing traces; co-active traces form persistent links; recall can spread through those links.

Current channels include concepts such as:

- `vision`
- `world`
- `action`
- `outcome`
- `will`
- `thought`
- `reflection`
- `schema`

### 6.1 Persistent affect/homeostasis

Functional state includes:

- valence
- arousal
- tension
- curiosity
- familiarity
- fatigue

These affect attention and resident behavior. They are functional dynamics, not a claim of biological emotion or consciousness.

### 6.2 Consolidation and schema structure

```text
many lived traces
  ↓
repetition / salience / affect / association / reactivation
  ↓
strong traces stabilize
weak isolated old detail may fade
shared repeated structure forms schema traces
```

A schema remains a neural trace in the same network. Schemas carry structured prediction profiles including relation family/value, confidence, support, alternatives and prediction-error state.

Compatible redundant schemas can structurally merge while preserving source experience and archived merge identity. Conflicting schemas are not blindly collapsed.

## 7. Prediction → reality → reconsolidation

The resident-native prediction/reality loop is implemented:

```text
lived experience
→ consolidation
→ structured schema
→ native prediction
→ current body/world/vision observation
→ prediction feedback
→ support / refinement / contradiction
→ one bounded confirming recheck when needed
→ reconsolidation
→ relation stabilization or restructuring
→ future recall and Will behavior change
```

Important properties:

- schema is prediction, not truth;
- comparison is relation-aware rather than naive text equality;
- reality can stabilize or restructure relations;
- stale superseded wording should not dominate live recall;
- the whole path can run with zero model calls.

## 8. Cross-context transfer and Will

ZN can cautiously reuse learned structure across related but different situations.

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

Transfer authority requires lived/reality-corrected support. Conflicts can block or weaken transfer.

### 8.1 Situation-gated incubation

Transferred activation never directly becomes action:

```text
cross-context activation
→ Will candidate may seed
→ current Situation/body independently tests applicability
→ unsupported candidate remains frozen
→ repeated present support raises maturity
→ matured candidate becomes an intention probe
```

Will retains one durable candidate slot rather than an ever-growing task/plan list.

### 8.2 Outcome plasticity

Transfer learning uses relation-specific prediction feedback:

```text
supported relation
→ strengthen contributing transfer path(s)

contradicted relation
→ weaken target-side applicability of contributing path(s)

probe execution failure / relation untested
→ do not punish transfer truth
```

Failure in context B must not erase a source relation correctly learned in context A.

## 9. Context-sensitive transfer tendency

Lived bridges keep bounded history of whether prior transfers held up in reality. This history stays in the neural substrate rather than a second policy/rule database.

Repeated support gradually strengthens route tendency; repeated contradiction suppresses it; a single observation only nudges it. History survives restart.

## 10. Multi-source transfer evidence integration

Transfer no longer chooses only one `max(path)` winner.

The integrated layer:

- gives one source schema at most one vote per target;
- considers a bounded number of competing sources;
- combines mutually compatible independent contributor paths;
- adds limited corroboration when independent evidence agrees;
- applies conflict pressure when source schemas disagree on a structured relation family;
- carries contributor provenance, consensus and conflict into Will/event state;
- reshapes all paths that actually contributed after reality feedback.

Transfer history survives structural schema merges by lazily resolving archived merged identities to the surviving canonical schema.

## 11. Evidence-driven attention persistence and re-probe rhythm

The old `ZN.md` listed this as the next target. It is already implemented and must not be reimplemented from the stale document.

Integrated transfer evidence now shapes how long a matter remains cognitively open and when another native observation is warranted.

```text
high consensus + repeated lived support
→ still require current reality confirmation
→ mature with less unnecessary review churn
→ avoid probing every heartbeat

low consensus / source conflict / fresh prediction error
→ keep matter open across pulses
→ delay Will commitment
→ wait for bounded later review/re-probe rhythm
→ another native observation can resolve it
→ feed result through reconsolidation
```

State survives restart when it spans pulses and is stored in existing resident/Will state rather than a new scheduler-agent.

World and visual sensing also have adaptive native sampling rhythms:

- stable repeated observations back off;
- current Thought can pull a relevant sense closer;
- relevant conflict/prediction error can tighten the corresponding sense;
- unrelated conflict does not hot-sample every sensor.

Zero-model tests cover these paths.

## 12. Native reflection and endogenous attention

When idle, ZN can perform low-frequency native association/reflection without creating a self-prompt or model loop.

Will, affect and salient neural traces compete for attention. Real user/internal events and open impasses remain higher priority.

Reflection itself can leave a neural trace and affect future cognition.

## 13. World and visual sense

### World

ZN can hold durable world focuses and periodically observe outside information without repeated user prompting. World sensing runs on its own rhythm so slow external observation does not block the resident heartbeat.

`AdaptiveWorldSense` persists rhythm per durable focus. Stable observations back off; relevant prediction error/conflict can bring a focus closer.

### Vision

The old statement that visual sensing stops when Electron closes is obsolete.

`ResidentSocketService` owns `NativeVisualSense`, attaches it to the resident as `resident.vision`, and runs a dedicated visual sampling thread in the long-lived resident service.

The visual organ retains compact structure rather than raw screenshots:

- frame fingerprint;
- coarse region signatures;
- dimensions;
- aggregate luminance;
- change scale/changed regions.

Raw frame pixels are discarded inside capture. Headless/permission/capture failures must not kill resident life.

## 14. Resident process, UI lifecycle and OS autostart

```text
Resident service = life/process continuity
Electron = face/client
```

Electron reconnects to an existing local resident endpoint or launches the detached service if none is reachable. Closing the desktop disconnects the client; explicit Stop/shutdown terminates the resident.

Dead same-host lease recovery can reclaim a crashed resident without waiting for the full stale timeout.

OS login autostart support now exists in `agent/kernel/resident_autostart.py`:

- Linux: user `systemd` service;
- macOS: `LaunchAgent`;
- Windows: current-user Scheduled Task.

The startup entry pins the Python executable and ZN home used to install it. Electron refreshes the entry once per desktop version after the resident is reachable.

This solves much of the UI-lifetime problem. It does **not** yet guarantee a clean machine has a self-contained ZN-owned Python/runtime substrate.

## 15. External cognition boundary

A successful model call does not directly equal a completed ZN event.

```text
Impasse
 ↓
bounded CognitionRequest
 ↓
external worker/model
 ↓
CognitiveIncrement stored in resident state
 ↓
next native Thought
 ↓
ZN accepts/integrates it
 ↓
knowledge/action/outcome continues
```

SelfModel learning and LearningCandidate creation occur after native integration, not merely because a provider returned success.

## 16. SelfModel and capability model

`SelfModel` distinguishes:

- external route competence (`route:*`)
- retained ZN knowledge (`knowledge:*`)
- independently demonstrated ZN ability (`self:*`)

A model solving a task can improve retained understanding after native integration without automatically proving ZN can execute it independently.

## 17. Desktop product state

The desktop now has a ZN-facing product layer over still-reused mature shell infrastructure:

- `electron/zn-main.ts` registers ZN resident/update ownership;
- `electron/zn-preload.ts` exposes `window.znDesktop`;
- `src/app/zn-workbench.tsx` makes the default surface a ZN workbench rather than the inherited IDE-heavy layout;
- resident status appears in the status bar;
- ZN release-update status appears in the status bar;
- `electron-builder.zn.yml` creates ZN-branded artifacts.

There is still inherited Hermes branding/compatibility code elsewhere in the desktop tree. Product-facing Hermes identity should continue to be removed, while useful mature infrastructure may stay internally when deliberately adopted by ZN.

## 18. Release/update state

`.github/workflows/zn-release.yml` currently packages Windows/macOS/Linux artifacts for `zn-v*` tags and can publish a GitHub Release.

The current updater checks the latest release of **`9529360-cpu/znagent`**, so the desktop update source itself is now ZN-owned.

Current implemented flow:

```text
ZN GitHub latest stable release
→ platform/arch manifest
→ choose installable asset
→ download on user apply
→ verify exact size + SHA-256
→ platform-specific replacement handoff
→ quit/restart desktop
```

Important terminology: the current manifest is **hash-verified**, not independently cryptographically signed. It contains SHA-256 digests/sizes but there is no separate manifest signing key/public-key verification layer yet. The latest commit message says "signed release manifests", but code currently implements hash manifest verification.

### 18.1 Desired formal-release UX

The intended product flow is:

```text
validated ZN code lands on main
→ formal ZN release/tag is published from main
→ clients detect the new ZN version automatically
→ update asset downloads in background
→ UI shows update ready
→ UI clearly shows:
     - new features
     - improvements
     - bug fixes
     - compatibility/behavior impacts
→ user clicks Install
→ verified staged update replaces desktop/runtime safely
```

The user should not need to discover releases manually or watch a developer channel.

Current code does **not** yet fully implement this target: it polls release availability every six hours and downloads when `apply()` is invoked; it does not yet pre-download the asset in the background or present structured release notes/changelog categories in the update UI.

Official release tags should originate from the ZN `main` release branch once the branch promotion is completed.

## 19. Current clean-machine bootstrap gap

This is the most important concrete integration gap found after reading the actual current code.

Current facts:

- `electron-builder.zn.yml` packages the desktop shell, not the ZN Python resident/runtime itself.
- inherited `apps/desktop/scripts/before-build.mjs` explicitly says the Python payload is not bundled;
- first-launch bootstrap is still inherited from Hermes installer infrastructure;
- `bootstrap-runner.ts` still builds the raw installer URL using `NousResearch/hermes-agent`;
- production ZN build stamps contain a **ZN repository commit SHA**;
- that ZN SHA normally does not exist in the Hermes upstream repository;
- fallback to an already-installed Hermes checkout cannot help a genuinely clean machine;
- inherited installer defaults still contain Hermes-oriented paths/names in multiple places.

Therefore a packaged ZN desktop is not yet production-complete merely because the Electron artifact builds and updates.

Required clean-machine invariant:

```text
fresh machine
→ install ZN desktop
→ obtain/install exact compatible ZN-owned runtime substrate
→ boot agent.kernel.resident_server
→ create/use persistent ZN home
→ expose reconnectable resident endpoint
→ install OS login autostart
→ Electron attaches as client
→ later ZN updates preserve resident continuity
```

No existing Hermes checkout, source checkout or manually prepared ZN Python package should be required.

## 20. Immediate next development target

The next implementation target is now **ZN-owned distribution/bootstrap continuity**, not transfer-attention rhythm.

Primary objective:

**Remove Hermes as an operational dependency from the clean-install/update path while preserving reusable mature implementation where useful.**

Work should proceed in this order unless actual code inspection proves a different dependency order is necessary:

1. Replace Hermes-hosted bootstrap script resolution with a ZN-owned source/artifact path.
2. Decide and implement how a release contains or obtains the compatible ZN Python/runtime substrate on Windows/macOS/Linux.
3. Make first launch boot `agent.kernel.resident_server` on a clean machine without an existing Hermes/source checkout.
4. Preserve one persistent ZN home across desktop/runtime updates.
5. Ensure OS autostart points at the updated compatible ZN runtime after upgrades.
6. Add clean-machine/bootstrap tests that prove the path does not contact Hermes for required runtime material.
7. Finish product-facing removal of inherited Hermes branding/update assumptions in the active ZN path.
8. Add background update pre-download + structured ZN release notes UI.
9. After CI is green, execute the repository branch migration so ZN `main` becomes the formal release branch and the original Hermes reference is retained separately as `upstream/hermes`/a preserved reference.

Do not solve this by simply redirecting more Hermes channels into ZN. The communication/release/bootstrap channel itself must become ZN-owned.

## 21. Branch state at this sync

Actual repository state at documentation sync:

```text
main HEAD:
61dd880aa4bbbdb359ca544b752afc2c22845ce9
(original Hermes-derived repository snapshot)

dev/zn-agent functional HEAD before this documentation commit:
380a916fc166a3f2de0ab3794e99e81c835fb7bc
feat: update ZN desktop from signed release manifests

dev/zn-agent relative to main:
222 commits ahead
0 commits behind
```

The functional head's commit message uses "signed" terminology, but current implementation is hash-manifest verification as described above.

Desired branch migration is documented in §2.1 and §20. It has not been silently assumed complete merely because it was planned in an earlier conversation.

## 22. CI and cost control

Current normal development CI:

- locked/reproducible Python environment;
- model-free ZN boot smoke;
- Python kernel tests;
- Electron/TypeScript typecheck;
- expensive container/runtime smoke skipped on ordinary development pushes.

Latest verified CI for functional head `380a916f...` before this docs commit:

```text
ZN Kernel / Python       success
Electron / TypeScript    success
Actions run              32527603821
```

Control GitHub Actions cost:

- group coherent changes;
- avoid many tiny pushes;
- do not rerun superseded historical commits for cosmetic reasons;
- keep expensive container/package jobs for changes/releases that actually need them.

## 23. Important code map

Resident/kernel:

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
├── world_closed_loop.py
├── visual_sense.py
├── daemon.py
├── service.py
├── resident_server.py
├── resident_autostart.py
├── provider_bridge.py
└── store.py
```

Desktop/product/release:

```text
apps/desktop/
├── electron-builder.zn.yml
├── electron/
│   ├── zn-main.ts
│   ├── zn-preload.ts
│   ├── zn-resident-ipc.ts
│   ├── zn-resident-process.ts
│   ├── zn-resident-autostart.ts
│   ├── zn-release-updater.ts
│   └── bootstrap-runner.ts
├── scripts/
│   ├── before-build.mjs
│   ├── bundle-electron-main.mjs
│   ├── write-build-stamp.mjs
│   └── write-zn-release-manifest.mjs
└── src/app/
    ├── zn-workbench.tsx
    └── zn/
        ├── resident-status.tsx
        └── update-status.tsx
```

Release/CI:

```text
.github/workflows/zn-ci.yml
.github/workflows/zn-release.yml
```

Tests under `tests/agent/kernel/` are part of the architecture specification. Restart/continuity tests are essential: a resident-native feature should not disappear merely because the process restarts.

## 24. Architecture traps to avoid

1. Do not make an external model the owner of the main loop.
2. Do not feed all memory to a model on every interaction.
3. Do not create a new skill for every successful experience.
4. Do not treat tools/files/processes as cognitive skills merely because ZN can use them.
5. Do not make an old schema automatically true; current reality must be able to correct it.
6. Do not turn Will into an ever-growing plan/task list.
7. Do not make idle reflection a hidden self-prompt token loop.
8. Do not equate model success with ZN accepting/completing a task.
9. Do not make Electron window lifetime equal resident lifetime.
10. Do not allow cross-context association to become action without present Situation evidence.
11. Do not turn one transfer success into a permanent context rule.
12. Do not collapse independent agreeing/conflicting transfer evidence into one strongest path.
13. Do not let failure in context B erase a relation correctly learned in context A.
14. Do not create a second context-policy memory store for behavior that belongs in lived neural state.
15. Do not spend this phase primarily on policy/constraint frameworks instead of the organism's core loops.
16. Do not make Hermes availability, Hermes releases, Hermes commit history or Hermes update infrastructure necessary for ZN to install, boot or update.
17. Do not rewrite mature infrastructure merely to claim originality; adopt it deliberately under ZN ownership when it solves the right problem.
18. Do not automatically merge `upstream/hermes` into ZN branches.

## 25. Handoff for the next development session

Use this as the current starting instruction:

> Continue `9529360-cpu/znagent` from the latest repository state. Read actual code first, then `ZN.md`; code remains authoritative. ZN is the product/subject and Hermes is only an upstream engineering reference. Do not depend on Hermes release/bootstrap/update channels. The previous transfer-attention target is already implemented. The immediate target is the ZN-owned clean-machine distribution/bootstrap/runtime continuity loop, followed by background ZN update pre-download and structured release notes. Keep the resident organism model-first only when it actually reaches an impasse; preserve native zero-model paths. Control CI cost. Do not modify `main` until the coherent branch-promotion step is intentionally executed after verification; when that migration is executed, `main` becomes the ZN formal release branch and Hermes remains only a separate reference/upstream source.

## 26. Provenance

This repository started from Hermes Agent source and continues to reuse mature infrastructure where useful. Preserve applicable upstream license/attribution requirements.

That provenance does not imply product dependence. ZN's identity, runtime architecture, release lifecycle and future maintenance belong to ZN.