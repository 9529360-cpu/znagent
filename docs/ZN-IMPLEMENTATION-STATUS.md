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

Exact implementation/test/CI checkpoint before this documentation synchronization:

```text
7b88494d8f6ef8974ca256ef6772754dec523310  ci: cover synchronous Work handoff
68447fea5bbda5b96a4e2a29a49f14c5fb625a82  test: prove synchronous Work recovery handoff
c26152175436b0d84a563437cae9f25466453eb4  feat: return blocked Work recovery to sync RPC callers
a200fcec16a429fdd65fce10f403f97b249070ff  feat: bound synchronous Work recovery driving
c812154b75bab5b2020c2020099df5028c10b812  refactor: reuse resident loop for sync recovery control
8274289f22daa18d8638f365da54d794e2e4b3f0  ci: cover external learning recovery boundaries
```

Status: **BROADER WORK DURABILITY REMAINS PARTIAL. EIGHTEEN CONCRETE CRASH/RESTART WINDOWS REMAIN CLOSED AND VERIFIED. THE DIRECT SYNCHRONOUS `side_effect_recovery` LIFECYCLE IS NOW ALSO BOUNDED AND VERIFIED. `EventOutcome` REMAINS TERMINAL TRUTH; OUTSIDE-WORLD UNCERTAINTY IS NOT CONVERTED INTO REPLAY PERMISSION OR INVENTED SUCCESS/FAILURE MERELY TO TERMINATE A CALLER.**

## 1. Durable foundations

The established durable boundaries remain:

- terminal event + exact `EventOutcome` + idle `WorkingState` publish atomically;
- Life observation is secondary and repairable without replaying a completed action;
- event-identity-safe nervous outcome perception uses receipts and keeps receipted traces dereferenceable across pruning;
- Windows canonical path identity remains consistent across investigation, Body/Terminal, Git, Work, verification and procedural learning;
- Work cancellation is atomic and bypasses failure learning because cancellation is a lifecycle/control result;
- effect-capable resident work persists durable ownership before dispatch and treats unresolved restart state as uncertainty;
- zero-model terminal failure and deterministic outer resident exceptions persist failure truth before event-idempotent accounting and terminal publication;
- structured-memory, native-investigation and external-cognition completion persist semantic completion before cumulative accounting/learning;
- external provider dispatch has durable attempt identity; a provider-dispatch crash with unknown outcome blocks blind replay rather than pretending exactly-once provider semantics.

Generic nervous `perceive()` remains intentionally plastic and is not an exactly-once API.

## 2. Eighteen proven broader Work crash/restart windows

The verified crash/restart windows are:

1. missing Work ingress linkage after durable resident event creation;
2. recovery decision committed before the next `WorkingState` save;
3. append dispatch durably `observed` before checkpoint save;
4. generic guarded side-effect dispatch durably `observed` before checkpoint save;
5. verified append recovery success before terminal `EventOutcome`;
6. common verified Body success resumes from `native_completion` without Body replay;
7. base resident investigation success resumes from `investigation_completion` without native reprobe;
8. verified semantic/focused/UI completion resumes from `native_completion` without resensing or input replay;
9. base resident MEMORY/CAPABILITY success resumes from `resident_completion` without re-recall/re-execution;
10. compiled capability execution persists durable `started`/`observed` ownership, blocks blind replay by default, and uses event-idempotent successful capability accounting;
11. durable observed compiled-capability failure resumes into native investigation without capability replay or duplicate failure evidence, while malformed observed truth fails closed;
12. zero-model terminal budget-blocked failure persists exact `terminal_failure` truth before task accounting and terminal publication;
13. deterministic outer `run_once()` exception publication uses the same terminal-failure ownership while refusing to overwrite durable success or outside-world uncertainty;
14. structured-memory success persists `resident_completion` before event-idempotent task/knowledge accounting;
15. native-investigation success persists `investigation_completion` before event-idempotent ability/knowledge/task accounting;
16. external cognition persists exact `external_completion` before resident metrics, success knowledge, Life/investigation integration and terminal `EventOutcome`, so restart does not replay the model;
17. external kernel attempts persist stable goal/attempt identity, full worker result, deterministic experience/proposal identity and exactly-once route-quality accounting;
18. crash after provider dispatch but before a returned result becomes explicit unknown-provider-outcome uncertainty: provider replay is blocked and no route learning or improvement proposal is invented from the unknown result.

The detailed completion/accounting implementation remains in `runtime.py`, `kernel_accounting.py`, `capability_recovery_resident.py`, `resident_accounting.py` and the completion durability tests. Those eighteen crash/restart windows remain the crash-window count; the synchronous lifecycle proof below is an additional caller/lifecycle boundary rather than an artificial nineteenth crash window.

## 3. Verified synchronous recovery lifecycle boundary

### 3.1 Real active callers audited

The active caller chain is now explicit:

```text
provider_bridge.build_resident_runtime()
-> RecoveryBoundedResidentRuntime
   -> direct run_once(thought=None)
   -> resident.submit()
-> RecoveryBoundedWorkLedger
   -> legacy synchronous Work submit
-> ResidentRpcServer.work_submit

normal desktop Work:
work_start
-> background resident life loop
-> work_progress / work_cancel
```

The normal desktop path was already asynchronous and did not need to turn uncertainty into a terminal result. The unbounded loop existed in the still-callable synchronous faces: direct `run_once()`, `resident.submit()` and legacy synchronous `work_submit`.

