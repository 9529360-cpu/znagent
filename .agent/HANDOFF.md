# ZN Agent Handoff

Updated: 2026-08-28

## Current goal

P1 shared side-effect-attempt persistence, P2 bounded cumulative accounting/learning durability, P3 managed-browser frontier reconciliation, and the bounded P4 resident-owned live-page registry are complete and CI-verified. P5 broader Work checkpoint/restore is now **PARTIAL**: its first bounded ingress-checkpoint slice is complete and CI-verified, while general per-task restore/rollback remains open.

Broader Work durability remains **PARTIAL**. Nineteen concrete crash/restart windows are now closed and verified. The new nineteenth window covers an accepted Work task whose user message is durable but whose resident event does not yet exist; a short-lived ingress checkpoint restores the exact pending event/message/run linkage without executing it or creating replay authority. Synchronous recovery, shared side-effect-attempt persistence/pruning, Body accounting and the managed-browser page-registry proof remain additional verified lifecycle/persistence/accounting/product invariants rather than artificial crash-window counts.

Founding boundary remains:

> **ZN uses models. Models do not own ZN.**

## Branch / repository truth

- repository: `9529360-cpu/znagent`
- development branch: `dev/zn-agent`
- canonical source/release branch: `main`
- canonical `main`: `8234a835dea604783cea0bd9d28a40de654ec03d`
- P2 Body-accounting proof head: `f79d4f3c81b1d7c46dcfb55b6fc923acda77b39c`
- P3 browser reconciliation full-CI proof head: `f90610749d257d63e66dd2149d746d3ec4579535`
- P4 live-page registry implementation/proof head: `fffb0f4b84a76cef21a088167c9eb4faceb93afc`
- P5 Work ingress checkpoint implementation/proof head: `2c20b8bded96ce07c6ec43263cc77b7bd10a7a82`
- branch HEAD immediately before this HANDOFF synchronization commit: `2c20b8bded96ce07c6ec43263cc77b7bd10a7a82`
- PR #6 remains the draft development PR from `dev/zn-agent` to `main`
- `main` was not modified
- no force push or history rewrite was requested or performed

A HANDOFF commit cannot contain its own resulting SHA. Re-read `dev/zn-agent` after this file is committed and use that exact head externally.

## Completed stages

### P1 - shared side-effect-attempt persistence owner

Status: **COMPLETE / CI VERIFIED**

Active ownership remains:

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

Body and compiled-capability historical signature identities remain intentionally distinct. Capacity pruning is terminal-truth-gated and cannot remove active nonterminal recovery facts solely because attempt status is no longer `started`.

Authoritative proof remains:

```text
ZN Work Recovery E2E run 33117334326  success
ZN CI run 33117334321                 success
```

### P2 - bounded cumulative accounting/learning durability

Status: **COMPLETE / CI VERIFIED**

The bounded audit found one real active gap: Body cumulative SelfModel/runtime accounting could become durable before the semantic completion/failure checkpoint that justified it. `DurableBodyAccountingResidentRuntime` now lets the inherited most-specific completion/failure owner persist semantic truth first, then applies event-idempotent cumulative accounting.

The accounting journal distinguishes:

```text
native_body_success
native_body_task
native_body_failure:<stable failure identity hash>
```

This preserves specialized semantics. Pointer `effect_probe` completion remains task-only and cannot gain broad `computer_use` competence merely because one local visual effect was verified. Failure/recovery paths receive failure learning only when the original inherited path actually attempted it.

Authoritative proof head `f79d4f3c81b1d7c46dcfb55b6fc923acda77b39c`:

```text
ZN Work Recovery E2E run 33119871079  success
ZN CI run 33119871129                 success
```

### P3 - managed-browser frontier reconciliation

Status: **COMPLETE / CI VERIFIED**

This stage added no new browser runtime behavior. It reconciled repository truth, product capability documentation and dedicated CI coverage.

Repository truth remains:

- `SELECT_OPTION` is **VERIFIED NARROW** with current-target authority, exact-node continuity and fresh privacy-safe selected-value evidence;
- CHECK/UNCHECK are **VERIFIED NARROW** with exact-node continuity and fresh boolean post-state evidence;
- `PRESS` remains genuinely OPEN and has no managed-provider dispatch or resident-owned postcondition owner;
- no arbitrary provider return is treated as completion evidence.

