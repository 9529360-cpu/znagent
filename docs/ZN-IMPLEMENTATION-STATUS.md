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

## Current checkpoint - 2026-08-27

`main` remains unchanged at `8234a835dea604783cea0bd9d28a40de654ec03d`. Ordinary development remains on `dev/zn-agent`.

Recent Work durability checkpoints:

```text
8ebae2c43ba13349aa4aebdf8c84746783096c1b  repair missing Work ingress linkage after restart
b41b65dd35ab652e6ed573e5d512778d7313db47  make side-effect recovery resolution restart-idempotent
cf88774ba8c4c9b95adf2aeef5954da4d55ea14b  block observed append replay after restart
173e0d03fbf52cda68571eb5f22e4aabc3d08805  block observed command replay after restart
2ffb79c4bf11903d46f53dd9a7b8d1fcbd922642  keep verified append recovery replay-safe until terminal EventOutcome
f7d6cb64121e914e0250736c0089d58c4b7fea2b  align regression contract with the terminal EventOutcome boundary
dc3b72ad1dfdc5bb8ac2a6c3898fe5038b85197d  resume verified Body completion without replay
82c495424acb4a005d8b6de162c833c6486b2cc0  resume investigation completion without reprobe
```

Status: **BROADER WORK DURABILITY REMAINS PARTIAL. SEVEN CONCRETE CRASH WINDOWS ARE CLOSED AND VERIFIED. `EventOutcome` REMAINS TERMINAL TRUTH. CANCELLATION REMAINS LIFECYCLE AUTHORITY, NOT EVIDENCE THAT AN OUTSIDE-WORLD EFFECT DID OR DID NOT OCCUR.**

## 1. Existing durable foundations

The established durable boundaries remain:

- terminal event + `EventOutcome` + idle `WorkingState` publish atomically;
- Life observation is secondary and repairable without replaying a completed action;
- event-identity-safe nervous outcome perception uses event receipts and keeps receipted traces dereferenceable across pruning;
- Windows canonical path identity remains consistent across investigation, Body/Terminal, Git, Work, verification and procedural learning;
- Work cancellation is atomic and bypasses failure learning because cancellation is a control/lifecycle result.

Generic nervous `perceive()` remains intentionally plastic and is not an exactly-once API.

## 2. Seven proven broader Work crash windows

### 2.1 Missing ingress linkage

The Work start path persists the resident event and `work_runs` linkage separately. `ResidentWorkControl.reconcile_missing_ingress_runs()` repairs only a missing linkage when durable Work thread/message/event evidence agrees. It does not claim, execute, requeue or replay the event.

### 2.2 Recovery decision committed before checkpoint save

`SideEffectAwareBody.resolve_uncertain_attempt()` accepts an exact idempotent acknowledgement of the same already-committed recovery result for the same event/attempt. Conflicting recovery truth still fails closed.

### 2.3 Append `observed` before checkpoint save

A real append can complete and be durably marked `observed` while `WorkingState` still says `native_action`. Append replay admission now treats that matching `observed` attempt as replay-blocking. Restart enters `side_effect_recovery`, re-reads the exact text postcondition and can complete or authorize one retry only from fresh current reality.

### 2.4 Generic command `observed` before checkpoint save

Generic guarded side effects now treat matching `observed` attempts as replay-blocking, including `command`, `terminal` and `shell`. Restart enters explicit recovery instead of redispatching the command. Cancellation coherently accepts the recovery-owned `started` or `observed` attempt while preserving observed dispatch metadata rather than reinterpreting outside-world effects.

Regression: `test_observed_command_restart_blocks_replay_and_cancellation_preserves_dispatch_metadata`.

### 2.5 Verified append recovery success before terminal outcome

After exact read-only verification has proven the append effect and the side-effect attempt is durably `verified_effect`, the resident can crash before `_complete_result()` publishes `EventOutcome`. The effect-present recovery path now keeps the last replay-safe `side_effect_recovery` checkpoint on disk until `KernelStore.complete_event()` atomically publishes terminal event state, exact outcome and idle state. Restart re-runs only the exact read-only verification and never replays `write_text`.

Regressions include `test_restart_after_verified_effect_before_checkpoint_save_completes_without_replay` and the aligned `test_interrupted_append_completes_from_verified_effect_without_replay_or_failure_learning`.

### 2.6 Common verified Body success before terminal outcome

`EmbodiedResidentRuntime._complete_successful_body_action()` previously persisted `WorkingState.stage = complete` before outer `_complete_result()`. Restart deliberately discards durable `complete`, so a still-nonterminal event could return to `orient` and reconsider or replay the Body action.

