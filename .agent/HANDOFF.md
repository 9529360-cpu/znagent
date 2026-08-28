# ZN Maintainer Handoff

Updated: 2026-08-28

This is an operational maintainer handoff, not a chat summary. Real repository state and CI remain authoritative.

## Current goal

P5.8 exact-file Work restore-point foundation is implemented and CI verified. The next bounded implementation target is a **read-only Work restore-point projection/inspection path**: expose retained restore metadata through resident-owned Work control, re-observe current target reality, and do not implement destructive restore application yet.

In parallel, keep the repository promotion ledger honest. `main` is the canonical source/release branch and must not be developed on directly, but it also must not remain permanently frozen after coherent verified stages. Normal low-risk promotion follows repository gates; high-risk boundaries retain explicit human approval.

Founding boundary:

> **ZN uses models. Models do not own ZN.**

## Branch / repository state

- repository: `9529360-cpu/znagent`
- development branch: `dev/zn-agent`
- canonical branch: `main`
- canonical `main` HEAD: `8234a835dea604783cea0bd9d28a40de654ec03d`
- exact P5.8 code/proof HEAD: `48bfe13ba6783184292e871ebbc62a895db47d1c`
- maintenance-prompt policy commit: `251508d06c8974aa342f61b36fef8d8cac1b74b2`
- P5.8 implementation-status sync: `4ba0dfcba8c5af178b18b86a5ade539f7e455838`
- ZN development-contract promotion alignment: `58d416f0527d191f4a752290375d3814ce8be484`
- AGENTS promotion alignment: `934de7ab19174de5ca1fe81494c9f3ca565f4c97`
- self-maintenance promotion alignment immediately before this handoff: `7c27d84a3e60e706d4b26662254a89d5322b52ed`
- PR #6: `dev/zn-agent` -> `main`, open, draft, mergeable at last check
- immediately before the latest alignment commits, dev was 468 commits ahead of main and 0 behind; re-check exact count before promotion because each documentation sync advances dev
- `main` has not been modified during this alignment work
- no force push or history rewrite was performed

This file intentionally does not self-reference its own final commit SHA. Re-read the actual branch HEAD before the next write or promotion decision.

## Completed in P5.8

Active owner:

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

Before an eligible Work-owned existing-file overwrite can dispatch, ZN now retains exact pre-mutation bytes in durable `work_restore_points` storage.

The restore point binds:

- deterministic restore-point ID;
- exact event/thread/message Work ownership;
- intent and action signature;
- canonical target path;
- exact pre-mutation file identity;
- raw old content BLOB;
- SHA-256 and byte size;
- retained status and timestamps.

Creation requires a matching durable `work_runs` row with exact event/thread/message/task linkage and `ledger_state='active'`. Non-Work, forged, missing, conflicting, or finalized Work linkage cannot create restore content or authorize the overwrite.

Current exact capture scope is intentionally narrow:

- existing stable regular file;
- complete SHA-256 identity;
- size at most 8 MiB;
- captured bytes match durable prestate size/hash;
- fresh identity after the read still exactly matches the prestate.

Capture-time drift withdraws mutation authority and returns to Investigation.

The restore point is not restore authority. Active state explicitly records:

```text
automatic_restore_authority: False
```

P5.8 never writes retained bytes back to the target.

Retention is bounded without destructive pruning:

- max 32 points per event;
- max 256 points resident-wide;
- max 128 MiB retained content total;
- max 8 MiB per captured file.

If capacity is exhausted, ZN preserves existing rollback material and blocks the new exact Work overwrite before Body mutation. It does not delete an older restore point to make room.

`retained_work_restore_points(event_id)` returns metadata only and does not expose the raw retained BLOB.

## P5 status

P5 is **PARTIAL / EIGHT BOUNDED SLICES CI VERIFIED**.

Concrete crash/restart windows closed and verified: **27**.

New window **#27**: process death after durable restore-point commit but before Body dispatch/mutation. The target remains unchanged, resident reconstruction retains the same restore point, and restart does not manufacture automatic rollback authority.

Additional P5.8 hardening covers capture identity drift, forged Work linkage, finalized Work runs, retention capacity, and non-Work exclusion. These are safety guards, not separately counted crash windows.

Do not describe P5 as general rollback/restore complete.

## Real test / CI result

Exact code/proof head:

```text
48bfe13ba6783184292e871ebbc62a895db47d1c
```

Focused Windows Work recovery CI:

```text
ZN Work Recovery E2E run 33166734152  success
Windows resident Work restart recovery    success
Ran 102 tests in 75.017s                  OK
```

Full-tree Windows CI on the same exact head:

```text
ZN CI run 33166734199                    success
ZN Kernel / Python / Windows             success
  isolated no-model boot                 success
  compile resident core                  success
  Ran 680 tests in 853.298s              OK (skipped=5)
ZN Source Boundary / Windows             success
  active tracked tree remains ZN-only    success
Electron / TypeScript / Windows          success
  npm audit high                         0 vulnerabilities
  typecheck / bundle                     success
  Electron contract tests                37 passed
  release/runtime script tests           8 passed
Publish Windows CI statuses              success
```

