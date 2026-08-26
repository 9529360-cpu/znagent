# ZN Agent Handoff

Updated: 2026-08-26

## Current goal

Recovery-only cancellation remains reachable and verified. Post-completion Life observation recovery is implemented and verified. A sanitized completion-observation health projection primitive now exists and is tested, but it is **not yet wired into resident `status` / RPC / desktop health**.

The IntentionalResident post-completion audit found an important constraint: `NativeWill` already has durable outcome reconciliation, while nervous-system `outcome` perception is not safely replayable as-is because repeated `PersistentNervousSystem.perceive()` calls intentionally increment repetitions, strengthen traces, blend affect, and strengthen links.

Next real target: **wire the sanitized health projection into the real resident status chain, then design event-identity-safe semantics for nervous outcome perception without duplicating lived reinforcement.**

Do not broaden cancellation into arbitrary in-flight cancellation. Do not treat cancellation as evidence about an uncertain outside-world effect. Do not weaken durable `EventOutcome` truth to repair secondary perception.

Founding boundary remains:

> **ZN uses models. Models do not own ZN.**

## Branch / repository truth

- repository: `9529360-cpu/znagent`
- development branch: `dev/zn-agent`
- canonical source/release branch: `main`
- canonical `main`: `8234a835dea604783cea0bd9d28a40de654ec03d`
- latest health implementation checkpoint before this HANDOFF update: `83ca2179bf1f836469687dac61310b016f482ca8`
- latest health regression checkpoint: `503edf31ce676810117a6e52d945f9d50cbb935d`
- implementation-status sync before this HANDOFF update: `9c490717c6bd595aa21f71643be49fc8c400f0cd`
- Life observation recovery checkpoint: `86895eda3397cf71d7f24b2d7d84d0c73c5e7220`
- cancellation UI checkpoint: `5c679ea742a2c83578c85c215cf582ce8c22a8cf`
- PR #6: draft/open/unmerged, base `main`, head `dev/zn-agent`
- `main` was not modified
- no force push or history rewrite was used

A HANDOFF commit cannot contain its own resulting SHA. Re-read `dev/zn-agent` after this file is committed and use that exact head externally.

## Completed

### 1. Recovery-only uncertain-effect cancellation

The active chain remains:

```text
KernelStore.cancel_uncertain_event
-> Resident cancellation authority
-> NativeWill / ResidentWorkControl reconciliation
-> work_cancel RPC
-> Electron / preload / renderer client
-> Workbench Stop work only for replayBlocked recovery
```

Cancellation remains a control/lifecycle result, not ordinary failure learning and not evidence that an outside-world effect did or did not happen.

Key checkpoints:

```text
6c655c761099cc6a206028285cc228d65f3e7734  atomic uncertain Work cancellation
0be9340e2db305be7134d403a1ecdf392a7f36b4  focused cancellation workflow coverage
5c679ea742a2c83578c85c215cf582ce8c22a8cf  recovery-only desktop control
```

### 2. Durable post-completion Life observation recovery

The authoritative boundary is now:

```text
action result
-> KernelStore.complete_event
-> durable terminal EventOutcome
-> secondary observation
```

`CompletionObservationJournal` durably receipts Life observation. A Life write failure remains pending and cannot reclassify the already-durable event. Restart reconstructs the result from `EventOutcome` and retries only Life observation; it does not rerun the event/action.

`run_once()` also checks for an existing durable outcome before ordinary exception handling, so later post-completion hook failures return terminal truth rather than manufacturing another failure completion.

Key checkpoints:

```text
baf5d5f3fcb9cad3c485d5ae4a05c7d937c5dbe8  completion observation journal
86895eda3397cf71d7f24b2d7d84d0c73c5e7220  preserve terminal truth across Life observation failure
f942bc07e4965af7f347c6659207328f92695e41  recovery regressions
6ac3dba5191aa5469bac0093bab15ca3e25b5d95  focused workflow coverage
```

This remains at-least-once observation repair, not an exactly-once claim.

### 3. Sanitized health projection primitive

New checkpoints:

```text
83ca2179bf1f836469687dac61310b016f482ca8  feat: add sanitized completion observation health
503edf31ce676810117a6e52d945f9d50cbb935d  test: keep completion observation health sanitized
```

`CompletionObservationJournal.health()` returns only:

```text
healthy
pending_count
waiting_count
running_count
stages
```

It does not expose event IDs, raw `last_error`, exception messages, internal paths, or repair payloads.

The test creates a pending Life observation containing deliberately sensitive-looking internal error text and verifies that neither that text nor `last_error` appears in the health projection. It also verifies repaired state reports healthy with zero pending observations.

This is a primitive only. It is not yet connected to `ZNResidentRuntime.status`, daemon/RPC status, or desktop health.

### 4. IntentionalResident post-completion audit result

Real call chain:

```text
ZNResidentRuntime._complete_result
-> durable EventOutcome + Life observation receipt
-> IntentionalResident._complete_result
-> nervous.perceive("outcome", ... event_id metadata ...)
-> NativeWill.observe_event_outcome when intention_id exists
```

