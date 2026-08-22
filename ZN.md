# ZN Agent — Product and Engineering Blueprint

> Active development branch: `dev/zn-agent`
>
> This document is the architecture and product contract for ZN.
>
> Current implementation details live in [`docs/ZN-IMPLEMENTATION-STATUS.md`](docs/ZN-IMPLEMENTATION-STATUS.md). Mature-source extraction rules and the current extraction ledger live in [`docs/ZN-SOURCE-EXTRACTION.md`](docs/ZN-SOURCE-EXTRACTION.md).
>
> **ZN.md must stay ahead of architecture changes.** Code is authoritative for what currently exists; this file is authoritative for where the product is going and which directions are prohibited.

---

## 0. Development contract: inspect first, document architecture, then code

The repository started from a mature inherited codebase. A locally convenient implementation can therefore accidentally keep the old product as ZN's real control plane.

The required development order is:

```text
inspect current repository code
→ identify the actual active boundary
→ read this blueprint completely
→ if architecture/direction must change, update ZN.md first
→ implement the smallest coherent ZN-owned step
→ test the real active path
→ update implementation/extraction status after verification
```

Rules:

1. Do not choose an architecture merely because an inherited module already exists.
2. Do not let a compatibility path silently become permanent product architecture.
3. Do not describe transitional code as complete ZN ownership.
4. If code proves a current-state statement in this blueprint wrong, synchronize that statement before continuing.
5. Tests specify behavior but do not replace the product architecture.
6. A green inherited test suite does not prove the ZN product boundary is correct.
7. `main` remains untouched until the explicit M10 migration/promotion milestone.
8. Mature mechanisms should be studied and extracted; old product control planes should not be embedded.
9. Ordinary development CI stays cheap. Multi-OS packaging/clean-machine release work runs only when the milestone needs it.

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
- Communication channels are I/O organs for the same resident, not separate agent identities.
- Electron/Desktop is a face and work surface, not the owner of ZN's life.
- Installation, runtime selection, configuration, updates and user data are owned by ZN.

Disconnecting every external model must not erase ZN's identity, memory, resident state or ability to continue native pulses.

### 1.1 Product experience

ZN should feel like one persistent digital subject with a calm workbench around it, not a collection of agents, dashboards and developer panes.

Normal experience:

```text
open ZN
→ reconnect to the same resident
→ see/continue current and previous work
→ ask, inspect, create or continue work
→ ZN acts through its own body and senses
→ external models appear only as resources when useful
→ closing the window does not erase ZN or define its identity
```

---

## 2. Hermes boundary: source reference only

The repository began from Hermes Agent source because mature solved engineering should be studied instead of ignored.

Hermes is a **reference codebase and implementation source**. It is not the ZN product, UI, runtime, release path or permanent dependency boundary.

Correct reuse pattern:

```text
ZN needs a solved engineering mechanism
→ inspect Hermes/reference implementation
→ understand mechanism + edge cases
→ extract/adapt the coherent useful slice
→ place it behind a ZN-owned interface/module/config/lifecycle
→ remove inherited product assumptions
→ add ZN tests
→ switch the active ZN caller
→ maintain it as ZN code
```

Incorrect reuse patterns:

```text
need desktop
→ start inherited Electron main and wrap it with ZN

need provider access
→ instantiate the inherited full AIAgent forever

need runtime
→ install the inherited Python distribution into a ZN package

need UI
→ render inherited ContribController under a ZN theme

need messaging
→ run the inherited gateway as ZN's communications brain
```

### 2.1 Hard ownership rules

Final active ZN paths must satisfy all of the following:

- artifacts are built from `9529360-cpu/znagent`;
- install/bootstrap does not require Hermes to be online or installed;
- a clean user machine does not require a Hermes checkout;
- updates do not track Hermes releases;
- private ZN source credentials are not a client update dependency;
- user data lives under ZN-owned locations/names;
- desktop main, preload API, protocol, updater and renderer are ZN-owned;
- runtime distribution metadata and executable entrypoints are ZN-owned;
- provider/resource, body/sense and channel interfaces are ZN-owned;
- no final active product path requires `hermes_cli`, `run_agent`, inherited Electron main/preload or inherited renderer root;
- no formal ZN installer registers `hermes://`;
- no formal ZN package presents Hermes product metadata to the OS/package manager.

Reference source may remain temporarily in the development branch while mechanisms are extracted. That is migration debt, not an accepted runtime dependency.

### 2.2 What “borrow code” means

ZN may reuse substantial mature implementation when legally and technically appropriate. Cosmetic originality is not the goal. Ownership transfer is.

