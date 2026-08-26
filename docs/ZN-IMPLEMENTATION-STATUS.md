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

Latest Work recovery implementation head before this status-document update:

```text
2bce63a23252b7166244d0afd9dcac63b6b4fc26
ci: verify durable work restart recovery
```

Status: **ZN NOW HAS REAL WINDOWS EVIDENCE THAT ACTIVE WORK SURVIVES RESIDENT PROCESS RECONSTRUCTION FROM ITS EXISTING DURABLE WORKING-STATE CHECKPOINT. MANAGED-BROWSER `SELECT_OPTION` REMAINS VERIFIED. WORK RECOVERY IS STILL PARTIAL BECAUSE TERMINAL EVENT + DURABLE OUTCOME + IDLE CHECKPOINT ARE NOT YET COMMITTED AS ONE ATOMIC STORE TRANSITION.**

## 1. Durable Work / checkpoint / recovery foundation

The real Work call chain was traced before modification:

```text
ResidentRpcServer work_start / work_progress
-> ResidentWorkLedger
-> resident event
-> KernelStore events + working_state
-> ZNResidentRuntime life pulses
-> durable EventOutcome
-> ResidentWorkLedger finalization
```

The important finding is that ZN already had a resident-owned checkpoint mechanism; it did not need a second checkpoint subsystem:

- `WorkingState` is persisted in SQLite after resident stages;
- it records `current_event_id`, `stage`, `next_action`, `blocked_by` and stage data;
- runtime construction calls `recover_interrupted_events()`;
- an interrupted `PROCESSING` event is returned to `PENDING` with a restart note;
- the existing `WorkingState` is deliberately preserved;
- `_state_for_event()` reuses that state when the same event resumes;
- Work keeps the original event/run/message identity instead of creating replacement work after restart.

New regression coverage:

```text
5a5b90f0f5b41872055015dabbcc8b10a5471d73
test: prove resident work resumes after reconstruction

2bce63a23252b7166244d0afd9dcac63b6b4fc26
ci: verify durable work restart recovery
```

The focused Windows workflow is repository-owned:

```text
.github/workflows/zn-work-recovery-e2e.yml
```

Exact-head verification:

```text
ZN Work Recovery E2E run 33002232752   success
head                                     2bce63a23252b7166244d0afd9dcac63b6b4fc26
runner                                   zn-ci-03 / Windows X64
Work progress + restart recovery tests   6 passed
```

The two new restart cases prove:

1. active Work advances beyond `orient`, is interrupted, resident/store are reconstructed from the same DB, the exact persisted `stage` and `next_action` remain, the same event continues to a durable outcome, and Work finalizes once as `[user, zn, activity]` without duplicating the user message;
2. reconstruction does not let a second task replace the active thread checkpoint.

This makes restart recovery a **verified foundation**, not a new parallel architecture.

### Remaining Work durability gap

Resident terminalization is still split across multiple durable writes in `ZNResidentRuntime._complete_result()`:

```text
event -> COMPLETED/FAILED
then EventOutcome
then working_state -> idle
```

A process failure between those writes can theoretically leave a terminal event without its durable outcome; existing Work/submit code already treats that state as an error. The next Work slice should make terminal event status, EventOutcome and the idle checkpoint one atomic SQLite transition, then prove rollback/consistency behavior.

Do not mark durable Work/checkpoint/recovery complete until that terminal transition and subsequent recovery/cancellation semantics are verified.

## 2. Verified managed-browser product slice

The verified browser checkpoint remains:

```text
8c94f1ac9a3fdda2e704f45bdaf02efdc4d40271
ci: run managed select option E2E
```

Verified narrow behavior includes managed Chromium session/network policy, exact DOM-id main-frame target sensing, `FOCUS`, explicit boolean `aria-pressed` toggle `CLICK`, empty writable non-password `TYPE_TEXT`, native `CHECK`, native `UNCHECK`, and native single-select `SELECT_OPTION`, all requiring fresh action-specific evidence rather than provider return alone.

`SELECT_OPTION` remains fail-closed: native single select only; bounded explicit string value; disabled/multi-select/already-selected refusal; fresh target reacquisition; exact DOM-node continuity; unchanged ZN target identity; independently observed selected-value digest/length; raw option values excluded from effect evidence.

Exact browser evidence:

```text
ZN Managed Browser E2E run 33001748123   success
runner                                     zn-ci-02 / Windows X64
managed browser contract tests             71 passed
real local Chromium E2E                    4 passed
new SELECT_OPTION Chromium cases           2 passed
```

Still incomplete browser scope includes `PRESS`, generic click, richer text editing, password/sensitive entry, contenteditable, ARIA checkbox mutation, multi-select, broader frame/tab/popup lifecycle, headed UX, file authority, persistent profile policy, cloud adapter and authenticated User Browser Bridge control.

## 3. Windows runner topology

Normal headless work remains on:

```text
[self-hosted, Windows, X64, zn-ci]
```

Interactive desktop proof remains on:

```text
[self-hosted, Windows, X64, zn-interactive]
```

Interactive recovery remains verified:

```text
ZN Windows Runner Bootstrap            run 32999198210   success
ZN Interactive Runner Visible Watchdog run 32999383631   success
runner                                  zn-interactive
session                                 SessionId 1
root                                    C:\actions-runner-znagent
startup                                 visible cmd.exe -> run.cmd
trigger                                 interactive user logon
hidden                                  false
```

The old hidden-watchdog migration is historical and not a current success criterion. Do not reintroduce hidden launch, Session-0 interactive claims, auto-logon, credential exposure or weakened labels.

## 4. Current ordinary ZN CI truth

For Work recovery head `2bce63a23252b7166244d0afd9dcac63b6b4fc26`, ordinary `ZN CI` run `33002232505` had at the latest inspection:

```text
ZN Source Boundary / Windows       success
Electron / TypeScript / Windows    success
ZN Kernel / Python / Windows       in progress - full core suite running
```

A separate real Windows NetworkService path-identity defect remains deferred by current product priority: long-path and DOS 8.3 representations can make strict repo/terminal path checks disagree. A partial attempted canonicalization was reverted normally in `db647cb49c3de014aa82bc28ec87c1c4e5b02c15`; no half-fix remains active.

Do not report ordinary Kernel CI green unless an exact run actually succeeds. The focused Work recovery success is exact evidence for that product slice; it is not a claim that the unrelated full Kernel suite is green.

## 5. Broader product gaps

High-leverage open foundations remain:

- atomic resident terminal checkpoint / outcome persistence;
- explicit Work cancellation and recovery semantics after side effects;
- isolated parallel Work/Investigation;
- MCP/connectors behind ZN-owned permission/evidence contracts;
- scheduled/event-driven resident work;
- unified permission/audit controls;
- M8 install/update/rollback/signing continuity;
- authenticated User Browser Bridge control;
- SM1+ isolated self-maintenance.

M8 Windows continuity remains PARTIAL. SM0 remains verified foundation; SM1+ remains open. High-risk identity, long-term memory, credential/permission, updater/signing and destructive self-maintenance changes continue to require human approval.

## 6. Next implementation order

```text
1. keep verified Work restart recovery and SELECT_OPTION checkpoints intact
2. make resident terminal event + EventOutcome + idle checkpoint atomic
3. prove the atomic transition and restart consistency with focused Windows tests
4. then add explicit Work cancellation/recovery semantics around resident-owned actions
5. keep browser PRESS and broader lifecycle as bounded follow-on work
```
