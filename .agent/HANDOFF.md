# ZN Agent Handoff

Updated: 2026-08-26

## Current goal

The recovery-only cancellation chain for unverifiable outside-world effects remains reachable and verified. The post-completion Life observation consistency gap is now hardened: durable event/Work outcome truth survives a later Life self-observation failure, pending Life observation is durably repairable, restart repairs observation without replaying the completed action, and generic post-completion exceptions return the existing durable outcome instead of reclassifying execution.

The next real target is **completion-observation health visibility plus IntentionalResident secondary post-processing audit**.

Do not broaden cancellation into arbitrary in-flight action cancellation. Do not treat Work cancellation as evidence that an outside-world effect happened or did not happen. Do not weaken terminal `EventOutcome` truth to repair secondary perception.

Do not spend the next stage on the deferred Windows NetworkService DOS-8.3 path-identity defect unless it materially blocks the active product objective or is explicitly reprioritized.

Founding boundary remains:

> **ZN uses models. Models do not own ZN.**

## Branch / repository truth

- repository: `9529360-cpu/znagent`
- fixed development branch: `dev/zn-agent`
- canonical source/release branch: `main`
- latest core implementation checkpoint before this HANDOFF update: `86895eda3397cf71d7f24b2d7d84d0c73c5e7220`
- focused completion-observation verification checkpoint: `6ac3dba5191aa5469bac0093bab15ca3e25b5d95`
- implementation-status synchronization commit before this HANDOFF update: `fad83603604dacc49a36971d4f9547fa505bedcc`
- cancellation UI checkpoint: `5c679ea742a2c83578c85c215cf582ce8c22a8cf`
- atomic cancellation primitive: `6c655c761099cc6a206028285cc228d65f3e7734`
- canonical `main`: `8234a835dea604783cea0bd9d28a40de654ec03d`
- PR #6: draft/open/unmerged, base `main`, head `dev/zn-agent`
- `main` was not modified
- no force push or history rewrite was used

A HANDOFF commit cannot contain its own resulting SHA. Re-read `dev/zn-agent` after this file is committed and use the resulting exact head externally.

## Completed in current stage

### 1. Uncertain outside-world cancellation remains reachable

The established chain remains:

```text
KernelStore.cancel_uncertain_event
-> Resident explicit cancellation authority
-> IntentionalResident / NativeWill cancelled semantics
-> ResidentWorkControl ownership + finalization/reconciliation
-> ResidentRpcServer work_cancel
-> Electron resident process + IPC
-> preload bridge
-> desktop bridge typing
-> resident-client recovery normalization + cancelZnWork
-> Workbench recovery-only Stop work control
```

`Stop work` is still shown only for resident-provided `replayBlocked === true` recovery. It prevents further ZN action but does not undo or prove the uncertain external effect.

Key cancellation checkpoints remain:

```text
6c655c761099cc6a206028285cc228d65f3e7734  atomic uncertain Work cancellation
1024752da9741326cf133e27c51358e45b9f6ef2  Will cancelled semantics
01a4a645e68bda87d74697af0fd9aacb9181e96b  Resident cancellation authority
1ad68ddb5f2e423ea02d249553aa404c98266b2d  Work cancellation control
4cf85f33a6c000f31ed839e405bd2bb978e8d83e  work_cancel RPC
0be9340e2db305be7134d403a1ecdf392a7f36b4  focused backend coverage
831bba875e77ecddd338bb2b464844171b479e93  Electron RPC typing fix
5c679ea742a2c83578c85c215cf582ce8c22a8cf  recovery-only Workbench control
```

### 2. Real post-completion bug was identified

The old real ordering was:

```text
KernelStore.complete_event(...)
-> terminal event + EventOutcome committed
-> life.observe_action(...)
```

`life.observe_action()` persists LivingState through a separate SQLite connection. If it raised after `complete_event()` had committed, the broad `run_once()` exception handler could interpret the secondary observation failure as an execution failure and try to complete the already-terminal event again.

That violated the required boundary between durable action truth and later resident self-observation.

### 3. Durable completion observation journal added

Checkpoint:

```text
baf5d5f3fcb9cad3c485d5ae4a05c7d937c5dbe8
feat: add durable completion observation journal
```

New file:

```text
runtime/python/zn_agent/core/completion_observation.py
```

`CompletionObservationJournal` owns a resident SQLite repair table:

```text
resident_completion_observations
(event_id, stage, status, attempts, last_error, updated_at)
```

Current durable stage is `life`.

Semantics:

```text
durable EventOutcome first
-> begin Life observation receipt
-> apply life.observe_action
-> success: mark receipt completed
-> failure: keep receipt pending, record bounded error, do not alter event truth
```

Repair reconstructs the result from the already-durable `EventOutcome` and reruns only Life observation. It never reruns the completed event/action.

This is at-least-once observation repair. It is not an exactly-once claim.

### 4. Resident terminal-truth guard added

Checkpoint:

```text
86895eda3397cf71d7f24b2d7d84d0c73c5e7220
fix: preserve durable outcome across Life observation failure
```

`ZNResidentRuntime` now:

- creates the completion-observation journal after Life wake;
- repairs pending Life observations during resident construction;
- routes post-completion Life observation through the journal;
- exposes `repair_completion_observations()` for resident-owned repair;
- checks `result_for(event_id)` first in the broad `run_once()` exception path.

