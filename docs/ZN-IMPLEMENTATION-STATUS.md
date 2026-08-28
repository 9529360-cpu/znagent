# ZN Implementation Status

Updated: 2026-08-28

This file records implementation truth for the active ZN product. Source code, Git state, tests, and CI remain authoritative over this document.

## Repository truth

- repository: `9529360-cpu/znagent`
- development branch: `dev/zn-agent`
- canonical source branch: `main`
- canonical `main` after PR #6 promotion: `b9820e6a56b20bc3e9eb5b431d0aab6bedc39438`
- promoted PR head: `40111a97f5335cee6678d6e18375543a01baa6bb`
- latest exact P5 code/proof head: `48bfe13ba6783184292e871ebbc62a895db47d1c`
- PR #6 was merged on 2026-08-28 through the normal traceable merge flow
- `dev/zn-agent` was then non-force fast-forwarded to the merge commit; no force push or history rewrite was performed
- GitHub Releases were confirmed empty during this stage; canonical source promotion is not a formal product release
- a documentation closeout commit on `dev/zn-agent` follows the merge and may make dev narrowly ahead again as normal development resumes

M10 canonical promotion remains complete. `main` is canonical source and the future release source, but a commit entering `main` does **not** by itself mean ZN has been formally released as a product. Normal development stays on `dev/zn-agent` or isolated work branches. Coherent verified stages should be promoted rather than leaving canonical `main` indefinitely stale. High-risk boundaries remain human-approved.

### PR #6 promotion closeout

The accumulated post-M10 promotion covered 473 commits and 185 changed files. The review explicitly covered approval-sensitive source areas including durable nervous/event-outcome retention semantics, self-maintenance approval/promotion rules, release-workflow source, Windows CI topology, and the P5 restore-point foundation. Explicit human authorization was provided for this accumulated source promotion after those boundaries were identified.

That authorization was limited to repository source promotion. It did not authorize a formal GitHub Release, stable-channel advance, signing/credential changes, updater activation, installed-version replacement, or future destructive restore application.

Exact pre-merge PR-head full CI:

```text
ZN CI run 33168732659                    success
head                                     40111a97f5335cee6678d6e18375543a01baa6bb
ZN Source Boundary / Windows             success
Electron / TypeScript / Windows          success
ZN Kernel / Python / Windows             success
Publish Windows CI statuses              success
```

Post-merge `main` CI run `33170354975` initially encountered a runner environment failure in Kernel before ZN tests started: the isolated uv/Python build environment on `zn-ci-01` raised an `importlib.metadata` partial-initialization error. Source Boundary and Electron succeeded. The failed Kernel job was re-run rather than bypassed. On the retry, the same runner successfully completed Python preparation, no-model boot, and resident compile and entered the full core-test step. A same-SHA dev run also successfully prepared/booted/compiled and entered core tests on another runner. At the time of this status write those core-test executions are still in progress, so post-merge CI is **not yet claimed fully green**.

Founding boundary:

> **ZN uses models. Models do not own ZN.**

## Stage summary

- P1 shared side-effect-attempt persistence owner: **COMPLETE / CI VERIFIED**
- P2 bounded cumulative accounting/learning durability: **COMPLETE / CI VERIFIED**
- P3 managed-browser frontier reconciliation: **COMPLETE / CI VERIFIED NARROW**
- P4 resident-owned live-page registry: **COMPLETE / CI VERIFIED NARROW**
- P5 durable Work checkpoint / restore foundation: **PARTIAL / EIGHT BOUNDED SLICES CI VERIFIED**

Broader Work durability now has **TWENTY-SEVEN concrete crash/restart windows closed and verified**. P5.8 adds one new concrete crash/restart boundary; its additional drift, ownership, capacity, and finalized-run tests are safety hardening and are not counted as separate crash windows.

This does **not** mean general rollback/restore, arbitrary workspace snapshots, or user-visible restore application is complete.

## P5 verified bounded slices

### P5.1 - accepted Work ingress checkpoint (#19)

Proof head `2c20b8bded96ce07c6ec43263cc77b7bd10a7a82`.

An accepted Work request is durably represented before resident-event creation, so restart can restore ingress without duplicating the resident event.

