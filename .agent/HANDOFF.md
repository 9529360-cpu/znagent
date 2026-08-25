# ZN Agent Handoff

Updated: 2026-08-25

## Current goal

The read-only cross-framework UI Automation focus slice is now verified on real Windows x64 CI. The next engineering target is not generic UIA expansion; it is real interactive-desktop E2E evidence for the existing screen -> pointer -> foreground -> UIA-focus chain, or the smallest reliable repository-defined lane that can produce that evidence without secrets or unsafe automation.

Core principle:

> **ZN uses models. Models do not own ZN.**

## Branch / HEAD

- fixed development branch: `dev/zn-agent`
- canonical source/release branch: `main`
- latest fully verified implementation head: `f5bca98003d01fb8bf64b36cf56c2a440385ff1b`
- canonical `main`: `8234a835dea604783cea0bd9d28a40de654ec03d`
- PR #6 remains draft/open/unmerged, base `main`, head `dev/zn-agent`
- dev is ahead 92 / behind 0 relative to main before this handoff sync
- main was not modified
- no force push or history rewrite was used

## Completed in current stage

### 1. Restored and reconciled repository truth

The required six documents, dev/main refs, PR #6, main-to-dev compare, exact-head CI, active builder, UIA Sense and click completion layer were re-read from GitHub.

Repository truth before this docs sync:

```text
dev  f5bca98003d01fb8bf64b36cf56c2a440385ff1b
main 8234a835dea604783cea0bd9d28a40de654ec03d
PR #6 open / draft / mergeable / unmerged
main -> dev: ahead 92 / behind 0
```

The previous STATUS/HANDOFF were stale because they still described `32cfd3d4...` as the latest verified implementation. Code and CI now outrank those stale ledgers.

### 2. UI Automation element Sense is active

Implementation lineage:

```text
0eba38cd9ff77c4ededeaff269bb0a9ca9ceb2b6
feat: verify focused automation target

fa214a4c178625bd92580033aedfa781b3cc3cbe
fix: initialize UI automation worker as MTA

f5bca98003d01fb8bf64b36cf56c2a440385ff1b
fix: create UI automation v2 client directly
```

Active builder:

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

This is not unused telemetry: the read-only UIA Sense has a typed active completion caller.

### 3. Native UIA read boundary

`runtime/python/zn_agent/core/automation_element_sense.py` provides a lazy `NativeAutomationElementSense`.

The native reader:

- starts only on first use, not resident boot;
- owns one daemon MTA read worker;
- ensures a fresh worker selects MTA before the first `comtypes` import;
- creates the UI Automation v2-capable COM client directly;
- applies bounded connection/transaction timeouts;
- keeps generated type-library wrappers memory-only;
- uses `AutomationElementMode_None` + `TreeScope_Element` cache requests;
- reads only cached properties;
- supports one element-at-point probe and one focused-element probe;
- never walks the UIA tree;
- never subscribes to UIA events;
- never requests a control pattern;
- never mutates through UI Automation.

Bounded observation:

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

`Name` and `AutomationId` remain intentionally excluded. `RuntimeId` is opaque and action-cycle scoped; it is not durable identity or learned semantic identity.

### 4. Typed automation-focus completion

Scope:

```text
completion_scope.kind = focused_automation_element_at_pointer
process_name
 title_equals
```

The exact source foreground `action_precondition` is mandatory and must match the same exact process/title as the completion scope.

Zero-input path:

```text
fresh exact foreground
-> exact structured target coordinate
-> read-only UIA element at point
-> read-only focused UIA element
-> same opaque RuntimeId + eligible + has keyboard focus
-> complete without movement/input
```

Mutation path:

```text
fresh exact source foreground admission
-> lower verified pointer preparation
-> visual baseline
-> durable non-replayable started marker
-> final exact source foreground recheck
-> read-only UIA target at exact prepared coordinate
-> require expected process + enabled + focusable + on-screen
-> persist action-cycle RuntimeId evidence
-> exactly one admitted left click
-> independent local visual-effect proof
-> fresh exact destination foreground
-> fresh focused UIA element
-> require same RuntimeId + eligible + has keyboard focus
-> complete
```

Any missing, drifting or contradictory evidence returns to Investigation without replaying uncertain pointer input.

### 5. Two real Windows integration failures were fixed at root cause

Run `32889119734` exposed the first native integration error:

