# ZN Agent

> Active development branch: `dev/zn-agent`
>
> This is the primary architecture/development handoff for ZN. Read the actual repository code first. If this document and implementation ever disagree, current code is authoritative and this file must be corrected.

## 1. Product definition

ZN is being built as a long-lived resident digital subject that lives on a computer.

The central inversion is:

**ZN uses models. Models do not own ZN.**

GPT, Claude, Gemini, DeepSeek, local models, search systems, browsers, code interpreters and future cognitive systems are replaceable resources. They are not the holder of ZN's identity, memory, Will or continuity.

For this project, "alive" means persistent computational continuity of self, state, perception, intention, thought, action, experience and adaptation even when no chat session or external model is active. It is not a claim of biological consciousness.

Product-level ownership:

- ZN is the subject.
- Models are cognitive resources ZN may consult.
- Tools are ways ZN's body can affect the computer/world.
- Memory is lived experience that changes the resident itself.
- Code is part of ZN's computational body.
- Electron/Desktop is a face and control surface, not the owner of ZN's life.
- ZN's own release infrastructure owns installation and updates.

Disconnecting every external model must not erase ZN's identity or stop resident state from existing.

## 2. Hermes boundary: engineering reference, never control plane

The repository began from uploaded Hermes Agent source because mature solved engineering should be studied and reused instead of rewritten for cosmetic originality.

Hermes is an inherited/reference implementation. It is **not** the product owner or an upstream runtime dependency.

The intended reuse pattern is:

```text
mature solved engineering problem
→ inspect inherited/reference implementation
→ keep/adapt the useful mechanism
→ move ownership into ZN
→ maintain and publish from ZN
```

Not:

```text
Hermes already has a channel/runtime/updater
→ point ZN at Hermes forever
→ Hermes changes therefore become ZN changes
```

Hard ownership rules:

- ZN release artifacts are built by `9529360-cpu/znagent`.
- A ZN commit SHA must never be resolved against the Hermes repository.
- ZN install/bootstrap must not require `NousResearch/hermes-agent` to be online.
- ZN updates must not track Hermes releases.
- A clean user's machine must not require an existing Hermes checkout.
- New product-facing IPC/RPC/update surfaces use ZN ownership/namespaces.
- Inherited Hermes code may remain internally while useful, but it is implementation debt/infrastructure rather than product authority.
- Provider integrations, Telegram/WhatsApp and mature desktop pieces may remain where deliberately adopted and maintained by ZN.
- Unused inherited product code should be removed gradually.

### 2.1 Branch topology

Desired repository topology:

```text
main              = formal ZN release/product branch
dev/zn-agent      = active ZN development branch
upstream/hermes   = reference mirror of NousResearch/hermes-agent
```

`upstream/hermes` is only for diffing and borrowing useful ideas. It may be periodically force-synchronized from upstream, but it must never auto-merge into ZN.

Current reality is still transitional: `main` remains the original Hermes-derived snapshot while `dev/zn-agent` contains the ZN product work. Do not treat the desired topology as already completed.

Do not modify/promote `main` until the active ZN branch and release path are deliberately verified and the branch migration is intentionally executed.

## 3. Organism-first architecture principles

### 3.1 Build the organism before large policy frameworks

Current priority is the resident body, senses, nervous system, Situation, Thought, Will, action and learning loop.

Do not lead this phase by constructing a large prompt-policy/permission/governance layer. Capability safety can be strengthened without reverting ZN to a prompt-governed LLM-centric agent.

### 3.2 Internal modules are organs, not prompt-agents

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
└── External brain access
```

Implementation can be modular, but do not turn each concern into its own planner/manager agent.

### 3.3 External models provide bounded cognitive increments

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
 isolate exact unknown
       ↓
 external cognitive resource
       ↓
 CognitiveIncrement
       ↓
 ZN judges/integrates it
       ↓
 continue
```

A provider response is not automatically ZN's decision or task completion.

### 3.4 Learning is consolidation, not one-skill-per-success

```text
experience
→ understand/classify
→ merge into existing knowledge/capability
→ strengthen/refine a domain
→ form a procedure/habit only when repeated and stable
```

Executable body capabilities and ZN's learned competence are separate concepts.

## 4. Current resident closed loop