### P5.2 - ordinary overwrite effect-present recovery (#20)

Proof head `c4276f8b151d2c45b69368cb414f012bf0644d01`.

After a durable overwrite attempt exists, restart never blindly repeats it. Exact intended current text resolves `verified_effect`; mismatch/read failure remains outside-world uncertainty and preserves the target.

### P5.3 - overwrite pre-dispatch identity guard (#21)

Proof head `97803f8d0616c1f2b30a61af5acc686f1256cd11`.

If restart occurs before Body attempt creation, exact unchanged target identity may continue the inherited fresh lifecycle; drift returns to Investigation without mutation. Once a durable attempt exists, old-state equality can never authorize replay.

### P5.4 - Windows staged atomic overwrite (#22)

Implementation `b3cf799ec24d8f4bb89d82752c2396e70cc6a233`; proof descendant `403ac14f04866380a0d32c74bd9e250226dbb780`.

Active exact overwrite writes a complete same-directory stage, flushes/fsyncs it, then uses Windows namespace replacement rather than truncation-first overwrite. The target is not partially truncated by process death while staging.

### P5.5 - durable staged-overwrite precommit reconciliation (#23)

Implementation/proof head `a006ee90c9fc6e53f4b90d09f69b64ebf7ffd4c1`.

Durable owner `runtime/python/zn_agent/core/atomic_overwrite_protocols.py` stores an atomic-overwrite protocol independent of `WorkingState`, binding event, Body signature, intent, attempt, deterministic stage/backup paths, exact stage identity, protocol version, and `namespace_commit_started`.

Restart may close the old attempt `verified_absent` and grant a fresh lifecycle only when matching protocol/attempt, complete stage-ready evidence, `namespace_commit_started=false`, exact target prestate, exact durable stage identity, and absent deterministic backup all agree. Ambiguity remains fail-closed.

### P5.6 - commit-start namespace reconciliation and verified-effect artifact cleanup (#24)

Base implementation/proof head `042e196418d8c4e9baa17d810b60d995007dc5b0`; zero-byte identity hardening descendant `75e50c243b44e347c0e549fa9cb4cf7b37716e9f`.

The namespace layer owns post-commit namespace evidence without converting that evidence into stale-attempt replay authority. Exact `ReplaceFileW` WinError `1177` split evidence is retained and replay-blocked. Independently verified intended target content may resolve `verified_effect`; exact retained artifacts may be cleaned only under checkpointed identity ownership. Zero-byte content remains valid exact evidence only with complete size + SHA-256 identity.

### P5.7 - restart-safe retained namespace repair (#25, #26)

Runtime implementation:

```text
47bcf6279a0d907ece7f7cda3221f5678efe99ab  fix: repair retained overwrite namespace
```

Race/drift hardening:

```text
fb8864f6934dc38c4f83fcce66b30b0212e55cc5  test: harden retained namespace repair races
099a1af7615e79fe34317f22d5c785aa46cba2b4  test: tolerate Windows path aliases in repair race
```

A proven retained `1177` split creates a new durable namespace-repair lifecycle rather than replaying the stale overwrite attempt. Immediately before mutation ZN revalidates target-missing + exact-stage-new + exact-backup-old reality and uses Windows no-replace movement. An external target winner is preserved.

Crash/restart window **#25** is death after durable repair checkpoint but before movement. Window **#26** is death after the retained stage has moved into target but before repair completion/cleanup state is durably advanced. Restart never repeats a proven move and never replays the stale overwrite attempt.

### P5.8 - Work-owned exact-file restore-point foundation (#27)

Implementation chain:

```text
448bbbd48d0b8454282860617152005361732dda  feat: persist Work overwrite restore points
15e732119844866538614189442ea2e40e40a549  feat: route active resident through Work restore points
0cf4bef527d479df149449def51a6a4f30ccf0e7  fix: retain rollback points without pruning
ea08b0b1c1d5d8dd2147befea1ff8c3ea7feca6e  fix: bind restore points to active Work runs
48bfe13ba6783184292e871ebbc62a895db47d1c  exact CI proof descendant
```

Active restore owner:

```text
runtime/python/zn_agent/core/work_restore_point_resident.py
```

