# ZN Agent Handoff

Updated: 2026-08-27

## Current goal

Continue broader Work durability from the next real unproven crash window. Four concrete windows are now closed and verified: missing `work_runs` ingress linkage; a committed side-effect recovery decision before the next `WorkingState` checkpoint; append dispatch durably `observed` before checkpoint advancement; and generic command dispatch durably `observed` before checkpoint advancement.

Broader Work durability remains **PARTIAL**. Do not infer completion from these four slices. Re-enter the active call chain read-only and select only a concrete remaining ambiguity that is not already covered.

Founding boundary remains:

> **ZN uses models. Models do not own ZN.**

## Branch / repository truth

- repository: `9529360-cpu/znagent`
- development branch: `dev/zn-agent`
- canonical source/release branch: `main`
- canonical `main`: `8234a835dea604783cea0bd9d28a40de654ec03d`
- code/test checkpoint: `173e0d03fbf52cda68571eb5f22e4aabc3d08805`
- observed append checkpoint: `cf88774ba8c4c9b95adf2aeef5954da4d55ea14b`
- command observed/recovery checkpoint: `173e0d03fbf52cda68571eb5f22e4aabc3d08805`
- branch baseline before this documentation sync: `4f9d0aa3c94da88fc07203f18284cbc6cd26295d`
- PR #6: draft/open/unmerged, base `main`, head `dev/zn-agent`
- `main` was not modified
- no force push or history rewrite was requested or performed

A HANDOFF commit cannot contain its own resulting SHA. Re-read `dev/zn-agent` after this file is committed and use that exact head externally.

## Completed in this stage

### Generic command `observed` / stale checkpoint crash window

The active guarded-command path can durably split here:

```text
native_action checkpoint
-> side-effect attempt `started`
-> command/process dispatch
-> side-effect attempt `observed` + result metadata
-> crash before resident advances WorkingState
```

Before `173e0d03...`, command replay admission considered only a matching `started` attempt. Restart could reconstruct stale `native_action` and dispatch the same command again even though the previous dispatch had already returned and was durably `observed`.

`SideEffectAwareBody` now treats matching `observed` attempts as replay-blocking for all guarded generic side effects, including `command`, `terminal`, `shell`, and append actions. A generic command has no invented exact verification contract: restart enters `side_effect_recovery` with `user_decision_required` and blocks replay.

`KernelStore.cancel_uncertain_event()` now accepts the recovery-owned attempt when its durable status is either `started` or `observed`. Cancellation still means only that ZN stops the Work; it does not claim whether the outside-world effect occurred. Event terminalization, cancelled `EventOutcome`, idle checkpoint and `work_abandoned` attempt transition remain one SQLite transaction.

For an already `observed` attempt, existing `completed_at`, `result_action_id` and `result_success` are preserved. Cancellation does not erase or reinterpret the durable dispatch observation.

Regression `test_observed_command_restart_blocks_replay_and_cancellation_preserves_dispatch_metadata` constructs the exact crash state, reconstructs the final product resident, proves no command replay, enters explicit recovery, cancels the Work, preserves dispatch metadata and remains terminal after another restart.

## Real test / CI truth

Focused Work proof:

```text
ZN Work Recovery E2E run 33068588882
head 173e0d03fbf52cda68571eb5f22e4aabc3d08805
Windows resident Work restart recovery  success
Ran 50 tests                            OK
```

Ordinary CI proof:

```text
ZN CI run 33068588844
head 173e0d03fbf52cda68571eb5f22e4aabc3d08805
Electron / TypeScript / Windows   success
ZN Source Boundary / Windows      success
ZN Kernel / Python / Windows      success
Kernel                            600 tests / 5 skipped / OK
Publish Windows CI statuses       success
```

The new observed-command regression passed in both focused and full Kernel CI. No local test run is claimed for this web-maintainer slice; repository self-hosted Windows CI is the verification authority.

## Housekeeping note

During documentation preparation, an accidental one-byte placeholder `docs/.tmp-should-not-use` was created in commit `aafa7e6ae0c3784c63e931f5daf5fd0aec244c6a` and immediately removed normally in `4f9d0aa3c94da88fc07203f18284cbc6cd26295d`. The resulting tree is identical to the verified code checkpoint tree. No force push, history rewrite, `main` change or product behavior change occurred.

## Current risks / incomplete work

- broader Work durability remains partial beyond the four verified crash windows;
- the next remaining Work durability ambiguity has not yet been selected and must be established from the real active call chain rather than guessed;
- explanatory-comment cleanup in `intentional_resident.py` remains non-behavioral debt;
- no deliberate outcome-trace rewrite/compactor exists; destructive long-term-memory migration still requires separate review and explicit approval;
- Windows M8 continuity remains incomplete;
- browser PRESS, broader click/editing/multi-select/page lifecycle remain incomplete;
- authenticated User Browser Bridge control remains incomplete;
- SM1+ self-maintenance remains incomplete;
- identity, long-term memory, credentials/permissions, updater/signing, rollback and destructive self-maintenance remain high-risk approval boundaries.

## Task queue

### P1 - broader Work durability

Status: **OPEN / FOUR CRASH WINDOWS VERIFIED**

Closed without blind replay:

1. resident event committed before missing `work_runs` linkage;
2. recovery decision committed before the next `WorkingState` checkpoint;
3. append dispatch durably `observed` before the next `WorkingState` checkpoint;
4. generic command dispatch durably `observed` before the next `WorkingState` checkpoint, with cancellation coherently accepting that recovery-owned state.

### P2 - browser follow-ons

Status: **OPEN**

PRESS, broader click semantics, richer text editing, multi-select, broader page/target lifecycle and authenticated User Browser Bridge control.

### P3 - M8 / SM1+

Status: **OPEN**

Preserve human approval for high-risk identity, memory, credentials, updater/signing, rollback and destructive self-maintenance changes.

## Related files

```text
runtime/python/zn_agent/core/side_effect_body.py
runtime/python/zn_agent/core/store.py
runtime/python/zn_agent/core/focused_modern_text_resident.py
runtime/python/zn_agent/core/work.py
runtime/python/zn_agent/core/work_control.py
tests/zn_agent/core/test_work_cancellation.py
tests/zn_agent/core/test_work_side_effect_recovery.py
tests/zn_agent/core/test_work_side_effect_observed_recovery.py
tests/zn_agent/core/test_work_side_effect_resolution_recovery.py
docs/ZN-IMPLEMENTATION-STATUS.md
.agent/HANDOFF.md
```

## Next real target

Read-only trace the next concrete Work durability ambiguity from durable event/checkpoint/side-effect state through active resident callers, recovery, Work progress/finalization, terminal `EventOutcome`, and restart. Select one narrow crash window only, then implement the smallest coherent ZN-owned fix with a regression.

Keep `main` untouched during ordinary development.
