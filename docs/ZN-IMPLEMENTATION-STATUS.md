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

Exact newest implementation/CI checkpoint before this documentation synchronization:

```text
f90610749d257d63e66dd2149d746d3ec4579535  docs: reconcile managed browser verified frontier
f05b2934d1ca4bb1299b7f143bc029de5732f212  ci: trigger managed browser proof for checkbox tests
f79d4f3c81b1d7c46dcfb55b6fc923acda77b39c  test: preserve effect probe accounting authority
d0e6c3bde9f50274a9ad4c31fac6a042364c8f7f  fix: defer body accounting without stealing completion ownership
d615241dc7fb0f95be1aa524ab2d27cf1bf1804b  fix: preserve body accounting semantics after checkpoints
```

Status: **BROADER WORK DURABILITY REMAINS PARTIAL. EIGHTEEN CONCRETE CRASH/RESTART WINDOWS REMAIN CLOSED AND VERIFIED. THE SYNCHRONOUS RECOVERY LIFECYCLE, SHARED SIDE-EFFECT-ATTEMPT OWNER/PRUNING INVARIANT, ACTIVE BODY CUMULATIVE ACCOUNTING BOUNDARY, AND CURRENT MANAGED-BROWSER VERIFIED FRONTIER/CI COVERAGE ARE NOW RECONCILED WITH REAL CODE AND REAL WINDOWS EVIDENCE.**

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
- replay-sensitive Body and compiled-capability attempts use one shared low-level SQLite owner while retaining intentionally different historical signature identities;
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

The crash-window count remains eighteen. The synchronous caller boundary, shared side-effect-attempt persistence/pruning proof, Body-accounting proof and browser frontier reconciliation are additional lifecycle/persistence/accounting/product-evidence invariants, not artificial new crash-window counts.

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

## 5. Durable Body cumulative accounting boundary

### 5.1 Real active gap that was closed

The bounded backward audit found one active cross-cutting gap in the Body path. Ordinary Body success and several Body failure paths could update cumulative SelfModel/runtime metrics before the next semantic `WorkingState` save. A process death in that window could leave cumulative evidence durable while restart lacked the semantic checkpoint that justified it, allowing duplicate learning/accounting on re-entry.

Other audited active cumulative paths were already protected: structured memory, native investigation, external cognition, compiled capability success/failure, and external kernel route accounting. No second evidence-backed active cumulative accounting/learning gap was found. Older eager base implementations that the active product MRO overrides were not refactored merely for aesthetic uniformity.

### 5.2 Active owner and semantics

The active product chain includes:

```text
provider_bridge.build_resident_runtime()
-> RecoveryBoundedResidentRuntime
-> DurableBodyAccountingResidentRuntime
-> CapabilityRecoveryResidentRuntime
-> focused/pointer/text completion owners
-> EmbodiedResidentRuntime
```

`DurableBodyAccountingResidentRuntime` does not construct Body semantic completion. It temporarily defers only cumulative writes that the inherited most-specific owner actually attempts, delegates to `super()`, then applies event-idempotent accounting after semantic truth is durable.

`ResidentAccountingJournal` distinguishes:

```text
native_body_success
native_body_task
native_body_failure:<stable failure identity hash>
```

Ordinary verified Body success may count one task and update native ability/knowledge evidence. Narrow pointer `effect_probe` completion counts one task but deliberately does not generalize the local visual effect into broad native ability/knowledge credit. Specialized failure/recovery paths that did not attempt SelfModel failure learning do not acquire invented failure evidence.

### 5.3 Crash/restart proof

`tests/zn_agent/core/test_body_accounting_recovery.py` proves success, ordinary failure and postcondition-verification failure checkpoint-first behavior. `tests/zn_agent/core/test_work_pointer_completion_recovery.py` locks the specialized effect-probe owner, task-only descriptor and restart idempotence.

The first wrapper exposed a real pointer completion ownership regression in focused CI. It was fixed rather than hidden; only the later green proof head is authoritative.

## 6. Managed-browser frontier reconciliation

This stage changed no browser runtime behavior. It reconciled the product ledger and dedicated CI trigger against already-existing code and provider evidence.

Repository truth now recorded in `docs/ZN-PRODUCT-CAPABILITY-MAP.md`:

