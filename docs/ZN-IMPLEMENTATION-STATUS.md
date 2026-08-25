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

## 1. Current checkpoint — 2026-08-25

M10 canonical source promotion remains complete. `main` is canonical source/release; ordinary development remains on `dev/zn-agent`.

Latest verified implementation head before this ledger sync:

```text
head  de61fef5e24eb8a2f2fb99a389bf77b21faddcef
run   32861070432

ZN Kernel / Python / Windows        success
ZN Source Boundary / Windows        success
Electron / TypeScript / Windows     success
Publish Windows CI statuses         success
```

The exact-head Windows kernel job created a fresh isolated Python 3.12.13 environment, installed the formal `runtime/python` distribution with 29 packages including `Pillow==12.3.0`, booted the resident with zero external models, compiled the resident core and ran the full working-tree suite: **405 tests passed with 5 platform-appropriate skips**.

This checkpoint closes the first event-level completion-scope hole around pointer click. A verified target-local visual change can terminal-complete only an event explicitly typed as an `effect_probe` whose structured `completion_scope` is exactly `verified_effect / visual_region_changed`. A normal `user_task`, a missing scope, a broader scope, or extra authority fields fail closed before pointer movement/input. Effect-only click completion also no longer credits arbitrary `event.task` prose as native self ability.

This does **not** implement a stronger semantic UI/business/world verifier. It prevents narrow local evidence from being silently promoted into broader task success while that verifier is still absent.

## 2. Resident ownership — VERIFIED

The resident owns persistent Self/life state, Situation/Thought/Will, durable WorkingState, Investigation, native Body actions and Senses, bounded cognition resources, memory/reconsolidation, verified experience/procedural tendencies, channels and resident work/progress state.

Zero-model boot passed at exact head `de61fef5...`.

The active builder now constructs `EffectScopedPointerClickResidentRuntime`, which extends `VerifiedPointerClickResidentRuntime` and preserves the existing repository-verifying/procedural/world-aware resident inheritance chain.

## 3. Engineering competence — VERIFIED NARROW SLICES

Current resident-owned engineering behavior includes structured Git state/diff evidence, bounded file/process/terminal/PTTY actions, exact text and command postcondition verification, tracked pre/post Git proof, evidence-bound anti-replay, current-reality-gated alternatives, bounded staging choices, targeted unittest verification and restart-safe side-effect verification.

The repository-owned verifier manifest remains bounded to three real literal target/test relations and cannot declare command, shell, workdir, timeout, model or task-prose authority:

```text
runtime/python/zn_agent/core/repo_test_semantics.py
→ tests/zn_agent/core/test_repo_test_semantics_authority.py

runtime/python/zn_agent/core/git_semantics.py
→ tests/zn_agent/core/test_git_staging_semantics.py

runtime/python/zn_agent/core/result_semantics.py
→ tests/zn_agent/core/test_verified_experience.py
```

Do not expand the manifest merely for count.

## 4. Memory and learning — VERIFIED FOUNDATION, MATURITY PARTIAL

Persistent traces, associations, schema formation, fading/pruning, prediction error, reconsolidation, independently verified episodic evidence and bounded procedural tendencies exist.

General procedural competence, mature computer use, broad local training and long-horizon growth benchmarks remain partial.

## 5. Body / Senses / computer interaction — VERIFIED FOUNDATION, MATURITY PARTIAL

### Resident visual foundation

`ResidentSocketService` owns persistent `NativeVisualSense` and on-demand read-only `NativeVisualRegionSense`. Default capture uses local Pillow `ImageGrab`; raw pixels are discarded inside capture. Target-local probes return only compact signature/luminance/bounds metadata and do not create mutation authority, another agent, persistent retina writes or model calls.

Run `32847172662` verified the local visual probe foundation with 397 passed / 5 skipped. Injected test probes do not constitute real interactive-desktop screenshot E2E evidence.

### Verified pointer movement

```text
explicit structured pointer_move
→ resident-owned NativeBody
→ Windows primary-screen movement
→ fresh pointer_state observation
→ complete only if current cursor matches the expected bounded target
→ contradiction → Investigation
```

Only finite normalized primary-screen coordinates are accepted. No task prose/model/procedural coordinate invention is permitted. Body movement success is not task success. Run `32844167956` verified this lifecycle with 393 passing core tests.

### Verified narrow pointer click lifecycle

The active call chain is now:

```text
provider_bridge.build_resident_runtime()
→ EffectScopedPointerClickResidentRuntime
→ VerifiedPointerClickResidentRuntime
→ explicit NativeActionIntent(kind="pointer_click")
→ require expected_outcome.kind="visual_region_changed"
→ require event.kind="effect_probe"
→ require completion_scope.kind="verified_effect"
→ require completion_scope.effect_kind="visual_region_changed"
→ move pointer to explicit normalized target
→ fresh pointer_state verifies target
→ persist prepared state
→ fresh target-local visual baseline
→ persist execution-start marker BEFORE input
→ NativeBody.act("pointer_click")
→ exactly one left click only if pointer is still at target
→ native_verification
→ fresh target-local visual probe
→ changed signature: close only the explicitly effect-scoped event
→ unchanged/unavailable: contradiction → Investigation
```

Properties:

- only one explicit left click exists; no right click, double click, drag, keyboard or generic browser agent;
- `NativeBody.pointer_click` never moves the cursor implicitly;
- click input API success is not completion proof;
- a durable `started` marker is written before click delivery; unresolved started state refuses blind replay;
- fresh local baseline and fresh post-click observation are required;
- missing/invalid visual postcondition, missing visual Sense, non-`effect_probe` event, missing/invalid completion scope, broader scope or unknown scope authority fields fail before input;
- `visual_region_changed` proves only that typed local effect;
- effect-only click success bypasses broad `event.task` self-model native-ability credit;
- broader semantic outcomes such as “form submitted”, “message sent”, “purchase completed” or equivalent remain unverified and therefore cannot use this narrow slice as proof.

Key commits:

```text
44ecb72d4c58f2c75a8e5c5d65d1820e64ceeed4  feat: add verified pointer click lifecycle
e2ab7600cafd18ca0956932af43fe6ae83f82449  refactor: minimize pointer body diff
a32c0f0dfd34e47371530e0ded2368401d3a8efb  test: align click success assertion with terminal lifecycle
de61fef5e24eb8a2f2fb99a389bf77b21faddcef  fix: bind pointer click completion scope
```

Exact-head run `32861070432` verified the current implementation with **405 tests passed / 5 skipped**. All eight pointer-click lifecycle tests passed, including:

```text
test_pointer_click_body_never_moves_implicitly
test_click_waits_for_position_baseline_and_fresh_effect_verification
test_interrupted_started_click_is_not_replayed
test_unchanged_local_region_contradicts_click_completion
test_click_without_narrow_visual_postcondition_fails_before_input
test_user_task_click_is_rejected_before_pointer_movement
test_effect_probe_without_exact_completion_scope_fails_before_input
test_effect_probe_completion_does_not_credit_task_prose_as_native_ability
```

## 6. External cognition, web/world and channels — VERIFIED FOUNDATION

Supported model providers remain bounded ZN-owned cognitive resources. Provider replacement does not replace resident identity, store or life state. ZN owns URL/network safety and web resource boundaries; channels remain I/O for the same resident.

## 7. Desktop ownership — VERIFIED

Active desktop path remains:

```text
ZN Electron main
→ ZN preload / IPC
→ long-lived resident RPC
→ ZN renderer
```

Run `32861070432` passed locked workspace dependency installation, high-severity npm audit, Electron typecheck, bundle, desktop ownership/runtime/update/handoff tests and release/runtime artifact verifier tests.

## 8. Runtime and artifact ownership — VERIFIED FOR EXERCISED TARGETS

Runtime identity remains:

```text
Python distribution: znagent
Python package:      zn_agent
entrypoint:          zn-resident
```

Run `32861070432` installed 29 formal runtime packages in fresh Windows Python 3.12.13 before zero-model boot and full tests. Historical artifact evidence exists for other exercised targets; steady-state development verification remains Windows x64.

## 9. Release/update state — M8 PARTIAL

Still open for current Windows x64 M8 target:

1. clean Windows install/login evidence;
2. installed Windows N→N+1 continuity evidence;
3. rollback validation across a real Windows version transition;
4. applicable secure Windows signing evidence.

M8 must not be reported complete until those are exercised.

## 10. Repository source boundary — COMPLETE AND CI-ENFORCED

Status: **COMPLETE**. The active tree remains physically ZN-only and exact-head Source Boundary passed in run `32861070432`. The historical source quarry is not an active runtime/build/test/package/release dependency.

## 11. Dependency security state

Electron remains on the patched `41.10.5` line and steady-state CI uses locked install plus `npm audit --audit-level=high`.

GitHub Actions still reports non-blocking Node 20→24 runtime deprecation warnings for some actions. Treat this as tooling maintenance debt, not a product failure.

## 12. Self-maintenance — SM0 COMPLETE, SM1+ OPEN

Architecture remains defined by `ZN-SELF-MAINTENANCE.md`. Full autonomous detect → investigate → isolated fix → PR → CI → merge → release is not yet owned end-to-end by ZN. High-risk identity/memory/credential/updater/rollback/signing/self-approval changes remain human-approved by default.

## 13. M10 status — COMPLETE

Canonical source promotion remains complete. `main` stays canonical source/release and `dev/zn-agent` stays normal development. This checkpoint did not modify `main` and did not change M8 status.

## 14. Current known debts

- a stronger typed semantic/current-world verifier for requested UI/application/world outcomes;
- a representation for higher-level completion scope that can be independently observed without model/task prose becoming authority or fact;
- real-session screen-capture and interactive-desktop availability evidence;
- broader computer-use primitives remain intentionally absent until matching authority and verifier contracts exist;
- M8 Windows clean-install/login, installed N→N+1, rollback and signing evidence;
- mature procedural competence/growth benchmarks;
- SM1+ autonomous self-maintenance;
- Node-action/deprecation warnings and other non-security tooling warnings.

## 15. Next real targets

```text
1. keep automatic Windows x64 CI green on every exact dev HEAD
2. preserve the new fail-closed effect completion scope while investigating semantic UI proof
3. design the smallest typed higher-level outcome contract with fresh current-world evidence appropriate to that contract
4. do not expand click/browser/input authority until such a verifier is implemented and tested
5. add real interactive-desktop/screen availability evidence when a suitable environment exists
6. close Windows M8 clean-install / N→N+1 / rollback / signing evidence
7. advance SM1+ behind existing approval and verification boundaries
```

Do not modify `main` through ordinary development. Any later status change belongs here only after real code/Git/CI evidence exists.
