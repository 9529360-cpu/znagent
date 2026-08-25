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

Latest fully verified implementation head:

```text
1e325926149f4df00ac7f7f83ba3d82c6611b7e6
test: assert click admission before completion reset
```

Status: **VERIFIED ON REAL WINDOWS X64 CI**.

Exact-head workflow evidence:

```text
run 32882987054

ZN Source Boundary / Windows       success
ZN Kernel / Python / Windows       success
Electron / TypeScript / Windows   success
Publish Windows CI statuses       success
```

The kernel job used CPython 3.12.13, installed the formal `znagent` runtime from `runtime/python`, booted an isolated resident with zero external models, compiled the resident core, and ran full discovery:

```text
Ran 423 tests
OK (skipped=5)
```

The commit status publisher also finished successfully; `ZN Source Boundary`, `ZN Kernel / Python`, and `Electron / TypeScript` are published as success for `1e325926...`.

The immediately preceding exact-head run `32875624835` at `abbacede34e...` executed on the same Windows runner and exposed one test error. The runtime behavior itself had reached successful semantic completion, but the test tried to read `native_pointer_click_semantic_precondition` after `_complete_result()` had intentionally replaced WorkingState with `stage="idle"`. Commit `1e325926...` moved those admission assertions to the preceding `native_verification` state. No product runtime behavior changed in that fix. The subsequent exact-head run above proves the correction.

## 2. Resident ownership

The resident continues to own persistent Self/life state, Situation/Thought/Will, durable WorkingState, Investigation, native Body actions and Senses, bounded cognition resources, memory/reconsolidation, verified experience/procedural tendencies, channels, and resident work/progress state.

Active pointer-click construction remains:

```text
provider_bridge.build_resident_runtime()
-> SemanticPointerClickResidentRuntime
-> EffectScopedPointerClickResidentRuntime
-> VerifiedPointerClickResidentRuntime
-> resident-owned lower runtime chain
-> NativeBody
-> Windows input boundary
```

External models do not own identity, execution authority, current-world truth, or completion.

## 3. Body / Senses / computer interaction

### Verified foreground-aware click boundary

The narrow UI chain is now verified through `1e325926...`.

It includes:

- structured bounded `pointer_click` authority;
- exact typed `ui_state_transition` event authority;
- read-only `NativeForegroundWindowSense`;
- exact destination `completion_scope.kind=foreground_window_matches` with process/title identity;
- exact source `action_precondition.kind=foreground_window_matches`;
- target-already-satisfied completion with zero pointer input;
- bounded pointer movement and fresh pointer-state verification;
- fresh target-local visual baseline;
- durable non-replayable click `status="started"` marker;
- a final fresh source-foreground check after the visual baseline and immediately before input;
- explicit final-precondition rejection recorded as `status="aborted"` and `input_sent=false`;
- exactly one left click when authority remains valid;
- fresh local visual-effect verification;
- admitted event/scope/source-precondition drift checks after input;
- fresh destination foreground proof before semantic completion.

Verified lifecycle:

```text
fresh source foreground observation
-> if exact destination is already satisfied: complete with zero input
-> otherwise require exact source action_precondition
-> source must match before pointer movement
-> persist admitted event/scope/source authority
-> bounded pointer movement/preparation
-> reject admitted authority drift
-> fresh pointer-state check
-> fresh target-local visual baseline
-> persist baseline + durable execution status="started"
-> FINAL fresh source-foreground check
   -> exact match: continue
   -> mismatch/unavailable: status="aborted", input_sent=false; Investigation
-> one left click
-> fresh local visual effect verification
-> reject post-input event/scope/source-authority drift
-> fresh destination foreground match
-> typed ui_state_transition completion
```

The base `VerifiedPointerClickResidentRuntime` owns a default no-op `_pointer_click_final_input_precondition()` hook. `SemanticPointerClickResidentRuntime` overrides it with the foreground source check. Effect-only click semantics therefore were not widened.

Foreground process/title proves only application/window identity. It does not prove internal control state, transaction completion, message delivery, network success, or arbitrary task prose.

No keyboard, right-click, double-click, drag, OCR, generic browser control plane, model-derived execution fact, new dependency, or new mutation primitive was added by this slice.

## 4. Repository source boundary

The active tree remains ZN-only by contract and by current exact-head CI evidence.

Run `32882987054` completed `ZN Source Boundary / Windows` successfully at `1e325926...`. No ownership rule or scanner exemption was weakened by the pointer-click work or the test-only follow-up.

## 5. Desktop / runtime / release

Run `32882987054` also completed `Electron / TypeScript / Windows` successfully at the exact verified head, including locked dependency installation, high-severity advisory rejection, typecheck, bundle, desktop ownership/runtime/update/handoff contract tests, and release-channel/runtime-staging/artifact-verifier tests.

M8 remains **PARTIAL**. Still open for Windows x64:

1. clean Windows install/login evidence;
2. installed Windows N->N+1 continuity evidence;
3. rollback validation across a real Windows version transition;
4. applicable secure Windows signing evidence.

## 6. Self-maintenance

SM0 remains complete. SM1+ remains open. No self-maintenance architecture changed in this slice.

## 7. Current known debts / blockers

The self-hosted Windows runner availability incident is no longer the current blocker; the runner accepted and completed the exact-head workflow.

Still open:

- real interactive-desktop foreground-window/screen-capture/click E2E evidence;
- semantic verification deeper than application/window identity;
- structured read-only internal UI/application-state evidence with a real active caller;
- broader input primitives until matching typed authority and independent verification exist;
- M8 Windows install/upgrade/rollback/signing evidence;
- mature procedural competence/growth benchmarks;
- SM1+;
- non-blocking GitHub Actions JavaScript runtime deprecation warnings.

## 8. Next real targets

```text
1. keep exact-head Windows x64 CI green
2. resume P5 with the smallest useful read-only internal UI/application-state evidence beyond foreground-window identity
3. trace entry -> owner -> state -> lifecycle -> dependency -> tests -> active caller before adding that Sense
4. do not add dead telemetry: new evidence must feed a typed completion/precondition/investigation boundary that actually uses it
5. keep real interactive-desktop E2E explicitly open until executed
6. keep M8 and SM1+ explicitly partial/open
7. leave main untouched through ordinary development
```
