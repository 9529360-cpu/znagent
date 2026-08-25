# ZN implementation status

> Architecture contract: [`../ZN.md`](../ZN.md)
>
> Memory/learning architecture: [`ZN-MEMORY-LEARNING.md`](ZN-MEMORY-LEARNING.md)
>
> Source adoption boundary: [`ZN-SOURCE-EXTRACTION.md`](ZN-SOURCE-EXTRACTION.md)
>
> Self-maintenance contract: [`ZN-SELF-MAINTENANCE.md`](ZN-SELF-MAINTENANCE.md)
>
> Real code, Git state and CI outrank this ledger.

Development branch: `dev/zn-agent`. Canonical source/release branch: `main`.

## 1. Current checkpoint - 2026-08-25

M10 canonical source promotion remains complete. `main` is canonical source/release; ordinary development remains on `dev/zn-agent`.

Latest verified implementation head before this ledger sync:

```text
head  6f25b30c46d2f1bcafdd8f62e0968c2a4d05623e
run   32866088556

ZN Kernel / Python / Windows        success
ZN Source Boundary / Windows       success
Electron / TypeScript / Windows    success
Publish Windows CI statuses        success
```

The exact-head Windows kernel job used a fresh isolated CPython 3.12.13 environment, installed the formal `runtime/python` distribution with 29 packages including `Pillow==12.3.0` and `psutil==7.2.2`, booted the resident with zero external models, compiled the resident core, and ran the full working-tree suite: **416 tests passed with 5 platform-appropriate skips**.

This checkpoint adds the first narrow semantic/current-world UI completion slice without widening mutation authority. Pointer click may now close a `ui_state_transition` only when the structured completion scope is exactly `foreground_window_matches(process_name, title_equals)` and fresh resident-owned Windows foreground-window evidence matches that scope. Natural-language task prose and model output are not completion evidence.

This proves only foreground application/window identity. It does **not** prove deeper business semantics such as "form submitted", "message sent", "purchase completed", or equivalent application state.

## 2. Resident ownership - VERIFIED

The resident owns persistent Self/life state, Situation/Thought/Will, durable WorkingState, Investigation, native Body actions and Senses, bounded cognition resources, memory/reconsolidation, verified experience/procedural tendencies, channels, and resident work/progress state.

The active builder now constructs `SemanticPointerClickResidentRuntime`, layered over `EffectScopedPointerClickResidentRuntime` and `VerifiedPointerClickResidentRuntime`. The previously verified effect-only completion guard remains intact.

Zero-model boot passed at exact head `6f25b30c...`.

## 3. Engineering competence - VERIFIED NARROW SLICES

Current resident-owned engineering behavior includes structured Git state/diff evidence, bounded file/process/terminal/PTTY actions, exact text and command postcondition verification, tracked pre/post Git proof, evidence-bound anti-replay, current-reality-gated alternatives, bounded staging choices, targeted unittest verification, and restart-safe side-effect verification.

The repository-owned verifier manifest remains bounded to three real literal target/test relations:

```text
runtime/python/zn_agent/core/repo_test_semantics.py
-> tests/zn_agent/core/test_repo_test_semantics_authority.py

runtime/python/zn_agent/core/git_semantics.py
-> tests/zn_agent/core/test_git_staging_semantics.py

runtime/python/zn_agent/core/result_semantics.py
-> tests/zn_agent/core/test_verified_experience.py
```

Do not expand the manifest merely for count.

## 4. Memory and learning - VERIFIED FOUNDATION, MATURITY PARTIAL

Persistent traces, associations, schema formation, fading/pruning, prediction error, reconsolidation, independently verified episodic evidence, and bounded procedural tendencies exist.

`visual_region_changed` remains outside positive verified-experience kinds, and pointer-click semantic completion still bypasses generic task-prose native-ability credit. General procedural competence, mature computer use, broad local training, and long-horizon growth benchmarks remain partial.

## 5. Body / Senses / computer interaction - VERIFIED FOUNDATION, MATURITY PARTIAL

### Resident visual foundation

