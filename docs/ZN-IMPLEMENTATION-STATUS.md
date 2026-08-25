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
f5bca98003d01fb8bf64b36cf56c2a440385ff1b
fix: create UI automation v2 client directly
```

Status: **VERIFIED ON REAL WINDOWS X64 CI**.

Exact-head workflow evidence:

```text
run 32891800589

ZN Source Boundary / Windows       success
ZN Kernel / Python / Windows       success
Electron / TypeScript / Windows   success
Publish Windows CI statuses       success
```

The Kernel job used CPython 3.12.13, installed the formal `znagent` runtime from `runtime/python`, booted an isolated resident with zero external models, compiled the resident core, initialized the native Windows UI Automation reader, and ran full discovery:

```text
Ran 446 tests in 515.441s
OK (skipped=5)
```

The native UI Automation initialization test passed on the real Windows runner. Published commit contexts for `f5bca980...` are success:

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
-> AutomationFocusPointerClickResidentRuntime
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

### 3.1 Existing verified click boundary

The previously verified lifecycle remains intact:

- structured bounded `pointer_click` authority;
- exact typed `ui_state_transition` event authority;
- read-only foreground-window Sense;
- exact source `action_precondition.kind=foreground_window_matches`;
- bounded pointer movement and fresh pointer-state verification;
- fresh target-local visual baseline;
- durable non-replayable click `status="started"` marker;
- final fresh source-foreground recheck after the visual baseline and immediately before input;
- explicit final-precondition rejection as `status="aborted"`, `input_sent=false`;
- exactly one left click only while admitted authority remains valid;
- fresh local visual-effect verification;
- admitted event/scope/source-precondition drift checks after input;
- contradiction returns to Investigation without replaying uncertain input.

The native focused-control scope also remains verified and available for meaningful Win32 child controls with stable class/control-id identity.

### 3.2 Read-only Windows UI Automation Sense

The new cross-framework element Sense is `NativeAutomationElementSense`.

Windows runtime dependency:

```text
comtypes==1.4.16 ; platform_system == "Windows"
```

The native reader is deliberately narrow:

- starts lazily only when the Sense is first used;
- runs on a dedicated daemon MTA worker rather than the resident thread;
- selects MTA before the first `comtypes` import on a fresh worker;
- creates the UI Automation v2-capable `CUIAutomation8` client and uses `IUIAutomation2` for bounded provider timeouts;
- uses `BuildCache` calls with `AutomationElementMode_None` and `TreeScope_Element`;
- reads only cached element properties;
- probes either the element at one exact desktop point or the current focused element;
- does not walk the UIA tree;
- does not subscribe to UIA events;
- does not request or invoke any control pattern;
- does not mutate application state through UI Automation.

The bounded observation contains:

```text
runtime_id
process_id
process_name
framework_id
control_type
class_name
is_enabled
is_keyboard_focusable
has_keyboard_focus
is_offscreen
native_window_handle
captured_at
source
```

`Name` and `AutomationId` are intentionally not collected or persisted. `RuntimeId` is treated as opaque short-lived identity for comparison inside the current action cycle only, not as a durable semantic identifier across restarts or application versions.

### 3.3 Focused automation-element completion

The active runtime recognizes the exact scope:

```text
completion_scope.kind = focused_automation_element_at_pointer
process_name
 title_equals
```

The source `action_precondition.kind=foreground_window_matches` must identify the same exact foreground process/title as the completion scope.

For this scope:

1. If the exact pointer-target UIA element already has keyboard focus, the transition may complete with zero pointer movement/input.
2. If mutation is required, the lower verified click lifecycle prepares the exact coordinates and visual baseline first.
3. At the final input boundary, the resident freshly rechecks the source foreground window.
4. Only then does it call read-only `ElementFromPointBuildCache` for the exact prepared pointer coordinate.
5. The target must belong to the expected process and be enabled, on-screen, and keyboard-focusable.
6. Its opaque `RuntimeId` is recorded for the current action cycle before input.
7. After the one admitted click and independent local visual-effect proof, the resident freshly verifies the destination foreground window and calls read-only `GetFocusedElementBuildCache`.
8. Completion requires the focused element to have the same opaque `RuntimeId`, remain eligible, and report keyboard focus.
9. Missing/mismatched evidence returns to Investigation and does not replay the click.

This adds cross-framework focus evidence for UIA-exposed elements, including cases where meaningful internal application elements are not represented by useful native child HWND controls.

It does **not** prove arbitrary DOM state, text/content meaning, business transaction completion, message delivery, network success, or arbitrary task prose.

### 3.4 Real Windows verification

Run `32891800589` at `f5bca980...` verified:

- native MTA UI Automation reader initialization;
- correct UI Automation v2 client creation;
- Windows-only COM client dependency installation;
- observation excludes dynamic `Name` and `AutomationId` fields;
- injected point/focused probes return bounded structured observations;
- invalid/missing RuntimeId fails closed;
- active resident owns the automation Sense without probing on boot;
- already-focused exact target completes with zero input;
- exact pre-click UIA target receiving focus after click completes the typed transition;
- final foreground drift aborts before UIA target capture/input;
- non-focusable final target is rejected before input;
- invalid scope fails before probe/movement;
- missing UIA Sense fails before movement;
- post-click focus mismatch returns to Investigation without replay;
- source window must equal the destination window for this element-focus scope;
- all previously verified foreground/native-focused-control/click lifecycle tests remain green.

Two preceding CI failures were resolved without weakening tests or authority:

- `fa214a4c...` fixed COM apartment initialization order by selecting MTA before first `comtypes` import on a fresh worker;
- `f5bca980...` fixed `E_NOINTERFACE` by creating the v2-capable UI Automation COM class directly instead of querying the older class for an unsupported interface.

## 4. Repository source boundary

The active tree remains ZN-only by contract and by exact-head CI evidence.

Run `32891800589` completed `ZN Source Boundary / Windows` successfully at `f5bca980...`. No ownership rule or scanner exemption was weakened.

## 5. Desktop / runtime / release

Run `32891800589` completed `Electron / TypeScript / Windows` successfully at the exact verified head, including locked dependency installation, high-severity advisory rejection, typecheck, bundle, desktop ownership/runtime/update/handoff contract tests, and release-channel/runtime-staging/artifact-verifier tests.

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

- real interactive-desktop foreground/screen/pointer/native-focus/UIA-focus E2E evidence;
- broader semantic verification for application state beyond keyboard focus;
- any future UIA property/tree use must have a real typed active caller and remain read-only unless a separate authority design is approved;
- broader input primitives until matching typed authority and independent verification exist;
- M8 Windows install/upgrade/rollback/signing evidence;
- mature procedural competence/growth benchmarks;
- SM1+;
- non-blocking GitHub Actions JavaScript runtime deprecation warnings.

## 8. Next real targets

```text
1. keep exact-head Windows x64 CI green
2. run/establish real interactive-desktop E2E evidence for the existing screen -> pointer -> foreground -> UIA focus chain before widening UI semantics
3. investigate the next useful read-only application-state evidence only from a concrete typed caller
4. do not turn UI Automation into a generic mutation/control plane
5. keep RuntimeId short-lived and action-cycle scoped
6. keep M8 and SM1+ explicitly partial/open
7. leave main untouched through ordinary development
```
