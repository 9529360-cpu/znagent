# ZN Agent

> Active development branch: `dev/zn-agent`
>
> This file is the primary architecture/development handoff for ZN. Read current repository code first. If implementation and this document disagree, code is authoritative and this file should be corrected.

## 1. Product definition

ZN is being built as a long-lived resident digital subject that lives on a computer.

The central inversion is:

**ZN uses models. Models do not own ZN.**

GPT, Claude, Gemini, DeepSeek, local models, search systems, browsers, code interpreters and future cognitive systems are replaceable resources. They are not the holder of ZN's identity, memory, Will or continuity.

For this project, "alive" means persistent computational continuity of self, state, perception, intention, thought, action, experience and adaptation even when no chat session or external model is active. It is not a claim of biological consciousness.

Product ownership:

- ZN is the subject.
- Models are bounded cognitive resources ZN may consult.
- Tools are ways ZN's body can affect the computer/world.
- Memory is lived experience that changes the resident itself.
- Code is part of ZN's computational body.
- Electron/Desktop is a face and control surface, not the owner of ZN's life.
- ZN's own release infrastructure owns installation and updates.

Disconnecting every external model must not erase ZN's identity or stop resident state from existing.

## 2. Hermes boundary: reference, never control plane

The repository began from uploaded Hermes Agent source because mature solved engineering should be studied and reused instead of rewritten for cosmetic originality.

Hermes is an inherited/reference implementation. It is **not** the product owner or an upstream runtime dependency.

Correct reuse pattern:

```text
mature solved engineering problem
→ inspect inherited/reference implementation
→ keep/adapt the useful mechanism
→ move ownership into ZN
→ maintain and publish from ZN
```

Incorrect pattern:

```text
Hermes already has a bootstrap/update/runtime channel
→ point ZN at Hermes forever
→ Hermes changes become ZN changes
```

Hard ownership rules:

- ZN artifacts are built from `9529360-cpu/znagent`.
- A ZN commit SHA must never be resolved against the Hermes repository.
- ZN install/bootstrap must not require `NousResearch/hermes-agent` to be online.
- ZN updates must not track Hermes releases.
- A clean user machine must not require an existing Hermes checkout.
- The private ZN source repository must not be a credentialless client update dependency.
- New product-facing IPC/RPC/update surfaces use ZN ownership/namespaces.
- Inherited Hermes internals may remain while useful, but they are infrastructure/debt rather than product authority.
- Provider integrations, Telegram/WhatsApp and mature desktop pieces may remain where deliberately adopted and maintained by ZN.
- Unused inherited product code should be removed gradually.

### 2.1 Branch topology

Desired topology:

```text
main              = formal ZN release/product branch
dev/zn-agent      = active ZN development branch
upstream/hermes   = reference mirror of NousResearch/hermes-agent
```

`upstream/hermes` is only for diffing and borrowing useful ideas. It may be periodically force-synchronized from upstream, but it must never auto-merge into ZN.

Current reality is transitional: `main` still contains the original Hermes-derived snapshot while `dev/zn-agent` contains the ZN product work. Do not promote or modify `main` until the active release path is deliberately verified and the branch migration is intentionally executed.

## 3. Organism-first architecture

### 3.1 Build the organism before large policy frameworks

Current priority remains the resident body, senses, nervous system, Situation, Thought, Will, action and learning loop. Do not turn this phase into a large prompt-policy/permission/governance project.

Capability safety can be strengthened without reverting ZN to a prompt-governed LLM-centric agent.

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

