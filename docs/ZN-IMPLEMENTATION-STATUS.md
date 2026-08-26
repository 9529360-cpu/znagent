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

M10 canonical source promotion remains complete. Ordinary development remains on `dev/zn-agent`; `main` was not modified in this stage.

Latest fully verified implementation/test head for the current P3 slice:

```text
1a1e4959ec07ac5d67e39033611b9931e705e80e
test: guard modern text Sense ownership
```

Status: **VERIFIED ON WINDOWS X64 CI AND REAL INTERACTIVE WINDOWS E2E**.

Exact-head normal workflow:

```text
run 32942313022
head 1a1e4959ec07ac5d67e39033611b9931e705e80e

Electron / TypeScript / Windows   success
ZN Source Boundary / Windows      success
ZN Kernel / Python / Windows      success
Publish Windows CI statuses       success
```

Kernel evidence:

```text
CPython 3.12.13
formal runtime installed from runtime/python
zero-model isolated resident boot success
resident core compile success
Ran 482 tests in 594.172s
OK (skipped=5)
```

Relevant real interactive workflow:

```text
run 32942284572
head ba25ffa9846eeb3c79f41f66572f9c408d02304b
job Windows interactive computer-use E2E
Ran 3 tests in 8.008s
OK
```

That head contains all product and E2E changes for this slice. The later exact normal-CI head only adds the resident-ownership unit test.

## 2. Resident ownership

The resident continues to own Self/life state, Situation/Thought/Will, durable WorkingState, Investigation, native Body actions and Senses, bounded cognition resources, memory/reconsolidation, verified experience/procedural tendencies, channels, and resident work/progress state.

External models do not own identity, target selection, execution authority, current-world truth or completion.

The active product runtime is now `FocusedModernTextResidentRuntime`, which extends the prior `FocusedTextEntryResidentRuntime` and additionally owns `NativeFocusedAutomationTextSense` as a read-only Sense. Existing `KeyboardTextBody`, native Win32 `NativeFocusedTextSense`, pointer/UIA Senses and mutation lifecycle remain present.

The new modern text Sense is **not** consulted as mutation authority by the existing `keyboard_text` lifecycle.

## 3. Body / Senses / computer interaction

### 3.1 Existing mutation remains narrow

ZN still mutates text only in an already-focused, empty native Win32 `Edit` through the previously verified typed lifecycle. It still requires fresh foreground/native-focus/UIA/native-text evidence, bounded Unicode input, a non-replayable started marker and an independent digest postcondition.

Still not available:

- generic keyboard input;
- WPF/Chromium/WinUI/custom-widget typing;
- non-empty replacement/editing;
- navigation keys or shortcuts;
- UIA `SetValue` or other control-pattern mutation.

### 3.2 Structural UIA capability Sense remains cached/read-only

`NativeAutomationElementSense` still exposes bounded cached structural evidence plus:

```text
is_password
is_value_pattern_available
is_text_pattern_available
value_is_read_only
```

It still does not request dynamic Value text, dynamic Name, control-pattern objects, event subscriptions or arbitrary tree walking.

### 3.3 New focused modern-text current-state Sense

Key commits:

```text
f5b68f899441a0a83e6dee73c25bdb15da9aac72
feat: add focused UIA text digest sense

bedcc29aa6009b58dcb6d4f40c5d4014c681aff3
feat: make UIA text state resident-owned

914ae49a291b786da156c306ef31e316a4444bf9
feat: activate modern text state resident
```

`NativeFocusedAutomationTextSense` is a separate focused-only read path. Before any dynamic Value read it requires cached evidence that the exact focused element is:

- UIA Edit control type;
- enabled, keyboard-focusable, focused and on-screen;
- non-password;
- ValuePattern-capable;
- writable rather than read-only;
- backed by a usable RuntimeId and process identity.

Only after those gates pass does the Sense transiently read the current UIA Value. Raw content is bounded to 4096 characters, reduced immediately to `text_length` plus SHA-256, and never appears in the observation. A second focused-element capture must still identify the same RuntimeId/process and satisfy the safety gates before evidence is returned.

