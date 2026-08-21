# ZN Agent — Product and Engineering Blueprint

> Active development branch: `dev/zn-agent`
>
> This document is the architecture and product contract for ZN.
>
> **ZN.md must stay ahead of implementation.** Before a substantial product or architecture change is coded, the target state and migration step must exist here first. Code is still the source of truth for what currently exists, but code is not allowed to silently redefine where the product is going.

---

## 0. Development contract: document first, then code

The repository started from a large mature codebase, so it is very easy to make a locally reasonable change that accidentally continues the old product architecture. The development process therefore has a strict order:

```text
inspect current repository code
→ identify actual current boundary
→ update ZN.md with the intended target/migration step
→ implement that step
→ test the real path
→ update only status/checklists after implementation
```

Rules:

1. Do not start a new architectural direction only because an inherited module already exists.
2. Do not let a temporary compatibility path silently become the product architecture.
3. Do not describe transitional code as complete ZN ownership.
4. If code reveals that this document is factually wrong about the current state, correct the current-state section before continuing implementation.
5. Architectural decisions should be written here before they are spread across multiple commits.
6. Tests specify behavior, but they do not replace the product architecture described here.
7. A green inherited test suite does not prove that the ZN product boundary is correct.
8. `main` remains untouched until the explicit migration/promotion milestone in this document.

This rule is intentionally stronger than the usual “keep docs in sync with code.” For ZN, the design document is the route map; implementation moves along that route.

---

## 1. Product definition

ZN is a long-lived resident digital subject that lives on a computer.

The central inversion is:

**ZN uses models. Models do not own ZN.**

GPT, Claude, Gemini, DeepSeek, local models, search systems, browsers, code interpreters and future cognitive systems are replaceable resources. They are not the holder of ZN's identity, memory, Will or continuity.

For this project, “alive” means persistent computational continuity of self, state, perception, intention, thought, action, experience and adaptation even when no chat session or external model is active. It is not a claim of biological consciousness.

Product ownership:

- ZN is the subject.
- Models are bounded cognitive resources ZN may consult.
- Tools are ways ZN's body can affect the computer/world.
- Senses are ways ZN obtains current evidence from the computer/world.
- Memory is lived experience that changes the resident itself.
- Code is part of ZN's computational body.
- Electron/Desktop is a face and work surface, not the owner of ZN's life.
- Installation, runtime selection, configuration, updates and user data are owned by ZN.

Disconnecting every external model must not erase ZN's identity, memory, resident state or ability to continue native pulses.

### 1.1 Product experience

ZN should feel like one persistent digital subject with a calm workbench around it, not a collection of agents, dashboards and developer panes.

The normal user experience is:

```text
open ZN
→ immediately reconnect to the same resident
→ see current/previous work and conversations
→ ask, inspect, create or continue work
→ ZN acts through its own body and senses
→ external models appear only as resources when needed
→ closing the window does not erase ZN or terminate its resident life
```

The UI may expose resident activity, memory, work artifacts, files and tools, but those surfaces are views into one subject.

---

## 2. Hermes boundary: source reference only

The repository began from uploaded Hermes Agent source because mature solved engineering should be studied instead of ignored.

Hermes is a **reference codebase and implementation source**. It is not the ZN product, not the ZN UI, not the ZN runtime, not the ZN release path and not a permanent dependency boundary.

Correct reuse pattern:

```text
ZN needs a solved engineering mechanism
→ inspect Hermes/reference implementation
→ understand the mechanism and its edge cases
→ extract/adapt only the useful implementation
→ place it under a ZN-owned interface/module
→ remove inherited product assumptions
→ test it as ZN behavior
→ maintain it from ZN thereafter
```

Incorrect reuse patterns:

```text
ZN needs a desktop
→ start the entire Hermes desktop
→ put a ZN wrapper around it

ZN needs provider access
→ instantiate the entire Hermes AIAgent as ZN's worker forever

ZN needs a release runtime
→ pip install the Hermes project into a package named ZN

ZN needs a UI
→ render the Hermes ContribController with a different default layout
```

Those patterns preserve the old product as the actual control plane. They are explicitly not the target architecture.

### 2.1 Hard product-ownership rules

Final active ZN paths must satisfy all of the following:

- ZN artifacts are built from `9529360-cpu/znagent`.
- ZN does not resolve runtime code or release commits from `NousResearch/hermes-agent`.
- ZN install/bootstrap does not require Hermes to be online or installed.
- ZN updates do not track Hermes releases.
- A clean user machine does not require a Hermes checkout.
- The private ZN source repository is not a credentialless client update dependency.
- ZN user data lives under ZN-owned locations and names.
- ZN desktop process, preload API, protocol, updater and renderer are ZN-owned.
- ZN runtime package metadata and executable entrypoints are ZN-owned.
- ZN provider/resource adapters are ZN-owned interfaces.
- ZN body/sense adapters are ZN-owned interfaces.
- No final ZN product path requires `hermes_cli`, `run_agent`, a Hermes desktop main process or Hermes renderer root.
- No final ZN installer registers `hermes://` as a product protocol.
- No final ZN package presents Hermes product metadata to the OS or package manager.

