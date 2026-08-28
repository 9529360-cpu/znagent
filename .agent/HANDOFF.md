# ZN Maintainer Handoff

Updated: 2026-08-28

This is an operational maintainer handoff, not a chat summary. Real repository state, code, tests, and CI remain authoritative.

## Current goal

P5.10 non-mutating Work restore proposal / eligibility is implemented and verified at the code head. The current action is documentation-head verification and normal low-risk source promotion into canonical `main` if the promotion gate remains green.

This stage is source development only. It does not create a GitHub Release, advance the stable channel, replace an installed version, or grant destructive restore authority.

Founding boundary:

> **ZN uses models. Models do not own ZN.**

## Branch / repository state

- repository: `9529360-cpu/znagent`
- development branch: `dev/zn-agent`
- canonical source branch: `main`
- current canonical `main`: `5ff8331ba1e44090b2cec9ca1ed8715c33196580`
- P5.9 was promoted to `main` through PR #7
- PR #9 merged the read-only restore proposal implementation into `dev/zn-agent`
- exact P5.10 code/proof head: `2fe96e46396c0cda8d618ad342b1196519e96e7b`
- implementation-status closeout commit: `0c4973b1f0430af67b770af290429c8fdb6f2e66`
- this HANDOFF write creates the final documentation-head commit; re-read actual `dev/zn-agent` HEAD after this write
- before documentation closeout, dev was 16 commits ahead of main and 0 behind
- no force push or Git history rewrite has been used

## P5 status

P5 remains **PARTIAL / TEN BOUNDED SLICES CI VERIFIED AT CODE HEAD**. Documentation-head exact CI is still required before calling the stage closed/promotable.

Concrete crash/restart windows closed and verified: **27**.

P5.9 and P5.10 are read-only and add no mutation lifecycle, so they do not add crash/restart windows.

Current resident chain:

```text
provider_bridge
-> RecoveryBoundedResidentRuntime
-> WorkRestorePointInspectionResidentRuntime
-> WorkRestorePointResidentRuntime
-> AtomicOverwriteNamespaceRecoveryResidentRuntime
-> AtomicOverwriteRecoveryResidentRuntime
-> OverwriteRecoveryResidentRuntime
-> DurableBodyAccountingResidentRuntime
-> CapabilityRecoveryResidentRuntime
-> resident core
```

P5.10 owner:

```text
runtime/python/zn_agent/core/work_restore_point_inspection_resident.py
```

P5.10 derives a read-only restore proposal only after exact durable Work ownership validation plus fresh target observation. Current proposal states are:

- unchanged -> blocked because the target already matches retained prestate;
- changed -> conflict review required;
- missing -> missing-target review required;
- unsupported -> blocked because current reality cannot be compared safely.

Every proposal is marked destructive, requires user approval and fresh revalidation, while `application_available` and `automatic_authority` remain false.

The proposal surface exports no retained content BLOB, content hash, private pre-identity record, action signature, intent ID, or message ID. Forged Work ownership and forged resident-event ownership fail closed.

The desktop remains read-only. There is no Restore/Apply action, no writeback RPC, no approval token, and no automatic restore path.

Actual destructive restore application is **not implemented** and remains a separate human-approved authority slice.

## Real test / CI evidence

Canonical P5.9 source state:

```text
main                                             5ff8331ba1e44090b2cec9ca1ed8715c33196580
PR #7                                            merged
```

P5.10 exact code/proof head:

```text
2fe96e46396c0cda8d618ad342b1196519e96e7b
ZN Work Recovery E2E / run 33183092342          success
Windows resident Work restart recovery           success
Ran 108 tests in 87.381s                         OK

ZN CI / run 33183092366                          success
ZN Kernel / Python / Windows                     success
  Ran 686 tests in 610.053s                      OK (skipped=5)
Electron / TypeScript / Windows                  success
ZN Source Boundary / Windows                     success
Publish Windows CI statuses                      success
```

