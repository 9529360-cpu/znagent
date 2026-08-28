# ZN Implementation Status

Updated: 2026-08-28

This file records implementation truth for the active ZN product. Source code, Git state, tests, and CI remain authoritative over this document.

## Repository truth

- repository: `9529360-cpu/znagent`
- development branch: `dev/zn-agent`
- canonical/release branch: `main`
- canonical `main`: `8234a835dea604783cea0bd9d28a40de654ec03d`
- latest P5 implementation/proof head: `042e196418d8c4e9baa17d810b60d995007dc5b0`
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
- P5 durable Work checkpoint / restore foundation: **PARTIAL / SIX BOUNDED SLICES CI VERIFIED**

Broader Work durability now has **TWENTY-FOUR concrete crash/restart windows closed and verified**. This does not mean general rollback/restore is complete.

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

Implementation/proof head:

```text
042e196418d8c4e9baa17d810b60d995007dc5b0  fix: reconcile committed overwrite namespaces
```

New active owner:

```text
runtime/python/zn_agent/core/atomic_overwrite_namespace_recovery_resident.py
```

Active runtime chain is now:

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

The new layer owns post-commit namespace evidence without converting that evidence into stale-attempt replay authority.

For the documented `ReplaceFileW` WinError `1177` split with a supplied backup, ZN can now recognize the exact bounded namespace contradiction when:

- `namespace_commit_started=true` belongs to the matching attempt;
- target is provably missing;
- retained stage still contains the exact durable staged payload;
- retained backup still contains the exact durable pre-state.

That state is classified as `replacefile_1177_split_retained`. ZN preserves both stage and backup, sets `replay_blocked=true`, and requires an explicit namespace repair decision. It does **not** infer rollback, completion, or permission to replay the old overwrite.

If commit-start has occurred but the target itself independently verifies as the exact requested effect, inherited overwrite recovery may resolve the attempt as `verified_effect`. Only after that independent effect proof may ZN checkpoint retained-artifact cleanup authority.

Cleanup is now crash/restart bounded:

```text
verified target effect
-> positive ownership proof for retained deterministic artifacts
-> durable cleanup checkpoint with exact artifact identities
-> unlink only while exact identity still matches
-> protocol removal after artifacts are absent
-> durable completion
```

Process death after the cleanup checkpoint and before backup deletion is therefore a distinct closed restart window (#24): restart continues only the exact artifact cleanup and never repeats the overwrite. If an artifact identity drifts, or its matching protocol disappears while an artifact remains, delete authority is withdrawn and the artifact is preserved for explicit handling.

### Real CI proof for #24

Focused Windows proof on exact implementation head:

```text
ZN Atomic Overwrite E2E run 33159250870          success
  Windows atomic overwrite lifecycle             success
  Ran 19 tests                                   OK
```

This includes the three new Windows proofs:

- exact documented 1177 split is classified and preserved without replay;
- verified-effect cleanup checkpoint survives process death and resumes without replay;
- externally replaced retained backup is preserved when its identity drifts.

Full-tree proof on the same exact implementation head:

```text
ZN CI run 33159250929                             success
  ZN Kernel / Python / Windows                    success
    Boot isolated ZN distribution without model  success
    Compile resident core                        success
    Run ZN core tests against working tree       success
    Ran 664 tests in 479.204s                    OK (skipped=5)
  ZN Source Boundary / Windows                    success
  Electron / TypeScript / Windows                 success
  Publish Windows CI statuses                     success
```

No local repository test run is claimed for this web-maintainer slice. Repository self-hosted Windows CI is the verification authority.

## Current atomic overwrite invariants

1. Old-state equality after dispatch is never replay authority.
2. `namespace_commit_started=false` may authorize only the exact #23 precommit reconciliation state.
3. `namespace_commit_started=true` never authorizes replay of the old overwrite attempt.
4. Exact intended target content can resolve `verified_effect` through read-only verification.
5. A potentially unique retained backup is preserved unless ZN has stronger terminal effect truth plus exact artifact ownership.
6. Delayed cleanup rechecks exact checkpointed artifact identity immediately before deletion.
7. Artifact drift removes delete authority; it does not change the already-verified target effect.

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
- `tests/zn_agent/core/test_work_overwrite_recovery.py`
- `tests/zn_agent/core/test_windows_atomic_overwrite.py`
- `tests/zn_agent/core/test_windows_atomic_overwrite_namespace_recovery.py`
- `.github/workflows/zn-atomic-overwrite-e2e.yml`

## Open risks / incomplete work

P5 remains **PARTIAL**. Still open:

- general per-task restore/rollback and arbitrary workspace snapshots;
- user-visible restore points;
- explicit automatic repair for a proven 1177 split; the current implementation only classifies and preserves it;
- a general startup/maintenance GC owner for deterministic artifacts outside an exact active protocol;
- zero-byte cross-path retained-artifact content equivalence currently fails closed, so automatic 1177 split recognition/cleanup does not cover that narrow edge yet;
- large/incomplete identities that cannot be proven exact remain fail-closed;
- replacement changes file identity; uncommon metadata/named-stream behavior and host/power-loss durability remain open;
- generic `NativeBody` remains unchanged for non-active/shared callers;
- isolated parallel Work remains open;
- broader browser, M8 continuity, and SM1+ work remains incomplete;
- identity, long-term memory, credentials/permissions, updater/signing, rollback and destructive self-maintenance remain human-approval boundaries.

## Next real target

Continue P5 at the retained namespace-repair/cleanup hardening boundary:

1. close the zero-byte exact-artifact identity edge with real Windows proof;
2. define a bounded explicit repair lifecycle for a proven 1177 split without ever replaying the stale overwrite attempt;
3. keep potentially unique backup data preserved until that repair authority is explicit and restart-safe.

Keep `main` untouched.