The reader has no `Name` read, `AddPattern`, `SetValue`, `FindFirst`/`FindAll`, event subscription or mutation surface.

Provider-side UIA password protection remains a final fail-closed layer for any race between the pre-read password check and the Value read; resident-side pre/post gates do not treat a successful read as mutation authority.

### 3.4 Privacy and race regressions

Commit:

```text
846f1ee459da4b9c7ee095cace9c535316bc8dad
test: guard focused UIA text digest privacy
```

The exact-head Kernel run proves regressions for:

- export of length/digest only, never raw `text`/`value`;
- password refusal before dynamic Value access;
- read-only refusal before dynamic Value access;
- RuntimeId drift rejection after the read;
- oversized content rejection without echoing content in errors;
- invalid digest/password observations failing closed;
- absence of Name/tree/mutation APIs from the reader.

Resident ownership is separately guarded by:

```text
1a1e4959ec07ac5d67e39033611b9931e705e80e
test: guard modern text Sense ownership
```

### 3.5 Real WPF current-state proof

Commit:

```text
ba25ffa9846eeb3c79f41f66572f9c408d02304b
test: prove WPF current text digest evidence
```

The real interactive E2E launches a focused `System.Windows.Controls.TextBox` containing a known marker and proves:

- the resident observes it as a non-native UIA Edit (`native_window_handle == 0`);
- structural UIA capability evidence and the new text-state Sense identify the same RuntimeId/process/AutomationId;
- the target is non-password, ValuePattern-capable and writable;
- returned `text_length` equals the real WPF text length;
- returned SHA-256 equals the real WPF text digest;
- no raw `text` or `value` field is exported;
- legacy `NativeFocusedTextSense` still refuses the WPF target;
- existing pointer/UIA and native Win32 text-entry E2Es still pass in the same run.

Therefore this slice establishes privacy-safe read-only current-state evidence for one concrete non-native modern Windows text control without widening mutation.

### 3.6 What this slice does not establish

This is **not** Chromium/browser proof. It also does not establish WinUI/custom-provider support or any modern-widget mutation lifecycle.

Chromium must be investigated from the actual Windows runner/provider behavior rather than inferred from WPF or UIA documentation.

## 4. Repository source boundary / desktop / release

Run `32942313022` passed Source Boundary and Electron at exact head `1a1e4959...`. No scanner exemption, product ownership rule, desktop control plane, runtime staging, update or release contract was weakened.

M8 remains **PARTIAL**. Still open for Windows x64:

1. clean Windows install/login evidence;
2. installed Windows N->N+1 continuity evidence;
3. rollback validation across a real Windows version transition;
4. applicable secure Windows signing evidence.

## 5. Self-maintenance

SM0 remains complete. SM1+ remains open. No self-maintenance architecture changed in this slice.

## 6. Current known debts / boundaries

- Chromium/browser current-text provider evidence is still unproven;
- mutation remains native-empty-Edit-only;
- replacement/editing, navigation keys and shortcuts remain open;
- broader real-application interactive coverage remains open;
- M8 Windows install/upgrade/rollback/signing remains partial;
- SM1+ remains open;
- GitHub Actions JavaScript runtime deprecation warnings remain non-blocking tooling debt;
- Pillow `Image.getdata` deprecation warning remains non-blocking visual-code debt.

## 7. Next real targets

```text
1. preserve the verified WPF read-only digest path and exact-head normal CI
2. investigate actual Chromium/browser availability and UIA provider behavior on the real Windows interactive runner
3. add read-only browser text-field evidence only if the real provider exposes a bounded, password-safe path
4. do not infer browser support from WPF and do not widen mutation while browser/current-state authority is unproven
5. after browser evidence, decide whether one typed modern-edit mutation lifecycle is justified and independently verifiable
6. keep M8 and SM1+ explicitly partial/open
7. leave main untouched through ordinary development
```
