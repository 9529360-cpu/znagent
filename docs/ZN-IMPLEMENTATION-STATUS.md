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
2c20b8bded96ce07c6ec43263cc77b7bd10a7a82  fix: recover accepted Work ingress before event creation
fffb0f4b84a76cef21a088167c9eb4faceb93afc  fix: reconcile managed browser page lifecycle
f90610749d257d63e66dd2149d746d3ec4579535  docs: reconcile managed browser verified frontier
f05b2934d1ca4bb1299b7f143bc029de5732f212  ci: trigger managed browser proof for checkbox tests
f79d4f3c81b1d7c46dcfb55b6fc923acda77b39c  test: preserve effect probe accounting authority
```

Status: **BROADER WORK DURABILITY REMAINS PARTIAL. NINETEEN CONCRETE CRASH/RESTART WINDOWS ARE CLOSED AND VERIFIED. THE NEW NINETEENTH WINDOW DURABLY COVERS ACCEPTED WORK BEFORE RESIDENT EVENT CREATION WITHOUT INVENTING REPLAY AUTHORITY. THE SYNCHRONOUS RECOVERY LIFECYCLE, SHARED SIDE-EFFECT-ATTEMPT OWNER/PRUNING INVARIANT, ACTIVE BODY CUMULATIVE ACCOUNTING BOUNDARY, MANAGED-BROWSER MUTATION FRONTIER, AND A NARROW RESIDENT-OWNED LIVE-PAGE REGISTRY LIFECYCLE ARE ALSO VERIFIED BY REAL WINDOWS CI/E2E. GENERAL PER-TASK RESTORE/ROLLBACK, FRAME/TAB CONTROL AND PRESS REMAIN OPEN.**

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
- capacity pruning can remove only attempts whose owning event has both terminal event state and a durable `EventOutcome`; nonterminal recovery truth is retained regardless of attempt status;
- Work ingress now owns a short-lived pre-event checkpoint so an accepted user task cannot disappear between durable message persistence and resident-event creation.

Generic nervous `perceive()` remains intentionally plastic and is not an exactly-once API.

## 2. Nineteen proven broader Work crash/restart windows

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
18. crash after provider dispatch but before a returned result becomes explicit unknown-provider-outcome uncertainty: provider replay is blocked and no route learning or improvement proposal is invented from the unknown result;
19. an accepted Work user message can survive a hard crash before resident-event persistence: restart reconstructs the exact preallocated **pending** event and `work_runs` linkage without executing the event, duplicating the user message, or granting replay authority. The adjacent crash after event persistence but before `work_runs` persistence is also regression-locked against duplicate event creation.

The crash-window count is now nineteen. The synchronous caller boundary, shared side-effect-attempt persistence/pruning proof, Body-accounting proof and browser lifecycle/product proofs are additional lifecycle/persistence/accounting/product-evidence invariants, not artificial new crash-window counts.

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

## 6. Managed-browser verified frontier and page lifecycle

### 6.1 P3 frontier reconciliation

P3 changed no browser runtime behavior. It reconciled the product ledger and dedicated CI trigger against already-existing code and provider evidence.

Repository truth remains:

- native `SELECT_OPTION` is implemented and **VERIFIED NARROW**;
- active chain is `BrowserActionKind.SELECT_OPTION` -> `PlaywrightManagedBrowser.act()` -> `managed_browser_select.perform_select_option`;
- native CHECK/UNCHECK remain **VERIFIED NARROW** with exact-node and fresh boolean state evidence;
- `PRESS` remains genuinely OPEN: it exists in the typed action/permission contract, but managed-provider dispatch/postcondition ownership is not implemented;
- no arbitrary provider method is completion authority.

### 6.2 P4 resident-owned live-page registry

The call-chain audit showed that `session.pages` previously contained only pages explicitly registered by ZN. Playwright-created additional pages were absent from ZN observation truth, closed pages could remain counted, and default-page selection was only the first dictionary key. That made `page_count` and page availability potentially stale before adding any further side-effect action.

Commit `fffb0f4b84a76cef21a088167c9eb4faceb93afc` implements a bounded page-registry lifecycle slice:

- `_ManagedSession` owns a monotonic `next_page_sequence` and explicit `default_page_id`;
- exported page IDs are resident-owned `page-N` identities rather than Python provider object addresses;
- reconciliation observes Playwright `context.pages`, registers newly live pages, evicts closed/disappeared pages, and fails closed when an available provider registry cannot be read;
- page eviction disposes the page target binding and removes stale `last_observation` state;
- if the default page disappears, the next still-live resident page becomes default deterministically;
- evicted page IDs are not reused in the same live session;
- observation metadata exposes `page_ids` and `default_page_id` in addition to current `page_count`.

This is **VERIFIED NARROW page-registry lifecycle**, not complete tab/popup/frame ownership. It does not add popup intent/permission semantics, explicit tab-open/switch/close actions, child-frame identities, iframe target authority, persistent browser-session recovery, or PRESS.

`tests/zn_agent/core/test_managed_browser_pages.py` covers provider-page discovery, stable IDs, default-page promotion, target-handle cleanup and fail-closed provider registry observation. `tests/zn_agent/e2e/test_windows_managed_browser_pages.py` verifies new-page discovery, closed-page eviction/default promotion and non-reuse against real local Chromium. The dedicated workflow trigger includes both test files.

## 7. P5 Work ingress checkpoint foundation

### 7.1 Real active gap that was closed

The active Work ingress chain is:

```text
ResidentRpcServer.work_start
-> ResidentWorkControl.start
-> RecoveryBoundedWorkLedger.start
-> durable Work user message
-> resident AgentEvent
-> durable work_runs linkage
-> resident WorkingState / side-effect ownership / EventOutcome
```

Before P5, recovery covered the later event -> `work_runs` crash window but not the earlier message -> event window. A process death after the accepted user message committed but before `resident.enqueue()` persisted an event left an accepted task with no resident event/run identity. Restart could not reconstruct it and the same Work thread could accept another task.

### 7.2 Bounded owner and semantics

Commit `2c20b8bded96ce07c6ec43263cc77b7bd10a7a82` adds `work_ingress_checkpoints` inside the active `RecoveryBoundedWorkLedger` rather than creating another resident execution checkpoint.

Before message/event dispatch, the short-lived checkpoint stores only the exact ingress identity needed to reconstruct linkage: preallocated `event_id`, `message_id`, thread/task, normalized kind/priority, event payload and creation timestamps.

Restart reconciliation:

- verifies thread/message/event identities agree or fails closed;
- creates the missing user message only if the exact message identity is absent;
- creates the missing resident event only when that exact event does not exist, and creates it as **pending** with zero attempts;
- if the event already exists, never creates a duplicate and only repairs missing WorkRun linkage;
- removes the ingress checkpoint only after message + event + WorkRun truth agree durably;
- removes a redundant leftover checkpoint idempotently after already-durable linkage.

This is safe specifically because the recoverable pre-event window ends before the resident can claim or execute the event. It does not replay an action, restore an unknown external effect, or override `WorkingState`/side-effect-attempt truth. Once an event may have executed, the existing resident recovery and uncertainty owners remain authoritative.

### 7.3 Hard-crash proof

`tests/zn_agent/core/test_work_ingress_checkpoint_recovery.py` uses `SystemExit` so ordinary exception cleanup cannot hide the crash window. It proves:

- hard exit after checkpoint + user message but before resident event persistence -> restart reconstructs the same pending event and active WorkRun, keeps exactly one user message and does not execute the task;
- hard exit after resident event persistence but before WorkRun persistence -> restart keeps exactly one resident event and repairs the linkage;
- checkpoint rows disappear after durable reconciliation;
- the repaired thread refuses a second active Work start.

The focused recovery workflow explicitly includes the new test path/module.

P5 remains **PARTIAL**. This slice does not provide arbitrary workspace rollback, historical file snapshots, external side-effect undo, parallel task isolation or generic user-visible restore points.

## 8. Real Windows CI proof

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

P3 browser frontier reconciliation proof remains:

```text
ZN Managed Browser E2E run 33120809421  success
ZN CI run 33120848980                   success
```

P4 live-page registry proof head `fffb0f4b84a76cef21a088167c9eb4faceb93afc`:

```text
ZN Managed Browser E2E run 33122620361                success
  Prepare isolated browser runtime                    success
  Run managed browser contract tests                  success
  Run real local Chromium E2E                         success

