# ZN Agent Handoff

Updated: 2026-08-26

## Current goal

P3 remains active. ZN now has real read-only evidence that a non-native modern Windows text control can be identified by the resident as a text-capable UIA element without reading its dynamic content or widening mutation. The next goal is to add a separate privacy-safe read-only current-text state path for a concrete non-native control, then prove Chromium/browser support from actual provider evidence before any broader keyboard mutation.

Core principle:

> **ZN uses models. Models do not own ZN.**

## Branch / HEAD

- fixed development branch: `dev/zn-agent`
- canonical source/release branch: `main`
- fully verified implementation/test head for this slice: `1e531658036ea2267191af0a2d4bb418e25a14eb`
- status-ledger sync for this slice: `90261dca11c099bd5877f53b19268877bf292550`
- canonical `main` before this stage: `8234a835dea604783cea0bd9d28a40de654ec03d`
- PR #6 remained draft/open/unmerged during implementation, base `main`, head `dev/zn-agent`
- `main` was not modified
- no force push or history rewrite was used

A commit cannot contain its own SHA. Re-read the resulting `dev/zn-agent` HEAD after this HANDOFF commit and require the documentation-sync HEAD's exact-head normal Windows CI before calling the stage fully handed off.

## Completed in current stage

### 1. Restored repository truth and active caller chain

Before modification, the required architecture/status/source/self-maintenance/HANDOFF documents, dev/main refs, PR #6, recent commits, CI and active caller chain were re-read.

Real starting implementation baseline was:

```text
80df7692b1574d922c9471933da905f234ba78af
docs: hand off typed text entry slice
```

The active chain was confirmed as:

```text
provider_bridge.build_resident_runtime
-> FocusedTextEntryResidentRuntime
-> resident-owned NativeAutomationElementSense / NativeFocusedTextSense
-> typed mutation lifecycle
```

The existing mutation path still only supports an already-focused, empty native Win32 `Edit`.

### 2. Added read-only UIA text capability evidence

Product commit:

```text
3880f5e54fabf79ebc92e2f0db98b6ca3cee6ce3
feat: sense UI automation text capabilities
```

`AutomationElementObservation` now carries bounded cached-property evidence:

```text
is_password
is_value_pattern_available
is_text_pattern_available
value_is_read_only
```

The UIA Sense still does not request dynamic Value text, dynamic Name, any control-pattern object, arbitrary tree walking, event subscriptions or mutation methods. `ValueIsReadOnly` is only consumed when Value capability exists. Invalid inconsistent observations fail closed.

This change is Sense evidence only. It does not authorize keyboard input into WPF, Chromium, WinUI or custom controls.

### 3. Added privacy-boundary regressions

Commit:

```text
3f197d0f
test: guard UI automation text capability evidence
```

New core tests verify:

- Value/Text/password/read-only capability extraction;
- no read-only Value property access when ValuePattern is unavailable;
- inconsistent Value capability evidence is rejected;
- reader source contains no dynamic Value property request, dynamic Name request, or control-pattern cache request.

All four new tests passed in exact-head Windows Kernel CI.

### 4. Added a real non-native WPF TextBox proof

Initial E2E commit:

```text
7d409ec577d8a307b5cd9330873dcd434060e466
test: prove non-native text capability on Windows
```

The test launches a real WPF `System.Windows.Controls.TextBox` on the self-hosted Windows input desktop, focuses it, then uses the real resident to observe foreground and focused UIA element evidence.

It proves the target is:

- UIA Edit control type;
- `native_window_handle == 0`;
- enabled/focusable/on-screen;
- not password;
- ValuePattern capable;
- TextPattern capable;
- not Value-read-only;
- exposed without raw `value`, `text` or dynamic `name` fields.

It also explicitly proves `NativeFocusedTextSense` still refuses this non-native target. The mutation boundary therefore remained native-Edit-only.

### 5. Fixed E2E lifecycle defects exposed by real Windows

The first interactive run reached and passed the new capability assertions but failed during temporary-directory cleanup because the resident SQLite store was still open. Root fix:

```text
97665ac03c388a7e5ec5896b3eff8c7094b7d31c
test: close UIA capability resident before temp cleanup
```

The next run passed all three interactive tests but exposed unclosed fixture stdout/stderr pipes. Cleanup fix:

```text
1e531658036ea2267191af0a2d4bb418e25a14eb
test: close WPF fixture process pipes
```

No sleeps, retries or weakened product assertions were used to hide these failures.

### 6. Real interactive Windows E2E is green

Exact implementation/test head:

```text
run 32939109842
head 1e531658036ea2267191af0a2d4bb418e25a14eb
```

Real input-desktop evidence:

```text
test_real_resident_click_proves_visual_foreground_and_uia_focus ... ok
test_real_resident_types_unicode_into_exact_focused_native_edit ... ok
test_real_resident_identifies_non_native_wpf_text_capability ... ok
```

