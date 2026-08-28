# ZN Implementation Status

Updated: 2026-08-28

This file records implementation truth for the active ZN product. Source code, Git state, tests, and CI remain authoritative over this document.

## Repository truth

- repository: `9529360-cpu/znagent`
- development branch: `dev/zn-agent`
- canonical source branch: `main`
- current canonical `main`: `5ff8331ba1e44090b2cec9ca1ed8715c33196580`
- `main` contains the P5.9 read-only restore-point inspection promotion from PR #7
- current P5.10 code/proof head before this documentation closeout: `2fe96e46396c0cda8d618ad342b1196519e96e7b`
- PR #9 merged the read-only restore proposal / eligibility implementation into `dev/zn-agent`
- no force push or Git history rewrite has been used
- canonical source promotion is not by itself a formal product Release, stable-channel advance, or installed-version replacement

M10 canonical promotion remains complete. Normal development stays on `dev/zn-agent` or isolated work branches. Coherent low-risk stages may be promoted through traceable PR/merge flow when the repository promotion gate is truly green. High-risk boundaries remain human-approved.

Founding boundary:

> **ZN uses models. Models do not own ZN.**

## Stage summary

- P1 shared side-effect-attempt persistence owner: **COMPLETE / CI VERIFIED**
- P2 bounded cumulative accounting/learning durability: **COMPLETE / CI VERIFIED**
- P3 managed-browser frontier reconciliation: **COMPLETE / CI VERIFIED NARROW**
- P4 resident-owned live-page registry: **COMPLETE / CI VERIFIED NARROW**
- P5 durable Work checkpoint / restore foundation: **PARTIAL / TEN BOUNDED SLICES CI VERIFIED AT CODE HEAD; DOCS-HEAD CLOSEOUT PENDING**

Broader Work durability has **TWENTY-SEVEN concrete crash/restart windows closed and verified**. P5.9 and P5.10 are read-only inspection/proposal slices and add no mutation lifecycle, so they do not increment that crash-window count.

This does **not** mean general rollback/restore, arbitrary workspace snapshots, destructive restore application, restore approval authority, or installed-version rollback is complete.

## P5 verified bounded slices

### P5.1 - accepted Work ingress checkpoint (#19)

An accepted Work request is durably represented before resident-event creation, so restart can restore ingress without duplicating the resident event. Historical proof head: `2c20b8bded96ce07c6ec43263cc77b7bd10a7a82`.

### P5.2 - ordinary overwrite effect-present recovery (#20)

After a durable overwrite attempt exists, restart never blindly repeats it. Exact intended current text resolves `verified_effect`; mismatch/read failure remains outside-world uncertainty and preserves the target. Historical proof head: `c4276f8b151d2c45b69368cb414f012bf0644d01`.

### P5.3 - overwrite pre-dispatch identity guard (#21)

If restart occurs before Body attempt creation, exact unchanged target identity may continue the inherited fresh lifecycle; drift returns to Investigation without mutation. Once a durable attempt exists, old-state equality can never authorize replay. Historical proof head: `97803f8d0616c1f2b30a61af5acc686f1256cd11`.

### P5.4 - Windows staged atomic overwrite (#22)

Active exact overwrite writes a complete same-directory stage, flushes/fsyncs it, then uses Windows namespace replacement rather than truncation-first overwrite. Historical implementation `b3cf799ec24d8f4bb89d82752c2396e70cc6a233`; proof descendant `403ac14f04866380a0d32c74bd9e250226dbb780`.

### P5.5 - durable staged-overwrite precommit reconciliation (#23)

Durable atomic-overwrite protocol state binds event, Body signature, intent, attempt, deterministic stage/backup paths, exact stage identity, protocol version, and `namespace_commit_started`. Restart may grant a fresh lifecycle only when all retained and freshly observed evidence agrees. Ambiguity fails closed. Historical proof head: `a006ee90c9fc6e53f4b90d09f69b64ebf7ffd4c1`.

### P5.6 - commit-start namespace reconciliation and verified-effect cleanup (#24)

Post-commit namespace evidence never becomes stale-attempt replay authority. Exact retained `ReplaceFileW` split evidence remains replay-blocked; independently verified intended target content may resolve `verified_effect`; cleanup requires exact retained ownership evidence. Historical proof chain includes `042e196418d8c4e9baa17d810b60d995007dc5b0` and zero-byte hardening `75e50c243b44e347c0e549fa9cb4cf7b37716e9f`.

### P5.7 - restart-safe retained namespace repair (#25, #26)

A proven retained namespace split creates a new bounded repair lifecycle rather than replaying the stale overwrite attempt. Immediately before mutation ZN revalidates target-missing + exact-stage-new + exact-backup-old reality. External target appearance wins. Historical implementation/hardening chain includes `47bcf6279a0d907ece7f7cda3221f5678efe99ab`, `fb8864f6934dc38c4f83fcce66b30b0212e55cc5`, and `099a1af7615e79fe34317f22d5c785aa46cba2b4`.