ZN CI run 33122620398                                  success
ZN Kernel / Python / Windows                           success
  Boot isolated ZN distribution without a model       success
  Compile resident core                               success
  Run ZN core tests against working tree              success
ZN Source Boundary / Windows                           success
Electron / TypeScript / Windows                        success
Publish Windows CI statuses                            success
```

P5 Work ingress checkpoint proof head `2c20b8bded96ce07c6ec43263cc77b7bd10a7a82`:

```text
ZN Work Recovery E2E run 33124662199                  success
  Compile Work recovery path                          success
  Verify durable Work progress and restart recovery  success

ZN CI run 33124662367                                  success
ZN Kernel / Python / Windows                           success
  Boot isolated ZN distribution without a model       success
  Compile resident core                               success
  Run ZN core tests against working tree              success
ZN Source Boundary / Windows                           success
Electron / TypeScript / Windows                        success
Publish Windows CI statuses                            success
```

Historical action-specific browser proof remains useful background evidence: SELECT_OPTION had dedicated real-Chromium success in run `33001748123`; CHECK/UNCHECK had real-Chromium success including run `32979312465`.

No local repository test run is claimed for these web-maintainer slices. Repository self-hosted Windows CI is the verification authority.

## 9. What remains partial

Open work still includes:

- broader Work durability beyond the nineteen proven crash/restart windows and the additional verified synchronous recovery, shared-attempt persistence/pruning and Body-accounting invariants;
- durable per-task Work checkpoints / restore / rollback beyond the new ingress checkpoint remain OPEN/PARTIAL;
- the active generic side-effect guard covers commands and append-style writes, while ordinary overwrite `write_text` / `write_file` still directly mutates the target and is the next bounded restore/recovery audit candidate;
- any file restore design must prove current-world identity/conflict state before mutation and must not overwrite external/user changes merely because a stale checkpoint exists;
- no deliberate outcome-trace rewrite/compactor; any future implementation must atomically retarget receipts before deleting old representation and requires separate review for destructive long-term-memory migration;
- explanatory-comment cleanup in `intentional_resident.py` remains non-behavioral debt;
- Windows continuity M8;
- browser `PRESS`, broader click/text replacement/ARIA checkbox mutation, multi-target/frame lifecycle, explicit tab/popup control, headed managed browser and browser-session UX;
- authenticated User Browser Bridge control;
- SM1+ self-maintenance.

High-risk identity, long-term memory, credential/permission, updater/signing, rollback and destructive self-maintenance changes still require human approval.

## 10. Next real target

P1 shared-attempt persistence, P2 bounded cumulative accounting/learning durability, P3 browser frontier reconciliation, and the bounded P4 resident-owned live-page registry are complete and CI-verified. P5 is now in progress with the first accepted-Work ingress checkpoint slice verified. Do not inflate this into general task restore.

Continue P5 from the next real mutation boundary:

1. trace ordinary overwrite `write_text` / `write_file` from `NativeActionIntent` through `SideEffectAwareBody`, semantic postcondition verification, Work artifact capture and restart behavior;
2. determine whether the resident needs a bounded pre-write checkpoint containing prior-state evidence plus intended post-state identity, rather than a generic workspace snapshot;
3. before any restore mutation, require fresh current-world evidence that distinguishes “intended write happened”, “write did not happen”, and “file changed independently”; a stale checkpoint must never be unconditional overwrite authority;
4. reuse `WorkingState`, current side-effect-attempt semantics, Body read evidence and Work ownership where possible instead of adding a competing recovery plane;
5. count a twentieth crash/restart window only if implementation really closes a distinct overwrite/restore interruption and real CI proves it;
6. keep PRESS, explicit tab/popup control and frame identity OPEN until dependency evidence makes browser work higher leverage again.

Preserve `outside_world_effect_uncertain` and unknown external-provider outcomes as uncertainty, not replay permission or fabricated success/failure evidence.

Keep `main` untouched during ordinary development.