A reused mechanism must:

- have a concrete ZN consumer;
- move behind a ZN-owned public contract;
- use ZN config/state/session ownership;
- drop inherited product assumptions that are not required by the mechanism;
- preserve applicable license/provenance;
- have ZN behavior tests;
- be packageable/testable without starting the old product control plane.

---

## 3. Repository reality and current ownership checkpoint

### 3.1 Branch policy

```text
main
  = inherited/original snapshot until M10

dev/zn-agent
  = active ZN development branch
```

Desired eventual topology:

```text
main
  = verified ZN product/release branch

dev/zn-agent
  = active ZN development branch

upstream/hermes
  = optional reference mirror/snapshot only
```

Reference upstream must never auto-merge into ZN.

### 3.2 Blueprint-reset history

At the blueprint reset, important active paths were still structurally inherited: provider construction could build `run_agent.AIAgent`, terminal/web crossed into inherited `tools.*`, desktop main/preload delegated to the inherited app, renderer mounted `ContribController`, and packaged runtime installed the inherited repository-root distribution.

Those facts motivated the ownership migration. They are historical context, not the current active-path status.

### 3.3 Current checkpoint — 2026-08-22

The active product boundary has moved substantially:

| Subsystem | Current active reality | Classification |
| --- | --- | --- |
| Resident kernel | ZN-native organism under `agent/kernel/` with persistent life, Situation/Thought/Will, nervous memory, investigation, action, learning and sensing | Keep/evolve |
| Python resident distribution | independent `runtime/python` `znagent` distribution, installed package `zn_agent`, `zn-resident` entrypoint | M1 active packaged path complete |
| Runtime construction | ZN config + ZN cognitive resources; no production `LegacyAIAgentWorkerFactory` / `run_agent.AIAgent` | Owned |
| Terminal/body | local process + PTY path is ZN-owned; completion-race cleanup covered | Owned for active local path |
| World/web sense | ZN-owned Tavily/Exa/Firecrawl resource layer + URL safety | Owned for active web path |
| Channels | resident-owned channel lifecycle; Telegram first transport; inbound media supported; outbound local-file policy exists | Owned framework, media egress transport still partial |
| Electron main | independent `zn-main.ts` owns window, runtime activation, resident/update IPC, single instance and protocol | M4 complete |
| Preload | independent `zn-preload.ts` exposes only intentional ZN bridge | M4 complete |
| Protocol | ZN-owned `zn://` parser/routing in active app | M4 complete |
| Renderer | independent React `ZnWorkbench`; no active `ContribController` shell | M5 owned foundation active |
| Workbench ↔ resident | resident-backed durable work/thread history, workspace association, contextual file/diff/terminal artifacts, provider/settings editing and active work progress are implemented | M5/M6 materially advanced; M6 still partial |
| Desktop package metadata | `apps/desktop/package.json` identifies `zn-desktop` / `ZN` and the ZN repository | Formal identity owned |
| Formal builder | ZN builder registers only `zn://`, includes the independent runtime and excludes inherited install/bootstrap resources | Formal identity owned |
| Formal installers | Linux x86_64, Windows x64 and macOS arm64 artifact shape/runtime identity verified; Linux amd64 deb also verified on a fresh Ubuntu installation | M7 artifact shape verified; M8 in progress |

Important distinction: inactive inherited source can remain as a reference quarry during migration. **Active product control-plane independence does not mean the repository has already been cosmetically purged of all inherited files.**

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

Communication channels connect at the resident I/O boundary and feed the same resident event loop.

The Desktop can disappear and the Resident remains valid.

Models can disappear and the Resident remains valid.

Individual providers, senses, tools and channels can be replaced without changing ZN's identity.

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
├── Communication organs
└── External cognitive resources
```

Implementation may be modular. Do not turn every concern into its own planner/manager agent.

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
→ ZN evaluates against current Situation/evidence
→ integrate, reject, probe further or act
```

### 5.4 Zero-model operation remains meaningful

Without external models ZN must continue to support:

- life pulses;
- persistent identity/state;
- body sensing;
- filesystem/process/Git observation;
- native investigation;
- memory recall;
- Will/attention evolution;
- world/visual sensing when locally available;
- deterministic/local capabilities;
- explicit “external cognition unavailable” outcomes when genuinely needed.

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

Failed movement returns as evidence. It is not silently treated as success and should not produce an uncontrolled retry loop.

### 6.1 ZN-owned adapter rule

The final resident may expose interfaces conceptually like:

```text
zn.body.files
zn.body.process
zn.body.terminal
zn.senses.web
zn.senses.visual
zn.senses.browser
```

Adapted mature implementation may live behind them. Active ZN code must not cross back into inherited product-level control planes to obtain the capability.

### 6.2 Terminal

Mature process/PTY/platform handling is valuable and should be source-extracted, not discarded.

The active local terminal path is now ZN-owned, including foreground/background processes, interactive PTY sessions, stdin/resize, platform cleanup and completed-session reclamation.

Optional Docker/SSH/cloud backends should be extracted only when ZN has a concrete body use; do not restore inherited gateway/session ownership to obtain them.

### 6.3 Web/world sensing

`NativeWorldSense` owns what ZN follows, sampling rhythm, durable observations and interpretation of change.

The web provider is replaceable transport:

```text
WorldSense
→ ZN WebResource interface
→ concrete search/extract provider
→ structured observation
→ nervous system
```

The active path is already ZN-owned. Additional providers remain demand-driven.

### 6.4 Vision

Visual sensing remains resident-owned. Raw pixels should not become long-lived memory by default. Compact structural evidence can persist and influence attention.

Screen-capture failure, missing permission or headless execution is a sensory failure, not a resident-death condition.

---

## 7. Nervous system, memory, Will and learning

`PersistentNervousSystem` and related reconsolidation/transfer machinery are the lived-memory substrate, not a transcript database.

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

Will must not become an ever-growing planner/task database. It remains a compact durable mechanism for what matters now and what should continue receiving attention.

---

## 8. External cognitive resources and integrations

### 8.1 Provider boundary

ZN owns a resource boundary that can support multiple external brains without making any one SDK or agent the owner:

```text
CognitionRequest
    ↓
CognitiveResourceRouter
    ↓
CognitiveResource
    ├── OpenAI-compatible providers
    ├── Anthropic
    ├── Gemini
    ├── local model
    └── future resources
    ↓
CognitiveIncrement
```

Providers expose bounded invocation plus capability/availability/cost/latency/reliability information where useful.

### 8.2 Current provider ownership

The active runtime has removed `LegacyAIAgentWorkerFactory` and no longer constructs `run_agent.AIAgent`. OpenAI-compatible, Anthropic and Gemini families are available through ZN-owned resource adapters.

Further extraction should preserve the same rule:

1. identify the concrete mature mechanism needed;
2. isolate it from inherited orchestration;
3. adapt it to the ZN resource contract;
4. use ZN configuration/credentials;
5. test it directly;
6. switch the active caller;
7. keep the resident as evaluator/decision maker.

### 8.3 Communication channels

Telegram, Discord, Slack, WhatsApp, Signal and future systems are communication organs, not new agent identities.

Target invariant:

```text
platform SDK/webhook/socket
→ ZN ChannelAdapter
→ normalized ChannelEvent
→ durable resident ingress
→ SAME resident Situation/Thought/action loop
→ durable outcome
→ ZN ChannelMessage/Delivery
→ selected platform adapter
```

The channel framework and Telegram first transport are active. Additional channels should reuse that contract rather than resurrecting the inherited gateway.

### 8.4 Outbound local media

An arbitrary local path is not permission to upload a file.

Before any channel adapter sends a local file:

```text
resident nominates artifact/path
→ OutboundMediaPathPolicy
→ resolve real file + authorized ZN root
→ reject traversal/symlink escape/non-file/empty/oversize as applicable
→ only then platform media transport
```

The generic authorization policy exists. Telegram outbound media transport remains to be wired through it.

---

## 9. ZN Desktop: independent content-first workbench

### 9.1 UI ownership rule

ZN will not ship the inherited UI under a ZN theme/layout.

The active ZN renderer no longer mounts `ContribController`. Inherited UI source remains reference material while the ZN workbench is completed.

The product hierarchy is inspired by the clarity of modern conversation/workbench interfaces:

- conversation/work is the primary surface;
- navigation/history is calm and predictable;
- advanced tools appear contextually instead of dominating the screen;
- artifacts/results can expand beside work when useful;
- there is one clear composer/input area;
- visual hierarchy is minimal and content-first;
- the product does not open as an IDE with multiple permanent technical panes.

This is interaction inspiration, not a copy of another product's branding/assets/exact styling.

### 9.2 Default information architecture

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

Exact pixels may evolve. The hierarchy should not.

### 9.3 Product surfaces

