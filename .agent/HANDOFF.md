# ZN Agent Handoff

Updated: 2026-08-27

## Current goal

Continue the bounded broader-Work durability audit after closing and verifying thirteen concrete crash windows. The newest slice makes zero-model terminal failure and deterministic outer `run_once()` exception publication restart-safe without duplicate task accounting, while preserving durable success and outside-world uncertainty rather than overwriting either as failure.

Broader Work durability remains **PARTIAL**. The next target is the nearest accounting-before-checkpoint pattern: structured-memory success and base native-investigation success, followed by external-cognition completion boundaries.

Founding boundary remains:

> **ZN uses models. Models do not own ZN.**

## Branch / repository truth

- repository: `9529360-cpu/znagent`
- development branch: `dev/zn-agent`
- canonical source/release branch: `main`
- canonical `main`: `8234a835dea604783cea0bd9d28a40de654ec03d`
- exact implementation/test/CI head: `20655834570a31dd4f59abcbc3502aab9e1d81f4`
- implementation-status synchronization: `4ecd94cc1ffce33806a8dfe2326a914363b368e8`
- branch HEAD immediately before this HANDOFF commit: `4ecd94cc1ffce33806a8dfe2326a914363b368e8`
- PR #6 remains the development PR; recheck its exact state before the next modification
- `main` was not modified
- no force push or history rewrite was requested or performed

A HANDOFF commit cannot contain its own resulting SHA. Re-read `dev/zn-agent` after this file is committed and use that exact head externally.

## Completed in this stage

### Twelfth crash window: terminal budget-blocked failure ownership

Real active chain:

```text
provider_bridge.build_resident_runtime*
-> CapabilityRecoveryResidentRuntime
-> base ZNResidentRuntime._deliberation_step()
-> no-model/budget-blocked terminal failure
-> terminal EventOutcome
```

Old behavior could increment `runtime_metrics.tasks_total` before terminal publication. A crash in that interval could repeat deliberation, increment impasse attempts again, and duplicate task accounting.

New ownership:

```text
known zero-model terminal failure
-> persist WorkingState stage=terminal_failure + exact failure payload
-> ResidentAccountingJournal.record_terminal_failure(event_id)
-> reconstruct BUDGET_BLOCKED result
-> KernelStore.complete_event()
```

`record_terminal_failure()` is event-idempotent through `resident_event_accounting(event_id, terminal_failure)`. It preserves existing semantics: terminal failure counts one attempted task but does not invent native ability or knowledge evidence.

Restart after checkpoint-before-accounting or accounting-before-EventOutcome now consumes the durable failure fact without repeating deliberation or task count.

### Thirteenth crash window: outer deterministic exception ownership

The outer `run_once()` exception fallback now uses the same durable terminal-failure checkpoint and idempotent task accounting before terminal publication.

It also refuses to overwrite stronger existing truth:

- existing `EventOutcome` remains authoritative;
- already-durable success/completion checkpoints are preserved if terminal publication throws;
- `side_effect_recovery` / `blocked_by=outside_world_effect_uncertain` propagates the exception without becoming known failure evidence;
- durable terminal/completion stages stay owned by their stage-specific resume path.

This contract is deliberately limited to deterministic zero-model `BUDGET_BLOCKED` fallback. External cognition is still an independent open durability boundary.

### Implementation/test commits

```text
7fdeddc68c3828504931af24149092ddf824783f  feat: journal terminal failure task accounting
076a611994d85aa76fcaf895142eb46acf93a4e4  fix: make terminal failure completion restart safe
c67d477397dbe02f12fb562aa7aece9ff941500a  test: prove terminal failure restart recovery
4f16cebfa867edbf50ed1094c410d3e15e3f90c7  ci: cover terminal failure restart recovery
20655834570a31dd4f59abcbc3502aab9e1d81f4  test: avoid slot-unsafe budget mocking
4ecd94cc1ffce33806a8dfe2326a914363b368e8  docs: record terminal failure recovery
```

Focused regressions in `tests/zn_agent/core/test_terminal_failure_recovery.py`:

```text
test_budget_failure_accounting_survives_crash_before_outcome
test_budget_failure_checkpoint_survives_crash_before_accounting
test_outer_exception_failure_survives_restart_without_duplicate_accounting
test_publish_exception_preserves_durable_success_checkpoint
test_outer_exception_does_not_reclassify_outside_world_uncertainty
```

## Real test / CI truth

Exact implementation/test/CI proof for `20655834570a31dd4f59abcbc3502aab9e1d81f4`:

```text
ZN Work Recovery E2E run 33108134821                 success
Windows resident Work restart recovery                success
Compile Work recovery path                            success
Verify durable Work progress and restart recovery     success
focused recovery suite                                66 tests / success

ZN CI run 33108134767                                 success
ZN Kernel / Python / Windows                          success
  Boot isolated ZN distribution without a model       success
  Compile resident core                               success
  Run ZN core tests against working tree              success
ZN Source Boundary / Windows                          success
Electron / TypeScript / Windows                       success
```

The superseded focused run `33108010947` failed only because two new tests attempted to patch the read-only slotted `CognitiveBudgetManager.decide` instance method. The implementation compiled and the other focused tests passed. Commit `20655834570a31dd4f59abcbc3502aab9e1d81f4` replaced that fragile instrumentation with persisted impasse-attempt assertions; the authoritative rerun is green.

No local repository test run is claimed. Repository self-hosted Windows CI is the verification authority.

## Current risks / incomplete work

- broader Work durability remains partial beyond thirteen verified crash windows;
- structured-memory success performs self-model/runtime accounting before `resident_completion`; the later completion restart interval is proven, this earlier interval is not;
- base native-investigation success performs self-model/runtime accounting before `investigation_completion`; the later completion restart interval is proven, this earlier interval is not;
- external cognition success/failure still needs direct ownership proof around model result, task accounting, learning, WorkingState and terminal `EventOutcome`;
- Body and compiled capability recovery share `resident_side_effect_attempts` durable truth but low-level helper implementation is not fully consolidated;
- direct synchronous driving while unresolved `side_effect_recovery` persists deserves separate lifecycle review; uncertainty must not become replay/failure merely to terminate a caller;
- no deliberate outcome-trace rewrite/compactor exists; destructive long-term-memory migration remains a separate approval boundary;
- Windows M8 continuity, browser PRESS/broader interaction lifecycle, authenticated User Browser Bridge control, and SM1+ remain incomplete;
- identity, long-term memory, credentials/permissions, updater/signing, rollback and destructive self-maintenance remain high-risk approval boundaries.

## Task queue

### P1 - bounded broader Work durability audit

Status: **OPEN / THIRTEEN CRASH WINDOWS VERIFIED / ACTIVE**

Next real target:

1. structured-memory success accounting before `resident_completion`;
2. base native-investigation success accounting before `investigation_completion`;
3. external-cognition success/failure completion and learning ownership.

For each path, trace entry -> owner -> state -> lifecycle -> dependencies -> tests -> active caller and prove crash/restart behavior directly. Preserve `outside_world_effect_uncertain` as uncertainty.

### P2 - browser follow-ons

Status: **OPEN**

PRESS, broader click semantics, richer text editing, multi-select, broader page/target lifecycle and authenticated User Browser Bridge control.

### P3 - M8 / SM1+

Status: **OPEN**

Preserve human approval for high-risk identity, memory, credentials, updater/signing, rollback and destructive self-maintenance changes.

## Related files

```text
runtime/python/zn_agent/core/resident.py
runtime/python/zn_agent/core/resident_accounting.py
runtime/python/zn_agent/core/capability_recovery_resident.py
runtime/python/zn_agent/core/completion_observation.py
runtime/python/zn_agent/core/provider_bridge.py
tests/zn_agent/core/test_terminal_failure_recovery.py
tests/zn_agent/core/test_resident_native_completion_recovery.py
tests/zn_agent/core/test_capability_failure_recovery.py
.github/workflows/zn-work-recovery-e2e.yml
docs/ZN-IMPLEMENTATION-STATUS.md
.agent/HANDOFF.md
```

## Next real target

Re-read current branch, PR/CI and the active caller chain before modification. Start the bounded backward durability audit at structured-memory and native-investigation accounting-before-checkpoint ownership, then external cognition. Keep broader Work durability marked PARTIAL and keep `main` untouched during ordinary development.
