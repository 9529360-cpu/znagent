# ZN Maintainer Handoff

Updated: 2026-08-28

This is an operational maintainer handoff, not a chat summary. Real repository state and CI remain authoritative.

## Current goal

Continue P5 durable Work recovery above the now-closed Windows `ReplaceFileW` 1177 retained-namespace repair boundary. The next bounded goal is a resident-owned per-task restore-point foundation: begin with exact-file pre-mutation restore metadata tied to one Work run, without claiming arbitrary workspace snapshots or automatic rollback.

Founding boundary:

> **ZN uses models. Models do not own ZN.**

## Branch / repository state

- repository: `9529360-cpu/znagent`
- development branch: `dev/zn-agent`
- canonical branch: `main`
- canonical `main` HEAD: `8234a835dea604783cea0bd9d28a40de654ec03d`
- latest code/proof HEAD before documentation sync: `099a1af7615e79fe34317f22d5c785aa46cba2b4`
- runtime P5.7 implementation: `47bcf6279a0d907ece7f7cda3221f5678efe99ab` (`fix: repair retained overwrite namespace`)
- race/drift hardening: `fb8864f6934dc38c4f83fcce66b30b0212e55cc5` (`test: harden retained namespace repair races`)
- exact proof descendant: `099a1af7615e79fe34317f22d5c785aa46cba2b4` (`test: tolerate Windows path aliases in repair race`)
- implementation-status sync commit immediately before this handoff: `6c81b247d2371eedc7b2c500247e1c254d7d7713`
- draft PR: #6, `dev/zn-agent` -> `main`
- `main` was not modified
- no force push or history rewrite was performed

Re-read `dev/zn-agent` after this handoff commit before starting the next implementation slice. This file intentionally does not self-reference its own final commit SHA.

## Completed in P5.7

The active runtime chain is:

```text
provider_bridge
-> RecoveryBoundedResidentRuntime
-> AtomicOverwriteNamespaceRecoveryResidentRuntime
-> AtomicOverwriteRecoveryResidentRuntime
-> OverwriteRecoveryResidentRuntime
-> DurableBodyAccountingResidentRuntime
-> CapabilityRecoveryResidentRuntime
-> resident core
```

Active repair owner:

```text
runtime/python/zn_agent/core/atomic_overwrite_namespace_recovery_resident.py
```

Physical no-replace movement:

```text
runtime/python/zn_agent/core/staged_text_write.py
```

For an exact proven `replacefile_1177_split_retained` state, ZN now creates a **new durable namespace-repair lifecycle** rather than retrying the stale overwrite attempt.

The repair checkpoint binds:

- event and Body signature;
- exact old attempt and intent;
- matching atomic-overwrite protocol;
- target path;
- deterministic retained stage and backup paths;
- exact retained stage identity;
- exact retained backup identity.

Immediately before mutation, repair authority is revalidated from current reality. ZN requires the target to remain missing, stage to remain the exact intended new content, and backup to remain the exact durable pre-state.

The retained stage is then moved to the still-missing target using Windows no-replace semantics. A target created by another process wins. ZN does not replace it, does not replay the old overwrite, preserves stage/backup evidence, and returns to explicit handling.

Two new crash/restart windows are closed:

- **#25**: process death after durable repair checkpoint but before movement. Restart may continue only after revalidating the exact checkpointed repair evidence.
- **#26**: process death after retained stage moves into target but before repair completion/cleanup state is durably advanced. Restart observes target/stage/backup reality, verifies the target effect, does not move twice, and never replays the stale overwrite attempt.

The potentially unique backup remains downstream of independently verified target effect plus exact checkpointed cleanup authority.

## P5 status

P5 is **PARTIAL / SEVEN BOUNDED SLICES CI VERIFIED**.

Concrete crash/restart windows closed and verified: **26**.

The three latest race/drift tests harden P5.7 and are not counted as additional crash/restart windows.

Do not describe this as general rollback/restore complete.

Current atomic-overwrite boundaries:

- old-state equality after dispatch is never replay authority;
- `namespace_commit_started=false` permits only the exact P5.5 precommit reconciliation state;
- `namespace_commit_started=true` never authorizes replay of the old overwrite attempt;
- a proven retained 1177 split may authorize only the new P5.7 repair lifecycle;
- target appearance before/during repair withdraws repair authority and preserves the external winner;
- stage or backup drift withdraws repair authority;
- backup cleanup remains downstream of independent effect proof and exact artifact ownership.

## Real test / CI result

Exact code/proof head:

```text
099a1af7615e79fe34317f22d5c785aa46cba2b4
```

Focused Windows atomic-overwrite CI:

```text
ZN Atomic Overwrite E2E run 33163584755  success
Windows atomic overwrite lifecycle       success
Ran 28 tests in 27.391s                  OK
```

The P5.7 repair tests prove:

1. repair checkpoint survives death before the no-replace move;
2. death after the repair move is reconciled without a second move;
3. a target winner appearing after checkpoint is never clobbered;
4. a target winner appearing during movement is never clobbered;
5. stage drift after checkpoint withdraws repair authority;
6. backup drift after checkpoint withdraws repair authority.

The first hardening run on `fb8864f...` failed only because the synthetic test compared a Windows 8.3 short-path representation against the equivalent long path. Product behavior was not the failure. `099a1af...` removed that representation-only test assertion, after which the focused suite passed 28/28.

Full-tree Windows CI on the same exact head:

```text
ZN CI run 33163584746                    success
ZN Kernel / Python / Windows             success
  isolated no-model boot                 success
  compile resident core                  success
  Ran 673 tests in 844.861s              OK (skipped=5)
ZN Source Boundary / Windows             success
Electron / TypeScript / Windows          success
Publish Windows CI statuses              success
```

No local repository test execution is claimed for this slice. Repository self-hosted Windows CI is the verification authority.

## Relevant files

- `ZN.md`
- `AGENTS.md`
- `docs/ZN-IMPLEMENTATION-STATUS.md`
- `docs/ZN-SOURCE-EXTRACTION.md`
- `docs/ZN-SELF-MAINTENANCE.md`
- `.agent/HANDOFF.md`
- `runtime/python/zn_agent/core/file_identity.py`
- `runtime/python/zn_agent/core/side_effect_attempts.py`
- `runtime/python/zn_agent/core/side_effect_body.py`
- `runtime/python/zn_agent/core/overwrite_recovery_resident.py`
- `runtime/python/zn_agent/core/atomic_overwrite_protocols.py`
- `runtime/python/zn_agent/core/staged_text_write.py`
- `runtime/python/zn_agent/core/atomic_overwrite_resident.py`
- `runtime/python/zn_agent/core/atomic_overwrite_namespace_recovery_resident.py`
- `runtime/python/zn_agent/core/recovery_bounded_resident.py`
- `runtime/python/zn_agent/core/provider_bridge.py`
- `runtime/python/zn_agent/core/work_control.py`
- `runtime/python/zn_agent/core/work.py`
- `tests/zn_agent/core/test_work_overwrite_recovery.py`
- `tests/zn_agent/core/test_windows_atomic_overwrite.py`
- `tests/zn_agent/core/test_windows_atomic_overwrite_namespace_recovery.py`
- `tests/zn_agent/core/test_windows_atomic_overwrite_namespace_repair.py`
- `.github/workflows/zn-atomic-overwrite-e2e.yml`

## Risks / blockers

No current implementation CI blocker.

Open technical work:

- general per-task restore/rollback and arbitrary workspace snapshots remain open;
- user-visible restore points remain open;
- `work_control.py` exposes Work/thread snapshots but these are interaction/control snapshots, not workspace rollback points;
- there is no general startup/maintenance GC authority for retained deterministic artifacts outside an exact active protocol;
- incomplete/large file identities remain fail-closed;
- replacement file identity and uncommon Windows metadata/named-stream/host-or-power-loss behavior are not claimed solved;
- generic `NativeBody` behavior outside the active product chain remains intentionally unchanged;
- isolated parallel Work remains open;
- broader browser, M8 continuity, and SM1+ remain incomplete;
- identity, long-term memory, credentials/permissions, updater/signing, rollback and destructive self-maintenance remain human-approval boundaries.

No secret, token, password, signing key, or production credential belongs in this file.

## Task queue

1. Re-read the six canonical project/handoff documents plus exact Git/PR/CI before coding.
2. Trace the Work mutation path from `work_control.py` / `work.py` through event ownership, resident action intent, Body mutation, verification, artifact retention, and terminalization.
3. Define one resident-owned durable restore-point record bound to an exact Work run and exact file mutation lifecycle.
4. Start narrowly: one exact-file pre-mutation restore point around resident-owned overwrite, not arbitrary workspace snapshots.
5. Record exact pre-mutation identity and restorable content ownership before mutation; define retention and terminal cleanup separately from rollback authority.
6. Make restart semantics explicit. A persisted restore point must survive process reconstruction, but its existence must not itself trigger automatic rollback.
7. Keep restore application user-visible and bounded until destructive/identity-sensitive restore policy is separately proven.
8. Add focused crash/restart tests, then run relevant focused CI and full `ZN CI`; fix failures before claiming the slice complete.
9. Update `ZN-IMPLEMENTATION-STATUS.md` and this HANDOFF only after exact-head proof.
10. Keep PR #6 draft and keep `main` untouched unless explicitly authorized and M10 conditions are revalidated.

## Next real target

P5 resident-owned per-task restore-point foundation: exact Work ownership -> durable exact-file pre-mutation restore metadata -> restart-safe retention -> explicit bounded restore authority later. Do not jump directly to arbitrary workspace rollback.
