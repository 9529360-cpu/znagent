# ZN Agent Handoff

Updated: 2026-08-28

## Current goal

The bounded cumulative accounting/learning durability audit is complete and CI-verified. The next real target is to reconcile the browser product frontier against current code and real provider evidence before adding new behavior.

The newest completed slice closes the active Body crash window where cumulative SelfModel/runtime accounting could become durable before the semantic Body completion/failure checkpoint that justified it. Active Body cumulative writes are now deferred until the inherited most-specific completion/failure owner has persisted semantic truth, then applied through event-idempotent accounting.

This wrapper does not own pointer/UI completion policy. Narrow `effect_probe` pointer completion remains task-only and does not acquire invented native ability/knowledge credit. Specialized failure/recovery paths receive failure learning only when the original inherited path actually attempted that learning.

Broader Work durability remains **PARTIAL**. The concrete crash/restart-window count remains eighteen; synchronous recovery, shared side-effect-attempt persistence/pruning, and Body accounting are additional verified lifecycle/persistence/accounting invariants rather than artificial new window counts.

Founding boundary remains:

> **ZN uses models. Models do not own ZN.**

## Branch / repository truth

- repository: `9529360-cpu/znagent`
- development branch: `dev/zn-agent`
- canonical source/release branch: `main`
- canonical `main`: `8234a835dea604783cea0bd9d28a40de654ec03d`
- exact Body-accounting implementation/test/CI proof head: `f79d4f3c81b1d7c46dcfb55b6fc923acda77b39c`
- branch HEAD immediately before this HANDOFF synchronization commit: `4f971458508daf2bdead2856fa821fae894c0abd`
- PR #6 remains the draft development PR from `dev/zn-agent` to `main`
- `main` was not modified
- no force push or history rewrite was requested or performed

A HANDOFF commit cannot contain its own resulting SHA. Re-read `dev/zn-agent` after this file is committed and use that exact head externally.

## Completed in this stage

### P1 remains complete: shared side-effect-attempt persistence owner

The previously completed active ownership remains:

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

Body and compiled capability historical signature identities remain intentionally distinct. Capacity pruning remains terminal-truth-gated and cannot remove active nonterminal recovery facts solely because their attempt status is no longer `started`.

### P2 complete: durable Body cumulative accounting

The bounded backward audit found one real active gap:

```text
Body semantic outcome
-> cumulative SelfModel / runtime accounting
-> next WorkingState save
```

The old order allowed a crash after cumulative evidence committed but before the semantic checkpoint. Restart could then repeat cumulative learning/accounting because the durable state did not yet explain what had already happened.

The active chain now includes:

```text
provider_bridge.build_resident_runtime()
-> RecoveryBoundedResidentRuntime
-> DurableBodyAccountingResidentRuntime
-> CapabilityRecoveryResidentRuntime
-> focused/pointer/text completion owners
-> EmbodiedResidentRuntime
```

`DurableBodyAccountingResidentRuntime` does not construct semantic completion. It temporarily intercepts only cumulative writes that the inherited path actually attempts, delegates to `super()` so the existing most-specific owner builds/persists completion or failure truth, and applies idempotent accounting afterward.

The accounting journal now distinguishes:

```text
native_body_success
native_body_task
native_body_failure:<stable failure identity hash>
```

- `native_body_success`: one task + native ability/knowledge evidence, event-idempotent;
- `native_body_task`: one task only, event-idempotent;
- distinct Body failure identity: failure evidence only, idempotent, no task-completion count.

This preserves specialized semantics. The pointer `effect_probe` completion still owns its exact completion reason/scope and uses task-only accounting; it does not generalize a local visual effect into broad `computer_use` competence. Likewise, a specialized failure/recovery path that did not call SelfModel failure learning does not receive invented failure evidence.

Legacy checkpoints without a new Body accounting descriptor are treated as already-accounted upgrade state, matching the prior eager-accounting behavior rather than double-counting during upgrade.

### Bounded audit conclusion

Other active cumulative paths were traced and did not expose a second evidence-backed gap:

- structured memory -> semantic completion first -> idempotent accounting;
- native investigation -> semantic completion first -> idempotent accounting;
- external cognition -> exact `external_completion` first -> idempotent metrics/learning;
- compiled capability success/failure -> durable attempt + WorkingState first -> idempotent resident accounting;
- external kernel route learning -> stable attempt/result identity -> idempotent route-quality accounting.

Older eager implementations remain in base resident code where active product subclasses override them. They were not refactored solely for uniformity because current active-call evidence did not justify expanding this stage.

The bounded accounting audit is therefore closed. Do not continue auditing this category indefinitely without new evidence.

