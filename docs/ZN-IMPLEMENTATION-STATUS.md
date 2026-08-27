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

Current verified implementation/test checkpoint before documentation synchronization:

```text
905b276b755806e119b4f1ce7a73294a03c78f57  ci: verify resident native completion recovery
74dc824db2aac312a8999e292eb871e8a568f5f8  test: cover resident native completion recovery
7e1996ce116fd88b0d2801ad65b984eea8203d88  fix: checkpoint resident native completion
08d74abb00410523f3820887ae9b5bd6b2cc81db  fix: resume verified UI completion safely
82c495424acb4a005d8b6de162c833c6486b2cc0  resume investigation completion without reprobe
```

Status: **BROADER WORK DURABILITY REMAINS PARTIAL. NINE CONCRETE CRASH WINDOWS ARE CLOSED AND VERIFIED. `EventOutcome` REMAINS TERMINAL TRUTH. CANCELLATION REMAINS LIFECYCLE AUTHORITY, NOT EVIDENCE THAT AN OUTSIDE-WORLD EFFECT DID OR DID NOT OCCUR.**

## 1. Existing durable foundations

The established durable boundaries remain:

- terminal event + exact `EventOutcome` + idle `WorkingState` publish atomically;
- Life observation is secondary and repairable without replaying a completed action;
- event-identity-safe nervous outcome perception uses event receipts and keeps receipted traces dereferenceable across pruning;
- Windows canonical path identity remains consistent across investigation, Body/Terminal, Git, Work, verification and procedural learning;
- Work cancellation is atomic and bypasses failure learning because cancellation is a control/lifecycle result.

Generic nervous `perceive()` remains intentionally plastic and is not an exactly-once API.

## 2. Nine proven broader Work crash windows

The first seven verified windows remain:

1. missing Work ingress linkage after durable resident event creation;
2. recovery decision committed before the next `WorkingState` save;
3. append dispatch durably `observed` before checkpoint save;
4. generic guarded side-effect dispatch durably `observed` before checkpoint save;
5. verified append recovery success before terminal `EventOutcome`;
6. common verified Body success resumes from `native_completion` without Body replay;
7. base resident investigation success resumes from `investigation_completion` without native reprobe.

### 2.8 Verified semantic/focused/UI completion before terminal outcome

The specialized semantic/focused/UI completion path previously persisted terminal-looking `complete` before outer terminal publication. `pointer_click_semantic_resident._complete_ui_scope()` now persists the already-proven result as resumable `native_completion` evidence and leaves `EventOutcome` publication to the existing terminal boundary.

Regression `test_verified_ui_completion_survives_restart_without_resensing_or_input` constructs the crash after fresh typed UI evidence is already accepted but before `EventOutcome`; restart is made fatal on any Body/input replay or typed UI re-verification. It proves terminal completion with unchanged ordinary task accounting.

Exact implementation head `08d74abb00410523f3820887ae9b5bd6b2cc81db` passed both `ZN Work Recovery E2E` run `33087030416` and ordinary `ZN CI` run `33087030408`.

### 2.9 Base resident memory / compiled capability success before terminal outcome

The base `ZNResidentRuntime._orient_step()` had a separate completion split not covered by Body or investigation recovery. A compiled capability was durably marked only as `native_capability` before execution, so a successful capability could return and the process could crash before outer `_complete_result()`; restart could re-enter orientation and execute the capability again. Memory completion could similarly repeat recall/accounting after the result had already been established.

The base resident now persists a `resident_completion` checkpoint containing only an already-established successful MEMORY or CAPABILITY result required for terminal publication. Restart reconstructs that result and reaches `KernelStore.complete_event()` without calling structured-memory recall again, without resolving/executing the compiled capability again, and without repeating ordinary runtime task accounting. Missing or malformed completion evidence fails closed instead of reopening native execution.

Regressions in `test_resident_native_completion_recovery.py` cover both paths:

- `test_compiled_capability_completion_survives_restart_without_reexecution` makes any capability resolution on restart fatal and proves the exact capability result/outcome survives;
- `test_memory_completion_survives_restart_without_recall` makes memory recall on restart fatal and proves the exact memory result/outcome survives.

The focused Work Recovery workflow was extended so these cases are part of the repository recovery gate.

This ninth slice closes only the durable `resident_completion` -> terminal publication split. It does **not** make the interval from a capability's successful return to `resident_completion` checkpoint persistence exactly-once. Self-model/runtime accounting also still occurs before the durable completion checkpoint. A crash in that earlier interval can still repeat accounting and, for a capability, can still re-enter execution. That adjacent boundary remains open and must not be described as solved.

## 3. Real Windows CI proof

Exact implementation/test/CI head `905b276b755806e119b4f1ce7a73294a03c78f57`:

```text
ZN Work Recovery E2E run 33089482266
Windows resident Work restart recovery  success
Compile Work recovery path              success
Verify durable Work progress/restart    success

ZN CI run 33089482187
Electron / TypeScript / Windows         success
ZN Source Boundary / Windows            success
ZN Kernel / Python / Windows             core test step success
```

At documentation-update time the substantive Kernel test step had completed successfully; CI wrapper/post-job status publication was still finishing. Re-read the exact run and final branch HEAD before reporting final CI state.

No local test run is claimed for this web-maintainer slice because there is no repository checkout in the available execution container. Repository self-hosted Windows CI is the verification authority.

Previous exact semantic/UI recovery head `08d74abb00410523f3820887ae9b5bd6b2cc81db` passed `ZN Work Recovery E2E` run `33087030416` and `ZN CI` run `33087030408` completely.

## 4. What remains partial

Open work still includes:

- broader Work durability beyond these nine proven windows;
- the capability-success / memory-accounting interval before `resident_completion` is durably saved; a capability may already have executed while restart still sees the pre-result state;
- generalized event-idempotent self-model and runtime accounting at completion checkpoints;
- failure-side terminal-looking checkpoint paths remain unproven;
- external cognition success/failure completion boundaries still require direct crash/restart proof rather than analogy;
- no deliberate outcome-trace rewrite/compactor; any future implementation must atomically retarget receipts before deleting old representation and requires separate review for destructive long-term-memory migration;
- explanatory-comment cleanup in `intentional_resident.py` remains non-behavioral debt;
- Windows continuity M8;
- browser PRESS, broader click/editing/multi-select/page lifecycle;
- authenticated User Browser Bridge control;
- SM1+ self-maintenance.

High-risk identity, long-term memory, credential/permission, updater/signing, rollback and destructive self-maintenance changes still require human approval.

## 5. Next real target

Continue from real call-chain evidence, not analogy. The strongest next Work durability target is the pre-`resident_completion` interval after compiled capability success: establish a durable, restart-safe ownership protocol that does not lose or duplicate accounting and does not blindly replay a capability whose outside-world effect may already have happened. If that requires distinguishing pure/replayable capabilities from effectful ones, encode that ownership explicitly rather than hiding it behind a compatibility layer.

Failure-side and external-cognition terminal publication boundaries remain independent later proof targets.

Keep `main` untouched during ordinary development.
