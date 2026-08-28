# ZN Maintainer Handoff

Updated: 2026-08-28

This is an operational maintainer handoff, not a chat summary. Real repository state, code, tests, builds and CI remain authoritative.

## Current goal

P5.10 non-mutating Work restore proposal / eligibility has been promoted to canonical `main` through PR #10. The immediate closeout is to verify the exact post-merge `main` CI, keep `dev/zn-agent` aligned without force/history rewrite, and then move into the next low-risk Windows-first release-readiness/documentation stage without crossing updater/rollback/signing/installed-version approval boundaries.

This state does not create a GitHub Release, advance `stable.json`, replace an installed version, or grant destructive restore authority.

> **ZN uses models. Models do not own ZN.**

## Branch / repository state

- repository: `9529360-cpu/znagent`
- development branch: `dev/zn-agent`
- canonical source branch: `main`
- P5.10 promotion PR: `#10`, merged normally
- canonical merge commit: `b29a7c9ecd205c34560e2945fe14451429afd16d`
- `dev/zn-agent` was non-force fast-forwarded to that merge commit before this HANDOFF refresh
- exact P5.10 code/proof head: `2fe96e46396c0cda8d618ad342b1196519e96e7b`
- final pre-promotion docs head: `7b70d8b2e21b397112c5b45328ebadbe1477c52a`
- no force push or Git history rewrite has been used

## Completed

- P5.10 read-only restore proposal contract implemented and previously verified at code head.
- Exact docs-head ZN CI run `33184402941` completed successfully: Source Boundary, Electron/TypeScript, Kernel/Python and status publication all succeeded.
- PR #10 passed final diff/branch/head review and was merged to `main` with expected head `7b70d8b2e21b397112c5b45328ebadbe1477c52a`.
- `dev/zn-agent` was aligned to merge commit `b29a7c9ecd205c34560e2945fe14451429afd16d` using a non-force fast-forward.
- Current P5.10 remains informational only: no Restore/Apply command, no writeback RPC, no approval token, no automatic authority.

## Real test / CI evidence

P5.10 code-head proof:

```text
ZN Work Recovery E2E / 33183092342             success
Windows resident Work restart recovery          108 tests OK

ZN CI / 33183092366                             success
ZN Kernel / Python / Windows                    686 tests OK (5 skipped)
Electron / TypeScript / Windows                 success
ZN Source Boundary / Windows                    success
Publish Windows CI statuses                     success
```

Final pre-promotion docs-head proof:

```text
ZN CI / 33184402941                             success
ZN Source Boundary / Windows                    success
Electron / TypeScript / Windows                 success
ZN Kernel / Python / Windows                    success
Publish Windows CI statuses                     success
```

Post-merge canonical proof currently running:

```text
main commit                                      b29a7c9ecd205c34560e2945fe14451429afd16d
ZN CI / 33185789960                             in progress
ZN Source Boundary / Windows                    success
Electron / TypeScript / Windows                 success
ZN Kernel / Python / Windows                    in progress at core tests
Publish Windows CI statuses                     pending until dependencies finish
```

Do not call canonical post-merge CI verified until run `33185789960` fully succeeds.

No local repository test run is claimed for this web-maintainer stage. Repository Windows CI is the execution authority.

## Windows-first release reality

`ZN.md` already defines Windows x64 as the current intended desktop platform. Linux/macOS are not first-release gates unless explicitly restored as intended targets.

Current release implementation still needs deliberate Windows closeout. Important observed facts:

- `.github/workflows/zn-release.yml` still packages Linux + Windows + macOS in a three-OS matrix; this is not yet aligned to the Windows-first launch scope.
- Windows packaging already produces NSIS/MSI artifacts.
- the current Windows updater verifies update-channel target size/SHA-256 and then hands the installer off with `['/S', '--updated']` after the resident application gate.
- unlike the visible macOS/Linux updater paths, the Windows handoff code does not itself show an explicit old-install backup/rollback lifecycle.
- hashes are integrity evidence, not a signing trust root.
- clean Windows install, real installed N -> N+1 continuity, installed-state/identity continuity, rollback across a real version transition, and Windows signing/release-trust evidence are not yet proven complete.

These observations are readiness evidence only. No updater, rollback, signing, stable-channel or installed-version behavior was changed in this stage.

## Risks / blockers

P5 remains partial overall. Still incomplete includes destructive restore writeback, commit-time destructive revalidation, restore authority lifecycle, post-restore verification/crash semantics, arbitrary workspace rollback, isolated parallel Work, broader browser work, M8 continuity, and SM1+.

For the Windows-first release lane, current blockers/gates include:

- exact post-merge `main` CI for P5.10 must finish green;
- release roadmap/status docs still need Windows-first alignment where they remain multi-platform;
- a real Windows clean-install and installed N -> N+1 continuity proof is still missing;
- a safe Windows rollback story across a real version transition is still missing;
- Windows signing/release trust is still not established for a formal product release.

Human approval remains required for identity, long-term memory destructive changes, credentials/permissions, updater/rollback/signing/release trust, self-maintenance approval-rule changes, destructive restore, destructive migrations and replacement of the user's installed formal version.

No secret, token, password, signing key or production credential belongs in this file.

## Task queue

1. Finish observing post-merge `main` CI run `33185789960`; inspect/fix rather than bypass if it fails.
2. Re-read `main` and `dev/zn-agent` heads after the HANDOFF refresh and record the new development HEAD.
3. Align `docs/ZN-IMPLEMENTATION-STATUS.md` and `docs/ZN-NEXT-PHASE.md` with the completed P5.10 promotion and Windows-x64-first launch scope.
4. Inspect the Windows release test/evidence chain and define the smallest low-risk release-readiness stage that does not modify updater/rollback/signing trust.
5. Keep `.github/workflows/zn-release.yml` behavior unchanged until a deliberately reviewed release-flow change is justified; it currently remains multi-OS.
6. Do not advance `stable.json`, create a formal release tag, replace the installed product, or modify updater/rollback/signing trust without the applicable human-approved high-risk slice.
7. Separately, the next safe P5 product slice remains a non-mutating restore approval/authority-boundary contract; actual restore writeback remains human-approved.

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
- `apps/desktop/electron/zn-release-updater.ts`
- `apps/desktop/electron/zn-release-application-gate.ts`
- `apps/desktop/electron/zn-release-channel.ts`
- `apps/desktop/electron-builder.zn.yml`
- `runtime/python/zn_agent/core/work_restore_point_inspection_resident.py`
- `tests/zn_agent/core/test_work_restore_proposals.py`

## Next real target

Close the exact post-merge P5.10 CI proof, then perform a low-risk Windows-first release-readiness/status alignment stage. Do not silently cross the updater/rollback/signing/release-trust or installed-version replacement approval boundary.