Will already calls `reconcile_outcomes()` during `IntentionalResident` construction, so Will should keep using durable outcome reconciliation rather than gain a duplicate completion authority.

Nervous outcome perception is different. `PersistentNervousSystem.perceive()` fingerprints matching perceptions, but a repeated call intentionally does:

```text
repetitions += 1
strength increases
salience / valence / arousal blend again
recent links strengthen again
affect integrates again
```

Therefore blind at-least-once replay of the nervous outcome perception would distort lived memory after an ambiguous commit/receipt boundary. Before adding nervous repair, introduce or choose an event-identity-safe semantic instead of copying the Life receipt behavior.

## Real test / CI truth

### Completion observation recovery proof

```text
ZN Work Recovery E2E run 33018036694
head 6ac3dba5191aa5469bac0093bab15ca3e25b5d95
conclusion success
```

### Sanitized health proof

```text
ZN Work Recovery E2E run 33018371392
head 503edf31ce676810117a6e52d945f9d50cbb935d
Compile Work recovery path                         success
Verify durable Work progress and restart recovery success
job conclusion                                     success
```

This focused suite includes the existing Work progress/restart/side-effect/cancellation tests plus `test_completion_observation_recovery`.

### Ordinary CI truth

At code/workflow checkpoint `6ac3dba...`, `ZN CI` run `33018036687` had:

```text
Electron / TypeScript / Windows    success
ZN Source Boundary / Windows       success
ZN Kernel / Python / Windows       still running at prior documentation sync
```

A current-head ordinary CI will be triggered/superseded by later commits; re-read Actions before reporting final status.

Known separate ordinary Kernel issue remains the Windows NetworkService DOS-8.3 versus long-path identity family. Prior exact evidence:

```text
ZN CI run 33014912300
head 6c655c761099cc6a206028285cc228d65f3e7734
Kernel 573 tests / 16 errors / 5 skipped
```

The partial attempted path fix was reverted normally in `db647cb49c3de014aa82bc28ec87c1c4e5b02c15`; no half-fix remains. Keep this **KNOWN / DEFERRED** unless it blocks the active product objective or is explicitly reprioritized.

## Current risks / incomplete work

- Sanitized completion-observation health is not yet reachable through resident `status` / RPC / desktop.
- Nervous outcome perception still lacks event-identity-safe durable repair semantics; blind retry is unsafe because it reinforces memory again.
- Broader Work durability remains partial outside the proven cancellation and Life-observation slices.
- Ordinary Windows Kernel CI may still report the known/deferred path-identity family.
- Browser PRESS/broader click/editing/multi-select/lifecycle, authenticated User Browser Bridge control, M8 continuity, and SM1+ remain incomplete.
- High-risk identity, long-term memory, credentials/permissions, updater/signing, rollback, and destructive self-maintenance changes still require human approval.
- `main` remains untouched.

## Task queue

### P0 - wire sanitized observation health

Status: **NEXT REAL TARGET**

Trace/modify the real chain, preserving resident ownership:

```text
CompletionObservationJournal.health()
-> ZNResidentRuntime.status (or the narrowest resident-owned status projection)
-> ResidentRpcServer status
-> renderer snapshot only if useful
```

Required output must remain sanitized counts/stages only. Do not expose raw `last_error` or per-event repair internals to the control plane.

### P0.1 - nervous outcome event identity

Status: **DESIGN/IMPLEMENT AFTER STATUS WIRING**

Choose a mechanism where the outcome neural perception can be recognized by durable event identity without repeated reinforcement. Verify crash/restart ambiguity explicitly before adding a retry queue.

`NativeWill` should continue using its existing durable outcome reconciliation.

### P1 - deferred Windows path identity

Status: **KNOWN / DEFERRED**

Resume only if reprioritized or materially blocking the current product target.

### P2 - browser follow-ons

Status: **OPEN**

PRESS, broader click semantics, richer text editing, multi-select, broader page/target lifecycle, authenticated User Browser Bridge control.

### P3 - M8 / SM1+

Status: **OPEN**

Preserve human approval for high-risk identity, memory, credentials, updater/signing, rollback, and destructive self-maintenance changes.

## Related files

```text
runtime/python/zn_agent/core/completion_observation.py
runtime/python/zn_agent/core/resident.py
runtime/python/zn_agent/core/life.py
runtime/python/zn_agent/core/intentional_resident.py
runtime/python/zn_agent/core/nervous_system.py
runtime/python/zn_agent/core/will.py
runtime/python/zn_agent/core/daemon.py
tests/zn_agent/core/test_completion_observation_recovery.py
.github/workflows/zn-work-recovery-e2e.yml
docs/ZN-IMPLEMENTATION-STATUS.md
.agent/HANDOFF.md
```

## Next real target

Wire sanitized pending completion-observation health into the real resident status chain. Then design event-identity-safe nervous outcome perception semantics. Keep `main` untouched.
