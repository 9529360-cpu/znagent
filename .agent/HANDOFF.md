# ZN Agent Handoff

Updated: 2026-08-28

## Current goal

P1 shared side-effect-attempt persistence, P2 bounded cumulative accounting/learning durability, P3 managed-browser frontier reconciliation, and the bounded P4 resident-owned live-page registry are complete and CI-verified. The next real target is the higher-leverage broader Work checkpoint/restore foundation from the active resident call chain, not arbitrary browser action expansion.

Broader Work durability remains **PARTIAL**. The concrete crash/restart-window count remains eighteen; synchronous recovery, shared side-effect-attempt persistence/pruning, Body accounting and the managed-browser page-registry proof are additional verified lifecycle/persistence/accounting/product invariants rather than artificial new crash-window counts.

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
- branch HEAD immediately before this HANDOFF synchronization commit: `fffb0f4b84a76cef21a088167c9eb4faceb93afc`
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

Proof files:

```text
tests/zn_agent/core/test_managed_browser_pages.py
tests/zn_agent/e2e/test_windows_managed_browser_pages.py
.github/workflows/zn-managed-browser-e2e.yml
```

Authoritative P4 proof:

```text
fffb0f4b84a76cef21a088167c9eb4faceb93afc
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

No local repository test run is claimed for P4. Repository self-hosted Windows CI is the verification authority.

## Key recent commits

```text
f79d4f3c81b1d7c46dcfb55b6fc923acda77b39c  test: preserve effect probe accounting authority
f05b2934d1ca4bb1299b7f143bc029de5732f212  ci: trigger managed browser proof for checkbox tests
f90610749d257d63e66dd2149d746d3ec4579535  docs: reconcile managed browser verified frontier
2fe2ed7c2d53c25edebbb5c949043c37dbd9e362  docs: record managed browser frontier reconciliation
600d87e36dd4998b196a81e0aed3e5aeb3defa2c  docs: hand off managed browser frontier reconciliation
fffb0f4b84a76cef21a088167c9eb4faceb93afc  fix: reconcile managed browser page lifecycle
```

## Current risks / incomplete work

- broader Work durability remains partial beyond eighteen verified crash/restart windows plus the verified synchronous recovery, shared-attempt persistence/pruning and Body-accounting invariants;
- durable per-task Work checkpoint/restore/rollback remains OPEN and is the next major foundation;
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

Completed contract:

1. traced PRESS and page lifecycle through the real managed-browser call chain rather than enum order;
2. chose page observation/lifecycle correctness as the prerequisite because current `session.pages` could be stale;
3. introduced stable resident page IDs, live provider reconciliation, closed-page eviction, stale target cleanup and deterministic default promotion;
4. added focused contract tests and real local Chromium E2E;
5. repaired dedicated browser workflow path coverage for the new tests;
6. ran the dedicated managed Chromium workflow successfully;
7. ran full working-tree ZN CI successfully;
8. kept PRESS, frame identity and explicit tab/popup mutation OPEN.

### P5 - durable Work checkpoint / restore foundation

Status: **OPEN / NEXT**

1. trace the active Work ingress -> durable owner -> WorkingState/checkpoint -> side-effect ownership -> recovery -> terminal publication call chain;
2. identify the smallest resident-owned per-task checkpoint/restore contract that adds useful restart continuity without replaying unknown outside-world effects;
3. reuse existing semantic checkpoints, `EventOutcome`, `ResidentSideEffectJournal`/shared attempt truth and recovery decisions rather than introducing a competing persistence owner;
4. add a concrete crash/restart proof only if a real new window is closed; keep the existing count at eighteen otherwise;
5. after the bounded Work slice, reassess next leverage from real code/CI rather than returning automatically to PRESS.

## Next real target

Re-read final branch and CI after this HANDOFF synchronization commit, then begin P5 from the real active Work/checkpoint/restore call chain. Keep `main` untouched during ordinary development.
