# ZN Maintainer Handoff

Updated: 2026-08-28

This is an operational maintainer handoff, not a chat summary. Real repository state, code, tests, and CI remain authoritative.

## Current goal

The accumulated post-M10 source promotion is complete. PR #6 has been merged into canonical `main`, and `dev/zn-agent` was then fast-forwarded to the merge commit without force push or history rewrite.

ZN is still in product development. Repository source promotion to `main` is **not** a formal product release. No GitHub Release was created, no stable channel was advanced, and no installed user version was replaced.

The next bounded product implementation target remains P5 read-only Work restore-point projection/inspection. Do not implement destructive restore application in that slice.

Founding boundary:

> **ZN uses models. Models do not own ZN.**

## Branch / repository state

- repository: `9529360-cpu/znagent`
- development branch: `dev/zn-agent`
- canonical source branch: `main`
- promotion PR: #6, merged 2026-08-28
- pre-promotion `main`: `8234a835dea604783cea0bd9d28a40de654ec03d`
- promoted dev head: `40111a97f5335cee6678d6e18375543a01baa6bb`
- promotion merge commit: `b9820e6a56b20bc3e9eb5b431d0aab6bedc39438`
- exact P5.8 code/proof head: `48bfe13ba6783184292e871ebbc62a895db47d1c`
- immediately after merge, both `main` and `dev/zn-agent` were confirmed at `b9820e6a56b20bc3e9eb5b431d0aab6bedc39438`
- `dev/zn-agent` was advanced with a non-force fast-forward ref update
- no force push or Git history rewrite was performed
- GitHub Releases were confirmed empty during this maintenance stage

This handoff update itself is a new documentation commit on `dev/zn-agent`; re-read the actual dev HEAD after this write before the next stage.

## Completed promotion work

PR #6 promoted the accumulated post-M10 development rather than leaving canonical `main` hundreds of commits behind development indefinitely.

The promotion review covered 473 commits, 185 changed files, and broad runtime/browser/recovery/CI scope. Approval-sensitive source areas were explicitly reviewed before promotion, including:

- durable nervous/event-outcome retention semantics affecting long-term resident memory behavior;
- self-maintenance/promotion approval-rule changes;
- release workflow source changes;
- Windows self-hosted CI topology changes;
- P5 Work restore-point retention foundation.

Explicit human authorization was provided for this accumulated **source promotion** after those boundaries were identified. That authorization did not grant a formal product release, signing/credential changes, stable-channel advance, updater activation, installed-version replacement, or future destructive restore authority.

The merge used GitHub's normal merge flow with the expected PR head pinned. The resulting merge commit is GitHub-verified.

## P5 status

P5 remains **PARTIAL / EIGHT BOUNDED SLICES CI VERIFIED**.

Concrete crash/restart windows closed and verified: **27**.

P5.8 active owner:

```text
runtime/python/zn_agent/core/work_restore_point_resident.py
```

Active runtime chain:

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

P5.8 retains exact pre-mutation bytes for eligible Work-owned existing-file overwrites under exact active Work ownership and bounded capacity. It does **not** write those bytes back automatically. `automatic_restore_authority` remains false. Metadata projection does not expose the raw retained BLOB.

General rollback/restore and user-visible destructive restore application are not complete.

## Real test / CI evidence

Pre-promotion exact PR head:

```text
40111a97f5335cee6678d6e18375543a01baa6bb
```

Exact-head full CI:

```text
ZN CI run 33168732659                    success
ZN Source Boundary / Windows             success
Electron / TypeScript / Windows          success
ZN Kernel / Python / Windows             success
Publish Windows CI statuses              success
```

P5.8 focused proof:

```text
ZN Work Recovery E2E run 33166734152     success
exact P5.8 code/proof head                48bfe13ba6783184292e871ebbc62a895db47d1c
102 focused Work recovery tests           OK
```

P5.7 focused proof:

```text
ZN Atomic Overwrite E2E run 33163584755  success
```

Post-merge `main` CI on merge commit `b9820e6a56b20bc3e9eb5b431d0aab6bedc39438`:

- run `33170354975` initially had Source Boundary and Electron succeed;
- its first Kernel attempt failed before product tests, while preparing the isolated Python runtime on runner `zn-ci-01`;
- the failure was an environment/build-import error in the uv-managed Python/build environment (`importlib.metadata` partial initialization), not a failed ZN test assertion;
- a second CI run for the same exact SHA on `dev/zn-agent` successfully prepared the Python runtime, booted ZN without a model, compiled the resident core, and entered the full core-test step on another runner;
- the failed `main` Kernel job was explicitly re-run rather than ignored;
- on retry, the same `zn-ci-01` runner successfully passed Python environment preparation, no-model boot, and compile, then entered the full core-test step.

At the time of this handoff write, the post-merge Kernel retry/full core tests are still in progress. Therefore the post-merge `main` run must **not** yet be described as fully green.

No local repository test run is claimed for this web-maintainer stage. Repository Windows CI is the execution authority.

## Relevant files

- `ZN.md`
- `AGENTS.md`
- `docs/ZN-IMPLEMENTATION-STATUS.md`
- `docs/ZN-SOURCE-EXTRACTION.md`
- `docs/ZN-SELF-MAINTENANCE.md`
- `.agent/HANDOFF.md`
- `.github/workflows/zn-ci.yml`
- `.github/workflows/zn-release.yml`
- `runtime/python/zn_agent/core/event_outcome_nervous.py`
- `runtime/python/zn_agent/core/nervous_system.py`
- `runtime/python/zn_agent/core/work_restore_point_resident.py`
- `runtime/python/zn_agent/core/work_control.py`
- `runtime/python/zn_agent/core/work.py`

## Risks / blockers

No known source-promotion blocker remains: PR #6 is merged and canonical `main` contains the accumulated development.

Current verification caveat: post-merge `main` Kernel retry is still running. The first attempt's transient Python/uv environment failure remains in the CI history and has not been hidden or bypassed.

Technical/product work still open includes:

- read-only restore-point metadata is not yet projected through Work control/UI;
- current-target unchanged/changed/missing/unsupported eligibility is not yet exposed;
- actual restore application is not implemented;
- arbitrary workspace snapshots/general per-task rollback remain open;
- isolated parallel Work, broader browser/M8 continuity, and SM1+ remain incomplete;
- identity, long-term memory, destructive migrations, credentials/permissions, updater/rollback/signing/release trust, self-maintenance approval-rule changes, and installed-version replacement remain human-approval boundaries.

No secret, token, password, signing key, or production credential belongs in this file.

## Task queue

1. Re-check post-merge `main` run `33170354975` and same-SHA dev run `33170366270`; record their final real outcomes.
2. Reconcile `docs/ZN-IMPLEMENTATION-STATUS.md` with the completed PR #6 promotion and final post-merge CI result.
3. Re-check exact `main` and `dev/zn-agent` HEAD after documentation closeout.
4. Keep formal product Release/stable-channel/install actions out of this stage.
5. Continue P5 with a read-only restore-point projection through `work_control.py` / Work snapshot surfaces.
6. Expose metadata only, bind it to exact Work ownership, and freshly re-observe target reality.
7. Add ownership, privacy, restart, and target-drift tests.
8. Run focused Work recovery CI plus full ZN CI before claiming the next P5 slice complete.
9. Keep actual destructive restore application as a later bounded authority slice with explicit drift handling and appropriate human approval.

## Next real target

Finish the promotion verification/doc closeout, then implement the read-only Work restore-point projection: exact Work ownership -> retained metadata -> fresh target re-observation -> unchanged/changed/missing/unsupported inspection, with **no restore mutation**.