Reference code may remain temporarily in the development branch while a mechanism is being extracted. That is migration debt, not an accepted final dependency.

### 2.2 What “borrow code” means

ZN is allowed to reuse mature implementation, including substantial algorithms, provider handling, terminal edge cases and platform work, when doing so is legally and technically appropriate.

Reuse does **not** require rewriting every line for cosmetic originality. It does require moving product ownership:

- choose the specific mechanism;
- move/copy/adapt it into a ZN namespace;
- replace Hermes configuration/state assumptions with ZN equivalents;
- reduce dependencies to what that mechanism actually needs;
- preserve applicable license/provenance;
- give it ZN tests and ZN lifecycle ownership.

The goal is not “no shared ancestry.” The goal is “no old product underneath the new one.”

---

## 3. Repository reality at the blueprint reset

This section records the actual state discovered before this blueprint rewrite. It deliberately distinguishes strong ZN work from transitional paths that must be replaced.

### 3.1 Branch state

```text
main
  = original Hermes-derived snapshot

dev/zn-agent
  = active ZN development branch
  = contains the resident/kernel work and current desktop/release experiments
```

Desired eventual topology:

```text
main
  = verified ZN product/release branch

dev/zn-agent
  = active ZN development branch

upstream/hermes
  = optional reference mirror/snapshot for studying and diffing mature upstream code
```

`upstream/hermes` is reference-only. It must never auto-merge into ZN.

### 3.2 Current subsystem assessment

| Subsystem | Current reality | Target classification |
| --- | --- | --- |
| Resident kernel | Large ZN-native implementation under `agent/kernel/`; persistent life, nervous system, Will, world/vision sensing, investigation, transfer and reconsolidation exist | Keep and evolve; migrate namespace later if useful |
| Resident process | ZN-owned socket service, endpoint, autostart and runtime identity exist | Keep |
| Model bridge | `provider_bridge.py` still loads `hermes_cli.config`, `hermes_cli.runtime_provider`; `worker.py` can instantiate legacy `run_agent.AIAgent` | Transitional; replace with ZN resource adapters |
| Terminal/body | Most body actions are native, but terminal delegates to inherited `tools.terminal_tool` | Transitional; extract terminal mechanism |
| World/web sense | World logic is ZN-native, but search delegates to inherited `tools.web_tools` | Transitional; extract web-search resource |
| Visual sense | ZN-owned resident-side logic; Pillow screen capture is direct | Keep/evolve |
| Desktop renderer | ZN entry ultimately renders inherited `ContribController`; old UI tree remains the actual application | Wrong product boundary; replace |
| Electron main | `zn-main.ts` configures ZN additions and then imports inherited `electron/main.ts` | Wrong product boundary; replace |
| Preload | `zn-preload.ts` imports inherited preload and adds `window.znDesktop` | Wrong product boundary; replace |
| Desktop package metadata | `apps/desktop/package.json` still declares Hermes name/product/repository and default build metadata | Wrong product boundary; replace |
| ZN builder config | ZN-specific builder file exists, but still packages the inherited desktop bundle and registers both `zn` and `hermes` protocols | Transitional; rebuild around independent desktop |
| Runtime staging | Portable Python logic exists, but staging installs the root project whose distribution is still `hermes-agent` and explicitly verifies `hermes_cli/main.py` | Wrong product boundary; replace |
| Release/update protocol | ZN-owned stable-channel parser/updater/publisher logic exists | Concept is valid; reattach to independent desktop/runtime |
| Release package CI | Multi-OS packaging is currently failing, and making the inherited package green is not the primary objective until product boundaries are corrected | Pause as product gate; resume after migration |

### 3.3 Important correction to previous development direction

The previous release work treated “built from the ZN repository” as sufficient ownership. That standard is too weak.

A package is not truly ZN-owned merely because GitHub Actions runs in the ZN repository. If the packaged Python distribution, Electron main process, preload bridge and renderer root are still the inherited product, then the installer is still structurally the old product with ZN additions.

Therefore:

**Do not continue polishing the current inherited release package as if it were the final ZN packaging architecture.**

Parts of the work remain useful — portable Python, versioned runtime directories, runtime manifest, resident handoff, stable update protocol, artifact hashing — but they must be reconnected to a genuinely ZN-owned application boundary.

---

## 4. Final product architecture

The target system has four product-owned layers:

```text
┌─────────────────────────────────────────────────────────────┐
│                     ZN Desktop Workbench                    │
│     conversation · work · artifacts · settings · status    │
└──────────────────────────────┬──────────────────────────────┘
                               │ ZN IPC / local resident RPC
┌──────────────────────────────▼──────────────────────────────┐
│                     ZN Resident Service                     │
│ identity · life · situation · thought · will · memory      │
│ investigation · action · learning · adaptation             │
└───────────────┬──────────────────────────────┬──────────────┘
                │                              │
       ┌────────▼─────────┐            ┌───────▼──────────┐
       │  Body / Senses   │            │ Cognitive       │
       │ files · process  │            │ Resources       │
       │ terminal · web   │            │ GPT · Claude    │
       │ screen · browser │            │ local models    │
       └──────────────────┘            └──────────────────┘
```

The Desktop can disappear and the Resident remains valid.

