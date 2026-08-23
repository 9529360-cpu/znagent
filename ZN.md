# ZN — Product and Engineering Contract

> Active development branch: `dev/zn-agent`
>
> This file is the current architecture contract. The full pre-evacuation blueprint is preserved at `docs/ZN-BLUEPRINT-BASELINE-2026-08-23.md` for historical context. When the baseline and this file differ, this file governs current work.

## 0. Development contract

Before changing the project, restore real repository state and inspect the active call chain. Real code and Git state outrank tests/CI; real tests/CI outrank handoff notes; handoff notes outrank chat descriptions.

Development order:

```text
inspect real repository + branch + CI
→ identify the active caller and ownership boundary
→ update ZN.md first if architecture changes
→ implement the smallest coherent ZN-owned step
→ test the active path
→ inspect diff
→ commit/push
→ verify real CI
→ synchronize status docs and .agent/HANDOFF.md
```

`main` is not modified before the explicit M10 promotion conditions are deliberately satisfied and the user explicitly requests promotion.

## 1. Product definition

ZN is the only product and the only resident subject.

**ZN uses models. Models do not own ZN.**

Models, browsers, search systems, code interpreters and future cognitive systems are replaceable resources. They do not own ZN identity, memory, Will, continuity or the main resident loop.

ZN owns:

- persistent Self and life;
- Body and Senses;
- Situation, Thought and Will;
- lived memory and learning;
- Investigation and Action;
- provider/resource boundaries;
- communication channels;
- runtime, configuration, credentials references and updates;
- desktop main/preload/renderer and product identity.

Disconnecting all external models must not erase ZN identity/state or stop native resident pulses.

## 2. Hermes boundary — physical evacuation is now mandatory

Hermes was uploaded only as a source reference. That temporary migration phase is over for `dev/zn-agent`.

### 2.1 New hard rule

The active development branch must converge to a repository tree in which Hermes product source is **not physically present** and is **not required for development, testing, build, packaging or release**.

Reference access belongs outside the active ZN tree:

```text
Git history / inherited main snapshot
or
an external/upstream reference repository
```

It must not remain as a quarry inside `dev/zn-agent`.

After the evacuation stage, the ZN development tree must not contain or depend on inherited product control planes such as:

```text
hermes_cli
run_agent
inherited agent loop modules
inherited tools package
inherited gateway / tui gateway
inherited providers/plugins product framework
inherited web/TUI product
inherited Electron renderer shell / ContribController
Hermes bootstrap/install/update scripts
Hermes package/distribution metadata
Hermes Docker/Nix product runtime
```

This is stronger than the previous rule that merely prohibited active imports.

### 2.2 Source reuse after evacuation

Mature upstream implementation may still be studied externally. Useful mechanisms may be adapted only when all of the following are true:

1. ZN has a concrete need;
2. the mechanism is understood rather than blindly copied;
3. it enters a ZN-owned namespace/interface/config/lifecycle;
4. inherited product assumptions are removed;
5. provenance/license obligations are retained;
6. ZN behavior tests cover the owned implementation;
7. no build/runtime/reference checkout dependency is introduced.

Never restore Hermes source merely because a test, import or build script breaks. Decide whether the capability belongs to ZN; if yes, extract it as ZN code, otherwise remove the obsolete caller/test.

## 3. Current evacuation checkpoint — 2026-08-23

At the start of this stage, real repository inspection found a mixed state:

### Already ZN-owned

- resident kernel behavior under the current `agent/kernel/` transitional physical path;
- packaged Python distribution `runtime/python` named `znagent`;
- installed package `zn_agent` and `zn-resident` entrypoint;
- ZN-native provider/resource, terminal, Git/file Body, web sense and channel paths used by the resident;
- independent Electron `zn-main.ts`, `zn-preload.ts`, `zn://` protocol and release/update path;
- an independent renderer implementation under `apps/desktop/src/zn/`;
- formal ZN package identity and versioned packaged runtime.

### Still inherited and therefore evacuation debt

Real inspection also found that previous documentation overstated desktop/repository separation:

