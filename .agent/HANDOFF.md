# ZN Maintainer Handoff

Updated: 2026-08-28

This is the operational work site, not a chat summary. Real repository state/code and real CI/build evidence remain authoritative.

## Current goal

Close and promote a low-risk **Windows x64 unsigned release-candidate proof** stage after P5.10 canonical promotion. This stage proves clean hosted packaging and artifact/runtime integrity only. It does not modify or execute formal publishing, updater replacement, rollback, signing or the stable channel.

> **ZN uses models. Models do not own ZN.**

## Branch / repository state

- repository: `9529360-cpu/znagent`
- development branch: `dev/zn-agent`
- canonical branch: `main`
- canonical `main`: `b29a7c9ecd205c34560e2945fe14451429afd16d`
- P5.10 promotion PR #10: merged normally and post-merge CI verified
- Windows candidate implementation commit: `50aab205d6cb898e9da044c44f9e1c0ab8849f62`
- candidate fixture-fix / exact package proof head: `3f1dca12f844d8745023a0322b499b7aed18cbad`
- Windows-first status/roadmap closeout head: `ccba9ca8ea5519ea9af5d218e8a7c9522aa51da4`
- this HANDOFF update creates the final documentation head; re-read the branch ref for the resulting exact HEAD
- no force push/history rewrite has been used

## Completed

### P5.10 canonical closeout

- exact pre-promotion docs CI `33184402941`: success
- PR #10 merged to `main` as `b29a7c9ecd205c34560e2945fe14451429afd16d`
- exact post-merge `main` CI `33185789960`: success for Source Boundary, Electron/TypeScript, Kernel/Python and status publisher
- dev HANDOFF refresh `60001371aadf94560aba56d9c682e8691d5f2bc6` passed full CI `33185971086`
- P5.10 remains read-only/non-mutating; no restore writeback/Apply/approval token/automatic authority exists

### Windows-first candidate proof

Added:

- `.github/workflows/zn-windows-release-candidate.yml`
- `apps/desktop/scripts/verify-zn-windows-release-candidate.mjs`
- `apps/desktop/scripts/verify-zn-windows-release-candidate.test.mjs`

The workflow is intentionally non-publishing:

- GitHub-hosted `windows-latest` x64;
- permissions only `contents: read`, `statuses: write`;
- no release secrets;
- no tag/GitHub Release;
- no public update-channel upload;
- no `stable.json` advance;
- no updater invocation;
- no signing;
- no installed-version replacement.

First candidate run `33187867062` failed before packaging because the duplicate-EXE unit-test fixture wrote 6 bytes while retaining 17-byte manifest metadata. The verifier correctly rejected the mismatch. Commit `3f1dca12f844d8745023a0322b499b7aed18cbad` fixed only the fixture; verifier assertions were not weakened.

Exact package proof:

```text
ZN Windows Release Candidate / 33188046176       success
clean GitHub-hosted Windows x64 runner            success
npm ci                                            success
npm audit --audit-level=high                      success (0 vulnerabilities)
release-candidate verifier                        5 tests passed
portable ZN runtime staging / zero-model smoke    success
renderer/Electron build                           success
unsigned Windows NSIS + MSI build                 success
packaged runtime verification + zero-model boot   success
release manifest generation                       success
independent installer size/SHA-256 verification   success
artifact upload                                   success
```

CI artifact:

```text
artifact id: 9692735233
name: zn-windows-release-candidate-3f1dca12f844d8745023a0322b499b7aed18cbad
archive digest: sha256:8b230e382c285a9b13ab9851b4583ffaa2f6163deb246649b6270cf3d348ae85
```

Downloaded artifact contents were independently inspected:

```text
ZN-0.17.0-win-x64.exe
size   131798873
sha256 e0cb2e0a08082a8d9e1268e05de8b9b6cd8d94441488e02ff352e77158d01988

ZN-0.17.0-win-x64.msi
size   145854544
sha256 3ab452ba38bf75514259d03333967dea7f4596e2348b848463ffe3f6891b30e0

zn-release-windows-x64.json
```

Independent `sha256sum` over the downloaded EXE/MSI exactly matched the manifest.

### Status/roadmap alignment

`docs/ZN-IMPLEMENTATION-STATUS.md` and `docs/ZN-NEXT-PHASE.md` now record:

- P5.10 is canonical verified, not docs-closeout-pending;
- first formal desktop target is Windows x64;
- Linux/macOS are deferred/non-blocking for the first release;
- current candidate proof is explicitly unsigned and non-publishing;
- clean install, installed N -> N+1, rollback and Windows signing/release trust remain incomplete.

