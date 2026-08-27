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

Exact implementation/test/CI checkpoint before documentation synchronization:

```text
8274289f22daa18d8638f365da54d794e2e4b3f0  ci: cover external learning recovery boundaries
5384a71ad0d92d59046a023550c8de987ed22047  test: probe external learning recovery boundaries
dadc769875f4694d26e908f9c3a445349326d138  fix: close resident completion durability gaps
b1809578162178cab09fc4ad7224ffaaeafb5ba2  docs: hand off terminal failure recovery
```

Status: **BROADER WORK DURABILITY REMAINS PARTIAL. EIGHTEEN CONCRETE CRASH/RESTART WINDOWS ARE NOW CLOSED AND VERIFIED. `EventOutcome` REMAINS TERMINAL TRUTH. OUTSIDE-WORLD UNCERTAINTY AND EXTERNAL-PROVIDER OUTCOME UNCERTAINTY ARE NOT INVENTED INTO SUCCESS OR SAFE REPLAY.**

## 1. Existing durable foundations

The established durable boundaries remain:

- terminal event + exact `EventOutcome` + idle `WorkingState` publish atomically;
- Life observation is secondary and repairable without replaying a completed action;
- event-identity-safe nervous outcome perception uses event receipts and keeps receipted traces dereferenceable across pruning;
- Windows canonical path identity remains consistent across investigation, Body/Terminal, Git, Work, verification and procedural learning;
- Work cancellation is atomic and bypasses failure learning because cancellation is a control/lifecycle result;
- effect-capable resident work persists a durable ownership boundary before dispatch and treats unresolved restart state as uncertainty rather than invented success/failure truth;
- zero-model terminal failure and deterministic outer resident exceptions persist terminal-failure truth before event-idempotent accounting and terminal publication.

Generic nervous `perceive()` remains intentionally plastic and is not an exactly-once API.

## 2. Eighteen proven broader Work crash/restart windows

The first thirteen verified windows remain:

1. missing Work ingress linkage after durable resident event creation;
2. recovery decision committed before the next `WorkingState` save;
3. append dispatch durably `observed` before checkpoint save;
4. generic guarded side-effect dispatch durably `observed` before checkpoint save;
5. verified append recovery success before terminal `EventOutcome`;
6. common verified Body success resumes from `native_completion` without Body replay;
7. base resident investigation success resumes from `investigation_completion` without native reprobe;
8. verified semantic/focused/UI completion resumes from `native_completion` without resensing or input replay;
9. already-established base resident MEMORY/CAPABILITY success resumes from `resident_completion` without re-recall/re-execution;
10. compiled capability execution persists durable `started`/`observed` ownership, blocks blind replay by default, and uses event-idempotent successful capability accounting;
11. durable observed compiled-capability failure resumes into native investigation without capability replay or duplicate failure evidence, while malformed observed truth fails closed;
12. zero-model terminal budget-blocked failure persists exact `terminal_failure` truth before task accounting and terminal publication;
13. deterministic outer `run_once()` exception publication uses the same terminal-failure ownership while refusing to overwrite durable success or outside-world uncertainty.

The current bounded backward audit closes five additional windows.

### 2.14 Structured-memory success: semantic completion before accounting

The active resident previously performed knowledge/runtime accounting before its durable `resident_completion` checkpoint. A crash in that interval could leave cumulative evidence ahead of the semantic fact used to resume the event.

The active product owner now does:

```text
structured memory match
-> construct exact memory completion
-> persist WorkingState stage=resident_completion
   + versioned resident_completion_accounting descriptor
-> ResidentAccountingJournal.record_memory_success(event_id)
-> publish terminal EventOutcome
```

`record_memory_success()` is event-idempotent through `(event_id, memory_success)`. Restart after checkpoint-before-accounting completes the missing accounting once without re-running memory recall. Restart after accounting-before-`EventOutcome` consumes the same checkpoint without duplicate task or knowledge evidence.

Compatibility rule: a historical `resident_completion` checkpoint without the new accounting descriptor is treated as already accounted, because the old implementation only created that checkpoint after eager accounting. Upgrade recovery therefore does not duplicate old evidence.

### 2.15 Native-investigation success: semantic completion before accounting

The active native-investigation success path had the same ordering problem for independent-ability, knowledge and task accounting.

It now does:

```text
native investigation resolves
-> construct exact investigation completion
-> persist WorkingState stage=investigation_completion
   + versioned investigation_completion_accounting descriptor
-> ResidentAccountingJournal.record_native_investigation_success(event_id)
-> publish terminal EventOutcome
```

The journal gates `(event_id, native_investigation_success)` and updates ability, knowledge and task totals atomically on first insert. Crash/restart tests prove both checkpoint-before-accounting and accounting-before-terminal-publication without native reprobe or duplicate evidence.

Historical investigation checkpoints without the descriptor are likewise treated as already accounted because the prior path checkpointed only after eager accounting.

### 2.16 External cognition resident completion and secondary learning boundary

External cognition previously returned from `ZNKernelRuntime.run_goal()`, updated task metrics and then moved WorkingState directly to `complete/failed`. On restart, those stages were not a recoverable semantic completion owner and the event could return to orientation/model selection.

The active resident now gives external cognition its own durable completion stage:

```text
bounded cognition request
-> durable kernel goal/result
-> persist WorkingState stage=external_completion
   + exact success/failure result
   + versioned external_completion_accounting descriptor
-> event-idempotent resident task/model/token accounting
-> success-only resident knowledge integration
-> success: Life resolution + guarded investigation integration
   failure: Life unresolved publication
-> terminal EventOutcome
```

The exact resident result is durable before cumulative resident accounting or learning. Restart from `external_completion` never invokes the provider again. Resident accounting is gated by `(event_id, external_completion)`.