1. **Home / new work** — entry composer, recent work, relevant resident availability.
2. **Conversation / work thread** — user ↔ ZN interaction, ongoing state, compact body/resource activity, contextual artifacts.
3. **Artifact/context panel** — optional files, rendered artifacts, diffs, structured results and resident detail.
4. **Workspaces/projects** — local folder/project association; files/terminal remain contextual tools.
5. **Resident view** — lightweight observability into the same subject, not a second agent manager.
6. **Settings** — models/providers, credentials, resident/autostart, appearance, updates and integration toggles.

### 9.4 Current M5/M6 foundation

The active `ZnWorkbench` / resident loop already provides:

- independent React renderer root;
- New work, Recent/Search and resident-backed work/thread continuity;
- real resident-backed workspace/folder association;
- central thread and composer;
- resident task submission/status/context and durable active `WorkRun` progress;
- contextual resident-backed file/diff/terminal artifact presentation;
- resident-owned provider settings and secure credential-reference editing with hot cognition reconfiguration;
- settings and update controls;
- bounded browser-side convenience cache that is not authoritative history;
- safe/inert deep-link notice.

Still required before calling M5/M6 complete:

- browser interaction only after a clean ZN-owned resident body/sense seam exists;
- richer ongoing progress/activity presentation where product value justifies it;
- broader artifact rendering only for concrete produced outputs;
- final visual assets, accessibility and keyboard behavior.

### 9.5 Terminal/files/tools UX

ZN is not primarily an IDE.

Default behavior:

- files open contextually;
- terminal opens as an explicit contextual panel/drawer/work surface;
- diffs/review appear when work produces them;
- hidden tools do not occupy permanent screen real estate;
- advanced users may later pin/arrange surfaces, but that is not the first-run layout.

---

## 10. ZN Electron process architecture

The active desktop main process now starts from ZN code directly:

```text
ZN Electron main
→ establish ZN single-instance + zn:// handling
→ locate/materialize packaged ZN runtime
→ connect/start resident
→ register ZN IPC
→ create ZN window
→ load ZN renderer
→ manage ZN updates
```

The previous transitional pattern `zn-main → inherited main.ts` has been removed from the active path.

### 10.1 ZN preload

The active preload exposes only intentional ZN APIs through `window.znDesktop` and does not import inherited preload code.

The bridge can grow only where the ZN workbench has a concrete need, conceptually including resident, files, system, workspaces, updates and shell operations.

### 10.2 Protocol

Formal product protocol:

```text
zn://
```

The active Electron app parses/routes `zn://`. Formal installer/builder metadata registers only `zn://`; inherited `hermes` protocol registration has been removed from the formal ZN package path.

### 10.3 Backend relationship

Electron does not need a hidden inherited dashboard/backend product to make ZN function.

Mature backend capabilities may be extracted or exposed behind a ZN-owned local service. The old product server must not become the real desktop backend.

---

## 11. ZN-owned Python/runtime package

### 11.1 Active distribution identity

The active packaged resident distribution is:

```text
Python distribution: znagent
Python package:      zn_agent
resident entrypoint: zn-resident
```

`runtime/python/pyproject.toml` is the active packaged-runtime project. The repository-root inherited distribution metadata is not used as the packaged resident and remains migration/reference debt.

A future root topology cleanup may consolidate distribution metadata, but it must not regress runtime ownership or trigger a mass rename before higher-value product seams are finished.

### 11.2 Runtime content

The packaged resident runtime contains only what ZN needs:

```text
portable CPython
+ ZN resident/core package
+ selected ZN provider/integration adapters
+ exact runtime dependencies
+ required runtime data
+ runtime.json
```

It must not require `hermes_cli/main.py` as a validity condition. Current staging explicitly rejects `hermes_cli` in the packaged backend root.

### 11.3 Versioned runtime directories

Keep the versioned-runtime model:

```text
<ZN_HOME>/runtime/<runtime_id>/
```

Runtime N and N+1 may coexist while the resident transitions safely. Persistent identity/state lives outside immutable runtime directories.

---

## 12. Persistent home and configuration

ZN owns its persistent home.

Current/default direction:

```text
Windows: %LOCALAPPDATA%/znagent
macOS:   OS-native ZN application support path when finalized
Linux:   ~/.local/share/znagent or ~/.znagent during migration
```

Migration may preserve current `~/.znagent` semantics initially. Formal platform paths should eventually be explicit and tested.

Persistent categories should be separated:

```text
ZN_HOME/
├── identity / kernel state
├── memory / nervous data
├── work / artifacts
├── config
├── credential metadata / secure-store references
├── channels/
├── runtime/
├── logs/
└── updates/
```

Model credentials and user secrets must use appropriate secure storage where available and must not leak into logs/state snapshots.