The active runtime chain is now:

```text
provider_bridge
-> RecoveryBoundedResidentRuntime
-> WorkRestorePointResidentRuntime
-> AtomicOverwriteNamespaceRecoveryResidentRuntime
-> AtomicOverwriteRecoveryResidentRuntime
-> OverwriteRecoveryResidentRuntime
-> DurableBodyAccountingResidentRuntime
-> CapabilityRecoveryResidentRuntime
-> resident core
```

Before an eligible Work-owned existing-file overwrite can dispatch to Body, ZN retains exact pre-mutation bytes in the kernel database. The durable `work_restore_points` record binds a deterministic restore-point identity to the event, thread, message, intent, action signature, canonical target path, exact pre-mutation identity, raw content BLOB, content SHA-256, size, status, and timestamps.

Restore ownership is deliberately stricter than event payload alone. Creation requires a matching durable `work_runs` row whose event/thread/message/task linkage agrees and whose `ledger_state` is exactly `active`. Non-Work events do not create restore points. Forged, missing, conflicting, or finalized Work linkage cannot create restore content or authorize the overwrite.

Current restorable scope is intentionally narrow:

- the target already exists;
- it is a stable regular file;
- its full SHA-256 identity is complete;
- its exact content is at most `DEFAULT_MAX_HASH_BYTES` (currently 8 MiB);
- the bytes read for retention match both the durable prestate size/hash and a fresh post-read identity observation.

If file reality changes while capture is occurring, mutation authority is withdrawn and the resident returns to Investigation. Missing targets and unsupported file shapes preserve their previous overwrite behavior but are **not** represented as restorable.

Restore-point identity is deterministic from event + action signature + target path. Existing durable rows are fully revalidated before reuse, so preparation is idempotent across inherited lifecycle calls and resident reconstruction.

The restore point is content ownership, **not rollback authority**. The active checkpoint records `automatic_restore_authority: False`. P5.8 never writes retained bytes back to the target and never interprets restart as permission to restore automatically.

Retention is bounded without destructive pruning:

- maximum 32 retained points per event;
- maximum 256 retained points resident-wide;
- maximum 128 MiB total retained content;
- maximum 8 MiB for one exact captured file.

An earlier implementation attempt pruned older finalized points to make capacity. That was rejected because it could delete the only rollback material. The active implementation never deletes an old restore point merely to admit a new one. If capacity is exhausted, the new exact Work overwrite is blocked **before mutation** with `capacity_blocked` and returns to Investigation.

`retained_work_restore_points(event_id)` exposes bounded metadata and does not return the raw retained BLOB.

Crash/restart window **#27** is process death after the exact restore point has been durably committed but before Body dispatch/mutation. The focused test injects process termination at dispatch, proves the target is still unchanged, reconstructs the resident, and proves the same restore point remains retained without becoming automatic restore authority.

Additional P5.8 hardening proves:

- capture-time identity drift withdraws mutation authority;
- forged Work linkage fails closed;
- a finalized Work run cannot authorize new restore capture or mutation;
- retention capacity preserves existing rollback points and blocks the new overwrite rather than pruning them;
- non-Work overwrite does not create a Work restore point.

### Real CI proof for P5.8

Exact code/proof head:

```text
48bfe13ba6783184292e871ebbc62a895db47d1c
```

Focused Windows Work recovery proof:

```text
ZN Work Recovery E2E run 33166734152             success
  Windows resident Work restart recovery          success
  Ran 102 tests in 75.017s                        OK
```

Full-tree proof on the same exact head:

```text
ZN CI run 33166734199                             success
  ZN Kernel / Python / Windows                    success
    Boot isolated ZN distribution without model  success
    Compile resident core                        success
    Run ZN core tests against working tree       success
    Ran 680 tests in 853.298s                    OK (skipped=5)
  ZN Source Boundary / Windows                    success
    active tracked tree remains ZN-only           success
  Electron / TypeScript / Windows                 success
    npm audit --audit-level=high                  0 vulnerabilities
    desktop typecheck / bundle                    success
    37 Electron contract tests                    passed
    8 release/runtime script tests                passed
  Publish Windows CI statuses                     success
```

