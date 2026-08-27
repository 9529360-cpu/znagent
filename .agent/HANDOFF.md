# ZN Agent Handoff

Updated: 2026-08-27

## Current goal

Trace the **next** still-unproven broader Work durability crash window. Two concrete windows are now closed and CI verified: the enqueue-to-`work_runs` ingress linkage window, and the side-effect recovery decision commit -> next `WorkingState` checkpoint window. Nervous receipt/trace retention and the Windows NetworkService DOS-8.3 versus long-path identity family remain closed at their current active owner chains with ordinary CI green.

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
- side-effect recovery resolution checkpoint: `b41b65dd35ab652e6ed573e5d512778d7313db47`
- current code/test HEAD when this handoff was prepared: `b41b65dd35ab652e6ed573e5d512778d7313db47`
- implementation-status sync immediately before this handoff: `297daef73067c110c6c6befee016331f00ab446f`
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

Resident heartbeat can invoke nervous consolidation and weak trace pruning. A database retention invariant prevents automatic deletion of any trace referenced by `neural_event_outcomes`. `_delete_trace()` reports the actual SQLite delete result and does not remove links when deletion is refused. Weak unreferenced traces still prune normally.

The contract is: receipts own event-ID idempotence and their current trace target must remain dereferenceable. A future deliberate compactor may change representation only by atomically retargeting every affected receipt before deleting the old trace. No compactor or destructive migration exists in this stage.

### 5. First broader Work ingress linkage crash window remains closed

The real ingress chain is:

```text
work_start RPC
-> ResidentWorkControl.start()
-> ResidentWorkLedger.start()
-> durable user Work message
-> resident.enqueue() commits resident event
-> work_runs linkage commits separately
```

A hard exit between the event commit and `work_runs` commit left a durable resident event with valid Work thread/message identity but no Work ledger run. `ResidentWorkControl.reconcile_missing_ingress_runs()` repairs only this linkage from mutually agreeing durable evidence and does not claim, execute, requeue, terminalize, or replay the event.

### 6. Side-effect recovery decision/checkpoint crash window closed

The active append recovery path contains two separate durable writes:

```text
side_effect_recovery checkpoint
-> fresh independent reality read
-> resolve_uncertain_attempt(... verified_effect | verified_absent)
   commits resident_side_effect_attempts
-> update WorkingState
-> save_working_state()
```

Before `b41b65dd...`, a hard exit after the attempt had durably become `verified_effect` or `verified_absent`, but before the next `WorkingState` save, left the old `side_effect_recovery` checkpoint behind. On restart, fresh reality could prove the exact same recovery result again, but `resolve_uncertain_attempt()` returned false because it only accepted rows still in `started`, incorrectly converting an already-committed recovery decision into a mismatch/hold.

`SideEffectAwareBody.resolve_uncertain_attempt()` now accepts only an exact idempotent acknowledgement of an already-committed recovery decision: same event, same attempt, same final recovery status. A wrong event or conflicting final status still fails closed. The method does not grant mutation authority and does not replay the outside-world action.

`tests/zn_agent/core/test_work_side_effect_resolution_recovery.py` constructs the exact crash state. It commits `verified_effect`, intentionally leaves the stale `side_effect_recovery` checkpoint, reconstructs the product resident, reclaims the event, re-verifies current reality, and completes without any `write_text` dispatch. The test also proves a conflicting `verified_absent` acknowledgement is rejected.

## Real test / CI truth

### Focused Work proof

```text
ZN Work Recovery E2E run 33053986871
head b41b65dd35ab652e6ed573e5d512778d7313db47
Windows resident Work restart recovery             success
Prepare isolated runtime                            success
Compile Work recovery path                          success
Verify durable Work progress and restart recovery  success
Ran 48 tests                                        OK
```

The 48-test focused suite includes the new side-effect resolution restart regression together with existing Work progress/restart/ingress/side-effect/cancellation, completion-observation and nervous-outcome regressions.

### Ordinary CI

```text
ZN CI run 33053986879
head b41b65dd35ab652e6ed573e5d512778d7313db47
Electron / TypeScript / Windows    success
ZN Source Boundary / Windows       success
ZN Kernel / Python / Windows       success
Kernel                             598 tests / 5 skipped / OK
Publish Windows CI statuses        success
```

The new `test_restart_after_verified_effect_before_checkpoint_save_completes_without_replay` passed in the full Kernel suite as well as focused CI.

No local test run is claimed for this web-maintainer slice; the exact code checkpoint was verified by repository self-hosted Windows CI.

## Current risks / incomplete work

- Broader Work durability remains partial beyond the proven ingress linkage, recovery-resolution idempotence, cancellation, Life-observation, nervous-outcome and non-replayable side-effect slices.
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

Status: **OPEN / TWO CRASH WINDOWS VERIFIED**

Closed without replay:

1. resident event committed before missing `work_runs` linkage;
2. side-effect recovery decision committed before the next `WorkingState` checkpoint.

Continue tracing only the next real ambiguity. Do not mark broader Work durability complete.

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
runtime/python/zn_agent/core/focused_modern_text_resident.py
runtime/python/zn_agent/core/side_effect_body.py
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
tests/zn_agent/core/test_work_side_effect_resolution_recovery.py
tests/zn_agent/core/test_work_cancellation.py
tests/zn_agent/core/test_work_cancel_control.py
tests/zn_agent/core/test_event_outcome_nervous.py
tests/zn_agent/core/test_event_outcome_nervous_recovery.py
.github/workflows/zn-work-recovery-e2e.yml
docs/ZN-IMPLEMENTATION-STATUS.md
.agent/HANDOFF.md
```

## Next real target

Trace the next unproven Work durability boundary after the two now-closed windows:

```text
event claim
-> durable stage/checkpoint ownership
-> outside-world side-effect admission
-> terminal outcome
-> restart reconstruction / progress
```

Select only a real ambiguity not already covered by ingress repair, recovery-resolution idempotence, cancellation, Life observation, nervous outcome perception, or the existing non-replayable action guard. Do not replay uncertain effects. Keep `main` untouched.
