# ZN Agent Handoff

Updated: 2026-08-26

## Current goal

Wire the verified atomic uncertain-Work cancellation primitive through the real resident control path without turning a user cancellation into ordinary action failure or false outside-world evidence.

The backend durability primitive is now implemented and verified. The next real target is the reachable chain:

```text
Resident explicit cancellation authority
-> no Life ordinary failure observation
-> Will explicit/restart cancellation semantics
-> ResidentWorkLedger cancellation/finalization
-> ResidentRpcServer work_cancel
-> Electron IPC
-> preload bridge
-> resident-client typed recovery/cancel API
-> Workbench recovery-only Cancel Work control
```

Do not broaden this into arbitrary in-flight action cancellation. The first user control must only cancel an active `side_effect_recovery` state whose ownership/attempt invariant the Store can prove.

Do not spend the current stage on the deferred Windows NetworkService DOS-8.3 path-identity defect unless it materially blocks current Work development or is explicitly reprioritized.

Founding boundary remains:

> **ZN uses models. Models do not own ZN.**

## Branch / repository truth

- repository: `9529360-cpu/znagent`
- fixed development branch: `dev/zn-agent`
- canonical source/release branch: `main`
- latest implementation checkpoint before this HANDOFF update: `6c655c761099cc6a206028285cc228d65f3e7734`
- status-document synchronization commit before this HANDOFF update: `5d284b437fe5a449c1e78ab75bb84dd83a94607c`
- sanitized Work recovery projection checkpoint: `643e174bfc6dcdbe313df1a5434427319d5f068f`
- append side-effect reverification checkpoint: `1bcbf410a401755d6037423ea677cb3db1c6217a`
- canonical `main`: `8234a835dea604783cea0bd9d28a40de654ec03d`
- PR #6: draft/open/unmerged, base `main`, head `dev/zn-agent`
- `main` was not modified
- no force push or history rewrite was used

A HANDOFF commit cannot contain its own resulting SHA. Re-read `dev/zn-agent` after this file is committed and report/use the resulting exact head externally.

## Completed in current stage

### 1. Atomic uncertain-Work cancellation primitive

Implementation:

```text
6c655c761099cc6a206028285cc228d65f3e7734
feat: add atomic uncertain Work cancellation
```

The durable model now distinguishes cancellation from ordinary execution failure:

```text
ExecutionPath.CONTROL
EventOutcome.cancelled = true
success = false
```

`cancelled` was appended compatibly to the existing result dataclasses, and old persisted outcomes default to `cancelled=false` when read.

`KernelStore.cancel_uncertain_event()` is narrow and fail-closed. It accepts only unfinished work (`PROCESSING`, or `PENDING` after restart recovery) for which all of the following agree:

```text
same event owns WorkingState
stage == side_effect_recovery
blocked_by == outside_world_effect_uncertain
replay_blocked == true
checkpoint attempt_id exists
same event owns that attempt
attempt status == started
no durable EventOutcome already exists
```

One SQLite transaction then performs all durable lifecycle changes:

```text
side-effect attempt -> work_abandoned
event -> terminal
EventOutcome -> cancelled=true, execution_path=control
WorkingState -> idle
```

`work_abandoned` is deliberately non-epistemic. It means only that ZN will no longer continue this Work. It does **not** claim that the uncertain outside-world effect happened, and it does **not** claim that the effect was absent.

The abandoned attempt therefore stores no `result_action_id` or `result_success` evidence.

Normal `save_event_outcome()` / `complete_event()` reject cancelled outcomes, so callers cannot bypass the dedicated atomic cancellation transaction.

### 2. Standalone side-effect cancellation path removed

`SideEffectAwareBody.resolve_uncertain_attempt()` now accepts only evidence-bearing recovery statuses:

```text
verified_effect
verified_absent
```

It no longer accepts `cancelled`. Lifecycle cancellation must pass through the Store transaction above so attempt/event/outcome/checkpoint cannot diverge after a crash.

### 3. Cancellation durability tests added

The focused Work workflow now includes `tests/zn_agent/core/test_work_cancellation.py`.

Covered invariants:

```text
normal atomic cancellation
restart PROCESSING -> PENDING then cancellation
whole-transaction rollback when EventOutcome insertion fails
wrong/non-recovery WorkingState rejection without mutation
standalone side-effect `cancelled` resolution rejection
```

## Real test / CI truth

### Exact focused Work recovery

```text
ZN Work Recovery E2E run 33014912312
head 6c655c761099cc6a206028285cc228d65f3e7734
runner zn-ci-01 / Windows X64
conclusion success
```

Checkout, isolated runtime setup, compile, and the complete focused Work recovery unittest step all passed.

### Exact ordinary ZN CI

```text
ZN CI run 33014912300
head 6c655c761099cc6a206028285cc228d65f3e7734
Electron / TypeScript / Windows    success
ZN Source Boundary / Windows       success
ZN Kernel / Python / Windows       failure
Kernel                             573 tests / 16 errors / 5 skipped
```

All four new cancellation durability test methods explicitly ran and returned `ok` in the Kernel job log:

```text
test_cancel_uncertain_event_after_restart_does_not_resurrect_work
test_cancel_uncertain_event_atomically_terminalizes_without_effect_claim
test_cancel_uncertain_event_rejects_non_recovery_checkpoint_without_mutation
test_cancel_uncertain_event_rolls_back_event_outcome_checkpoint_and_attempt
```