Models can disappear and the Resident remains valid.

Individual tools/providers can be replaced without changing ZN's identity.

---

## 5. Organism-first resident architecture

### 5.1 One subject, modular organs

Conceptually there is one subject:

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
├── Learning / reconsolidation
└── External cognitive resources
```

Implementation may be modular, but do not turn every concern into its own planner/manager agent.

### 5.2 Resident closed loop

Normal life loop:

```text
exist
 ↓
sense body / world / internal state
 ↓
Situation
 ↓
Thought
 ↓
maintain or choose intention
 ↓
native investigation / movement / reflection
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
→ one concrete Probe
→ Evidence
→ next Pulse / new Thought
→ ...
→ Native Deliberation
→ Impasse only if local cognition is exhausted
→ External Cognition if useful
→ CognitiveIncrement
→ native ZN evaluation/integration
→ Action / Outcome
```

A processing event remains durable across pulses. Work must not cognitively restart simply because one heartbeat ended.

### 5.3 Models are bounded increments

A provider response is never automatically ZN's decision.

```text
exact unknown/gap
→ bounded request
→ selected external cognitive resource
→ CognitiveIncrement
→ ZN evaluates against current Situation / evidence
→ integrate, reject, probe further or act
```

The final provider layer must not require constructing a complete legacy LLM-centric agent to obtain one bounded cognitive increment.

### 5.4 Native behavior remains valuable without models

Zero-model operation must continue to support:

- life pulses;
- persistent identity and state;
- body sensing;
- filesystem/process/Git observation;
- native investigation;
- memory recall;
- Will/attention evolution;
- world/visual sensing when those resources are locally available;
- deterministic/local capabilities;
- explicit “external cognition unavailable” outcomes when needed.

---

## 6. Body, senses and action

Files, processes, Git, terminal operations, browser interaction and host sensing are body movements/senses, not separate cognitive personalities.

```text
Thought
→ NativeActionIntent
→ Body
→ BodyActionResult
→ current Situation / nervous experience
→ next Thought
```

Failed movement returns as evidence. It is not silently treated as success and should not automatically produce an infinite retry loop.

### 6.1 ZN-owned adapter rule

The final resident may call interfaces such as:

```text
zn.body.files
zn.body.process
zn.body.terminal
zn.senses.web
zn.senses.visual
zn.senses.browser
```

Those interfaces may contain adapted mature implementation, but ZN code must not permanently cross the product boundary to invoke inherited product-level modules such as `tools.terminal_tool` or `tools.web_tools`.

### 6.2 Terminal

The mature terminal implementation is valuable because process management, PTY behavior, background jobs and platform differences are difficult.

Migration principle:

```text
study existing terminal stack
→ identify execution/session primitives ZN actually needs
→ port those primitives into a ZN terminal body adapter
→ remove chat-agent-specific/global-Hermes assumptions
→ test Windows/macOS/Linux behavior
```

Do not reimplement shell execution from zero just to avoid shared ancestry.

### 6.3 Web/world sensing

`NativeWorldSense` owns what ZN follows, sampling rhythm, durable observations and change interpretation at the sensor level.

The web provider itself is replaceable transport. Final code should look conceptually like:

```text
WorldSense
→ SearchResource interface
→ concrete web/search provider
→ structured observation
→ nervous system
```

It should not be “WorldSense calls Hermes web tool.”

### 6.4 Vision

Visual sensing remains resident-owned. Raw pixels should not become long-lived memory by default. Compact structural evidence can persist and influence attention.

Screen capture failure, missing permission or headless execution is a sensory failure, not a resident-death condition.

---

## 7. Nervous system, memory, Will and learning

`PersistentNervousSystem` and the related reconsolidation/transfer machinery are the lived-memory substrate. It is not a transcript database.

```text
experience
→ traces / relations
→ repeated structure
→ consolidation
→ schema/prediction
→ current reality test
→ support / refinement / contradiction
→ reconsolidation
→ future recall and Will change
```

Schemas are predictions, not eternal facts.

Cross-context transfer never directly becomes action:

```text
cross-context activation
→ candidate tendency
→ current Situation/body independently tests applicability
→ unsupported candidate stays weak/frozen
→ repeated present support raises maturity
→ only then can it shape concrete intention/action
```

Learning is consolidation, not one-skill-per-success.

Executable capability and learned competence are separate concepts.

Will must not degrade into an ever-growing task/planner list. It should remain a compact, durable mechanism for what matters now and what should continue receiving attention.

---

## 8. External cognitive resources and integrations

### 8.1 Target provider interface

ZN needs a native resource boundary that can support multiple external brains without making any one SDK or legacy agent the owner.

Conceptually:

```text
CognitionRequest
    ↓
CognitiveResourceRouter
    ↓
CognitiveProvider
    ├── OpenAI
    ├── Anthropic
    ├── Google
    ├── OpenRouter
    ├── local model
    └── future resources
    ↓
