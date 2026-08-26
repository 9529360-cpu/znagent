# ZN Agent Handoff

Updated: 2026-08-27

## Current goal

Close the Windows NetworkService DOS-8.3 versus long-path identity family that keeps exact-head ordinary CI red. The low-risk completion journal ownership cleanup is complete: `EmbodiedResidentRuntime` is the single richer-resident birth/lifecycle owner; `FocusedModernTextResidentRuntime` no longer reconstructs or re-repairs the same journal and still projects sanitized completion-observation health through `status()`.

`EventOutcome` remains terminal truth. Nervous plasticity remains secondary. A nervous failure after terminal completion does not reclassify the event and does not replay the action. `NativeWill` keeps its existing durable outcome reconciliation authority.

Generic nervous `perceive()` remains intentionally plastic and non-idempotent. Do not generalize the event-ID guarantee into a global exactly-once claim.

The next real target is now the Windows NetworkService DOS-8.3 versus long-path identity family because exact-head ordinary CI remains red. The repair must cover the full identity call chain and preserve fail-closed symlink/reparse-point semantics; do not restore the prior partial `path_context.py`-only attempt.

Founding boundary remains:

> **ZN uses models. Models do not own ZN.**

## Branch / repository truth

- repository: `9529360-cpu/znagent`
- development branch: `dev/zn-agent`
- canonical source/release branch: `main`
- canonical `main`: `8234a835dea604783cea0bd9d28a40de654ec03d`
- nervous code/test checkpoint: `ba06e08561cc73bcd8afc61b444b860c45bfb376`
- completion journal owner cleanup: `c54bb8c37385d98fc9688b6e89839d7a5cba6df6`
- implementation-status sync: `d7f940651bc3896853dff91acfcb0b9e04f511c6`
- PR #6: draft/open/unmerged, base `main`, head `dev/zn-agent`
- `main` was not modified
- no force push or history rewrite was requested or performed by the maintainer

A HANDOFF commit cannot contain its own resulting SHA. Re-read `dev/zn-agent` after this file is committed and use that exact head externally.

## Completed in this stage

### 1. Actual nervous transaction boundary traced

The durable completion chain is:

```text
resident completion
-> KernelStore.complete_event(...)
-> terminal event + durable EventOutcome
-> Life completion observation journal
-> Intentional secondary nervous outcome perception
-> NativeWill outcome observation when applicable
```

`NativeWill` already runs `will.reconcile_outcomes()` during construction and remains the Will authority.

The old `PersistentNervousSystem.perceive("outcome", ...)` could not be safely replayed because one call committed trace, links, and affect independently, and a repeated matching perception intentionally strengthens all of them.

### 2. Event-identity-safe outcome plasticity implemented

New `runtime/python/zn_agent/core/event_outcome_nervous.py` owns the durable EventOutcome plasticity transaction.

For one durable event identity, one `BEGIN IMMEDIATE` transaction covers:

```text
event receipt / dedupe identity
trace insert or reinforcement
recent co-active neural-link reinforcement
affect / nervous_state update
```

The active nervous object's in-memory affect changes only after commit.

The durable tables are:

```text
neural_event_outcomes(event_id PRIMARY KEY, trace_id, perceived_at)
neural_event_outcome_state(id=1, repair_from)
```

The first installation records `repair_from`. Restart repair only considers terminal outcomes created after that cutoff, because pre-feature outcomes may already have affected legacy nervous memory without receipts. ZN does not guess whether old history was seen.

Event identity is separate from semantic trace identity:

- same event ID after commit is a full plasticity no-op;
- distinct events with the same outcome can still reinforce the same trace as separate lived evidence.

### 3. Final nervous owner corrected instead of hidden behind a builder shim

Focused CI exposed that the final product later replaces the lower nervous object with `IntegratedTransferNervousSystem` through the richer transfer resident construction chain.

