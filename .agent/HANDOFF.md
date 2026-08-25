# ZN Agent Handoff

Updated: 2026-08-25

## Current goal

The mainline remains **browser/computer Body/Senses**. This stage implemented the first narrow semantic/current-world UI completion slice: a pointer-click `ui_state_transition` may close only when a separate resident-owned read-only foreground-window Sense freshly proves the exact structured `process_name + title_equals` scope.

The next target is not broader input authority. It is deeper read-only UI/application state evidence for a typed outcome that foreground-window identity alone cannot prove.

Core principle:

> **ZN uses models. Models do not own ZN.**

## Branch / HEAD

- fixed development branch: `dev/zn-agent`
- canonical source/release branch: `main`
- implementation HEAD before this docs sync: `6f25b30c46d2f1bcafdd8f62e0968c2a4d05623e`
- canonical `main`: `8234a835dea604783cea0bd9d28a40de654ec03d`
- implementation HEAD is ahead 79 / behind 0 relative to `main`; this docs sync advances dev once more
- PR #6 remains draft/open, base `main`, head `dev/zn-agent`, unmerged at implementation verification time
- `main` was not modified; no force push/history rewrite was used

## Completed

### 1. Existing effect-scoped pointer click remains intact

The previously verified chain is still active:

```text
pointer_click
+ expected_outcome visual_region_changed
+ event.kind effect_probe
+ exact verified_effect/visual_region_changed completion_scope
+ fresh pointer position
+ local visual baseline
+ durable started marker before input
+ exactly one left click
+ fresh local visual change
-> only the matching effect_probe may complete
```

Ordinary broad `user_task` click still fails before pointer movement. Effect-only completion still avoids arbitrary task-prose native-ability credit.

### 2. New read-only foreground-window Sense

Implementation commit:

```text
6f25b30c46d2f1bcafdd8f62e0968c2a4d05623e  feat: verify foreground ui state
```

New `NativeForegroundWindowSense` uses Windows `user32` plus resident runtime `psutil` to obtain bounded current-world facts:

```text
GetForegroundWindow
GetWindowTextW
GetWindowThreadProcessId
GetClassNameW
psutil.Process(pid).name()
-> ForegroundWindowObservation
```

Evidence fields are `process_id`, exact `title`, required `process_name`, `class_name`, `captured_at`, and source. It is stateless/read-only: no OCR, no model, no screenshot persistence, no input action.

If process identity/name cannot be obtained, evidence is unavailable rather than silently treated as a mismatch.

### 3. Typed foreground-window semantic completion

Active construction:

```text
provider_bridge.build_resident_runtime()
-> SemanticPointerClickResidentRuntime
-> EffectScopedPointerClickResidentRuntime
-> VerifiedPointerClickResidentRuntime
-> existing repository/procedural/world-aware resident chain
```

Real ingress is reachable without a new protocol: daemon/work ledger already pass caller-provided typed `kind` into `resident.enqueue()`.

New semantic contract:

```text
event.kind = ui_state_transition
completion_scope.kind = foreground_window_matches
completion_scope.process_name = exact non-empty process name
completion_scope.title_equals = exact non-empty foreground title
```

Unknown scope fields fail closed.

Lifecycle:

```text
semantic contract admission
-> require resident-owned foreground-window Sense before pointer movement
-> one fresh preflight before pointer preparation
   -> target already matches: terminal success with zero pointer movement/click
   -> evidence unavailable: fail closed before movement
   -> mismatch: continue existing click lifecycle
-> persist admitted event kind + semantic scope in native_verification
-> existing local click effect must verify
-> fresh foreground-window probe after click
   -> exact process/title match: close only this ui_state_transition
   -> mismatch/unavailable: Investigation, no click replay
-> post-input admitted-scope/event-kind drift: Investigation, no replay
```

No generic `_complete_successful_body_action()` task-prose ability credit is used for this semantic completion.

### 4. Semantic boundary remains narrow

This slice proves only that the exact application/window is foreground. It does **not** prove:

```text
form submitted
message sent
purchase completed
network delivery
internal application state not represented by foreground process/title
```

Task prose, model output, Body API success, or local visual change alone cannot make those claims true.

No keyboard, right-click, double-click, drag, generic browser automation catalog, or other mutation primitive was added.

## Real tests / CI

Authoritative implementation-head evidence:

```text
run  32866088556
head 6f25b30c46d2f1bcafdd8f62e0968c2a4d05623e

ZN Kernel / Python / Windows        success
ZN Source Boundary / Windows       success
Electron / TypeScript / Windows    success
Publish Windows CI statuses        success
```

Kernel evidence:

```text
fresh isolated CPython 3.12.13      success
formal runtime install              success
29 runtime packages                 installed
Pillow 12.3.0                       installed
psutil 7.2.2                        installed
zero-model resident boot            success
resident core compile               success
full unittest discovery             416 passed, 5 skipped
```

All 11 new tests passed:

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

All eight previous pointer-click lifecycle tests also passed. Electron passed locked install, high-severity audit, typecheck, bundle, ownership/runtime/update/handoff contracts, and release/runtime artifact verifiers. Source Boundary passed.

Local generated files were statically compiled before commit. There is no authoritative local private checkout; exact-head GitHub Actions is the executed test source of truth.

## Diff / ownership reconciliation

Implementation parent -> `6f25b30c...` was reviewed before moving the branch and contained exactly five files:

```text
runtime/python/zn_agent/core/foreground_window_sense.py              added
runtime/python/zn_agent/core/pointer_click_semantic_resident.py      added
runtime/python/zn_agent/core/provider_bridge.py                      2 add / 2 delete builder switch
tests/zn_agent/core/test_foreground_window_sense.py                  added
tests/zn_agent/core/test_pointer_click_semantic_completion.py        added
```

The previous `pointer_click_completion_resident.py` was not modified. `dev/zn-agent` was advanced with `force=false`.

No `ZN.md`, `ZN-SOURCE-EXTRACTION.md`, or `ZN-SELF-MAINTENANCE.md` change is required for this stage: no architecture direction, reference-source extraction state, or self-maintenance architecture changed.

## Risks / boundaries

- Do not modify `main` through ordinary development.
- No force push/history rewrite.
- Foreground process/title identity is not arbitrary task/business semantic proof.
- Exact title matching is intentionally strict and can be brittle; weakening it to substring/model interpretation would enlarge authority and is not justified by this slice.
- The Windows CI semantic lifecycle uses injected foreground-window probes. Real interactive-desktop foreground-window + click E2E evidence remains absent.
- Broader input authority remains intentionally absent.
- Node 20->24 action runtime deprecation warnings remain non-blocking tooling debt.
- M8 updater/rollback/signing remains partial/high risk.

## Task queue

### P0 - exact-head Windows CI
Status: **GREEN THROUGH `6f25b30c...` / RUN `32866088556`**

This STATUS/HANDOFF sync creates a later docs HEAD. Let automatic CI verify it; do not create an infinite docs-only loop solely to record its own run ID.

### P1 - bounded verifier manifest
Status: **VERIFIED NARROW SLICE / THREE REAL RELATIONS**

### P2 - resident visual foundation
Status: **VERIFIED FOUNDATION**

Real interactive-desktop capture evidence remains open.

### P3 - bounded pointer movement
Status: **VERIFIED**

### P4 - narrow pointer click lifecycle
Status: **VERIFIED NARROW SLICE**

### P5 - semantic/current-world UI verification
Status: **NARROW FOREGROUND-WINDOW SLICE VERIFIED / DEEPER SEMANTICS OPEN**

Verified now:

```text
explicit typed ui_state_transition
+ exact foreground_window_matches process/title scope
+ fresh read-only OS foreground-window evidence
+ existing independently verified local click effect when mutation is needed
-> only matching foreground-window state may complete
```

Still open:

```text
explicit deeper UI/application semantic outcome
+ fresh read-only evidence appropriate to that exact internal state
-> only matching higher-level outcome may complete
```

Do not infer that evidence from natural-language task text or model claims.

### P6 - M8 Windows continuity / rollback / signing
Status: **PENDING / PARTIAL**

### P7 - SM1+ self-maintenance
Status: **PENDING**

## Next real target

1. verify the docs-sync HEAD on automatic Windows x64 CI;
2. trace the smallest useful internal UI/application state that can be independently observed read-only beyond foreground process/title;
3. add a typed semantic contract only if fresh evidence can prove that exact state;
4. prefer another smallest read-only Sense over weakening proof requirements or expanding mutation authority;
5. keep real interactive-desktop E2E, M8, and SM1+ explicitly open;
6. leave `main` untouched.
