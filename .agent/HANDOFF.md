# ZN Agent Handoff

Updated: 2026-08-26

## Current goal

Recovery-only cancellation remains reachable and verified. Durable post-completion Life observation recovery remains intact. The active product resident now exposes sanitized completion-observation health through its resident-owned `status` response, and the existing daemon/RPC status path passes that projection through without raw repair errors.

A real full-Kernel regression was found and fixed in this stage: the richer resident birth sequence (`EmbodiedResidentRuntime` and descendants) intentionally skips `ZNResidentRuntime.__init__`, so it had not installed `CompletionObservationJournal`. That caused completed richer events to fail in post-completion observation and produced cascading Intentional/Will/transfer failures. The journal is now owned by the richer birth root after `EmbodiedLifeCore.wake()`.

The next real target is **event-identity-safe nervous outcome perception**. Do not add a naive retry queue: one nervous `perceive()` currently writes trace, links, and affect in separate transactions, and a duplicate perception intentionally reinforces memory.

Do not broaden cancellation into arbitrary in-flight cancellation. Do not treat cancellation as evidence about an uncertain outside-world effect. Do not weaken durable `EventOutcome` truth to repair secondary perception.

Founding boundary remains:

> **ZN uses models. Models do not own ZN.**

## Branch / repository truth

- repository: `9529360-cpu/znagent`
- development branch: `dev/zn-agent`
- canonical source/release branch: `main`
- canonical `main`: `8234a835dea604783cea0bd9d28a40de654ec03d`
- code/workflow checkpoint before documentation sync: `43142de23196b4e5fb3912bc177a8f25b95189e3`
- implementation-status sync before this HANDOFF update: `4b38f49b015030efbe1dd6f58f1fe8f8142d99a7`
- Life observation recovery checkpoint: `86895eda3397cf71d7f24b2d7d84d0c73c5e7220`
- cancellation UI checkpoint: `5c679ea742a2c83578c85c215cf582ce8c22a8cf`
- PR #6: draft/open/unmerged, base `main`, head `dev/zn-agent`
- `main` was not modified
- no force push or history rewrite was used

A HANDOFF commit cannot contain its own resulting SHA. Re-read `dev/zn-agent` after this file is committed and use that exact head externally.

## Completed in this stage

### 1. Found the new full-Kernel regression instead of hiding it as the old path issue

At earlier head `59af7bd050595682e3c0354d67d73187c6db7829`, ordinary Kernel CI reported 581 tests / 29 errors / 5 skipped. The log contained a new failure:

```text
AttributeError: 'FocusedModernTextResidentRuntime' object has no attribute 'completion_observations'
```

That was separate from the known NetworkService DOS-8.3 path family and caused cascading failures where Intentional/transfer state did not finish normally.

### 2. Corrected completion-observation ownership for both legitimate resident births

The ordinary resident birth already has:

```text
ZNResidentRuntime.__init__
-> ZNLifeCore.wake()
-> CompletionObservationJournal
-> repair pending Life observation
```

The richer resident deliberately has a different birth:

```text
EmbodiedResidentRuntime.__init__
-> does not call ZNResidentRuntime.__init__
-> EmbodiedLifeCore from the first durable load
```

Calling the base constructor would temporarily birth the wrong LifeCore and is not an acceptable compatibility fix.

`EmbodiedResidentRuntime` now installs the same journal only after `EmbodiedLifeCore.wake()`, then repairs pending Life observation from durable `EventOutcome` truth. Direct `EmbodiedResidentRuntime`, `IntentionalResidentRuntime`, and later richer descendants therefore own the organ without relying on a product builder shim.

Relevant repair sequence:

```text
1058f7c5401db44c156c7a40c41317d327178a5b  initial product-builder repair
9303b257c12f324ed07fc095149e095dc4346b5d  product resident regression
 ef4d68b363fb381ac74ca83d6623a024651575a7 product resident health/status ownership
 e934431f57c1ba59fb97223dda4fe389b6a4c210 provider bridge restored to pure assembly
 a2428564b30556f3a33ea1556b47c0829f1c99e3 richer resident journal installation
 a395897e79c060e09b9aa2b0e67f206d4b841db8 restore unrelated embodied documentation after diff review
08891757291954963c974504079137d5ca268a24  direct Embodied/Intentional regression
43142de23196b4e5fb3912bc177a8f25b95189e3  focused workflow coverage
```

The initial builder-specific install was removed. `provider_bridge.py` is assembly-only again.

The `a2428564` full-file edit was explicitly diff-reviewed. It had unintentionally removed explanatory comments/docstrings; `a395897e` restored them immediately. Net behavioral change in `embodied_resident.py` is only journal import + installation/repair after richer Life wake.

### 3. Sanitized health is now reachable through product status and RPC

`CompletionObservationJournal.health()` continues to return only:

```text
healthy
pending_count
waiting_count
running_count
stages
```

`FocusedModernTextResidentRuntime.status()` exposes that object as `completion_observations`.

Regression coverage verifies both healthy and pending states and asserts that raw exception text and `last_error` are absent. `ResidentRpcServer` status regression verifies the same sanitized object passes through the existing resident status RPC without becoming daemon/renderer-owned state.

The desktop snapshot already transports resident status opaquely. No new UI warning, permission, or cancellation authority was added.

Relevant checkpoints:

```text
83ca2179bf1f836469687dac61310b016f482ca8  sanitized health primitive
 ef4d68b363fb381ac74ca83d6623a024651575a7 product status projection
81dc10bff548eaaaa7a3dba95524f10107a5a855  product status sanitization regressions
d589e3aaf1ad276867926f33a814395630c59bdc  status RPC pass-through regression
```