The repair was not put into provider bridge and did not create a second neural authority. Event-outcome operations accept the active `PersistentNervousSystem` instance and mutate the real final owner directly. This preserves richer transfer/reality-aware nervous behavior while adding event identity to the terminal-outcome path.

### 4. Crash/restart ambiguity is tested at both substrate and product levels

Direct regressions verify:

- same event ID does not increment repetitions twice;
- same event ID does not strengthen links twice;
- same event ID does not integrate affect twice;
- two distinct same-result event IDs still reinforce;
- forced failure immediately before commit rolls back trace, links, affect, and receipt;
- retry after restart commits exactly one lived outcome.

Product regression verifies:

```text
terminal EventOutcome commits
-> forced nervous failure before nervous commit
-> _complete_result still returns completed event
-> nervous receipt remains missing
-> resident restart repairs only perception
-> second restart does not reinforce again
```

The completed action is never replayed by nervous repair.

### 5. Focused workflow now proves the new path

`.github/workflows/zn-work-recovery-e2e.yml` now triggers on and compiles the event-outcome nervous/Intentional path and runs both new nervous regression modules together with the existing Work/completion suite.

Relevant checkpoints:

```text
ae5996eb005d16262a4a44e93a79236d8d0f5703  atomic nervous EventOutcome substrate
10ad29e32555f17493e58bea108cfdd54c86bc04  activation cutoff
4e616d8a323e99adec11a0815b6a602ac5dbcd25  Intentional outcome reconciliation
26de35ef690f4eecdee0fd02cd88cf314f6d619e  resident event identity wiring
754f3cc6258b2fdae0311748fa0f8d6c42f52143  product crash/restart regression
a576afca7f61432d827882cc6b4a7005fc385aa5  focused workflow coverage
c72f9348f0a0485483f5cc35554b0bc2c3060f00  active nervous operation refactor
75c7c303a4ed2fa8fbec8e5dfee2066d03baf949  final nervous owner integration
90a24a4bff07735a95d7a73783518f2cdd4c4044  final-owner product assertions
ba06e08561cc73bcd8afc61b444b860c45bfb376  final focused test fix/checkpoint
```

### 6. Completion journal ownership cleanup completed

`FocusedModernTextResidentRuntime` no longer imports or constructs `CompletionObservationJournal`. The Embodied birth root installs and repairs the organ once. The final product layer continues to expose `status()["completion_observations"]`.

`test_modern_text_resident_ownership` now proves the product construction calls `repair_life()` exactly once and preserves the status projection. The Work Recovery workflow triggers on and executes this regression.

## Real test / CI truth

### Focused nervous/Work proof

```text
ZN Work Recovery E2E run 33023392867
head c54bb8c37385d98fc9688b6e89839d7a5cba6df6
Windows resident Work restart recovery             success
Prepare isolated runtime                            success
Compile Work recovery path                          success
Verify durable Work progress and restart recovery  success
Ran 44 tests in 9.798s                              OK
```

The 44 tests include the existing Work progress/restart/side-effect/cancellation and completion-observation suites plus:

```text
tests.zn_agent.core.test_modern_text_resident_ownership
tests.zn_agent.core.test_event_outcome_nervous
tests.zn_agent.core.test_event_outcome_nervous_recovery
```

### Ordinary CI

The current exact-head result is:

```text
ZN CI run 33023392907
head c54bb8c37385d98fc9688b6e89839d7a5cba6df6
Electron / TypeScript / Windows    success
ZN Source Boundary / Windows       success
ZN Kernel / Python / Windows       failure
Kernel                             592 tests / 16 errors / 5 skipped
```

Those 16 errors are the known Windows NetworkService DOS-8.3 versus long-path identity family. The partial path fix remains reverted in `db647cb49c3de014aa82bc28ec87c1c4e5b02c15`.

Additional exact-head evidence:

```text
ZN Managed Browser E2E run 33023392889             success
ZN Windows Interactive Desktop E2E run 33023392801 success on attempt 2 / 4 tests
```

