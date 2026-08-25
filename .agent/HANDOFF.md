# ZN Agent Handoff

Updated: 2026-08-25

## Current goal

The active lane remains browser/computer Body/Senses. The focused native-control semantic slice is now verified on real Windows x64 CI. The next engineering target is the smallest useful read-only cross-framework UI element evidence beyond native HWND focus, but only if it has a real typed active caller and does not become a new mutation/control plane.

Core principle:

> **ZN uses models. Models do not own ZN.**

## Branch / HEAD

- fixed development branch: `dev/zn-agent`
- canonical source/release branch: `main`
- latest fully verified implementation head before this handoff sync: `32cfd3d4a6ed76906243ddf916a76fe5d2960cfe`
- canonical `main`: `8234a835dea604783cea0bd9d28a40de654ec03d`
- PR #6 remains draft/open/unmerged, base `main`, head `dev/zn-agent`
- dev is ahead 88 / behind 0 relative to main before this docs sync
- main was not modified
- no force push or history rewrite was used

## Completed in current stage

### 1. Restored real repository state

The required six documents, dev/main refs, PR #6, recent commits, main-to-dev compare, current exact-head CI, active builder, focused-control Sense, semantic click layer and tests were re-read from GitHub before continuing.

Repository truth before this docs sync:

```text
dev  32cfd3d4a6ed76906243ddf916a76fe5d2960cfe
main 8234a835dea604783cea0bd9d28a40de654ec03d
PR #6 open / draft / mergeable / unmerged
```

### 2. Focused native-control implementation is active

Commit:

```text
32cfd3d4a6ed76906243ddf916a76fe5d2960cfe
feat: verify focused native control state
```

Active builder now returns:

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

This is not dead telemetry; the new Sense has a real typed completion caller.

### 3. New read-only focused-control Sense

`runtime/python/zn_agent/core/focused_control_sense.py` uses Windows user32 only and introduces no new dependency.

Native evidence flow:

```text
GetForegroundWindow
-> GetWindowThreadProcessId
-> GetGUIThreadInfo(foreground thread)
-> hwndFocus
-> require hwndFocus is a child/descendant of foreground HWND
-> require same foreground process
-> GetClassNameW
-> GetDlgCtrlID
-> IsWindowEnabled / IsWindowVisible
-> bounded FocusedControlObservation
```

Observation contains exact process/window/control identity plus enabled/visible state. It intentionally does not read focused-control text, inspect pixels, invoke OCR/models, or use accessibility mutation APIs.

The Sense fails closed if there is no focused native child control, no class identity, cross-process focus, or no stable positive control/dialog id.

### 4. New typed focused-control completion scope

The active click semantic layer recognizes:

```text
completion_scope.kind = focused_control_matches
process_name
foreground_title
control_class_name
control_id
```

All identity fields are exact, `control_id` must be positive, and an observed match additionally requires enabled + visible.

This completion scope is permitted only for `ui_state_transition` pointer-click events.

If the exact target control is already focused, completion occurs with zero pointer input.

If a click is needed, the existing exact source:

```text
action_precondition.kind = foreground_window_matches
```

remains mandatory. The focused layer does not bypass pointer preparation, visual baseline, durable non-replayable `started` state, final source-window check, one left click, visual effect verification, admitted-authority drift checks, or contradiction -> Investigation behavior.

After input, fresh focused-control evidence must exactly match before semantic completion. Mismatch/unavailable evidence returns to Investigation and the click is not replayed.

### 5. Exact-head Windows CI is fully green

Workflow:

```text
run  32885707163
head 32cfd3d4a6ed76906243ddf916a76fe5d2960cfe
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
zero-model isolated resident boot success
resident core compile success
Ran 432 tests in 489.510s
OK (skipped=5)
```

The new focused-control tests all passed on the real Windows runner, including:

- active resident owns the Sense without probing on boot;
- invalid/missing control identity fails closed;
- already-focused target completes with zero input;
- exact focused-control match after click completes the typed transition;
- final source drift after visual baseline aborts before input;
- post-click focused-control mismatch returns to Investigation without replay;
- invalid focused scope fails before probe/movement;
- missing focused-control Sense fails before pointer movement.

All prior foreground semantic click tests remained green.

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
- Native focused-control identity is deeper than foreground-window identity but remains an HWND/Win32 slice.
- It does not prove arbitrary Electron/Chromium DOM state, business-state completion, message delivery or network success.
- Cross-process focused-control text is intentionally not used as evidence.
- Windows UI Automation may be a useful later read-only cross-framework Sense, but it is a substantially larger COM/cross-process surface and is not currently runtime authority.
- Real interactive-desktop E2E is still absent even though resident behavior is CI verified.
- Broader input authority remains intentionally absent.
- M8 updater/rollback/signing remains partial and high risk.
- SM1+ remains open.
- GitHub Actions JavaScript runtime deprecation warnings are tooling debt, not a current functional failure.

## Task queue

### P0 - exact-head Windows CI
Status: **VERIFIED / GREEN**

Run `32885707163` at `32cfd3d4...`; all four required Windows jobs succeeded and Kernel completed **432 passed / 5 skipped**.

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
Status: **FOREGROUND + NATIVE FOCUSED-CONTROL SLICE VERIFIED**

Verified evidence now includes exact source foreground authority, final pre-input source recheck, visual effect proof, exact foreground destination completion, and exact focused native-child control completion.

Modern framework/internal application elements that do not expose useful native child HWND identity remain open.

### P6 - M8 Windows continuity / rollback / signing
Status: **PENDING / PARTIAL**

### P7 - SM1+ self-maintenance
Status: **PENDING**

## Next real target

1. evaluate the smallest useful read-only cross-framework UI element Sense beyond native HWND focus;
2. trace entry -> owner -> state -> lifecycle -> dependency -> tests -> active caller before implementation;
3. prefer read-only semantics first and do not make UI Automation or any accessibility layer a mutation/control plane;
4. add nothing if it would be unused telemetry;
5. keep real interactive-desktop E2E explicitly open until executed;
6. keep M8 and SM1+ explicitly open;
7. keep exact-head Windows CI green;
8. keep `main` untouched.