## Key commits

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
```

Related files:

```text
runtime/python/zn_agent/core/resident_accounting.py
runtime/python/zn_agent/core/durable_body_accounting_resident.py
runtime/python/zn_agent/core/provider_bridge.py
tests/zn_agent/core/test_body_accounting_recovery.py
tests/zn_agent/core/test_work_pointer_completion_recovery.py
.github/workflows/zn-work-recovery-e2e.yml
docs/ZN-IMPLEMENTATION-STATUS.md
```

## Real test / CI truth

Exact P2 implementation/test proof head `f79d4f3c81b1d7c46dcfb55b6fc923acda77b39c`:

```text
ZN Work Recovery E2E run 33119871079                 success
Windows resident Work restart recovery                success
Compile Work recovery path                            success
Verify durable Work progress and restart recovery     success
  Body accounting restart regressions                 success
  existing pointer/UI recovery regressions            success

ZN CI run 33119871129                                success
ZN Kernel / Python / Windows                         success
  Boot isolated ZN distribution without a model       success
  Compile resident core                              success
  Run ZN core tests against working tree             success
ZN Source Boundary / Windows                         success
Electron / TypeScript / Windows                      success
Publish Windows CI statuses                          success
```

The earlier first wrapper version did fail focused CI by stealing the pointer completion owner. That failure was real and was fixed; it is not proof. Only the final successful heads/runs above are authoritative for P2.

No local repository test run is claimed for this stage. Repository self-hosted Windows CI is the verification authority.

## Browser frontier facts already established by read-only reconciliation

The product capability ledger is stale relative to current code and CI:

- `SELECT_OPTION` is already implemented through `BrowserActionKind.SELECT_OPTION` -> `PlaywrightManagedBrowser.act()` -> `managed_browser_select.py`;
- dedicated native-select unit tests exist;
- real Chromium E2E `tests/zn_agent/e2e/test_windows_managed_browser_select.py` exists;
- `ZN Managed Browser E2E` run `33001748123` on workflow head `8c94f1ac9a3fdda2e704f45bdaf02efdc4d40271` succeeded;
- native CHECK/UNCHECK also have unit tests and real Chromium E2E; `ZN Managed Browser E2E` run `32979312465` on UNCHECK head `73257f8c728778054faf74869243b356383fede1` succeeded.

Therefore do **not** implement SELECT_OPTION again. Reconcile documentation to real code/evidence first.

A bounded CI trigger gap was also found: `.github/workflows/zn-managed-browser-e2e.yml` dynamically runs `test_managed_browser_check.py` when invoked, but that test file is absent from the workflow's `push.paths`. A change limited to that test file would not invoke the dedicated Chromium lane. This is a safe CI reliability fix for the next stage.

## Current risks / incomplete work

- broader Work durability remains partial beyond eighteen verified crash/restart windows plus the verified synchronous recovery, shared-attempt persistence/pruning and Body-accounting invariants;
- no deliberate outcome-trace rewrite/compactor exists; destructive long-term-memory migration remains a separate approval boundary;
- explanatory-comment cleanup in `intentional_resident.py` remains non-behavioral debt;
- browser capability ledger currently understates SELECT_OPTION and should be reconciled before new browser action expansion;
- browser PRESS, broader click/editing/target-frame-tab lifecycle and authenticated User Browser Bridge control remain incomplete;
- Windows M8 continuity and SM1+ remain incomplete;
- identity, long-term memory, credentials/permissions, updater/signing, rollback and destructive self-maintenance remain high-risk approval boundaries.

## Task queue

### P1 - shared side-effect-attempt persistence owner

Status: **COMPLETE / CI VERIFIED**

### P2 - bounded cumulative accounting/learning durability audit

Status: **COMPLETE / CI VERIFIED**

Completed contract:

1. enumerated active cumulative resident/kernel accounting and learning paths;
2. found the active Body checkpoint-ordering gap;
3. made Body cumulative accounting retryable/event-idempotent after durable semantic truth;
4. preserved specialized pointer/UI completion and failure-learning ownership;
5. proved success, ordinary failure, postcondition failure and effect-probe restart behavior;
6. re-audited the other active cumulative paths and found no second evidence-backed gap;
7. passed focused recovery and full working-tree ZN CI.

### P3 - browser frontier reconciliation

Status: **OPEN / NEXT**

1. correct stale product capability-map entries for already-verified SELECT_OPTION;
2. add `tests/zn_agent/core/test_managed_browser_check.py` to the dedicated managed-browser E2E path trigger;
3. run the real managed Chromium workflow and any relevant full CI on the reconciliation head;
4. then re-evaluate the genuinely open browser frontier, beginning with PRESS / broader target-frame-tab lifecycle rather than reimplementing existing actions.

### P4 - later product foundations

Status: **OPEN**

Broader Work/checkpoint/restore, Windows M8 continuity, authenticated User Browser Bridge control and SM1+ remain open. Re-read current code and capability map after P3 before choosing ordering; do not trust stale ledger ordering over repository truth.

## Next real target

Re-read the final branch/CI after this HANDOFF commit, then execute P3 browser frontier reconciliation. Keep `main` untouched during ordinary development.