CognitiveIncrement
```

Providers should expose capabilities, availability, cost/latency/reliability metadata and a bounded invoke path.

### 8.2 Provider migration strategy

Do not throw away mature provider work.

For each provider/integration:

1. identify the minimal mature mechanisms worth keeping;
2. extract them from agent-level orchestration;
3. move them behind a ZN provider/resource interface;
4. replace Hermes home/config/identity assumptions;
5. keep credentials in ZN-owned configuration/storage;
6. test the resource directly;
7. only then remove the inherited path.

The target removes `LegacyAIAgentWorkerFactory` from production runtime. A temporary adapter may remain during migration, but no new ZN feature should deepen that dependency.

### 8.3 Messaging, browser and other mature systems

Telegram, WhatsApp/other messaging, browser drivers, provider adapters and similar mature mechanisms can be adopted selectively later.

They must become **ZN integrations**, not a reason to resurrect the old product control plane.

---

## 9. ZN Desktop: independent product, ChatGPT-style workbench

### 9.1 UI ownership rule

ZN will not ship the Hermes UI with a ZN theme/layout.

The final renderer must have its own application root, information architecture and interaction model.

The current `ContribController`-based renderer is transitional and must be replaced.

The target experience is inspired by the clarity of the ChatGPT desktop/web workbench model:

- conversation/work is the primary surface;
- navigation/history is calm and predictable;
- advanced tools appear contextually instead of dominating the screen;
- artifacts/results can expand beside the conversation when useful;
- there is one clear composer/input area;
- visual hierarchy is minimal and content-first;
- the product does not open as an IDE with multiple permanent technical panes.

This is interaction inspiration, not a copy of OpenAI branding, proprietary assets or exact styling.

### 9.2 Default desktop information architecture

Target default desktop:

```text
┌────────────────────────────────────────────────────────────────────┐
│  ZN / workspace title                           resource · account  │
├──────────────────┬─────────────────────────────────────────────────┤
│                  │                                                 │
│  New work        │                 Main work                       │
│  Search          │                                                 │
│                  │   conversation / resident interaction           │
│  Recent          │                                                 │
│  Pinned          │   inline actions / progress / results           │
│  Workspaces      │                                                 │
│                  │   optional artifact/context panel when needed   │
│                  │                                                 │
│  Settings        │                 composer                        │
└──────────────────┴─────────────────────────────────────────────────┘
```

The exact pixels may evolve. The hierarchy should not.

### 9.3 Main surfaces

The initial ZN desktop should own these product surfaces:

1. **Home / new work**
   - clear entry composer;
   - recent work;
   - resident availability/status only when relevant.

2. **Conversation / work thread**
   - user ↔ ZN interaction;
   - streaming/ongoing state;
   - model/resource use can be visible without pretending the model is ZN;
   - tool/body actions can be shown in compact activity blocks;
   - generated artifacts can open beside the thread.

3. **Artifact/context panel**
   - optional, not permanent;
   - files, rendered artifacts, diffs, structured results, resident details;
   - opening it must not replace the primary thread unexpectedly.

4. **Workspaces/projects**
   - local folder/project association;
   - clear active workspace;
   - files/terminal become contextual work tools rather than permanent default panes.

5. **Resident view**
   - lightweight inspection of current state, activity, world focuses and runtime health;
   - this is observability into ZN, not a second “agent manager.”

6. **Settings**
   - models/providers;
   - credentials;
   - resident/autostart;
   - appearance;
   - updates;
   - integration toggles as they are added.

### 9.4 Terminal/files/tools UX

Terminal, files and review are useful, but ZN is not primarily an IDE.

Default behavior:

- files open as contextual browser/artifact views;
- terminal opens as an explicit contextual panel/drawer/work surface;
- diffs/review appear when work produces them;
- hidden tools do not occupy permanent screen real estate;
- advanced users may later pin or arrange work surfaces, but that is not the first-run layout.

### 9.5 UI implementation rule

The new UI may reuse generic third-party libraries already present when appropriate, for example React, TanStack Query, assistant-ui, Radix-style primitives or other non-Hermes dependencies.

Inherited Hermes UI components are reference material. If a primitive is genuinely excellent, its implementation pattern can be adopted into a ZN-owned component. The final app root must not import the old product shell.

### 9.6 Target renderer tree

A possible target structure:

```text
apps/desktop/src/
├── main.tsx
├── app/
│   ├── app.tsx
│   ├── router.tsx
│   └── providers.tsx
├── workbench/
│   ├── shell.tsx
│   ├── sidebar.tsx
│   ├── topbar.tsx
│   ├── thread.tsx
│   ├── composer.tsx
│   ├── activity.tsx
│   └── context-panel.tsx
├── resident/
│   ├── client.ts
│   ├── state.ts
│   └── views/
├── artifacts/
├── workspaces/
├── settings/
├── components/
├── state/
└── styles/
```

Names can change. Ownership cannot.

---

## 10. ZN Electron process architecture

The final desktop main process must start from ZN code directly.

Incorrect transitional shape:

```text
zn-main
→ configure some ZN state
→ import inherited main.ts
→ inherited product creates windows/backend/protocols
→ add ZN IPC afterward
```

Target shape:

```text
ZN Electron main
→ establish ZN single-instance/protocol
→ locate/materialize packaged ZN runtime
→ connect/start resident
→ register ZN IPC
→ create ZN windows
→ load ZN renderer
→ manage ZN updates
```

### 10.1 ZN preload

The final preload exposes only intentional ZN APIs.

Conceptually:

```ts
window.znDesktop = {
  resident: ...,
  files: ...,
  system: ...,
  workspaces: ...,
  updates: ...,
  shell: ...
}
```

Do not import an inherited preload and then layer ZN onto it.

### 10.2 Protocol

Final product protocol:

```text
zn://
```

No Hermes protocol registration in a formal ZN installer.

### 10.3 Backend relationship

Electron is not required to start a separate inherited dashboard/backend process merely to make the ZN UI function.

If a mature backend capability is adopted, extract the capability or expose it through a ZN-owned local service boundary. Do not keep a hidden old product server as the actual desktop backend.

---

## 11. ZN-owned Python/runtime package

### 11.1 Final distribution identity

The final Python project must be ZN-owned. The distribution/module naming may be finalized during migration, but the intended direction is:

```text
Python distribution: zn-agent
Python package:      zn_agent  (or another explicitly chosen ZN namespace)
resident entrypoint: zn-resident
optional CLI:        zn
```

Do not ship a formal ZN runtime whose installed distribution metadata is `hermes-agent`.

### 11.2 Final runtime content

The packaged resident runtime contains only what ZN actually needs:

```text
portable CPython
+ ZN resident/core package
+ ZN provider/integration adapters selected for desktop
+ exact runtime dependencies
+ required runtime data
+ runtime.json
```

It must not require `hermes_cli/main.py` as a validity condition.

### 11.3 Versioned runtime directories

Keep the useful versioned-runtime concept:

```text
<ZN_HOME>/runtime/<runtime_id>/
```

Runtime N and N+1 can coexist while the resident safely transitions.

Persistent identity/state lives outside those immutable runtime directories.

---

## 12. Persistent home and configuration

ZN owns its persistent home.

Default direction:

```text
Windows: %LOCALAPPDATA%/znagent
macOS:   ~/Library/Application Support/ZN   (final OS-native path to be chosen deliberately)
Linux:   ~/.local/share/znagent or ~/.znagent during migration
```

A migration may preserve current `~/.znagent` semantics initially, but formal platform paths should eventually be explicit and tested.

Persistent categories should be separated:

```text
ZN_HOME/
├── identity / kernel state
├── memory / nervous data
├── work / artifacts
├── config
├── credentials metadata / secure-store references
├── runtime/
├── logs/
└── updates/
```

Model credentials and user secrets must use appropriate secure storage where available rather than leaking into logs/state snapshots.

No final ZN path should depend on `HERMES_HOME`.

---

## 13. Resident process, runtime identity and autostart

Core principle:

```text
Resident service = life/process continuity
Electron = face/client
```

Electron reconnects to an existing resident endpoint or starts the resident if needed. Closing the desktop disconnects the UI; it does not inherently stop resident life.

Existing ZN work worth retaining:

- local reconnectable endpoint;
- process-level `runtime_id` and `python` reporting;
- versioned runtime materialization;
- OS-login autostart;
- same ZN home across runtime upgrades;
- conservative N → N+1 handoff.

### 13.1 Safe N → N+1 handoff

Target policy remains:

```text
Desktop N+1 starts
→ materialize runtime N+1 beside runtime N
→ connect to existing resident if alive
→ point future autostart to N+1 first
→ compare active runtime with desired runtime

