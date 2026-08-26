# ZN Agent Handoff

Updated: 2026-08-26

## Current goal

ZN now has one real, resident-owned typed text-entry competence for an already-focused, empty native Win32 `Edit`. The next goal is not generic keyboard expansion. It is to investigate the next concrete read-only application/browser text-field state needed for mainstream modern apps, then widen mutation only when ZN can independently identify the target and verify the resulting state.

Core principle:

> **ZN uses models. Models do not own ZN.**

## Branch / HEAD

- fixed development branch: `dev/zn-agent`
- canonical source/release branch: `main`
- latest fully verified implementation/test head: `ecf258122cda0f96c6bbdca09834242e72a6daed`
- exact product implementation with the Win64 keyboard fix: `c0e3dcdf3f9dbc15cfe16b20c6bae9d53a047cf1`
- status-ledger sync immediately before this HANDOFF sync: `93809b76a3af00d29958036f74a9fa0ccc95274d`
- canonical `main` at the start of this stage: `8234a835dea604783cea0bd9d28a40de654ec03d`
- PR #6 was draft/open/unmerged at the start of this stage, base `main`, head `dev/zn-agent`
- `main` was not modified in this stage
- no force push or history rewrite was used

A Git commit cannot truthfully contain its own SHA. The final report must re-read the resulting `dev/zn-agent` HEAD after this HANDOFF commit, re-read `main` and PR #6, and require the final documentation-sync HEAD's exact-head normal Windows CI to be green.

## Completed in current stage

### 1. Restored repository truth before changing capability behavior

The required architecture/status/source/self-maintenance/HANDOFF documents, dev/main refs, PR #6, latest CI, recent commits and the active pointer/UIA/body caller chain were re-read before implementation.

Real starting HEAD was:

```text
baca8fe4c5850703564ebed54324a4e64605a6f6
docs: hand off typed UI automation slice
```

Its exact-head Windows CI was green. `main` remained `8234a835...`.

### 2. Added one bounded Unicode keyboard Body movement

Key commit:

```text
557ae8f5cdb4aeb1fb7e88959bb7f9468bb02983
feat: add bounded Unicode keyboard body
```

`KeyboardTextBody(NativeBody)` adds only `keyboard_text` and delegates all existing Body actions unchanged.

Current limits:

- Windows only;
- explicit non-empty string;
- max 512 UTF-16 code units;
- no control characters;
- no Enter/Tab/Escape;
- no modifiers/shortcuts;
- no selection/deletion/replacement;
- Unicode `SendInput` only;
- partial `SendInput` is failure and must not be blindly replayed.

Later commits:

```text
3886697d25e40d42de2ce49a5213d0faa727e17f
fix: redact keyboard text from body ledger

826ae9eaf0227166625770f0c8b464ca05c86fe3
test: prove keyboard ledger redacts text
```

The native Body ledger does not duplicate typed text. It stores bounded length/unit/digest metadata with `redacted=true`.

### 3. Added a read-only focused native text digest Sense

Commit:

```text
536d82e97c9126f341dfe7b7418c4b13f5cb7531
feat: add focused native text digest sense
```

`NativeFocusedTextSense` is separate from UI Automation and preserves the earlier rule that the narrow UIA Sense does not expose dynamic UI text.

It is deliberately native-Edit-only:

- exact focused child of foreground GUI thread;
- same foreground process;
- native class `Edit`;
- positive control id;
- enabled + visible;
- password controls refused;
- read-only controls refused;
- bounded transient `WM_GETTEXTLENGTH` / `WM_GETTEXT` through `SendMessageTimeoutW`;
- exported observation contains text length + SHA-256, never raw text.

Regression commit:

```text
24f7cf256152d245c2c7f75a06b847360eca34eb
test: guard focused text digest privacy boundary
```

### 4. Added the typed, non-replayable resident lifecycle

Commit:

```text
8d7431e97a22825a47c6c752c948af6fb15dd9fb
feat: add typed focused text entry lifecycle
```

`FocusedTextEntryResidentRuntime` extends the existing typed pointer/UIA runtime. `provider_bridge.build_resident_runtime()` now constructs this active runtime via:

```text
a75389e674f3c432dfc42f4b4a7abd63eeb3d16d
feat: activate typed focused text entry resident
```

The real action contract is intentionally narrow:

```text
ui_state_transition
-> body_action.kind=keyboard_text
-> expected_outcome.kind=focused_text_equals_action_text
-> completion_scope.kind=focused_native_edit_text
```

Fresh authority requires exact foreground process/title, native Edit class/control id, UIA control type/class, focused UIA RuntimeId and agreement between UIA/native text HWND.

Lifecycle:

```text
fresh target + text digest
-> already desired: complete without input
-> non-empty different: refuse mutation
-> empty: persist preparation
-> persist started marker
-> final fresh target/empty recheck
-> one Unicode Body input
-> fresh target/text digest verification
-> complete only from independent current-world proof
```

If the resident finds a prior `started` marker after interruption, it refuses blind replay. Partial input or failed postcondition returns to Investigation.

Core regression commits include:

```text
2412b4363292352da316bea35b72183588fe5639
test: guard typed focused text entry lifecycle

c46c013d21a41a8e9bfbd5eda3004bd239c21b61
test: close keyboard ledger read connection on Windows

ecf258122cda0f96c6bbdca09834242e72a6daed
test: assert text verification before terminal cleanup
```

The last two commits fix test-lifecycle defects found by full Windows CI; they do not change product input behavior.

### 5. Added and passed real interactive Windows text-entry E2E

Commit:

```text
780782a3999f0a6f2646fe177291dc8813cdd1b0
test: prove typed text entry on real Windows Edit
```

The interactive workflow now discovers both repository-defined Windows computer-use E2Es:

```text
c8d3e128fd70dd1f752e42118d84d65f3da10c6b
ci: run all Windows interactive computer use E2Es
```

The first real text-entry run exposed a genuine implementation bug rather than passing via mocks:

```text
run 32913418213
head c8d3e128...
new text-entry E2E failed because the real Edit stayed empty
```

Root cause: the first ctypes Win32 `INPUT` union contained only `KEYBDINPUT`, so `sizeof(INPUT)` was too small on Win64 and Windows rejected `SendInput`'s `cbSize`.

Root fix:

```text
c0e3dcdf3f9dbc15cfe16b20c6bae9d53a047cf1
fix: use full Win32 INPUT layout for keyboard text
```

The full union now includes `MOUSEINPUT`, `KEYBDINPUT` and `HARDWAREINPUT`.

Exact product-head interactive evidence:

```text
run 32913591334
head c0e3dcdf3f9dbc15cfe16b20c6bae9d53a047cf1
Windows interactive computer-use E2E  success
```

Real job evidence:

```text
formal runtime on self-hosted Windows x64 input desktop
CPython 3.12.13
test_real_resident_click_proves_visual_foreground_and_uia_focus ... ok
test_real_resident_types_unicode_into_exact_focused_native_edit ... ok
Ran 2 tests in 6.924s
OK
```

The text test creates a real native Win32 Edit, targets it using resident-owned Senses, executes with `model_policy=never`, observes the OS control containing `ZN native 世界`, and requires fresh digest/UIA/native-focus proof before the resident returns success.

The later `c46c013...` / `ecf25812...` commits are core-test-only and therefore do not retrigger the path-filtered interactive workflow. The real product implementation SHA itself is the SHA that passed the interactive proof.

### 6. Exact implementation/test-head normal Windows CI is green

Workflow:

```text
run 32914801495
head ecf258122cda0f96c6bbdca09834242e72a6daed
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
checkout exact ecf258122cda0f96c6bbdca09834242e72a6daed
CPython 3.12.13
formal runtime installed from runtime/python
zero-model isolated resident boot success
resident core compile success
Ran 470 tests in 609.436s
OK (skipped=5)
```

The log explicitly shows every new focused-text lifecycle/Sense/Body regression as `ok`, including the two tests that failed in the prior run before their test-only fixes.

Desktop locked install, high-severity audit, typecheck, bundle, desktop ownership/runtime/update/handoff contracts and release/runtime/artifact verifiers all passed. Source Boundary passed without scanner exemptions.

### 7. Documentation synchronized

Status ledger commit immediately before this HANDOFF sync:

```text
93809b76a3af00d29958036f74a9fa0ccc95274d
docs: record typed text entry evidence
```

`ZN.md` was not changed because the existing architecture already requires resident-owned Body/Senses/authority/verification and treats models as resources. `ZN-SOURCE-EXTRACTION.md` and `ZN-SELF-MAINTENANCE.md` were not changed because source-adoption and self-maintenance architecture did not change.

## Risks / boundaries

- Do not modify `main` through ordinary development.
- No force push/history rewrite.
- Do not weaken source-boundary scanning.
- Models do not own input authority, target selection or completion.
- `keyboard_text` is not generic keyboard authority.
- Only already-focused native Win32 Edit controls are supported by this slice.
- Non-empty different text is deliberately refused; there is no replace/select/delete lifecycle yet.
- Password and read-only controls are refused.
- Control/navigation keys and shortcuts are unsupported.
- The existing UI Automation Sense remains read-only; no ValuePattern/control-pattern mutation was added.
- Dynamic UIA Name/text remains excluded.
- RuntimeId remains action-cycle scoped; AutomationId remains non-authoritative.
- Right-click/double-click/drag remain unsupported.
- Broader browser/Chromium/WinUI/custom-control text entry remains open.
- M8 install/upgrade/rollback/signing remains partial.
- SM1+ remains open.
- GitHub Actions JavaScript runtime and Pillow `Image.getdata` deprecation warnings remain non-blocking tooling debt.

## Task queue

### P0 - exact-head normal Windows CI
Status: **VERIFIED / GREEN FOR IMPLEMENTATION-TEST HEAD**

Run `32914801495` at `ecf25812...`: all four normal Windows jobs succeeded; Kernel **470 tests / 5 skipped / OK**.

### P1 - resident typed native Edit text entry
Status: **VERIFIED NARROW SLICE**

Body, read-only digest Sense, target authority, non-replay lifecycle and independent postcondition are implemented and covered by full CI.

### P2 - real interactive computer-use proof
Status: **VERIFIED POINTER + TEXT ENTRY**

Run `32913591334` at product implementation `c0e3dcdf...` passed two real Windows input-desktop E2Es, including Unicode text into a native Edit with zero model calls.

### P3 - modern application/browser text state
Status: **NEXT / INVESTIGATE BEFORE MUTATION**

Find the concrete active caller and read-only evidence required to identify and verify text fields outside native Win32 Edit. Do not widen keyboard or UIA mutation first.

### P4 - broader keyboard/editing primitives
Status: **PENDING**

Selection/replacement, navigation keys, shortcuts and broader widgets need separate typed authority and postcondition designs.

### P5 - M8 Windows continuity / rollback / signing
Status: **PENDING / PARTIAL**

### P6 - SM1+ self-maintenance
Status: **PENDING**

## Related files

```text
runtime/python/zn_agent/core/keyboard_text_body.py
runtime/python/zn_agent/core/focused_text_sense.py
runtime/python/zn_agent/core/focused_text_entry_resident.py
runtime/python/zn_agent/core/provider_bridge.py
tests/zn_agent/core/test_keyboard_text_body.py
tests/zn_agent/core/test_focused_text_sense.py
tests/zn_agent/core/test_focused_text_entry.py
tests/zn_agent/e2e/test_windows_interactive_text_entry.py
.github/workflows/zn-windows-interactive-e2e.yml
docs/ZN-IMPLEMENTATION-STATUS.md
.agent/HANDOFF.md
```

## Blockers

No current product or Windows CI blocker for this completed native-Edit text-entry slice.

## Next real target

1. re-read the final `dev/zn-agent` HEAD after this HANDOFF commit and require its exact-head normal Windows CI to remain green;
2. preserve the `c0e3dcdf...` real interactive pointer + text-entry evidence;
3. inspect existing browser/web/application-state code and active callers for the next concrete read-only modern text-field identity/state gap;
4. prefer a Sense/evidence improvement before adding generic keyboard primitives;
5. if mutation widens, require fresh target authority, non-replay semantics and independent postcondition as in this slice;
6. keep M8 and SM1+ explicitly open;
7. keep `main` untouched.
