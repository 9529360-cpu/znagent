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

M10 canonical source promotion remains complete. `main` remains the canonical source/release branch; ordinary development remains on `dev/zn-agent`.

Latest fully verified implementation/test head for the current P3 slice:

```text
1e531658036ea2267191af0a2d4bb418e25a14eb
test: close WPF fixture process pipes
```

Status: **VERIFIED ON REAL WINDOWS X64 CI AND REAL INTERACTIVE WINDOWS E2E**.

Exact-head normal workflow evidence:

```text
run 32939109838
head 1e531658036ea2267191af0a2d4bb418e25a14eb

Electron / TypeScript / Windows   success
ZN Source Boundary / Windows      success
ZN Kernel / Python / Windows      success
```

The Kernel job checked out exact SHA `1e531658...`, used CPython 3.12.13, installed the formal `znagent` runtime from `runtime/python`, booted an isolated zero-model resident, compiled the resident core, and ran full discovery:

```text
Ran 474 tests in 593.000s
OK (skipped=5)
```

The four new read-only UIA capability regressions all passed, including guards that the Sense does not request dynamic Value text, dynamic Name, or control patterns.

Exact-head interactive evidence:

```text
run 32939109842
head 1e531658036ea2267191af0a2d4bb418e25a14eb
job Windows interactive computer-use E2E
```

The real input-desktop suite passed all three tests:

```text
test_real_resident_click_proves_visual_foreground_and_uia_focus ... ok
test_real_resident_types_unicode_into_exact_focused_native_edit ... ok
test_real_resident_identifies_non_native_wpf_text_capability ... ok
```

The WPF proof uses a real focused `System.Windows.Controls.TextBox`, not a mock. ZN observes it as a UIA Edit element with no native child HWND, identifies Value/Text capabilities and writable/read-only/password metadata, and still refuses it through the legacy native Win32 text Sense. Therefore this slice proves modern non-native text-control classification without widening mutation authority.

## 2. Resident ownership

The resident continues to own Self/life state, Situation/Thought/Will, durable WorkingState, Investigation, native Body actions and Senses, bounded cognition resources, memory/reconsolidation, verified experience/procedural tendencies, channels, and resident work/progress state.

External models do not own identity, target selection, execution authority, current-world truth or completion.

The active product runtime remains `FocusedTextEntryResidentRuntime`, extending the verified pointer/UIA resident. The previously verified `KeyboardTextBody` and native Win32 `NativeFocusedTextSense` remain unchanged by the current P3 slice.

## 3. Body / Senses / computer interaction

### 3.1 Existing typed text-entry competence remains narrow

ZN still has one real resident-owned typed text-entry competence for an already-focused, empty native Win32 `Edit` control. Its bounded Unicode Body movement, redacted durable ledger, digest-only native text Sense, non-replayable started marker, fresh target rechecks and independent postcondition remain intact.

Still true:

- no generic keyboard API;
- no Enter/Tab/Escape or modifier shortcuts;
- no selection/deletion/replacement lifecycle;
- non-empty different text is refused;
- password/read-only native controls are refused;
- completion requires fresh independent digest/target evidence.

The prior exact product-head interactive proof for this mutation competence remains valid, and the current three-test interactive run re-proved it alongside the new P3 read-only capability test.

### 3.2 UI Automation Sense now exposes bounded text-control capability metadata

Key product commit:

```text
3880f5e54fabf79ebc92e2f0db98b6ca3cee6ce3
feat: sense UI automation text capabilities
```

`NativeAutomationElementSense` remains a read-only, lazy, bounded Windows UIA Sense. Its cached element observation now additionally carries:

```text
is_password
is_value_pattern_available
is_text_pattern_available
value_is_read_only
```

These are capability/classification facts, not content and not mutation authority.

The UIA cache request may read the corresponding cached properties, but this Sense intentionally does **not** request:

- `Value.Value` / current dynamic text;
- dynamic `Name`;
- any control-pattern object;
- arbitrary UIA tree walking;
- event subscriptions;
- UIA mutation methods.

`ValueIsReadOnly` is only requested from the cached observation path when Value capability is actually available. Invalid or internally inconsistent injected observations fail closed.

AutomationId remains bounded and non-authoritative. Opaque RuntimeId remains action-cycle scoped evidence rather than durable semantic identity.

### 3.3 Real non-native WPF proof

Key test commits:

```text
7d409ec577d8a307b5cd9330873dcd434060e466
test: prove non-native text capability on Windows

97665ac03c388a7e5ec5896b3eff8c7094b7d31c
test: close UIA capability resident before temp cleanup

1e531658036ea2267191af0a2d4bb418e25a14eb
test: close WPF fixture process pipes
```

The real E2E launches a WPF `TextBox` on the interactive desktop, focuses it, and observes it using the resident-owned foreground and UI Automation Senses. It proves:

- UIA Edit control type;
- no native child HWND (`native_window_handle == 0`);
- enabled, keyboard-focusable and on-screen;
- not a password field;
- ValuePattern available;
- TextPattern available;
- Value is not read-only;
- no raw `value`, `text` or dynamic `name` field exists in the observation;
- `NativeFocusedTextSense` still refuses the non-native control.

The first E2E attempt exposed a fixture lifecycle defect: SQLite remained open while the temporary directory was being removed. That was fixed by closing the resident store inside the temporary-directory lifetime. A later successful run exposed an unclosed subprocess-pipe warning; the final fixture closes those streams too. Product behavior was not weakened to make the test pass.

### 3.4 What this slice does not establish

This slice does **not** yet expose the current text content or digest of a WPF/Chromium/WinUI/custom text field.

It therefore does not establish:

- browser/Chromium text-value sensing;
- generic modern-app text verification;
- typing into WPF/Chromium/WinUI/custom widgets;
- replacement/editing of existing text;
- UIA control-pattern mutation.

The new capability metadata is evidence that ZN can identify a promising modern text control and its safety-relevant capability shape. Mutation must remain closed until a concrete read-only current-state verifier exists.

## 4. Repository source boundary

The active tree remains ZN-only by contract and exact-head CI evidence.

Run `32939109838` completed `ZN Source Boundary / Windows` successfully at `1e531658...`. No ownership rule or scanner exemption was weakened. No reference-product runtime/control plane was restored.

## 5. Desktop / runtime / release

Run `32939109838` completed `Electron / TypeScript / Windows` successfully at `1e531658...`, including locked dependency installation, high-severity advisory rejection, typecheck, bundle, desktop ownership/runtime/update/handoff contracts, and release/runtime/artifact verifiers.

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

- current-value/digest sensing for non-native modern text controls;
- concrete browser/Chromium text-field evidence;
- any mutation lifecycle beyond already-focused empty native Win32 `Edit`;
- replacement/editing, navigation keys and shortcuts;
- broader real-application interactive coverage;
- mature procedural competence/growth benchmarks across repeated real tasks;
- M8 Windows install/upgrade/rollback/signing evidence;
- SM1+;
- non-blocking GitHub Actions JavaScript runtime deprecation warnings;
- a non-blocking Pillow `Image.getdata` deprecation warning in visual interactive code.

## 8. Next real targets

```text
1. preserve exact-head Windows x64 CI and the three-test real interactive lane
2. design a separate read-only focused modern-text state Sense that can transiently read only safe controls and export privacy-safe length/digest evidence
3. prove that read-only state path first on a concrete non-native control, then on Chromium/browser input if the actual provider supports it
4. keep password fields fail-closed and never persist raw dynamic text
5. do not widen keyboard/UIA mutation until current target/state can be independently verified
6. keep M8 and SM1+ explicitly partial/open
7. leave main untouched through ordinary development
```
