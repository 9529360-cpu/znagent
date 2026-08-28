# ZN next phase — Self + mature execution + Windows-first release continuity

> Updated: 2026-08-28
>
> Active development branch: `dev/zn-agent`
>
> Canonical source/release branch: `main`
>
> Governing architecture: [`../ZN.md`](../ZN.md)
>
> Current facts: [`ZN-IMPLEMENTATION-STATUS.md`](ZN-IMPLEMENTATION-STATUS.md)
>
> Self-maintenance: [`ZN-SELF-MAINTENANCE.md`](ZN-SELF-MAINTENANCE.md)

## 1. Product target

The organism-first architecture remains governing:

> **ZN keeps its own durable Self, acts through ZN-owned Body/Senses, verifies reality, learns from verified experience, and uses external models only as replaceable cognitive resources.**

```text
durable Self
+ reality-based execution
+ resident-owned competence
+ verified learning
+ replaceable external cognition
= ZN
```

The first formal desktop release target is **Windows x64**. Linux and macOS are deferred and do not block the first-release lane unless `ZN.md` is deliberately changed again.

## 2. Core invariants

1. The same resident Self owns work before, during and after model calls.
2. Work continuity lives in ZN-owned durable state, not a model context window.
3. Body action success is not task success; completion requires fresh reality evidence.
4. Model output is candidate cognition, never automatic fact/authority/completion proof.
5. Familiarity and learned competence never bypass current evidence or authorization.
6. Prediction error interrupts stale automatic behavior and returns control to Investigation.
7. Mature recurring mechanics should crystallize into ZN-owned mechanisms/tests.
8. Providers/frameworks remain replaceable and may not become ZN's control plane.
9. The active repository remains ZN-only.
10. Formal product continuity must survive runtime/version replacement without redefining ZN identity.

## 3. Verified foundation

Current repository evidence already supports:

- persistent resident life and identity;
- meaningful zero-model operation;
- Situation / Thought / Will;
- durable events and WorkingState;
- native Investigation / Action / verification loops;
- ZN-owned filesystem/process/terminal/web/channel paths;
- persistent nervous traces and bounded procedural learning;
- restart-safe bounded Work overwrite recovery;
- Work-owned exact-file restore-point retention;
- read-only restore-point inspection and non-mutating restore proposals;
- ZN-owned Python runtime/package/desktop/build/release boundaries;
- physically ZN-only active source tree;
- canonical `main` promotion flow with real Windows CI;
- clean GitHub-hosted Windows x64 unsigned NSIS/MSI candidate packaging, packaged-runtime verification and zero-model boot.

These foundations do not prove general intelligence, general rollback, installed-version continuity or formal release trust.

## 4. Immediate engineering sequence

### P0 — Protect ZN-only ownership

Keep source-boundary, package/runtime ownership and zero-model boot evidence green. Never restore a foreign product/control plane to satisfy a build or test.

### P1 — Resident-owned verification and competence

Continue broadening deterministic evidence contracts where the repository/current world can prove them. Do not guess arbitrary execution authority from filenames, model text or prior success.

### P2 — Recovery into learned competence

Verified failure/recovery should become resident-owned experience without turning memory into blind side-effect replay.

### P3 — Skill maturity, inhibition and relearning

Repeated verified compatible experience may strengthen a tendency. Contradiction must weaken/inhibit it and trigger re-sensing/relearning.

### P4 — Browser/computer-use Body and Senses

Advance managed-browser and user-browser-bridge capability behind ZN-owned target, permission, action and evidence semantics.

### P5 — M8 Windows-first release continuity

The launch-gating sequence is now explicitly Windows x64:

```text
clean hosted Windows candidate build
→ clean Windows install/start proof
→ installed N state/identity/work baseline
→ real installed N -> N+1 handoff
→ post-update resident/body/state verification
→ rollback proof across a real Windows version transition
→ Windows signing/release-trust proof
→ formal immutable release assets
→ stable.json last
```

Current completed narrow evidence:

- clean GitHub-hosted Windows x64 builder;
- portable ZN runtime staging;
- zero-model runtime smoke;
- Electron build;
- unsigned NSIS + MSI build;
- packaged-runtime verification and boot;
- Windows manifest generation;
- independent installer size/SHA-256 verification;
- CI artifact retention.

Still required before formal first release:

- real clean Windows installation and first launch evidence;
- real installed N -> N+1 continuity, including resident identity/state/work/config references;
- safe rollback across a real Windows transition;
- Windows signing and release trust through secure repository-defined infrastructure;
- formal release artifact verification and immutable publication;
- stable channel advancement only after immutable assets are verified.

Linux/macOS packaging may remain useful optional evidence but is not a Windows first-release gate. macOS notarization is therefore not part of the first-release gate.

Do not quietly reinterpret the current unsigned package proof as signing or release readiness.

### P6 — SM1+ self-maintenance

Advance detection/investigation/fix preparation behind branch/PR/CI and existing human-approval boundaries. First-stage ZN must not silently replace the user's installed formal body.

## 5. High-risk release boundary

Ordinary low-risk investigation, tests, candidate-build automation and source promotion may proceed through repository gates.

Explicit human approval remains required for changes to or execution of high-risk areas such as:

- updater/installed-version replacement;
- rollback semantics;
- signing keys/trust root/release trust;
- credentials/permissions;
- identity or long-term-memory destructive migration;
- destructive restore/writeback;
- self-maintenance approval rules.

The current Windows candidate workflow intentionally does not cross those boundaries.

## 6. Growth benchmark

A mature ZN should increasingly support:

```text
receive durable work
→ same Self owns it
→ investigate current reality
→ act through owned Body
→ verify real outcome
→ preserve/reconcile state across restart/version change
→ learn from verified experience
→ use less external cognition for familiar compatible work
→ interrupt itself when reality contradicts familiarity
```

Release continuity is part of this benchmark: replacing runtime/body must not mean replacing the subject.

## 7. Next concrete release target

After the current candidate-proof stage is fully documented and promoted, the next low-risk M8 target is **clean Windows install/start evidence** using isolated test state and no production update channel.

Real installed N -> N+1 application, rollback and signing/release-trust changes remain separate explicitly reviewed slices because they touch the high-risk update boundary.
