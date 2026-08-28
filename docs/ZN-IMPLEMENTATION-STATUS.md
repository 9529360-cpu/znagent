# ZN Implementation Status

Updated: 2026-08-28

This file records current implementation truth for ZN. Real code/Git state is authoritative, followed by real tests/builds/CI, then `.agent/HANDOFF.md`, then this document.

## Repository truth

- repository: `9529360-cpu/znagent`
- development branch: `dev/zn-agent`
- canonical source/release branch: `main`
- canonical `main`: `b29a7c9ecd205c34560e2945fe14451429afd16d`
- `b29a7c9...` is the normal merge of PR #10, promoting P5.10 read-only restore proposals
- P5.10 exact pre-promotion docs head: `7b70d8b2e21b397112c5b45328ebadbe1477c52a`
- current Windows release-candidate proof head: `3f1dca12f844d8745023a0322b499b7aed18cbad`
- no force push or Git history rewrite has been used
- canonical source promotion is not itself a formal product Release, stable-channel advance, signing event, updater activation, rollback event, or installed-version replacement

M10 canonical promotion remains complete. Normal development stays on `dev/zn-agent` or an isolated work branch. Low-risk coherent stages may enter `main` through the repository promotion gate. High-risk boundaries remain explicitly human-approved.

> **ZN uses models. Models do not own ZN.**

## Stage summary

- P1 shared side-effect-attempt persistence owner: **COMPLETE / CI VERIFIED**
- P2 bounded cumulative accounting/learning durability: **COMPLETE / CI VERIFIED**
- P3 managed-browser frontier reconciliation: **COMPLETE / CI VERIFIED NARROW**
- P4 resident-owned live-page registry: **COMPLETE / CI VERIFIED NARROW**
- P5 durable Work checkpoint / restore foundation: **PARTIAL / TEN BOUNDED SLICES CANONICAL VERIFIED**
- Windows-first release-candidate packaging proof: **COMPLETE / CI VERIFIED NARROW**
- M8 installed-version continuity / rollback / signing: **INCOMPLETE**
- SM0: **COMPLETE**; SM1+: **INCOMPLETE**

Broader Work durability has **27 concrete crash/restart mutation windows closed and verified**. P5.9 and P5.10 are read-only inspection/proposal slices and add no mutation window.

## P5 durable Work / restore status

Historical bounded slices remain:

1. accepted Work ingress checkpoint;
2. ordinary overwrite effect-present recovery;
3. overwrite pre-dispatch identity guard;
4. Windows staged atomic overwrite;
5. durable staged-overwrite precommit reconciliation;
6. commit-start namespace reconciliation and verified-effect cleanup;
7. restart-safe retained namespace repair;
8. Work-owned exact-file restore-point foundation;
9. read-only Work restore-point inspection;
10. non-mutating restore proposal / eligibility contract.

P5.10 is now canonical source through PR #10. Its proposal remains informational only. For retained exact-file points it freshly classifies current reality as unchanged, changed, missing, or unsupported after exact Work ownership validation.

Every proposal keeps the destructive boundary explicit:

```text
kind = restore_exact_file
destructive = true
requires_user_approval = true
requires_fresh_revalidation = true
application_available = false
automatic_authority = false
```

There is still no Restore/Apply command, writeback RPC, approval token, destructive restore lifecycle, or automatic restore authority. Raw retained content/private identity evidence remains resident-owned and is not projected to the desktop.

### P5.10 real canonical proof

Code/proof head:

```text
2fe96e46396c0cda8d618ad342b1196519e96e7b
ZN Work Recovery E2E / 33183092342             success
Windows resident Work restart recovery          108 tests OK
ZN CI / 33183092366                             success
ZN Kernel / Python / Windows                    686 tests OK (5 skipped)
Electron / TypeScript / Windows                 success
ZN Source Boundary / Windows                    success
Publish Windows CI statuses                     success
```

Exact pre-promotion docs head:

```text
7b70d8b2e21b397112c5b45328ebadbe1477c52a
ZN CI / 33184402941                             success
```

Canonical merge:

```text
PR #10                                          merged
main                                            b29a7c9ecd205c34560e2945fe14451429afd16d
ZN CI / 33185789960                             success
ZN Source Boundary / Windows                    success
Electron / TypeScript / Windows                 success
ZN Kernel / Python / Windows                    success
Publish Windows CI statuses                     success
```

A later HANDOFF-only dev commit `60001371aadf94560aba56d9c682e8691d5f2bc6` also passed full ZN CI run `33185971086`.

## Windows-first release readiness

`ZN.md` defines the current intended desktop platform as **Windows x64**. Linux/macOS are deferred and are not first-release gates unless the architecture contract explicitly changes again.

