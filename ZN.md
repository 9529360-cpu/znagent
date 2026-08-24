# ZN — Product and Engineering Contract

> Active development branch: `dev/zn-agent`
>
> Canonical source/release branch: `main`
>
> This file is the current architecture contract. Real code and Git state determine what exists; tests/CI determine what has been verified; `.agent/HANDOFF.md` records the current work site.

## 0. Development contract

Before changing the project, restore the real repository state and inspect the active call chain.

Fact priority:

```text
real code and Git state
> real tests / builds / CI
> .agent/HANDOFF.md
> chat descriptions
```

Normal engineering loop:

```text
inspect repository + branch + CI
→ identify entry / owner / state / lifecycle / dependency / tests / active caller
→ update ZN.md first when architecture direction changes
→ implement the smallest coherent ZN-owned step on dev/zn-agent or an isolated work branch
→ add or update tests
→ run relevant verification
→ inspect diff
→ commit / push
→ verify real CI
→ synchronize status docs and HANDOFF
```

M10 canonical promotion is complete. Ordinary development must still not experiment directly on `main`; verified development flows through `dev/zn-agent` or isolated work branches and reaches `main` only through the repository's deliberate promotion/release process.

## 1. Product definition

ZN is the only product and the only resident subject.

**ZN uses models. Models do not own ZN.**

Models, browsers, search systems, code interpreters and future cognitive systems are replaceable resources. They do not own ZN identity, memory, Will, continuity or the resident life loop.

ZN owns:

- persistent Self and life;
- Body and Senses;
- Situation, Thought and Will;
- lived memory and learning;
- Investigation and Action;
- provider/resource boundaries;
- communication channels;
- runtime, configuration and credential references;
- desktop main/preload/renderer and product identity;
- update and release behavior.

Disconnecting every external model must not erase ZN identity/state or prevent native resident pulses and owned deterministic behavior.

## 2. Repository ownership boundary

The active development tree is ZN-only. Historical/reference product source is not kept inside the active tree and is not a runtime, build, test, packaging, release or maintenance dependency.

Reference mechanisms may be studied from Git history, the dedicated reference branch, or an external/upstream repository. Reuse is allowed only when the mechanism is understood, adapted behind ZN-owned interfaces/config/state/lifecycle, covered by ZN tests and free of reference-product control-plane assumptions.

Never restore a historical product tree merely because a test, import or build step breaks. Decide whether the capability belongs to ZN. If it does, implement or adapt it as ZN-owned code; otherwise remove the obsolete caller or contract.

The steady-state physical topology is:

```text
znagent/
├── ZN.md
├── AGENTS.md
├── LICENSE
├── runtime/
│   └── python/
│       ├── pyproject.toml
│       └── zn_agent/
│           ├── core/
│           └── resident.py
├── apps/
│   └── desktop/
│       ├── electron/
│       ├── src/zn/
│       ├── assets/
│       ├── scripts/
│       └── package.json
├── tests/
│   └── zn_agent/core/
├── docs/
├── .agent/
└── .github/workflows/
```

A small root Node manifest/lock may exist only to provide a reproducible ZN desktop workspace install.

## 3. Resident architecture

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

Model output is never automatically fact, decision, execution authority or completion proof.

## 4. Body, verification and learned competence

Files, processes, Git, terminal, browser and network sensing are Body/Senses, not extra agent personalities.

Movement success alone is not task success. Completion and positive learning require independent current-world verification appropriate to the effect.

Engineering competence must preserve:

- explicit typed or resident-proven authority before side effects;
- structured current repository/path evidence where Git state matters;
- fresh post-action verification;
- contradiction returns to Investigation;
- procedural memory may influence only freshly re-formed safe choices;
- familiar execution never makes current evidence optional;
- model suggestions do not create execution authority.

## 5. Memory and learning

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

Detailed direction is maintained in `docs/ZN-MEMORY-LEARNING.md` and `docs/ZN-NEXT-PHASE.md`.

## 6. Desktop boundary

Electron is ZN's face/work surface, not the owner of resident life.

```text
ZN Electron main
→ ZN preload / IPC
→ long-lived ZN resident
→ independent ZN renderer (`src/zn`)
```

