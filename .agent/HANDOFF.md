# ZN Agent Handoff

Updated: 2026-08-27

## Current goal

Continue broader Work durability after closing and verifying the seventh concrete crash window. Base resident investigation success now survives a crash after durable completion evidence and before terminal `EventOutcome` publication without re-running native investigation.

Broader Work durability remains **PARTIAL**. Do not infer completion from these seven slices.

Founding boundary remains:

> **ZN uses models. Models do not own ZN.**

## Branch / repository truth

- repository: `9529360-cpu/znagent`
- development branch: `dev/zn-agent`
- canonical source/release branch: `main`
- canonical `main`: `8234a835dea604783cea0bd9d28a40de654ec03d`
- verified implementation/test head: `82c495424acb4a005d8b6de162c833c6486b2cc0`
- investigation completion checkpoint: `82c495424acb4a005d8b6de162c833c6486b2cc0`
- common Body completion checkpoint: `dc3b72ad1dfdc5bb8ac2a6c3898fe5038b85197d`
- append terminal-boundary runtime checkpoint: `2ffb79c4bf11903d46f53dd9a7b8d1fcbd922642`
- companion test-contract checkpoint: `f7d6cb64121e914e0250736c0089d58c4b7fea2b`
- PR #6: draft/open/unmerged, base `main`, head `dev/zn-agent`
- `main` was not modified
- no force push or history rewrite was requested or performed

A HANDOFF commit cannot contain its own resulting SHA. Re-read `dev/zn-agent` after this file is committed and use that exact head externally.

## Completed in this stage

### Seventh crash window: base resident investigation success before EventOutcome

The active base chain was:

```text
native investigation resolves from ZN's own evidence
-> _investigation_step()
-> durable WorkingState.stage = complete
-> successful INVESTIGATION result returned
-> crash before outer _complete_result()
-> restart discards complete checkpoint and returns to orient/investigation
```

`ZNResidentRuntime._investigation_step()` now persists a resumable `investigation_completion` checkpoint with the established investigation result required for terminal publication. Restart reconstructs that result and reaches `KernelStore.complete_event()` without invoking `NativeInvestigator.investigate()` again or repeating ordinary runtime task accounting. Missing or malformed completion data fails closed instead of reopening investigation.

Product regression:

```text
test_resolved_investigation_completion_survives_restart_without_reprobe
```

It proves the exact crash/restart boundary on the final product resident, makes any reprobe fatal, keeps `tasks_total` and investigation rounds unchanged after restart, then verifies terminal `EventOutcome`, idle checkpoint and finalized Work progress.

This slice intentionally does not solve the neighboring crash before `investigation_completion` itself is saved. Self-model outcome evidence and runtime task metrics are written before that checkpoint and are not all event-idempotent; that adjacent accounting boundary remains open.

### Sixth crash window: common verified Body success before EventOutcome

`EmbodiedResidentRuntime` persists `native_completion` rather than terminal-looking `complete` before outer terminal publication. Restart reconstructs the verified Body result and reaches `KernelStore.complete_event()` without Body replay or repeated runtime task accounting.

Regression: `test_restart_publishes_verified_body_completion_without_body_replay`.

### Earlier five windows

The earlier verified slices remain closed:

1. missing Work ingress linkage after durable resident event creation;
2. recovery decision committed before the next WorkingState save;
3. append dispatch durably `observed` before checkpoint save;
4. generic command dispatch durably `observed` before checkpoint save, with coherent cancellation of recovery-owned state;
5. append recovery already durably `verified_effect`, then success returned before terminal `EventOutcome`; restart re-verifies without append replay.

## Real test / CI truth

Exact-head seventh-window proof:

```text
head 82c495424acb4a005d8b6de162c833c6486b2cc0
ZN Work Recovery E2E run 33080544314  success / 52 tests / OK
ZN CI run 33080544259
Electron / TypeScript / Windows      success
ZN Source Boundary / Windows         success
ZN Kernel / Python / Windows         success / 602 tests / 5 skipped / OK
Publish Windows CI statuses          success
```

The focused Work Recovery job and the full Kernel discovery both explicitly passed `test_resolved_investigation_completion_survives_restart_without_reprobe` at the exact implementation SHA.

Previous sixth-window proof:

```text
head dc3b72ad1dfdc5bb8ac2a6c3898fe5038b85197d
ZN Work Recovery E2E run 33076704204  success / 51 tests / OK
ZN CI run 33076704179
Electron / TypeScript / Windows      success
ZN Source Boundary / Windows         success
ZN Kernel / Python / Windows         success / 601 tests / 5 skipped / OK
Publish Windows CI statuses          success
```

No local test run is claimed for the seventh-window web-maintainer slice; repository self-hosted Windows CI is the verification authority.

## Current risks / incomplete work

- broader Work durability remains partial beyond the seven verified crash windows;
- specialized semantic/pointer UI completion overrides remain separate proof targets;
- failure-side terminal-looking checkpoint paths remain unproven;
- adjacent pre-completion-checkpoint accounting is not exactly-once: self-model capability evidence and runtime metrics can be updated before the durable completion checkpoint and may repeat after a crash before checkpoint save;
- no deliberate outcome-trace rewrite/compactor exists; destructive long-term-memory migration still requires separate review and explicit approval;
- explanatory-comment cleanup in `intentional_resident.py` remains non-behavioral debt;
- Windows M8 continuity remains incomplete;
- browser PRESS, broader click/editing/multi-select/page lifecycle remain incomplete;
- authenticated User Browser Bridge control remains incomplete;
- SM1+ self-maintenance remains incomplete;
- identity, long-term memory, credentials/permissions, updater/signing, rollback and destructive self-maintenance remain high-risk approval boundaries.

## Task queue

### P1 - broader Work durability

Status: **OPEN / SEVEN CRASH WINDOWS VERIFIED / ACTIVE**

Closed without blind replay:

1. resident event committed before missing `work_runs` linkage;
2. recovery decision committed before the next `WorkingState` checkpoint;
3. append dispatch durably `observed` before the next `WorkingState` checkpoint;
4. generic command dispatch durably `observed` before the next `WorkingState` checkpoint;
5. verified append recovery success before terminal `EventOutcome`;
6. common verified Body success resumes from `native_completion` without Body replay;
7. base resident investigation success resumes from `investigation_completion` without native reprobe.

Next candidates must be selected from real code, not analogy: specialized semantic/pointer UI completion, failure-side terminal-looking checkpoints, or the adjacent pre-checkpoint accounting/idempotence boundary.

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
runtime/python/zn_agent/core/store.py
runtime/python/zn_agent/core/work.py
tests/zn_agent/core/test_work_recovery.py
tests/zn_agent/core/test_work_body_success_recovery.py
tests/zn_agent/core/test_work_side_effect_recovery.py
tests/zn_agent/core/test_work_side_effect_resolution_recovery.py
docs/ZN-IMPLEMENTATION-STATUS.md
.agent/HANDOFF.md
```

## Next real target

Re-read current branch, CI and active caller chain before modifying the next family. Prioritize a narrow crash boundary with a regression that can prove restart behavior on the final product resident. Keep broader Work durability marked PARTIAL, keep `EventOutcome` as terminal truth, and keep `main` untouched during ordinary development.
