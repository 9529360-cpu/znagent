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
32cfd3d4a6ed76906243ddf916a76fe5d2960cfe
feat: verify focused native control state
```

Status: **VERIFIED ON REAL WINDOWS X64 CI**.

Exact-head workflow evidence:

```text
run 32885707163

ZN Source Boundary / Windows       success
ZN Kernel / Python / Windows       success
Electron / TypeScript / Windows   success
Publish Windows CI statuses       success
```

The Kernel job used CPython 3.12.13, installed the formal `znagent` runtime from `runtime/python`, booted an isolated resident with zero external models, compiled the resident core, and ran full discovery:

```text
Ran 432 tests in 489.510s
OK (skipped=5)
```

The exact focused-control tests, existing foreground semantic-click tests, final input-boundary drift tests, source-boundary verification, desktop typecheck/build/tests, and CI status publisher all passed in that run.

Published commit contexts for `32cfd3d4...` are success:

```text
ZN Source Boundary
ZN Kernel / Python
Electron / TypeScript
```

## 2. Resident ownership

The resident continues to own persistent Self/life state, Situation/Thought/Will, durable WorkingState, Investigation, native Body actions and Senses, bounded cognition resources, memory/reconsolidation, verified experience/procedural tendencies, channels, and resident work/progress state.

The active pointer-click construction is now:

```text
provider_bridge.build_resident_runtime()
-> FocusedControlPointerClickResidentRuntime
-> SemanticPointerClickResidentRuntime
-> EffectScopedPointerClickResidentRuntime
-> VerifiedPointerClickResidentRuntime
-> resident-owned lower runtime chain
-> NativeBody
-> Windows input boundary
```

External models do not own identity, execution authority, current-world truth, or completion.

## 3. Body / Senses / computer interaction

### 3.1 Foreground-aware click boundary

The previously verified foreground semantic lifecycle remains intact:

- structured bounded `pointer_click` authority;
- exact typed `ui_state_transition` event authority;
- read-only `NativeForegroundWindowSense`;
- exact source `action_precondition.kind=foreground_window_matches`;
- exact destination `completion_scope.kind=foreground_window_matches`;
- zero-input completion when destination is already satisfied;
- bounded pointer movement and fresh pointer-state verification;
- fresh target-local visual baseline;
- durable non-replayable click `status="started"` marker;
- final fresh source-foreground recheck after the visual baseline and immediately before input;
- explicit final-precondition rejection as `status="aborted"`, `input_sent=false`;
- exactly one left click only while admitted authority remains valid;
- fresh local visual-effect verification;
- admitted event/scope/source-precondition drift checks after input;
- fresh destination proof before semantic completion.

### 3.2 Focused native-control Sense

Commit `32cfd3d4...` adds `NativeFocusedControlSense`, a resident-owned read-only Windows Sense for one deeper UI fact than top-level foreground identity.

It uses the current foreground GUI thread and Windows `GetGUIThreadInfo` to obtain the actual focused HWND, then fails closed unless that HWND is a real child/descendant of the current foreground window and belongs to the same foreground process.

The bounded observation contains:

```text
process_id
process_name
foreground_title
foreground_class_name
control_class_name
control_id
enabled
visible
captured_at
source
```

The native probe deliberately does **not** read focused-control text, inspect pixels, use OCR, call a model, or invoke accessibility mutation APIs. It also requires a positive control/dialog id; absent or ambiguous native identity fails closed.

### 3.3 Focused-control semantic completion

The active runtime adds a new exact completion scope:

```text
completion_scope.kind = focused_control_matches
process_name           = exact expected foreground process
foreground_title       = exact expected foreground title
control_class_name     = exact expected native control class
control_id             = exact positive native control id
```

A match additionally requires the observed control to be enabled and visible.

This scope is permitted only for typed `ui_state_transition` pointer-click events. If the target control is already focused, the event completes with zero pointer input.

If mutation is still needed, the existing exact foreground-window source `action_precondition` remains mandatory. The focused-control layer does not bypass the lower click lifecycle: pointer preparation, visual baseline, durable anti-replay marker, final source-window recheck, one left click, visual-effect proof, admitted-authority drift checks, and Investigation on contradiction remain in force.

After input, completion requires fresh exact focused-control evidence. Mismatch or unavailable focused-control evidence returns to Investigation without replaying the click.

Real Windows CI verified tests for:

- active resident ownership of the new Sense without probing on boot;
- bounded observation validation;
- already-focused target completing with zero input;
- exact focused-control match after click completing the typed transition;
- final source drift after visual baseline aborting before input;
- focused-control mismatch after click returning to Investigation without replay;
- invalid scope failing before probe/movement;
- missing focused-control Sense failing before pointer movement.

### 3.4 Scope limit

This is an HWND/native-control slice, not generic internal application semantics.

It is useful where an application exposes meaningful native child controls with stable class/id identity. It does **not** prove arbitrary Electron/Chromium DOM state, web content semantics, transaction completion, message delivery, network success, or arbitrary task prose.

Windows UI Automation remains a plausible later read-only cross-framework evidence source because it can expose element-level semantics beyond raw HWNDs, but it is a larger COM/cross-process surface. It is not yet part of ZN's runtime or authority model.

No keyboard, right-click, double-click, drag, OCR, generic browser control plane, model-derived execution fact, new dependency, or new mutation primitive was added by this slice.

## 4. Repository source boundary

The active tree remains ZN-only by contract and by exact-head CI evidence.

Run `32885707163` completed `ZN Source Boundary / Windows` successfully at `32cfd3d4...`. No ownership rule or scanner exemption was weakened.

## 5. Desktop / runtime / release

Run `32885707163` completed `Electron / TypeScript / Windows` successfully at the exact verified head, including locked dependency installation, high-severity advisory rejection, typecheck, bundle, desktop ownership/runtime/update/handoff contract tests, and release-channel/runtime-staging/artifact-verifier tests.

M8 remains **PARTIAL**. Still open for Windows x64:

1. clean Windows install/login evidence;
2. installed Windows N->N+1 continuity evidence;
3. rollback validation across a real Windows version transition;
4. applicable secure Windows signing evidence.

## 6. Self-maintenance

SM0 remains complete. SM1+ remains open. No self-maintenance architecture changed in this slice.

## 7. Current known debts / blockers

There is no current Windows CI infrastructure blocker.

Still open:

- real interactive-desktop foreground/screen/click/focused-control E2E evidence;
- semantic verification for modern framework/internal application elements that are not meaningful native child HWND controls;
- a bounded read-only cross-framework UI element Sense with a real typed caller, if justified;
- broader input primitives until matching typed authority and independent verification exist;
- M8 Windows install/upgrade/rollback/signing evidence;
- mature procedural competence/growth benchmarks;
- SM1+;
- non-blocking GitHub Actions JavaScript runtime deprecation warnings.

## 8. Next real targets

```text
1. keep exact-head Windows x64 CI green
2. evaluate the smallest useful read-only cross-framework UI element evidence beyond native HWND focus
3. trace entry -> owner -> state -> lifecycle -> dependency -> tests -> active caller before implementation
4. prefer read-only evidence first; do not let UI Automation or another accessibility layer become a mutation/control plane
5. add nothing if it would be unused telemetry
6. keep real interactive-desktop E2E explicitly open until executed
7. keep M8 and SM1+ explicitly partial/open
8. leave main untouched through ordinary development
```