This re-proves the existing pointer/UIA and native Edit text mutation competence while adding a real non-native read-only classification proof.

### 7. Exact implementation/test-head normal Windows CI is green

Workflow:

```text
run 32939109838
head 1e531658036ea2267191af0a2d4bb418e25a14eb
```

Results observed:

```text
Electron / TypeScript / Windows   success
ZN Source Boundary / Windows      success
ZN Kernel / Python / Windows      success
```

Kernel evidence:

```text
checkout exact 1e531658036ea2267191af0a2d4bb418e25a14eb
CPython 3.12.13
formal runtime installed from runtime/python
zero-model isolated resident boot success
resident core compile success
Ran 474 tests in 593.000s
OK (skipped=5)
```

The final status-publisher job was still queued when the implementation ledger was written; re-read the run before final reporting.

### 8. Documentation synchronized

Status ledger commit:

```text
90261dca11c099bd5877f53b19268877bf292550
docs: record modern UIA text capability evidence
```

`ZN.md` was not changed because architecture direction did not change. `ZN-SOURCE-EXTRACTION.md` and `ZN-SELF-MAINTENANCE.md` were not changed because source-adoption and self-maintenance architecture did not change.

## Risks / boundaries

- Do not modify `main` through ordinary development.
- No force push/history rewrite.
- Do not weaken source-boundary scanning.
- Models do not own input authority, target selection or completion.
- `keyboard_text` is not generic keyboard authority.
- Actual mutation remains limited to already-focused empty native Win32 `Edit` controls.
- The new WPF proof is **classification only**, not current-text verification and not WPF write support.
- Do not call this browser support; Chromium/browser has not been proven.
- No dynamic UIA Value text or Name is currently exposed by `NativeAutomationElementSense`.
- Password fields must remain fail-closed.
- RuntimeId remains action-cycle scoped; AutomationId remains non-authoritative.
- M8 install/upgrade/rollback/signing remains partial.
- SM1+ remains open.
- GitHub Actions JavaScript runtime and Pillow `Image.getdata` warnings remain non-blocking tooling debt.

## Task queue

### P0 - exact-head normal Windows CI
Status: **GREEN FOR IMPLEMENTATION/TEST HEAD**

Run `32939109838` at `1e531658...`: Electron, Source Boundary and Kernel succeeded. Kernel **474 tests / 5 skipped / OK**. Re-read final status publisher.

### P1 - resident typed native Edit text entry
Status: **VERIFIED NARROW SLICE**

Existing bounded Body, digest Sense, target authority, non-replay lifecycle and postcondition remain intact.

### P2 - real interactive computer-use proof
Status: **VERIFIED POINTER + NATIVE TEXT + WPF READ-ONLY CAPABILITY**

Run `32939109842` at `1e531658...` passed all three real Windows input-desktop E2Es.

### P3 - modern application/browser text state
Status: **IN PROGRESS / READ-ONLY FIRST**

Next concrete gap: safely obtain current text state for a focused non-native text control without persisting raw content. Prefer transient read plus exported length/SHA-256, guarded by password/read-only/provider capability evidence. Then prove Chromium/browser behavior separately from WPF.

### P4 - broader keyboard/editing primitives
Status: **PENDING**

Selection/replacement, navigation keys, shortcuts and broader widgets need separate typed authority and independent postconditions.

### P5 - M8 Windows continuity / rollback / signing
Status: **PENDING / PARTIAL**

### P6 - SM1+ self-maintenance
Status: **PENDING**

## Related files

```text
runtime/python/zn_agent/core/automation_element_sense.py
runtime/python/zn_agent/core/focused_text_sense.py
runtime/python/zn_agent/core/focused_text_entry_resident.py
runtime/python/zn_agent/core/provider_bridge.py
tests/zn_agent/core/test_automation_text_capability_sense.py
tests/zn_agent/e2e/test_windows_interactive_uia_text_capability.py
tests/zn_agent/e2e/test_windows_interactive_pointer_uia.py
tests/zn_agent/e2e/test_windows_interactive_text_entry.py
.github/workflows/zn-windows-interactive-e2e.yml
docs/ZN-IMPLEMENTATION-STATUS.md
.agent/HANDOFF.md
```

## Blockers

No current product or Windows CI blocker for this read-only WPF capability slice.

## Next real target

1. re-read final `dev/zn-agent` HEAD, `main`, PR #6 and exact-head CI after this HANDOFF commit;
2. preserve exact implementation-head interactive evidence `32939109842`;
3. trace the concrete UIA provider/caller needed for transient current-value sensing on a focused non-native text control;
4. design privacy-safe evidence: reject password fields, bound content, export only length/digest, do not persist raw text;
5. prove WPF current-state sensing first, then separately prove Chromium/browser provider behavior;
6. only after that consider widening mutation, with fresh target authority, non-replay semantics and independent postcondition;
7. keep M8/SM1+ open and `main` untouched.
