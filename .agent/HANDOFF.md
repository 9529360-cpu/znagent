# ZN Agent Handoff

Updated: 2026-08-26

## Current goal

Continue durable resident-owned Work/checkpoint/recovery from the now-verified restart-resume foundation. The next concrete durability gap is atomic terminalization: event terminal status, durable EventOutcome and idle WorkingState currently commit separately and should become one store transaction.

Do not spend the current stage on the deferred Windows NetworkService 8.3 path-identity defect unless it materially blocks the next Work slice.

Founding boundary remains:

> **ZN uses models. Models do not own ZN.**

## Branch / repository truth

- repository: `9529360-cpu/znagent`
- fixed development branch: `dev/zn-agent`
- canonical source/release branch: `main`
- Work recovery implementation head before documentation: `2bce63a23252b7166244d0afd9dcac63b6b4fc26`
- managed-browser checkpoint: `8c94f1ac9a3fdda2e704f45bdaf02efdc4d40271`
- canonical `main`: `8234a835dea604783cea0bd9d28a40de654ec03d`
- PR #6: draft/open/unmerged, base `main`, head `dev/zn-agent`
- `main` was not modified
- no force push or history rewrite was used

A HANDOFF commit cannot contain its own resulting SHA. Re-read `dev/zn-agent` after committing this file and report the resulting exact head externally.

## Completed in current stage

### 1. Deferred 8.3 path fix remains cleanly reverted

The abandoned partial fix was removed by normal forward commit:

```text
db647cb49c3de014aa82bc28ec87c1c4e5b02c15
revert: defer Windows short-path canonicalization
```

No half-fix remains active. The NetworkService long-path vs DOS 8.3 identity issue is real known debt, not fixed and not flaky.

### 2. Managed-browser SELECT_OPTION remains a verified checkpoint

Implementation/test/CI commits:

```text
3c5e8b30637ab2168c130eb1bffe0c4adc8eecb9  feat: add verified managed select option effect
7dcf67c8aa78449adb1404f3384f3e2d19e19b02  feat: route native select option through verified effect
de0e82a1e9036350fd0abf75e9901625786938a3  test: cover verified managed select option
39a087e5eab499b536f2d845311542e5e9c52804  test: verify managed select option in Chromium
8c94f1ac9a3fdda2e704f45bdaf02efdc4d40271  ci: run managed select option E2E
```

Real exact-head evidence:

```text
ZN Managed Browser E2E run 33001748123   success
runner zn-ci-02 / Windows X64
71 managed-browser contract tests passed
4 real local Chromium E2E tests passed
```

SELECT_OPTION completion requires fresh exact-node selected-value evidence; provider return alone is not success.

### 3. Existing durable WorkingState is the real Work checkpoint

Call chain inspected:

```text
ResidentRpcServer work_start/work_progress
-> ResidentWorkLedger.start/progress
-> ZNResidentRuntime event lifecycle
-> KernelStore events + singleton working_state
-> resident life pulse stages
-> EventOutcome
-> ResidentWorkLedger finalization
```

Key existing semantics confirmed from real code:

- every major resident stage persists `WorkingState`;
- `WorkingState` includes `current_event_id`, `stage`, `next_action`, `blocked_by` and stage data;
- `ZNResidentRuntime.__init__()` calls `store.recover_interrupted_events()`;
- interrupted `PROCESSING` events are reset to `PENDING` with a restart note;
- the existing WorkingState is not cleared by restart recovery;
- `_state_for_event()` reuses that checkpoint for the same event;
- Work keeps its original event/run/message association.

A second checkpoint architecture was therefore not added.

### 4. Real process-reconstruction Work recovery is now tested and verified

New test commit:

```text
5a5b90f0f5b41872055015dabbcc8b10a5471d73
test: prove resident work resumes after reconstruction
```

New repository-owned focused workflow:

```text
2bce63a23252b7166244d0afd9dcac63b6b4fc26
ci: verify durable work restart recovery

.github/workflows/zn-work-recovery-e2e.yml
```

Real Actions evidence:

```text
ZN Work Recovery E2E run 33002232752
head 2bce63a23252b7166244d0afd9dcac63b6b4fc26
runner zn-ci-03 / Windows X64
conclusion success
Ran 6 tests in 3.759s
OK
```

The two new restart tests passed:

```text
test_active_work_resumes_from_persisted_stage_after_resident_reconstruction ... ok
test_reconstruction_does_not_allow_second_work_item_to_replace_active_checkpoint ... ok
```

Verified behavior:

1. Work starts once and advances beyond `orient`;
2. resident/store are closed while the event is still active;
3. a new resident instance opens the same DB;
4. event is recovered to `PENDING` with restart evidence;
5. exact persisted stage and next_action survive;
6. Work.progress reports that checkpoint;
7. the same event continues to a durable outcome;
8. Work finalizes once as `[user, zn, activity]` with no duplicate user message;
9. a replacement task cannot steal the active thread after reconstruction.

This is a verified restart-recovery foundation, not full Work durability completion.

## Real test / CI truth

### Focused Work recovery CI

```text
run 33002232752   success
head 2bce63a23252b7166244d0afd9dcac63b6b4fc26
runner zn-ci-03 / Windows X64
6/6 Work progress + restart recovery tests passed
```

### Ordinary ZN CI on the same implementation head

```text
run 33002232505
ZN Source Boundary / Windows       success
Electron / TypeScript / Windows    success
ZN Kernel / Python / Windows       in progress at last inspection; full core suite running
```

Do not call the ordinary CI green unless Kernel actually completes successfully. If it fails on the already-known NetworkService 8.3 identity defect, record that truth and do not automatically reopen the deferred fix.

### Interactive Windows runner

Still verified from earlier real Actions:

```text
ZN Windows Runner Bootstrap             run 32999198210   success
ZN Interactive Runner Visible Watchdog  run 32999383631   success
runner.name                              zn-interactive
runner.session_id                        1
runner.root                              C:\actions-runner-znagent
startup                                  visible cmd.exe -> run.cmd
```

The three `zn-ci` service workers remain separate. Do not restore hidden launch or move interactive proof to Session 0.

## Current risks / blockers

- Work restart/resume from persisted resident stage is verified.
- Work terminalization is not yet atomic.
- Current `_complete_result()` sequence is effectively:
  1. `finish_event()`;
  2. `save_event_outcome()`;
  3. life observation;
  4. `save_working_state(idle)`.
- A crash between terminal event and outcome persistence can leave a terminal event without a durable outcome; existing `submit()`/Work code explicitly treats that state as an error.
- Explicit cancellation/recovery semantics around already-performed side effects remain open.
- normal Kernel CI may remain red on the deferred Windows 8.3 path defect.
- browser PRESS/generic click/richer editing/multi-select/lifecycle remain open.
- User Browser Bridge control, M8 continuity and SM1+ remain incomplete.
- `main` remains untouched.

## Task queue

### P0 - atomic terminal checkpoint

Status: **NEXT REAL TARGET**

Trace `KernelStore.finish_event`, `save_event_outcome`, `save_working_state` and `ZNResidentRuntime._complete_result` as one lifecycle. Implement one resident/store-owned atomic transition that commits:

```text
event status COMPLETED/FAILED
+ EventOutcome
+ WorkingState(stage=idle)
```

in one SQLite transaction. Preserve outcome reconstruction and life observation behavior. Add tests proving terminal state cannot be observed without its corresponding durable outcome through the normal completion path and that reconstruction sees a consistent terminal checkpoint.

Do not create a second database or a compatibility layer merely to avoid modifying KernelStore.

### P1 - explicit Work cancellation/recovery

Status: **AFTER ATOMIC TERMINALIZATION**

Define cancellation semantics against current stage/action evidence. Avoid replaying non-idempotent body actions after crash/restart without fresh verification.

### P2 - browser follow-ons

Status: **OPEN / NOT CURRENT MAJOR TARGET**

PRESS, generic click semantics, richer text editing, multi-select and broader page/target lifecycle remain bounded candidates.

### P3 - deferred Windows 8.3 path identity

Status: **KNOWN / DEFERRED BY USER DECISION**

Resume only if explicitly reprioritized or it materially blocks current product work.

## Related files

```text
runtime/python/zn_agent/core/work.py
runtime/python/zn_agent/core/store.py
runtime/python/zn_agent/core/resident.py
runtime/python/zn_agent/core/daemon.py
runtime/python/zn_agent/core/provider_bridge.py
tests/zn_agent/core/test_work_progress.py
tests/zn_agent/core/test_work_recovery.py
.github/workflows/zn-work-recovery-e2e.yml
runtime/python/zn_agent/core/managed_browser.py
runtime/python/zn_agent/core/managed_browser_select.py
.github/workflows/zn-managed-browser-e2e.yml
```

## Next real target

Make resident terminal completion atomic in KernelStore/ZNResidentRuntime, prove it on the focused Windows Work recovery workflow, then move to explicit Work cancellation/recovery. Keep `main` untouched.
