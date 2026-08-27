# ZN Agent Handoff

Updated: 2026-08-27

## Current goal

Trace the **next** still-unproven broader Work durability crash window. The first enqueue-to-`work_runs` ingress linkage crash window is now closed and CI verified. Nervous receipt/trace retention and the Windows NetworkService DOS-8.3 versus long-path identity family remain closed at their current active owner chains with ordinary CI green.

`EventOutcome` remains terminal truth. Nervous plasticity remains secondary. A nervous failure after terminal completion does not reclassify the event and does not replay the action. `NativeWill` keeps its existing durable outcome reconciliation authority.

Generic nervous `perceive()` remains intentionally plastic and non-idempotent. Do not generalize the event-ID guarantee into a global exactly-once claim.

Automatic nervous pruning fails closed for receipted outcome traces. A future deliberate outcome-trace rewrite must atomically retarget receipts before deleting the old representation; no such rewrite or destructive migration was added. Do not perform a destructive long-term-memory migration without explicit human approval.

Founding boundary remains:

> **ZN uses models. Models do not own ZN.**

## Branch / repository truth

- repository: `9529360-cpu/znagent`
- development branch: `dev/zn-agent`
- canonical source/release branch: `main`
- canonical `main`: `8234a835dea604783cea0bd9d28a40de654ec03d`
- nervous code/test checkpoint: `ba06e08561cc73bcd8afc61b444b860c45bfb376`
- completion journal owner cleanup: `c54bb8c37385d98fc9688b6e89839d7a5cba6df6`
- Windows path owner checkpoint: `0c011a2473c581e6517a882343208d6efe47cac1`
- Windows evidence/learning checkpoint: `e3fc20b7b4271e46868f408c258cab58ba014abb`
- nervous receipt lifecycle checkpoint: `9207d3de534080ea62a9847a848cde3b0ba5b6b5`
- Work ingress linkage checkpoint: `8ebae2c43ba13349aa4aebdf8c84746783096c1b`
- current code/test HEAD when this handoff was prepared: `8ebae2c43ba13349aa4aebdf8c84746783096c1b`
- PR #6: draft/open/unmerged, base `main`, head `dev/zn-agent`
- `main` was not modified
- no force push or history rewrite was requested or performed by the maintainer

A HANDOFF commit cannot contain its own resulting SHA. Re-read `dev/zn-agent` after this file is committed and use that exact head externally.

## Completed in this stage

### 1. Event-identity-safe outcome plasticity remains verified

Durable completion remains:

```text
resident completion
-> KernelStore.complete_event(...)
-> terminal event + durable EventOutcome
-> Life completion observation journal
-> Intentional secondary nervous outcome perception
-> NativeWill outcome observation when applicable
```

For one durable event identity, one SQLite transaction covers event receipt/dedupe, trace insert or reinforcement, recent co-active neural-link reinforcement, and affect/nervous-state update. Same event ID is a plasticity no-op after receipt commit; distinct events can still reinforce the same semantic trace. Generic nervous `perceive()` is intentionally different and remains plastic/non-idempotent.

### 2. Completion journal ownership cleanup remains complete

`FocusedModernTextResidentRuntime` does not reconstruct or re-repair `CompletionObservationJournal`. The Embodied birth root owns it once; final product status still projects sanitized completion-observation health.

### 3. Windows path identity remains closed across the active chain

`canonical_host_path()` expands DOS 8.3 components in the longest existing Windows prefix and reattaches missing suffix components without resolving symlinks or reparse points. Canonical identity is carried through Investigation evidence, action path/workdir matching, Body/Terminal, Git root senses, Work workspace state, verification, procedural applicability, experience fingerprints and active resident callers. Strict real-path containment remains separate and fail-closed for symlink/reparse escapes.

### 4. Nervous receipt/trace pruning lifecycle remains closed

Resident heartbeat can invoke nervous consolidation and weak trace pruning. A database retention invariant now prevents automatic deletion of any trace referenced by `neural_event_outcomes`. `_delete_trace()` reports the actual SQLite delete result and does not remove links when deletion is refused. Weak unreferenced traces still prune normally.

The contract is: receipts own event-ID idempotence and their current trace target must remain dereferenceable. A future deliberate compactor may change representation only by atomically retargeting every affected receipt before deleting the old trace. No compactor or destructive migration exists in this stage.

### 5. First broader Work ingress linkage crash window closed

The real ingress chain is:

```text
work_start RPC
-> ResidentWorkControl.start()
-> ResidentWorkLedger.start()
-> durable user Work message
-> resident.enqueue() commits resident event
-> work_runs linkage commits separately
```

A hard exit between the event commit and `work_runs` commit left a durable resident event with valid Work thread/message identity but no Work ledger run. The event could recover independently while Work progress could not see it and the thread could appear free for another start.

`ResidentWorkControl.reconcile_missing_ingress_runs()` now repairs only this linkage on construction. It requires mutually agreeing durable evidence: embedded event identity, Work thread, exact Work message identity, `user` role and exact message/task text. Invalid or ambiguous records are ignored rather than guessed.

The repair does not claim, execute, requeue, terminalize, or replay the event. Resident event/outcome/checkpoint state remains execution truth. The regression constructs the exact crash state, restarts the product path, proves the Work run is restored, proves the event remains `PENDING` with `attempts == 0`, proves the working checkpoint remains idle, and proves the repaired active run blocks duplicate same-thread Work.