No final ZN path should depend on `HERMES_HOME`.

---

## 13. Resident process, runtime identity and autostart

Core principle:

```text
Resident service = life/process continuity
Electron = face/client
```

Electron reconnects to an existing resident endpoint or starts the resident if needed. Closing the desktop disconnects the UI; it does not define resident identity.

Retain/complete:

- reconnectable local endpoint;
- process-level `runtime_id` and Python identity;
- versioned runtime materialization;
- OS-login autostart;
- same ZN home across runtime upgrades;
- conservative N → N+1 handoff.

### 13.1 Safe N → N+1 handoff

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

### 14.2 Builder/package identity

Formal package metadata must be consistently ZN-owned:

```text
productName: ZN
appId:       ai.zn.desktop  # unless deliberately changed
protocol:    zn
artifact:    ZN-<version>-<os>-<arch>...
```

`apps/desktop/package.json` itself is now ZN-owned; the formal builder also registers only `zn://`.

Current release evidence/debt is explicit:

- formal package/repository/product/app/executable/artifact identity is ZN-owned;
- formal package and builder protocol registration is `zn` only;
- real Linux AppImage/deb/rpm, Windows NSIS/MSI and macOS arm64 DMG/ZIP payloads preserve ZN identity and an independently bootable embedded resident;
- Linux amd64 deb has additionally survived a fresh Ubuntu installation with embedded zero-model resident boot;
- OS-login autostart continuity, N → N+1 handoff, equivalent intended-platform clean installs and signing/notarization remain separate M8/release gates.

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

Client behavior must not depend on which ZN-controlled object-storage/CDN provider serves it.

Release order:

```text
build verified self-contained ZN installers
→ publish immutable versioned assets
→ optionally create archival GitHub Release
→ publish/replace stable.json LAST
```

`stable.json` is the mutable pointer. Versioned binaries are immutable.

### 14.4 Integrity/signing

Hash verification is useful but is not independent signing.

Final hardening should include:

- artifact size verification;
- SHA-256 verification;
- platform code signing where operationally available;
- macOS notarization when configured;
- later signed release metadata if a durable public-key scheme is introduced.

Do not call hashes “signature verification.”

---

## 15. Safety without turning ZN into a policy-agent framework

Safety belongs in concrete body/resource/channel boundaries and product UX, not in a giant prompt constitution that replaces the organism loop.

Examples:

- explicit destructive filesystem operations;
- credential handling boundaries;
- scoped browser/network permissions;
- platform screen/mic/camera permission surfaces;
- outbound local-file authorization before channel upload;
- URL/network target safety where transport reaches arbitrary URLs;
- update integrity checks;
- bounded resource/time usage;
- reversible operations and visible failures where practical.

The development priority remains the resident organism and owned product architecture. Do not derail the project into a large governance subsystem before the core product works.

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
- world/vision adaptive attention;
- external cognition remaining bounded;
- PTY/process lifecycle correctness;
- channel ingress/delivery idempotency and restart behavior.

### 16.2 Ownership-boundary tests

The active path must be guarded against regression:

```text
agent/kernel must not import hermes_cli
agent/kernel must not import run_agent
ZN runtime distribution must identify as ZN and boot zn_agent
packaged runtime must reject inherited CLI content
ZN desktop main must not import inherited main.ts
ZN preload must not import inherited preload.ts
ZN renderer root must not import/render ContribController
formal builder must not register hermes://
formal package metadata must not identify product as Hermes
```

These active/formal ownership boundaries are now protected on the implemented package path. M8 continuity evidence remains a separate release gate and must not be inferred from package-shape tests.

### 16.3 Desktop behavior tests

Build tests around ZN behavior, not inherited UI snapshots:

- first launch/reconnect;
- new work/thread;
- send/receive resident work;
- model unavailable state;
- contextual activity rendering;
- artifact panel behavior;
- workspace association;
- settings/provider configuration;
- `zn://` handling;
- app close/resident continuity;
- update ready/apply flows.

### 16.4 Release tests

Formal release gates eventually include:

- package metadata is ZN-only;
- installer contains ZN runtime manifest;
- bundled Python imports only intended ZN runtime entrypoints;
- clean-machine launch;
- no source checkout/system Python dependency;
- N → N+1 busy/idle handoff;
- autostart after login;
- public update-channel reachability.

---

## 17. Target repository topology

Final active product should resemble:

```text
znagent/
├── ZN.md
├── pyproject.toml                # eventual ZN root distribution/topology
├── zn_agent/                     # eventual physical ZN Python namespace
│   ├── core/
│   ├── cognition/
│   ├── memory/
│   ├── body/
│   ├── senses/
│   ├── integrations/
│   ├── runtime/
│   └── config/
├── apps/
│   └── desktop/
│       ├── electron/
│       ├── src/
│       ├── assets/
│       ├── scripts/
│       └── package.json
├── runtime/python/               # current independent runtime packaging seam; may evolve
├── tests/
├── docs/
└── .github/workflows/
```

The existing `agent/kernel/` ZN implementation does not need to be mechanically moved immediately. Current `runtime/python` already packages it under installed `zn_agent.core` ownership. Namespace/topology cleanup is lower priority than product completeness and formal package ownership.

Reference Hermes source should ultimately live outside the active product tree, preferably `upstream/hermes` plus retained license/provenance, and never be a production import.

---

## 18. Full migration and product landing plan

This is the route to a complete independently maintainable ZN product.

### M0 — Blueprint reset and freeze wrong-direction expansion

Status: **COMPLETE**.

Established this blueprint, ownership rules, source-extraction policy and the rule that inherited package polish cannot define ZN architecture.

### M1 — Independently packageable ZN Python resident runtime

Status: **COMPLETE for the active packaged resident path**.

Delivered:

- independent `runtime/python` distribution metadata;
- `zn_agent` installed package boundary;
- `zn-resident` entrypoint;
- ZN config/resource runtime construction;
- zero-model resident boot;
- packaged-runtime staging/verification without inherited CLI;
- isolated CI install/smoke.

Remaining later topology cleanup (root distribution identity/physical namespace location) does not invalidate the active packaged-runtime ownership seam.

### M2 — ZN-native bounded provider cognition

Status: **COMPLETE for active main provider families; selective extraction continues**.

Production resident cognition no longer constructs `run_agent.AIAgent`. OpenAI-compatible, Anthropic and Gemini resource paths are ZN-owned. Additional provider-specific mechanisms remain demand-driven.

### M3 — ZN-owned body/sense infrastructure

Status: **COMPLETE for active local terminal + web paths**.

Local process/PTTY and active web search/extract paths are ZN-owned. Optional terminal backends, browser automation and extra web providers are future concrete capability work, not blockers to ownership.

### M4 — Independent Electron main + preload foundation

Status: **COMPLETE**.

Delivered:

- independent ZN main process;
- independent ZN preload;
- ZN BrowserWindow lifecycle;
- ZN resident/update IPC registration;
- ZN single-instance handling;
- ZN `zn://` deep-link parsing/routing;
- independent active renderer document/bundle boundary;
- ownership regression tests.

Exit condition is satisfied: active Electron app launches the ZN renderer and connects to resident without importing inherited main/preload.

### M5 — Content-first ZN workbench

Status: **IN PROGRESS; core owned surfaces materially advanced**.

Already delivered:

- independent React renderer root;
- resident-backed work/thread history;
- real workspace/folder association;
- central thread/composer and resident progress/status;
- contextual file/diff/terminal artifacts;
- resident-owned provider/credential settings integration;
- settings/update surface;
- ZN-owned styles/shell.

Remaining before M5 completion:

- final information/visual polish;
- accessibility/keyboard behavior;
- broader contextual artifact/tool presentation only where concrete product output needs it;
- browser surface only after a clean resident-owned browser body/sense seam exists.

### M6 — End-to-end resident work + artifacts

Status: **PARTIAL / IN PROGRESS**.

Already connected:

- renderer → ZN preload → resident task submission;
- durable resident work/thread identity/history;
- resident-backed workspace association;
- durable active `WorkRun` identity and resident-derived ongoing progress;
- contextual file/diff/terminal artifact presentation;
- provider/settings editing and hot cognition reconfiguration;
- resident status/self inspection and update controls.

Still required:

- richer ongoing progress/activity delivery where needed;
- broader artifact production/presentation for concrete outputs;
- contextual browser invocation after a ZN-owned browser seam exists;
- final product polish around the owned work loop.

### M7 — Formal packaging around the owned product

Status: **ARTIFACT SHAPE VERIFIED for the currently exercised Linux x86_64, Windows x64 and macOS arm64 targets**.

Delivered/verified:

- `apps/desktop/package.json` is ZN-owned;
- formal builder registers only `zn://`;
- formal packages use ZN product/app/executable/artifact identity;
- package includes the independent ZN main/preload/renderer and self-contained `zn_agent` runtime;
- versioned runtime manifest and ZN-only runtime verification are preserved;
- real Linux AppImage/deb/rpm, Windows NSIS/MSI and macOS arm64 DMG/ZIP payloads preserve ZN identity and zero-model resident boot.

