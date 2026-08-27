# ZN Agent Handoff

Updated: 2026-08-27

## Current goal

Trace and define nervous receipt/trace lifecycle robustness before any pruning or compaction implementation. The Windows NetworkService DOS-8.3 versus long-path identity family is closed at the full owner chain and ordinary CI is green.

`EventOutcome` remains terminal truth. Nervous plasticity remains secondary. A nervous failure after terminal completion does not reclassify the event and does not replay the action. `NativeWill` keeps its existing durable outcome reconciliation authority.

Generic nervous `perceive()` remains intentionally plastic and non-idempotent. Do not generalize the event-ID guarantee into a global exactly-once claim.

The next target is investigation/specification first: determine how `neural_event_outcomes.trace_id` survives a future deliberate trace prune/rewrite while preserving event-ID dedupe and restart idempotence. Do not perform a destructive long-term-memory migration without explicit human approval.

Founding boundary remains:

> **ZN uses models. Models do not own ZN.**

## Branch / repository truth

- repository: `9529360-cpu/znagent`
- development branch: `dev/zn-agent`
- canonical source/release branch: `main`
- canonical `main`: `8234a835dea604783cea0bd9d28a40de654ec03d`
- nervous code/test checkpoint: `ba06e08561cc73bcd8afc61b444b860c45bfb376`
- completion journal owner cleanup: `c54bb8c37385d98fc9688b6e89839d7a5cba6df6`
- Windows path owner checkpoint: `0c011a2473c581e6517a882343208d6efe47cac1`
- Windows evidence/learning checkpoint: `e3fc20b7b4271e46868f408c258cab58ba014abb`
- current code/test HEAD when this handoff was prepared: `e3fc20b7b4271e46868f408c258cab58ba014abb`
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

### 7. Windows path identity closed across the full active chain

`canonical_host_path()` expands DOS 8.3 components in the longest existing Windows prefix and reattaches missing suffix components without resolving symlinks or reparse points. Canonical identity is now established and carried through:

```text
event/context entry
-> Investigation path facts and previews
-> action path/workdir matching
-> Body / Terminal
-> Git root senses / Work workspace state
-> verification / procedural applicability and experience fingerprints
-> active resident callers
```

The first implementation checkpoint removed the historical 16 repository/terminal/Work errors. Its ordinary CI exposed the remaining Investigation/action evidence split; `e3fc20b7...` fixed that owner boundary. Existing strict real-path containment remains fail-closed for symlink/reparse escapes.

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

### Windows path identity local proof

```text
DOS 8.3 TEMP/TMP coverage group  33 tests / OK / 1 symlink privilege skip
CI-equivalent full core discovery 594 tests / OK / 5 skips
```

### Ordinary CI

The current code-checkpoint result is:

```text
ZN CI run 33047823223
head e3fc20b7b4271e46868f408c258cab58ba014abb
Electron / TypeScript / Windows    success
ZN Source Boundary / Windows       success
ZN Kernel / Python / Windows       success
Kernel                             594 tests / 5 skipped / OK
```

The preceding code checkpoint was intentionally not hidden:

```text
ZN CI run 33046424920
head 0c011a2473c581e6517a882343208d6efe47cac1
Kernel 594 tests / 4 failures / 6 errors / 5 skipped
```

That run proved the old 16 failures were gone and exposed the remaining evidence/action split. The follow-up fixed it. Additional code-checkpoint evidence:

```text
ZN Windows Interactive Desktop E2E run 33047823208 success
ZN Work Recovery E2E run 33046424926               success at 0c011a24
```

The second evidence-only commit did not match the Work Recovery workflow's path trigger. Ordinary CI provides the exact-head full-core proof.

## Current risks / incomplete work

- Several explanatory comments in `intentional_resident.py` were accidentally lost during the whole-file owner replacement. Diff review found no corresponding behavioral deletion; restoring those comments remains cleanup.
- Event receipts currently point to trace IDs. If future neural pruning/compaction deliberately removes a referenced outcome trace, receipt/trace lifecycle semantics need an explicit policy rather than silent guessing.
- Generic nervous `perceive()` remains intentionally plastic and is not safe for blind replay. Only the durable terminal EventOutcome path has event-ID dedupe semantics.
- Broader Work durability remains partial outside the proven cancellation, Life-observation, and nervous-outcome slices.
- Browser PRESS/broader click/editing/multi-select/lifecycle, authenticated User Browser Bridge control, M8 continuity, and SM1+ remain incomplete.
- High-risk identity, long-term memory, credentials/permissions, updater/signing, rollback, and destructive self-maintenance changes still require human approval.
- `main` remains untouched.

## Blockers

No blocker prevents the next read-only lifecycle trace and policy specification. Any destructive identity or long-term-memory migration discovered to be necessary must stop for explicit human approval.

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

Status: **COMPLETE / ORDINARY CI VERIFIED**

Full entry/evidence/action/state/dependency/verification caller chain uses one lexical Windows identity; strict containment safety remains separate and fail-closed.

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
runtime/python/zn_agent/core/path_context.py
runtime/python/zn_agent/core/action.py
runtime/python/zn_agent/core/investigation.py
runtime/python/zn_agent/core/body.py
runtime/python/zn_agent/core/terminal.py
runtime/python/zn_agent/core/work.py
runtime/python/zn_agent/core/procedural_applicability.py
runtime/python/zn_agent/core/verified_experience.py
tests/zn_agent/core/test_event_outcome_nervous.py
tests/zn_agent/core/test_event_outcome_nervous_recovery.py
tests/zn_agent/core/test_completion_observation_recovery.py
tests/zn_agent/core/test_completion_observation_embodied.py
tests/zn_agent/core/test_workspace_file_context.py
tests/zn_agent/core/test_repo_targeted_test_verification.py
.github/workflows/zn-work-recovery-e2e.yml
docs/ZN-IMPLEMENTATION-STATUS.md
.agent/HANDOFF.md
```

## Next real target

Trace the neural event receipt to trace/pruning lifecycle and define a fail-closed durable policy before implementation. Any destructive long-term-memory migration requires explicit human approval. Keep `main` untouched.
