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

## 1. Current checkpoint - 2026-08-26

M10 canonical source promotion remains complete. `main` is canonical source/release; ordinary development remains on `dev/zn-agent`.

Latest fully verified implementation/test head:

```text
ecf258122cda0f96c6bbdca09834242e72a6daed
test: assert text verification before terminal cleanup
```

The product implementation that changed real Windows keyboard behavior is:

```text
c0e3dcdf3f9dbc15cfe16b20c6bae9d53a047cf1
fix: use full Win32 INPUT layout for keyboard text
```

Status: **VERIFIED ON REAL WINDOWS X64 CI AND REAL INTERACTIVE WINDOWS E2E**.

Exact-head normal workflow evidence for `ecf25812...`:

```text
run 32914801495
head ecf258122cda0f96c6bbdca09834242e72a6daed

ZN Source Boundary / Windows       success
ZN Kernel / Python / Windows       success
Electron / TypeScript / Windows   success
Publish Windows CI statuses       success
```

The Kernel job checked out exact SHA `ecf25812...`, used CPython 3.12.13, installed the formal `znagent` runtime from `runtime/python`, booted an isolated zero-model resident, compiled the resident core and ran full discovery:

```text
Ran 470 tests in 609.436s
OK (skipped=5)
```

The real Windows Kernel log includes the new keyboard/text regressions as `ok`, including:

```text
test_empty_exact_target_types_once_then_verifies_fresh_digest ... ok
test_already_matching_text_completes_without_input ... ok
test_nonempty_different_text_fails_before_input ... ok
test_started_marker_refuses_blind_replay ... ok
test_partial_send_returns_to_investigation_without_retry ... ok
test_uia_and_native_text_hwnd_mismatch_fails_before_input ... ok
test_unknown_scope_authority_fails_closed_before_sensing_or_input ... ok
test_digest_evidence_never_exposes_dynamic_text ... ok
test_password_read_only_and_non_edit_controls_fail_closed ... ok
test_body_ledger_persists_only_redacted_keyboard_metadata ... ok
test_partial_send_is_failure_and_never_claims_completion ... ok
```

Exact product-implementation interactive evidence:

```text
run 32913591334
head c0e3dcdf3f9dbc15cfe16b20c6bae9d53a047cf1
job Windows interactive computer-use E2E
conclusion success

test_real_resident_click_proves_visual_foreground_and_uia_focus ... ok
test_real_resident_types_unicode_into_exact_focused_native_edit ... ok
Ran 2 tests in 6.924s
OK
```

The later `c46c013...` / `ecf25812...` commits change only core tests, so the path-filtered interactive workflow correctly did not rerun for them. The actual product implementation SHA `c0e3dcdf...` is the exact SHA that passed the real interactive input-desktop proof.

## 2. Resident ownership

The resident continues to own persistent Self/life state, Situation/Thought/Will, durable WorkingState, Investigation, native Body actions and Senses, bounded cognition resources, memory/reconsolidation, verified experience/procedural tendencies, channels, and resident work/progress state.

External models do not own identity, target selection, execution authority, current-world truth or completion.

The active product runtime now constructs `FocusedTextEntryResidentRuntime`, which extends the already verified pointer/UIA resident rather than replacing its architecture. It installs `KeyboardTextBody` as the resident Body and owns a `NativeFocusedTextSense` alongside the existing foreground, native focused-control and read-only UI Automation Senses.

Zero-model isolated boot passed at exact head `ecf25812...`; the new input competence does not make an external model a runtime prerequisite.

## 3. Body / Senses / computer interaction

### 3.1 Bounded Unicode keyboard Body movement

`KeyboardTextBody` adds one narrow Body action:

```text
keyboard_text
```

Current authority is intentionally much narrower than a generic keyboard API:

- Windows only;
- explicit non-empty string only;
- maximum 512 UTF-16 code units;
- plain text characters only;
- no Enter, Tab, Escape, control characters, shortcuts or modifier chords;
- no selection, deletion or replacement primitive;
- one Unicode `SendInput` down/up pair per UTF-16 code unit;
- partial Windows input acceptance is a failure, never completion evidence.

The Body result records only lengths, event counts and SHA-256. Its durable native-body ledger explicitly redacts the action text and persists only bounded metadata/digest rather than duplicating dynamic typed text into the action ledger.

### 3.2 Focused native text Sense keeps raw dynamic text private

`NativeFocusedTextSense` is a dedicated read-only native Win32 text-state Sense. It does not widen the existing UI Automation Sense and does not add dynamic UIA `Name` or Value text.

The first slice is deliberately limited to the exact focused native Win32 `Edit` child control. It requires:

- focused child of the current foreground GUI thread;
- same foreground process;
- native class `Edit`;
- positive control id;
- enabled and visible;
- not password style;
- not read-only style;
- bounded text length.

The native text is read transiently through bounded `WM_GETTEXTLENGTH` / `WM_GETTEXT` with `SendMessageTimeoutW`. The observation exported to the resident contains only text length + SHA-256 plus target identity; it contains no raw text field.