### 3.3 Models provide bounded cognitive increments

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
 native ZN judgment/integration
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
→ form a reusable procedure/habit only when repeated and stable
```

Executable body capabilities and learned competence are separate concepts.

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

A `PROCESSING` event remains visible across pulses so unfinished matters continue instead of cognitively restarting every heartbeat.

The production constructor `build_resident_runtime_from_existing_stack()` returns `WorldAwareTransferResidentRuntime`, so situated intention, world sensing, transfer and reconsolidation are part of the real resident runtime rather than detached experiments.

## 5. Body, nervous system, Will and learning

`NativeBody` represents ZN's computational body. Files, terminal operations, Git, processes and host sensing are body movements/senses, not separate cognitive skills.

```text
Thought
→ NativeActionIntent
→ Body
→ BodyActionResult
→ Situation / nervous experience
→ Thought
```

Failed movement returns as evidence instead of being treated as success or blindly retried.

`PersistentNervousSystem` plus reality-aware adaptation/transfer is the lived-memory substrate. It is not a transcript database. Neural traces are left by perception, thought, action and outcome; repetition strengthens traces, co-active traces form links and recall can spread through those links.

Repeated lived structure can consolidate into structured schema traces. Schemas are predictions, not eternal truth:

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

Cross-context transfer never directly becomes action:

```text
cross-context activation
→ Will candidate may seed
→ current Situation/body independently tests applicability
→ unsupported candidate remains frozen
→ repeated present support raises maturity
→ matured candidate becomes an intention probe
```

Will keeps one durable candidate slot rather than an ever-growing plan/task list. Transfer integrates multiple independent source paths; consensus can strengthen a candidate, while conflict/prediction error delays commitment and keeps attention open.

Outcome plasticity is relation-specific: supported relations strengthen contributing paths, contradicted relations weaken target-side applicability, and probe execution failure does not automatically erase source truth.

## 6. Evidence-driven native attention rhythm

The old transfer-attention development target is complete and must not be reimplemented from stale notes.

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

The relevant kernel tests run with zero model calls.

## 7. World, vision and reflection

`AdaptiveWorldSense` keeps durable world focuses, persists observation rhythm and produces structured world-change evidence. Stable focuses back off; relevant uncertainty can increase sampling.

Visual sensing is owned by the long-lived resident service, not the Electron window. `NativeVisualSense` keeps compact structural signatures rather than persisting raw screenshots. Headless/capture/permission failures must not kill resident life.

When idle, ZN can perform low-frequency native association/reflection without creating a hidden self-prompt/token loop. Real events and open impasses have higher priority.

## 8. Resident process, runtime identity and autostart

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

The resident endpoint also reports process-level runtime identity:

```text
runtime_id
python
```

This metadata belongs to process/body lifecycle, not SelfModel or neural memory. A packaged desktop can therefore distinguish "the same persistent ZN is currently running on runtime N" from "the installed desktop wants runtime N+1" without polluting the cognition model.

When `ZN_RUNTIME_ID` is unavailable (notably an OS-login autostart process), the resident derives its runtime ID from the nearest valid ZN `runtime.json` above `sys.executable`. This keeps runtime identity accurate across login/startup boundaries.

## 9. ZN-owned packaged runtime

The old clean-machine gap was real: inherited desktop bootstrap could fetch/install Hermes while packaged Electron did not contain the ZN Python resident. That active path has been replaced by a ZN-owned packaged runtime.

Release build:

```text
ZN release job
→ install portable CPython 3.11 with pinned uv
→ export locked project dependencies from uv.lock
→ install dependencies into portable Python
→ install current ZN project into that Python
→ verify desktop backend + agent.kernel.resident_server
→ zero-model resident smoke inside portable runtime
→ write runtime.json
→ electron-builder carries build/zn-runtime as extraResources
```

`hermes_cli` naming may still exist inside inherited desktop backend implementation; it no longer means Hermes owns the runtime. The interpreter, installed code and release payload are built from the ZN repository and carried by the ZN installer.

Packaged desktop start:

```text
<installer resources>/zn-runtime
→ validate runtime.json, platform, arch and entrypoints
→ atomically materialize to <ZN_HOME>/runtime/<runtime_id>
→ expose desired ZN_RUNTIME_ID
→ set ZN_RESIDENT_PYTHON to that interpreter
→ point inherited desktop backend seam at the same Python/site-packages
→ load mature shell infrastructure
→ start/reconnect ZN resident
→ refresh OS autostart with the actual runtime Python
```

The versioned runtime directory is deliberate: runtime N and N+1 coexist under the same persistent ZN home rather than replacing an interpreter that may still be executing.

Clean packaged launch should no longer require a Hermes checkout, a ZN source checkout, system Python that happens to import the kernel, or private GitHub source access.

### 9.1 Safe N → N+1 resident handoff

Desktop update and resident update are related but not identical. Replacing Electron does not automatically mean the already-running resident process changed interpreters.

The handoff policy is deliberately conservative:

```text
Desktop N+1 starts
→ materialize runtime N+1 beside runtime N
→ connect to existing resident if one is alive
→ refresh autostart to N+1 Python FIRST
→ compare endpoint runtime identity with desired N+1

if resident already runs N+1
  → continue

if resident runs N / legacy runtime AND current Situation has active event
  → do not restart
  → keep subject alive and working
  → bounded delayed recheck

if resident runs N / legacy runtime AND no active event
  → graceful shutdown RPC
  → wait briefly for old endpoint retirement
  → launch/reconnect with N+1 Python
  → same ZN home / same persistent state
  → verify endpoint now reports N+1
