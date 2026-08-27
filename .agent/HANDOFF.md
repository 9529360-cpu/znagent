# ZN Agent Handoff

Updated: 2026-08-27

## Current goal

Continue broader Work durability after closing and verifying nine concrete crash windows. The newest slice makes already-established base resident MEMORY and compiled CAPABILITY success resumable after a crash before terminal `EventOutcome`, without re-recall/re-execution after the durable completion checkpoint.

Broader Work durability remains **PARTIAL**. Do not infer completion from these nine slices.

Founding boundary remains:

> **ZN uses models. Models do not own ZN.**

## Branch / repository truth

- repository: `9529360-cpu/znagent`
- development branch: `dev/zn-agent`
- canonical source/release branch: `main`
- canonical `main`: `8234a835dea604783cea0bd9d28a40de654ec03d`
- exact implementation/test/CI head before documentation synchronization: `905b276b755806e119b4f1ce7a73294a03c78f57`
- resident native completion runtime checkpoint: `7e1996ce116fd88b0d2801ad65b984eea8203d88`
- resident native completion regression checkpoint: `74dc824db2aac312a8999e292eb871e8a568f5f8`
- resident native completion CI checkpoint: `905b276b755806e119b4f1ce7a73294a03c78f57`
- semantic/UI completion checkpoint: `08d74abb00410523f3820887ae9b5bd6b2cc81db`
- investigation completion checkpoint: `82c495424acb4a005d8b6de162c833c6486b2cc0`
- PR #6: draft/open/unmerged, mergeable, base `main`, head `dev/zn-agent`
- `main` was not modified
- no force push or history rewrite was requested or performed

A HANDOFF commit cannot contain its own resulting SHA. Re-read `dev/zn-agent` after this file is committed and use that exact head externally.

## Completed in this stage

### Ninth crash window: base resident memory / compiled capability success before EventOutcome

The active base capability chain was:

```text
_orient_step()
-> persist native_capability before execute
-> compiled capability executes and returns success
-> self-model/runtime accounting
-> successful CAPABILITY result returned
-> crash before outer _complete_result()
-> restart recovers nonterminal event while WorkingState still looks pre-result
-> orient/capability could execute again
```

Memory success had the analogous post-result/pre-terminal replay risk for recall/accounting.

`ZNResidentRuntime` now owns a resumable `resident_completion` checkpoint for already-established successful MEMORY and CAPABILITY results. Once that checkpoint is durable, restart reconstructs the result and proceeds to `KernelStore.complete_event()` without structured-memory recall, capability resolution/execution, or repeated ordinary runtime task accounting. Missing/malformed checkpoint data fails closed instead of reopening native execution.

Product regressions:

```text
test_compiled_capability_completion_survives_restart_without_reexecution
test_memory_completion_survives_restart_without_recall
```

The tests reconstruct the final product resident from the same SQLite store, make replay operations fatal on restart, verify the exact terminal `EventOutcome`, and prove `tasks_total` is unchanged across the restart completion step.

This slice intentionally does **not** solve the earlier interval after a capability has returned success but before `resident_completion` itself is durable. In that interval the effect may already have happened while restart can still see pre-result state. Self-model/runtime accounting also remains pre-checkpoint and not generally event-idempotent. That is now the strongest next durability target.

### Eighth crash window: verified semantic/focused/UI completion before EventOutcome

`pointer_click_semantic_resident._complete_ui_scope()` now persists verified typed UI success as resumable `native_completion` evidence instead of terminal-looking `complete`. Restart publishes terminal outcome without Body/input replay or typed UI re-verification.

Regression: `test_verified_ui_completion_survives_restart_without_resensing_or_input`.

Exact head `08d74abb00410523f3820887ae9b5bd6b2cc81db` passed `ZN Work Recovery E2E` run `33087030416` and `ZN CI` run `33087030408`.

### Earlier seven windows

The earlier verified slices remain closed:

1. missing Work ingress linkage after durable resident event creation;
2. recovery decision committed before the next WorkingState save;
3. append dispatch durably `observed` before checkpoint save;
4. generic command dispatch durably `observed` before checkpoint save;
5. verified append recovery success before terminal `EventOutcome`;
6. common verified Body success resumes from `native_completion` without Body replay;
7. base resident investigation success resumes from `investigation_completion` without native reprobe.

## Real test / CI truth

Exact implementation/test/CI proof for `905b276b755806e119b4f1ce7a73294a03c78f57`:

```text
ZN Work Recovery E2E run 33089482266                 success
Windows resident Work restart recovery                success
Compile Work recovery path                            success
Verify durable Work progress and restart recovery     success

ZN CI run 33089482187                                 success
Electron / TypeScript / Windows                       success
ZN Source Boundary / Windows                          success
ZN Kernel / Python / Windows                          success
Publish Windows CI statuses                           success
```

The focused recovery suite explicitly includes both new resident native completion regressions. The full Kernel job compiled the resident core and completed its working-tree core test step successfully.

No local test run is claimed for this web-maintainer slice because the available execution container has no repository checkout; repository self-hosted Windows CI is the verification authority.

## Current risks / incomplete work

- broader Work durability remains partial beyond nine verified crash windows;
- strongest adjacent gap: capability success can occur before `resident_completion` is durably saved; a restart in that interval can still re-enter execution;
- self-model outcome evidence and runtime task metrics are not generally event-idempotent before completion checkpoints;
- failure-side terminal-looking checkpoint paths remain unproven;
- external cognition completion/failure crash boundaries remain unproven;
- no deliberate outcome-trace rewrite/compactor exists; destructive long-term-memory migration still requires separate review and explicit approval;
- explanatory-comment cleanup in `intentional_resident.py` remains non-behavioral debt;
- Windows M8 continuity remains incomplete;
- browser PRESS, broader click/editing/multi-select/page lifecycle remain incomplete;
- authenticated User Browser Bridge control remains incomplete;
- SM1+ self-maintenance remains incomplete;
- identity, long-term memory, credentials/permissions, updater/signing, rollback and destructive self-maintenance remain high-risk approval boundaries.

## Task queue

### P1 - broader Work durability

Status: **OPEN / NINE CRASH WINDOWS VERIFIED / ACTIVE**

Next real target: trace the compiled capability ownership boundary from `CapabilityRegistry.resolve()` through capability execution, self-model/runtime accounting, `resident_completion`, and `KernelStore.complete_event()`. Design an explicit durable protocol for the success-return -> checkpoint interval. Do not blindly replay an effectful capability and do not hide the gap behind compatibility state. If capability purity/replayability must become explicit metadata, make that ownership part of ZN's native capability contract and test it on restart.

After that, investigate failure-side and external-cognition completion boundaries independently.

### P2 - browser follow-ons

Status: **OPEN**

PRESS, broader click semantics, richer text editing, multi-select, broader page/target lifecycle and authenticated User Browser Bridge control.

### P3 - M8 / SM1+

Status: **OPEN**

Preserve human approval for high-risk identity, memory, credentials, updater/signing, rollback and destructive self-maintenance changes.

## Related files

```text
runtime/python/zn_agent/core/resident.py
runtime/python/zn_agent/core/embodied_resident.py
runtime/python/zn_agent/core/pointer_click_semantic_resident.py
runtime/python/zn_agent/core/store.py
runtime/python/zn_agent/core/capabilities.py
tests/zn_agent/core/test_resident_native_completion_recovery.py
tests/zn_agent/core/test_work_ui_completion_recovery.py
.github/workflows/zn-work-recovery-e2e.yml
docs/ZN-IMPLEMENTATION-STATUS.md
.agent/HANDOFF.md
```

## Next real target

Re-read current branch, CI and active caller chain before modification. Prioritize the pre-`resident_completion` compiled-capability success interval and preserve `EventOutcome` as terminal truth. Keep broader Work durability marked PARTIAL and keep `main` untouched during ordinary development.