A new low-risk, non-publishing proof lane now exists:

```text
.github/workflows/zn-windows-release-candidate.yml
apps/desktop/scripts/verify-zn-windows-release-candidate.mjs
apps/desktop/scripts/verify-zn-windows-release-candidate.test.mjs
```

The lane runs on a clean GitHub-hosted Windows x64 image and intentionally has only `contents: read` and `statuses: write`. It does not use release secrets, create a tag or GitHub Release, publish to the update channel, advance `stable.json`, invoke the updater, sign artifacts, or replace an installed copy.

Exact candidate proof head:

```text
3f1dca12f844d8745023a0322b499b7aed18cbad
ZN Windows Release Candidate / 33188046176       success
Windows x64 GitHub-hosted runner                 success
locked npm install + high-severity audit         success
candidate verifier tests                         5 tests passed
ZN portable runtime staging + zero-model smoke   success
renderer/Electron build                          success
NSIS + MSI unsigned installer build              success
packaged runtime verification + zero-model boot  success
Windows release manifest                         success
independent size/SHA-256 candidate verification  success
candidate evidence upload                        success
```

Uploaded artifact `9692735233`, retained by CI for 7 days, contains exactly:

```text
ZN-0.17.0-win-x64.exe        131798873 bytes
sha256 e0cb2e0a08082a8d9e1268e05de8b9b6cd8d94441488e02ff352e77158d01988

ZN-0.17.0-win-x64.msi        145854544 bytes
sha256 3ab452ba38bf75514259d03333967dea7f4596e2348b848463ffe3f6891b30e0

zn-release-windows-x64.json
```

The artifact archive itself is recorded by GitHub with digest:

```text
sha256:8b230e382c285a9b13ab9851b4583ffaa2f6163deb246649b6270cf3d348ae85
```

The installer file hashes were independently recomputed from the downloaded CI artifact and exactly matched the manifest.

This proof establishes reproducible unsigned Windows packaging and packaged-runtime boot on a clean hosted builder. It does **not** prove a clean installed desktop session, real installed N -> N+1 updater continuity, rollback, signing trust, or production release readiness.

## Current restore/recovery invariants

1. Old-state equality after dispatch is never stale-attempt replay authority.
2. `namespace_commit_started=true` never authorizes replay of the old overwrite attempt.
3. Retained namespace repair is a new bounded lifecycle with fresh exact evidence.
4. External target appearance wins over repair.
5. Stage/backup drift withdraws repair or cleanup authority.
6. Restore capture requires exact active durable Work ownership.
7. A restore point proves retained pre-mutation content ownership, not restore authority.
8. Capture-time file drift withdraws overwrite authority.
9. Capacity exhaustion blocks incoming restorable overwrite rather than deleting older rollback evidence.
10. Raw restore content stays resident-owned and private.
11. Inspection/proposals require fresh ownership/current-target evidence.
12. Desktop restore observation is transient, not persisted authority.
13. `requires_user_approval` declares a prerequisite; it does not grant approval.
14. Actual destructive restore remains a separate high-risk lifecycle.

## Open risks / incomplete work

P5 remains partial:

- destructive restore writeback is not implemented;
- commit-time destructive target revalidation is not implemented;
- restore approval/authority lifecycle is not implemented;
- post-restore verification/crash/failure semantics are not implemented;
- arbitrary workspace snapshots/general per-task rollback remain open;
- isolated parallel Work remains open.

Windows-first M8 remains incomplete:

- real clean Windows install/login/startup evidence is still missing;
- real installed N -> N+1 application/runtime/resident continuity is still missing;
- identity, memory, work and configuration continuity across the installed transition is not yet proven;
- a safe Windows rollback lifecycle across a real version transition is not implemented/proven;
- Windows signing and release trust are not established; current installer proof is explicitly unsigned;
- the formal `.github/workflows/zn-release.yml` still has a three-OS package matrix and has not been changed in this low-risk candidate stage;
- no formal tag, GitHub Release or stable-channel advance has occurred.

Broader browser/product work and SM1+ also remain incomplete.

Identity, long-term memory destructive changes, credentials/permissions, updater/rollback/signing/release trust, destructive restore, destructive migrations, installed-version replacement and self-maintenance approval-rule changes remain human-approval boundaries.

## Next real target

Finish exact documentation-head CI and promote this low-risk Windows candidate proof/status stage only if the full gate remains green.

After that, continue Windows-first M8 with the smallest safe step toward **real clean-install evidence** without modifying updater/rollback/signing trust. The later installed N -> N+1, rollback and signing/release-trust slices remain separately reviewed high-risk work.

The next safe P5 restore slice remains a non-mutating approval/authority-boundary contract. Actual restore writeback remains separately human-approved.