The resident is multi-pulse and resumable. One pulse advances one piece of cognition rather than running an arbitrary fixed number of model rounds.

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
→ native integration
→ Action / Outcome
```

A `PROCESSING` event stays visible across pulses so unfinished matters continue instead of restarting cognitively each heartbeat.

The production constructor `build_resident_runtime_from_existing_stack()` currently returns `WorldAwareTransferResidentRuntime`, so situated intention, world sensing, transfer and reconsolidation are part of the actual resident runtime rather than detached experiments.

## 5. Body, nervous system, Will and learning

### 5.1 Body

`NativeBody` represents ZN's computational body. Files, terminal operations, Git, processes and host sensing are body movements/senses, not separate cognitive skills.

```text
Thought
→ NativeActionIntent
→ Body
→ BodyActionResult
→ Situation / nervous experience
→ Thought
```

Failed body movement returns as evidence rather than being treated as success or blindly retried.

### 5.2 Persistent nervous system

`PersistentNervousSystem` plus reality-aware adaptation/transfer is the lived-memory substrate. It is not a transcript database.

Neural traces are left by perception, thought, action and outcome. Repetition strengthens traces, co-active traces form links and recall can spread through those links.

Functional affect/homeostasis currently includes dimensions such as valence, arousal, tension, curiosity, familiarity and fatigue. These are computational state dynamics, not claims of biological emotion.

### 5.3 Schema and reconsolidation

Repeated lived structure can consolidate into structured schema traces. Schemas carry relation-aware prediction profiles rather than being treated as eternal truth.

```text
lived experience
→ consolidation
→ schema/prediction
→ current body/world/vision observation
→ prediction feedback
→ support / refinement / contradiction
→ bounded confirming recheck if needed
→ reconsolidation
→ future recall and Will change
```

Compatible redundant schemas can merge while preserving source history. Conflicting schemas are not blindly collapsed.

### 5.4 Will and cross-context transfer

Transferred activation never directly becomes action:

```text
cross-context activation
→ Will candidate may seed
→ current Situation/body independently tests applicability
→ unsupported candidate remains frozen
→ repeated present support raises maturity
→ matured candidate becomes an intention probe
```

Will keeps one durable candidate slot rather than an ever-growing plan/task list.

Transfer integrates multiple independent source paths rather than selecting only one strongest path. Consensus can strengthen a candidate; conflict delays commitment and keeps attention open.

Outcome plasticity is relation-specific: supported relations strengthen contributing paths, contradicted relations weaken target-side applicability, and probe execution failure does not automatically erase source truth.

## 6. Evidence-driven native attention rhythm

The old development target around transfer-attention persistence is complete and must not be reimplemented from stale notes.

Current behavior includes:

```text
high consensus + repeated lived support
→ still require current reality support
→ mature with less redundant review churn