The 16 errors remain the known Windows NetworkService DOS-8.3 versus long-path identity family. Representative failures remain repository targeted-test/text-delta verification and terminal/Work artifact cwd identity. Cleanup `PermissionError` traces on test databases are secondary fallout after those path assertions fail.

Do not call ordinary CI green. No new Work cancellation/recovery regression appeared.

The prior partial path fix was reverted normally in `db647cb49c3de014aa82bc28ec87c1c4e5b02c15`; no half-fix remains.

## Existing durable Work foundations that remain verified

- resident Work survives restart with same-event `WorkingState` recovery;
- normal event terminal state + `EventOutcome` + idle checkpoint commit atomically;
- generic command/append side effects use a pre-dispatch durable `started` attempt and refuse blind replay;
- trustworthy append recovery may prove `verified_effect` or `verified_absent` from fresh read-only reality;
- `work_progress.recovery` is a sanitized allowlisted projection and survives reconstruction/RPC;
- uncertainty is not routed into ordinary failure learning while it remains in recovery.

Prior exact focused projection proof remains:

```text
ZN Work Recovery E2E run 33011631232
head 643e174bfc6dcdbe313df1a5434427319d5f068f
20/20 passed
```

## Current risks / blockers

- The atomic backend cancellation primitive is verified but not yet reachable through Resident/Work/RPC/UI.
- `Resident._complete_result()` normally calls `life.observe_action(result)`; cancellation must bypass this path so it is not learned as an action failure.
- `IntentionalResident._complete_result()` normally sends outcome feedback and calls `Will.observe_event_outcome()`; cancellation must use an explicit neutral/control path.
- `NativeWill.reconcile_outcomes()` currently reconstructs outcomes from `success` only. Before cancellation becomes reachable it must consume `EventOutcome.cancelled` explicitly so restart does not convert cancellation into `step_failed`.
- `ResidentWorkLedger._finalize_run()` currently maps all `success=false` outcomes to failed Work. It must gain explicit cancellation finalization semantics before RPC/UI exposure.
- `ZnWorkProgress` in the desktop resident client does not yet type/normalize the already-sanitized backend `recovery` projection. This must be added before rendering a recovery-only button.
- The first UI control must not claim to cancel arbitrary actions already executing outside ZN.
- Workbench cancellation copy must state that stopping Work does not determine whether the uncertain outside-world effect occurred.
- Life self-observation recovery after ordinary durable completion remains a separate consistency concern.
- Windows NetworkService DOS-8.3 path identity remains known/deferred.
- Browser PRESS/broader click/editing/multi-select/lifecycle, User Browser Bridge control, M8 continuity, and SM1+ remain incomplete.
- `main` remains untouched.

## Task queue

### P0 - reachable explicit cancellation control

Status: **NEXT REAL TARGET**

Implement in dependency order:

```text
1. Resident explicit cancel API that calls the Store primitive and bypasses life.observe_action
2. IntentionalResident / NativeWill explicit cancelled semantics, including restart reconcile
3. ResidentWorkLedger cancellation ownership + cancellation-aware finalization/progress
4. ResidentRpcServer work_cancel
5. Electron IPC + preload + desktop bridge typing
6. resident-client typed recovery projection + cancelZnWork
7. Workbench recovery-only Cancel Work button and truthful uncertainty language
8. focused backend + desktop tests, then real Windows CI
```

Required invariant:

```text
user decides to stop Work
-> Work/event lifecycle becomes terminal through resident-owned authority
-> no ordinary failure learning
-> no Will step_failed learning, including after restart
-> uncertain side-effect attempt becomes work_abandoned
-> no claim that external effect was present or absent
-> restart never resurrects the cancelled Work into replay
```

### P1 - life observation recovery

Status: **OPEN / SEPARATE FROM EVENT TERMINAL TRUTH**

A durable completed event remains completed even if later self-observation needs repair.

### P2 - browser follow-ons

Status: **OPEN / NOT CURRENT MAJOR TARGET**

PRESS, broader click semantics, richer text editing, multi-select, and broader page/target lifecycle remain bounded candidates.

### P3 - deferred Windows DOS-8.3 path identity

Status: **KNOWN / DEFERRED**

Resume only if explicitly reprioritized or materially blocking current product work.

### P4 - M8 / SM1+

Status: **OPEN**

Preserve human approval for high-risk identity, memory, credentials, updater/signing, and destructive self-maintenance changes.

## Related files

```text
runtime/python/zn_agent/core/models.py
runtime/python/zn_agent/core/store.py
runtime/python/zn_agent/core/side_effect_body.py
runtime/python/zn_agent/core/resident.py
runtime/python/zn_agent/core/intentional_resident.py
runtime/python/zn_agent/core/will.py
runtime/python/zn_agent/core/work.py
runtime/python/zn_agent/core/daemon.py
tests/zn_agent/core/test_work_cancellation.py
tests/zn_agent/core/test_native_will.py
.github/workflows/zn-work-recovery-e2e.yml
apps/desktop/electron/zn-resident-ipc.ts
apps/desktop/electron/zn-preload.ts
apps/desktop/src/zn/desktop-env.d.ts
apps/desktop/src/zn/resident-client.ts
apps/desktop/src/zn/workbench.tsx
```

## Next real target

Make the verified Store cancellation primitive reachable through Resident and Will first, with cancellation remaining outside ordinary failure learning and restart reconciliation. Then carry the same bounded authority through Work/RPC/Electron/client to a recovery-only Workbench button. Keep `main` untouched.