if already N+1
  → continue

if active work exists
  → do not interrupt
  → keep resident alive
  → recheck later

if resident is idle
  → graceful shutdown RPC
  → wait for endpoint retirement
  → start N+1 using same ZN home
  → verify active runtime identity
```

Runtime switching is a body/process lifecycle event, not a SelfModel memory event.

---

## 14. Release and update architecture

### 14.1 Installer requirements

A formal installer must contain an independently bootable ZN product:

- ZN desktop executable;
- ZN renderer;
- ZN preload/main process;
- self-contained ZN Python runtime;
- required dependencies/data;
- ZN assets/branding;
- ZN updater configuration.

A clean machine must not need:

- Hermes;
- a source checkout;
- system Python;
- Node/npm;
- developer GitHub credentials;
- access to the private source repository.

### 14.2 Builder identity

Formal package metadata must be consistently ZN-owned:

```text
productName: ZN
appId:       ai.zn.desktop (unless deliberately changed)
protocol:    zn
artifact:    ZN-<version>-<os>-<arch>...
```

`apps/desktop/package.json` itself must become ZN-owned; a separate builder override is not enough.

### 14.3 Public update channel

The ZN-defined provider-neutral stable channel remains the target:

```json
{
  "schema": 1,
  "product": "ZN",
  "channel": "stable",
  "version": "1.2.3",
  "release_url": "https://updates.example/releases/1.2.3",
  "notes": {
    "new": [],
    "improvements": [],
    "fixes": [],
    "impact": []
  },
  "targets": []
}
```

The client must not know or care which ZN-controlled object-storage/CDN provider serves it.

Release order:

```text
build verified self-contained ZN installers
→ publish immutable versioned assets
→ optionally create archival GitHub Release
→ publish/replace stable.json LAST
```

`stable.json` is the mutable pointer. Versioned binaries are immutable.

### 14.4 Integrity and signing

Current hash verification is useful but is not independent signing.

Final release hardening should include:

- artifact size verification;
- SHA-256 verification;
- platform code signing where operationally available;
- notarization on macOS when configured;
- later signed release metadata if a durable public-key scheme is introduced.

Do not call hashes “signature verification.”

---

## 15. Safety without turning ZN into a policy-agent framework

Safety belongs in concrete body/resource boundaries and product UX, not in a giant prompt constitution that replaces the organism loop.

Examples of correct engineering boundaries:

- explicit destructive filesystem operations;
- clear credential handling;
- scoped browser/network permissions;
- platform permission surfaces for screen/microphone/camera;
- update integrity checks;
- bounded resource/time usage;
- reversible operations and visible failures where practical.

The current development priority remains building the resident organism and owned product architecture. Do not derail the project into a large governance/policy subsystem before the core product exists.

---

## 16. Testing philosophy

Tests are architecture contracts, not a substitute for architecture.

### 16.1 Kernel tests

Protect:

- zero-model resident boot/life;
- persistence across process restarts;
- Situation/Thought/Will continuity;
- native investigation progression;
- body result → next cognition feedback;
- nervous consolidation/reconsolidation;
- reality-gated transfer;
- world/vision adaptive attention rhythm;
- external cognition remaining bounded.

### 16.2 Ownership-boundary tests

Add tests that explicitly prevent regression into the old product architecture.

Final active paths should be checked for forbidden product dependencies, for example:

```text
ZN runtime package must not import hermes_cli
ZN runtime package must not import run_agent
ZN desktop main must not import inherited main.ts
ZN preload must not import inherited preload.ts
ZN renderer root must not render/import inherited ContribController
formal builder must not register hermes://
formal package metadata must not identify product as Hermes
```

During migration these tests can be introduced milestone-by-milestone as each boundary is cut.

### 16.3 Desktop tests

Build new ZN tests around user behavior, not old UI snapshots:

- first launch;
- reconnect to existing resident;
- new work/thread;
- send/receive resident task interaction;
- model unavailable state;
- contextual tool/activity rendering;
- artifact panel open/close;
- workspace association;
- settings/provider configuration;
- app close leaves resident alive;
- update ready/apply flows.

### 16.4 Release tests

Formal release gates eventually include:

- package metadata is ZN-only;
- installer contains ZN runtime manifest;
- bundled Python imports only required ZN runtime entrypoints;
- clean-machine launch;
- no source checkout/system Python dependency;
- N → N+1 busy/idle handoff;
- autostart after login;
- public update channel reachability.

---

## 17. Target repository topology

The exact migration can be incremental, but the final active product should resemble this ownership shape:

```text
znagent/
├── ZN.md
├── pyproject.toml                # ZN distribution
├── zn_agent/                     # final ZN Python product namespace
│   ├── core/                     # resident/life/situation/thought/will
│   ├── cognition/                # bounded external cognition abstractions
│   ├── memory/                   # nervous system / learning / reconsolidation
│   ├── body/                     # files/process/terminal/browser actions
│   ├── senses/                   # host/world/visual/browser sensing
│   ├── integrations/             # provider/messaging/etc adapters
│   ├── runtime/                  # resident server, service, autostart
│   └── config/
├── apps/
│   └── desktop/                  # independent ZN Electron application
│       ├── electron/
│       ├── src/
│       ├── assets/
│       ├── scripts/
│       └── package.json
├── tests/
├── docs/
└── .github/workflows/
```

The existing `agent/kernel/` implementation does not need to be mechanically moved immediately. Namespace migration is lower priority than removing product-level dependencies. Do not perform a mass rename before the ownership seams are actually fixed.

Reference Hermes source should ultimately live outside the active ZN product tree, preferably on `upstream/hermes` (plus retained license/provenance), rather than being imported by production ZN code.

---

## 18. Full migration and product landing plan

This plan intentionally runs beyond the next few commits. It is the route to a complete independently maintainable ZN product.

### M0 — Blueprint reset and freeze wrong-direction expansion

Status: **current milestone**

Goals:

- establish this document as the forward contract;
- record that current desktop/release ownership is transitional/incorrect;
- stop deepening imports from inherited product control planes;
- do not spend multi-OS CI budget repeatedly polishing the wrong package shape.

Exit condition:

- ZN.md contains the complete ownership/UI/runtime/release target and migration order.

### M1 — Establish an independently packageable ZN Python runtime

Goals:

- create/finalize ZN-owned Python distribution metadata;
- package resident/core code without requiring `hermes_cli.main`;
- create native ZN config loading;
- create native provider/resource interfaces;
- keep zero-model resident boot working;
- stage portable runtime from only ZN-owned package content.

Migration detail:

1. isolate the resident package boundary;
2. port configuration fields ZN actually needs;
3. replace default `hermes_cli.config` loading;
4. replace provider resolver dependency with a ZN resource registry;
5. add a `zn-resident` entrypoint;
6. update runtime smoke to import ZN entrypoints only.

Exit condition:

```text
portable Python
→ install ZN distribution
→ start zn-resident
→ zero-model pulse succeeds
```

with no `hermes_cli`/`run_agent` requirement.

### M2 — Extract mature provider cognition into ZN resource adapters

Goals:

- replace `LegacyAIAgentWorkerFactory` in production;
- support at least the first real provider path through ZN-owned adapters;
- preserve bounded cognition semantics;
- port additional providers selectively.

Exit condition:

- a resident impasse can call an external model through a ZN-native provider adapter without constructing the legacy AIAgent.

### M3 — Extract body/sense infrastructure used by the resident

Goals:

- port terminal execution/session primitives needed by `NativeBody`;
- port web-search transport needed by `NativeWorldSense`;
- keep direct file/process/Git and visual paths intact;
- remove production imports from inherited `tools.*` for these paths.

Exit condition:

- resident native body/world loop runs from ZN-owned modules only.

### M4 — Build independent Electron main + preload foundation

Goals:

- replace `zn-main → inherited main` boot pattern;
- create ZN BrowserWindow lifecycle;
- create ZN single-instance/protocol handling;
- create ZN preload bridge;
- connect resident RPC directly;
- keep updater/runtime handoff modules that are genuinely ZN-owned.

Exit condition:

- an Electron app can launch a minimal ZN renderer and connect to resident without importing inherited main/preload.

### M5 — Build the new ChatGPT-style ZN workbench UI

Goals:

- independent renderer root;
- left navigation/history/workspaces;
- central work/thread surface;
- stable composer;
- compact body/resource activity presentation;
- optional context/artifact panel;
- settings/provider UI;
- resident status/inspection surface;
- ZN visual identity/assets.

Do not recreate every inherited desktop feature before first usable ZN UI. Build the product hierarchy first, then add capabilities according to actual ZN needs.

Exit condition:

- normal ZN use no longer renders `ContribController` or inherited app shell.

### M6 — Connect workbench to resident and artifacts

Goals:

- thread/task submission over ZN IPC/RPC;
- resident progress/state updates;
- bounded model-resource activity visibility;
- files/artifacts/diffs as contextual work products;
- workspace/project association;
- terminal/browser surfaces only when invoked.

Exit condition:

- a user can do real work end-to-end through the new ZN UI.

### M7 — Rebuild formal packaging around the owned product

Goals:

- make `apps/desktop/package.json` entirely ZN-owned;
- builder uses only `zn://`;
- bundle independent Electron main/preload/renderer;
- bundle independently packageable ZN Python runtime;
- preserve versioned runtime + manifest;
- remove Hermes validation from staging/verification.

