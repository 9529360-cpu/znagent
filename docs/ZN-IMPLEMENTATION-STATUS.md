# ZN Implementation Status

Updated: 2026-08-28

This file records implementation truth for the active ZN product. Source code, Git state, tests, and CI remain authoritative over this document.

## Repository truth

- repository: `9529360-cpu/znagent`
- development branch: `dev/zn-agent`
- canonical/release branch: `main`
- canonical `main`: `8234a835dea604783cea0bd9d28a40de654ec03d`
- latest P5 code/proof head before this documentation sync: `099a1af7615e79fe34317f22d5c785aa46cba2b4`
- PR #6 remains the draft development PR from `dev/zn-agent` to `main`
- `main` was not modified
- no force push or history rewrite was performed

Founding boundary:

> **ZN uses models. Models do not own ZN.**

## Stage summary

- P1 shared side-effect-attempt persistence owner: **COMPLETE / CI VERIFIED**
- P2 bounded cumulative accounting/learning durability: **COMPLETE / CI VERIFIED**
- P3 managed-browser frontier reconciliation: **COMPLETE / CI VERIFIED NARROW**
- P4 resident-owned live-page registry: **COMPLETE / CI VERIFIED NARROW**
- P5 durable Work checkpoint / restore foundation: **PARTIAL / SEVEN BOUNDED SLICES CI VERIFIED**

Broader Work durability has **TWENTY-SIX concrete crash/restart windows closed and verified**. The latest race/drift tests harden P5.7 but are not counted as additional crash/restart windows. This does not mean general rollback/restore is complete.

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

Restart may close the old attempt `verified_absent` and grant a fresh lifecycle only when all of the following are exact: matching protocol/attempt, complete stage-ready evidence, `namespace_commit_started=false`, target equals the pre-dispatch identity, stage equals its durable identity, and deterministic backup is absent. Missing/legacy protocol, incomplete identity, tampering, drift, unexpected backup, or commit-start remain fail-closed.

### P5.6 - commit-start namespace reconciliation and verified-effect artifact cleanup (#24)

Base implementation/proof head `042e196418d8c4e9baa17d810b60d995007dc5b0`; zero-byte identity hardening descendant `75e50c243b44e347c0e549fa9cb4cf7b37716e9f`.

The namespace layer owns post-commit namespace evidence without converting that evidence into stale-attempt replay authority. For the documented `ReplaceFileW` WinError `1177` split with a supplied backup, ZN recognizes the exact bounded contradiction only when the matching attempt has durable `namespace_commit_started=true`, target is provably missing, retained stage is the exact durable staged payload, and retained backup is the exact durable pre-state.

That state is classified as `replacefile_1177_split_retained`. Before P5.7 it was preserved and replay-blocked for explicit repair. Independently verified intended target content may resolve `verified_effect`; only then may exact retained artifacts enter checkpointed cleanup. Cleanup rechecks checkpointed identities before deletion and preserves drifted artifacts.

The zero-byte hardening treats size zero as valid content evidence only when paired with a complete SHA-256 identity; malformed/incomplete identities remain fail-closed.

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

Active owner:

```text
runtime/python/zn_agent/core/atomic_overwrite_namespace_recovery_resident.py
```

Physical no-replace movement:

```text
runtime/python/zn_agent/core/staged_text_write.py
```

Active runtime chain remains:

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

P5.7 does not replay the stale overwrite attempt. A proven `replacefile_1177_split_retained` state first receives a new durable namespace-repair checkpoint bound to the exact protocol, attempt, intent, target, stage, backup, and retained artifact identities. Immediately before mutation ZN revalidates target-missing + exact-stage-new + exact-backup-old reality.

The repair is a new bounded Body movement: move the exact retained stage into the still-missing target using Windows no-replace namespace semantics. If another process creates the target before or during this move, ZN preserves the external winner, withdraws repair authority, preserves stage and backup, keeps replay blocked, and returns to explicit handling rather than overwriting it.

Crash/restart window **#25** is process death after the durable repair checkpoint but before the no-replace move. Restart revalidates current target/stage/backup reality and may continue only the checkpointed new repair action; it never replays the stale overwrite attempt.

Crash/restart window **#26** is process death after the retained stage has moved into the target but before repair completion/cleanup state is durably advanced. Restart observes fresh target/stage/backup reality. Exact intended target content plus missing retained stage proves the repair effect; the move is not repeated, the old overwrite attempt is not replayed, and the potentially unique backup remains until independent effect verification and exact cleanup authority allow removal.

Repair authority is deliberately revocable. Target appearance, stage identity drift, backup identity drift, protocol mismatch, or incomplete evidence fail closed and preserve retained artifacts.

