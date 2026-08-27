# ZN Agent Handoff

Updated: 2026-08-27

## Current goal

Continue the bounded broader-Work durability audit after verifying eighteen concrete crash/restart windows **and** the direct synchronous `side_effect_recovery` caller lifecycle.

The newest slice closes the previously-open caller-termination gap without changing outside-world uncertainty semantics: direct synchronous callers now yield control when replay is blocked and an explicit recovery decision is required, while asynchronous resident life remains alive, exact read-only reverification can still progress, and explicit cancellation remains lifecycle authority.

Broader Work durability remains **PARTIAL**. The next real target is the shared low-level `resident_side_effect_attempts` persistence helper boundary used by Body and compiled capability recovery.

Founding boundary remains:

> **ZN uses models. Models do not own ZN.**

## Branch / repository truth

- repository: `9529360-cpu/znagent`
- development branch: `dev/zn-agent`
- canonical source/release branch: `main`
- canonical `main`: `8234a835dea604783cea0bd9d28a40de654ec03d`
- exact implementation/test/CI proof head: `7b88494d8f6ef8974ca256ef6772754dec523310`
- implementation-status synchronization commit: `a2f295cff2dadbd07ac53dcbe8a28d1be972ad2f`
- branch HEAD immediately before this HANDOFF commit: `a2f295cff2dadbd07ac53dcbe8a28d1be972ad2f`
- PR #6 remains the development PR from `dev/zn-agent` to `main`
- `main` was not modified
- no force push or history rewrite was requested or performed

A HANDOFF commit cannot contain its own resulting SHA. Re-read `dev/zn-agent` after this file is committed and use that exact head externally.

## Completed in this stage

### Synchronous recovery-control boundary

Real active callers audited:

```text
provider_bridge.build_resident_runtime()
-> RecoveryBoundedResidentRuntime
   -> direct run_once(thought=None)
   -> resident.submit()
-> RecoveryBoundedWorkLedger
   -> legacy synchronous Work submit
-> ResidentRpcServer.work_submit

normal desktop Work:
work_start
-> background resident life loop
-> work_progress / work_cancel
```

The normal desktop path was already asynchronous. The real gap was that still-callable synchronous faces could keep pulsing forever after a Work reached replay-blocked `side_effect_recovery` awaiting an explicit decision.

`recovery_control.py` now defines `ResidentRecoveryRequired` as a caller-control condition, not task failure. It applies only when durable truth says:

```text
stage=side_effect_recovery
blocked_by=outside_world_effect_uncertain
replay_blocked=true
decision != reverify_effect
```

`reverify_effect` remains allowed because it uses read-only evidence and can safely make progress without replaying the side effect.

### Single resident loop preserved

`RecoveryBoundedResidentRuntime` was deliberately refactored away from an early copied `run_once()` implementation. The final design uses a thread-local synchronous control scope plus an `_advance_event_step()` hook and delegates to the existing resident owner loop.

Consequences:

- direct `run_once(thought=None)` yields when explicit recovery control is required;
- `resident.submit()` uses the same boundary;
- ordinary one-step/asynchronous resident life does not throw and can remain alive around blocked Work;
- `resident.submit()` checks an already-blocked active event before enqueueing, so a caller cannot receive an exception while silently creating a second queued task;
- yielding does not publish terminal `EventOutcome`, does not replay the side effect, and does not change the durable recovery fact.

### Legacy synchronous Work/RPC handoff

`RecoveryBoundedWorkLedger` wraps the existing Work submit logic in the same synchronous recovery-control scope rather than copying Work execution.

If that synchronous Work itself reaches replay-blocked uncertainty, `ResidentRpcServer.work_submit` returns structured control state for the same Work:

```text
recovery_required=true
progress.stage=side_effect_recovery
progress.terminal=false
progress.finalized=false
```

Existing `work_progress` and `work_cancel` remain the control surfaces. Explicit cancellation still atomically publishes a cancelled CONTROL outcome, clears Work ownership, and marks the unresolved attempt `work_abandoned` without asserting whether the outside-world effect happened.

### Restart/control proof

`tests/zn_agent/core/test_synchronous_recovery_control.py` proves:

- direct sync `run_once()` yields without terminalizing or replaying;
- one-step resident life keeps the recovery alive without throwing;
- sync `resident.submit()` refuses hidden enqueue behind an existing blocked event;
- restart preserves the same yield boundary and explicit cancellation remains available;
- legacy RPC `work_submit` returns recovery progress for its own blocked Work and a later `work_cancel` closes lifecycle ownership atomically;
- read-only `reverify_effect` is not treated as an explicit-control block.