### 3.3 Typed text-entry lifecycle

The supported completion contract is intentionally specific:

```text
event.kind = ui_state_transition
body_action.kind = keyboard_text
expected_outcome.kind = focused_text_equals_action_text
completion_scope.kind = focused_native_edit_text
```

The scope requires exact foreground process/title, native `Edit` class/control id, UIA control type and exact UIA class name. Unknown fields fail closed. AutomationId remains non-authoritative.

The resident requires this sequence:

```text
fresh foreground evidence
-> fresh native focused-control evidence
-> fresh focused UIA RuntimeId/type/class evidence
-> fresh native text length/digest evidence
-> exact HWND agreement between UIA and native text Sense
-> typed completion/precondition admission
-> if already equal: complete with zero input
-> if non-empty and different: refuse mutation
-> if empty: persist preparation
-> persist non-replayable started marker
-> final fresh target + empty-text recheck
-> one bounded Unicode Body input
-> fresh target + text digest re-observation
-> complete only if exact requested digest/length is independently proven
```

An interrupted `started` marker never causes blind keyboard replay. Partial input or failed postcondition returns to Investigation rather than repeating input.

### 3.4 Real Windows failure exposed and fixed a Win64 ABI bug

The first real text-entry interactive run (`32913418213`) reached the new E2E but the native Edit remained empty. The failure was not hidden with sleeps or retries.

Root cause was the first ctypes definition of Win32 `INPUT`: its union contained only `KEYBDINPUT`, making `sizeof(INPUT)` too small on Win64. `SendInput` therefore rejected the supplied `cbSize`.

Commit `c0e3dcdf...` defines the full Win32 union, including `MOUSEINPUT`, `KEYBDINPUT` and `HARDWAREINPUT`, so the structure has the correct Win64 layout. Exact-head interactive run `32913591334` then passed both the pre-existing real pointer/UIA E2E and the new Unicode text-entry E2E.

The real text test creates a native Win32 `Edit`, obtains target identity from ZN's own Senses, executes with `model_policy=never`, observes the real control containing `ZN native 世界`, and requires fresh resident-owned digest/UIA/native-focus proof before success.

### 3.5 Explicit non-goals of this slice

This does **not** establish generic keyboard authority.

Still unsupported:

- typing into arbitrary browser/Chromium/WinUI/custom text widgets;
- replacing arbitrary existing text;
- password fields;
- read-only fields;
- Enter/Tab/navigation keys;
- Ctrl/Alt/Win shortcuts;
- right-click/double-click/drag;
- arbitrary UIA tree search or control-pattern mutation.

These require their own concrete typed caller and independent verification design.

## 4. Repository source boundary

The active tree remains ZN-only by contract and exact-head CI evidence.

Run `32914801495` completed `ZN Source Boundary / Windows` successfully at `ecf25812...`. No ownership rule or scanner exemption was weakened. No reference-product runtime/control plane was restored.

## 5. Desktop / runtime / release

Run `32914801495` completed `Electron / TypeScript / Windows` successfully at `ecf25812...`, including locked dependency installation, high-severity advisory rejection, typecheck, bundle, desktop ownership/runtime/update/handoff contract tests, and release-channel/runtime-staging/artifact-verifier tests.

M8 remains **PARTIAL**. Still open for Windows x64:

1. clean Windows install/login evidence;
2. installed Windows N->N+1 continuity evidence;
3. rollback validation across a real Windows version transition;
4. applicable secure Windows signing evidence.

## 6. Self-maintenance

SM0 remains complete. SM1+ remains open. No self-maintenance architecture changed in this slice.

## 7. Current known debts / boundaries

There is no current Windows CI infrastructure blocker.

Still open:

- text-entry/application-state support beyond native Win32 `Edit`;
- browser/Chromium/modern application text-field evidence from a concrete ZN-owned caller;
- any replacement/editing lifecycle for non-empty controls;
- keyboard navigation/shortcuts and other input primitives until matching typed authority and independent verification exist;
- broader interactive E2E coverage across real applications and environments;
- mature procedural competence/growth benchmarks across repeated real tasks;
- M8 Windows install/upgrade/rollback/signing evidence;
- SM1+;
- non-blocking GitHub Actions JavaScript runtime deprecation warnings;
- a non-blocking Pillow `Image.getdata` deprecation warning in the visual interactive fixture.

## 8. Next real targets

```text
1. keep exact-head Windows x64 CI and the two-test real interactive lane green
2. preserve the native Edit text-entry privacy, non-replay and fresh-verification boundaries
3. investigate the next concrete read-only application/browser text-field state needed to support mainstream modern apps
4. only widen text mutation after ZN can independently identify and verify that target/state
5. do not turn keyboard or UI Automation into generic model-owned tool/control planes
6. keep M8 and SM1+ explicitly partial/open
7. leave main untouched through ordinary development
```
