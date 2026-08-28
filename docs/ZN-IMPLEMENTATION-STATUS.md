# ZN implementation status

> Architecture contract: [`../ZN.md`](../ZN.md)
>
> Product capability ledger: [`ZN-PRODUCT-CAPABILITY-MAP.md`](ZN-PRODUCT-CAPABILITY-MAP.md)
>
> Source adoption boundary: [`ZN-SOURCE-EXTRACTION.md`](ZN-SOURCE-EXTRACTION.md)
>
> Self-maintenance contract: [`ZN-SELF-MAINTENANCE.md`](ZN-SELF-MAINTENANCE.md)
>
> Real code, Git state and CI outrank this ledger.

Development branch: `dev/zn-agent`. Canonical source/release branch: `main`.

## Current checkpoint - 2026-08-28

`main` remains unchanged at:

```text
8234a835dea604783cea0bd9d28a40de654ec03d  docs: close M10 handoff state
```

Latest P5 implementation commit:

```text
b3cf799ec24d8f4bb89d82752c2396e70cc6a233  fix: stage Windows overwrite commits atomically
```

CI-enabling descendant used for exact current proof:

```text
403ac14f04866380a0d32c74bd9e250226dbb780  ci: allow Windows atomic overwrite checks
```

Status: **BROADER WORK DURABILITY REMAINS PARTIAL. TWENTY-TWO CONCRETE CRASH/RESTART WINDOWS ARE NOW CLOSED AND VERIFIED. P5 HAS FOUR BOUNDED CI-VERIFIED SLICES. WINDOW #22 REMOVES THE ACTIVE WINDOWS EXACT-OVERWRITE TRUNCATION-FIRST PROCESS-DEATH WINDOW BY STAGING COMPLETE TEXT BEFORE THE FINAL NAMESPACE COMMIT. GENERAL PER-TASK RESTORE/ROLLBACK REMAINS OPEN/PARTIAL.**

## 1. Durable foundations

Established durable boundaries include:

- terminal event + exact `EventOutcome` + idle `WorkingState` publish atomically;
- Life observation is secondary and repairable without replaying a completed action;
- event-identity-safe nervous outcome perception uses receipts;
- Windows canonical path identity is shared across Investigation, Body/Terminal, Git, Work, verification and procedural learning;
- Work cancellation is atomic and bypasses failure learning because cancellation is lifecycle/control truth;
- replay-sensitive Body and compiled-capability effects persist durable attempt ownership before dispatch;
- unresolved outside-world effects remain uncertainty rather than fabricated success/failure or replay permission;
- cumulative Body/accounting evidence is applied only after the relevant semantic checkpoint is durable;
- external provider dispatch has durable attempt identity and unknown provider outcomes block replay;
- terminal-safe pruning cannot remove nonterminal recovery truth;
- accepted Work ingress has a pre-event checkpoint so accepted user work cannot disappear before resident-event persistence;
- active ordinary overwrite writes participate in resident side-effect ownership/recovery without broadening the reusable generic Body contract;
- fresh overwrite owns a privacy-bounded pre-dispatch file-identity checkpoint and re-observes it after restart before stale work may continue;
- active Windows exact overwrite now writes complete text to a same-directory ZN-owned stage, fsyncs it, rechecks the durable pre-state immediately before commit, then performs a Windows namespace replacement/move rather than truncating the target first.

Generic nervous `perceive()` remains intentionally plastic and is not an exactly-once API.

## 2. Twenty-two proven broader Work crash/restart windows

The verified windows are:

1. missing Work ingress linkage after durable resident event creation;
2. recovery decision committed before the next `WorkingState` save;
3. append dispatch durably `observed` before checkpoint save;
4. generic guarded side-effect dispatch durably `observed` before checkpoint save;
5. verified append recovery success before terminal `EventOutcome`;
6. common verified Body success resumes from `native_completion` without Body replay;
7. base resident investigation success resumes from `investigation_completion` without native reprobe;
8. verified semantic/focused/UI completion resumes from `native_completion` without resensing or input replay;
9. base resident MEMORY/CAPABILITY success resumes from `resident_completion` without re-recall/re-execution;
10. compiled capability execution persists durable `started`/`observed` ownership, blocks blind replay and applies successful accounting event-idempotently;
11. durable observed compiled-capability failure resumes into Investigation without replay or duplicate failure evidence, while malformed observed truth fails closed;
12. zero-model terminal budget-blocked failure persists exact `terminal_failure` truth before task accounting and terminal publication;
13. deterministic outer `run_once()` exception publication uses the same terminal-failure owner while refusing to overwrite durable success or outside-world uncertainty;
14. structured-memory success persists `resident_completion` before event-idempotent task/knowledge accounting;
15. native-investigation success persists `investigation_completion` before event-idempotent ability/knowledge/task accounting;
16. external cognition persists exact `external_completion` before resident metrics, success learning and terminal publication so restart does not replay the model;
17. external kernel attempts persist stable goal/attempt identity, result, deterministic proposal identity and exactly-once route-quality accounting;
18. crash after provider dispatch but before returned-result persistence becomes unknown-provider-outcome uncertainty: provider replay is blocked and no learning is fabricated;
19. accepted Work survives hard crash before resident-event persistence by reconstructing the exact pending event and WorkRun linkage without execution/replay authority;
20. an exact overwrite that may already have reached the filesystem survives via durable side-effect ownership. Restart performs read-only postcondition verification; exact intended text becomes `verified_effect`, otherwise replay remains blocked;
21. a fresh overwrite that loses the process after durable pre-state identity but before Body attempt is revalidated on restart. Exact unchanged identity may continue the inherited fresh lifecycle; drift returns to Investigation without mutation;
22. an active Windows exact overwrite no longer truncates the target before the full replacement text exists. ZN stages complete text in the target directory and fsyncs it, then rechecks #21 pre-state immediately before namespace commit. Existing regular files use `ReplaceFileW` with a deterministic backup; missing targets use `MoveFileExW` without replace permission. Process death after staging and before commit leaves the original target intact. Precommit drift or deterministic pre-commit failure closes the durable attempt as `verified_absent`; the documented `ERROR_UNABLE_TO_MOVE_REPLACEMENT_2` (`1177`) remains side-effect uncertainty because namespace state may already have moved, so replay is still forbidden.