### Real CI proof for P5.7

Focused Windows atomic-overwrite proof on exact head `099a1af7615e79fe34317f22d5c785aa46cba2b4`:

```text
ZN Atomic Overwrite E2E run 33163584755          success
  Windows atomic overwrite lifecycle             success
  Ran 28 tests in 27.391s                        OK
```

The P5.7 suite includes direct proof that:

- a repair checkpoint survives process death before movement;
- process death after the repair move is reconciled without a second move;
- an external target winner appearing after checkpoint is never clobbered;
- an external target winner appearing during the no-replace move is never clobbered;
- stage drift after checkpoint withdraws repair authority;
- backup drift after checkpoint withdraws repair authority.

The first run of the new race test on `fb8864f...` exposed only a Windows 8.3-short-path versus long-path test equality assumption. Runtime behavior was not the failure. `099a1af...` removed that representation-only assertion, and the exact-head focused suite passed 28/28.

Full-tree proof on the same exact head:

```text
ZN CI run 33163584746                             success
  ZN Kernel / Python / Windows                    success
    Boot isolated ZN distribution without model  success
    Compile resident core                        success
    Run ZN core tests against working tree       success
    Ran 673 tests in 844.861s                    OK (skipped=5)
  ZN Source Boundary / Windows                    success
  Electron / TypeScript / Windows                 success
  Publish Windows CI statuses                     success
```

No local repository test run is claimed for this web-maintainer slice. Repository self-hosted Windows CI is the verification authority.

## Current atomic overwrite invariants

1. Old-state equality after dispatch is never replay authority.
2. `namespace_commit_started=false` may authorize only the exact P5.5 precommit reconciliation state.
3. `namespace_commit_started=true` never authorizes replay of the old overwrite attempt.
4. Exact intended target content can resolve `verified_effect` through read-only verification.
5. A proven retained 1177 split may authorize only the new P5.7 namespace-repair lifecycle, never the stale overwrite attempt.
6. Repair authority is bound to exact durable protocol/attempt/intent/artifact evidence and is revalidated immediately before mutation.
7. A target that appears before or during repair wins; ZN never replaces that external winner.
8. Stage or backup drift withdraws repair authority and preserves the artifacts.
9. A potentially unique retained backup is preserved until stronger terminal effect truth plus exact cleanup ownership exists.
10. Delayed cleanup rechecks exact checkpointed artifact identity immediately before deletion.
11. Artifact drift removes delete authority; it does not manufacture effect truth.
12. Zero-byte content is valid exact evidence only when size and complete SHA-256 are both well-formed; malformed/incomplete identities remain fail-closed.

## Relevant files

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
- `tests/zn_agent/core/test_work_overwrite_recovery.py`
- `tests/zn_agent/core/test_windows_atomic_overwrite.py`
- `tests/zn_agent/core/test_windows_atomic_overwrite_namespace_recovery.py`
- `tests/zn_agent/core/test_windows_atomic_overwrite_namespace_repair.py`
- `.github/workflows/zn-atomic-overwrite-e2e.yml`

## Open risks / incomplete work

P5 remains **PARTIAL**. Still open:

- general per-task restore/rollback and arbitrary workspace snapshots;
- user-visible restore points;
- a general startup/maintenance GC owner for deterministic artifacts outside an exact active protocol;
- large/incomplete identities that cannot be proven exact remain fail-closed;
- replacement changes file identity; uncommon metadata/named-stream behavior and host/power-loss durability remain open;
- generic `NativeBody` remains unchanged for non-active/shared callers;
- isolated parallel Work remains open;
- broader browser, M8 continuity, and SM1+ work remains incomplete;
- identity, long-term memory, credentials/permissions, updater/signing, rollback and destructive self-maintenance remain human-approval boundaries.

## Next real target

Continue P5 above the now-closed 1177 repair boundary. The next bounded target is a resident-owned **per-task restore-point foundation**, not another special-case overwrite replay mechanism:

1. define durable restore-point metadata owned by the Work lifecycle and bound to one exact Work run;
2. begin with a narrow exact-file restore point around resident-owned file mutation rather than claiming arbitrary workspace snapshots;
3. record exact pre-mutation identity and restorable content ownership before mutation, with explicit retention/lifecycle rules;
4. make restart semantics explicit so a restore point is neither silently lost nor interpreted as automatic rollback authority;
5. keep actual rollback user-visible and bounded until destructive/identity-sensitive restore policy is separately proven.

This is a stepping stone toward general per-task restore/rollback. Do not describe arbitrary workspace restore, broad rollback, or M8 as complete.

Keep `main` untouched.