An earlier Work Recovery E2E run on `26bf1b9a430f29aa7fdb8415cbc46e6b7f330fa7` failed on Windows because the forged-ownership test left its SQLite connection open and `TemporaryDirectory` cleanup hit `WinError 32`. Commit `2fe96e46396c0cda8d618ad342b1196519e96e7b` explicitly closes that test connection. The failing run remains visible and was fixed rather than bypassed.

No local repository test run is claimed for this web-maintainer stage. Repository self-hosted Windows CI is the execution authority.

The documentation-head commit created by this HANDOFF update has **not yet been remotely verified** at the moment this text is written. Do not call it CI verified until its exact-head run completes successfully.

## Relevant files

- `ZN.md`
- `AGENTS.md`
- `docs/ZN-IMPLEMENTATION-STATUS.md`
- `docs/ZN-SOURCE-EXTRACTION.md`
- `docs/ZN-SELF-MAINTENANCE.md`
- `.agent/HANDOFF.md`
- `runtime/python/zn_agent/core/work_restore_point_resident.py`
- `runtime/python/zn_agent/core/work_restore_point_inspection_resident.py`
- `runtime/python/zn_agent/core/recovery_bounded_resident.py`
- `runtime/python/zn_agent/core/work_control.py`
- `runtime/python/zn_agent/core/work.py`
- `tests/zn_agent/core/test_work_restore_points.py`
- `tests/zn_agent/core/test_work_restore_proposals.py`
- `tests/zn_agent/core/test_work_restore_point_guards.py`
- `tests/zn_agent/core/test_work_restore_point_retention.py`
- `tests/zn_agent/core/test_work_restore_point_active_run.py`
- `apps/desktop/src/zn/resident-client.ts`
- `apps/desktop/src/zn/state.ts`
- `apps/desktop/src/zn/workbench.tsx`
- `apps/desktop/electron/zn-restore-point-inspection.test.ts`
- `apps/desktop/electron/zn-desktop-ownership.test.ts`
- `.github/workflows/zn-ci.yml`
- `.github/workflows/zn-work-recovery-e2e.yml`

## Risks / blockers

No known P5.10 product blocker remains at the verified code head.

Before claiming this stage closed/promoted, the final documentation head still needs exact-head ZN CI and a final diff/repository-state check.

Still incomplete:

- actual destructive restore application/writeback;
- commit-time target revalidation for destructive restore;
- restore approval/authority lifecycle;
- post-restore verification, crash semantics, and failure semantics;
- arbitrary workspace snapshots/general per-task rollback;
- isolated parallel Work;
- broader browser/M8 continuity and SM1+ work.

Human approval remains required for identity, long-term memory destructive changes, credentials/permissions, updater/rollback/signing/release trust, self-maintenance approval-rule changes, destructive restore, destructive migrations, and installed-version replacement.

No secret, token, password, signing key, or production credential belongs in this file.

## Task queue

1. Re-read the actual `dev/zn-agent` documentation HEAD created by this update.
2. Observe exact docs-head ZN CI; do not call the closeout verified until it is green.
3. Re-check `main` / `dev/zn-agent` HEADs and the complete cumulative diff.
4. If the low-risk promotion gate remains satisfied, create a traceable P5.10 promotion PR and normally merge it to `main`.
5. Verify post-merge `main` CI on the exact merge commit.
6. If ancestry permits, non-force fast-forward `dev/zn-agent` to the canonical merge commit; never force push or rewrite history.
7. Keep formal Release/stable-channel/install actions out of this stage.
8. After promotion, begin a non-mutating restore approval/authority-boundary contract.
9. Do not implement actual restore writeback without the separate human-approved destructive authority slice.

## Next real target

Close and promote P5.10, then define the **non-mutating restore approval/authority-boundary contract**: an explicit approval must be bindable to one restore point, exact Work ownership, one target identity, a freshness boundary, and one exact proposed operation, but the contract itself must still grant no writeback authority.

Actual restore application remains a separately reviewed human-approved destructive slice.