### 4. Focused workflow now covers the previously missed richer birth path

`.github/workflows/zn-work-recovery-e2e.yml` now:

- triggers on `embodied_resident.py`;
- compiles `embodied_resident.py` with the Work recovery path;
- includes `test_completion_observation_embodied.py`;
- directly completes events through both `EmbodiedResidentRuntime` and `IntentionalResidentRuntime`.

This prevents the focused suite from proving only the plain resident while the product/richer resident is broken.

### 5. Nervous post-completion audit reached a concrete transaction boundary

Real chain:

```text
ZNResidentRuntime._complete_result
-> durable EventOutcome + Life observation journal
-> IntentionalResident._complete_result
-> nervous.perceive("outcome")
-> NativeWill.observe_event_outcome when applicable
```

`NativeWill` already runs durable outcome reconciliation on construction. Keep that authority.

`PersistentNervousSystem.perceive()` is not safe for blind replay. A single perception currently performs independent durable writes for:

```text
trace
links
nervous affect/state
```

and a repeated matching perception intentionally increments repetitions, strengthens the trace, changes salience/valence/arousal, strengthens links, and integrates affect again.

A separate receipt without changing the plasticity transaction boundary would therefore be false safety: crash after a partial write could either leave incomplete perception or cause duplicate reinforcement on retry.

No nervous exactly-once claim has been made and no naive repair queue was added.

## Real test / CI truth

### Current focused proof

```text
ZN Work Recovery E2E run 33020344769
head 43142de23196b4e5fb3912bc177a8f25b95189e3
Windows resident Work restart recovery            success
Compile Work recovery path                        success
Verify durable Work progress and restart recovery success
job conclusion                                    success
```

Focused modules include:

```text
test_work_progress
test_work_recovery
test_work_side_effect_recovery
test_work_cancellation
test_work_cancel_control
test_completion_observation_recovery
test_completion_observation_embodied
```

### Current ordinary code-head CI

```text
ZN CI run 33020344789
head 43142de23196b4e5fb3912bc177a8f25b95189e3
Electron / TypeScript / Windows    success
ZN Source Boundary / Windows       success
ZN Kernel / Python / Windows       failure
Kernel                             585 tests / 16 errors / 5 skipped
```

The missing `completion_observations` AttributeError and associated Intentional/transfer cascade are gone. The formerly affected richer tests execute successfully.

The remaining 16 errors are the known Windows NetworkService DOS-8.3 versus long-path identity family around repository targeted-test/text-delta verification and terminal/Work artifact cwd identity, with cleanup `PermissionError` fallout.

The prior partial path fix remains normally reverted in `db647cb49c3de014aa82bc28ec87c1c4e5b02c15`; no half-fix remains. Ordinary CI is not green.

## Current risks / incomplete work

- Nervous outcome perception still lacks an event-identity-safe atomic/deduplicated plasticity boundary; blind retry is unsafe.
- `FocusedModernTextResidentRuntime` currently performs a redundant second construction of the same completion-observation journal after the Embodied root already installed it. It is functionally harmless and not a correctness blocker, but should be cleaned when an edit can be made without another risky large-file replacement.
- Broader Work durability remains partial outside the proven cancellation and Life-observation slices.
- Ordinary Windows Kernel CI remains red on the known/deferred path-identity family.
- Browser PRESS/broader click/editing/multi-select/lifecycle, authenticated User Browser Bridge control, M8 continuity, and SM1+ remain incomplete.
- High-risk identity, long-term memory, credentials/permissions, updater/signing, rollback, and destructive self-maintenance changes still require human approval.
- `main` remains untouched.

## Task queue

### P0 - event-identity-safe nervous outcome perception

Status: **NEXT REAL TARGET**

Design a resident-owned boundary where one durable event outcome can influence neural plasticity once without ambiguity across crash/restart.

Do not simply add a receipt around the current `perceive()` call. The design must account atomically or equivalently for:

```text
outcome event identity
trace mutation
link mutation
affect mutation
completion marker / dedupe identity
```

Required invariants:

```text
EventOutcome remains terminal authority
one completed event is not reinforced twice by recovery
partial nervous writes cannot masquerade as a complete perception
restart cannot replay the completed action
Will continues its existing durable outcome reconciliation
models never become recovery authority
```

### P0.1 - low-risk cleanup

Status: **OPEN / NON-BLOCKING**

Remove the redundant second `CompletionObservationJournal` initialization from `FocusedModernTextResidentRuntime` once a safe narrow edit path is available. Keep its product `status()` projection.

### P1 - deferred Windows path identity

Status: **KNOWN / DEFERRED**

Resume only if explicitly reprioritized or materially blocking the current product objective.

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
runtime/python/zn_agent/core/embodied_resident.py
runtime/python/zn_agent/core/intentional_resident.py
runtime/python/zn_agent/core/focused_modern_text_resident.py
runtime/python/zn_agent/core/nervous_system.py
runtime/python/zn_agent/core/will.py
runtime/python/zn_agent/core/daemon.py
runtime/python/zn_agent/core/provider_bridge.py
tests/zn_agent/core/test_completion_observation_recovery.py
tests/zn_agent/core/test_completion_observation_embodied.py
.github/workflows/zn-work-recovery-e2e.yml
docs/ZN-IMPLEMENTATION-STATUS.md
.agent/HANDOFF.md
```

## Next real target

Design and implement event-identity-safe nervous outcome perception without duplicating lived reinforcement or weakening durable event truth. Keep `main` untouched.