The crash-window count is now twenty-two. Browser lifecycle proofs, synchronous caller control, shared-attempt pruning and Body-accounting invariants remain additional evidence, not artificial crash-window counts.

## 3. Active synchronous recovery boundary

The active caller chain is:

```text
provider_bridge.build_resident_runtime()
-> RecoveryBoundedResidentRuntime
   -> AtomicOverwriteRecoveryResidentRuntime
   -> OverwriteRecoveryResidentRuntime
   -> DurableBodyAccountingResidentRuntime
   -> CapabilityRecoveryResidentRuntime
   -> FocusedModernTextResidentRuntime
   -> embodied/focused/pointer completion owners

normal desktop Work:
ResidentRpcServer.work_start
-> ResidentWorkControl.start
-> RecoveryBoundedWorkLedger.start
-> background resident life loop
-> work_progress / work_cancel

legacy/direct synchronous callers:
resident.submit() / run_once()
-> RecoveryBoundedResidentRuntime synchronous recovery control
```

`ResidentRecoveryRequired` remains caller-control flow, not task failure. Exact read-only recovery may continue; unresolved replay-blocked uncertainty yields for explicit lifecycle decision without killing asynchronous resident life.

## 4. Shared side-effect-attempt owner

Replay-sensitive Body and compiled-capability execution converge on:

```text
runtime/python/zn_agent/core/side_effect_attempts.py
-> resident_side_effect_attempts
```

`SideEffectAwareBody` deliberately retains its reusable command/append contract. Exact overwrite additions remain active-product layers: `OverwriteAwareBody` owns replay semantics and `AtomicOverwriteAwareBody` owns the Windows physical commit primitive. Generic/shared callers do not silently acquire new semantics.

## 5. P1-P4 verified stages

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

Explicit tab/popup actions, frame identity, persistent browser-session recovery and `PRESS` remain open.

## 6. P5 - durable Work checkpoint / restore foundation

Status: **PARTIAL / FOUR BOUNDED SLICES CI VERIFIED**

P5 is not generic workspace rollback.

### 6.1 Accepted Work ingress checkpoint (#19)

Proof head `2c20b8bded96ce07c6ec43263cc77b7bd10a7a82`.

```text
ZN Work Recovery E2E 33124662199  success
ZN CI                33124662367  success
```

### 6.2 Reality-gated overwrite effect-present recovery (#20)

Proof head `c4276f8b151d2c45b69368cb414f012bf0644d01`.

Exact intended current text completes without replay; mismatch, truncation or read failure preserves uncertainty and the target.

```text
ZN Work Recovery E2E 33129111422  success
ZN CI                33129111419  success
```

### 6.3 Privacy-bounded overwrite pre-dispatch identity (#21)

Proof head `97803f8d0616c1f2b30a61af5acc686f1256cd11`.

Owner:

```text
runtime/python/zn_agent/core/file_identity.py
```

The identity sensor stores no raw file body. It records canonical path, type and bounded filesystem metadata; stable regular files up to 8 MiB may also receive a complete SHA-256 observed with before/after stat agreement. Unsupported, unstable or unprovable identity fails closed.

```text
ZN Work Recovery E2E 33151244307  success  (95 tests, OK)
ZN CI                33151244298  success
```

Once a durable side-effect attempt exists, old pre-state equality is never replay authority.

### 6.4 Windows staged atomic-overwrite lifecycle (#22)

Implementation commit:

```text
b3cf799ec24d8f4bb89d82752c2396e70cc6a233  fix: stage Windows overwrite commits atomically
```

New owners:

```text
runtime/python/zn_agent/core/staged_text_write.py
runtime/python/zn_agent/core/atomic_overwrite_resident.py
tests/zn_agent/core/test_windows_atomic_overwrite.py
.github/workflows/zn-atomic-overwrite-e2e.yml
```

Active Windows exact overwrite now performs:

```text
durable side-effect attempt
-> write complete same-directory stage with exclusive create
-> flush + fsync stage
-> recheck #21 durable pre-state identity
-> existing regular target: ReplaceFileW(target, stage, backup)
   missing target: MoveFileExW(stage, target, WRITE_THROUGH) without REPLACE_EXISTING
-> inherited semantic/Git/test verification and completion ownership
```

Important boundaries:

- existing regular-file replacement uses Windows `ReplaceFileW` rather than a naive `os.replace()` so the API can merge the replaced file's security/metadata semantics, including DACL and creation-time behavior;
- readonly and reparse/symlink targets fail closed in the primitive rather than silently changing target meaning;
- a file appearing during the missing-target race is not clobbered;
- precommit drift is a precondition contradiction and its attempt is resolved `verified_absent`, not learned as a Body failure and not left replay-blocked;
- WinError `1177` remains uncertain and is routed into the existing overwrite recovery owner because the old target may already have moved to the backup name;
- deterministic ZN artifact names are privacy-bounded hashes and owned per exact overwrite attempt.

Real focused Windows proof on exact descendant `403ac14f04866380a0d32c74bd9e250226dbb780`:

```text
ZN Atomic Overwrite E2E run 33154361936               success
  Prepare isolated runtime                            success
  Compile atomic overwrite path                       success
  Verify overwrite recovery and Windows semantics     success
```

Focused log: `Ran 10 tests in 2.695s` / `OK` (4 prior overwrite-recovery regressions + 6 new Windows atomic-overwrite tests).

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

The first focused run `33154248922` failed before compile/tests because the new workflow omitted the repository's Windows PowerShell execution-policy bypass. Commit `403ac14f...` fixed only that workflow shell configuration; the subsequent focused and full-tree proofs above are green.

No local repository test run is claimed for this web-maintainer slice. Repository self-hosted Windows CI is the verification authority.

## 7. Resident intelligence architecture direction

ZN continues to distinguish:

```text
built-in resident competence
+ learned resident competence
+ replaceable external cognition
```

Mature general computer/recovery mechanics should become explicit ZN-owned sensing/state/procedure/verification/recovery where concrete and verifiable. Post-birth learning should concentrate on user, environment, project and recurring-work experience. This direction remains broader than current implementation.

## 8. What remains partial / open

Open work includes:

- broader Work durability beyond the twenty-two proven windows;
- general per-task restore/rollback, arbitrary workspace checkpoints and user-visible restore points;
- post-dispatch overwrite old-state equality remains insufficient for `verified_absent` because it is not causal proof that the effect never happened;
- deterministic `.zn-write-*` / `.zn-backup-*` artifacts can remain after hard process death or cleanup failure. ZN has exact owned names and bounded cleanup, but no general startup reconciliation/garbage-collection owner yet;
- `ERROR_UNABLE_TO_MOVE_REPLACEMENT_2` remains intentionally uncertain; recovery must inspect current namespace/content and preserve any unique backup rather than invent rollback/replay authority;
- active Windows exact overwrite no longer uses truncation-first `Path.write_text(...)`, but the generic `NativeBody` primitive still exists for non-active/shared callers and must not be confused with the active product contract;
- replacement changes file identity; broader Windows sharing/locking behavior, uncommon metadata/named-stream cases and host/power-loss durability beyond the current fsync/Windows API guarantees are not claimed complete;
- isolated parallel Work;
- long-horizon repetition/drift/provider-replacement benchmarks for resident intelligence;
- browser `PRESS`, broader click/text replacement/ARIA checkbox mutation, explicit tab/popup/frame ownership, headed managed-browser UX and authenticated User Browser Bridge;
- Windows M8 install / N->N+1 / rollback / signing evidence;
- SM1+ self-maintenance;
- high-risk identity, long-term-memory, credential/permission, updater/signing, rollback and destructive self-maintenance changes remain human-approval boundaries.

## 9. Next real target

Continue P5 at the **owned atomic-overwrite artifact restart-reconciliation boundary**. The next audit should:

1. enumerate every same-directory stage/backup namespace state before commit, after successful commit, after deterministic failure, after process death and after WinError `1177`;
2. prove on restart which artifact belongs to the exact durable attempt without storing raw user content as control metadata;
3. preserve any artifact that may be the only remaining pre-state copy and never treat cleanup as mutation/replay authority;
4. define bounded, event-idempotent cleanup/reconciliation for stale ZN-owned artifacts and cleanup failures;
5. test Windows sharing violations/locks and backup cleanup failures against current namespace reality;
6. preserve inherited repo baseline / Git delta / targeted-test / semantic verification owners;
7. add crash/restart window #23 only if a genuinely distinct interruption is closed and real Windows CI proves it.

Keep `main` untouched during ordinary development.