The renderer is content/work oriented. Files, diffs and terminal are contextual surfaces. Closing the desktop must not define or erase resident identity.

## 7. Runtime, data and credentials

Packaged runtime identity:

```text
Python distribution: znagent
Python package:      zn_agent
entrypoint:          zn-resident
```

The physical core source is `runtime/python/zn_agent/core/`; tests live under `tests/zn_agent/core/`.

Persistent identity/state belongs outside immutable runtime versions. Runtime N and N+1 may coexist during safe handoff.

Credentials and secrets belong in appropriate secure stores/project secret infrastructure and must not be committed, written into HANDOFF, logs or ordinary resident memory.

## 8. Release/update architecture

The current intended desktop platform is **Windows x64**. Formal release readiness and M8 evidence are Windows-first. Linux and macOS packaging or continuity checks may be retained as optional/on-demand evidence, but they do not block normal development or M8 unless they are explicitly restored as intended product targets.

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

A clean Windows machine must not require a source checkout, system Python, Node/npm or private source credentials.

Hashes are integrity checks, not signatures. Windows signing remains a separate release hardening gate.

## 9. Self-maintenance

Self-maintenance follows `docs/ZN-SELF-MAINTENANCE.md`.

First-stage principle: ZN may investigate, develop, test, prepare branches/PRs and release candidates, but replacing the user's currently installed body defaults to explicit user approval.

Identity, long-term memory, credentials, updater, rollback, signing and self-maintenance permission rules remain high-risk boundaries requiring conservative approval.

## 10. Testing contract

The steady-state daily CI target is Windows x64. It should run automatically from repository events on a replaceable self-hosted Windows x64 runner rather than depending on a specific runner name or maintainer session. A replacement Windows x64 runner registered to the repository must be able to resume the same workflow.

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
- repository-boundary scans that prevent historical/reference product paths, package namespaces or control planes from becoming active dependencies again.

Tests retained in the active tree must describe ZN behavior or guard ZN ownership boundaries. Optional Linux/macOS checks must not be presented as required evidence while those platforms are not intended targets.

## 11. M8 and M10 boundaries

M8 release continuity debt remains separate and must not be falsely reported complete. For the current Windows x64 product target, M8 requires Windows clean-install/login evidence, installed N→N+1 continuity, rollback evidence and applicable Windows signing evidence.

Historical Linux/macOS evidence remains useful engineering evidence, but Linux AppImage, Linux container and macOS continuity/signing are not current M8 blockers unless those platforms are deliberately restored as intended targets.

M10 canonical source promotion is complete. Its continuing value is the stable ownership rule it established:

1. ZN owns resident runtime and persistent identity/state paths;
2. ZN owns desktop main/preload/renderer and product identity;
3. ZN owns build, package and release automation;
4. CI verifies the active canonical source;
5. applicable license/provenance obligations remain preserved;
6. historical/reference source is not an active dependency;
7. unresolved release risks remain explicit rather than being hidden by branch promotion.

The 2026-08-24 promotion was performed by non-forced fast-forward after a fresh full CI review. No history rewrite was used.

Canonical branch promotion does not mean M8 or formal release readiness is complete. M8 remains a separate evidence-based milestone.

## 12. Current priority

The repository-boundary evacuation and M10 canonical promotion are complete. Engineering priority is now:

```text
keep automatic Windows x64 self-hosted CI green on push / PR
→ keep ZN-only ownership guards green
→ remove remaining development/tooling security debt where safely possible
→ advance resident-owned engineering competence
→ strengthen browser/computer Body/Senses only behind ZN ownership
→ close Windows M8 install / N→N+1 / rollback / signing gaps
→ maintain self-maintenance/release automation
```

Linux/macOS work is optional/on-demand at the current product stage. Do not let dormant secondary-platform work block Windows development, and do not expand product behavior by restoring old control planes or generic agent-framework ownership.

## 13. Provenance

Historical upstream provenance and license obligations are retained through repository history, the dedicated reference branch and applicable license records. Provenance is legal/historical information only; it must not become a runtime, build, test, release or maintenance dependency.
