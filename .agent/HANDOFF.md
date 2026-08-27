# ZN Agent Handoff

Updated: 2026-08-27

## Current goal

Continue broader Work durability after closing and verifying ten concrete crash windows. The newest slice closes the compiled-capability execution/success interval before `resident_completion`: default opaque capability code is non-replayable after interruption, durable observed success is resumable without reloading code, and native capability success accounting is event-idempotent across restart.

Broader Work durability remains **PARTIAL**. Do not infer completion from these ten slices.

Founding boundary remains:

> **ZN uses models. Models do not own ZN.**

## Branch / repository truth

- repository: `9529360-cpu/znagent`
- development branch: `dev/zn-agent`
- canonical source/release branch: `main`
- canonical `main`: `8234a835dea604783cea0bd9d28a40de654ec03d`
- exact implementation/test/CI head before documentation synchronization: `a5d95f1f2049f96e9ece0c4a1f0ccfa1883e884d`
- implementation-status synchronization: `a209fa6b2e4987305eac23a7e5f73a4fb112ac73`
- capability accounting recovery: `bb26cf1731eca594c13cf97e6a9eb6bc49b09e1d`
- event-idempotent capability accounting journal: `4abe91d042e0cc3df57ecf4df1fc342c915ec008`
- capability ownership/replay contract: `bfd8e19bf5a20b5802dbf8148af7ae2c11dcc9dd`
- capability recovery active product owner: `6af16f7f7f6e73ddbb7aaa6820afd13c07a3d5af` / `b11a20d6b6f9914e43c10f94ace15f0b19d7c00d`
- resident side-effect journal: `98ddce8f89aa5071451d295f06b3e745a345fd03`
- restart/idempotency regression checkpoint: `67957c8044240abd1d35639a4ca93325c89009d3`
- PR #6: draft/open/unmerged, mergeable, base `main`, head `dev/zn-agent`
- `main` was not modified
- no force push or history rewrite was requested or performed

A HANDOFF commit cannot contain its own resulting SHA. Re-read `dev/zn-agent` after this file is committed and use that exact head externally.

## Completed in this stage

### Tenth crash window: compiled capability execution ownership before `resident_completion`

The previously open chain was:

```text
CapabilityRegistry.resolve()
-> persist only generic native_capability stage
-> arbitrary compiled capability code executes / may affect outside world
-> result returns
-> self-model/runtime accounting
-> resident_completion save
-> terminal EventOutcome
```

A crash after the code had started or returned could leave restart with no durable fact distinguishing “never ran” from “may already have affected the world”, and accounting could duplicate before the completion checkpoint.

The active product now owns an explicit protocol:

```text
resolve capability
-> atomically persist side-effect attempt `started` + WorkingState
-> execute capability code
-> atomically persist serialized result as `observed` + WorkingState
-> event-idempotent successful native capability accounting
-> persist `resident_completion`
-> KernelStore.complete_event()
```

Key semantics:

- `CallableCapability` and `ExactTaskCapability` default to `replay_safe=False`;
- restart after durable `started` for a default capability does not run the handler again;
- that case becomes existing resident `side_effect_recovery` with `blocked_by=outside_world_effect_uncertain` and `replay_blocked=True`;
- cancellation abandons only lifecycle/attempt ownership and does not assert whether the external effect occurred;
- only explicit `replay_safe=True` permits retry after interrupted `started`;
- a successful durable `observed` result is sufficient to resume without memory recall, capability matching/resolution or the capability code being registered after restart;
- `resident_event_accounting(event_id, kind)` makes successful native capability self-model evidence plus `runtime_metrics.tasks_total` a single event-idempotent transaction, so crash after accounting but before `resident_completion` does not duplicate either.

Product regressions in `test_resident_native_completion_recovery.py` cover:

```text
test_interrupted_default_capability_enters_recovery_without_replay_or_failure_learning
test_explicit_replay_safe_capability_may_retry_after_interrupted_start
test_observed_capability_success_resumes_without_code_and_does_not_duplicate_accounting
test_compiled_capability_completion_survives_restart_without_reexecution
```

The first test also proves cancellation changes the durable attempt to `work_abandoned` and writes a control cancellation outcome without false failure learning. The observed-success test simulates a crash after event-idempotent accounting but before `resident_completion`, then makes memory recall and capability resolution fatal on restart and proves exact completion with unchanged metrics/evidence.

This slice does **not** generalize exactly-once accounting to memory, failure or external cognition paths. Observed capability failure and outer failure paths remain separate proof targets.

### Earlier nine windows

The earlier verified slices remain closed:

1. missing Work ingress linkage after durable resident event creation;
2. recovery decision committed before the next WorkingState save;
3. append dispatch durably `observed` before checkpoint save;
4. generic guarded side-effect dispatch durably `observed` before checkpoint save;
5. verified append recovery success before terminal `EventOutcome`;
6. common verified Body success resumes from `native_completion` without Body replay;
7. base resident investigation success resumes from `investigation_completion` without native reprobe;
8. verified semantic/focused/UI completion resumes without resensing or input replay;
9. established base MEMORY/CAPABILITY completion resumes from `resident_completion` without re-recall/re-execution.

## Real test / CI truth

Exact implementation/test/CI proof for `a5d95f1f2049f96e9ece0c4a1f0ccfa1883e884d`:

```text
ZN Work Recovery E2E run 33101772085                 success
Windows resident Work restart recovery                success
Compile Work recovery path                            success
Verify durable Work progress and restart recovery     success

ZN CI run 33101772081                                 success
ZN Kernel / Python / Windows                          success
  Boot isolated ZN distribution without a model       success
  Compile resident core                               success
  Run ZN core tests against working tree              success
ZN Source Boundary / Windows                          success
Electron / TypeScript / Windows                       success
Publish Windows CI statuses                           success
```

The focused recovery suite explicitly includes the new capability interruption/replay/observed-result/accounting regressions. The full Kernel job also passed its working-tree core test step.

No local test run is claimed for this web-maintainer slice because the available execution container has no repository checkout; repository self-hosted Windows CI is the verification authority.

## Current risks / incomplete work

- broader Work durability remains partial beyond ten verified crash windows;
- observed compiled-capability failure and failure-side terminal/checkpoint paths are not yet proven resumable/exactly-once;
- structured-memory success still performs self-model/runtime accounting before its completion checkpoint; only restart after durable `resident_completion` is proven there;
- outer `run_once()` exception handling can still perform impasse/failure accounting before terminal publication without a dedicated durable failure completion contract;
- external cognition success/failure completion crash boundaries remain unproven;
- Body and compiled capability recovery share the same `resident_side_effect_attempts` durable truth but their low-level helper implementation is not fully consolidated;
- direct synchronous driving while unresolved `side_effect_recovery` persists deserves separate lifecycle review; do not turn uncertainty into replay/failure merely to terminate a synchronous call;
- no deliberate outcome-trace rewrite/compactor exists; destructive long-term-memory migration still requires separate review and explicit approval;
- explanatory-comment cleanup in `intentional_resident.py` remains non-behavioral debt;
- Windows M8 continuity remains incomplete;
- browser PRESS, broader click/editing/multi-select/page lifecycle remain incomplete;
- authenticated User Browser Bridge control remains incomplete;
- SM1+ self-maintenance remains incomplete;
- identity, long-term memory, credentials/permissions, updater/signing, rollback and destructive self-maintenance remain high-risk approval boundaries.

## Task queue

### P1 - broader Work durability

Status: **OPEN / TEN CRASH WINDOWS VERIFIED / ACTIVE**

Next real target: trace failure ownership through observed compiled-capability failure, `_deliberation_step()` impasse/failure handling and the outer `run_once()` exception path. A durable failure fact must be resumable without duplicate self-model/runtime learning/accounting, and outside-world uncertainty must never be collapsed into false failure evidence.

After that, prove structured-memory pre-completion accounting and external-cognition completion boundaries independently.

### P2 - browser follow-ons

Status: **OPEN**

PRESS, broader click semantics, richer text editing, multi-select, broader page/target lifecycle and authenticated User Browser Bridge control.

### P3 - M8 / SM1+

Status: **OPEN**

Preserve human approval for high-risk identity, memory, credentials, updater/signing, rollback and destructive self-maintenance changes.

## Related files

```text
runtime/python/zn_agent/core/capabilities.py
runtime/python/zn_agent/core/capability_recovery_resident.py
runtime/python/zn_agent/core/resident_accounting.py
runtime/python/zn_agent/core/side_effect_journal.py
runtime/python/zn_agent/core/provider_bridge.py
runtime/python/zn_agent/core/resident.py
runtime/python/zn_agent/core/store.py
tests/zn_agent/core/test_resident_native_completion_recovery.py
.github/workflows/zn-work-recovery-e2e.yml
docs/ZN-IMPLEMENTATION-STATUS.md
.agent/HANDOFF.md
```

## Next real target

Re-read current branch, CI and active caller chain before modification. Prioritize failure-side completion ownership and keep outside-world uncertainty separate from failure evidence. Keep broader Work durability marked PARTIAL and keep `main` untouched during ordinary development.