This closes current artifact-shape ownership evidence, not full release readiness. Clean-machine/continuity, additional intended architectures and signing/notarization remain later gates.

### M8 — Clean-machine and continuity validation

Status: **IN PROGRESS; Linux amd64 deb fresh-install resident boot verified**.

Already verified:

1. a Linux amd64 deb can cross an artifact-only handoff to a fresh Ubuntu 24.04 runner with no repository checkout;
2. that package installs under `/opt/ZN` with ZN desktop/protocol identity;
3. its embedded portable Python / `zn_agent` runtime boots the resident zero-model without source/system Python.

Still validate as separate gates:

1. OS-login autostart and graceful service stop/restart continuity;
2. close/reopen desktop while resident continuity remains valid where not already behavior-covered;
3. N → N+1 while resident busy — no interruption;
4. N → N+1 while idle — clean handoff;
5. same ZN identity/state after upgrade;
6. Windows/macOS clean installation for the intended release matrix;
7. public update asset reachability without private source credentials;
8. signing/notarization when operationally configured.

### M9 — Product completeness and hardening

Status: **LATER**.

After owned end-to-end product works:

- provider/account setup polish;
- browser integration;
- more messaging integrations;
- voice if desired;
- richer artifacts/workspaces;
- performance/resource work;
- secure secret-storage review;
- signing/notarization/release hardening;
- accessibility;
- crash recovery/diagnostics;
- selective mature features only where they improve ZN.

### M10 — Repository migration and formal `main` promotion

Status: **LATER; `main` remains untouched**.

Prerequisites:

- owned runtime;
- owned desktop main/preload/renderer;
- owned package/release artifacts;
- clean-machine verification;
- reasonable CI coverage;
- applicable provenance/license preserved.

Then:

1. preserve reference Hermes state in `upstream/hermes` or equivalent archival reference;
2. remove inactive inherited product code from the ZN product branch when no longer needed;
3. update remaining repository documentation/branding to ZN;
4. intentionally promote the verified ZN product to `main`;
5. keep `dev/zn-agent` as the development branch.

Do not perform M10 early merely for cosmetic cleanliness.

---

## 19. Product completion criteria

ZN is not “done” merely because kernel tests pass or an installer exists.

A credible first complete product release should satisfy:

### Identity/life

- persistent identity/state survives desktop restart and OS restart;
- resident is not owned by an external model session;
- zero-model resident boot works.

### Cognition

- native investigation/body actions work;
- external models are bounded replaceable resources;
- at least one production provider path is ZN-native;
- model output is evaluated/integrated by ZN rather than treated as automatic truth/action.

### Body/senses

- files/process/Git/terminal active paths are ZN-owned;
- world sensing is ZN-owned;
- visual failure does not kill resident;
- body results feed back into Situation/Thought.

### Memory/learning

- lived state persists;
- reconsolidation can correct stale predictions;
- transfer requires current evidence;
- learning does not create a permanent skill for every success.

### Channels

- channel transports feed the same resident identity/event loop;
- durable ingress/delivery survives restart/replay;
- local-file media egress is authorized before upload.

### Desktop

- independent ZN main/preload/renderer;
- content-first workbench hierarchy;
- conversation/work primary;
- files/terminal/artifacts contextual;
- settings/provider management usable;
- desktop lifetime does not define resident identity.

### Packaging/update

- installer has ZN-only product identity;
- clean machine needs no Hermes/source/system Python;
- versioned runtime is self-contained;
- autostart works;
- safe runtime handoff works;
- stable update channel works;
- public update assets need no source-repo credentials.

### Repository ownership

- final active product has no runtime dependency on inherited product modules;
- provenance/license retained;
- `main` represents ZN after intentional M10 promotion.

---

## 20. CI and cost control

Normal development CI stays cheap.

Current/default dev checks:

- locked repository test environment;
- isolated install of active ZN runtime distribution;
- zero-model resident smoke;
- focused kernel tests;
- TypeScript typecheck for active desktop;
- independent ZN bundle smoke;
- ownership/runtime/update contract tests.

Expensive checks:

- multi-OS installers;
- clean-machine VM tests;
- signing/notarization;
- large E2E matrices.

These run only when a release milestone needs them, through explicit workflow dispatch, release candidates/tags or deliberately chosen paths.

---

## 21. Architecture traps — prohibited directions