The common path now persists a resumable `native_completion` checkpoint containing the already-established Body result. Restart reconstructs that result and reaches `KernelStore.complete_event()` without calling Body or repeating runtime task accounting. Missing or malformed completion data fails closed instead of reopening action.

Regression: `test_restart_publishes_verified_body_completion_without_body_replay`.

### 2.7 Base resident investigation success before terminal outcome

The base resident investigation path had the same terminal-looking checkpoint split:

```text
_native_investigation_step resolves from native evidence
-> durable WorkingState.stage = complete
-> successful INVESTIGATION result returned
-> crash before outer _complete_result()
-> restart recovers event to pending but discards complete checkpoint
-> orient/investigate can run again
```

`ZNResidentRuntime._investigation_step()` now persists a nonterminal, resumable `investigation_completion` checkpoint containing only the established investigation result required for terminal publication. Once that checkpoint is durable, restart reconstructs the `ResidentRunResult` and proceeds to the existing atomic `KernelStore.complete_event()` boundary without invoking another native probe or repeating ordinary runtime task accounting. Missing or malformed completion data fails closed as an investigation-path failure instead of reopening investigation.

Regression `test_resolved_investigation_completion_survives_restart_without_reprobe` constructs the exact crash after durable investigation completion and before `EventOutcome`, reconstructs the final product resident, makes any further `investigator.investigate()` call fatal, and proves no reprobe, unchanged runtime task count and investigation rounds, terminal `EventOutcome`, idle `WorkingState` and finalized Work progress.

This closes only the durable `investigation_completion` -> terminal publication split. It does **not** make pre-checkpoint self-model/runtime accounting exactly-once, and it does not prove specialized semantic UI completion or failure-side paths safe.

## 3. Real Windows CI proof

Current exact implementation/test proof for `82c495424acb4a005d8b6de162c833c6486b2cc0`:

```text
ZN Work Recovery E2E run 33080544314  success / 52 tests / OK
ZN CI run 33080544259
Electron / TypeScript / Windows      success
ZN Source Boundary / Windows         success
ZN Kernel / Python / Windows         success / 602 tests / 5 skipped / OK
Publish Windows CI statuses          success
```

The focused recovery job explicitly passed `test_resolved_investigation_completion_survives_restart_without_reprobe`. The full Kernel discovery also passed the same regression at the exact implementation SHA. No local test run is claimed for this web-maintainer slice; repository self-hosted Windows CI is the verification authority.

Previous exact-head sixth-window proof for `dc3b72ad1dfdc5bb8ac2a6c3898fe5038b85197d`:

```text
ZN Work Recovery E2E run 33076704204  success / 51 tests / OK
ZN CI run 33076704179
Electron / TypeScript / Windows      success
ZN Source Boundary / Windows         success
ZN Kernel / Python / Windows         success / 601 tests / 5 skipped / OK
Publish Windows CI statuses          success
```

Previous fifth-window verification head `f7d6cb64121e914e0250736c0089d58c4b7fea2b` also passed focused Work Recovery (50 tests / OK) and ordinary ZN CI (Kernel 600 tests / 5 skipped / OK).

## 4. What remains partial

Open work still includes:

- broader Work durability beyond these seven proven windows;
- specialized semantic/pointer UI completion paths still require their own durable-boundary proof rather than being inferred safe from the common Body path;
- failure-side terminal-looking checkpoint paths remain unproven;
- an adjacent pre-completion-checkpoint accounting window remains: self-model outcome evidence and runtime task metrics can be written before a durable completion checkpoint and are not all event-idempotent, so a crash before checkpoint save can repeat accounting even when the outside-world action itself is not replayed;
- no deliberate outcome-trace rewrite/compactor; any future implementation must atomically retarget receipts before deleting old representation and requires separate review for destructive long-term-memory migration;
- explanatory-comment cleanup in `intentional_resident.py` remains non-behavioral debt;
- Windows continuity M8;
- browser PRESS, broader click/editing/multi-select/page lifecycle;
- authenticated User Browser Bridge control;
- SM1+ self-maintenance.

High-risk identity, long-term memory, credential/permission, updater/signing, rollback and destructive self-maintenance changes still require human approval.

## 5. Next real target

Development is active again. Re-read repository/CI truth before the next slice and prove one remaining family from its real call chain. The strongest current candidates are specialized semantic/pointer UI completion, failure-side terminal-looking checkpoints, or the adjacent pre-checkpoint accounting/idempotence boundary. Do not infer any of them safe from the seven completed slices.

Keep `main` untouched during ordinary development.