Exact status/roadmap head `ccba9ca8ea5519ea9af5d218e8a7c9522aa51da4` passed full ZN CI `33188933799`: Source Boundary, Electron/TypeScript, Kernel/Python and status publisher all succeeded.

## Current CI

Verified proof points:

```text
main P5.10 merge                               b29a7c9ecd205c34560e2945fe14451429afd16d
ZN CI / 33185789960                           success

candidate proof head                          3f1dca12f844d8745023a0322b499b7aed18cbad
Windows Release Candidate / 33188046176       success

status/roadmap head                           ccba9ca8ea5519ea9af5d218e8a7c9522aa51da4
ZN CI / 33188933799                           success
```

The HANDOFF update containing this final closeout still requires its own exact-head ZN CI before promotion. Do not substitute predecessor CI for that final gate.

## Windows-first release reality

The candidate proof establishes that a clean hosted Windows machine can build self-contained unsigned NSIS/MSI candidates and boot the packaged ZN runtime without a model.

It does **not** establish:

- real clean installed desktop first launch/login;
- real installed N -> N+1 update continuity;
- identity/memory/work/config continuity across an installed transition;
- rollback across a real Windows version transition;
- Windows code signing or release trust;
- formal immutable release/stable-channel publication.

The formal `.github/workflows/zn-release.yml` remains unchanged and still contains a three-OS package matrix. It was deliberately kept outside this low-risk stage.

## Risks / blockers

P5 remains partial overall: destructive restore writeback, destructive revalidation/authority lifecycle, post-restore verification/crash semantics, general workspace rollback and isolated parallel Work remain open.

Windows M8 remaining gates:

1. exact final HANDOFF-head full CI and source promotion for this candidate-proof stage;
2. real clean Windows install/start evidence;
3. real installed N -> N+1 continuity evidence;
4. safe Windows rollback lifecycle/proof;
5. Windows signing/release trust;
6. only after those gates, formal immutable release assets and stable-channel advancement.

High-risk areas still require explicit human approval: identity/long-term-memory destructive changes, credentials/permissions, updater/rollback/signing/release trust, destructive restore/migrations, installed-version replacement and self-maintenance approval-rule changes.

No secret, token, password, signing key or production credential belongs here.

## Relevant files

- `ZN.md`
- `AGENTS.md`
- `docs/ZN-IMPLEMENTATION-STATUS.md`
- `docs/ZN-NEXT-PHASE.md`
- `docs/ZN-SOURCE-EXTRACTION.md`
- `docs/ZN-SELF-MAINTENANCE.md`
- `.agent/HANDOFF.md`
- `.github/workflows/zn-ci.yml`
- `.github/workflows/zn-release.yml`
- `.github/workflows/zn-windows-release-candidate.yml`
- `apps/desktop/electron-builder.zn.yml`
- `apps/desktop/electron/zn-release-updater.ts`
- `apps/desktop/scripts/stage-zn-runtime.mjs`
- `apps/desktop/scripts/verify-zn-packaged-runtime.mjs`
- `apps/desktop/scripts/write-zn-release-manifest.mjs`
- `apps/desktop/scripts/verify-zn-windows-release-candidate.mjs`
- `apps/desktop/scripts/verify-zn-windows-release-candidate.test.mjs`

## Task queue

1. Observe exact final HANDOFF-head ZN CI; fix failures rather than bypass them.
2. Re-check `main`/`dev` heads and complete cumulative diff.
3. If the low-risk gate is fully green, create/merge a traceable promotion PR into `main` and verify exact post-merge `main` CI.
4. If ancestry permits after merge, non-force fast-forward `dev/zn-agent` to the canonical merge commit; never rewrite history.
5. Keep formal release/updater/rollback/signing/stable actions out of this stage.
6. Next low-risk M8 target: clean Windows install/start evidence in isolated test state, without production update infrastructure.
7. Real installed N -> N+1, rollback and signing/release-trust changes remain separately reviewed high-risk slices.
8. Separately, next safe P5 restore work remains a non-mutating approval/authority-boundary contract; actual restore application remains human-approved.

## Next real target

Finish this candidate-proof stage through exact final-head CI and normal source promotion. Then build a bounded **clean Windows install/start proof** that exercises the real installer in isolated test state but does not change updater/rollback/signing trust or the user's installed formal version.