Authoritative P3 proof:

```text
ZN Managed Browser E2E run 33120809421  success
ZN CI run 33120848980                   success
```

### P4 - resident-owned live-page registry

Status: **COMPLETE / CI VERIFIED NARROW**

The active call-chain audit found that Playwright `context.pages` was not reconciled into ZN state. Additional provider pages could be absent from `session.pages`, closed pages could remain counted, and the exported page ID embedded provider object identity. That made page observation truth stale before any additional mutation such as PRESS.

Commit `fffb0f4b84a76cef21a088167c9eb4faceb93afc` closes the bounded live-page registry gap:

- `_ManagedSession` owns monotonic resident `page-N` identities and explicit `default_page_id`;
- provider-created pages are discovered from `context.pages`;
- closed/disappeared pages are evicted and their stale observation/target handle is removed/disposed;
- default-page promotion is deterministic when the current default disappears;
- page IDs are not reused during the live session;
- an available provider page registry that cannot be observed fails closed;
- observation metadata now exposes current `page_ids` and `default_page_id`.

This does **not** complete popup intent/permissions, explicit tab-open/switch/close actions, frame identities, iframe stale-target handling, persistent browser-session recovery, headed browser UX, or PRESS.

Authoritative P4 proof:

```text
fffb0f4b84a76cef21a088167c9eb4faceb93afc
ZN Managed Browser E2E run 33122620361  success
ZN CI run 33122620398                   success
```

### P5 - durable Work checkpoint / restore foundation, ingress slice

Status: **PARTIAL / FIRST SLICE COMPLETE / CI VERIFIED**

The active Work ingress chain was traced as:

```text
ResidentRpcServer.work_start
-> ResidentWorkControl.start
-> RecoveryBoundedWorkLedger.start
-> Work user message
-> resident AgentEvent
-> work_runs linkage
-> WorkingState / side-effect ownership / EventOutcome
```

Existing recovery already repaired the later crash window where a resident event was durable but `work_runs` linkage was missing. The newly identified earlier window was different: `ResidentWorkLedger.start()` could persist the user message and then crash before creating the resident event. Restart then had an accepted task with no event/run truth, and the thread could accept another task.

Commit `2c20b8bded96ce07c6ec43263cc77b7bd10a7a82` adds a short-lived `work_ingress_checkpoints` owner inside `RecoveryBoundedWorkLedger`:

- exact message/event identities, task, kind, priority, payload and creation times are durable before the user message/event boundary;
- a hard restart before event persistence recreates only the exact **pending** resident event because no resident dispatch/outside-world effect has started yet;
- if the event already exists, reconciliation repairs linkage only and never creates a second event;
- message, event and WorkRun identities must agree or recovery fails closed;
- the ingress checkpoint is removed once ordinary message -> event -> `work_runs` linkage is durable;
- a redundant leftover checkpoint after durable linkage is removed idempotently on restart;
- this checkpoint is not a second execution `WorkingState` and grants no replay permission for an existing side effect.

Hard-crash proof uses `SystemExit` to bypass ordinary exception cleanup and exercise the actual restart boundary:

```text
tests/zn_agent/core/test_work_ingress_checkpoint_recovery.py
  crash after accepted Work message, before resident event persistence
  crash after resident event persistence, before WorkRun linkage
```

Authoritative P5 ingress proof head `2c20b8bded96ce07c6ec43263cc77b7bd10a7a82`:

```text
ZN Work Recovery E2E run 33124662199  success
  Compile Work recovery path            success
  Verify durable Work progress/restart  success

ZN CI run 33124662367                   success
ZN Kernel / Python / Windows            success
  Boot isolated zero-model distribution success
  Compile resident core                 success
  Run ZN core tests against working tree success
ZN Source Boundary / Windows            success
Electron / TypeScript / Windows         success
Publish Windows CI statuses             success
```

No local repository test run is claimed. Repository self-hosted Windows CI is the verification authority.

## Key recent commits

