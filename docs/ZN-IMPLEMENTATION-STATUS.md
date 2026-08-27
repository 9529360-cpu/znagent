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
a70d15600c7bd8b361a0120e303b881b82461f3f  ci: cover shared side effect attempt owner
a681bfbf08efe720251ef037f0bd45d5f1b797aa  test: protect active side effect recovery facts
a093a35226d05bff866063b2f483a01f869bb84f  refactor: share compiled side effect persistence
5c42cdd7a403b1a14ee915934d9e3d4967e34a8b  refactor: route body side effects through shared persistence
836acf3b778cf0bbb7b5ae6eeb247f6771ae424e  refactor: centralize side effect attempt persistence
7b88494d8f6ef8974ca256ef6772754dec523310  ci: cover synchronous Work handoff
```

Status: **BROADER WORK DURABILITY REMAINS PARTIAL. EIGHTEEN CONCRETE CRASH/RESTART WINDOWS REMAIN CLOSED AND VERIFIED. THE DIRECT SYNCHRONOUS `side_effect_recovery` LIFECYCLE REMAINS BOUNDED AND VERIFIED. BODY AND COMPILED CAPABILITY RECOVERY NOW SHARE ONE LOW-LEVEL `resident_side_effect_attempts` PERSISTENCE OWNER, AND CAPACITY PRUNING IS TERMINAL-TRUTH-GATED SO ACTIVE RECOVERY FACTS CANNOT BE DELETED MERELY BECAUSE THEIR ATTEMPT STATUS IS NO LONGER `started`.**

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
- external provider dispatch has durable attempt identity; a provider-dispatch crash with unknown outcome blocks blind replay rather than pretending exactly-once provider semantics;
- replay-sensitive Body and compiled-capability attempts use one shared low-level SQLite owner while retaining their intentionally different historical signature identities;
- capacity pruning can remove only attempts whose owning event has both terminal event state and a durable `EventOutcome`; nonterminal recovery truth is retained regardless of attempt status.

Generic nervous `perceive()` remains intentionally plastic and is not an exactly-once API.

## 2. Eighteen proven broader Work crash/restart windows

The verified crash/restart windows remain:

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

The crash-window count remains eighteen. The synchronous caller boundary and the shared side-effect-attempt persistence/pruning proof are additional lifecycle/persistence invariants, not artificial new crash-window counts.

## 3. Verified synchronous recovery lifecycle boundary

The previously verified caller chain remains:

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

`ResidentRecoveryRequired` remains caller-control flow rather than task failure. It yields only for durable replay-blocked `side_effect_recovery` that requires an explicit decision, while exact read-only `reverify_effect` can continue. Asynchronous resident life remains alive; explicit cancellation remains lifecycle authority; no terminal result is fabricated solely to end a synchronous call.

## 4. Shared side-effect-attempt persistence owner

### 4.1 Active callers and ownership

The active replay-sensitive paths now converge on `runtime/python/zn_agent/core/side_effect_attempts.py`:

```text
SideEffectAwareBody
-> side_effect_attempts
-> resident_side_effect_attempts

compiled capability execution
-> ResidentSideEffectJournal
-> side_effect_attempts
-> resident_side_effect_attempts