- native `SELECT_OPTION` is already implemented and is **VERIFIED NARROW**, not OPEN;
- active chain is `BrowserActionKind.SELECT_OPTION` -> `PlaywrightManagedBrowser.act()` -> `managed_browser_select.perform_select_option`;
- the mutation is limited to an enabled single-select native combobox with one explicit bounded string value, current target authority, exact-node continuity and fresh privacy-safe selected-value evidence;
- already-selected, multi-select, replacement and no-change cases fail closed, and raw requested value is not persisted;
- native CHECK/UNCHECK remain **VERIFIED NARROW** with exact-node and fresh boolean state evidence;
- `PRESS` remains genuinely OPEN: it exists in the typed action/permission contract, but managed-provider dispatch/postcondition ownership is not implemented.

The dedicated browser workflow already dynamically executed `test_managed_browser_check.py`, but that test file was absent from `push.paths`. Commit `f05b2934d1ca4bb1299b7f143bc029de5732f212` adds the missing trigger so changes limited to the checkbox contract tests invoke the real Chromium proof lane.

No arbitrary provider method was added. Any future `PRESS` implementation must first define a bounded resident-owned authority and independently observable effect; provider `press()` return alone is not completion truth.

## 7. Real Windows CI proof

Shared-attempt proof head `a70d15600c7bd8b361a0120e303b881b82461f3f` remains verified by:

```text
ZN Work Recovery E2E run 33117334326  success
ZN CI run 33117334321                 success
```

Body-accounting proof head `f79d4f3c81b1d7c46dcfb55b6fc923acda77b39c` remains verified by:

```text
ZN Work Recovery E2E run 33119871079  success
ZN CI run 33119871129                 success
```

Current browser frontier reconciliation proof:

```text
f05b2934d1ca4bb1299b7f143bc029de5732f212
ZN Managed Browser E2E run 33120809421                success
  Prepare isolated browser runtime                    success
  Run managed browser contract tests                  success
  Run real local Chromium E2E                         success

f90610749d257d63e66dd2149d746d3ec4579535
ZN CI run 33120848980                                  success
ZN Kernel / Python / Windows                           success
  Boot isolated ZN distribution without a model       success
  Compile resident core                               success
  Run ZN core tests against working tree              success
ZN Source Boundary / Windows                           success
Electron / TypeScript / Windows                        success
Publish Windows CI statuses                            success
```

Historical action-specific browser proof remains useful background evidence: SELECT_OPTION had dedicated real-Chromium success in run `33001748123`; CHECK/UNCHECK had real-Chromium success including run `32979312465`. Current run `33120809421` revalidates the present managed-browser working tree after the trigger repair.

No local repository test run is claimed for this web-maintainer slice. Repository self-hosted Windows CI is the verification authority.

## 8. What remains partial

Open work still includes:

- broader Work durability beyond the eighteen proven crash/restart windows and the additional verified synchronous recovery, shared-attempt persistence/pruning and Body-accounting invariants;
- no deliberate outcome-trace rewrite/compactor; any future implementation must atomically retarget receipts before deleting old representation and requires separate review for destructive long-term-memory migration;
- explanatory-comment cleanup in `intentional_resident.py` remains non-behavioral debt;
- Windows continuity M8;
- browser `PRESS`, broader click/text replacement/ARIA checkbox mutation, multi-target/frame/tab/page lifecycle, headed managed browser and browser-session UX;
- authenticated User Browser Bridge control;
- SM1+ self-maintenance.

High-risk identity, long-term memory, credential/permission, updater/signing, rollback and destructive self-maintenance changes still require human approval.

## 9. Next real target

P1 shared-attempt persistence, P2 bounded cumulative accounting/learning durability, and P3 browser frontier reconciliation are complete and CI-verified. Do not continue any of those audits indefinitely without new evidence.

Next reassess the genuinely open managed-browser frontier from the real call chain:

1. compare `PRESS` against broader target/frame/tab lifecycle value and dependencies rather than implementing the thinnest enum member automatically;
2. if `PRESS` is chosen, define exact key vocabulary, authority scope, replay/side-effect lifecycle and independent postcondition before provider dispatch;
3. if target/frame/tab lifecycle is the higher-leverage prerequisite, establish stable page/frame identities and stale-target handling first;
4. after that bounded browser checkpoint, return to the highest-leverage broader Work/checkpoint/restore foundation from current repository truth.

Preserve `outside_world_effect_uncertain` and unknown external-provider outcomes as uncertainty, not replay permission or fabricated success/failure evidence.

Keep `main` untouched during ordinary development.