low consensus / source conflict / prediction error
→ matter remains open across pulses
→ commitment is delayed
→ bounded later review/re-probe
→ result reconsolidates into future behavior
```

World and visual sensing also adapt their native sampling rhythm:

- stable observations back off;
- current Thought can pull a relevant sense closer;
- relevant conflict/prediction error tightens the corresponding sense;
- unrelated conflict does not hot-sample every sensor.

The relevant tests run with zero model calls.

## 7. World, vision and endogenous reflection

### World

`AdaptiveWorldSense` keeps durable world focuses, persists observation rhythm and produces structured world-change evidence. Stable focuses back off; relevant uncertainty can increase sampling.

### Vision

Visual sensing is owned by the long-lived resident service, not the Electron window. `NativeVisualSense` retains compact structural signatures rather than persisting raw screenshots.

Headless/capture/permission failures must not kill resident life.

### Reflection

When idle, ZN can perform low-frequency native association/reflection without creating a hidden self-prompt/token loop. Real events and open impasses have higher priority.

## 8. Resident process, UI lifecycle and OS autostart

```text
Resident service = life/process continuity
Electron = face/client
```

Electron reconnects to an existing local resident endpoint or launches the detached resident if none is reachable. Closing the desktop disconnects the UI; it does not inherently stop resident life.

OS-login autostart exists in `agent/kernel/resident_autostart.py`:

- Linux: user `systemd` service;
- macOS: `LaunchAgent`;
- Windows: current-user Scheduled Task.

The startup entry pins the Python executable and ZN home used to install it. Electron refreshes that entry after the resident is reachable.

## 9. ZN-owned packaged runtime

The previous clean-machine gap was real: the inherited desktop bootstrap tried to fetch/install Hermes source, while packaged Electron did not contain the ZN Python resident.

That path is now being replaced by a ZN-owned packaged runtime.

Current release-build flow:

```text
ZN release job
→ install portable CPython 3.11 with pinned uv
→ export locked project dependencies from uv.lock
→ install dependencies into portable Python
→ install current ZN project into that Python
→ verify hermes_cli desktop backend entrypoint exists
→ verify agent.kernel.resident_server exists
→ zero-model resident smoke inside portable runtime
→ write runtime.json
→ electron-builder carries build/zn-runtime as extraResources
```

`hermes_cli` naming can still exist inside the inherited desktop backend implementation; that does not make Hermes the runtime owner. The interpreter, installed code and release payload are created from the ZN repository and carried by the ZN installer.

On packaged desktop start:

```text
<installer resources>/zn-runtime
→ validate runtime.json, platform, arch and entrypoints
→ atomically materialize to <ZN_HOME>/runtime/<runtime_id>
→ set ZN_RESIDENT_PYTHON to that interpreter
→ point inherited desktop backend seam at the same installed site-packages/Python
→ load legacy shell infrastructure
→ start/reconnect ZN resident
→ refresh OS autostart with the actual runtime Python
```

The versioned runtime directory is deliberate. An old resident may continue running from the previous runtime while the desktop updates; the new desktop can then activate the new runtime and refresh autostart without requiring the updater to replace an in-use Python executable inside the app directory.

Clean packaged launch should therefore no longer require:

- a Hermes checkout;
- a ZN source checkout;
- system Python that happens to import `agent.kernel`;
- private GitHub source access on the client machine.

Runtime materialization has a direct Electron/Vitest contract and normal development CI keeps that test cheap.

## 10. Desktop product state

The active ZN desktop layer includes:

- `electron/zn-main.ts` — packaged runtime setup before inherited main loads;
- `electron/zn-preload.ts` — `window.znDesktop` namespace;
- `electron/zn-resident-ipc.ts` — resident client IPC;
- `electron/zn-resident-process.ts` — detached resident connection/launch;
- `electron/zn-resident-autostart.ts` — OS startup refresh;
- `src/app/zn-workbench.tsx` — ZN workbench surface;
- status-bar resident/update surfaces;
- `electron-builder.zn.yml` — ZN-branded artifacts plus runtime payload.

There is still inherited Hermes branding/compatibility code elsewhere in the desktop tree. Product-facing Hermes identity should keep shrinking, while useful mature infrastructure may remain internally when deliberately adopted.

## 11. ZN update channel

A critical production fact: `9529360-cpu/znagent` is currently private. A clean user machine cannot rely on unauthenticated access to that repository's GitHub Releases API or private release assets.

Therefore the updater must not treat the private source repository as the production client channel.

The client now uses a ZN-defined public stable-channel protocol instead of GitHub's release API schema. The packaged update URL is injected at build time through repository variable `ZN_UPDATE_CHANNEL_URL` and baked as `ZN_DESKTOP_UPDATE_CHANNEL_URL`.

Formal `zn-v*` tag packaging is blocked if the public channel URL is not configured. `workflow_dispatch` packaging can still be used for internal validation without a channel.

The public endpoint is expected to return a compact document shaped like:

```json
{
  "schema": 1,
  "product": "ZN",
  "channel": "stable",
  "version": "1.2.3",
  "release_url": "https://updates.example/releases/1.2.3",
  "notes": {
    "new": ["..."],
    "improvements": ["..."],
    "fixes": ["..."],
    "impact": ["..."]
  },
  "targets": [
    {
      "platform": "windows",
      "arch": "x64",
      "name": "ZN-1.2.3-win-x64.exe",
      "url": "./releases/1.2.3/ZN-1.2.3-win-x64.exe",
      "size": 123456789,
      "sha256": "<64 hex characters>"
    }
  ]
}
```

The same document can point at any ZN-controlled public static/CDN/object-storage host. The desktop does not need to know which provider serves it.

Automatic install targets currently remain:

- Windows: `.exe`;
- macOS: `.zip` app bundle;
- Linux: `.AppImage` when running as AppImage.

Deb/rpm users can still follow the published package path manually unless a package-manager update path is added later.

### 11.1 Background preparation

The updater now treats check and install as separate phases:

```text
periodic check
→ read public stable.json
→ compare version
→ select exact platform/arch target
→ begin background download
→ stream SHA-256 while downloading
→ verify exact size + digest
→ persist verified installer under desktop userData
→ status becomes ready
→ user clicks Install
→ reuse verified cached asset; do not download again
→ platform-specific handoff
```

A failed background download stays visible as failed rather than retrying aggressively every status poll. Explicit user install can retry.

### 11.2 Release-note UI

The status-bar update surface opens a compact update panel showing the four channel categories:

- New;
- Improvements;
- Bug fixes;
- Possible impact.

While a download is active, the UI polls the local updater status on a short interval and shows progress. Normal update checks stay low-frequency.

Important terminology: installer verification is still **hash verification**, not independent cryptographic signing. SHA-256 detects corruption/tampering relative to the channel document, but a later signing-key layer is a separate security mechanism and should not be falsely described as already implemented.

## 12. Remaining distribution gap

The runtime and client-side update protocol are now ZN-owned, but one production deployment piece remains intentionally unresolved:

**the public `stable.json` endpoint and its installer asset host must actually be provisioned and published.**

Do not hide this gap by falling back to the private source repository or Hermes.

The desired production chain is:

```text
validated ZN release from main
→ package self-contained ZN desktop + versioned runtime
→ publish installer assets to ZN-controlled public release storage
→ publish stable.json last (atomic channel switch)
→ clients discover version
→ clients pre-download + hash-verify
→ UI shows notes and readiness
→ user clicks Install
→ desktop updates while resident continuity is preserved
```

Publishing `stable.json` last is important: clients must never see a version whose referenced assets are not already available.

## 13. Immediate next development target

The old transfer-attention target is complete. The old Hermes-bootstrap gap is substantially closed by the packaged runtime.

The next concrete target is now:

**finish the ZN-owned public release-channel publishing side and validate a real packaged clean-machine update cycle.**

Priority order:

1. Choose/provision the public ZN release storage/channel endpoint without exposing the private source repository.
2. Add release automation that uploads immutable installer assets first and atomically publishes `stable.json` last.
3. Supply structured release notes to that channel during formal releases.
4. Run actual Windows/macOS/Linux packaged-runtime smoke, not only source tests.
5. Validate update continuity with a resident already running from version N while desktop N+1 installs.
6. Verify autostart is refreshed to the N+1 runtime after activation without destroying resident home/state.
7. Continue removing product-facing Hermes names/assumptions from the active desktop path.
8. Preserve applicable upstream license/attribution even as product ownership moves fully to ZN.
9. After release path verification, perform the intentional branch migration: preserve Hermes reference separately and promote verified ZN code to `main`.

Do not solve the next step by silently making clients depend on another private repository API. The public channel is a product interface owned by ZN.

## 14. CI and cost control

Normal development CI intentionally remains cheap:

- locked Python environment;
- zero-model resident boot smoke;
- Python kernel test suite;
- Electron/TypeScript typecheck;
- focused packaged-runtime/update-channel contract tests;
- expensive container/runtime smoke skipped on ordinary dev pushes.

Last verified head before the update-channel change in this document:

```text
9455f3df39c01d3d1268f3daa748c537c7467639
feat: package ZN-owned desktop runtime