KernelStore.cancel_uncertain_event
-> same resident_side_effect_attempts transaction
-> shared schema deletion guard
-> event + EventOutcome + idle WorkingState atomically
```

The shared module owns table/index creation, connection policy, plain attempt start/read/observe/resolve queries, replay-blocking/event-attempt lookup and terminal-safe capacity pruning.

`KernelStore.cancel_uncertain_event()` intentionally remains a participant in the same SQLite transaction instead of opening a second helper connection: cancellation must atomically transition the attempt to `work_abandoned`, publish failed/cancelled event truth + `EventOutcome`, and clear `WorkingState`. The shared schema protects that transaction's existing direct cleanup SQL from deleting any nonterminal recovery fact.

### 4.2 Historical identity semantics preserved

The refactor does **not** normalize persisted identities:

- Body keeps SHA-256 over exact JSON `{"kind": kind, "args": args}`;
- compiled capabilities keep SHA-256 over exact JSON `{"kind": normalized_kind, "identity": identity}`.

Direct regression constants lock both encodings and assert they remain distinct. No upgrade rewrite or historical row migration was introduced.

Body keeps its existing behavioral differences: strict plain attempt start/observe, `result_action_id` + result success metadata, started-or-observed recovery resolution, and optional observed replay blocking. Compiled capabilities keep idempotent `start_with_checkpoint` / `observe_with_checkpoint`, atomic WorkingState persistence and started-only default replay blocking.

### 4.3 Terminal-truth-gated pruning

The old cleanup rule selected any attempt with `status!='started'`. That was unsafe because `observed`, `verified_effect` or `verified_absent` may still be required recovery truth while the owning event has no terminal `EventOutcome`.

The new invariant is:

> **Capacity pruning may delete an attempt only after the owning event is terminal (`completed` or `failed`) and that event has a durable `event_outcomes` row. Attempts for nonterminal events are retained regardless of attempt status.**

The shared helper enforces the rule in its normal prune query. The shared schema also installs a delete guard, so an older/direct generic DELETE fails safe for nonterminal attempts. Terminal outcome publication can then prune bounded historical rows without weakening active recovery.

This specifically protects:

- Body recovery facts already resolved to `verified_effect` / `verified_absent` before terminal publication;
- Body `observed` dispatch truth before the next semantic checkpoint;
- compiled-capability `observed` attempt truth paired with its durable WorkingState;
- unrelated active recoveries during Work cancellation cleanup.

### 4.4 Compatibility proof

`tests/zn_agent/core/test_side_effect_attempt_persistence.py` proves:

- the exact historical Body and compiled-capability signature encodings remain stable and distinct;
- an attempt started through Body is visible through `ResidentSideEffectJournal`, and a Body recovery transition is visible through the same journal owner;
- terminal historical attempts are eligible for bounded pruning;
- active Body `verified_effect` and compiled-capability `observed` attempts survive zero-capacity pruning pressure;
- a raw/generic DELETE cannot remove those nonterminal recovery facts;
- the active event still has no `EventOutcome`, demonstrating that retention is tied to terminal truth rather than attempt status.

Existing Work side-effect, observed recovery, resolution recovery, cancellation and compiled-capability recovery tests remain in the focused recovery suite and all passed on the same code head.

## 5. Real Windows CI proof

Exact implementation/test/CI head `a70d15600c7bd8b361a0120e303b881b82461f3f`:

```text
ZN Work Recovery E2E run 33117334326                success
Windows resident Work restart recovery               success
Compile Work recovery path                           success
Verify durable Work progress and restart recovery    success
  includes shared attempt-owner/pruning regressions

ZN CI run 33117334321                                success
ZN Kernel / Python / Windows                         success
  Boot isolated ZN distribution without a model      success
  Compile resident core                              success
  Run ZN core tests against working tree             success
ZN Source Boundary / Windows                         success
Electron / TypeScript / Windows                      success
Publish Windows CI statuses                          success
```

No local repository test run is claimed for this web-maintainer slice. Repository self-hosted Windows CI is the verification authority.

## 6. What remains partial

Open work still includes:

- broader Work durability beyond the eighteen proven crash/restart windows, synchronous recovery lifecycle and now-verified shared side-effect-attempt owner/pruning invariant;
- continue bounded backward auditing for other cumulative accounting/learning writes that can occur before durable semantic facts in active paths;
- no deliberate outcome-trace rewrite/compactor; any future implementation must atomically retarget receipts before deleting old representation and requires separate review for destructive long-term-memory migration;
- explanatory-comment cleanup in `intentional_resident.py` remains non-behavioral debt;
- Windows continuity M8;
- browser PRESS, broader click/editing/multi-select/page lifecycle;
- authenticated User Browser Bridge control;
- SM1+ self-maintenance.

High-risk identity, long-term memory, credential/permission, updater/signing, rollback and destructive self-maintenance changes still require human approval.

## 7. Next real target

Continue the bounded broader-Work durability audit from cumulative accounting/learning writes:

1. enumerate active resident/kernel accounting and learning writes that mutate cumulative state;
2. trace each backward to the durable semantic fact that makes the write replay-safe or event-idempotent;
3. identify any remaining path where cumulative state can become durable before the semantic completion/failure fact needed to resume correctly;
4. close only evidence-backed gaps with restart tests and real CI before advancing again.

Preserve `outside_world_effect_uncertain` and unknown external-provider outcomes as uncertainty, not replay permission or fabricated success/failure evidence.

Keep `main` untouched during ordinary development.