### P5.8 - Work-owned exact-file restore-point foundation (#27)

Before an eligible Work-owned existing-file overwrite can dispatch to Body, ZN retains exact pre-mutation bytes in the kernel database. Creation requires exact active durable `work_runs` ownership; forged, missing, conflicting, non-Work, or finalized linkage cannot create restore content or authorize the overwrite.

Current retained scope is intentionally narrow: stable regular file, complete SHA-256 identity, at most 8 MiB, and matching pre/post capture identity. Capacity exhaustion blocks the incoming restorable overwrite before mutation rather than deleting older rollback material.

The restore point is retained content ownership, **not rollback authority**. `automatic_restore_authority` remains false and retained bytes are never written back by this slice.

Historical exact proof head: `48bfe13ba6783184292e871ebbc62a895db47d1c`.

### P5.9 - read-only Work restore-point inspection

P5.9 was promoted to canonical `main` in PR #7. Read-only inspection owner:

```text
runtime/python/zn_agent/core/work_restore_point_inspection_resident.py
```

The active resident chain is:

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

Inspection revalidates exact durable Work event/thread/message ownership and freshly observes the target before classifying it as `unchanged`, `changed`, `missing`, or `unsupported`.

The public projection excludes retained content BLOBs, content hashes, action signatures, intent identity, and the private pre-identity record. Every projected point keeps `automatic_restore_authority: False` and `restore_application_available: False`.

The desktop reuses detailed `workGet`; recurring Work list refresh remains lightweight and does not repeatedly hash restore targets. Restore observations are transient and stripped from browser localStorage. The UI exposes status and Refresh only, with no Restore/Apply control.

Historical P5.9 exact full-tree proof descendant: `a59380d5a70c79ea8fd1e759c537d2245beafdff`, ZN CI run `33174294153` success. Canonical P5.9 source promotion commit on `main`: `5ff8331ba1e44090b2cec9ca1ed8715c33196580`.

### P5.10 - non-mutating restore proposal / eligibility contract

P5.10 builds on P5.9 and adds a user-visible **proposal**, not restore authority. The proposal is freshly derived only after exact Work ownership validation and current target observation.

For an exact retained file restore point the proposal currently classifies:

- `unchanged` -> `blocked`, reason `current_target_already_matches_retained_prestate`;
- `changed` -> `conflict_review_required`, reason `current_target_changed_since_restore_point`;
- `missing` -> `missing_target_review_required`, reason `current_target_is_missing`;
- `unsupported` -> `blocked`, reason `current_target_cannot_be_compared_safely`.

Every proposal explicitly records:

```text
kind = restore_exact_file
destructive = true
requires_user_approval = true
requires_fresh_revalidation = true
application_available = false
automatic_authority = false
```

This contract does not create a restore command, Apply button, writeback path, approval token, or automatic authority. It cannot mutate the target. Retained bytes and private identity evidence remain resident-owned.

Ownership is fail-closed twice: the retained row must agree with the durable Work run, and the resident event payload/task linkage must agree with the same Work ownership. Forged Work ownership or forged resident-event ownership raises instead of producing an apparently safe proposal.

The proposal is re-derived after resident reconstruction from durable retained ownership plus fresh outside-world target reality. Stale UI observation is not persisted as authority.

Focused tests cover unchanged/changed/missing/unsupported reality, restart re-derivation, private-data exclusion, forged Work ownership, and forged resident-event ownership.

#### Real CI proof for P5.10 code head

Exact code/proof head:

```text
2fe96e46396c0cda8d618ad342b1196519e96e7b
```

Focused Windows Work recovery proof:

```text
ZN Work Recovery E2E run 33183092342             success
Windows resident Work restart recovery           success
Ran 108 tests in 87.381s                         OK
```

Full-tree proof on the same exact head:

```text
ZN CI run 33183092366                             success
ZN Source Boundary / Windows                     success
Electron / TypeScript / Windows                  success
ZN Kernel / Python / Windows                     success
  Ran 686 tests in 610.053s                      OK (skipped=5)
Publish Windows CI statuses                      success
```

An earlier focused run on `26bf1b9a430f29aa7fdb8415cbc46e6b7f330fa7` exposed a Windows-only test resource leak: the forged-ownership test left a SQLite handle open, causing `TemporaryDirectory` cleanup to fail with `WinError 32`. Commit `2fe96e46396c0cda8d618ad342b1196519e96e7b` changed the test connection to explicit closing. The failure was fixed and re-run; it was not waived or bypassed.

No local repository test run is claimed for this web-maintainer stage. Repository self-hosted Windows CI is the execution authority.

Because P5.10 is read-only, it adds no new crash/restart mutation window. The count remains 27.

