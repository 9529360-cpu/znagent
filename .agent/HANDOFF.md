# ZN Agent Handoff

Updated: 2026-08-28

## Current goal

P1 shared side-effect-attempt persistence, P2 bounded cumulative accounting/learning durability, and P3 managed-browser frontier reconciliation are complete and CI-verified. The next real target is to choose the highest-leverage genuinely open browser foundation from current code: `PRESS` versus broader target/frame/tab lifecycle, with resident-owned authority and independent effect evidence defined before any new provider mutation.

Broader Work durability remains **PARTIAL**. The concrete crash/restart-window count remains eighteen; synchronous recovery, shared side-effect-attempt persistence/pruning, and Body accounting are additional verified lifecycle/persistence/accounting invariants rather than artificial new window counts.

Founding boundary remains:

> **ZN uses models. Models do not own ZN.**

## Branch / repository truth

- repository: `9529360-cpu/znagent`
- development branch: `dev/zn-agent`
- canonical source/release branch: `main`
- canonical `main`: `8234a835dea604783cea0bd9d28a40de654ec03d`
- P2 Body-accounting proof head: `f79d4f3c81b1d7c46dcfb55b6fc923acda77b39c`
- P3 browser reconciliation full-CI proof head: `f90610749d257d63e66dd2149d746d3ec4579535`
- branch HEAD immediately before this HANDOFF synchronization commit: `2fe2ed7c2d53c25edebbb5c949043c37dbd9e362`
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
-> shared schema delete guard
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

Other active cumulative paths were traced and did not expose a second evidence-backed gap: structured memory, native investigation, external cognition, compiled capability success/failure and external kernel route accounting were already semantic-checkpoint-first/idempotent.

Authoritative proof head `f79d4f3c81b1d7c46dcfb55b6fc923acda77b39c`:

```text
ZN Work Recovery E2E run 33119871079  success
ZN CI run 33119871129                 success
```

The earlier first wrapper did fail focused CI by stealing pointer completion ownership. That failure was real and fixed; it is not proof.

### P3 - managed-browser frontier reconciliation

Status: **COMPLETE / CI VERIFIED**

This stage added no new browser runtime behavior. It reconciled repository truth, product capability documentation and dedicated CI coverage.

Repository truth:

- `SELECT_OPTION` already exists through `BrowserActionKind.SELECT_OPTION` -> `PlaywrightManagedBrowser.act()` -> `managed_browser_select.perform_select_option`;
- it is now correctly recorded as **VERIFIED NARROW**, not OPEN;
- its current contract is limited to an enabled single-select native combobox, one explicit bounded string value, current target authority, exact-node continuity and fresh privacy-safe selected-value evidence;
- already-selected, multi-select, replacement and no-change cases fail closed; raw requested value is not persisted;
- CHECK/UNCHECK remain **VERIFIED NARROW** with exact-node continuity and fresh boolean post-state evidence;
- `PRESS` remains genuinely OPEN: it is present in the typed action/permission contract but has no managed-provider dispatch or resident-owned postcondition owner.

CI reliability fix:

- `.github/workflows/zn-managed-browser-e2e.yml` dynamically ran `test_managed_browser_check.py` but omitted it from `push.paths`;
- `f05b2934d1ca4bb1299b7f143bc029de5732f212` adds the missing trigger so checkbox-contract-only changes invoke the real Chromium lane.

Capability ledger reconciliation:

- `f90610749d257d63e66dd2149d746d3ec4579535` updates `docs/ZN-PRODUCT-CAPABILITY-MAP.md` to current implementation/evidence truth;
- PRESS / broader click, text replacement and ARIA checkbox mutation remain OPEN rather than being implied by provider capability.

Authoritative P3 proof:

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

Historical action-specific browser evidence remains useful background proof: SELECT_OPTION real-Chromium run `33001748123` succeeded; CHECK/UNCHECK real-Chromium proof includes run `32979312465`. Current run `33120809421` revalidates the present managed-browser working tree after the trigger repair.