## Real test / CI truth

### Focused Work proof

```text
ZN Work Recovery E2E run 33051627642
head 8ebae2c43ba13349aa4aebdf8c84746783096c1b
Windows resident Work restart recovery             success
Prepare isolated runtime                            success
Compile Work recovery path                          success
Verify durable Work progress and restart recovery  success
Ran 47 tests                                        OK
```

The focused suite includes the new `tests.zn_agent.core.test_work_ingress_recovery` regression together with existing Work progress/restart/side-effect/cancellation, completion-observation and nervous-outcome regressions.

### Ordinary CI

```text
ZN CI run 33051627644
head 8ebae2c43ba13349aa4aebdf8c84746783096c1b
Electron / TypeScript / Windows    success
ZN Source Boundary / Windows       success
ZN Kernel / Python / Windows       success
Kernel                             597 tests / 5 skipped / OK
Publish Windows CI statuses        success
```

Previous green checkpoints remain evidence, including nervous receipt retention at `9207d3de...` and Windows path identity at `e3fc20b7...`.

No local test run was claimed for this web-maintainer slice; the exact code checkpoint was verified by repository self-hosted Windows CI.

## Current risks / incomplete work

- Broader Work durability remains partial beyond the proven ingress linkage, cancellation, Life-observation, nervous-outcome and non-replayable side-effect slices.
- Several explanatory comments in `intentional_resident.py` were accidentally lost during an earlier whole-file owner replacement; diff review found no corresponding behavioral deletion. Restoring them remains cleanup.
- No deliberate outcome-trace rewrite/compactor exists. Any future implementation must atomically retarget receipts and receive separate review before a destructive long-term-memory migration.
- Generic nervous `perceive()` remains intentionally plastic and is not safe for blind replay. Only the durable terminal EventOutcome path has event-ID dedupe semantics.
- Browser PRESS/broader click/editing/multi-select/lifecycle, authenticated User Browser Bridge control, M8 continuity, and SM1+ remain incomplete.
- High-risk identity, long-term memory, credentials/permissions, updater/signing, rollback, and destructive self-maintenance changes still require human approval.
- `main` remains untouched.

## Blockers

No blocker prevents the next read-only Work durability trace. Any destructive identity or long-term-memory migration discovered to be necessary must stop for explicit human approval.

## Task queue

### P0 - event-identity-safe nervous outcome perception

Status: **IMPLEMENTED / FOCUSED CI VERIFIED**

Do not broaden the guarantee beyond durable terminal EventOutcome perception.

### P0.1 - completion journal ownership cleanup

Status: **COMPLETE / FOCUSED CI VERIFIED**

Single richer birth-root owner; final status projection retained; regression runs in focused CI.

### P0.2 - nervous receipt lifecycle robustness

Status: **COMPLETE / ORDINARY AND FOCUSED CI VERIFIED**

Automatic pruning preserves referential integrity and accurate pruning/link state. Future deliberate rewriting remains a separate, unimplemented operation that must atomically retarget receipts before deletion.

### P1 - broader Work durability

Status: **OPEN / FIRST INGRESS WINDOW VERIFIED**

The enqueue-to-`work_runs` linkage crash window is closed without event replay. Continue tracing the next real ambiguity after persisted ingress linkage.

### P1.1 - Windows path identity

Status: **COMPLETE / ORDINARY CI VERIFIED**

Full entry/evidence/action/state/dependency/verification caller chain uses one lexical Windows identity; strict containment safety remains separate and fail-closed.

### P2 - browser follow-ons

Status: **OPEN**

PRESS, broader click semantics, richer text editing, multi-select, broader page/target lifecycle, authenticated User Browser Bridge control.

### P3 - M8 / SM1+

Status: **OPEN**

Preserve human approval for high-risk identity, memory, credentials, updater/signing, rollback, and destructive self-maintenance changes.

## Related files

```text
runtime/python/zn_agent/core/work.py
runtime/python/zn_agent/core/work_control.py
runtime/python/zn_agent/core/store.py
runtime/python/zn_agent/core/resident.py
runtime/python/zn_agent/core/daemon.py
runtime/python/zn_agent/core/event_outcome_nervous.py
runtime/python/zn_agent/core/intentional_resident.py
runtime/python/zn_agent/core/nervous_system.py
runtime/python/zn_agent/core/completion_observation.py
runtime/python/zn_agent/core/path_context.py
tests/zn_agent/core/test_work_ingress_recovery.py
tests/zn_agent/core/test_work_progress.py
tests/zn_agent/core/test_work_recovery.py
tests/zn_agent/core/test_work_side_effect_recovery.py
tests/zn_agent/core/test_work_cancellation.py
tests/zn_agent/core/test_work_cancel_control.py
tests/zn_agent/core/test_event_outcome_nervous.py
tests/zn_agent/core/test_event_outcome_nervous_recovery.py
.github/workflows/zn-work-recovery-e2e.yml
docs/ZN-IMPLEMENTATION-STATUS.md
.agent/HANDOFF.md
```

## Next real target

Trace the next unproven Work durability boundary beginning after persisted ingress linkage:

```text
event claim
-> durable stage/checkpoint ownership
-> outside-world side-effect admission
-> terminal outcome
-> restart reconstruction / progress
```

Select only a real ambiguity not already covered by ingress repair, cancellation, Life observation, nervous outcome perception, or the existing non-replayable action guard. Do not replay uncertain effects. Keep `main` untouched.
