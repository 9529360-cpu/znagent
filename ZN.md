# ZN — Product and Engineering Contract

> Active development branch: `dev/zn-agent`
>
> Canonical release/source branch: `main` once the M10 promotion decision below is executed.
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
→ implement the smallest coherent ZN-owned step
→ add or update tests
→ run relevant verification
→ inspect diff
→ commit / push
→ verify real CI
→ synchronize status docs and HANDOFF
```

`main` must not be modified until the explicit M10 conditions are satisfied and the user explicitly authorizes promotion.

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

Reference mechanisms may be studied from Git history or a dedicated reference branch/external upstream. Reuse is allowed only when the mechanism is understood, adapted behind ZN-owned interfaces/config/state/lifecycle, covered by ZN tests and free of reference-product control-plane assumptions.

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

A clean machine must not require a source checkout, system Python, Node/npm or private source credentials.

Hashes are integrity checks, not signatures. Signing/notarization remain separate release hardening gates where applicable.

## 9. Self-maintenance

Self-maintenance follows `docs/ZN-SELF-MAINTENANCE.md`.

First-stage principle: ZN may investigate, develop, test, prepare branches/PRs and release candidates, but replacing the user's currently installed body defaults to explicit user approval.

Identity, long-term memory, credentials, updater, rollback, signing and self-maintenance permission rules remain high-risk boundaries requiring conservative approval.

## 10. Testing contract

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

Tests retained in the active tree must describe ZN behavior or guard ZN ownership boundaries.

## 11. M8 and M10 boundaries

M8 release continuity debt remains separate and must not be falsely reported complete. Installed N→N+1 continuity, intended-platform clean-install/login evidence and signing/notarization remain explicit until verified.

M10 is the intentional promotion of verified ZN to `main`. Active-tree source cleanup by itself does not authorize modifying `main`.

M10 requires all of the following at promotion time:

1. ZN-owned resident runtime and persistent identity/state path;
2. ZN-owned desktop main/preload/renderer and protocol/product identity;
3. ZN-owned build, package and release automation;
4. reproducible CI proving the current promoted commit;
5. applicable license/provenance obligations retained;
6. no active dependency on historical/reference product source;
7. unresolved M8/release risks explicitly reviewed and acceptable for the intended promotion;
8. explicit user authorization to promote `dev/zn-agent` to `main`.

Promotion must be deliberate and traceable. Do not force-push or rewrite history to achieve it.

### 11.1 2026-08-24 canonical-branch promotion decision

For the purpose of making ZN the canonical source on `main`—not for declaring M8 or formal release readiness complete—the M10 risk review is approved once the exact promotion commit has a fresh full CI pass.

Current review:

- resident/runtime ownership is ZN-owned and zero-model boot is CI-verified;
- desktop main/preload/renderer, protocol and packaged runtime ownership are ZN-owned and CI-verified;
- build/package/release automation is ZN-owned;
- the active tracked tree has a CI-enforced source boundary; preserved legal attribution in `LICENSE` is the only text-scan exception;
- historical source is preserved outside the active tree in a dedicated reference branch and is not an active dependency;
- production npm dependencies are gated against high-severity advisories in CI;
- two known high-severity findings in the development/tooling dependency set remain debt and must be traced, but they are not accepted as production/runtime dependencies;
- M8 remains **PARTIAL**: intended-platform continuity, real secure signing/notarization evidence and real-version rollback evidence remain open;
- those M8 gaps are accepted only for canonical branch promotion, not for claiming formal release completion;
- the user has explicitly authorized promotion after the source boundary is clean.

Therefore the final M10 gate is: fresh full CI on the exact documentation/decision commit, followed by a non-forced fast-forward of `main`. After promotion, the same source-boundary, production dependency, Python and desktop CI gates must remain active on `main`.

## 12. Current priority

The repository-boundary evacuation is complete. After M10 canonical-branch promotion, engineering priority remains:

```text
keep ZN-only ownership guards green
→ trace and remove remaining development/tooling security debt
→ advance resident-owned engineering competence
→ strengthen browser/computer Body/Senses only behind ZN ownership
→ close M8 N→N+1 and intended-platform continuity gaps
→ maintain self-maintenance/release automation
```

Do not expand product behavior by restoring old control planes or generic agent-framework ownership.

## 13. Provenance

Historical upstream provenance and license obligations are retained through repository history, the dedicated reference branch and applicable license records. Provenance is legal/historical information only; it must not become a runtime, build, test, release or maintenance dependency.