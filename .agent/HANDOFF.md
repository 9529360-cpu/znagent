# ZN Agent Handoff

Updated: 2026-08-27

## Current goal

Continue the bounded broader-Work durability audit after closing and verifying eighteen concrete crash/restart windows. The newest slice closes the structured-memory and native-investigation accounting-before-completion gaps, then independently closes the active external-cognition resident completion, secondary learning, kernel result/route-learning and unknown-provider-outcome replay boundaries.

Broader Work durability remains **PARTIAL**. Do not reopen these verified completion paths without evidence; the next real target is the unresolved `side_effect_recovery` synchronous-driving lifecycle and the shared low-level side-effect-attempt helper boundary.

Founding boundary remains:

> **ZN uses models. Models do not own ZN.**

## Branch / repository truth

- repository: `9529360-cpu/znagent`
- development branch: `dev/zn-agent`
- canonical source/release branch: `main`
- canonical `main`: `8234a835dea604783cea0bd9d28a40de654ec03d`
- exact implementation/test/CI proof head: `8274289f22daa18d8638f365da54d794e2e4b3f0`
- branch HEAD immediately before this status/HANDOFF synchronization commit: `8274289f22daa18d8638f365da54d794e2e4b3f0`
- PR #6 remains the development PR from `dev/zn-agent` to `main`
- `main` was not modified
- no force push or history rewrite was requested or performed

A HANDOFF commit cannot contain its own resulting SHA. Re-read `dev/zn-agent` after this file is committed and use that exact head externally.

## Completed in this stage

### 14. Structured-memory accounting boundary

Active chain:

```text
provider_bridge.build_resident_runtime*
-> CapabilityRecoveryResidentRuntime._orient_step()
-> structured memory recall
-> resident_completion
-> terminal EventOutcome
```

Old ordering learned/counted before the durable semantic completion. New ordering persists exact `resident_completion` plus a versioned accounting descriptor first, then calls event-idempotent `ResidentAccountingJournal.record_memory_success(event_id)`.

Crash/restart proof covers both checkpoint-before-accounting and accounting-before-terminal-publication. Restart does not rerun recall and does not duplicate task or knowledge evidence. Historical completion checkpoints without the new descriptor are treated as already-accounted because the old path only checkpointed after eager accounting.

### 15. Native-investigation accounting boundary

Active native investigation now persists exact `investigation_completion` plus a versioned accounting descriptor before ability/knowledge/task accounting. `record_native_investigation_success(event_id)` gates the cumulative update by durable event identity.

Fault injection proves restart after checkpoint-before-accounting and accounting-before-terminal-publication without native reprobe or duplicate ability/knowledge/task evidence. Historical descriptor-less checkpoints remain upgrade-safe under the same old-ordering rule.

### 16. External resident completion + learning boundary

The active resident now owns external cognition through a durable `external_completion` stage rather than writing `complete/failed` and returning to a non-resumable state.

```text
bounded CognitionRequest
-> stable kernel goal derived from request_id
-> durable kernel result
-> persist WorkingState stage=external_completion
   + exact success/failure payload
   + external accounting descriptor
-> idempotent resident metrics/token accounting
-> success-only resident knowledge integration
-> Life/investigation secondary integration
-> terminal EventOutcome
```

Restart from `external_completion` never reruns the provider. Direct fault injection proves:

- success after resident accounting before terminal publication: metrics, knowledge, route evidence and Life candidate remain once;
- success after Life learning before investigation external integration: restart completes investigation integration without provider replay or duplicate Life/accounting;
- failure before resident metrics: restart accounts once, no success knowledge;
- failure after resident metrics before Life unresolved publication: restart publishes unresolved Life state without provider replay or duplicate metrics.

### 17. Durable kernel result and route-learning boundary

`ZNKernelRuntime.run_goal()` now supports a stable durable `goal_id` and stores a versioned attempt ledger in Goal metadata:

```text
dispatching
-> full worker result checkpoint (worker_observed)
-> assessed
-> idempotent experience + route-quality accounting
-> settled
-> final goal result
```

`KernelAttemptAccountingJournal` gates route evidence by `(goal_id, attempt, external_route_assessment)`. Full WorkerResult is persisted, so restart after provider return reconstructs the complete result rather than replaying the provider or relying on the old 2000-character experience excerpt. Experience and improvement-proposal identities are deterministic for recovery.

Fault injection proves restart after `worker_observed` and after route learning/`settled` before final publication with zero provider replay and exactly-once route evidence.

### 18. Unknown provider outcome blocks replay

The unavoidable crash interval after durable `dispatching` but before a returned provider result is explicit uncertainty. On restart ZN does not retry or switch routes blindly. It records an unknown external outcome, blocks provider replay, adds no route learning, and creates no improvement proposal from the unknown result.

This is an intentional at-most-once provider boundary, not a false exactly-once claim.

### Implementation/test commits