Interactive attempt 1 lost foreground ownership to `warp.exe`; the clean rerun passed. Do not infer ordinary-CI success from the focused and E2E workflows.

## Current risks / incomplete work

- Several explanatory comments in `intentional_resident.py` were accidentally lost during the whole-file owner replacement. Diff review found no corresponding behavioral deletion; restoring those comments remains cleanup.
- Event receipts currently point to trace IDs. If future neural pruning/compaction deliberately removes a referenced outcome trace, receipt/trace lifecycle semantics need an explicit policy rather than silent guessing.
- Generic nervous `perceive()` remains intentionally plastic and is not safe for blind replay. Only the durable terminal EventOutcome path has event-ID dedupe semantics.
- Broader Work durability remains partial outside the proven cancellation, Life-observation, and nervous-outcome slices.
- Ordinary Windows Kernel CI remains historically red on the known/deferred path-identity family until the current ordinary run provides newer evidence.
- Browser PRESS/broader click/editing/multi-select/lifecycle, authenticated User Browser Bridge control, M8 continuity, and SM1+ remain incomplete.
- High-risk identity, long-term memory, credentials/permissions, updater/signing, rollback, and destructive self-maintenance changes still require human approval.
- `main` remains untouched.

## Task queue

### P0 - event-identity-safe nervous outcome perception

Status: **IMPLEMENTED / FOCUSED CI VERIFIED**

Do not broaden the guarantee beyond durable terminal EventOutcome perception.

### P0.1 - completion journal ownership cleanup

Status: **COMPLETE / FOCUSED CI VERIFIED**

Single richer birth-root owner; final status projection retained; regression runs in focused CI.

### P0.2 - nervous receipt lifecycle robustness

Status: **OPEN**

Define behavior when a future deliberate neural pruning/compaction pass encounters a trace referenced by `neural_event_outcomes`. Preserve event identity without pinning accidental implementation details forever.

### P1 - broader Work durability

Status: **OPEN**

Continue beyond the proven cancellation/Life/nervous secondary-observation slices without replaying uncertain outside-world effects.

### P1.1 - Windows path identity

Status: **NEXT / ORDINARY-CI BLOCKER**

Trace repository entry, owner, stored workspace/path state, lifecycle, Git/terminal dependencies, failing tests and active callers. Fix the full identity boundary without weakening alias/symlink safety.

### P2 - browser follow-ons

Status: **OPEN**

PRESS, broader click semantics, richer text editing, multi-select, broader page/target lifecycle, authenticated User Browser Bridge control.

### P3 - M8 / SM1+

Status: **OPEN**

Preserve human approval for high-risk identity, memory, credentials, updater/signing, rollback, and destructive self-maintenance changes.

## Related files

```text
runtime/python/zn_agent/core/event_outcome_nervous.py
runtime/python/zn_agent/core/intentional_resident.py
runtime/python/zn_agent/core/nervous_system.py
runtime/python/zn_agent/core/integrated_transfer.py
runtime/python/zn_agent/core/transfer_incubation.py
runtime/python/zn_agent/core/will.py
runtime/python/zn_agent/core/completion_observation.py
runtime/python/zn_agent/core/embodied_resident.py
runtime/python/zn_agent/core/focused_modern_text_resident.py
tests/zn_agent/core/test_event_outcome_nervous.py
tests/zn_agent/core/test_event_outcome_nervous_recovery.py
tests/zn_agent/core/test_completion_observation_recovery.py
tests/zn_agent/core/test_completion_observation_embodied.py
.github/workflows/zn-work-recovery-e2e.yml
docs/ZN-IMPLEMENTATION-STATUS.md
.agent/HANDOFF.md
```

## Next real target

Close the Windows NetworkService DOS-8.3 versus long-path identity family and obtain a genuinely green ordinary CI run. Keep `main` untouched.