The later maintenance/documentation alignment commits are documentation-only descendants. The GitHub connector returned no PR-triggered workflow run for `251508d...`; do not claim those documentation descendants as independently code-CI-proven. Runtime proof remains `48bfe13...`.

No local repository test execution is claimed for this web-maintainer slice. Repository self-hosted Windows CI is the verification authority.

## Promotion policy now aligned

The following repository contracts now distinguish direct development from verified promotion:

- `ZN.md`;
- `AGENTS.md`;
- `docs/ZN-MAINTAINER-PROMPT.md`;
- `docs/ZN-SELF-MAINTENANCE.md`.

Normal rule:

```text
develop / investigate on dev or work branch
→ complete coherent claimed stage
→ relevant tests + full CI / required E2E
→ review diff
→ align status docs + HANDOFF
→ confirm no unresolved blocker or high-risk approval boundary
→ normal traceable PR / merge / promotion
→ main becomes new verified canonical source
```

Do not require a chat-only approval sentence for every ordinary low-risk promotion after those repository gates are genuinely satisfied. Do not use this rule to bypass explicit human approval for identity, long-term memory, destructive migrations, credentials/permissions, updater/rollback/signing trust, self-maintenance approval rules, or replacement of the user's installed formal version.

Force push, history rewrite, disabled CI, bypassed failed checks, and false completion claims are never normal promotion.

## Relevant files

- `ZN.md`
- `AGENTS.md`
- `docs/ZN-MAINTAINER-PROMPT.md`
- `docs/ZN-IMPLEMENTATION-STATUS.md`
- `docs/ZN-SOURCE-EXTRACTION.md`
- `docs/ZN-SELF-MAINTENANCE.md`
- `.agent/HANDOFF.md`
- `runtime/python/zn_agent/core/work_restore_point_resident.py`
- `runtime/python/zn_agent/core/recovery_bounded_resident.py`
- `runtime/python/zn_agent/core/provider_bridge.py`
- `runtime/python/zn_agent/core/work_control.py`
- `runtime/python/zn_agent/core/work.py`
- `tests/zn_agent/core/test_work_restore_points.py`
- `tests/zn_agent/core/test_work_restore_point_guards.py`
- `tests/zn_agent/core/test_work_restore_point_retention.py`
- `tests/zn_agent/core/test_work_restore_point_active_run.py`
- `.github/workflows/zn-work-recovery-e2e.yml`

## Risks / blockers

No known P5.8 implementation CI blocker.

Open technical/product work:

- restore-point metadata is not yet projected through `work_control.py` / Work UI;
- actual restore application is not implemented;
- current-target drift/eligibility semantics for a future restore proposal are not yet exposed to users;
- arbitrary workspace snapshots and general per-task rollback remain open;
- retained restore points have bounded capacity but no destructive automatic GC policy, intentionally;
- files above the exact capture limit and incomplete identities are not claimed restorable;
- uncommon Windows metadata/named-stream and host/power-loss durability remain open;
- isolated parallel Work remains open;
- broader browser, M8 continuity, and SM1+ remain incomplete;
- identity, long-term memory, credentials/permissions, updater/signing, destructive rollback, destructive self-maintenance, and installed-version replacement remain explicit human-approval boundaries.

Repository promotion also requires a separate review of the accumulated post-M10 PR scope. PR #6 contains hundreds of commits and touches release/update and other broad product areas; being mergeable and having a green code proof does not by itself prove the whole accumulated PR is a low-risk automatic promotion. Inspect the actual accumulated diff and high-risk boundaries before changing `main`.

No secret, token, password, signing key, or production credential belongs in this file.

## Task queue

1. Re-read exact dev/main HEAD, PR #6, latest CI, and this handoff before the next implementation or promotion decision.
2. Update PR #6 body to P5.8 / eight slices / 27 windows and current promotion policy.
3. Re-check the accumulated PR #6 diff specifically for high-risk promotion boundaries before any `main` merge.
4. Continue P5 with a read-only restore-point projection in `work_control.py` / Work snapshot surface.
5. Expose metadata only; do not expose raw restore BLOB by default.
6. Re-observe the current target and report read-only eligibility reality such as unchanged / changed / missing / unsupported without performing restore.
7. Add ownership, privacy, restart, and target-drift tests for the projection.
8. Run focused Work recovery CI and full `ZN CI`; fix failures before claiming the next slice complete.
9. Update implementation status and this HANDOFF after exact-head proof.
10. Keep actual destructive restore application as a later bounded authority slice with explicit drift handling and appropriate user approval.

## Next real target

Read-only Work restore-point projection: exact Work ownership -> retained metadata projection -> fresh target re-observation -> restart-safe user-visible inspection, with **no restore mutation** in this slice.
