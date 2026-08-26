# ZN Agent Handoff

Updated: 2026-08-26

## Current goal

The reachable explicit cancellation slice for unverifiable outside-world effects is now implemented through the real ZN control chain. The next resident-level consistency target is **post-completion Life observation recovery**: a durable event/Work outcome must remain terminal truth even if a later resident self-observation step fails and needs repair.

Do not broaden cancellation into arbitrary in-flight action cancellation. Do not treat a user decision to stop Work as evidence that an outside-world effect happened or did not happen.

Do not spend the next stage on the deferred Windows NetworkService DOS-8.3 path-identity defect unless it materially blocks the active product objective or is explicitly reprioritized.

Founding boundary remains:

> **ZN uses models. Models do not own ZN.**

## Branch / repository truth

- repository: `9529360-cpu/znagent`
- fixed development branch: `dev/zn-agent`
- canonical source/release branch: `main`
- latest implementation checkpoint before this HANDOFF update: `5c679ea742a2c83578c85c215cf582ce8c22a8cf`
- implementation-status synchronization commit before this HANDOFF update: `8f79b609e3014661d0f1f14c8ade40fff7d5db87`
- atomic cancellation primitive: `6c655c761099cc6a206028285cc228d65f3e7734`
- focused reachable-cancellation workflow checkpoint: `0be9340e2db305be7134d403a1ecdf392a7f36b4`
- canonical `main`: `8234a835dea604783cea0bd9d28a40de654ec03d`
- PR #6: draft/open/unmerged, base `main`, head `dev/zn-agent`
- `main` was not modified
- no force push or history rewrite was used

A HANDOFF commit cannot contain its own resulting SHA. Re-read `dev/zn-agent` after this file is committed and use the resulting exact head externally.

## Completed in current stage

### 1. Atomic uncertain-Work cancellation remains the authority

`KernelStore.cancel_uncertain_event()` remains narrow and fail-closed. It accepts only an unfinished event whose resident checkpoint is an active replay-blocked `side_effect_recovery`, whose started side-effect attempt belongs to the same event, and for which no durable outcome already exists.

One SQLite transaction performs:

```text
side-effect attempt -> work_abandoned
event -> terminal
EventOutcome.cancelled = true
EventOutcome.execution_path = control
WorkingState -> idle
```

`work_abandoned` is non-epistemic. It means ZN stops continuing that Work; it does not claim whether the uncertain external effect occurred.

### 2. Resident and Will cancellation semantics are explicit

Relevant checkpoints:

```text
1024752da9741326cf133e27c51358e45b9f6ef2  Will cancelled semantics
01a4a645e68bda87d74697af0fd9aacb9181e96b  Resident cancellation authority
```

Cancellation bypasses ordinary Life action-failure observation. `NativeWill` consumes explicit cancelled outcomes directly and during restart reconciliation, so cancellation is not reconstructed as `step_failed`, successful completion, or failure-learning evidence.

### 3. Work-level cancellation authority is resident-owned

Relevant checkpoints:

```text
1ad68ddb5f2e423ea02d249553aa404c98266b2d  Resident Work cancellation control
4cf85f33a6c000f31ed839e405bd2bb978e8d83e  work_cancel RPC
c47887bbeb5e02fe89fc4b30bd0494c329df8e83  reconciliation connection cleanup
55d6922bc0cf51a05939ced26fe4386cd5f4cc48  reachable cancellation regression coverage
0be9340e2db305be7134d403a1ecdf392a7f36b4  focused workflow coverage
```

`ResidentWorkControl` verifies thread/event ownership, invokes resident cancellation authority, reconciles cancellation/finalization crash windows, publishes public `status/stage = cancelled`, and finalizes the Work without ordinary `failed: true` semantics or fabricated artifacts for an uncertain effect.

### 4. Electron and renderer chain is wired

Relevant checkpoints:

```text
4f29aa71e8b7d8b35522360d22b79c9177b22dd7  Electron IPC bridge
ad9998892cde6ee366d0181aece6c68fd5f5329d  preload bridge
48ececc7d9f8a48e83097cf38f1158b1d8ab27a1  desktop bridge typing
510b2e6219763180f8177847619bc9795f612d56  recovery normalization + cancelZnWork
831bba875e77ecddd338bb2b464844171b479e93  resident RPC method typing
5c679ea742a2c83578c85c215cf582ce8c22a8cf  Workbench control + ownership regression
```

The Workbench exposes `Stop work` only when the resident-provided sanitized recovery projection has `replayBlocked === true`.

The UI states that the outside-world effect is uncertain, that ZN will not replay the action automatically, and that stopping Work prevents further ZN action without undoing or proving what already happened outside ZN.

The renderer requests cancellation; it never becomes cancellation authority.

### 5. Desktop ownership regression was extended

`apps/desktop/electron/zn-desktop-ownership.test.ts` now checks the cancellation chain across:

```text
ZnResidentProcess work_cancel method typing
Electron IPC work_cancel
preload workCancel
resident-client normalizeWorkRecovery + cancelZnWork
Workbench recovery-only Stop work presentation
```

It continues to reject renderer fake-progress authority and inherited desktop control-plane dependencies.

## Real test / CI truth

### Focused reachable cancellation proof