Only here does multi-OS installer polishing become a primary release task again.

Exit condition:

- Windows/macOS/Linux artifacts contain only the intended ZN active product paths.

### M8 — Real clean-machine and continuity validation

Validate on actual artifacts:

1. clean install without Hermes/source/system Python;
2. first resident boot;
3. close/reopen desktop while resident continues;
4. OS-login autostart;
5. N → N+1 while resident busy — no interruption;
6. N → N+1 while idle — clean handoff;
7. same ZN identity/state after upgrade;
8. update channel asset reachability without private source credentials.

Exit condition:

- complete installer lifecycle is proven on all supported OS targets.

### M9 — Product completeness and hardening

After the owned end-to-end product works:

- provider/account setup polish;
- browser integration;
- selected messaging integrations;
- voice if desired;
- richer artifacts/workspaces;
- resource usage/performance work;
- secure secret storage review;
- signing/notarization/release hardening;
- accessibility and keyboard behavior;
- crash recovery/diagnostics;
- migration of useful mature features only where they improve ZN.

Avoid importing whole inherited subsystems just to check feature boxes.

### M10 — Repository migration and formal `main` promotion

Prerequisites:

- owned runtime;
- owned desktop UI/main/preload;
- owned release artifacts;
- clean-machine verification;
- reasonable CI coverage;
- applicable license/provenance preserved.

