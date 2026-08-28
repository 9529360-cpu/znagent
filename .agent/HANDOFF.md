# ZN Maintainer Handoff

Updated: 2026-08-28

This is an operational maintainer handoff, not a chat summary. Real repository state and CI remain authoritative.

## Current goal

Continue P5 durable Work recovery at the explicit Windows atomic-overwrite namespace-repair boundary. The zero-byte retained-artifact identity edge is now CI-verified. Next narrow work is a restart-safe repair lifecycle for a proven `ReplaceFileW` 1177 split, implemented as a new namespace repair action and never as replay of the stale overwrite attempt.

## Branch / repository state

- repository: `9529360-cpu/znagent`
- development branch: `dev/zn-agent`
- canonical branch: `main`
- canonical `main` HEAD: `8234a835dea604783cea0bd9d28a40de654ec03d`
- implementation/proof HEAD before this documentation sync: `75e50c243b44e347c0e549fa9cb4cf7b37716e9f`
- key latest implementation commit: `75e50c243b44e347c0e549fa9cb4cf7b37716e9f` (`fix: handle zero-byte overwrite artifacts`)
- base #24 implementation: `042e196418d8c4e9baa17d810b60d995007dc5b0` (`fix: reconcile committed overwrite namespaces`)
- draft PR: #6, `dev/zn-agent` -> `main`
- `main` was not modified
- no force push/history rewrite performed

Re-read `dev/zn-agent` after this handoff/documentation commit before starting the next implementation slice; the branch HEAD will be the documentation-sync descendant of `75e50c24...`.

## Completed in the latest P5 hardening

The live call chain remains:

```text
provider_bridge
-> RecoveryBoundedResidentRuntime
-> AtomicOverwriteNamespaceRecoveryResidentRuntime
-> AtomicOverwriteRecoveryResidentRuntime
-> OverwriteRecoveryResidentRuntime
-> DurableBodyAccountingResidentRuntime
-> CapabilityRecoveryResidentRuntime
-> ...
```

Root cause closed in:

```text
runtime/python/zn_agent/core/atomic_overwrite_namespace_recovery_resident.py
```

`observe_file_identity()` already records a complete SHA-256 for zero-byte files. The bug was in cross-path content equivalence: `size_bytes == 0` was passed through a truthy fallback and became a sentinel, so exact empty stage or backup files could never match durable content evidence.

The repaired equivalence rule now requires all of the following for both identities:

- observable, stable, existing regular file;
- complete digest;
- exact Python integer size, nonnegative (zero is valid);
- exact 64-character lowercase hexadecimal SHA-256.

Only then are exact size and digest compared. This closes the empty-file edge without accepting malformed/incomplete identity evidence.

New Windows proofs in:

```text
tests/zn_agent/core/test_windows_atomic_overwrite_namespace_recovery.py
```

Coverage added:

1. Empty **new staged payload** + nonempty old pre-state can still classify the documented 1177 split after restart, with target missing and replay blocked.
2. Nonempty new staged payload + empty **old pre-state / retained backup** can still classify the documented 1177 split.
3. After independently verified target effect, an exact zero-byte retained backup can receive cleanup ownership and be deleted; the overwrite itself is not replayed.

This is an identity-input hardening of the already-counted #24 restart window. Do **not** increment the concrete crash/restart-window count for these three boundary tests.

## P5 status

P5 is **PARTIAL / SIX BOUNDED SLICES CI VERIFIED**.

Concrete crash/restart windows closed and verified: **24**.

Do not describe this as general rollback/restore complete.

Important boundaries remain:

- #23 is the only precommit replay-adjacent reconciliation: matching protocol/attempt, complete stage-ready identity, `namespace_commit_started=false`, unchanged target pre-state, exact stage, absent backup may close old attempt `verified_absent` and permit a fresh lifecycle.
- Once `namespace_commit_started=true`, the old overwrite attempt is never replay authority.
- #24 may classify exact 1177 split evidence and preserve artifacts, or resolve exact target effect and run checkpointed cleanup.
- zero-byte stage/backup content is now valid exact evidence under the same strict complete-digest rules.

## Real test / CI result

Exact zero-byte hardening head:

```text
75e50c243b44e347c0e549fa9cb4cf7b37716e9f
```

Focused Windows CI:

```text
ZN Atomic Overwrite E2E run 33161103589  success
Windows atomic overwrite lifecycle       success
Ran 22 tests in 10.841s                  OK
```

Full-tree Windows CI:

```text
ZN CI run 33161103586                    success
Electron / TypeScript / Windows          success
ZN Source Boundary / Windows             success
ZN Kernel / Python / Windows             success
  isolated no-model boot                 success
  compile resident core                  success
  667 core tests in 505.584s             OK (skipped=5)
Publish Windows CI statuses              success
```

The full suite explicitly includes the three added zero-byte namespace-recovery tests.

No local repository test execution is claimed for this slice. Self-hosted Windows repository CI is the verification authority.

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
- `tests/zn_agent/core/test_work_overwrite_recovery.py`
- `tests/zn_agent/core/test_windows_atomic_overwrite.py`
- `tests/zn_agent/core/test_windows_atomic_overwrite_namespace_recovery.py`
- `.github/workflows/zn-atomic-overwrite-e2e.yml`

## Risks / blockers

No current CI blocker on the implementation head.

Open technical risks:

- A proven 1177 split is classified and preserved, but there is no restart-safe repair action yet.
- General workspace rollback/restore remains open.
- There is no general startup/maintenance GC authority for retained deterministic artifacts outside an exact protocol.
- Incomplete/large identities remain fail-closed.
- Replacement file identity and uncommon Windows metadata/named-stream/power-loss behavior are not claimed solved.
- Potentially unique backups must continue to be preserved unless stronger terminal truth and explicit cleanup authority exist.
- Generic `NativeBody` behavior outside the active product chain remains intentionally unchanged.

No secret, token, password, signing key, or production credential belongs in this file.

## Task queue

1. Re-read the six canonical project/handoff documents and current Git/PR/CI before coding.
2. Design the 1177 repair as a **new namespace repair lifecycle**, not a retry/replay of `write_text`.
3. Add durable repair-start truth bound to the exact protocol/attempt and retained stage/backup identities before the new namespace action crosses its mutation boundary.
4. Immediately before repair, re-observe and require exact proven split reality: target absent, stage still exact new payload, backup still exact old pre-state.
5. Repair stage -> target with no replace semantics so an external target winner is never clobbered.
6. Add crash/restart tests for death after repair-start and after namespace mutation; restart must classify target/stage/backup truth before any continuation and must never replay the old overwrite.
7. Keep backup cleanup downstream of independent target-effect verification plus durable exact cleanup authority.
8. Run focused atomic-overwrite CI and full `ZN CI`; fix failures before updating status/HANDOFF.
9. Keep broader rollback/restore, isolated parallel Work, M8, and SM1+ marked incomplete until their own proofs exist.
10. Keep PR #6 draft and keep `main` untouched unless explicitly authorized and M10 conditions are revalidated.

## Next real target

P5 explicit 1177 namespace repair: exact proven split -> durable repair-start -> no-replace stage-to-target repair -> restart reconciliation -> independent effect verification -> bounded backup cleanup. Never reuse the stale overwrite attempt as repair authority.