Direct fault injection proves:

- success after resident accounting but before terminal `EventOutcome`: no model replay, no duplicate metrics, knowledge, route evidence or Life learning candidate;
- success after Life learning but before `investigator.resolve_from_external()`: restart finishes the missing investigation integration without replaying the model or duplicating resident accounting/Life candidate;
- failure before resident metrics: restart accounts once and does not invent success knowledge;
- failure after resident metrics but before `mark_impasse_unresolved()`: restart publishes the missing unresolved Life state without model replay or duplicate metrics.

`Life` learning candidate identity remains deterministic by impasse. Investigation external integration is guarded so an already-resolved investigation does not append duplicate external evidence.

### 2.17 Durable kernel result, experience and route-learning settlement

Resident completion alone is insufficient because the external kernel previously had no durable provider-attempt identity. The kernel now stores a versioned attempt ledger in Goal metadata and accepts a stable `goal_id` from the resident cognition request.

Attempt ownership is:

```text
select route
-> persist attempt status=dispatching + route snapshot
-> provider worker.run()
-> persist full WorkerResult status=worker_observed
-> local critic assessment -> persist assessed
-> idempotent experience + route-quality accounting
-> persist settled
-> persist final goal result
```

Full `WorkerResult` is persisted rather than only the old experience excerpt, so a restart after provider return reconstructs the original complete response. Experience IDs are deterministic per `(goal_id, attempt)`. Route-quality evidence is journaled exactly once by `(goal_id, attempt, external_route_assessment)`.

Fault injection proves restart after `worker_observed` does not recreate or rerun the provider, preserves a response longer than the old 2000-character experience excerpt, and records route evidence once. A second fault injection after route accounting/`settled` but before final goal publication proves restart does not duplicate route learning or provider work.

Improvement proposal IDs are now deterministic for the same durable goal/weakness/scope so recovery cannot create a second logical proposal merely because final publication was interrupted.

### 2.18 Provider dispatch with unknown outcome is replay-blocking uncertainty

There is an irreducible interval after durable `dispatching` and before a returned provider result can be checkpointed. If the process dies there, ZN cannot know whether the external provider completed, charged, or produced a result.

Restart therefore does **not** blindly retry or switch route. It converts that durable attempt into an explicit unknown-outcome failure:

- provider replay is blocked;
- the task reports that external outcome is unknown;
- no route-quality evidence is learned from the unknown outcome;
- no improvement proposal is created from the unknown outcome;
- resident failure accounting can still publish the one bounded cognition attempt as a failed task fact without pretending to know provider success.

This is intentionally conservative. At-most-once provider dispatch is preferred over inventing exactly-once semantics that the provider boundary cannot prove.

## 3. Real Windows CI proof

Exact implementation/test/CI head `8274289f22daa18d8638f365da54d794e2e4b3f0`:

```text
ZN Work Recovery E2E run 33112257030                success
Windows resident Work restart recovery               success
Compile Work recovery path                           success
Verify durable Work progress and restart recovery    success
  includes primary + secondary completion durability fault injection

ZN CI run 33112257029                                success
ZN Kernel / Python / Windows                         success
  Boot isolated ZN distribution without a model      success
  Compile resident core                              success
  Run ZN core tests against working tree             success
ZN Source Boundary / Windows                         success
Electron / TypeScript / Windows                      success
Publish Windows CI statuses                          success
```

The previous focused recovery run on implementation commit `dadc769875f4694d26e908f9c3a445349326d138` also passed (`ZN Work Recovery E2E` run `33111884613`). Its general ZN CI run was superseded/cancelled by later branch pushes, so it is not used as the final full-suite proof.

No local repository test run is claimed for this web-maintainer slice. Scratch copies of the changed Python modules/tests passed `py_compile`; repository self-hosted Windows CI is the verification authority.

## 4. What remains partial

Open work still includes:

- broader Work durability beyond these eighteen proven windows;
- direct synchronous driving while a Work item is in unresolved `side_effect_recovery` still deserves separate lifecycle review; unresolved external truth must not be converted to automatic replay or failure merely to make synchronous callers terminate;
- the shared `resident_side_effect_attempts` truth is used by Body and compiled capability recovery, but low-level helper implementation is not yet fully consolidated; do not treat helper duplication as a second truth model;
- continue bounded backward auditing for any cumulative accounting/learning that can still occur before its durable semantic fact in other active paths;
- no deliberate outcome-trace rewrite/compactor; any future implementation must atomically retarget receipts before deleting old representation and requires separate review for destructive long-term-memory migration;
- explanatory-comment cleanup in `intentional_resident.py` remains non-behavioral debt;
- Windows continuity M8;
- browser PRESS, broader click/editing/multi-select/page lifecycle;
- authenticated User Browser Bridge control;
- SM1+ self-maintenance.

High-risk identity, long-term memory, credential/permission, updater/signing, rollback and destructive self-maintenance changes still require human approval.

## 5. Next real target

Continue the bounded broader-Work durability audit from the nearest remaining lifecycle gap rather than reopening the just-closed completion paths:

1. trace direct synchronous driving while durable `side_effect_recovery` remains unresolved, including caller termination, cancellation and resume semantics;
2. audit/consolidate the shared low-level `resident_side_effect_attempts` helper without introducing a second truth model or changing outside-world uncertainty semantics;
3. continue backward from other cumulative accounting/learning writes to verify that durable semantic facts always precede recoverable cumulative state.

For each path, trace entry -> owner -> durable state -> lifecycle -> dependencies -> tests -> active caller, and add direct crash/restart proof rather than assuming similarity. Preserve both `outside_world_effect_uncertain` and unknown external-provider outcomes as uncertainty, not replay permission or fabricated success/failure evidence.

Keep `main` untouched during ordinary development.