Then:

1. preserve reference Hermes state in `upstream/hermes` or equivalent archival reference;
2. remove inactive inherited product code from the ZN product branch when no longer needed;
3. update README/contribution docs to ZN;
4. intentionally promote verified ZN product to `main`;
5. keep `dev/zn-agent` as the development branch.

Do not perform this migration early merely for cosmetic cleanliness.

---

## 19. Product completion criteria

ZN is not “done” merely because the kernel tests pass or an installer exists.

A credible first complete product release should satisfy all of these:

### Identity/life

- persistent identity/state survives desktop restart and OS restart;
- resident is not owned by an external model session;
- zero-model resident boot works.

### Cognition

- native investigation/body actions work;
- external models are bounded replaceable resources;
- at least one production provider path is ZN-native;
- model output is integrated/evaluated by ZN rather than treated as automatic truth/action.

### Body/senses

- files/process/Git/terminal paths are ZN-owned;
- world sensing is ZN-owned;
- visual sensing failure does not kill resident;
- body results feed back into Situation/Thought.

### Memory/learning

- lived state persists;
- reconsolidation can correct stale predictions;
- transfer requires current evidence;
- learning does not create a permanent skill for every success.

### Desktop

- independent ZN main/preload/renderer;
- ChatGPT-style workbench hierarchy;
- conversation/work is primary;
- files/terminal/artifacts are contextual;
- settings/provider management is usable;
- resident remains alive when UI closes.