The P5.8 runtime proof remains the exact `48bfe13...` evidence above. Later documentation/promotion descendants do not alter the P5.8 runtime implementation and are not substituted for that exact proof.

No local repository test run is claimed for this web-maintainer stage. Repository self-hosted Windows CI is the verification authority.

## Current restore/recovery invariants

1. Old-state equality after dispatch is never stale-attempt replay authority.
2. `namespace_commit_started=true` never authorizes replay of the old overwrite attempt.
3. Retained `1177` namespace repair is a new bounded lifecycle with fresh exact evidence.
4. External target appearance wins over repair; ZN does not clobber it.
5. Stage/backup drift withdraws repair or cleanup authority.
6. Work restore capture requires an exact active durable Work run, not merely claimed payload linkage.
7. A retained restore point proves exact captured pre-mutation content ownership only; it grants no automatic restore authority.
8. Capture-time file drift withdraws overwrite authority.
9. Capacity exhaustion blocks the incoming restorable overwrite rather than deleting older rollback evidence.
10. Missing/unsupported/too-large targets are not claimed restorable.
11. Raw restore content stays resident-owned in the kernel DB and is not exposed by the metadata projection.
12. General restore application remains a separate authority/lifecycle problem.

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
- `runtime/python/zn_agent/core/recovery_bounded_resident.py`
- `runtime/python/zn_agent/core/provider_bridge.py`
- `runtime/python/zn_agent/core/work_control.py`
- `runtime/python/zn_agent/core/work.py`
- `tests/zn_agent/core/test_work_overwrite_recovery.py`
- `tests/zn_agent/core/test_windows_atomic_overwrite.py`
- `tests/zn_agent/core/test_windows_atomic_overwrite_namespace_recovery.py`
- `tests/zn_agent/core/test_windows_atomic_overwrite_namespace_repair.py`
- `tests/zn_agent/core/test_work_restore_points.py`
- `tests/zn_agent/core/test_work_restore_point_guards.py`
- `tests/zn_agent/core/test_work_restore_point_retention.py`
- `tests/zn_agent/core/test_work_restore_point_active_run.py`
- `.github/workflows/zn-atomic-overwrite-e2e.yml`
- `.github/workflows/zn-work-recovery-e2e.yml`

## Open risks / incomplete work

P5 remains **PARTIAL**. Still open:

- user-visible restore-point inspection/projection is not yet connected through Work control/UI;
- actual restore application and its authority, target-drift handling, user confirmation, and post-restore verification are not implemented;
- general per-task rollback and arbitrary workspace snapshots remain open;
- there is no general startup/maintenance GC owner for deterministic artifacts outside an exact active protocol;
- files larger than the exact capture limit and incomplete identities remain non-restorable/fail-closed for this path;
- replacement changes file identity; uncommon metadata/named-stream behavior and host/power-loss durability remain open;
- generic `NativeBody` remains unchanged for non-active/shared callers;
- isolated parallel Work remains open;
- broader browser, M8 continuity, and SM1+ work remains incomplete;
- identity, long-term memory, credentials/permissions, updater/signing, destructive rollback and destructive self-maintenance remain human-approval boundaries.

## Next real target

First finish the post-promotion verification/doc closeout honestly; do not call the post-merge run green until its retry actually completes successfully.

Then continue P5 without jumping directly to destructive restore application. The next bounded target is a **read-only Work restore-point projection/inspection path**:

1. connect existing retained restore metadata to the resident-owned `work_control.py` / Work snapshot surface;
2. expose only metadata required to understand that a restore point exists; do not expose the raw retained BLOB by default;
3. bind projection to the exact Work event/thread ownership already enforced by the restore layer;
4. re-observe current target identity so future restore eligibility can distinguish unchanged, changed, missing, and unsupported reality without mutating anything;
5. add restart and privacy/ownership tests around that read-only projection;
6. design actual restore proposal/authority as a later bounded slice with explicit drift handling and user-visible approval where destructive replacement is involved.

Normal development remains on `dev/zn-agent` or isolated work branches. Verified coherent stages should continue to use traceable PR/promotion flow into `main`; a `main` merge is canonical source maintenance, not by itself a formal product Release.