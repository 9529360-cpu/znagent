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
a006ee90c9fc6e53f4b90d09f69b64ebf7ffd4c1  fix: reconcile staged overwrites before commit
```

Status: **BROADER WORK DURABILITY REMAINS PARTIAL. TWENTY-THREE CONCRETE CRASH/RESTART WINDOWS ARE NOW CLOSED AND VERIFIED. P5 HAS FIVE BOUNDED CI-VERIFIED SLICES. WINDOW #23 ADDS A DURABLE, ATTEMPT-BOUND NAMESPACE-COMMIT CHECKPOINT SO A RESTART CAN DISTINGUISH AN EXACT FSYNCED STAGE THAT NEVER ENTERED THE WINDOWS COMMIT API FROM A WRITE WHOSE COMMIT MAY HAVE STARTED. GENERAL PER-TASK RESTORE/ROLLBACK REMAINS OPEN/PARTIAL.**

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
- active Windows exact overwrite stages complete text in the target directory, fsyncs it, rechecks the durable pre-state and uses a Windows namespace replacement/move instead of truncating first;
- the staged Windows overwrite protocol now owns an independent durable SQLite checkpoint tied to the exact side-effect attempt, recording stage readiness/identity and whether namespace commit was entered before the Windows API is invoked.

Generic nervous `perceive()` remains intentionally plastic and is not an exactly-once API.

## 2. Twenty-three proven broader Work crash/restart windows

The previously verified windows #1-#22 remain valid. The most recent bounded sequence is:

19. accepted Work survives hard crash before resident-event persistence by reconstructing the exact pending event and WorkRun linkage without execution/replay authority;
20. an exact overwrite that may already have reached the filesystem survives via durable side-effect ownership. Restart performs read-only postcondition verification; exact intended text becomes `verified_effect`, otherwise replay remains blocked;
21. a fresh overwrite that loses the process after durable pre-state identity but before Body attempt is revalidated on restart. Exact unchanged identity may continue the inherited fresh lifecycle; drift returns to Investigation without mutation;
22. an active Windows exact overwrite no longer truncates the target before the full replacement text exists. ZN stages complete text, fsyncs it, rechecks #21 identity, then uses `ReplaceFileW` for existing regular files or no-replace `MoveFileExW` for missing targets. WinError `1177` remains uncertainty;
23. after the durable Body attempt and an exact fsynced stage exist, ZN now durably records the stage identity and separately persists `namespace_commit_started` immediately before `ReplaceFileW` / `MoveFileExW`. If restart proves the protocol belongs to the exact attempt, the commit marker is still false, target equals #21 pre-state, stage identity is exact and the deterministic backup is absent, the old attempt is causally `verified_absent`, the exact stage is cleaned and execution returns to a fresh overwrite lifecycle. If commit-start is true or any evidence is incomplete/drifted/tampered, replay remains blocked.

The crash-window count is now twenty-three. Browser lifecycle proofs, synchronous caller control, shared-attempt pruning and Body-accounting invariants remain additional evidence, not artificial crash-window counts.

## 3. Active synchronous recovery boundary

The active caller chain remains:

```text
provider_bridge.build_resident_runtime()
-> RecoveryBoundedResidentRuntime
   -> AtomicOverwriteRecoveryResidentRuntime
   -> OverwriteRecoveryResidentRuntime
   -> DurableBodyAccountingResidentRuntime
   -> CapabilityRecoveryResidentRuntime
   -> FocusedModernTextResidentRuntime
   -> embodied/focused/pointer completion owners
