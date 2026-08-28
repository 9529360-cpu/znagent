# ZN Agent Handoff

Updated: 2026-08-28

## Current goal

P1-P4 are complete and CI-verified. P5 broader Work checkpoint/restore remains **PARTIAL / IN PROGRESS** with five bounded, verified slices:

1. accepted Work ingress checkpoint before resident-event creation (#19);
2. reality-gated ordinary overwrite effect-present recovery (#20);
3. privacy-bounded overwrite pre-dispatch identity/restart guard (#21);
4. Windows staged atomic-overwrite lifecycle that removes truncation-first process-death ambiguity for active exact overwrite (#22);
5. durable staged-overwrite precommit reconciliation that proves an exact fsynced stage never entered the Windows namespace commit API before granting a fresh lifecycle (#23).

Broader Work durability now has **TWENTY-THREE concrete crash/restart windows closed and verified**.

General per-task restore/rollback, arbitrary workspace snapshots, user-visible restore points, isolated parallel Work and any automatic replay after namespace commit has started remain open.

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
- P5 staged-overwrite reconciliation implementation/proof head: `a006ee90c9fc6e53f4b90d09f69b64ebf7ffd4c1`
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

Status: **PARTIAL / FIVE BOUNDED SLICES CI VERIFIED**

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

If restart occurs before Body attempt creation, exact unchanged identity may continue the inherited fresh lifecycle; drift returns to Investigation without mutation. Once a durable attempt exists, the old identity can never authorize replay.

```text
ZN Work Recovery E2E 33151244307  success  (95 tests, OK)
ZN CI                33151244298  success
```

### P5.4 - Windows staged atomic overwrite (#22)
Status: **BOUNDED SLICE COMPLETE / CI VERIFIED**

Implementation `b3cf799ec24d8f4bb89d82752c2396e70cc6a233`; exact proof descendant `403ac14f04866380a0d32c74bd9e250226dbb780`.

```text
ZN Atomic Overwrite E2E 33154361936  success  (10 tests, OK)
ZN CI                   33154361960  success
```

### P5.5 - durable staged-overwrite precommit reconciliation (#23)
Status: **BOUNDED SLICE COMPLETE / CI VERIFIED**

Implementation/proof head:

```text
a006ee90c9fc6e53f4b90d09f69b64ebf7ffd4c1  fix: reconcile staged overwrites before commit
```

New durable owner:

```text
runtime/python/zn_agent/core/atomic_overwrite_protocols.py
-> resident_atomic_overwrite_protocols
```

The protocol is independent of `WorkingState` and binds `event_id + Body signature + intent_id + side-effect attempt_id` to deterministic staging/backup paths, stage-ready identity, protocol version and `namespace_commit_started`.

Active physical/recovery sequence:

```text
#21 exact target pre-state
-> durable side-effect attempt
-> full same-directory stage + flush + fsync
-> durable stage-ready identity linked to attempt
-> recheck #21 target identity
-> durable namespace_commit_started marker
-> ReplaceFileW / no-replace MoveFileExW
-> inherited verification/completion lifecycle
```

Restart may close the old attempt `verified_absent` only when protocol/attempt match exactly, stage-ready is durable, commit-start remains false, target equals #21 pre-state, stage equals its durable identity and deterministic backup is absent. Then only the exact stage is cleaned and a fresh lifecycle may create a new attempt.

Commit-start=true, missing/legacy protocol, incomplete identity, tampered stage, target drift or unexpected backup all remain fail-closed. A large stage whose bounded identity cannot be proven exact may still complete normally while fresh; it simply cannot use #23 automatic restart reconciliation.

Additional Windows proofs include backup-cleanup retry after verified completion and a real sharing handle that denies delete without mutating the target.

Real focused Windows proof:

```text
ZN Atomic Overwrite E2E run 33157039949               success
  Prepare isolated runtime                            success
  Compile atomic overwrite path                       success
  Verify overwrite recovery and Windows semantics     success
```

Focused log: `Ran 16 tests in 5.601s` / `OK`.

Real full-tree proof on the same exact code head:

```text
ZN CI run 33157039957                                  success
ZN Kernel / Python / Windows                           success
  Boot isolated ZN distribution without a model       success
  Compile resident core                               success
  Run ZN core tests against working tree              success
ZN Source Boundary / Windows                           success
Electron / TypeScript / Windows                        success
Publish Windows CI statuses                            success
```

No local repository test run is claimed for this web-maintainer slice. Repository self-hosted Windows CI is the verification authority.

## Relevant files

- `runtime/python/zn_agent/core/file_identity.py`
- `runtime/python/zn_agent/core/overwrite_recovery_resident.py`
- `runtime/python/zn_agent/core/atomic_overwrite_protocols.py`
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

- broader Work durability remains partial beyond twenty-three verified windows;
- general per-task restore/rollback, arbitrary workspace checkpoints and user-visible restore points remain open;
- post-dispatch old-state equality remains intentionally insufficient for `verified_absent`;
- #23 proves only the precommit state where a matching durable protocol says the namespace API never started. Commit-start=true, WinError `1177`, legacy/no-protocol and incomplete-stage-identity states remain uncertainty;
- a backup that may be the only surviving pre-state copy is preserved; broader retained-backup lifecycle/terminal cleanup is not complete;
- deterministic artifacts outside an exact provable protocol have no general startup GC owner;
- replacement changes file identity; uncommon metadata/named-stream behavior and host/power-loss durability remain open;
- generic `NativeBody` remains unchanged for non-active/shared callers;
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
4. Windows staged atomic-overwrite process-death boundary (#22);
5. exact staged precommit restart reconciliation / durable namespace-commit boundary (#23).

Next bounded P5 audit:

1. enumerate target/stage/backup namespace states once `namespace_commit_started=true`;
2. reconcile exact durable attempt/protocol with current namespace without turning old-state equality into replay authority;
3. preserve any potentially unique backup;
4. define bounded retained-backup cleanup only after stronger completion/recovery truth;
5. continue real Windows sharing/cleanup failure coverage;
6. add #24 only for a genuinely distinct crash/restart window proven by real Windows CI.

## Next real target

Continue P5 at the **atomic-overwrite commit-start / WinError 1177 namespace reconciliation and retained-backup ownership boundary**. Keep `main` untouched.