```text
dadc769875f4694d26e908f9c3a445349326d138  fix: close resident completion durability gaps
5384a71ad0d92d59046a023550c8de987ed22047  test: probe external learning recovery boundaries
8274289f22daa18d8638f365da54d794e2e4b3f0  ci: cover external learning recovery boundaries
```

Key implementation files:

```text
runtime/python/zn_agent/core/runtime.py
runtime/python/zn_agent/core/kernel_accounting.py
runtime/python/zn_agent/core/evolution.py
runtime/python/zn_agent/core/capability_recovery_resident.py
runtime/python/zn_agent/core/resident_accounting.py
```

Key new fault-injection suites:

```text
tests/zn_agent/core/test_completion_durability_boundaries.py
tests/zn_agent/core/test_completion_durability_secondary.py
```

The recovery workflow now directly compiles and executes these durability tests.

## Real test / CI truth

Exact implementation/test/CI proof for `8274289f22daa18d8638f365da54d794e2e4b3f0`:

```text
ZN Work Recovery E2E run 33112257030                 success
Windows resident Work restart recovery                success
Compile Work recovery path                            success
Verify durable Work progress and restart recovery     success
  primary completion durability fault injection       success
  secondary learning durability fault injection       success

ZN CI run 33112257029                                 success
ZN Kernel / Python / Windows                          success
  Boot isolated ZN distribution without a model       success
  Compile resident core                               success
  Run ZN core tests against working tree              success
ZN Source Boundary / Windows                          success
Electron / TypeScript / Windows                       success
Publish Windows CI statuses                           success
```

The earlier focused recovery run for `dadc769875f4694d26e908f9c3a445349326d138` (`33111884613`) also passed. Its general CI was superseded by later branch pushes and is not used as the final full-suite proof.

No local repository test run is claimed. Scratch copies of changed Python modules/tests passed `py_compile`; repository self-hosted Windows CI is the verification authority.

## Current risks / incomplete work

- broader Work durability remains partial beyond eighteen verified crash/restart windows;
- direct synchronous driving while unresolved `side_effect_recovery` persists still deserves separate lifecycle review; external uncertainty must not become automatic replay or invented failure merely to terminate a caller;
- Body and compiled capability recovery share `resident_side_effect_attempts` durable truth but low-level helper implementation is not fully consolidated;
- continue the bounded backward audit for any other cumulative accounting/learning writes that can occur before durable semantic facts;
- no deliberate outcome-trace rewrite/compactor exists; destructive long-term-memory migration remains a separate approval boundary;
- explanatory-comment cleanup in `intentional_resident.py` remains non-behavioral debt;
- Windows M8 continuity, browser PRESS/broader interaction lifecycle, authenticated User Browser Bridge control, and SM1+ remain incomplete;
- identity, long-term memory, credentials/permissions, updater/signing, rollback and destructive self-maintenance remain high-risk approval boundaries.

## Task queue

### P1 - bounded broader Work durability audit

Status: **OPEN / EIGHTEEN CRASH-RESTART WINDOWS VERIFIED / ACTIVE**

Next real target:

1. trace direct synchronous driving while a durable `side_effect_recovery` remains unresolved, including caller termination, cancellation and later resume semantics;
2. audit/consolidate the shared low-level `resident_side_effect_attempts` helper without introducing a second truth model;
3. continue backward from other cumulative accounting/learning writes and prove durable semantic facts precede recoverable cumulative state.

For every path, trace entry -> owner -> state -> lifecycle -> dependency -> tests -> active caller and prove the crash/restart boundary directly. Preserve both outside-world-effect uncertainty and unknown-provider outcome as uncertainty.

### P2 - browser follow-ons

Status: **OPEN**

PRESS, broader click semantics, richer text editing, multi-select, broader page/target lifecycle and authenticated User Browser Bridge control.

### P3 - M8 / SM1+

Status: **OPEN**

Preserve human approval for high-risk identity, memory, credentials, updater/signing, rollback and destructive self-maintenance changes.

## Related files

```text
runtime/python/zn_agent/core/runtime.py
runtime/python/zn_agent/core/kernel_accounting.py
runtime/python/zn_agent/core/evolution.py
runtime/python/zn_agent/core/capability_recovery_resident.py
runtime/python/zn_agent/core/resident_accounting.py
tests/zn_agent/core/test_completion_durability_boundaries.py
tests/zn_agent/core/test_completion_durability_secondary.py
.github/workflows/zn-work-recovery-e2e.yml
docs/ZN-IMPLEMENTATION-STATUS.md
.agent/HANDOFF.md
```

## Next real target

Re-read current branch, PR/CI and active caller chain before the next modification. Start with unresolved `side_effect_recovery` under direct synchronous driving, then the shared low-level side-effect-attempt helper boundary. Keep broader Work durability marked PARTIAL and keep `main` untouched during ordinary development.
