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

## Current checkpoint - 2026-08-28

`main` remains unchanged at `8234a835dea604783cea0bd9d28a40de654ec03d`. Ordinary development remains on `dev/zn-agent`.

Exact implementation/test/CI checkpoint before this documentation synchronization:

```text
f79d4f3c81b1d7c46dcfb55b6fc923acda77b39c  test: preserve effect probe accounting authority
d0e6c3bde9f50274a9ad4c31fac6a042364c8f7f  fix: defer body accounting without stealing completion ownership
d615241dc7fb0f95be1aa524ab2d27cf1bf1804b  fix: preserve body accounting semantics after checkpoints
7a420f67efd58dfe55d04c173a15adeabaeb1c83  ci: cover durable body accounting recovery
c8fec59fdc442da67829ea0a4e299e6c800c7533  test: prove body accounting follows durable semantic truth
3020604e70762dc9f461fb85555d1c507523c0e2  feat: checkpoint body outcomes before cumulative accounting
eb06679289765740b7fd13a06e8ffd034e59418b  feat: add idempotent body outcome accounting
9b657de42ef0bf1a3ea511b2d053470818b17437  docs: record shared side effect attempt owner
a70d15600c7bd8b361a0120e303b881b82461f3f  ci: cover shared side effect attempt owner
```

Status: **BROADER WORK DURABILITY REMAINS PARTIAL. EIGHTEEN CONCRETE CRASH/RESTART WINDOWS REMAIN CLOSED AND VERIFIED. THE DIRECT SYNCHRONOUS `side_effect_recovery` LIFECYCLE, SHARED `resident_side_effect_attempts` OWNER/PRUNING INVARIANT, AND ACTIVE BODY CUMULATIVE ACCOUNTING BOUNDARY ARE VERIFIED. BODY SUCCESS/FAILURE SEMANTIC FACTS NOW BECOME DURABLE BEFORE RETRYABLE CUMULATIVE ACCOUNTING, WITHOUT STEALING SPECIALIZED POINTER/UI COMPLETION AUTHORITY OR INVENTING LEARNING THAT THE ORIGINAL PATH DID NOT ATTEMPT.**

## 1. Durable foundations

The established durable boundaries remain:

- terminal event + exact `EventOutcome` + idle `WorkingState` publish atomically;
- Life observation is secondary and repairable without replaying a completed action;
- event-identity-safe nervous outcome perception uses receipts and keeps receipted traces dereferenceable across pruning;
- Windows canonical path identity remains consistent across investigation, Body/Terminal, Git, Work, verification and procedural learning;
- Work cancellation is atomic and bypasses failure learning because cancellation is a lifecycle/control result;
- effect-capable resident work persists durable ownership before dispatch and treats unresolved restart state as uncertainty;
- zero-model terminal failure and deterministic outer resident exceptions persist failure truth before event-idempotent accounting and terminal publication;
- structured-memory, native-investigation, external-cognition and active Body outcome paths persist semantic facts before their cumulative accounting/learning;
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

The crash-window count remains eighteen. The synchronous caller boundary, shared side-effect-attempt persistence/pruning proof, and Body accounting proof are additional lifecycle/persistence/accounting invariants, not artificial new crash-window counts.

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

The active replay-sensitive paths converge on `runtime/python/zn_agent/core/side_effect_attempts.py`:

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

The shared module owns table/index creation, connection policy, plain attempt start/read/observe/resolve queries, replay-blocking/event-attempt lookup and terminal-safe capacity pruning. `KernelStore.cancel_uncertain_event()` intentionally remains inside its one SQLite transaction rather than opening a helper connection.

The two durable signature identities intentionally remain different and regression-locked:

- Body: SHA-256 over exact JSON `{"kind": kind, "args": args}`;
- compiled capability: SHA-256 over exact JSON `{"kind": normalized_kind, "identity": identity}`.

No persisted-row rewrite or upgrade migration was introduced.

Capacity pruning may delete an attempt only after the owning event is terminal (`completed` or `failed`) and already owns a durable `event_outcomes` row. Nonterminal `observed`, `verified_effect` and `verified_absent` attempts remain protected recovery truth regardless of status. The shared schema delete guard also fails safe against older/direct generic cleanup SQL.

`tests/zn_agent/core/test_side_effect_attempt_persistence.py` locks historical identities, shared visibility and terminal-truth-gated pruning. Existing Work side-effect, observed recovery, resolution recovery, cancellation and compiled-capability recovery tests remain in the focused recovery suite.

## 5. Durable Body cumulative accounting boundary

### 5.1 Real active gap that was closed

The bounded backward audit found one active cross-cutting gap in the Body path. Ordinary Body success and several Body failure paths could update cumulative SelfModel/runtime metrics before the next semantic `WorkingState` save. A process death in that window could leave cumulative evidence durable while restart lacked the semantic checkpoint that justified it, allowing duplicate learning/accounting on re-entry.

Other audited active cumulative paths were already protected:

- structured memory: semantic completion first, event-idempotent accounting after;
- native investigation: semantic completion first, event-idempotent accounting after;
- external cognition: exact `external_completion` first, idempotent metrics/learning after;
- compiled capabilities: durable attempt + WorkingState first, idempotent success/failure accounting after;
- external kernel route accounting: stable attempt/result identity with idempotent route-quality accounting.