## Current restore/recovery invariants

1. Old-state equality after dispatch is never stale-attempt replay authority.
2. `namespace_commit_started=true` never authorizes replay of the old overwrite attempt.
3. Retained namespace repair is a new bounded lifecycle with fresh exact evidence.
4. External target appearance wins over repair; ZN does not clobber it.
5. Stage/backup drift withdraws repair or cleanup authority.
6. Work restore capture requires an exact active durable Work run, not merely claimed payload linkage.
7. A retained restore point proves exact captured pre-mutation content ownership only; it grants no automatic restore authority.
8. Capture-time file drift withdraws overwrite authority.
9. Capacity exhaustion blocks the incoming restorable overwrite rather than deleting older rollback evidence.
10. Missing/unsupported/too-large targets are not claimed restorable.
11. Raw restore content stays resident-owned in the kernel DB and is not exposed by metadata, inspection, or proposal projection.
12. Read-only inspection and proposal derivation must revalidate exact Work ownership.
13. Current-target inspection is fresh observation, not restore authority.
14. The recurring Work list does not perform restore-target hashing; detailed `workGet` / explicit refresh owns inspection.
15. Desktop restore-point observations are transient and are not persisted in browser localStorage.
16. A restore proposal is informational only; `requires_user_approval` is a prerequisite declaration, not an approval grant.
17. Actual restore application remains a separate destructive authority/lifecycle problem.

## Relevant files

- `runtime/python/zn_agent/core/file_identity.py`
- `runtime/python/zn_agent/core/side_effect_attempts.py`
- `runtime/python/zn_agent/core/side_effect_body.py`
- `runtime/python/zn_agent/core/overwrite_recovery_resident.py`
- `runtime/python/zn_agent/core/atomic_overwrite_protocols.py`
- `runtime/python/zn_agent/core/staged_text_write.py`
- `runtime/python/zn_agent/core/atomic_overwrite_resident.py`
- `runtime/python/zn_agent/core/atomic_overwrite_namespace_recovery_resident.py`
- `runtime/python/zn_agent/core/work_restore_point_resident.py`
- `runtime/python/zn_agent/core/work_restore_point_inspection_resident.py`
- `runtime/python/zn_agent/core/recovery_bounded_resident.py`
- `runtime/python/zn_agent/core/provider_bridge.py`
- `runtime/python/zn_agent/core/work_control.py`
- `runtime/python/zn_agent/core/work.py`
- `tests/zn_agent/core/test_work_overwrite_recovery.py`
- `tests/zn_agent/core/test_windows_atomic_overwrite.py`
- `tests/zn_agent/core/test_windows_atomic_overwrite_namespace_recovery.py`
- `tests/zn_agent/core/test_windows_atomic_overwrite_namespace_repair.py`
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
- `.github/workflows/zn-atomic-overwrite-e2e.yml`
- `.github/workflows/zn-work-recovery-e2e.yml`

## Open risks / incomplete work

P5 remains **PARTIAL**. Still open:

- actual destructive restore application/writeback is not implemented;
- commit-time target revalidation for destructive restore is not implemented;
- explicit approval/authority lifecycle is not implemented;
- post-restore verification, crash semantics, and failure semantics are not implemented;
- current proposal is informational and grants no restore authority;
- general per-task rollback and arbitrary workspace snapshots remain open;
- there is no general startup/maintenance GC owner for deterministic artifacts outside an exact active protocol;
- files larger than the exact capture limit and incomplete identities remain non-restorable/fail-closed for this path;
- replacement changes file identity; uncommon metadata/named-stream behavior and host/power-loss durability remain open;
- isolated parallel Work remains open;
- broader browser, M8 continuity, and SM1+ work remains incomplete;
- identity, long-term memory, credentials/permissions, updater/rollback/signing/release trust, destructive restore, destructive migrations, installed-version replacement, and self-maintenance approval-rule changes remain human-approval boundaries.

## Next real target

First, close this P5.10 source stage with exact documentation-head CI, final diff review, and normal traceable low-risk promotion into canonical `main` if the gate remains green. Do not turn source promotion into a formal Release, stable-channel advance, updater activation, or installed-version replacement.

After promotion, the next safe P5 target is a **non-mutating restore approval/authority-boundary contract**. It should define what an explicit user approval would need to bind to (restore point, Work ownership, target identity, freshness window, and one exact proposed operation) while still granting **no writeback authority** and performing no destructive restore.

Actual restore application, commit-time destructive revalidation, writeback, rollback semantics, post-restore verification, and crash recovery for that mutation remain a separately reviewed human-approved slice.

Normal development remains on `dev/zn-agent` or isolated work branches. Verified coherent stages should continue to use traceable PR/promotion flow into `main`; a `main` merge is canonical source maintenance, not by itself a formal product Release.