- root `pyproject.toml` still describes `hermes-agent` and installs inherited Python packages/entrypoints;
- normal Python CI still creates its test environment through that root Hermes project;
- root `package.json` still identifies Hermes and includes inherited workspaces;
- root Node lock/workspace still carries inherited product dependencies;
- the actual Vite entry still reaches `src/app/zn-workbench.tsx`, which mounts inherited `ContribController`;
- `apps/desktop/index.html` still contains Hermes title/storage identifiers;
- desktop configuration still carries `@hermes/shared` and inherited aliases/development identifiers;
- the non-push container smoke still builds an inherited Hermes Dockerfile;
- old CLI/agent/tools/gateway/provider/plugin/web/TUI/source trees remain physically present.

These are current defects to remove, not accepted migration architecture.

## 4. Evacuation exit conditions

Hermes evacuation is complete only when all of these are true on `dev/zn-agent`:

### Python ownership

- physical resident core lives under a ZN namespace/path, not under the inherited product tree;
- runtime/test imports use the ZN package namespace;
- root Hermes Python distribution metadata is gone or replaced by ZN-only development metadata;
- kernel tests install/run without installing a Hermes distribution;
- ZN source cannot import inherited product roots;
- zero-model packaged resident boot remains green.

### Desktop/Node ownership

- Vite launches the independent `src/zn` renderer directly;
- active renderer does not import/render `ContribController` or inherited renderer roots;
- root workspace/package metadata is ZN-owned and contains only workspaces required by ZN;
- active desktop has no `@hermes/*` package dependency/alias;
- product HTML/runtime configuration contains no Hermes identity keys that define behavior;
- Electron typecheck/bundle/ownership tests remain green.

### Build/release ownership

- normal CI installs only ZN development/runtime dependencies;
- container smoke, if retained, builds a ZN runtime image rather than the inherited product image;
- formal release uses only ZN-owned manifests/workspaces/runtime staging;
- packaged runtime verification rejects inherited product content;
- no clean ZN build needs a Hermes checkout or source path.

### Physical tree

- inherited Hermes product source, docs, tests, setup/update scripts, web/TUI, gateway, old agent loop, old tools/providers/plugins and old runtime packaging are absent from `dev/zn-agent`;
- only required provenance/license records remain;
- `main` may continue to preserve the inherited historical snapshot until M10; that does not make it a ZN dependency.

## 5. Final ZN topology

The active tree should converge toward:

```text
znagent/
├── ZN.md
├── AGENTS.md
├── LICENSE / provenance
├── runtime/
│   └── python/
│       ├── pyproject.toml
│       └── zn_agent/
│           ├── core/
│           └── resident.py
├── apps/
│   └── desktop/
│       ├── electron/        # ZN main/preload/protocol/update/resident IPC
│       ├── src/zn/          # active independent renderer
│       ├── assets/
│       ├── scripts/
│       └── package.json
├── tests/
│   └── zn_agent/core/
├── docs/
├── .agent/
└── .github/workflows/
```

A small ZN-owned root Node manifest/lock may remain when required to provide a reproducible desktop workspace install. It must not act as a wrapper around inherited workspaces.

## 6. Resident architecture

There is one subject with modular organs:

```text
ZN
├── Self / identity
├── Body
├── Senses
├── Nervous system / lived memory
├── Situation
├── Thought
├── Will
├── Investigation
├── Action
├── Learning / reconsolidation
├── Communication organs
└── External cognitive resources
```

Normal life loop:

```text
exist
→ sense current body/world/internal state
→ Situation
→ Thought
→ maintain/form intention
→ Investigation / Action / reflection
→ observe real outcome
→ lived experience
→ learning / Will change
→ continue existing
```

External cognition is a bounded increment:

```text
specific gap
→ optional CognitiveResource
→ CognitiveIncrement
→ ZN checks against current evidence
→ integrate / reject / investigate further / act
```

Model output is never automatically fact, decision or completion proof.

## 7. Body, verification and learned competence

Files, processes, Git, terminal, browser and network sensing are Body/Senses, not extra agent personalities.

Movement success alone is not task success. Completion and positive learning require independent current-world verification appropriate to the effect.

Current engineering competence must preserve these rules:

- explicit typed or resident-proven authority before side effects;
- structured current repository/path evidence where Git state matters;
- fresh post-action verification;
- contradiction returns to Investigation;
- procedural memory may influence freshly re-formed safe choices but does not replay raw side-effect arguments;
- familiar execution never makes reality evidence optional;
- model suggestions do not create execution authority.