```text
f79d4f3c81b1d7c46dcfb55b6fc923acda77b39c  test: preserve effect probe accounting authority
f05b2934d1ca4bb1299b7f143bc029de5732f212  ci: trigger managed browser proof for checkbox tests
f90610749d257d63e66dd2149d746d3ec4579535  docs: reconcile managed browser verified frontier
2fe2ed7c2d53c25edebbb5c949043c37dbd9e362  docs: record managed browser frontier reconciliation
600d87e36dd4998b196a81e0aed3e5aeb3defa2c  docs: hand off managed browser frontier reconciliation
fffb0f4b84a76cef21a088167c9eb4faceb93afc  fix: reconcile managed browser page lifecycle
2c20b8bded96ce07c6ec43263cc77b7bd10a7a82  fix: recover accepted Work ingress before event creation
```

## Current risks / incomplete work

- broader Work durability remains partial beyond nineteen verified crash/restart windows plus the verified synchronous recovery, shared-attempt persistence/pruning and Body-accounting invariants;
- the new ingress checkpoint covers only task acceptance/linkage; durable per-task Work restore/rollback for workspace mutations remains OPEN;
- generic side-effect guarding currently covers commands and append-style writes, while ordinary overwrite `write_text` / `write_file` directly mutates the target and therefore deserves the next bounded restore/recovery audit;
- any overwrite-file recovery design must distinguish pre-state, intended post-state and current-world evidence and must not overwrite user/external changes merely because an old checkpoint exists;
- no deliberate outcome-trace rewrite/compactor exists; destructive long-term-memory migration remains a separate approval boundary;
- explanatory-comment cleanup in `intentional_resident.py` remains non-behavioral debt;
- browser `PRESS`, broader click/text replacement/ARIA checkbox mutation, multi-target/frame lifecycle, explicit tab/popup control, headed managed-browser UX and authenticated User Browser Bridge control remain incomplete;
- isolated parallel work remains open;
- Windows M8 continuity and SM1+ remain incomplete;
- identity, long-term memory, credentials/permissions, updater/signing, rollback and destructive self-maintenance remain high-risk approval boundaries.

## Task queue

### P1 - shared side-effect-attempt persistence owner

Status: **COMPLETE / CI VERIFIED**

### P2 - bounded cumulative accounting/learning durability audit

Status: **COMPLETE / CI VERIFIED**

### P3 - browser frontier reconciliation

Status: **COMPLETE / CI VERIFIED**

### P4 - resident-owned live-page registry

Status: **COMPLETE / CI VERIFIED NARROW**

### P5 - durable Work checkpoint / restore foundation

Status: **PARTIAL / IN PROGRESS**

Completed first slice:

1. traced Work ingress through message, event, `work_runs`, resident checkpoint/recovery and terminal truth;
2. identified the real pre-event crash gap rather than inventing another recovery store;
3. added a transient ingress checkpoint with stable message/event identities before task acceptance crosses into resident event persistence;
4. restored a missing pending event safely only while no resident execution/outside-world effect could yet have started;
5. repaired existing-event linkage without duplicate event creation;
6. added two hard-crash restart tests and dedicated workflow coverage;
7. passed focused Work Recovery E2E and full working-tree ZN CI;
8. increased the concrete verified crash/restart-window count from eighteen to nineteen.

Next bounded P5 audit:

1. trace ordinary overwrite `write_text` / `write_file` from `NativeActionIntent` through `SideEffectAwareBody`, semantic verification, Work artifact capture and restart behavior;
2. decide whether a safe resident-owned pre-write checkpoint can preserve bounded prior file state and intended post-state without becoming unconditional rollback authority;
3. require current-world identity/evidence before any restore, especially when a file changed externally after interruption;
4. add a twentieth crash/restart window only if a real overwrite/restore gap is actually closed and independently verified;
5. keep generic rollback, destructive workspace restore and broad browser expansion OPEN until evidence justifies them.

## Next real target

Re-read final branch and CI after this HANDOFF synchronization commit, then continue P5 with the overwrite-file restore/recovery call chain. Do not assume that every overwrite requires rollback: first establish exact current code ownership, existing semantic verification and conflict behavior. Keep `main` untouched during ordinary development.
