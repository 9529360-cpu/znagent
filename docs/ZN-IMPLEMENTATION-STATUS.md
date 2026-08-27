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
a5d95f1f2049f96e9ece0c4a1f0ccfa1883e884d  ci: compile resident accounting recovery
67957c8044240abd1d35639a4ca93325c89009d3  test: prove observed capability accounting is restart-idempotent
bb26cf1731eca594c13cf97e6a9eb6bc49b09e1d  fix: resume observed capability results with idempotent accounting
4abe91d042e0cc3df57ecf4df1fc342c915ec008  feat: add idempotent resident capability accounting
bfd8e19bf5a20b5802dbf8148af7ae2c11dcc9dd  fix: distinguish fresh capability admission from replay
```

Status: **BROADER WORK DURABILITY REMAINS PARTIAL. TEN CONCRETE CRASH WINDOWS ARE CLOSED AND VERIFIED. `EventOutcome` REMAINS TERMINAL TRUTH. CANCELLATION REMAINS LIFECYCLE AUTHORITY, NOT EVIDENCE THAT AN OUTSIDE-WORLD EFFECT DID OR DID NOT OCCUR.**

## 1. Existing durable foundations

The established durable boundaries remain:

- terminal event + exact `EventOutcome` + idle `WorkingState` publish atomically;
- Life observation is secondary and repairable without replaying a completed action;
- event-identity-safe nervous outcome perception uses event receipts and keeps receipted traces dereferenceable across pruning;
- Windows canonical path identity remains consistent across investigation, Body/Terminal, Git, Work, verification and procedural learning;
- Work cancellation is atomic and bypasses failure learning because cancellation is a control/lifecycle result;
- effect-capable resident work persists a durable ownership boundary before dispatch and treats unresolved restart state as uncertainty rather than invented success/failure truth.

Generic nervous `perceive()` remains intentionally plastic and is not an exactly-once API.

## 2. Ten proven broader Work crash windows

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

Successful capability accounting is also event-idempotent for this path. `resident_event_accounting(event_id, kind)` gates the self-model evidence update and `runtime_metrics.tasks_total` increment in one SQLite transaction. A crash after accounting but before `resident_completion` can therefore resume from the durable observed result and re-enter the accounting method without duplicating evidence or task totals.

Focused regressions in `test_resident_native_completion_recovery.py` prove:

- interrupted default capability -> restart recovery with no replay and no false failure learning; cancellation closes only lifecycle/attempt ownership;
- explicitly replay-safe capability -> restart may retry the same durable attempt and then complete;
- observed successful capability -> restart completes without capability code being present and without duplicate self-model/runtime accounting;
- the prior `resident_completion` restart case still publishes the exact capability result without re-execution.

This closes the compiled-capability execution/success interval through terminal publication for the tested ownership contracts. It does **not** make every resident accounting path globally event-idempotent and does not prove observed capability failure, general failure-side, memory pre-completion accounting, or external cognition completion boundaries.

## 3. Real Windows CI proof

Exact implementation/test/CI head `a5d95f1f2049f96e9ece0c4a1f0ccfa1883e884d`:

```text
ZN Work Recovery E2E run 33101772085                success
Windows resident Work restart recovery               success
Compile Work recovery path                           success
Verify durable Work progress and restart recovery    success

ZN CI run 33101772081                                success
ZN Kernel / Python / Windows                         success
  Boot isolated ZN distribution without a model      success
  Compile resident core                              success
  Run ZN core tests against working tree             success
ZN Source Boundary / Windows                         success
Electron / TypeScript / Windows                      success
Publish Windows CI statuses                          success
```

The focused recovery suite includes the new interrupted-default, explicit-replay-safe, observed-result/accounting-idempotency and prior native-completion regressions. The ordinary Kernel gate also passed the full working-tree core suite.

No local test run is claimed for this web-maintainer slice because there is no repository checkout in the available execution container. Repository self-hosted Windows CI is the verification authority.

Previous ninth-window implementation head `905b276b755806e119b4f1ce7a73294a03c78f57` passed `ZN Work Recovery E2E` run `33089482266` and `ZN CI` run `33089482187`.

## 4. What remains partial

Open work still includes:

- broader Work durability beyond these ten proven windows;
- observed compiled-capability failure and other failure-side terminal/checkpoint paths remain unproven and are not yet generally event-idempotent;
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

Continue from real call-chain evidence, not analogy. The strongest next Work durability target is failure-side completion ownership: trace observed compiled-capability failure, `_deliberation_step()` failure/impasse handling and the outer `run_once()` exception path through self-model/runtime accounting, checkpoint persistence and terminal `EventOutcome`. Failure must be resumable without duplicate learning/accounting and without converting an uncertain outside-world effect into invented failure evidence.

After that, prove structured-memory pre-completion accounting and external-cognition success/failure completion boundaries independently.

Keep `main` untouched during ordinary development.