The existing bounded tracked exact-replacement / repository-delta / targeted Python unittest verification work must survive physical namespace migration without widening authority.

## 8. Memory and learning

Memory is lived resident change, not merely transcript/context retrieval.

```text
experience
→ resident-owned traces/relations
→ repeated compatible evidence
→ candidate tendency
→ current-reality applicability
→ bounded procedural influence
→ prediction check
→ reinforcement, inhibition or relearning
```

One success does not create a permanent skill. Contradiction must be able to weaken or inhibit stale competence. Mature resident-owned ability should survive provider replacement and full model removal.

## 9. Desktop boundary

Electron is ZN's face/work surface, not the owner of resident life.

Active architecture after evacuation:

```text
ZN Electron main
→ ZN preload / IPC
→ long-lived ZN resident
→ independent ZN renderer (`src/zn`)
```

The renderer must be content/work oriented. Files, diffs and terminal are contextual surfaces. Do not restore the inherited Contrib shell merely to obtain UI infrastructure.

Closing the desktop must not define or erase resident identity.

## 10. Runtime, data and credentials

Packaged runtime identity:

```text
Python distribution: znagent
Python package:      zn_agent
entrypoint:          zn-resident
```

Persistent identity/state belongs outside immutable runtime versions. Runtime N and N+1 may coexist during safe handoff.

Credentials/secrets must remain in appropriate secure stores/project secret infrastructure and must not be committed, written into HANDOFF, logs or ordinary resident memory.

## 11. Release/update architecture

Formal installers and update assets are ZN-only:

```text
traceable commit/tag
→ CI
→ build self-contained ZN artifacts
→ verify artifacts/runtime
→ publish immutable version assets
→ optional archival GitHub Release
→ advance stable.json LAST
```

A clean machine must not need Hermes, a source checkout, system Python, Node/npm or private source credentials.

Hashes are integrity checks, not signatures. Signing/notarization remain separate release hardening gates where applicable.

## 12. Self-maintenance

Self-maintenance follows `docs/ZN-SELF-MAINTENANCE.md`.

First-stage principle: ZN may investigate, develop, test, prepare branches/PRs and release candidates, but replacing the user's currently installed body defaults to explicit user approval.

Identity, long-term memory, credentials, updater, rollback, signing and self-maintenance permission rules remain high-risk boundaries requiring conservative approval.

## 13. Testing contract

At minimum protect:

- zero-model resident boot and persistence;
- Situation/Thought/Will continuity;
- Body result feedback and independent verification;
- nervous learning/reconsolidation;
- current-reality-gated procedural influence;
- channel restart/idempotency behavior;
- runtime package ownership;
- active ZN renderer/main/preload/protocol ownership;
- release/runtime staging integrity;
- explicit anti-Hermes dependency scans over active ZN source/config/manifests.

A green inherited test suite is irrelevant after evacuation. Tests retained in the active tree must describe ZN behavior.

## 14. M8/M10 boundaries

M8 release continuity debt remains separate and must not be falsely reported complete. Installed N→N+1 continuity, equivalent intended-platform clean-install/login evidence and signing/notarization remain explicit until verified.

M10 is the eventual intentional promotion of verified ZN to `main`. Removing Hermes source from `dev/zn-agent` **does not authorize modifying `main` early**.

M10 still requires an owned runtime, owned desktop, owned release artifacts, reasonable CI and applicable provenance/license retention, followed by explicit user authorization.

## 15. Immediate priority

Until evacuation exits are met, the primary engineering lane is:

```text
cut root Hermes dev/test dependency
→ move physical resident core into zn_agent
→ migrate ZN tests/imports and verifier path semantics
→ switch active renderer to src/zn
→ reduce Node workspace to ZN-only
→ replace inherited container/build consumers
→ delete inherited source/product trees
→ regenerate/reconcile locks
→ run real CI and fix without restoring Hermes
→ update implementation/extraction/HANDOFF
```

Do not expand resident competence or add new product features during this stage unless necessary to preserve existing ZN behavior through the migration.

## 16. Provenance

This repository originated from Hermes Agent source and ZN has adapted mature implementation during migration. Preserve the applicable upstream license/copyright/attribution records for reused implementation.

Provenance is historical/legal information. It must not become a runtime, build, test, release or maintenance dependency.
