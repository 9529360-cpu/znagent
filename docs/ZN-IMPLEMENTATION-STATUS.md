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

Current verified implementation/test/CI checkpoint before documentation synchronization:

```text
79f7b07dec8e86576f7df66c588ca3b55b278922  test: fail closed on malformed capability observation
08c74058061d612ba8d478d67f211a56edc50d20  fix: fail closed on malformed observed capability result
e61a6749e4478af90cee63cdfa61291f58af7432  ci: cover capability failure restart recovery
d71fd35ed0a1fb3de16d83035cef26c0407f13f0  test: prove observed capability failure recovery
ce90a747eef4340d154db0e3ee24ad15bf226759  fix: resume observed capability failures safely
861533bcf05b4f15289305452011721972fddf73  feat: make capability failure accounting idempotent
```

Status: **BROADER WORK DURABILITY REMAINS PARTIAL. ELEVEN CONCRETE CRASH WINDOWS ARE CLOSED AND VERIFIED. `EventOutcome` REMAINS TERMINAL TRUTH. CANCELLATION REMAINS LIFECYCLE AUTHORITY, NOT EVIDENCE THAT AN OUTSIDE-WORLD EFFECT DID OR DID NOT OCCUR.**

## 1. Existing durable foundations

The established durable boundaries remain:

- terminal event + exact `EventOutcome` + idle `WorkingState` publish atomically;
- Life observation is secondary and repairable without replaying a completed action;
- event-identity-safe nervous outcome perception uses event receipts and keeps receipted traces dereferenceable across pruning;
- Windows canonical path identity remains consistent across investigation, Body/Terminal, Git, Work, verification and procedural learning;
- Work cancellation is atomic and bypasses failure learning because cancellation is a control/lifecycle result;
- effect-capable resident work persists a durable ownership boundary before dispatch and treats unresolved restart state as uncertainty rather than invented success/failure truth.

Generic nervous `perceive()` remains intentionally plastic and is not an exactly-once API.

## 2. Eleven proven broader Work crash windows

The first nine verified windows remain:

1. missing Work ingress linkage after durable resident event creation;
2. recovery decision committed before the next `WorkingState` save;
3. append dispatch durably `observed` before checkpoint save;
4. generic guarded side-effect dispatch durably `observed` before checkpoint save;
5. verified append recovery success before terminal `EventOutcome`;
6. common verified Body success resumes from `native_completion` without Body replay;
7. base resident investigation success resumes from `investigation_completion` without native reprobe;
8. verified semantic/focused/UI completion resumes from `native_completion` without resensing or input replay;
9. already-established base resident MEMORY/CAPABILITY success resumes from `resident_completion` without re-recall/re-execution.

### 2.10 Compiled capability execution ownership before `resident_completion`

The adjacent ninth-window gap was earlier than `resident_completion`: compiled capability code is arbitrary resident-owned program code and may touch the outside world. The old chain could persist only `native_capability`, execute the handler, return success, update self-model/runtime accounting, and then crash before `resident_completion`. Restart could therefore execute the same opaque code again and could duplicate accounting.

The active product now owns an explicit durable compiled-capability execution protocol:

```text
resolve compiled capability
-> persist capability attempt `started` + WorkingState atomically
-> execute resident-owned capability code
-> persist serialized result as attempt `observed` + WorkingState atomically
-> event-idempotent native capability self-model/runtime accounting
-> persist `resident_completion`
-> `KernelStore.complete_event()` terminal transaction
```

Capability replay semantics are explicit rather than guessed:

- `CallableCapability` / `ExactTaskCapability` default to `replay_safe=False`;
- a default capability interrupted after durable `started` is never blindly executed again;
- restart converts that durable ownership fact into the existing `side_effect_recovery` state with `blocked_by=outside_world_effect_uncertain` and `replay_blocked=True`;
- cancellation remains lifecycle authority and atomically abandons the attempt without claiming whether an outside-world effect occurred;
- only a capability explicitly declared `replay_safe=True` may retry after an interrupted durable `started`;
- once a successful result is durably `observed`, restart can reconstruct it even if the capability is not re-registered and without memory recall, matching, resolution or handler execution.

Successful capability accounting is event-idempotent for this path. `resident_event_accounting(event_id, kind)` gates the self-model evidence update and `runtime_metrics.tasks_total` increment in one SQLite transaction. A crash after accounting but before `resident_completion` can therefore resume from the durable observed result and re-enter the accounting method without duplicating evidence or task totals.

Focused regressions in `test_resident_native_completion_recovery.py` prove:

- interrupted default capability -> restart recovery with no replay and no false failure learning; cancellation closes only lifecycle/attempt ownership;
- explicitly replay-safe capability -> restart may retry the same durable attempt and then complete;
- observed successful capability -> restart completes without capability code being present and without duplicate self-model/runtime accounting;
- the prior `resident_completion` restart case still publishes the exact capability result without re-execution.

### 2.11 Observed compiled-capability failure before native investigation

