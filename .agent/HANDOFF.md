# ZN Maintainer Handoff

Updated: 2026-08-28

This is an operational maintainer handoff, not a chat summary. Real repository state, code, tests, and CI remain authoritative.

## Current goal

P5.9 read-only Work restore-point inspection is implemented and verified. The next action is to close this stage with documentation, exact docs-head CI, and normal low-risk source promotion into canonical `main` if the promotion gate remains green.

This stage is source development only. It does not create a GitHub Release, advance the stable channel, replace an installed version, or grant destructive restore authority.

Founding boundary:

> **ZN uses models. Models do not own ZN.**

## Branch / repository state

- repository: `9529360-cpu/znagent`
- development branch: `dev/zn-agent`
- canonical source branch: `main`
- current canonical `main`: `b9820e6a56b20bc3e9eb5b431d0aab6bedc39438`
- current pre-closeout dev head: `a59380d5a70c79ea8fd1e759c537d2245beafdff`
- dev is 8 commits ahead of main and 0 behind before this documentation closeout
- PR #6 accumulated post-M10 promotion is complete
- post-merge main CI run `33170354975`, attempt 2: success
- no force push or Git history rewrite has been used

After this HANDOFF write, re-read the actual dev HEAD; the documentation closeout commit will make it one commit newer than the pre-closeout head above.

## P5 status

P5 remains **PARTIAL / NINE BOUNDED SLICES CI VERIFIED**, subject only to the documentation closeout commit receiving its own exact-head CI before promotion.

Concrete crash/restart windows closed and verified: **27**.

P5.9 is read-only and adds no mutation lifecycle, so it does not add a crash/restart window.

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

P5.9 owner:

```text
runtime/python/zn_agent/core/work_restore_point_inspection_resident.py
```

P5.9 provides a read-only inspection path for exact Work-owned retained restore points. It freshly re-observes the target and reports `unchanged`, `changed`, `missing`, or `unsupported` without writing retained content back.

The public inspection projection excludes the retained content BLOB, content hashes, private pre-identity record, intent identity, and action signatures. `automatic_restore_authority` and `restore_application_available` remain false.

The desktop uses the existing detailed `workGet` path. Ordinary recurring Work-list refresh remains the durable Work authority and does not repeatedly hash restore targets. Restore-point observation is transient and stripped from browser localStorage. The UI exposes status and Refresh only; it has no Restore/Apply action.

Actual destructive restore application is **not implemented** and remains a separate human-approved authority slice.

## Real test / CI evidence

Canonical promotion proof for PR #6:

```text
main merge commit                              b9820e6a56b20bc3e9eb5b431d0aab6bedc39438
post-merge ZN CI run 33170354975 attempt 2     success
ZN Kernel / Python / Windows                   success
Electron / TypeScript / Windows                success
ZN Source Boundary / Windows                   success
Publish Windows CI statuses                    success
```

P5.9 backend implementation head:

```text
ed000252db5b262e1954712a9679ed83653b89c5
ZN Work Recovery E2E #96 / 33172674061         success
ZN Atomic Overwrite E2E #10 / 33172674065      success
ZN CI #1107                                    success
```

P5.9 desktop/CI product head:

```text
0e806fe64109d3428a098ece7f2e59d409bd84a2
ZN Work Recovery E2E #97 / 33173759246         success
```

Latest exact full-tree proof descendant:

```text
a59380d5a70c79ea8fd1e759c537d2245beafdff
ZN CI #1110 / 33174294153                      success
ZN Kernel / Python / Windows                   success
Electron / TypeScript / Windows                success
ZN Source Boundary / Windows                   success
Publish Windows CI statuses                    success
```

Two intermediate full-CI runs exposed desktop contract mismatches. They were fixed rather than bypassed. The final exact-head run is green.

No local repository test run is claimed for this web-maintainer stage. Repository self-hosted Windows CI is the execution authority.

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
- `apps/desktop/src/zn/resident-client.ts`
- `apps/desktop/src/zn/state.ts`
- `apps/desktop/src/zn/workbench.tsx`
- `apps/desktop/electron/zn-restore-point-inspection.test.ts`
- `apps/desktop/electron/zn-desktop-ownership.test.ts`
- `.github/workflows/zn-ci.yml`
- `.github/workflows/zn-work-recovery-e2e.yml`

## Risks / blockers

No known P5.9 product blocker remains at the pre-closeout implementation head.

Before claiming this stage fully closed/promoted, the documentation closeout commit itself still needs exact-head ZN CI and a final diff/repository-state check.

Still incomplete:

- actual restore application/writeback;
- commit-time target revalidation for destructive restore;
- restore approval/authority lifecycle;
- post-restore verification and failure semantics;
- arbitrary workspace snapshots/general per-task rollback;
- isolated parallel Work;
- broader browser/M8 continuity and SM1+ work.

Human approval remains required for identity, long-term memory destructive changes, credentials/permissions, updater/rollback/signing/release trust, self-maintenance approval-rule changes, destructive restore, destructive migrations, and installed-version replacement.

No secret, token, password, signing key, or production credential belongs in this file.

## Task queue

1. Commit this documentation closeout with `docs/ZN-IMPLEMENTATION-STATUS.md` as one coherent commit on `dev/zn-agent`.
2. Run/observe exact docs-head ZN CI; do not call the closeout verified until it is green.
3. Re-check main/dev HEAD and full diff.
4. If the low-risk promotion gate remains satisfied, create/update a traceable PR and normally promote P5.9 source to `main`.
5. Verify post-merge `main` CI and non-force align `dev/zn-agent` with the merge commit if appropriate.
6. Keep formal Release/stable-channel/install actions out of this stage.
7. After promotion, begin a non-mutating restore proposal/eligibility contract.
8. Do not implement actual restore writeback without the separate human-approved destructive authority slice.

## Next real target

Close and promote P5.9, then build the **non-mutating restore proposal / eligibility contract**: exact Work ownership + retained metadata + fresh target reality -> clear user-visible proposal, still with no writeback and no automatic restore authority.
