# ZN Maintainer Handoff

Updated: 2026-08-28

This is an operational maintainer handoff, not a chat summary. Real repository state and CI remain authoritative.

## Current goal

Continue P5 durable Work recovery at the Windows atomic-overwrite retained-namespace boundary. The next narrow work is zero-byte artifact identity hardening followed by an explicit restart-safe repair lifecycle for a proven `ReplaceFileW` 1177 split, without granting replay authority to the stale overwrite attempt.

## Branch / repository state

- repository: `9529360-cpu/znagent`
- development branch: `dev/zn-agent`
- canonical branch: `main`
- canonical `main` HEAD: `8234a835dea604783cea0bd9d28a40de654ec03d`
- implementation/proof HEAD before this documentation sync: `042e196418d8c4e9baa17d810b60d995007dc5b0`
- key implementation commit: `042e196418d8c4e9baa17d810b60d995007dc5b0` (`fix: reconcile committed overwrite namespaces`)
- draft PR: #6, `dev/zn-agent` -> `main`
- `main` was not modified
- no force push/history rewrite performed

Re-read `dev/zn-agent` after this handoff/documentation commit before starting the next implementation slice; the branch HEAD will be the documentation sync descendant of `042e1964...`.

## Completed in the latest P5 slice

Added active product layer:

```text
runtime/python/zn_agent/core/atomic_overwrite_namespace_recovery_resident.py
```

Updated active runtime ownership:

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

The slice closes one more distinct crash/restart window (#24) and adds bounded post-commit namespace reasoning:

1. A matching `namespace_commit_started=true` protocol may be used as read-only namespace evidence, never as replay authority.
2. The exact documented `ReplaceFileW` WinError 1177 split can be recognized when target is missing, retained stage still equals the durable new payload, and retained backup still equals the durable pre-state.
3. That split is held as `repair_retained_atomic_namespace_required`, with both artifacts preserved and replay blocked.
4. If target independently verifies as the exact requested effect, the attempt may resolve `verified_effect` through inherited overwrite recovery.
5. Only after that verified effect may ZN durably checkpoint cleanup ownership for exact retained deterministic artifacts.
6. Restart after the cleanup checkpoint continues only exact artifact deletion and never repeats the overwrite.
7. Exact artifact identity is rechecked before delayed unlink; drift removes delete authority and preserves the artifact.
8. Matching protocol is removed only after the exact retained artifacts are absent.

New tests:

```text
tests/zn_agent/core/test_windows_atomic_overwrite_namespace_recovery.py
```

Coverage includes:

- 1177 split classification/preservation without replay;
- process death after durable cleanup checkpoint before backup delete, followed by restart completion without replay;
- retained-backup drift after checkpoint, proving ZN preserves the changed artifact instead of deleting it.

Updated focused workflow:

```text
.github/workflows/zn-atomic-overwrite-e2e.yml
```

## P5 status

P5 is **PARTIAL / SIX BOUNDED SLICES CI VERIFIED**.

Concrete crash/restart windows closed and verified: **24**.

Do not describe this as general rollback/restore complete.

Important prior boundary from #23 remains unchanged:

- exact matching protocol;
- stage ready with complete identity;
- `namespace_commit_started=false`;
- target exactly equals durable pre-dispatch identity;
- stage exactly equals durable staged identity;
- backup absent;

Only that state can close the old attempt `verified_absent` and permit a fresh overwrite lifecycle. Once commit-start is durable, stale overwrite replay remains forbidden.

## Real test / CI result

Exact implementation head:

```text
042e196418d8c4e9baa17d810b60d995007dc5b0
```

Focused Windows CI:

```text
ZN Atomic Overwrite E2E run 33159250870  success
Ran 19 tests                           OK
```

Full-tree Windows CI:

```text
ZN CI run 33159250929                  success
Electron / TypeScript / Windows        success
ZN Source Boundary / Windows           success
ZN Kernel / Python / Windows           success
  isolated no-model boot               success
  compile resident core                success
  664 core tests                       OK (skipped=5)
Publish Windows CI statuses             success
```

The 664-test suite explicitly includes all 12 earlier Windows atomic-overwrite tests plus the 3 new namespace-recovery tests.

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
- `tests/zn_agent/core/test_work_overwrite_recovery.py`
- `tests/zn_agent/core/test_windows_atomic_overwrite.py`
- `tests/zn_agent/core/test_windows_atomic_overwrite_namespace_recovery.py`
- `.github/workflows/zn-atomic-overwrite-e2e.yml`

## Risks / blockers

No current CI blocker on the implementation head.

Open technical risks:

- A proven 1177 split is classified and preserved, but there is no automatic repair/restore action yet.
- General workspace rollback/restore remains open.
- There is no general startup/maintenance GC authority for retained deterministic artifacts outside an exact protocol.
- Cross-path content-equivalence currently fails closed for zero-byte files because the bounded comparison uses truthy size fallback; zero-byte retained stage/backup cannot yet receive automatic equivalence authority.
- Incomplete/large identities remain fail-closed.
- Replacement file identity and uncommon Windows metadata/named-stream/power-loss behavior are not claimed solved.
- Potentially unique backups must continue to be preserved unless stronger terminal truth and explicit cleanup authority exist.
- Generic `NativeBody` behavior outside the active product chain remains intentionally unchanged.

No secret, token, password, signing key, or production credential belongs in this file.

## Task queue

1. Re-read the six canonical project/handoff documents and current Git/PR/CI before coding.
2. Fix zero-byte exact artifact content-equivalence without broadening unsafe identity assumptions; add focused Windows tests including zero-byte pre-state/new payload cases.
3. Re-run focused atomic-overwrite CI and full `ZN CI`; fix failures before moving on.
4. Then design an explicit 1177 repair lifecycle as a **new repair action/lifecycle**, not replay of the old overwrite attempt. It must be restart-safe, preserve unique backup data until authority is durable, and use fresh namespace evidence.
5. Keep broader rollback/restore, isolated parallel Work, M8, and SM1+ marked incomplete until their own proofs exist.
6. Keep PR #6 draft and keep `main` untouched unless explicitly authorized and M10 conditions are revalidated.

## Next real target

P5 atomic-overwrite retained namespace hardening: close the zero-byte exact-artifact identity edge first, then establish explicit 1177 repair authority that cannot be confused with stale overwrite replay.