```

Atomic overwrite now adds an independent persistence owner inside the active product layer:

```text
runtime/python/zn_agent/core/atomic_overwrite_protocols.py
-> resident_atomic_overwrite_protocols
```

That ledger is intentionally separate from `WorkingState`. A Body callback can persist the commit boundary while the outer synchronous owner still holds an older in-memory `WorkingState`; a later normal state save therefore cannot erase the causal marker.

`ResidentRecoveryRequired` remains caller-control flow, not task failure. Exact read-only recovery may continue; unresolved replay-blocked uncertainty yields for explicit lifecycle decision without killing asynchronous resident life.

## 4. Shared side-effect-attempt owner

Replay-sensitive Body and compiled-capability execution continue to converge on:

```text
runtime/python/zn_agent/core/side_effect_attempts.py
-> resident_side_effect_attempts
```

`SideEffectAwareBody` deliberately retains its reusable command/append contract. Exact overwrite additions remain active-product layers: `OverwriteAwareBody` owns replay semantics and `AtomicOverwriteAwareBody` owns the Windows physical commit/restart protocol. Generic/shared callers do not silently acquire new semantics.

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

## 6. P5 - durable Work checkpoint / restore foundation

Status: **PARTIAL / FIVE BOUNDED SLICES CI VERIFIED**

P5 is not generic workspace rollback.

### 6.1 Accepted Work ingress checkpoint (#19)
Proof head `2c20b8bded96ce07c6ec43263cc77b7bd10a7a82`.

```text
ZN Work Recovery E2E 33124662199  success
ZN CI                33124662367  success
```

### 6.2 Reality-gated overwrite effect-present recovery (#20)
Proof head `c4276f8b151d2c45b69368cb414f012bf0644d01`.

```text
ZN Work Recovery E2E 33129111422  success
ZN CI                33129111419  success
```

### 6.3 Privacy-bounded overwrite pre-dispatch identity (#21)
Proof head `97803f8d0616c1f2b30a61af5acc686f1256cd11`.

```text
ZN Work Recovery E2E 33151244307  success  (95 tests, OK)
ZN CI                33151244298  success
```

Once a durable side-effect attempt exists, old pre-state equality is never replay authority.

### 6.4 Windows staged atomic-overwrite lifecycle (#22)
Implementation commit `b3cf799ec24d8f4bb89d82752c2396e70cc6a233`.
Exact proof descendant `403ac14f04866380a0d32c74bd9e250226dbb780`.

```text
ZN Atomic Overwrite E2E 33154361936  success  (10 tests, OK)
ZN CI                   33154361960  success
```

### 6.5 Durable staged-overwrite precommit reconciliation (#23)

Implementation commit:

```text
a006ee90c9fc6e53f4b90d09f69b64ebf7ffd4c1  fix: reconcile staged overwrites before commit
```

New/changed owners:

```text
runtime/python/zn_agent/core/atomic_overwrite_protocols.py
runtime/python/zn_agent/core/staged_text_write.py
runtime/python/zn_agent/core/atomic_overwrite_resident.py
tests/zn_agent/core/test_windows_atomic_overwrite.py
.github/workflows/zn-atomic-overwrite-e2e.yml
```

Durable sequence for active Windows exact overwrite is now:

```text
#21 exact target pre-state
-> durable side-effect attempt
-> complete same-directory stage + flush + fsync
-> durable stage-ready identity linked to exact attempt
-> recheck #21 target identity
-> durable namespace_commit_started marker
-> ReplaceFileW / MoveFileExW
-> inherited semantic/Git/test verification and completion ownership
```

Safe restart reconciliation is deliberately narrow. Automatic `verified_absent` is allowed only when:

- protocol version and intent/signature match the current Work;
- protocol is linked to the exact recovery attempt ID;
- stage-ready was durably recorded;
- `namespace_commit_started` is still false;
- current target exactly equals the durable #21 pre-state;
- current stage exactly equals its durable stage identity;
- deterministic backup path is absent.

Only then is the old attempt closed `verified_absent`, the exact stage removed and a fresh lifecycle allowed to create a new attempt. Missing/legacy protocol, incomplete stage identity, stage tampering, target drift, unexpected backup or a true commit-start marker all remain fail-closed.

A stage whose bounded identity cannot be exact (for example a regular file beyond the identity sensor's complete-digest bound) is still allowed through the normal fresh commit path. It simply cannot use #23 automatic restart proof; this avoids turning recovery metadata limits into a write-size regression.

Focused real Windows proof on exact head `a006ee90...`:

```text
ZN Atomic Overwrite E2E run 33157039949               success
  Prepare isolated runtime                            success
  Compile atomic overwrite path                       success
  Verify overwrite recovery and Windows semantics     success
```

Focused log: `Ran 16 tests in 5.601s` / `OK` (4 prior overwrite-recovery regressions + 12 Windows atomic-overwrite tests).

The Windows tests prove, in addition to #22:

- crash after durable stage identity but before commit marker safely reconciles old attempt `verified_absent`, cleans stage, then succeeds through a fresh attempt;
- crash after durable commit-start marker never auto-replays;
- tampered stage never grants replay and is preserved for investigation;
- an unexpected backup prevents replay and is not deleted;
- backup-cleanup failure after successful replacement is retried after verified completion;
- a real Windows sharing handle that denies delete causes a no-mutation failure and preserves the target.

Full-tree proof on the same exact code head:

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

## 7. What remains partial / open

Open work includes:

- broader Work durability beyond the twenty-three proven windows;
- general per-task restore/rollback, arbitrary workspace checkpoints and user-visible restore points;
- post-dispatch overwrite old-state equality remains insufficient for `verified_absent` because it is not causal proof that the effect never happened;
- #23 reconciles only the exact precommit state where a durable protocol proves namespace commit never started. Commit-start=true, WinError `1177`, legacy/no-protocol and incomplete-identity cases remain uncertainty by design;
- a backup that may be the only surviving pre-state copy is preserved rather than garbage-collected automatically. A broader retained-backup lifecycle/terminal cleanup owner is still open;
- deterministic ZN artifacts outside an exact provable protocol still have no general startup garbage-collection owner;
- replacement changes file identity; uncommon Windows metadata/named-stream cases and host/power-loss durability beyond current fsync/Windows API guarantees are not claimed complete;
- active product exact overwrite no longer truncates via `Path.write_text`, but generic `NativeBody` remains unchanged for non-active/shared callers;
- isolated parallel Work;
- long-horizon repetition/drift/provider-replacement benchmarks for resident intelligence;
- browser `PRESS`, broader click/text replacement/ARIA checkbox mutation, explicit tab/popup/frame ownership, headed managed-browser UX and authenticated User Browser Bridge;
- Windows M8 install / N->N+1 / rollback / signing evidence;
- SM1+ self-maintenance;
- high-risk identity, long-term-memory, credential/permission, updater/signing, rollback and destructive self-maintenance changes remain human-approval boundaries.

## 8. Next real target

Continue P5 at the **atomic-overwrite commit-start / WinError 1177 namespace reconciliation and retained-backup ownership boundary**. The next audit should:

1. enumerate exact target/stage/backup namespace states once `namespace_commit_started=true`;
2. keep old-state equality and backup presence from becoming replay authority;
3. determine which states can be read-only classified as verified effect, explicit contradiction or unresolved uncertainty using the exact durable attempt/protocol;
4. preserve any backup that may be the only surviving pre-state copy until stronger terminal truth exists;
5. define bounded, event-idempotent retained-backup cleanup only after semantic completion/recovery truth makes deletion safe;
6. cover real/synthetic Windows sharing and cleanup failures without broadening generic `NativeBody`;
7. add crash/restart window #24 only if a genuinely distinct interruption is closed and real Windows CI proves it.

Keep `main` untouched during ordinary development.