Therefore any exception after a durable `EventOutcome` exists returns that existing outcome instead of manufacturing a second failure interpretation.

### 5. Regression coverage added

Checkpoint:

```text
f942bc07e4965af7f347c6659207328f92695e41
test: cover post-completion Life observation recovery
```

`tests/zn_agent/core/test_completion_observation_recovery.py` proves:

```text
Life observation failure does not reclassify durable success
pending Life observation repairs after resident restart without replay
an arbitrary exception after completion returns the existing outcome
```

The restart test also verifies the event attempt count remains `1`.

### 6. Focused Windows workflow now owns this proof

Checkpoint:

```text
6ac3dba5191aa5469bac0093bab15ca3e25b5d95
ci: verify completion observation recovery
```

`.github/workflows/zn-work-recovery-e2e.yml` now triggers on the completion-observation implementation/test files, compiles the new module, and includes the new unittest module with the existing Work recovery/cancellation suite.

## Real test / CI truth

### Exact focused completion-observation proof

```text
ZN Work Recovery E2E run 33018036694
head 6ac3dba5191aa5469bac0093bab15ca3e25b5d95
Windows resident Work restart recovery  success
Compile Work recovery path               success
Verify durable Work progress and restart recovery  success
```

That verification step includes:

```text
test_work_progress
test_work_recovery
test_work_side_effect_recovery
test_work_cancellation
test_work_cancel_control
test_completion_observation_recovery
```

An earlier focused run at implementation head `86895eda...` also passed the existing Work recovery suite:

```text
ZN Work Recovery E2E run 33017989185
conclusion success
```

### Ordinary CI at code/workflow checkpoint

```text
ZN CI run 33018036687
head 6ac3dba5191aa5469bac0093bab15ca3e25b5d95
```

Verified before documentation commits:

```text
Electron / TypeScript / Windows    success
  typecheck                         success
  independent ZN bundle            success
  desktop ownership/packaged/update/handoff tests  success
  release/runtime/package verifier tests           success
ZN Source Boundary / Windows       success
ZN Kernel / Python / Windows       still running at documentation sync
```

Do not call the whole ordinary CI green while Kernel is unfinished or failing.

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

The 16 errors are the known Windows NetworkService DOS-8.3 versus long-path identity family affecting repository targeted-test/text-delta verification and terminal/Work artifact cwd identity. Cleanup `PermissionError` traces are secondary fallout.

The prior partial path fix was reverted normally in `db647cb49c3de014aa82bc28ec87c1c4e5b02c15`; no half-fix remains.

## Current risks / blockers

- Life post-completion observation repair is implemented and focused-Windows verified, but broader Work durability remains partial.
- Current completion-observation repair health is not yet surfaced through sanitized resident status/desktop health.
- `NativeWill` already reconciles durable outcomes on restart, but `IntentionalResident` nervous-system outcome perception still needs an explicit durability/idempotence audit; do not claim all post-completion perception is exactly-once.
- Ordinary Kernel CI may still fail on the known/deferred Windows DOS-8.3 path identity family.
- The cancellation UI remains intentionally recovery-only; arbitrary already-executing external effects are not safely cancellable by claim.
- Browser PRESS/broader click/editing/multi-select/lifecycle, authenticated User Browser Bridge control, M8 continuity, and SM1+ remain incomplete.
- High-risk identity, long-term memory, credentials/permissions, updater/signing, rollback, and destructive self-maintenance changes still require human approval.
- `main` remains untouched.

## Task queue

### P0 - completion-observation health visibility + IntentionalResident post-processing audit

Status: **NEXT REAL TARGET**

First trace the real read/status path and expose only sanitized health, for example bounded counts/stages, not raw internal error text:

```text
CompletionObservationJournal.pending
-> ZNResidentRuntime.status
-> daemon/RPC status response
-> desktop resident snapshot/health if useful
```

Then inspect the post-completion `IntentionalResident` chain:

```text
ZNResidentRuntime._complete_result
-> durable EventOutcome + Life receipt
-> IntentionalResident nervous outcome perception
-> NativeWill.observe_event_outcome
-> NativeWill.reconcile_outcomes on restart
```

Required decisions/invariants:

```text
EventOutcome remains terminal authority
pending observation health is visible without leaking raw failure details
Will keeps using durable outcome reconciliation rather than duplicate action replay
Nervous outcome perception is either safely reconstructible/idempotent or gains its own durable receipt
no secondary perception failure can reopen/replay completed Work
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
runtime/python/zn_agent/core/completion_observation.py
runtime/python/zn_agent/core/life.py
runtime/python/zn_agent/core/intentional_resident.py
runtime/python/zn_agent/core/nervous_system.py
runtime/python/zn_agent/core/will.py
runtime/python/zn_agent/core/work.py
runtime/python/zn_agent/core/work_control.py
runtime/python/zn_agent/core/daemon.py
tests/zn_agent/core/test_completion_observation_recovery.py
tests/zn_agent/core/test_work_cancellation.py
tests/zn_agent/core/test_work_cancel_control.py
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

Expose sanitized pending completion-observation health and audit `IntentionalResident` nervous/Will post-completion semantics without weakening durable event truth or replaying completed Work. Keep `main` untouched.