```text
ZN Work Recovery E2E run 33016402296
head 0be9340e2db305be7134d403a1ecdf392a7f36b4
conclusion success
```

This run includes `test_work_cancel_control.py` in the focused Work recovery workflow.

Earlier atomic Store cancellation proof remains:

```text
ZN Work Recovery E2E run 33014912312
head 6c655c761099cc6a206028285cc228d65f3e7734
conclusion success
```

### Current reachable-desktop ordinary CI

```text
ZN CI run 33017359211
head 5c679ea742a2c83578c85c215cf582ce8c22a8cf
```

Verified at HANDOFF synchronization time:

```text
Electron / TypeScript / Windows    success
  Typecheck Electron desktop       success
  independent ZN bundle            success
  desktop ownership/packaged/update/handoff tests  success
  release/runtime/package verifier tests           success
ZN Source Boundary / Windows       success
ZN Kernel / Python / Windows       still running
```

The preceding `510b2e` run exposed the missing `work_cancel` member in the Electron resident request union. `831bba87` fixed that exact defect; its Electron job passed before the newer head superseded the remaining jobs. The current `5c679ea7` Electron job passes independently with the Workbench cancellation control and updated ownership regression included.

Do not call ordinary CI green while the current Kernel job is unfinished or failing.

### Known ordinary Kernel failure family

A prior exact run remains:

```text
ZN CI run 33014912300
head 6c655c761099cc6a206028285cc228d65f3e7734
Electron / TypeScript / Windows    success
ZN Source Boundary / Windows       success
ZN Kernel / Python / Windows       failure
Kernel                             573 tests / 16 errors / 5 skipped
```

The 16 errors are the known Windows NetworkService DOS-8.3 versus long-path identity family affecting repository targeted-test/text-delta verification and terminal/Work artifact cwd identity. Cleanup `PermissionError` traces are secondary fallout after those assertions fail.

The prior partial path fix was reverted normally in `db647cb49c3de014aa82bc28ec87c1c4e5b02c15`; no half-fix remains.

## Current risks / blockers

- Reachable uncertain-effect cancellation is implemented and its focused/backend + desktop ownership paths are verified, but ordinary Kernel CI is not currently green.
- The Windows NetworkService DOS-8.3 path-identity family remains known/deferred.
- Durable event completion followed by failed Life self-observation is still a separate consistency gap; terminal event truth must not be weakened to solve it.
- The cancellation UI is intentionally recovery-only; there is no claim that ZN can safely interrupt arbitrary effects already executing outside ZN.
- Browser PRESS/broader click/editing/multi-select/lifecycle, authenticated User Browser Bridge control, M8 continuity, and SM1+ remain incomplete.
- High-risk identity, long-term memory, credentials/permissions, updater/signing, rollback, and destructive self-maintenance changes still require human approval.
- `main` remains untouched.

## Task queue

### P0 - post-completion Life observation recovery

Status: **NEXT REAL TARGET**

Trace the real completion call chain and separate these facts cleanly:

```text
event/Work terminal outcome is already durable
-> later Life self-observation may fail independently
-> observation repair must be durable/retryable without reopening or falsifying event completion
```

Before modifying code, inspect:

```text
Resident._complete_result
IntentionalResident._complete_result
life.observe_action / resident Life persistence
EventOutcome publication ordering
restart reconstruction callers/tests
```

Required invariant:

```text
durable event truth does not roll back because later self-observation failed
self-observation failure is visible and repairable
restart does not duplicate the completed outside-world action
models never become completion or recovery authority
```

### P1 - deferred Windows DOS-8.3 path identity

Status: **KNOWN / DEFERRED**

Resume only if explicitly reprioritized or materially blocking the active product objective.

### P2 - browser follow-ons

Status: **OPEN / NOT CURRENT MAJOR TARGET**

PRESS, broader click semantics, richer text editing, multi-select, broader page/target lifecycle, and authenticated User Browser Bridge control remain open.

### P3 - M8 / SM1+

Status: **OPEN**

Preserve human approval for high-risk identity, memory, credentials, updater/signing, rollback, and destructive self-maintenance changes.

## Related files

```text
runtime/python/zn_agent/core/models.py
runtime/python/zn_agent/core/store.py
runtime/python/zn_agent/core/resident.py
runtime/python/zn_agent/core/intentional_resident.py
runtime/python/zn_agent/core/will.py
runtime/python/zn_agent/core/work.py
runtime/python/zn_agent/core/work_control.py
runtime/python/zn_agent/core/daemon.py
tests/zn_agent/core/test_work_cancellation.py
tests/zn_agent/core/test_work_cancel_control.py
tests/zn_agent/core/test_native_will.py
.github/workflows/zn-work-recovery-e2e.yml
apps/desktop/electron/zn-resident-process.ts
apps/desktop/electron/zn-resident-ipc.ts
apps/desktop/electron/zn-preload.ts
apps/desktop/electron/zn-desktop-ownership.test.ts
apps/desktop/src/zn/desktop-env.d.ts
apps/desktop/src/zn/resident-client.ts
apps/desktop/src/zn/workbench.tsx
docs/ZN-IMPLEMENTATION-STATUS.md
.agent/HANDOFF.md
```

## Next real target

Investigate and harden post-completion Life observation recovery without reopening durable event truth or replaying outside-world work. Keep `main` untouched.