### 3.2 Synchronous caller contract

`recovery_control.py` defines `ResidentRecoveryRequired`, a control-flow exception rather than a task-failure result. It is raised only when the current event is durably in:

```text
stage=side_effect_recovery
blocked_by=outside_world_effect_uncertain
replay_blocked=true
decision != reverify_effect
```

The exact append `reverify_effect` path is deliberately allowed to continue because it can make progress through read-only evidence without replaying the outside-world effect.

`RecoveryBoundedResidentRuntime` does **not** copy the resident main loop. A thread-local synchronous control scope and `_advance_event_step()` hook reuse the single resident owner loop:

- direct `run_once(thought=None)` yields once an explicit recovery decision is required;
- `resident.submit()` uses the same boundary;
- one-step/asynchronous `live_once()` driving does not raise and the resident remains alive while the Work waits;
- `resident.submit()` preflights an already-blocked active event before enqueueing a second hidden task, so a caller cannot receive an exception while unknowingly creating new queued Work.

The event remains active, its `WorkingState` remains `side_effect_recovery`, the side-effect attempt remains durable, and no terminal `EventOutcome` is invented.

### 3.3 Legacy synchronous Work and RPC handoff

`RecoveryBoundedWorkLedger` wraps the existing `ResidentWorkLedger.submit()` in the same synchronous control scope instead of copying Work execution logic. If that Work itself reaches replay-blocked uncertainty, the resident boundary yields while the Work/event remains active.

`ResidentRpcServer.work_submit` converts that control handoff into structured progress for the same Work:

```text
recovery_required=true
progress.stage=side_effect_recovery
progress.terminal=false
progress.finalized=false
```

The caller can then use existing progress/cancel control instead of hanging the RPC or receiving invented failure truth. Explicit `work_cancel` remains atomic lifecycle authority and marks the durable side-effect attempt `work_abandoned`; cancellation still does not assert whether the outside-world effect actually happened.

### 3.4 Restart and no-replay proof

`tests/zn_agent/core/test_synchronous_recovery_control.py` directly proves:

- direct synchronous `run_once()` yields without terminal publication or side-effect replay;
- one-step resident life driving holds the same recovery without throwing;
- synchronous `resident.submit()` refuses to enqueue hidden new Work behind an already-blocked event;
- restart preserves the yield boundary and the same event can still be explicitly cancelled afterward;
- legacy RPC `work_submit` returns structured recovery progress for its own blocked Work, and subsequent `work_cancel` atomically terminates lifecycle ownership while marking the attempt `work_abandoned`;
- read-only `reverify_effect` is not mistaken for a user-decision block.

This closes the synchronous caller-termination/cancellation/restart lifecycle gap without changing outside-world uncertainty semantics.

## 4. Real Windows CI proof

Exact implementation/test/CI head `7b88494d8f6ef8974ca256ef6772754dec523310`:

```text
ZN Work Recovery E2E run 33114819916                success
Windows resident Work restart recovery               success
Compile Work recovery path                           success
Verify durable Work progress and restart recovery    success
  includes synchronous recovery lifecycle regressions

ZN CI run 33114819943                                success
ZN Kernel / Python / Windows                         success
  Boot isolated ZN distribution without a model      success
  Compile resident core                              success
  Run ZN core tests against working tree             success
ZN Source Boundary / Windows                         success
Electron / TypeScript / Windows                      success
Publish Windows CI statuses                          success
```

A superseded general-CI run on `a200fcec16a429fdd65fce10f403f97b249070ff` was partially cancelled during the later branch pushes and is not used as proof. The final-head recovery and general CI runs above are authoritative.

No local repository test run is claimed for this web-maintainer slice. Repository self-hosted Windows CI is the verification authority.

## 5. What remains partial

Open work still includes:

- broader Work durability beyond the eighteen proven crash/restart windows and the now-verified synchronous recovery lifecycle;
- Body and compiled capability recovery share the single `resident_side_effect_attempts` durable truth, but low-level helper implementation remains duplicated and needs an audit/consolidation that preserves existing signature/hash and upgrade semantics;
- continue bounded backward auditing for any other cumulative accounting/learning writes that can occur before durable semantic facts in active paths;
- no deliberate outcome-trace rewrite/compactor; any future implementation must atomically retarget receipts before deleting old representation and requires separate review for destructive long-term-memory migration;
- explanatory-comment cleanup in `intentional_resident.py` remains non-behavioral debt;
- Windows continuity M8;
- browser PRESS, broader click/editing/multi-select/page lifecycle;
- authenticated User Browser Bridge control;
- SM1+ self-maintenance.

High-risk identity, long-term memory, credential/permission, updater/signing, rollback and destructive self-maintenance changes still require human approval.

## 6. Next real target

Continue the bounded broader-Work audit at the shared low-level side-effect-attempt owner:

1. trace `resident_side_effect_attempts` from Body and compiled capability entry points through schema, signature identity, start/observe/finish/abandon transitions, pruning, recovery and tests;
2. consolidate only genuinely duplicated low-level persistence helpers without introducing a second truth model or changing historical signature/hash semantics;
3. add direct compatibility/recovery proof for Body and compiled capability callers against the shared helper;
4. then continue backward from other cumulative accounting/learning writes to verify durable semantic facts precede recoverable cumulative state.

Preserve `outside_world_effect_uncertain` and unknown external-provider outcomes as uncertainty, not replay permission or fabricated success/failure evidence.

Keep `main` untouched during ordinary development.