ZN Kernel / Python       success
Electron / TypeScript    success
Actions run              32532574923
```

Cost rules:

- group coherent changes into one push;
- avoid cosmetic CI reruns;
- let concurrency cancel superseded development runs;
- reserve multi-OS package/release jobs for changes that need them.

## 15. Important code map

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
├── resident_server.py
├── resident_autostart.py
├── provider_bridge.py
└── store.py
```

Desktop/release:

```text
apps/desktop/
├── electron-builder.zn.yml
├── electron/
│   ├── zn-main.ts
│   ├── zn-packaged-runtime.ts
│   ├── zn-release-channel.ts
│   ├── zn-release-updater.ts
│   ├── zn-preload.ts
│   ├── zn-resident-ipc.ts
│   ├── zn-resident-process.ts
│   └── zn-resident-autostart.ts
├── scripts/
│   ├── stage-zn-runtime.mjs
│   ├── bundle-electron-main.mjs
│   ├── write-build-stamp.mjs
│   └── write-zn-release-manifest.mjs
└── src/app/zn/
    ├── resident-status.tsx
    └── update-status.tsx
```

CI/release:

```text
.github/workflows/zn-ci.yml
.github/workflows/zn-release.yml
```

Tests are part of the architecture specification. Restart/continuity tests matter: resident-native behavior should not disappear merely because a process restarts.

## 16. Architecture traps to avoid

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
16. Do not make Hermes availability, releases, commit history or update infrastructure necessary for ZN to install, boot or update.
17. Do not make the private ZN source repository itself a credentialless client update dependency.
18. Do not rewrite mature infrastructure merely to claim originality; adopt it deliberately under ZN ownership when it solves the right problem.
19. Do not automatically merge `upstream/hermes` into ZN branches.
20. Do not publish a channel document before all immutable assets it references are available.

## 17. Handoff for the next development session

Use this as the starting instruction:

> Continue `9529360-cpu/znagent` from the latest repository state on `dev/zn-agent`. Read actual code first, then `ZN.md`; code remains authoritative. ZN is the subject/product and Hermes is only an upstream engineering reference. Do not depend on Hermes or the private source repository as a clean-client release/bootstrap/update channel. The resident kernel, transfer-attention rhythm, persistent visual/world sensing, detached resident/autostart and ZN-owned packaged runtime already exist. The next target is the public ZN release-channel publishing side plus a real packaged clean-machine/update-continuity validation. Preserve native zero-model paths and model-as-resource architecture. Control CI cost. Do not modify `main` until the intentional verified branch-promotion step.

## 18. Provenance

This repository started from Hermes Agent source and continues to reuse mature infrastructure where useful. Preserve applicable upstream license and attribution requirements.

Provenance does not imply product dependence. ZN's identity, runtime architecture, distribution lifecycle and future maintenance belong to ZN.
