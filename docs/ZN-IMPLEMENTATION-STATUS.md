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
6c655c761099cc6a206028285cc228d65f3e7734
feat: add atomic uncertain Work cancellation
```

Status: **THE DURABLE BACKEND CANCELLATION PRIMITIVE FOR UNVERIFIABLE WORK IS IMPLEMENTED AND VERIFIED. IT ATOMICALLY TERMINATES THE RESIDENT EVENT, PERSISTS AN EXPLICIT CANCELLED/CONTROL OUTCOME, CLEARS THE ACTIVE CHECKPOINT, AND MARKS THE UNCERTAIN SIDE-EFFECT ATTEMPT `work_abandoned` WITHOUT CLAIMING WHETHER THE OUTSIDE-WORLD EFFECT HAPPENED. WORK DURABILITY REMAINS PARTIAL UNTIL THIS PRIMITIVE IS WIRED THROUGH RESIDENT/WILL, WORK/RPC, ELECTRON/PRELOAD, RESIDENT-CLIENT, AND WORKBENCH.**

## 1. Durable Work foundation

The active ownership chain remains:

```text
ResidentRpcServer
-> ResidentWorkLedger
-> resident event lifecycle
-> KernelStore events + singleton WorkingState
-> resident life stages
-> EventOutcome
-> Work finalization
```

Already verified foundations remain intact:

- interrupted `PROCESSING` work returns to `PENDING` on reconstruction while the exact same-event checkpoint survives;
- normal terminalization publishes event terminal state, `EventOutcome`, and idle `WorkingState` in one SQLite transaction;
- generic non-replayable command/append actions commit a `started` side-effect attempt before dispatch and refuse blind replay after interruption;
- trustworthy append postconditions may resolve uncertainty from fresh read-only reality as `verified_effect` or `verified_absent`;
- `work_progress.recovery` is a sanitized allowlisted projection and never exports raw commands, appended text, environment values, signatures, internal paths/output, or arbitrary resident state.

The previous sanitized recovery projection checkpoint remains:

```text
643e174bfc6dcdbe313df1a5434427319d5f068f
feat: expose sanitized Work recovery progress
ZN Work Recovery E2E run 33011631232
20/20 passed
```

## 2. Atomic uncertain-Work cancellation primitive

Implementation:

```text
6c655c761099cc6a206028285cc228d65f3e7734
feat: add atomic uncertain Work cancellation
```

The durable model now distinguishes lifecycle cancellation from ordinary execution failure:

```text
ExecutionPath.CONTROL
EventOutcome.cancelled = true
success = false
```

`cancelled` is appended compatibly to the existing dataclasses, and old persisted outcomes default to `cancelled=false` when read.

`KernelStore.cancel_uncertain_event()` is deliberately narrow and fail-closed. Cancellation is allowed only when all of these facts agree:

```text
same unfinished event (PROCESSING, or PENDING after restart recovery)
same event owns WorkingState
stage == side_effect_recovery
blocked_by == outside_world_effect_uncertain
replay_blocked == true
checkpoint attempt_id exists
same event owns that side-effect attempt
attempt status == started
no durable EventOutcome already exists
```

One SQLite transaction then performs all four durable lifecycle changes:

```text
side-effect attempt -> work_abandoned
event -> terminal
EventOutcome -> cancelled=true, execution_path=control
WorkingState -> idle
```

`work_abandoned` is explicitly **non-epistemic**. It means only that ZN will no longer continue this Work. It does not assert that the uncertain external effect occurred, and it does not assert that the effect was absent.

The attempt therefore stores no `result_action_id` or `result_success` when abandoned.

`SideEffectAwareBody.resolve_uncertain_attempt()` no longer accepts a standalone `cancelled` resolution. Its recovery statuses remain only evidence-bearing `verified_effect` and `verified_absent`; lifecycle cancellation must pass through the Store transaction above.

Normal completion APIs reject `cancelled` outcomes so cancellation cannot bypass the dedicated atomic invariant.

## 3. Cancellation durability proof

The focused suite now covers:

```text
normal atomic cancellation
restart PROCESSING -> PENDING then cancellation
whole-transaction rollback when EventOutcome insertion fails
wrong/non-recovery WorkingState rejection without mutation
standalone side-effect `cancelled` resolution rejection
```

Exact focused Windows proof:

```text
ZN Work Recovery E2E run 33014912312
head   6c655c761099cc6a206028285cc228d65f3e7734
runner zn-ci-01 / Windows X64
result success
```

The same four new cancellation durability tests also passed inside ordinary Kernel CI.

## 4. Exact ordinary Windows CI truth

Exact implementation-head ordinary CI:

```text
ZN CI run 33014912300
head 6c655c761099cc6a206028285cc228d65f3e7734
Electron / TypeScript / Windows    success
ZN Source Boundary / Windows       success
ZN Kernel / Python / Windows       failure
Kernel suite                        573 tests, 16 errors, 5 skipped
```

The 573-test count increased by the four new cancellation tests; all four passed. No new cancellation or Work-recovery regression appeared.

The 16 Kernel errors remain the known Windows NetworkService DOS-8.3 versus long-path identity family. The run again exposes temporary/repository paths through aliases such as:

```text
C:\WINDOWS\SERVIC~1\NETWOR~1\AppData\Local\Temp\...
```

while Python/repository expectations use long identities such as:

```text
C:\Windows\ServiceProfiles\NetworkService\AppData\Local\Temp\...
```

Failures remain concentrated around repository targeted-test/text-delta verification plus the terminal/Work artifact cwd identity assertion. Cleanup `PermissionError` exceptions on resident `kernel.db` files are secondary fallout after those assertions fail.

This path-identity issue remains **KNOWN / DEFERRED BY CURRENT PRODUCT PRIORITY**. The earlier partial attempted fix was reverted normally in `db647cb49c3de014aa82bc28ec87c1c4e5b02c15`; no half-fix remains. Do not call ordinary CI green, and do not reopen this path work unless it materially blocks the current Work objective or is explicitly reprioritized.

## 5. Remaining reachable cancellation gap

The backend primitive is intentionally not yet reachable from UI or RPC. This prevents a partially wired control path from learning cancellation as ordinary failure.

The real next call chain is:

```text
Resident explicit cancellation authority
-> bypass Life ordinary failure observation
-> Will explicit/restart cancellation reconciliation
-> ResidentWorkLedger cancellation/finalization
-> ResidentRpcServer work_cancel
-> Electron IPC
-> preload bridge
-> resident-client typed recovery projection + cancel request
-> Workbench recovery-only Cancel Work control
```

Two invariants must be preserved before the button is exposed:

1. `life.observe_action()` must not receive cancellation as a failed action.
2. `NativeWill.reconcile_outcomes()` must not map `cancelled=true` to an ordinary failed intention step after restart.

The first UI control must stay narrow: it may cancel only the active `side_effect_recovery` state that the Store primitive can prove. It must not pretend to stop an arbitrary action already executing outside ZN.

Workbench language must preserve uncertainty: cancelling stops ZN from continuing the Work; it does not claim whether the external effect happened.

## 6. Other current truth

Headless CI remains on `[self-hosted, Windows, X64, zn-ci]`. Interactive proof remains on `[self-hosted, Windows, X64, zn-interactive]`.

Previously verified real regressions remain:

```text
ZN Windows Interactive Desktop E2E run 33006103742   success, 4/4
ZN Managed Browser E2E             run 33006103702   success, 71 contract + 4 real Chromium
```

Managed-browser native `SELECT_OPTION` remains verified. Browser PRESS, broader click/editing/multi-select/page lifecycle, authenticated User Browser Bridge control, M8 continuity, and SM1+ remain open.

M8 Windows continuity remains PARTIAL. SM0 remains verified foundation; SM1+ remains open. High-risk identity, long-term memory, credential/permission, updater/signing, and destructive self-maintenance changes continue to require human approval.
