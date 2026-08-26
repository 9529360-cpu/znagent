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

## Current checkpoint - 2026-08-26

M10 canonical source promotion remains complete. Ordinary development remains on `dev/zn-agent`; `main` remains unchanged at `8234a835dea604783cea0bd9d28a40de654ec03d`.

Latest implementation checkpoint before this documentation update:

```text
5c679ea742a2c83578c85c215cf582ce8c22a8cf
feat: surface uncertain Work cancellation in desktop
```

Status: **THE EXPLICIT CANCELLATION PATH FOR UNVERIFIABLE OUTSIDE-WORLD EFFECTS IS NOW REACHABLE END TO END FROM THE RESIDENT STORE THROUGH WILL/WORK/RPC/ELECTRON TO A RECOVERY-ONLY WORKBENCH CONTROL. CANCELLATION REMAINS A CONTROL/LIFECYCLE RESULT, NOT ORDINARY FAILURE LEARNING AND NOT EVIDENCE ABOUT WHETHER THE OUTSIDE-WORLD EFFECT HAPPENED. WORK DURABILITY REMAINS PARTIAL; THIS SLICE DOES NOT IMPLEMENT ARBITRARY IN-FLIGHT ACTION CANCELLATION OR RESOLVE THE SEPARATE POST-COMPLETION LIFE-OBSERVATION CONSISTENCY GAP.**

## 1. Durable cancellation semantics

The verified Store primitive remains:

```text
6c655c761099cc6a206028285cc228d65f3e7734
feat: add atomic uncertain Work cancellation
```

`KernelStore.cancel_uncertain_event()` accepts only the proven recovery state for an unfinished event whose `WorkingState` and started side-effect attempt belong to that same event, with:

```text
stage == side_effect_recovery
blocked_by == outside_world_effect_uncertain
replay_blocked == true
attempt status == started
no durable EventOutcome yet exists
```

One SQLite transaction then performs:

```text
side-effect attempt -> work_abandoned
event -> terminal
EventOutcome.cancelled = true
EventOutcome.execution_path = control
WorkingState -> idle
```

`work_abandoned` is deliberately non-epistemic. It means ZN will no longer continue that Work. It does not assert that the external effect occurred, and it does not assert that the effect was absent.

Normal completion APIs reject cancelled outcomes so callers cannot bypass the dedicated atomic transaction.

## 2. Reachable resident-owned control chain

The real active chain is now:

```text
KernelStore.cancel_uncertain_event
-> Resident explicit cancellation authority
-> IntentionalResident / NativeWill cancelled semantics
-> ResidentWorkControl ownership + finalization/reconciliation
-> ResidentRpcServer work_cancel
-> Electron resident process + IPC
-> preload bridge
-> desktop environment typing
-> resident-client recovery normalization + cancelZnWork
-> Workbench recovery-only Stop work control
```

Key implementation checkpoints after the Store primitive include:

```text
1024752da9741326cf133e27c51358e45b9f6ef2  Will cancelled semantics
01a4a645e68bda87d74697af0fd9aacb9181e96b  Resident cancellation authority
1ad68ddb5f2e423ea02d249553aa404c98266b2d  Resident Work cancellation control
4cf85f33a6c000f31ed839e405bd2bb978e8d83e  work_cancel RPC
c47887bbeb5e02fe89fc4b30bd0494c329df8e83  reconciliation connection cleanup
55d6922bc0cf51a05939ced26fe4386cd5f4cc48  reachable cancellation regression coverage
0be9340e2db305be7134d403a1ecdf392a7f36b4  focused workflow coverage
4f29aa71e8b7d8b35522360d22b79c9177b22dd7  Electron IPC bridge
ad9998892cde6ee366d0181aece6c68fd5f5329d  preload bridge
48ececc7d9f8a48e83097cf38f1158b1d8ab27a1  desktop bridge typing
510b2e6219763180f8177847619bc9795f612d56  recovery projection + cancelZnWork
831bba875e77ecddd338bb2b464844171b479e93  resident RPC method typing
5c679ea742a2c83578c85c215cf582ce8c22a8cf  Workbench control + ownership regression
```

Cancellation bypasses ordinary Life action-failure observation. Will consumes explicit `cancelled` state both directly and during restart reconciliation, so it does not reconstruct cancellation as `step_failed`, successful completion, or failure-learning evidence.

