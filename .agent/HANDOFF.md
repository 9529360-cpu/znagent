# ZN Agent Handoff

Updated: 2026-08-28

## Current goal

P1-P4 are complete and CI-verified. P5 broader Work checkpoint/restore remains **PARTIAL / IN PROGRESS** with four bounded, verified slices:

1. accepted Work ingress checkpoint before resident-event creation (#19);
2. reality-gated ordinary overwrite effect-present recovery (#20);
3. privacy-bounded overwrite pre-dispatch identity/restart guard (#21);
4. Windows staged atomic-overwrite lifecycle that removes truncation-first process-death ambiguity for active exact overwrite (#22).

Broader Work durability now has **TWENTY-TWO concrete crash/restart windows closed and verified**.

General per-task restore/rollback, arbitrary workspace snapshots, user-visible restore points, isolated parallel Work and post-dispatch automatic overwrite replay remain open.

Founding boundary:

> **ZN uses models. Models do not own ZN.**

## Branch / repository truth

- repository: `9529360-cpu/znagent`
- development branch: `dev/zn-agent`
- canonical source/release branch: `main`
- canonical `main`: `8234a835dea604783cea0bd9d28a40de654ec03d`
- P5 ingress proof head: `2c20b8bded96ce07c6ec43263cc77b7bd10a7a82`
- P5 overwrite effect-present proof head: `c4276f8b151d2c45b69368cb414f012bf0644d01`
- P5 overwrite pre-dispatch proof head: `97803f8d0616c1f2b30a61af5acc686f1256cd11`
- P5 atomic-overwrite implementation head: `b3cf799ec24d8f4bb89d82752c2396e70cc6a233`
- exact CI-verification descendant before this documentation sync: `403ac14f04866380a0d32c74bd9e250226dbb780`
- PR #6 remains the draft development PR from `dev/zn-agent` to `main`
- `main` was not modified
- no force push or history rewrite was requested or performed

A HANDOFF commit cannot contain its own resulting SHA. Re-read `dev/zn-agent` after this commit and use that exact HEAD externally.

## Completed stages

### P1 - shared side-effect-attempt persistence owner

Status: **COMPLETE / CI VERIFIED**

```text
ZN Work Recovery E2E 33117334326  success
ZN CI                33117334321  success
```

### P2 - bounded cumulative accounting/learning durability

Status: **COMPLETE / CI VERIFIED**

Proof head `f79d4f3c81b1d7c46dcfb55b6fc923acda77b39c`.

```text
ZN Work Recovery E2E 33119871079  success
ZN CI                33119871129  success
```

### P3 - managed-browser frontier reconciliation

Status: **COMPLETE / CI VERIFIED**

`SELECT_OPTION`, CHECK and UNCHECK are **VERIFIED NARROW**. `PRESS` remains OPEN.

```text
ZN Managed Browser E2E 33120809421  success
ZN CI                  33120848980  success
```

### P4 - resident-owned live-page registry

Status: **COMPLETE / CI VERIFIED NARROW**

Proof head `fffb0f4b84a76cef21a088167c9eb4faceb93afc`.

```text
ZN Managed Browser E2E 33122620361  success
ZN CI                  33122620398  success
```

## P5 - durable Work checkpoint / restore foundation

Status: **PARTIAL / FOUR BOUNDED SLICES CI VERIFIED**

### P5.1 - accepted Work ingress checkpoint (#19)

Proof head `2c20b8bded96ce07c6ec43263cc77b7bd10a7a82`.

```text
ZN Work Recovery E2E 33124662199  success
ZN CI                33124662367  success
```

### P5.2 - ordinary overwrite effect-present recovery (#20)

Proof head `c4276f8b151d2c45b69368cb414f012bf0644d01`.

After a durable overwrite attempt exists, restart never blindly repeats the write. Exact intended current text resolves `verified_effect`; mismatch/read failure remains outside-world uncertainty and preserves the target.

```text
ZN Work Recovery E2E 33129111422  success
ZN CI                33129111419  success
```

### P5.3 - overwrite pre-dispatch identity guard (#21)

Proof head `97803f8d0616c1f2b30a61af5acc686f1256cd11`.

Owner: `runtime/python/zn_agent/core/file_identity.py`.

Pre-state identity is privacy-bounded and content-free apart from bounded SHA-256 evidence. If restart occurs before Body attempt creation, exact unchanged identity may continue the inherited fresh lifecycle; drift returns to Investigation without mutation. Once a durable attempt exists, the old identity can never authorize replay.

```text
ZN Work Recovery E2E 33151244307  success  (95 tests, OK)
ZN CI                33151244298  success
```

### P5.4 - Windows staged atomic overwrite (#22)

Status: **BOUNDED SLICE COMPLETE / CI VERIFIED**

Implementation commit:

```text
b3cf799ec24d8f4bb89d82752c2396e70cc6a233  fix: stage Windows overwrite commits atomically
```

CI workflow correction/current proof descendant:

```text
403ac14f04866380a0d32c74bd9e250226dbb780  ci: allow Windows atomic overwrite checks
```

New files:

```text
runtime/python/zn_agent/core/staged_text_write.py
runtime/python/zn_agent/core/atomic_overwrite_resident.py
tests/zn_agent/core/test_windows_atomic_overwrite.py
.github/workflows/zn-atomic-overwrite-e2e.yml
```

Active call chain now includes:

```text
provider_bridge.build_resident_runtime()
-> RecoveryBoundedResidentRuntime
-> AtomicOverwriteRecoveryResidentRuntime
-> OverwriteRecoveryResidentRuntime
-> DurableBodyAccountingResidentRuntime
-> CapabilityRecoveryResidentRuntime
-> inherited specialized repo/Body completion owners
```

Physical Windows exact-overwrite sequence:

```text
durable side-effect attempt
-> complete same-directory stage
-> flush + fsync
-> recheck #21 durable pre-state identity
-> existing regular file: ReplaceFileW with deterministic backup
   missing file: MoveFileExW without replace flag + WRITE_THROUGH
-> inherited verification/completion lifecycle
```

Semantics now proven:

- process death after staging does not truncate the original target;
- missing-target race does not clobber an external winner;
- existing replacement preserves observed creation-time behavior and cleans normal backup state;
- precommit drift becomes a precondition contradiction and closes the attempt `verified_absent`;
- synthetic WinError `1177` enters side-effect recovery rather than failure learning/replay;
- read-only target is rejected without replacement;
- prior #21 overwrite recovery remains regression-locked.

Real focused Windows proof:

```text
ZN Atomic Overwrite E2E run 33154361936               success
  Prepare isolated runtime                            success
  Compile atomic overwrite path                       success
  Verify overwrite recovery and Windows semantics     success
```

Focused log: `Ran 10 tests in 2.695s` / `OK`.

Real full-tree proof on the same exact head:

```text
ZN CI run 33154361960                                  success
ZN Kernel / Python / Windows                           success
  Boot isolated ZN distribution without a model       success
  Compile resident core                               success
  Run ZN core tests against working tree              success
ZN Source Boundary / Windows                           success
Electron / TypeScript / Windows                        success
Publish Windows CI statuses                            success
```

CI history note: focused run `33154248922` failed before compile/tests because the new workflow omitted the repository-standard Windows PowerShell execution-policy bypass. `403ac14f...` changed only workflow shell configuration; subsequent focused and full-tree runs are green.

No local repository test run is claimed for this web-maintainer slice. Repository self-hosted Windows CI is the verification authority.

## Relevant files

- `runtime/python/zn_agent/core/file_identity.py`
- `runtime/python/zn_agent/core/overwrite_recovery_resident.py`
- `runtime/python/zn_agent/core/staged_text_write.py`
- `runtime/python/zn_agent/core/atomic_overwrite_resident.py`
- `runtime/python/zn_agent/core/recovery_bounded_resident.py`
- `runtime/python/zn_agent/core/side_effect_body.py`
- `tests/zn_agent/core/test_work_overwrite_recovery.py`
- `tests/zn_agent/core/test_windows_atomic_overwrite.py`
- `.github/workflows/zn-atomic-overwrite-e2e.yml`
- `docs/ZN-IMPLEMENTATION-STATUS.md`
- `.agent/HANDOFF.md`

## Current risks / incomplete work

- broader Work durability remains partial beyond twenty-two verified windows;
- general per-task restore/rollback, arbitrary workspace checkpoints and user-visible restore points remain open;
- post-dispatch old-state equality remains intentionally insufficient for `verified_absent`;
- hard process death or cleanup failure can leave deterministic ZN-owned `.zn-write-*` / `.zn-backup-*` artifacts. There is not yet a general startup reconciliation/cleanup owner;
- WinError `1177` can represent namespace movement and remains uncertainty by design; any unique backup must be preserved until current reality proves what happened;
- replacement changes file identity, and broader Windows sharing/locking behavior, uncommon metadata/named-stream cases and host/power-loss durability are not yet claimed complete;
- the active product exact-overwrite path no longer truncates via `Path.write_text`, but generic `NativeBody` remains unchanged for non-active/shared callers;
- isolated parallel Work remains open;
- browser `PRESS`, broader click/text replacement/ARIA checkbox mutation, explicit tab/popup/frame ownership, headed managed browser and authenticated User Browser Bridge remain incomplete;
- Windows M8 continuity and SM1+ remain incomplete;
- identity, long-term memory, credentials/permissions, updater/signing, rollback and destructive self-maintenance remain human-approval boundaries.

## Task queue

### P1
Status: **COMPLETE / CI VERIFIED**

### P2
Status: **COMPLETE / CI VERIFIED**

### P3
Status: **COMPLETE / CI VERIFIED**

### P4
Status: **COMPLETE / CI VERIFIED NARROW**

### P5
Status: **PARTIAL / IN PROGRESS**

Completed bounded slices:

1. accepted Work ingress checkpoint (#19);
2. ordinary overwrite effect-present recovery/no-replay (#20);
3. overwrite pre-dispatch identity/drift guard (#21);
4. Windows staged atomic-overwrite process-death boundary (#22).

Next bounded P5 audit:

1. enumerate exact stage/backup namespace states across precommit, commit, cleanup, process death and WinError `1177`;
2. reconcile deterministic ZN-owned artifacts on restart only when exact durable attempt + namespace reality identify ownership;
3. never delete a backup that may be the only surviving pre-state copy;
4. make cleanup/reconciliation bounded and event-idempotent without creating replay authority;
5. test Windows sharing violations/locks and backup-cleanup failures;
6. add #23 only for a genuinely distinct crash/restart window proven by real Windows CI.

## Next real target

Continue P5 at the **owned atomic-overwrite artifact restart-reconciliation and cleanup boundary**. Keep `main` untouched.