This is recorded as an additional verified lifecycle boundary, not an artificial nineteenth crash/restart window. The crash-window count remains eighteen.

## Key commits

```text
c812154b75bab5b2020c2020099df5028c10b812  refactor: reuse resident loop for sync recovery control
a200fcec16a429fdd65fce10f403f97b249070ff  feat: bound synchronous Work recovery driving
c26152175436b0d84a563437cae9f25466453eb4  feat: return blocked Work recovery to sync RPC callers
68447fea5bbda5b96a4e2a29a49f14c5fb625a82  test: prove synchronous Work recovery handoff
7b88494d8f6ef8974ca256ef6772754dec523310  ci: cover synchronous Work handoff
a2f295cff2dadbd07ac53dcbe8a28d1be972ad2f  docs: record synchronous recovery lifecycle
```

Related implementation files:

```text
runtime/python/zn_agent/core/recovery_control.py
runtime/python/zn_agent/core/recovery_bounded_resident.py
runtime/python/zn_agent/core/recovery_bounded_work.py
runtime/python/zn_agent/core/provider_bridge.py
runtime/python/zn_agent/core/daemon.py
tests/zn_agent/core/test_synchronous_recovery_control.py
.github/workflows/zn-work-recovery-e2e.yml
```

## Real test / CI truth

Exact implementation/test/CI proof for `7b88494d8f6ef8974ca256ef6772754dec523310`:

```text
ZN Work Recovery E2E run 33114819916                 success
Windows resident Work restart recovery                success
Compile Work recovery path                            success
Verify durable Work progress and restart recovery     success
  synchronous recovery lifecycle regressions          success

ZN CI run 33114819943                                 success
ZN Kernel / Python / Windows                          success
  Boot isolated ZN distribution without a model       success
  Compile resident core                               success
  Run ZN core tests against working tree              success
ZN Source Boundary / Windows                          success
Electron / TypeScript / Windows                       success
Publish Windows CI statuses                           success
```

An intermediate general-CI run on `a200fcec16a429fdd65fce10f403f97b249070ff` was superseded/cancelled during the later branch pushes and is not used as proof.

No local repository test run is claimed for this stage. Repository self-hosted Windows CI is the verification authority.

## Current risks / incomplete work

- broader Work durability remains partial beyond eighteen verified crash/restart windows plus the verified synchronous recovery lifecycle;
- Body and compiled capability recovery share the same `resident_side_effect_attempts` table/truth, but low-level schema/query/start/observe/finish/prune helpers are still partly duplicated;
- consolidation must preserve historical durable signature/hash semantics: Body and compiled-capability identities are not currently encoded the same way, so do not normalize them casually during refactor;
- continue the bounded backward audit for other cumulative accounting/learning writes that may precede durable semantic facts;
- no deliberate outcome-trace rewrite/compactor exists; destructive long-term-memory migration remains a separate approval boundary;
- explanatory-comment cleanup in `intentional_resident.py` remains non-behavioral debt;
- Windows M8 continuity, browser PRESS/broader interaction lifecycle, authenticated User Browser Bridge control, and SM1+ remain incomplete;
- identity, long-term memory, credentials/permissions, updater/signing, rollback and destructive self-maintenance remain high-risk approval boundaries.

## Task queue

### P1 - shared side-effect-attempt persistence owner

Status: **OPEN / NEXT**

Trace both active callers before modification:

```text
SideEffectAwareBody
-> resident_side_effect_attempts
-> dispatch/observe/finish/recovery/cancel/prune

compiled capability recovery
-> ResidentSideEffectJournal
-> resident_side_effect_attempts
-> dispatch/observe/finish/recovery/cancel/prune
```

Goals:

1. prove table/schema and lifecycle truth are genuinely shared;
2. identify duplicated low-level helpers versus intentionally different identity/signature rules;
3. consolidate only safe persistence plumbing without creating a second truth model or changing historical hashes;
4. add compatibility/restart tests for both Body and compiled capability callers;
5. run focused recovery CI and full ZN CI before updating status again.

### P2 - continued bounded backward durability audit

Status: **OPEN**

After the helper boundary is proven, continue backward from cumulative accounting/learning writes and verify durable semantic facts precede recoverable cumulative state.

### P3 - browser / M8 / SM1+

Status: **OPEN**

PRESS, broader interaction lifecycle, authenticated User Browser Bridge control, Windows M8 continuity and SM1+ remain incomplete. Preserve human approval for high-risk identity, memory, credentials, updater/signing, rollback and destructive self-maintenance changes.

## Next real target

Re-read current branch, PR/CI and active Body/capability side-effect call chains before modifying the shared helper. Keep broader Work durability marked PARTIAL and keep `main` untouched during ordinary development.