`ResidentSocketService` owns persistent `NativeVisualSense` and on-demand read-only `NativeVisualRegionSense`. Default capture uses local Pillow `ImageGrab`; raw pixels are discarded inside capture. Target-local probes return only compact signature/luminance/bounds metadata and do not create mutation authority, another agent, persistent retina writes, or model calls.

Historical run `32847172662` verified the local visual probe foundation with 397 passed / 5 skipped. Injected probes do not constitute real interactive-desktop screenshot E2E evidence.

### Verified pointer movement

```text
explicit structured pointer_move
-> resident-owned NativeBody
-> Windows primary-screen movement
-> fresh pointer_state observation
-> complete only if current cursor matches the expected bounded target
-> contradiction -> Investigation
```

Only finite normalized primary-screen coordinates are accepted. No task prose/model/procedural coordinate invention is permitted. Body movement success is not task success.

### Verified local pointer-click effect

The existing narrow effect chain remains:

```text
explicit NativeActionIntent(kind="pointer_click")
-> expected_outcome.kind="visual_region_changed"
-> event.kind="effect_probe"
-> completion_scope = verified_effect / visual_region_changed
-> explicit normalized pointer target
-> fresh pointer_state verification
-> fresh target-local visual baseline
-> durable started marker before click delivery
-> exactly one left click
-> fresh target-local visual verification
-> changed signature may close only that effect_probe
-> contradiction/unavailable evidence -> Investigation
```

Ordinary `user_task` click, missing/invalid effect scope, broader scope, or unknown authority fields still fail closed before pointer movement/input.

### Narrow semantic UI-state completion

New read-only Sense:

```text
NativeForegroundWindowSense
-> Windows user32 GetForegroundWindow
-> GetWindowTextW
-> GetWindowThreadProcessId
-> GetClassNameW
-> psutil process name lookup
-> ForegroundWindowObservation
```

The Sense is stateless and read-only. It returns bounded `process_id`, exact `title`, required `process_name`, `class_name`, capture time, and source metadata. It performs no OCR, model call, pixel persistence, or input action. Missing process identity/name fails as unavailable evidence.

New typed completion chain:

```text
structured body_action/native_action pointer_click
-> require existing visual_region_changed click-effect contract
-> require event.kind="ui_state_transition"
-> require completion_scope.kind="foreground_window_matches"
-> require exact non-empty completion_scope.process_name
-> require exact non-empty completion_scope.title_equals
-> reject unknown scope authority fields
-> fresh foreground-window preflight BEFORE pointer preparation
   -> already matches: complete without pointer movement/click
   -> unavailable: fail closed before pointer movement
   -> mismatch: continue existing bounded click lifecycle
-> persist admitted event kind + semantic completion scope in native_verification
-> local click effect must verify first
-> fresh foreground-window probe after click
   -> exact process/title match: close only this typed ui_state_transition
   -> mismatch/unavailable: Investigation, no click replay
-> admitted scope/event-kind drift after click: Investigation, no replay
```

Important boundary:

- foreground-window identity is a real semantic/current-world slice, but it is still narrow;
- exact `process_name + title_equals` proves only that the matching application window is foreground;
- it does not prove internal application state, network delivery, transaction completion, or arbitrary task prose;
- no keyboard, right-click, double-click, drag, browser automation catalog, or new mutation primitive was added;
- the old `effect_probe` guard remains active for local-effect-only clicks;
- real interactive-desktop E2E evidence is still absent; CI uses injected probes for this semantic lifecycle.

Key commits:

```text
44ecb72d4c58f2c75a8e5c5d65d1820e64ceeed4  feat: add verified pointer click lifecycle
de61fef5e24eb8a2f2fb99a389bf77b21faddcef  fix: bind pointer click completion scope
6f25b30c46d2f1bcafdd8f62e0968c2a4d05623e  feat: verify foreground ui state
```

Exact-head run `32866088556` verified the current implementation with **416 tests passed / 5 skipped**. The 11 new tests passed:

```text
test_probe_returns_bounded_structured_identity_from_injected_source
test_probe_rejects_unusable_identity
test_probe_rejects_missing_process_name
test_active_resident_owns_foreground_window_sense_without_probing_on_boot
test_ui_state_transition_requires_exact_semantic_scope_before_input
test_ui_state_transition_requires_typed_event_kind_before_input
test_already_satisfied_ui_state_completes_without_pointer_input
test_ui_state_transition_needs_fresh_semantic_match_after_click
test_semantic_mismatch_after_click_returns_to_investigation_without_replay
test_post_input_scope_drift_is_rejected_without_replay
test_missing_semantic_sense_fails_before_pointer_movement
```

All eight previous pointer-click lifecycle tests also passed in the same full discovery.

## 6. External cognition, web/world and channels - VERIFIED FOUNDATION

Supported model providers remain bounded ZN-owned cognitive resources. Provider replacement does not replace resident identity, store, or life state. ZN owns URL/network safety and web resource boundaries; channels remain I/O for the same resident.

## 7. Desktop ownership - VERIFIED

Active desktop path remains:

```text
ZN Electron main
-> ZN preload / IPC
-> long-lived resident RPC
-> ZN renderer
```

Run `32866088556` passed locked workspace dependency installation, high-severity npm audit, Electron typecheck, bundle, desktop ownership/runtime/update/handoff tests, and release/runtime artifact verifier tests.

## 8. Runtime and artifact ownership - VERIFIED FOR EXERCISED TARGETS

Runtime identity remains:

```text
Python distribution: znagent
Python package:      zn_agent
entrypoint:          zn-resident
```

Run `32866088556` installed the formal runtime in fresh Windows Python 3.12.13 before zero-model boot and full tests. Steady-state development verification remains Windows x64.

## 9. Release/update state - M8 PARTIAL

Still open for current Windows x64 M8 target:

1. clean Windows install/login evidence;
2. installed Windows N->N+1 continuity evidence;
3. rollback validation across a real Windows version transition;
4. applicable secure Windows signing evidence.

M8 must not be reported complete until those are exercised.

## 10. Repository source boundary - COMPLETE AND CI-ENFORCED

Status: **COMPLETE**. The active tree remains physically ZN-only and exact-head Source Boundary passed in run `32866088556`. The historical source quarry is not an active runtime/build/test/package/release dependency.

## 11. Dependency security state

Electron remains on the patched `41.10.5` line and steady-state CI uses locked install plus `npm audit --audit-level=high`.

GitHub Actions still reports non-blocking Node 20->24 runtime deprecation warnings for some actions. Treat this as tooling maintenance debt, not a product failure.

## 12. Self-maintenance - SM0 COMPLETE, SM1+ OPEN

Architecture remains defined by `ZN-SELF-MAINTENANCE.md`. Full autonomous detect -> investigate -> isolated fix -> PR -> CI -> merge -> release is not yet owned end-to-end by ZN. High-risk identity/memory/credential/updater/rollback/signing/self-approval changes remain human-approved by default.

## 13. M10 status - COMPLETE

Canonical source promotion remains complete. `main` stays canonical source/release and `dev/zn-agent` stays normal development. This checkpoint did not modify `main` and did not change M8 status.

## 14. Current known debts

- semantic verification deeper than foreground application/window identity;
- structured read-only evidence for internal application/UI state without model/task prose becoming fact;
- real-session foreground-window/screen-capture/click E2E evidence;
- broader computer-use primitives remain intentionally absent until matching authority and verifier contracts exist;
- M8 Windows clean-install/login, installed N->N+1, rollback, and signing evidence;
- mature procedural competence/growth benchmarks;
- SM1+ autonomous self-maintenance;
- Node-action/deprecation warnings and other non-security tooling warnings.

## 15. Next real targets

```text
1. keep automatic Windows x64 CI green on every exact dev HEAD
2. preserve both fail-closed click layers: local effect scope and foreground-window semantic scope
3. trace the smallest useful internal UI/application state that can be independently observed read-only
4. add a typed outcome only when its fresh evidence can prove that exact state; never infer it from task prose/model output
5. do not expand click/browser/input authority merely because foreground-window identity is now verifiable
6. add real interactive-desktop evidence when a suitable environment exists
7. close Windows M8 clean-install / N->N+1 / rollback / signing evidence
8. advance SM1+ behind existing approval and verification boundaries
```

Do not modify `main` through ordinary development. Any later status change belongs here only after real code/Git/CI evidence exists.
