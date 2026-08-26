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

Latest Work implementation head before this status-document update:

```text
f02582557a39f32273fb806929a6f64906fea547
feat: atomically finalize resident work
```

Status: **DURABLE WORK RESTART/RESUME AND ATOMIC TERMINALIZATION ARE NOW VERIFIED FOUNDATIONS. EVENT TERMINAL STATUS, DURABLE `EventOutcome`, AND THE IDLE `WorkingState` ARE PUBLISHED IN ONE SQLITE TRANSACTION. WORK DURABILITY IS STILL PARTIAL BECAUSE EXPLICIT CANCELLATION/RECOVERY AROUND SIDE EFFECTS REMAINS OPEN.**

## 1. Durable Work checkpoint and restart recovery

The real Work call chain is:

```text
ResidentRpcServer work_start / work_progress
-> ResidentWorkLedger
-> ZNResidentRuntime event lifecycle
-> KernelStore events + singleton working_state
-> resident life stages
-> EventOutcome
-> ResidentWorkLedger finalization
```

ZN's existing SQLite `WorkingState` remains the resident-owned checkpoint. No duplicate checkpoint subsystem was added. It persists the active event, stage, next action, blockers and stage data. On resident reconstruction, interrupted `PROCESSING` work returns to `PENDING` while the exact `WorkingState` is retained; the same event resumes from that checkpoint.

Verified restart checkpoint:

```text
2bce63a23252b7166244d0afd9dcac63b6b4fc26
ci: verify durable work restart recovery
ZN Work Recovery E2E run 33002232752   success
runner                                   zn-ci-03 / Windows X64
6/6 Work progress + restart tests        passed
```

This proves an active Work item can cross resident/store reconstruction without replacement work stealing its thread or duplicating the user message.

## 2. Atomic terminal completion

Before `f0258255`, resident completion wrote three durable records separately:

```text
event -> COMPLETED/FAILED
then EventOutcome
then working_state -> idle
```

A crash between those writes could leave a terminal event without its durable outcome. `KernelStore.complete_event()` now owns one fail-closed terminal transition. Under one SQLite transaction it:

- requires the event to be the active `PROCESSING` event;
- requires the singleton checkpoint to belong to that same event;
- refuses a pre-existing outcome;
- commits `COMPLETED`/`FAILED` event state;
- inserts the exact `EventOutcome`;
- replaces the active checkpoint with `WorkingState(stage="idle")`;
- rolls all three writes back together on any SQLite failure.

`ZNResidentRuntime._complete_result()` is the active product caller and now uses this atomic API. The older low-level `finish_event()` and `save_event_outcome()` remain available for explicit low-level callers such as isolated channel tests; their semantics were not silently changed.

Exact implementation verification:

```text
ZN Work Recovery E2E run 33004561095   success
head                                     f02582557a39f32273fb806929a6f64906fea547
runner                                   zn-ci-02 / Windows X64
Work progress + recovery tests           8 passed
```

New real Windows cases passed:

```text
test_terminal_completion_is_durable_with_outcome_and_idle_checkpoint ... ok
test_atomic_terminal_transition_rolls_back_all_three_records_on_outcome_failure ... ok
```

The second test installs a deliberate SQLite trigger that aborts `event_outcomes` insertion. The transaction raises and the persisted event remains `PROCESSING`, no outcome exists, and the original active `WorkingState` survives unchanged. This is direct rollback evidence rather than a mock assertion.

Life observation still occurs after the atomic durable terminal transition. It is resident self-observation, not part of the event/outcome/checkpoint commit contract.

## 3. Verified managed-browser checkpoint

Managed-browser `SELECT_OPTION` remains verified at:

```text
8c94f1ac9a3fdda2e704f45bdaf02efdc4d40271
ci: run managed select option E2E
ZN Managed Browser E2E run 33001748123   success
71 browser contract tests + 4 real Chromium E2E tests passed
```

Verified browser scope remains narrow and evidence-driven: exact DOM-id main-frame sensing, `FOCUS`, explicit boolean `aria-pressed` toggle `CLICK`, empty writable non-password `TYPE_TEXT`, native `CHECK`, native `UNCHECK`, and native single-select `SELECT_OPTION`. Provider return alone is not completion truth.

Open browser work includes `PRESS`, generic click semantics, richer editing, password/sensitive entry, contenteditable, ARIA checkbox mutation, multi-select, broader frame/tab/popup lifecycle, headed UX, file authority, persistent profile policy, cloud adapter and authenticated User Browser Bridge control.

## 4. Windows runner and ordinary CI truth

Headless CI remains on `[self-hosted, Windows, X64, zn-ci]`. Interactive proof remains on `[self-hosted, Windows, X64, zn-interactive]`.

Interactive recovery remains verified:

```text
ZN Windows Runner Bootstrap             run 32999198210   success
ZN Interactive Runner Visible Watchdog  run 32999383631   success
runner                                   zn-interactive / SessionId 1
root                                     C:\actions-runner-znagent
startup                                  visible cmd.exe -> run.cmd
```

For atomic Work implementation head `f0258255`, ordinary `ZN CI` run `33004560957` had at the latest inspection:

```text
ZN Source Boundary / Windows       success
Electron / TypeScript / Windows    success
ZN Kernel / Python / Windows       in progress - full core suite running
```

A separate real NetworkService long-path vs DOS-8.3 path-identity defect remains deferred by current product priority. The partial attempted fix was reverted normally in `db647cb49c3de014aa82bc28ec87c1c4e5b02c15`; no half-fix remains. Do not report ordinary Kernel CI green unless an exact run actually succeeds, and do not automatically reopen that deferred issue.

## 5. Remaining Work durability work

The next real Work problem is explicit cancellation/recovery semantics, especially around non-idempotent body actions. Restart recovery must not blindly replay an action merely because its event was interrupted if the outside-world side effect may already have happened.

The next slice should trace current action/evidence ownership and define a fail-closed distinction between at least:

```text
safe to resume/retry
needs fresh effect verification before retry
requires explicit cancellation or user decision
terminal / already observed complete
```

Do not make an LLM, UI thread, provider, or task planner the owner of continuation or cancellation truth.

Broader open foundations remain isolated parallel Work/Investigation, ZN-owned connector/MCP permission/evidence substrate, scheduled/event-driven work, unified permission/audit controls, M8 install/update/rollback/signing continuity, authenticated User Browser Bridge control, and SM1+ self-maintenance.

M8 Windows continuity remains PARTIAL. SM0 remains verified foundation; SM1+ remains open. High-risk identity, long-term memory, credential/permission, updater/signing and destructive self-maintenance changes continue to require human approval.

## 6. Next implementation order

```text
1. preserve verified restart recovery + atomic terminal completion
2. trace body/action side-effect evidence through Work restart and recovery
3. add explicit Work cancellation/recovery semantics without replaying uncertain side effects
4. prove those semantics with focused Windows reconstruction tests
5. keep browser PRESS and broader lifecycle as bounded follow-on work
```