### Packaging/update

- installer is ZN-only product identity;
- clean machine needs no Hermes/source/system Python;
- versioned runtime is self-contained;
- autostart works;
- safe runtime handoff works;
- stable update channel works;
- public update assets do not require source-repo credentials.

### Repository ownership

- final active product has no runtime dependency on Hermes product modules;
- provenance/license retained;
- `main` represents ZN, not the inherited snapshot.

---

## 20. CI and cost control

Normal development CI should stay cheap.

Default dev checks:

- locked Python environment for active ZN runtime;
- zero-model resident smoke;
- focused kernel tests;
- TypeScript typecheck/lint for active ZN desktop;
- focused desktop/runtime contract tests.

Expensive checks:

- multi-OS installers;
- clean-machine VM tests;
- signing/notarization;
- large E2E matrices.

Those should run only when the milestone needs them, on explicit workflow dispatch, release candidates/tags or carefully chosen paths.

The current release workflow temporarily running multi-OS packaging on every `dev/zn-agent` push is not the desired long-term cost model. Once implementation resumes, move expensive package validation behind an explicit/release-relevant trigger while the ownership migration is underway.

---

## 21. Architecture traps — prohibited directions

1. Do not make an external model the owner of the main loop.
2. Do not feed all memory to a model on every interaction.
3. Do not create a new skill for every successful experience.
4. Do not treat tools/files/processes as cognitive personalities.
5. Do not make old schemas automatically true; current reality can correct them.
6. Do not turn Will into an ever-growing planner/task database.
7. Do not make idle reflection a hidden self-prompt token loop.
8. Do not equate model success with ZN accepting/completing a task.
9. Do not make Electron lifetime equal resident lifetime.
10. Do not interrupt active resident work just to activate a new runtime.
11. Do not allow cross-context association to become action without present evidence.
12. Do not create another hidden private-repository bootstrap dependency.
13. Do not package the Hermes Python distribution and call it the ZN runtime.
14. Do not launch the Hermes Electron main process from a ZN wrapper as the final desktop.
15. Do not import the Hermes preload from the ZN preload as the final bridge.
16. Do not render the Hermes `ContribController`/shell as the final ZN UI.
17. Do not register `hermes://` in a formal ZN installer.
18. Do not preserve Hermes package/app metadata in formal ZN artifacts.
19. Do not deepen new ZN dependencies on `hermes_cli`, `run_agent` or inherited `tools.*` while those seams are scheduled for extraction.
20. Do not rewrite mature mechanisms merely for cosmetic originality; extract and own the useful engineering.
21. Do not automatically merge a reference Hermes branch into ZN.
22. Do not publish `stable.json` before immutable assets exist.
23. Do not turn this organism-building phase primarily into policy/governance infrastructure.
24. Do not modify `main` until M10 prerequisites are deliberately met.
25. Do not let code invent a new product direction that is absent from this blueprint.

---

## 22. Immediate next development target

After this blueprint commit, the next engineering target is **not** “make the current inherited multi-OS package green.”

The next target is M1:

**establish an independently packageable ZN Python runtime boundary, while preserving the existing resident organism behavior.**

Concrete order:

1. stop expensive multi-OS package runs from firing on every ordinary development push;
2. define the ZN Python distribution/package boundary and native config entrypoint;
3. make resident zero-model boot independent of `hermes_cli`;
4. introduce the ZN cognitive-resource interface;
5. keep the legacy provider worker only as an explicitly temporary adapter until M2;
6. change packaged-runtime smoke to validate only ZN entrypoints;
7. only then continue extracting provider/terminal/web mechanisms.

Desktop work follows M4/M5 after the runtime ownership seam is real. UI implementation must target the independent ChatGPT-style ZN workbench described above, not another layout on the inherited renderer.

---

## 23. Handoff instruction for future sessions

Use this as the canonical restart prompt:

> Continue `9529360-cpu/znagent` on `dev/zn-agent`. Read current repository code first, then read `ZN.md` completely before changing code. `ZN.md` is intentionally ahead of implementation and defines the target product. ZN is the only product/subject. Hermes is source reference only: borrow mature mechanisms selectively, move them under ZN ownership, and do not use the Hermes UI, Electron main/preload, Python distribution, runtime, release channel or product shell as ZN's permanent control plane. The current resident/kernel work is valuable, but provider/terminal/web seams are still transitional; the current desktop and packaged release boundary are explicitly not final. The UI target is an independent content-first ChatGPT-style workbench: calm left navigation/history/workspaces, central conversation/work surface and contextual artifacts/tools rather than the inherited IDE-like shell. Follow the milestone order in section 18. Immediate target is M1, an independently packageable ZN Python resident runtime. Preserve native zero-model behavior, organism-first architecture and CI cost discipline. Do not modify `main` before M10.

---

## 24. Provenance and attribution

This repository started from Hermes Agent source and will continue to study/adapt mature engineering where useful.

Preserve applicable upstream license, copyright and attribution requirements for reused implementation.

Provenance does not imply product dependence.

ZN's identity, resident architecture, UI, runtime package, distribution lifecycle, data model and future maintenance belong to ZN.