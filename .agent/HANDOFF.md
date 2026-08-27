# ZN Agent Handoff

Updated: 2026-08-27

## Current goal

Continue broader Work durability after closing and verifying eleven concrete crash windows. The newest verified slice makes a durably observed compiled-capability failure resumable without capability replay or duplicate failure learning, while keeping outside-world uncertainty distinct from known failure evidence.

Broader Work durability remains **PARTIAL**. The next target is terminal failure completion ownership in `_deliberation_step()` and the outer `run_once()` exception path.

Founding boundary remains:

> **ZN uses models. Models do not own ZN.**

## Branch / repository truth

- repository: `9529360-cpu/znagent`
- development branch: `dev/zn-agent`
- canonical source/release branch: `main`
- canonical `main`: `8234a835dea604783cea0bd9d28a40de654ec03d`
- exact implementation/test/CI head: `79f7b07dec8e86576f7df66c588ca3b55b278922`
- implementation-status synchronization: `97d63fdef0d9437a8ee0dd640b16312be64eab63`
- branch HEAD immediately before this HANDOFF commit: `97d63fdef0d9437a8ee0dd640b16312be64eab63`
- PR #6: draft/open/unmerged, base `main`, head `dev/zn-agent`
- `main` was not modified
- no force push or history rewrite was requested or performed

A HANDOFF commit cannot contain its own resulting SHA. Re-read `dev/zn-agent` after this file is committed and use that exact head externally.

## Completed in this stage

### Eleventh crash window: observed compiled-capability failure before native investigation

The real active call chain is:

```text
provider_bridge.build_resident_runtime*
-> CapabilityRecoveryResidentRuntime._orient_step()
-> CapabilityRegistry.resolve()
-> journaled capability execution
-> capability_execution.status=observed
-> known failure evidence
-> native_investigation
```

Before this stage, only durable observed capability success had explicit restart ownership. A returned capability failure was persisted as `observed`, but restart could ignore that durable fact, enter ordinary memory/capability matching again, execute compiled code again, and duplicate `observe_native_outcome(... success=False)` evidence.

The active product now owns the failure interval explicitly:

```text
capability returns known failure
-> atomically persist durable observed result
-> ResidentAccountingJournal.record_native_capability_failure()
-> persist native_investigation continuation
-> continue investigation
```

Key semantics:

- observed known failure is resumed before memory recall or capability resolution;
- failure accounting is gated by `resident_event_accounting(event_id, native_capability_failure)`;
- a crash after accounting but before the investigation checkpoint can safely re-enter accounting without duplicate self-model evidence;
- capability failure is intermediate evidence, so this accounting does not increment `runtime_metrics.tasks_total`;
- `outside_world_effect_uncertain` remains recovery/uncertainty and is rejected if code attempts to convert it into known failure evidence;
- malformed durable `observed` result truth fails closed with `RuntimeError` instead of falling through to replay.

New implementation/test commits:

```text
861533bcf05b4f15289305452011721972fddf73  feat: make capability failure accounting idempotent
ce90a747eef4340d154db0e3ee24ad15bf226759  fix: resume observed capability failures safely
d71fd35ed0a1fb3de16d83035cef26c0407f13f0  test: prove observed capability failure recovery
e61a6749e4478af90cee63cdfa61291f58af7432  ci: cover capability failure restart recovery
08c74058061d612ba8d478d67f211a56edc50d20  fix: fail closed on malformed observed capability result
79f7b07dec8e86576f7df66c588ca3b55b278922  test: fail closed on malformed capability observation
```

Regressions in `tests/zn_agent/core/test_capability_failure_recovery.py`:

```text
test_observed_failure_resumes_without_code_or_duplicate_failure_learning
test_malformed_observed_result_fails_closed_without_replay
```

The first simulates crash after failure accounting but before `native_investigation` persistence, restarts without capability code, makes memory recall/capability resolution fatal, and verifies one failure-evidence update with no task-total increment. The second proves malformed durable observed truth cannot reopen execution.

### Earlier ten windows

The prior ten verified slices remain closed, including compiled-capability durable `started`/`observed` ownership, default non-replayability, side-effect uncertainty recovery, successful observed-result resume, and event-idempotent successful capability accounting through `resident_completion`.

## Real test / CI truth

Exact implementation/test/CI proof for `79f7b07dec8e86576f7df66c588ca3b55b278922`:

```text
ZN Work Recovery E2E run 33103741459                 success
Windows resident Work restart recovery                success
Compile Work recovery path                            success
Verify durable Work progress and restart recovery     success

ZN CI run 33103741461                                 success
ZN Kernel / Python / Windows                          success
  Boot isolated ZN distribution without a model       success
  Compile resident core                               success
  Run ZN core tests against working tree              success
ZN Source Boundary / Windows                          success
Electron / TypeScript / Windows                       success
Publish Windows CI statuses                           success
```

The focused recovery workflow explicitly includes `test_capability_failure_recovery.py`. The ordinary Kernel job passed the full working-tree core test suite.

No local repository test run is claimed: the available execution container does not have a reachable repository checkout. Repository self-hosted Windows CI is the verification authority.

## Current risks / incomplete work

- broader Work durability remains partial beyond eleven verified crash windows;
- `_deliberation_step()` impasse/budget failure still performs failure/Life/runtime accounting without a dedicated durable resumable terminal-failure completion contract;
- the outer `run_once()` exception path can still account unresolved failure before terminal `EventOutcome` publication without a dedicated resumable checkpoint;
- structured-memory success still performs self-model/runtime accounting before its completion checkpoint; only restart after durable `resident_completion` is proven there;
- external cognition success/failure completion crash boundaries remain unproven;
- Body and compiled capability recovery share `resident_side_effect_attempts` durable truth but low-level helper implementation is not fully consolidated;
- direct synchronous driving while unresolved `side_effect_recovery` persists deserves separate lifecycle review; do not turn uncertainty into replay/failure merely to terminate a synchronous call;
- no deliberate outcome-trace rewrite/compactor exists; destructive long-term-memory migration still requires separate review and explicit approval;
- Windows M8 continuity remains incomplete;
- browser PRESS, broader click/editing/multi-select/page lifecycle remain incomplete;
- authenticated User Browser Bridge control remains incomplete;
- SM1+ self-maintenance remains incomplete;
- identity, long-term memory, credentials/permissions, updater/signing, rollback and destructive self-maintenance remain high-risk approval boundaries.

## Task queue

### P1 - broader Work durability

Status: **OPEN / ELEVEN CRASH WINDOWS VERIFIED / ACTIVE**

Next real target: trace terminal failure ownership through `_deliberation_step()` impasse/budget failure and the outer `run_once()` exception path. Establish durable failure completion/checkpoint truth before non-idempotent Life/self-model/runtime accounting so restart cannot duplicate failure evidence or terminal publication. Outside-world uncertainty must remain separate from known failure.

After that, prove structured-memory pre-completion accounting and external-cognition success/failure completion boundaries independently.

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
runtime/python/zn_agent/core/resident.py
runtime/python/zn_agent/core/provider_bridge.py
tests/zn_agent/core/test_resident_native_completion_recovery.py
tests/zn_agent/core/test_capability_failure_recovery.py
.github/workflows/zn-work-recovery-e2e.yml
docs/ZN-IMPLEMENTATION-STATUS.md
.agent/HANDOFF.md
```

## Next real target

Re-read current branch, PR/CI and active caller chain before modification. Prioritize terminal failure completion ownership in `_deliberation_step()` and outer `run_once()`. Keep broader Work durability marked PARTIAL, preserve uncertainty vs failure semantics, and keep `main` untouched during ordinary development.