1. Do not make an external model the owner of the main loop.
2. Do not feed all memory to a model on every interaction.
3. Do not create a new skill for every successful experience.
4. Do not treat tools/files/processes/channels as cognitive personalities.
5. Do not make old schemas automatically true; current reality can correct them.
6. Do not turn Will into an ever-growing planner/task database.
7. Do not make idle reflection a hidden self-prompt token loop.
8. Do not equate model success with ZN accepting/completing a task.
9. Do not make Electron lifetime equal resident lifetime.
10. Do not interrupt active resident work merely to activate a new runtime.
11. Do not allow cross-context association to become action without present evidence.
12. Do not create another hidden private-repository bootstrap dependency.
13. Do not package the inherited Python distribution and call it the ZN runtime.
14. Do not launch inherited Electron main from a ZN wrapper as the final desktop.
15. Do not import inherited preload from ZN preload.
16. Do not render inherited `ContribController`/shell as the active ZN UI.
17. Do not register `hermes://` in a formal ZN installer.
18. Do not preserve Hermes package/app metadata in formal ZN artifacts.
19. Do not deepen new ZN dependencies on `hermes_cli`, `run_agent`, inherited `tools.*` or old gateway control planes.
20. Do not rewrite mature mechanisms merely for cosmetic originality; extract and own useful engineering.
21. Do not automatically merge a reference Hermes branch into ZN.
22. Do not publish `stable.json` before immutable assets exist.
23. Do not turn organism-building primarily into policy/governance infrastructure.
24. Do not modify `main` before M10 prerequisites are deliberately met.
25. Do not let code invent a new product direction absent from this blueprint.
26. Do not interpret an arbitrary local filesystem path as authorization for channel upload.
27. Do not treat a separate builder override as sufficient formal product ownership while `package.json` still identifies the inherited product.

---

## 22. Immediate next development target

The ownership migration has closed the current M7 artifact-shape exercise and entered M8 continuity validation. The immediate target is now:

**prove OS-login resident continuity on an actually installed ZN package, then validate N → N+1 application/runtime/resident handoff as a separate gate.**

Concrete order:

1. do not rebuild already-proven installer/artifact gates merely to recreate evidence;
2. finish the Linux installed autostart gate by repairing resident/service lifecycle defects at their source boundary, including graceful stop and lease release;
3. after autostart is proven, validate N → N+1 busy and idle handoff without interrupting active work or changing ZN identity/state;
4. add Windows/macOS clean-install coverage only where it provides genuinely new release evidence;
5. keep signing/notarization explicit and operational—never infer it from unsigned artifact success;
6. establish browser interaction only through a clean resident-owned body/sense seam;
7. define explicit resident artifact/message egress nomination before Telegram outbound attachment transport;
8. continue M5/M6 polish only around concrete product outputs without regressing the content-first workbench.

Do not regress by reintroducing inherited main/preload/renderer/runtime control planes to accelerate these steps.

---

## 23. Handoff instruction for future sessions

Use this as the canonical restart prompt:

> Continue `9529360-cpu/znagent` on `dev/zn-agent`. Read the current repository code first, then read `ZN.md`, `docs/ZN-IMPLEMENTATION-STATUS.md`, and `docs/ZN-SOURCE-EXTRACTION.md` completely before changing code. ZN is the only product/subject. Hermes is source reference only: inspect mature mechanisms, extract/adapt them behind ZN-owned interfaces/config/lifecycle/tests, then switch the active caller; never make Hermes the runtime, UI, desktop control plane, gateway brain or release dependency. The active packaged resident is the independent `runtime/python` `znagent` distribution booting `zn_agent.resident`; production runtime construction no longer uses `run_agent.AIAgent`. Active local terminal/PTTY and web paths are ZN-owned. The independent Electron main, preload, React workbench and `zn://` protocol are active; resident-backed work/thread/workspace/artifact/progress and provider/settings ownership are materially implemented. Formal package identity is ZN-owned, formal builder protocol is `zn` only, and real Linux/Windows/macOS artifacts preserve the self-contained ZN runtime. M8 has started: Linux amd64 deb fresh installation and embedded zero-model resident boot are proven. Current priority is to finish installed OS-login autostart by fixing graceful resident stop/lease-release lifecycle at source, then validate N → N+1 busy/idle runtime continuity as a separate gate. Preserve zero-model organism behavior, CI cost discipline and `main` untouched until M10.

---

## 24. Provenance and attribution

This repository started from Hermes Agent source and will continue to study/adapt mature engineering where useful.

Preserve applicable upstream license, copyright and attribution requirements for reused implementation.

Provenance does not imply product dependence.

ZN's identity, resident architecture, UI, runtime package, distribution lifecycle, data model and future maintenance belong to ZN.