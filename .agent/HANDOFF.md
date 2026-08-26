# ZN Agent Handoff

Updated: 2026-08-26

## Current goal

Continue durable resident-owned Work from the now-verified restart/resume and atomic-terminal foundations. The next real target is explicit cancellation/recovery semantics around actions whose outside-world side effects may already have happened before a crash.

Do not spend the current stage on the deferred Windows NetworkService DOS-8.3 path-identity defect unless it materially blocks current Work development.

Founding boundary remains:

> **ZN uses models. Models do not own ZN.**

## Branch / repository truth

- repository: `9529360-cpu/znagent`
- fixed development branch: `dev/zn-agent`
- canonical source/release branch: `main`
- atomic Work implementation head before documentation: `f02582557a39f32273fb806929a6f64906fea547`
- prior Work restart checkpoint: `2bce63a23252b7166244d0afd9dcac63b6b4fc26`
- managed-browser checkpoint: `8c94f1ac9a3fdda2e704f45bdaf02efdc4d40271`
- canonical `main`: `8234a835dea604783cea0bd9d28a40de654ec03d`
- PR #6: draft/open/unmerged, base `main`, head `dev/zn-agent`
- `main` was not modified
- no force push or history rewrite was used

A HANDOFF commit cannot contain its own resulting SHA. Re-read `dev/zn-agent` after this file is committed and report the resulting exact head externally.

## Completed in current stage

### 1. Real Work completion call chain was traced

Active completion ownership is:

```text
ResidentRpcServer / Work caller
-> ResidentWorkLedger
-> ZNResidentRuntime life step
-> ZNResidentRuntime._complete_result
-> KernelStore
-> durable EventOutcome / terminal event / idle checkpoint
-> ResidentWorkLedger finalization
```

`finish_event()` and `save_event_outcome()` also have explicit low-level callers, so their existing semantics were not silently changed. The product completion path instead gained one new store-owned atomic API.

### 2. Atomic terminalization implemented

Implementation commit:

```text
f02582557a39f32273fb806929a6f64906fea547
feat: atomically finalize resident work
```

Changed files:

```text
runtime/python/zn_agent/core/store.py
runtime/python/zn_agent/core/resident.py
tests/zn_agent/core/test_work_recovery.py
```

`KernelStore.complete_event()` now validates that:

- the event exists and is still `PROCESSING`;
- the active singleton `WorkingState` belongs to that exact event;
- no durable outcome already exists.

It then performs one SQLite transaction containing:

```text
event -> COMPLETED/FAILED
+ EventOutcome INSERT
+ WorkingState(stage=idle)
```

Any SQL failure rolls back all three. `ZNResidentRuntime._complete_result()` is the normal product caller and no longer executes the old split `finish_event -> save_event_outcome -> save_working_state(idle)` sequence.

Life self-observation remains after the durable atomic transition and is not treated as the source of event completion truth.

### 3. Atomic rollback is proven on real Windows

Exact focused evidence:

```text
ZN Work Recovery E2E run 33004561095
head f02582557a39f32273fb806929a6f64906fea547
runner zn-ci-02 / Windows X64
conclusion success
Ran 8 tests in 4.269s
OK
```

New tests that actually ran and passed:

```text
test_terminal_completion_is_durable_with_outcome_and_idle_checkpoint ... ok
test_atomic_terminal_transition_rolls_back_all_three_records_on_outcome_failure ... ok
```

The rollback test deliberately creates an SQLite trigger that aborts insertion into `event_outcomes`. After the exception, persisted truth remains:

```text
event.status == PROCESSING
EventOutcome == absent
WorkingState == original active event/stage/next_action/data
```

So this is direct database rollback evidence, not a mock-only assertion.

### 4. Earlier restart/reconstruction checkpoint remains verified

```text
ZN Work Recovery E2E run 33002232752   success
head 2bce63a23252b7166244d0afd9dcac63b6b4fc26
runner zn-ci-03 / Windows X64
6/6 tests passed
```

Existing `WorkingState` remains the real checkpoint. Interrupted `PROCESSING` events return to `PENDING` while exact stage/next_action survives and the same event resumes. No second checkpoint architecture was added.

### 5. Managed-browser SELECT_OPTION remains verified