```text
RPC_E_CHANGED_MODE
```

Cause: `comtypes` can initialize the importing thread automatically; the worker had imported it before explicitly selecting MTA.

Fix `fa214a4c...`: select MTA before first import on a fresh worker, while retaining explicit per-thread MTA initialization when `comtypes` is already loaded elsewhere.

Run `32890346314` then exposed:

```text
E_NOINTERFACE
```

Cause: the old UI Automation coclass was created and then queried for a newer interface it did not provide.

Fix `f5bca980...`: create the UI Automation v2-capable coclass directly. No test, timeout, cache-only boundary or authority rule was weakened.

### 6. Exact-head Windows CI is fully green

Workflow:

```text
run  32891800589
head f5bca98003d01fb8bf64b36cf56c2a440385ff1b
```

Results:

```text
ZN Source Boundary / Windows       success
ZN Kernel / Python / Windows       success
Electron / TypeScript / Windows   success
Publish Windows CI statuses       success
```

Kernel evidence:

```text
CPython 3.12.13
formal runtime installed from runtime/python
comtypes 1.4.16 installed on Windows
zero-model isolated resident boot success
resident core compile success
native MTA cache-only UIA client initialization success
Ran 446 tests in 515.441s
OK (skipped=5)
```

The real native reader initialization test passed. All automation-focus behavioral tests and all earlier foreground/native-focused-control/pointer-click lifecycle tests remained green.

Published commit contexts are success:

```text
ZN Source Boundary
ZN Kernel / Python
Electron / TypeScript
```

## Risks / boundaries

- Do not modify main through ordinary development.
- No force push/history rewrite.
- Do not weaken source-boundary scanning.
- UI Automation remains a read-only Sense, not a new mutation/control plane.
- RuntimeId is opaque, desktop-local/action-cycle evidence and must not become long-term identity or memory.
- `IsOffscreen=false` does not prove an element is unobscured by another window.
- UIA element process identity may differ across Chromium/Electron process topology; real interactive E2E must verify actual product behavior before widening semantics.
- This scope proves keyboard focus on the exact pre-click UIA target, not arbitrary DOM/business state.
- Real interactive-desktop E2E is still absent.
- No keyboard/right-click/double-click/drag authority has been added.
- M8 updater/rollback/signing remains partial and high risk.
- SM1+ remains open.
- GitHub Actions JavaScript runtime deprecation warnings remain non-blocking tooling debt.

## Task queue

### P0 - exact-head Windows CI
Status: **VERIFIED / GREEN**

Run `32891800589` at `f5bca980...`; all four required Windows jobs succeeded and Kernel completed **446 tests / 5 skipped / OK**.

### P1 - bounded verifier manifest
Status: **VERIFIED NARROW SLICE / THREE REAL RELATIONS**

### P2 - resident visual foundation
Status: **VERIFIED FOUNDATION**

Real interactive-desktop capture evidence remains open.

### P3 - bounded pointer movement
Status: **VERIFIED**

### P4 - narrow pointer click lifecycle
Status: **VERIFIED NARROW SLICE INCLUDING FINAL INPUT BOUNDARY**

### P5 - semantic/current-world UI verification
Status: **FOREGROUND + NATIVE FOCUSED-CONTROL + UIA FOCUSED-TARGET SLICES VERIFIED**

Verified evidence now includes exact source foreground authority, final pre-input source recheck, visual effect proof, exact foreground destination completion, exact focused native-child control completion, and exact opaque UIA target-focus completion for the current action cycle.

Real interactive-desktop E2E remains open and must not be implied by unit/integration initialization coverage.

### P6 - M8 Windows continuity / rollback / signing
Status: **PENDING / PARTIAL**

### P7 - SM1+ self-maintenance
Status: **PENDING**

## Next real target

1. investigate how repository automation can execute a real interactive Windows desktop E2E for screen capture, pointer movement/click, exact foreground identity and UIA target/focused identity;
2. do not require production secrets or unsafe unattended mutation merely to obtain E2E evidence;
3. if no reliable interactive-desktop lane exists, keep the gap explicit rather than faking it with mocks;
4. do not widen UIA into generic tree search or control-pattern mutation without a concrete typed caller and separate authority design;
5. keep RuntimeId short-lived and action-cycle scoped;
6. keep M8 and SM1+ explicitly open;
7. keep exact-head Windows CI green;
8. keep `main` untouched.