```

The desktop retry window is bounded. Closing Electron cancels only the UI-side retry timer; it does not kill a busy resident. Because N+1 autostart is installed before handoff, a later login/restart still activates the new runtime.

The status bar surfaces `runtime handoff pending` when ZN is alive on an older/legacy runtime. This is not reported as offline.

Tests protect the lower-level continuity invariants:

- N and N+1 runtime directories coexist;
- persistent files under ZN home survive runtime activation;
- active events classify the resident as busy and block immediate handoff;
- endpoint runtime identity reports the actual interpreter/runtime;
- autostart-launched portable Python can recover runtime identity from `runtime.json` without inherited environment variables.

## 10. ZN desktop and public update channel

The active ZN desktop layer owns runtime setup, resident IPC/lifecycle and update UI while still reusing mature inherited shell infrastructure.

A critical production fact is that `9529360-cpu/znagent` is private. Therefore a clean user machine must not use its unauthenticated GitHub Releases API/assets as the production update channel.

The client uses a ZN-defined public stable-channel protocol. `ZN_UPDATE_CHANNEL_URL` is baked into formal desktop builds as `ZN_DESKTOP_UPDATE_CHANNEL_URL` and must be an HTTPS URL ending in `/stable.json`.

Channel shape:

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

The client does not know or care which ZN-controlled static/CDN/object-storage provider serves that document.

Automatic install targets currently remain Windows `.exe`, macOS `.zip` app bundle and Linux `.AppImage` when running as AppImage. Deb/rpm users follow the published package path manually until a package-manager update path exists.

### 10.1 Background update preparation

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
→ reuse verified cached asset
→ platform-specific handoff
```

A failed background download remains visible as failed instead of retrying aggressively on every poll. Explicit user install can retry.

The status-bar update panel shows New, Improvements, Bug fixes and Possible impact, plus background download progress and readiness.

Installer verification is currently **hash verification**, not independent cryptographic signing. Do not call it signed-manifest verification until a real signing-key/public-key layer exists.

## 11. ZN-owned public release publisher

Formal tag publishing produces a provider-neutral static channel bundle using `apps/desktop/scripts/prepare-zn-public-channel.mjs`:

```text
public-channel/
├── stable.json
└── releases/
    └── <version>/
        ├── Windows installers
        ├── macOS installers
        └── Linux installers
```

The producer consumes per-platform release manifests, checks preferred updater artifacts, rejects unsafe asset names, verifies copied asset sizes and emits target SHA-256 metadata.

User-facing release notes are derived from conventional commit subjects since the previous `zn-v*` tag:

- `feat:` → New;
- `fix:` → Bug fixes;
- `perf:` / `refactor:` / `improve:` / `enhance:` → Improvements;
- conventional `!` breaking marker → Possible impact;
- internal `ci:`, `test:`, `docs:` and unrelated prefixes are not automatically presented as product changes.

The bundle is preserved as a GitHub Actions audit artifact and published through a generic **S3-compatible transport adapter**. Storage provider remains replaceable; the client protocol does not depend on AWS/R2/B2/etc.

Release order:

```text
package self-contained ZN desktop + runtime
→ build public-channel bundle
→ upload releases/<version>/ immutable assets
→ create/update archival GitHub Release
→ upload/replace stable.json LAST
```

`stable.json` is the only mutable pointer. Versioned assets use immutable caching; `stable.json` uses no-cache semantics.

Formal release configuration:

- repository variable `ZN_UPDATE_CHANNEL_URL` — public HTTPS `stable.json` URL baked into desktop;
- repository variable `ZN_UPDATE_S3_BUCKET`;
- optional `ZN_UPDATE_S3_ENDPOINT` for non-AWS S3-compatible storage;
- optional `ZN_UPDATE_S3_REGION`;
- secrets `ZN_UPDATE_S3_ACCESS_KEY_ID` and `ZN_UPDATE_S3_SECRET_ACCESS_KEY`;
- optional `ZN_PUBLIC_RELEASE_URL` for a human-facing public release page.

The actual bucket/domain/credentials are operational configuration and are not provisioned by source code. Do not hide missing deployment configuration by falling back to Hermes or the private source repository.

## 12. Immediate next development target

The resident kernel, transfer-attention rhythm, persistent world/vision sensing, detached resident/autostart, self-contained runtime, runtime identity/handoff, client stable-channel protocol, background updater and release-side static publisher now exist.

The next target is:

**validate the complete packaged lifecycle on real installer artifacts, then finish product/repository migration.**

Priority order:

1. Provision/configure the actual public ZN bucket/domain and point `ZN_UPDATE_CHANNEL_URL` at its `stable.json`.
2. Run the manual multi-OS release workflow and inspect the portable runtime inside Windows/macOS/Linux installer artifacts.
3. Validate a clean machine can install and boot ZN without Hermes, a source checkout or system Python.
4. Validate N → N+1 with a real running resident: active work must not be interrupted; idle handoff must switch to N+1 using the same ZN home.
5. Verify autostart points to N+1 and runtime identity remains correct after login when no desktop environment variables are inherited.
6. Confirm public assets are reachable without GitHub/source credentials and `stable.json` moves only after immutable assets exist.
7. Continue removing product-facing Hermes names/assumptions from the active desktop path.
8. Preserve applicable upstream license/attribution even as product ownership moves fully to ZN.
9. After release-path verification, preserve Hermes separately as `upstream/hermes` and intentionally promote verified ZN code to `main`.