```text
ZN Managed Browser E2E run 33001748123   success
head 8c94f1ac9a3fdda2e704f45bdaf02efdc4d40271
71 managed-browser contract tests passed
4 real Chromium E2E tests passed
```

## Real test / CI truth

### Atomic Work focused CI

```text
run 33004561095   success
head f02582557a39f32273fb806929a6f64906fea547
runner zn-ci-02 / Windows X64
8/8 Work progress/recovery/atomic-terminal tests passed
```

### Ordinary ZN CI on atomic implementation head

At latest inspection:

```text
run 33004560957
head f02582557a39f32273fb806929a6f64906fea547
ZN Source Boundary / Windows       success
Electron / TypeScript / Windows    success
ZN Kernel / Python / Windows       in progress; full core suite running
```

Do not call ordinary CI green unless Kernel actually completes successfully. If it fails only on the known NetworkService long-path vs DOS-8.3 identity defect, record that fact and keep it deferred per current priority.

### Windows runner topology

```text
headless CI:       [self-hosted, Windows, X64, zn-ci]
interactive proof: [self-hosted, Windows, X64, zn-interactive]
```

Interactive runner remains previously verified as visible `cmd.exe -> run.cmd` in SessionId 1 at `C:\actions-runner-znagent`. Do not reintroduce hidden launch, auto-logon, or Session-0 UI proof.

## Current risks / blockers

- Work process reconstruction is verified.
- Atomic event/outcome/idle terminalization is verified.
- Work durability is still PARTIAL: interruption around non-idempotent outside-world side effects does not yet have an explicit resident-owned resume/cancel/reverify policy.
- A restarted event must not blindly replay an action if the action may already have taken effect.
- Life self-observation is outside the atomic terminal transaction; its recovery semantics are a separate resident-self consistency concern, not event completion truth.
- Ordinary Kernel CI may remain red on the deferred DOS-8.3 path issue.
- Browser PRESS/generic click/richer editing/multi-select/lifecycle remain open.
- User Browser Bridge control, M8 continuity and SM1+ remain incomplete.
- `main` remains untouched.

## Task queue

### P0 - Work cancellation / side-effect recovery

Status: **NEXT REAL TARGET**

Trace the real action path before modification:

```text
WorkingState stage / next_action
-> Body or capability action dispatch
-> persisted action/effect evidence
-> event progress
-> restart recovery
-> retry / reverify / cancel decision
```

Define resident-owned, fail-closed semantics that distinguish at least:

```text
safe to resume/retry
side effect uncertain -> verify before retry
requires explicit cancellation/user decision
already observed complete / terminal
```

Do not blindly repeat non-idempotent actions after restart. Do not make a model or provider the owner of retry/cancellation truth.

### P1 - life observation recovery

Status: **OPEN / SEPARATE FROM EVENT TERMINAL TRUTH**

Investigate only after the Work side-effect recovery path is clear. A durable completed event must remain completed even if later living-self observation needs repair.

### P2 - browser follow-ons

Status: **OPEN / NOT CURRENT MAJOR TARGET**

PRESS, generic click semantics, richer text editing, multi-select and broader target/page lifecycle remain bounded candidates.

### P3 - deferred Windows DOS-8.3 path identity

Status: **KNOWN / DEFERRED BY USER DECISION**

Partial fix was reverted by `db647cb49c3de014aa82bc28ec87c1c4e5b02c15`. Resume only if explicitly reprioritized or materially blocking current work.

### P4 - M8 / SM1+

Status: **OPEN**

Preserve existing human-approval boundaries for high-risk identity, memory, credentials, updater/signing and destructive self-maintenance changes.

## Related files

```text
runtime/python/zn_agent/core/store.py
runtime/python/zn_agent/core/resident.py
runtime/python/zn_agent/core/work.py
runtime/python/zn_agent/core/body.py
runtime/python/zn_agent/core/life.py
runtime/python/zn_agent/core/daemon.py
tests/zn_agent/core/test_work_progress.py
tests/zn_agent/core/test_work_recovery.py
.github/workflows/zn-work-recovery-e2e.yml
```

## Next real target

Trace and implement explicit Work cancellation/recovery around side-effect uncertainty, then prove restart behavior on the focused Windows Work workflow. Keep `main` untouched.