A returned compiled-capability failure is different from an interrupted opaque side effect. The capability wrapper already persists an ordinary returned failure as durable `capability_execution.status=observed`, so ZN has a reliable failure fact. Previously the active resident only resumed observed success. Restart could ignore the observed failure, re-enter memory/capability matching, execute code again, and duplicate `observe_native_outcome(... success=False)` evidence.

The active product now treats observed capability failure as its own resumable fact:

```text
capability returns known failure
-> atomically persist result as `observed` + WorkingState
-> event-idempotent native capability failure evidence
-> persist `native_investigation` continuation
-> continue investigation without reloading/re-executing capability code
```

`ResidentAccountingJournal.record_native_capability_failure()` gates failure evidence by `(event_id, native_capability_failure)`. This path deliberately does **not** increment `runtime_metrics.tasks_total`, because a failed compiled capability is an intermediate observation and the resident task continues into native investigation.

Restart semantics are explicit:

- a durable observed failure is resumed before memory recall or capability resolution;
- a crash after failure accounting but before the `native_investigation` WorkingState save re-enters the accounting method safely without duplicate evidence;
- `outside_world_effect_uncertain` remains recovery/uncertainty and is rejected if any caller tries to convert it into known failure evidence;
- malformed durable `observed` result data fails closed with `RuntimeError` rather than falling through to capability replay.

Focused regressions in `test_capability_failure_recovery.py` prove:

- `test_observed_failure_resumes_without_code_or_duplicate_failure_learning` simulates crash after durable failure accounting but before investigation checkpoint, restarts without capability code, makes memory recall/resolution fatal, and verifies exactly one failure-evidence update with no task-total increment;
- `test_malformed_observed_result_fails_closed_without_replay` verifies corrupt observed result truth cannot reopen execution.

This closes the observed compiled-capability failure -> native-investigation restart interval for the tested ownership contract. It does **not** close terminal failure ownership in `_deliberation_step()`, the outer `run_once()` exception path, structured-memory pre-completion accounting, or external cognition completion boundaries.

## 3. Real Windows CI proof

Exact implementation/test/CI head `79f7b07dec8e86576f7df66c588ca3b55b278922`:

```text
ZN Work Recovery E2E run 33103741459                success
Windows resident Work restart recovery               success
Compile Work recovery path                           success
Verify durable Work progress and restart recovery    success

ZN CI run 33103741461                                success
ZN Kernel / Python / Windows                         success
  Boot isolated ZN distribution without a model      success
  Compile resident core                              success
  Run ZN core tests against working tree             success
ZN Source Boundary / Windows                         success
Electron / TypeScript / Windows                      success
Publish Windows CI statuses                          success
```

The focused recovery suite includes the existing capability interruption/success recovery regressions plus the new observed-failure/idempotency and malformed-observation fail-closed tests. The ordinary Kernel gate also passed the full working-tree core suite.

No local test run is claimed for this web-maintainer slice because there is no repository checkout in the available execution container. Repository self-hosted Windows CI is the verification authority.

Previous tenth-window implementation head `a5d95f1f2049f96e9ece0c4a1f0ccfa1883e884d` passed `ZN Work Recovery E2E` run `33101772085` and `ZN CI` run `33101772081`.

## 4. What remains partial

Open work still includes:

- broader Work durability beyond these eleven proven windows;
- terminal failure/checkpoint ownership remains unproven for `_deliberation_step()` impasse/budget failure and the outer `run_once()` exception path; those paths can still account failure before terminal publication without a dedicated resumable failure-completion contract;
- structured-memory success still performs self-model/runtime accounting before its completion checkpoint; only the already-durable `resident_completion` restart interval is proven there;
- external cognition success/failure completion boundaries still require direct crash/restart proof rather than analogy;
- the shared `resident_side_effect_attempts` truth is used by Body and compiled capability recovery, but low-level helper implementation is not yet fully consolidated; do not treat helper duplication as a second truth model;
- direct synchronous driving while a Work item is in unresolved `side_effect_recovery` still deserves separate lifecycle review; unresolved external truth must not be converted to automatic replay or failure merely to make synchronous callers terminate;
- no deliberate outcome-trace rewrite/compactor; any future implementation must atomically retarget receipts before deleting old representation and requires separate review for destructive long-term-memory migration;
- explanatory-comment cleanup in `intentional_resident.py` remains non-behavioral debt;
- Windows continuity M8;
- browser PRESS, broader click/editing/multi-select/page lifecycle;
- authenticated User Browser Bridge control;
- SM1+ self-maintenance.

High-risk identity, long-term memory, credential/permission, updater/signing, rollback and destructive self-maintenance changes still require human approval.

## 5. Next real target

Continue from real call-chain evidence, not analogy. The strongest next Work durability target is terminal failure completion ownership: trace `_deliberation_step()` impasse/budget failure and the outer `run_once()` exception path through Life/self-model/runtime accounting, WorkingState persistence and terminal `EventOutcome`. Establish a durable resumable failure fact before non-idempotent learning/accounting, without converting uncertain outside-world effects into invented failure evidence.

After that, prove structured-memory pre-completion accounting and external-cognition success/failure completion boundaries independently.

Keep `main` untouched during ordinary development.