Do not solve remaining deployment issues by introducing another hidden private-repository dependency.

## 13. CI and cost control

Normal dev CI intentionally remains cheap:

- locked Python environment;
- zero-model resident boot smoke;
- Python kernel test suite;
- Electron/TypeScript typecheck;
- focused packaged-runtime/update-channel/runtime-handoff contract tests;
- public-channel bundle producer test;
- expensive container/runtime smoke skipped on ordinary dev pushes.

Last verified development head before the runtime-handoff change in this document:

```text
85451685c4d04d9096be5b1c2a9e60eb4c6162ab
feat: publish ZN stable channel bundle

ZN Kernel / Python       success
Electron / TypeScript    success
Actions run              32533891437
```

Cost rules:

- group coherent changes into one push;
- avoid cosmetic CI reruns;
- let concurrency cancel superseded development runs;
- reserve multi-OS package/release jobs for changes that need them.

## 14. Important code map

Resident/kernel:

```text
agent/kernel/
├── body.py
├── intentional_resident.py
├── nervous_system.py
├── integrated_transfer.py
├── transfer_incubation.py
├── intention_formation.py
├── reconsolidation.py
├── schema_structure.py
├── will.py
├── investigation.py
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
│   ├── zn-resident-runtime-state.ts
│   ├── zn-release-channel.ts
│   ├── zn-release-updater.ts
│   ├── zn-preload.ts
│   ├── zn-resident-ipc.ts
│   ├── zn-resident-process.ts
│   └── zn-resident-autostart.ts
├── scripts/
│   ├── stage-zn-runtime.mjs
│   ├── prepare-zn-public-channel.mjs
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

Tests are part of the architecture specification. Restart/continuity behavior matters: resident-native behavior should not disappear merely because a process or UI restarts.

## 15. Architecture traps to avoid

1. Do not make an external model the owner of the main loop.
2. Do not feed all memory to a model on every interaction.
3. Do not create a new skill for every successful experience.
4. Do not treat tools/files/processes as cognitive skills merely because ZN can use them.
5. Do not make an old schema automatically true; current reality must be able to correct it.
6. Do not turn Will into an ever-growing plan/task list.
7. Do not make idle reflection a hidden self-prompt token loop.
8. Do not equate model success with ZN accepting/completing a task.
9. Do not make Electron window lifetime equal resident lifetime.
10. Do not interrupt active resident work merely to activate a newer packaged runtime.
11. Do not allow cross-context association to become action without present Situation evidence.
12. Do not turn one transfer success into a permanent context rule.
13. Do not collapse independent agreeing/conflicting transfer evidence into one strongest path.
14. Do not let failure in context B erase a relation correctly learned in context A.
15. Do not create a second context-policy memory store for behavior that belongs in lived neural state.
16. Do not spend this phase primarily on policy frameworks instead of the organism's core loops.
17. Do not make Hermes availability, releases, commit history or update infrastructure necessary for ZN to install, boot or update.
18. Do not make the private ZN source repository itself a client update dependency.
19. Do not rewrite mature infrastructure merely to claim originality; adopt it deliberately under ZN ownership when it solves the right problem.
20. Do not automatically merge `upstream/hermes` into ZN branches.
21. Do not publish `stable.json` before all immutable assets it references are available.

## 16. Handoff

Use this as the next-session starting instruction:

> Continue `9529360-cpu/znagent` from the latest repository state on `dev/zn-agent`. Read actual code first, then `ZN.md`; code remains authoritative. ZN is the subject/product and Hermes is only an engineering reference. Do not depend on Hermes or the private source repository as a clean-client bootstrap/update channel. The resident kernel, transfer-attention rhythm, persistent world/vision sensing, detached resident/autostart, ZN-owned packaged runtime, safe runtime identity/handoff, public stable-channel protocol, background updater and S3-compatible release publisher already exist. The next target is real packaged clean-machine/N→N+1 continuity validation, then product-facing Hermes cleanup and the intentional `main`/`upstream/hermes` migration. Preserve native zero-model paths and model-as-resource architecture. Control CI cost. Do not modify `main` until the verified promotion step.

## 17. Provenance

This repository started from Hermes Agent source and continues to reuse mature infrastructure where useful. Preserve applicable upstream license and attribution requirements.

Provenance does not imply product dependence. ZN's identity, runtime architecture, distribution lifecycle and future maintenance belong to ZN.