`ResidentWorkControl` owns the Work-level transition. It validates thread/event ownership before cancelling, maps the durable cancelled outcome to public `status/stage = cancelled`, finalizes the Work without `failed: true`, and does not manufacture artifacts for an external effect whose truth remains unknown.

## 3. Desktop behavior and safety boundary

The Workbench does **not** expose a generic stop button for arbitrary executing actions.

The user control appears only when the resident reports a sanitized recovery projection with `replayBlocked === true`. The UI states that the outside-world effect is uncertain and that ZN will not replay it automatically.

`Stop work` calls the resident-owned `work_cancel` path. The copy explicitly preserves the truth boundary:

- stopping prevents further ZN action for that Work;
- stopping cannot undo an outside-world effect;
- stopping does not prove whether that effect already happened.

The renderer does not become cancellation authority. It requests the transition; the resident Store remains the authority that accepts or rejects it.

## 4. Focused cancellation proof

The reachable backend control path is covered by `tests/zn_agent/core/test_work_cancel_control.py`, including:

```text
Resident cancellation bypasses Life ordinary failure observation
Will restart reconciliation preserves neutral/control cancellation semantics
Work control finalizes cancellation without failed Work or uncertain artifacts
work_cancel RPC repairs the cancellation/finalization crash window
```

Exact focused Windows proof:

```text
ZN Work Recovery E2E run 33016402296
head 0be9340e2db305be7134d403a1ecdf392a7f36b4
result success
```

The earlier atomic Store proof also remains:

```text
ZN Work Recovery E2E run 33014912312
head 6c655c761099cc6a206028285cc228d65f3e7734
result success
```

## 5. Desktop CI truth for the reachable UI

Current-head ordinary CI run:

```text
ZN CI run 33017359211
head 5c679ea742a2c83578c85c215cf582ce8c22a8cf
```

Verified so far in that run:

```text
Electron / TypeScript / Windows    success
  typecheck                         success
  independent ZN desktop bundle    success
  desktop ownership/packaged/update/handoff tests  success
  release/runtime/package verifier tests           success
ZN Source Boundary / Windows       success
ZN Kernel / Python / Windows       in progress at documentation sync
```

The preceding `510b2e` ordinary CI exposed the missing Electron resident RPC union and therefore failed TypeScript. `831bba87` fixed that exact defect; its Electron / TypeScript job then passed before the newer head superseded the run. The current `5c679ea7` Electron job independently passes with the Workbench cancellation UI and updated ownership regression included.

Do not call the whole ordinary CI green while the Kernel job is unfinished or failing.

## 6. Known ordinary Kernel issue remains separate

The ordinary Windows Kernel suite has an existing, documented NetworkService DOS-8.3 versus long-path identity failure family. A prior exact run at the atomic cancellation checkpoint was:

```text
ZN CI run 33014912300
head 6c655c761099cc6a206028285cc228d65f3e7734
Electron / TypeScript / Windows    success
ZN Source Boundary / Windows       success
ZN Kernel / Python / Windows       failure
Kernel suite                        573 tests, 16 errors, 5 skipped
```

Those errors are concentrated around repository targeted-test/text-delta verification and terminal/Work-artifact cwd identity, with cleanup `PermissionError` traces as secondary fallout. The earlier partial attempted path fix was reverted normally in `db647cb49c3de014aa82bc28ec87c1c4e5b02c15`; no half-fix remains.

This path-identity issue remains **KNOWN / DEFERRED BY CURRENT PRODUCT PRIORITY** unless it materially blocks the active product objective or is explicitly reprioritized.

## 7. What remains partial

This cancellation slice is complete enough to be reachable and tested, but broader Work durability is still **PARTIAL**.

Open concerns include:

- durable event completion versus later Life self-observation failure/recovery;
- Windows continuity M8;
- browser PRESS, broader click/editing/multi-select/page lifecycle;
- authenticated User Browser Bridge control;
- SM1+ self-maintenance stages;
- the deferred Windows path-identity family above.

High-risk identity, long-term memory, credential/permission, updater/signing, rollback, and destructive self-maintenance changes continue to require human approval.

## 8. Next real target

The next resident-level consistency target is **post-completion Life observation recovery**: preserve the already-durable event/Work outcome if later resident self-observation fails, and make that later repairable observation state explicit rather than weakening terminal truth.

Do not reopen arbitrary action cancellation, do not reinterpret cancellation as effect evidence, and do not move development to `main`.