No second evidence-backed active cumulative accounting/learning gap was found in this bounded audit. Base resident code still contains older eager implementations for paths that the active product MRO overrides; those inactive/base implementations were not refactored merely for aesthetic uniformity.

### 5.2 Active owner and semantics

The active product chain now includes:

```text
provider_bridge.build_resident_runtime()
-> RecoveryBoundedResidentRuntime
-> DurableBodyAccountingResidentRuntime
-> CapabilityRecoveryResidentRuntime
-> focused/pointer/text completion owners
-> EmbodiedResidentRuntime
```

`DurableBodyAccountingResidentRuntime` deliberately does **not** construct Body semantic completion. It temporarily defers only cumulative writes that the inherited most-specific owner actually attempts, calls `super()` so existing pointer/UI/ordinary Body owners create and persist their own completion/failure facts, and then applies event-idempotent accounting.

This preserves important semantic differences:

- ordinary verified Body success may count one task and update native ability/knowledge evidence;
- narrow pointer `effect_probe` completion counts one task but deliberately does **not** generalize the local effect into native ability/knowledge credit;
- specialized failure/recovery paths that did not call SelfModel failure learning do not acquire invented failure evidence merely because a failure record exists.

`ResidentAccountingJournal` now exposes explicit durable Body accounting kinds:

```text
native_body_success
native_body_task
native_body_failure:<stable failure identity hash>
```

`native_body_success` is event-idempotent task + ability/knowledge accounting. `native_body_task` is event-idempotent task-only accounting. Distinct Body failure facts use a stable action-signature/evidence-fingerprint identity and update failure evidence without counting task completion.

Legacy checkpoints with no new descriptor are treated as already-accounted upgrade state, preserving compatibility with builds that used eager accounting.

### 5.3 Crash/restart proof

`tests/zn_agent/core/test_body_accounting_recovery.py` proves:

- Body success semantic `native_completion` is durable before cumulative accounting and restart finishes without Body replay or duplicate evidence;
- ordinary Body failure state is durable before failure learning and restart applies the exact failure evidence once;
- postcondition-verification failure follows the same checkpoint-first rule.

`tests/zn_agent/core/test_work_pointer_completion_recovery.py` additionally locks the specialized effect-probe boundary:

- caller text cannot replace the resident-owned `effect_probe` completion reason/scope;
- the durable accounting descriptor is `native_body_task`, not `native_body_success`;
- `tasks_total` increments exactly once;
- `computer_use` ability/knowledge evidence remain unchanged;
- restart publishes the durable completion without pointer/body replay or duplicate task accounting.

The first wrapper implementation exposed this MRO ownership regression in real focused CI; it was not hidden. The wrapper was corrected to defer cumulative writes without stealing specialized completion ownership, and the final code head passed both focused recovery and full CI.

## 6. Real Windows CI proof

Previous shared-attempt proof head `a70d15600c7bd8b361a0120e303b881b82461f3f` remains verified by:

```text
ZN Work Recovery E2E run 33117334326  success
ZN CI run 33117334321                 success
```

Exact current Body-accounting implementation/test proof head `f79d4f3c81b1d7c46dcfb55b6fc923acda77b39c`:

```text
ZN Work Recovery E2E run 33119871079                 success
  Compile Work recovery path                          success
  Verify durable Work progress and restart recovery   success
  includes Body accounting + pointer/UI recovery      success

ZN CI run 33119871129                                success
ZN Kernel / Python / Windows                         success
  Boot isolated ZN distribution without a model      success
  Compile resident core                              success
  Run ZN core tests against working tree             success
ZN Source Boundary / Windows                         success
Electron / TypeScript / Windows                      success
Publish Windows CI statuses                          success
```

No local repository test run is claimed for this web-maintainer slice. Repository self-hosted Windows CI is the verification authority.

## 7. What remains partial

Open work still includes:

- broader Work durability beyond the eighteen proven crash/restart windows and the additional verified synchronous recovery, shared-attempt persistence/pruning and Body accounting invariants;
- no deliberate outcome-trace rewrite/compactor; any future implementation must atomically retarget receipts before deleting old representation and requires separate review for destructive long-term-memory migration;
- explanatory-comment cleanup in `intentional_resident.py` remains non-behavioral debt;
- Windows continuity M8;
- browser PRESS, broader click/editing/multi-select/page lifecycle and browser capability-ledger/CI reconciliation;
- authenticated User Browser Bridge control;
- SM1+ self-maintenance.

High-risk identity, long-term memory, credential/permission, updater/signing, rollback and destructive self-maintenance changes still require human approval.

## 8. Next real target

The bounded cumulative accounting/learning audit is complete. Do not continue it indefinitely without new evidence.

Next reconcile the browser product frontier against real code and real CI before adding behavior:

1. correct stale capability-ledger entries where implemented/verified managed-browser actions outrank documentation;
2. close dedicated managed-browser CI trigger gaps so relevant browser tests reliably invoke the real Chromium lane;
3. re-evaluate the next genuinely open browser capability (`PRESS` / broader target-frame-tab lifecycle) from its real authority, provider, effect-evidence and active-caller chain rather than assuming the ledger is current;
4. after the browser checkpoint is trustworthy, choose the next broader Work/browser foundation from current code and evidence.

Preserve `outside_world_effect_uncertain` and unknown external-provider outcomes as uncertainty, not replay permission or fabricated success/failure evidence.

Keep `main` untouched during ordinary development.