No local repository test run is claimed for these stages. Repository self-hosted Windows CI is the verification authority.

## Key recent commits

```text
eb06679289765740b7fd13a06e8ffd034e59418b  feat: add idempotent body outcome accounting
3020604e70762dc9f461fb85555d1c507523c0e2  feat: checkpoint body outcomes before cumulative accounting
04e07a777eb13c5bdbe82a6c651be9d7b344c287  refactor: activate durable body accounting boundary
c8fec59fdc442da67829ea0a4e299e6c800c7533  test: prove body accounting follows durable semantic truth
7a420f67efd58dfe55d04c173a15adeabaeb1c83  ci: cover durable body accounting recovery
d615241dc7fb0f95be1aa524ab2d27cf1bf1804b  fix: preserve body accounting semantics after checkpoints
d0e6c3bde9f50274a9ad4c31fac6a042364c8f7f  fix: defer body accounting without stealing completion ownership
f79d4f3c81b1d7c46dcfb55b6fc923acda77b39c  test: preserve effect probe accounting authority
4f971458508daf2bdead2856fa821fae894c0abd  docs: record durable body accounting boundary
e9f6ec0fc34602fc658360272616aadd099d830d  docs: hand off durable body accounting boundary
f05b2934d1ca4bb1299b7f143bc029de5732f212  ci: trigger managed browser proof for checkbox tests
f90610749d257d63e66dd2149d746d3ec4579535  docs: reconcile managed browser verified frontier
2fe2ed7c2d53c25edebbb5c949043c37dbd9e362  docs: record managed browser frontier reconciliation
```

## Current risks / incomplete work

- broader Work durability remains partial beyond eighteen verified crash/restart windows plus the verified synchronous recovery, shared-attempt persistence/pruning and Body-accounting invariants;
- no deliberate outcome-trace rewrite/compactor exists; destructive long-term-memory migration remains a separate approval boundary;
- explanatory-comment cleanup in `intentional_resident.py` remains non-behavioral debt;
- browser `PRESS`, broader click/text replacement/ARIA checkbox mutation, stable multi-target/frame/tab/page lifecycle, headed managed-browser UX and authenticated User Browser Bridge control remain incomplete;
- broader Work checkpoint/restore and isolated parallel work remain open;
- Windows M8 continuity and SM1+ remain incomplete;
- identity, long-term memory, credentials/permissions, updater/signing, rollback and destructive self-maintenance remain high-risk approval boundaries.

## Task queue

### P1 - shared side-effect-attempt persistence owner

Status: **COMPLETE / CI VERIFIED**

### P2 - bounded cumulative accounting/learning durability audit

Status: **COMPLETE / CI VERIFIED**

### P3 - browser frontier reconciliation

Status: **COMPLETE / CI VERIFIED**

Completed contract:

1. reconciled capability ledger to already-implemented/verified SELECT_OPTION;
2. kept CHECK/UNCHECK truth aligned with current real Chromium evidence;
3. repaired dedicated E2E path trigger for checkbox contract tests;
4. ran the real managed Chromium workflow successfully;
5. ran full working-tree ZN CI successfully;
6. added no new provider mutation and kept PRESS explicitly OPEN.

### P4 - next browser/product foundation

Status: **OPEN / NEXT**

1. trace the active `PRESS` contract/provider/effect path and the current target/frame/tab lifecycle together;
2. choose by leverage/dependency rather than by enum order;
3. if PRESS is chosen, define exact key vocabulary, authority, replay/uncertainty behavior and independent postcondition before provider dispatch;
4. if stable page/frame identities are prerequisite, implement that lifecycle first;
5. after the bounded browser checkpoint, return to the highest-leverage broader Work/checkpoint/restore foundation from current repository truth.

## Next real target

Re-read final branch/CI after this HANDOFF commit, update PR #6 with P3 completion proof, then begin P4 from the real current call chain. Keep `main` untouched during ordinary development.
