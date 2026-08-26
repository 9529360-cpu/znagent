# ZN Agent Handoff

Updated: 2026-08-26

## Current goal

P3 remains active. ZN now has resident-owned, privacy-safe read-only current-text digest evidence for a real focused non-native WPF TextBox. The next concrete target is to investigate actual Chromium/browser availability and UIA provider behavior on the real interactive Windows runner, then prove browser text-field state only from real evidence. Do not widen mutation from the WPF result alone.

Core principle:

> **ZN uses models. Models do not own ZN.**

## Branch / HEAD

- fixed development branch: `dev/zn-agent`
- canonical source/release branch: `main`
- verified implementation/test head: `1a1e4959ec07ac5d67e39033611b9931e705e80e`
- current status-ledger commit: `c39a91bd7ec4a525aae3e24cb032fc11635d1bca`
- canonical `main` during this stage: `8234a835dea604783cea0bd9d28a40de654ec03d`
- PR #6 remained draft/open/unmerged, base `main`, head `dev/zn-agent`
- `main` was not modified
- no force push or history rewrite was used

A HANDOFF commit cannot contain its own resulting SHA. Re-read the resulting `dev/zn-agent` HEAD and require its docs-only exact-head normal Windows CI before calling the handoff fully synchronized.

## Completed in current stage

### 1. Restored repository truth

Required architecture/status/source/self-maintenance/HANDOFF documents, dev/main refs, PR #6, recent commits, CI and the real caller chain were re-read before modification.

Starting head was `5c22f283b3534b508cefc72f2c3b0a625ee869d3`. Its docs-only normal CI run `32940267608` was fully green before new P3 work began.

The active chain was confirmed as:

```text
provider_bridge.build_resident_runtime
-> FocusedTextEntryResidentRuntime
-> resident-owned UIA/native Senses
-> existing native Edit text mutation lifecycle
```

### 2. Added a separate privacy-safe modern text-state Sense

Product commit:

```text
f5b68f899441a0a83e6dee73c25bdb15da9aac72
feat: add focused UIA text digest sense
```

New `NativeFocusedAutomationTextSense`:

- only targets the focused UIA Edit;
- pre-gates on enabled/focusable/focused/on-screen/non-password/ValuePattern/writable identity evidence;
- transiently reads current UIA Value only after those gates;
- bounds raw content to 4096 characters;
- exports only `text_length` + SHA-256 plus bounded target identity/capability evidence;
- rechecks the focused RuntimeId/process and safety evidence after the read;
- never exports raw text/value;
- has no mutation method, Name read, tree walk, control-pattern request or event subscription.

### 3. Added privacy/race regressions

Commit:

```text
846f1ee459da4b9c7ee095cace9c535316bc8dad
test: guard focused UIA text digest privacy
```

Tests cover safe digest export, password/read-only pre-read refusal, focus RuntimeId drift, oversized-content privacy, invalid digest/password validation, and reader source guards against Name/tree/mutation APIs.

### 4. Made the Sense resident-owned without widening mutation

Commits:

```text
bedcc29aa6009b58dcb6d4f40c5d4014c681aff3
feat: make UIA text state resident-owned

914ae49a291b786da156c306ef31e316a4444bf9
feat: activate modern text state resident

1a1e4959ec07ac5d67e39033611b9931e705e80e
test: guard modern text Sense ownership
```

`provider_bridge.build_resident_runtime()` now constructs `FocusedModernTextResidentRuntime`, which extends the previous text-entry resident and owns `automation_text_state`.

The existing `focused_text`, `KeyboardTextBody` and native text mutation lifecycle remain present. The new Sense is not consulted as execution authority by `keyboard_text`.

The implementation diff from the prior stage base contains exactly six commits. `provider_bridge.py` changed by only 3 additions/3 deletions; there was no unintended broad rewrite.

### 5. Real WPF current-text digest proof is green

E2E commit:

```text
ba25ffa9846eeb3c79f41f66572f9c408d02304b
test: prove WPF current text digest evidence
```

Interactive workflow:

```text
run 32942284572
head ba25ffa9846eeb3c79f41f66572f9c408d02304b
job Windows interactive computer-use E2E
Ran 3 tests in 8.008s
OK
```

The real WPF fixture contains `ZN WPF capability marker`. The resident proves:

- non-native UIA Edit (`native_window_handle == 0`);
- structural and text-state Senses agree on the same RuntimeId/process/AutomationId;
- non-password, ValuePattern-capable, writable target;
- exact current text length;
- exact SHA-256 of the fixture text;
- no raw `text`/`value` export;
- old native Win32 text Sense still refuses WPF.

The same run also re-passed the real pointer/UIA and native Win32 text-entry E2Es.

### 6. Exact implementation/test-head normal Windows CI is green

Workflow:

```text
run 32942313022
head 1a1e4959ec07ac5d67e39033611b9931e705e80e
```

Results:

```text
Electron / TypeScript / Windows   success
ZN Source Boundary / Windows      success
ZN Kernel / Python / Windows      success
Publish Windows CI statuses       success
```

Kernel evidence:

```text
checkout exact 1a1e4959ec07ac5d67e39033611b9931e705e80e
CPython 3.12.13
formal runtime installed from runtime/python
zero-model isolated resident boot success
resident core compile success
Ran 482 tests in 594.172s
OK (skipped=5)
```

All new text-state privacy tests and resident ownership test explicitly passed.

### 7. Documentation synchronized

Status ledger commit:

```text
c39a91bd7ec4a525aae3e24cb032fc11635d1bca
docs: record focused modern text digest evidence
```

`ZN.md` was not changed because the architecture direction did not change. `ZN-SOURCE-EXTRACTION.md` and `ZN-SELF-MAINTENANCE.md` were not changed because source-adoption and self-maintenance architecture did not change.

## Risks / boundaries

- Do not modify `main` through ordinary development.
- No force push/history rewrite.
- Models do not own target selection, input authority or completion.
- `NativeFocusedAutomationTextSense` is read-only evidence, not mutation authority.
- Current mutation remains limited to an already-focused empty native Win32 `Edit`.
- WPF current-state proof is not browser proof.
- Chromium/Edge/Chrome provider behavior has not been proven.
- Password fields must remain fail-closed; provider-side UIA password protection is also relied on for races around a current Value read.
- Raw modern text must not enter observation/store/error output.
- RuntimeId remains action-cycle scoped; AutomationId remains non-authoritative.
- M8 install/upgrade/rollback/signing remains partial.
- SM1+ remains open.
- GitHub Actions JavaScript runtime and Pillow `Image.getdata` warnings remain non-blocking tooling debt.

## Task queue

### P0 - exact-head normal Windows CI
Status: **GREEN FOR IMPLEMENTATION/TEST HEAD**

Run `32942313022` at `1a1e4959...`: all four jobs successful; Kernel `482 tests / 5 skipped / OK`.

### P1 - resident typed native Edit text entry
Status: **VERIFIED NARROW SLICE**

No mutation behavior changed.

### P2 - real interactive computer-use proof
Status: **VERIFIED POINTER + NATIVE TEXT + WPF CURRENT-TEXT DIGEST**

Run `32942284572` passed all three real input-desktop E2Es.

### P3 - modern application/browser text state
Status: **IN PROGRESS / WPF READ-ONLY VERIFIED / BROWSER OPEN**

Next gap is real Chromium/browser provider evidence on the actual runner. Investigate installed browser availability and focused input UIA shape; do not infer browser support.

### P4 - broader keyboard/editing primitives
Status: **PENDING**

Do not start until modern target/current-state authority is independently proven and a narrow typed lifecycle is justified.

### P5 - M8 Windows continuity / rollback / signing
Status: **PENDING / PARTIAL**

### P6 - SM1+ self-maintenance
Status: **PENDING**

## Related files

```text
runtime/python/zn_agent/core/automation_element_sense.py
runtime/python/zn_agent/core/automation_text_state_sense.py
runtime/python/zn_agent/core/focused_modern_text_resident.py
runtime/python/zn_agent/core/focused_text_sense.py
runtime/python/zn_agent/core/focused_text_entry_resident.py
runtime/python/zn_agent/core/provider_bridge.py
tests/zn_agent/core/test_automation_text_capability_sense.py
tests/zn_agent/core/test_automation_text_state_sense.py
tests/zn_agent/core/test_modern_text_resident_ownership.py
tests/zn_agent/e2e/test_windows_interactive_uia_text_capability.py
tests/zn_agent/e2e/test_windows_interactive_pointer_uia.py
tests/zn_agent/e2e/test_windows_interactive_text_entry.py
.github/workflows/zn-windows-interactive-e2e.yml
docs/ZN-IMPLEMENTATION-STATUS.md
.agent/HANDOFF.md
```

## Blockers

No current product or Windows CI blocker for the WPF read-only current-state slice.

## Next real target

1. re-read resulting `dev/zn-agent` HEAD, `main`, PR #6 and docs-head exact normal CI;
2. preserve interactive evidence `32942284572` for the product/E2E head;
3. investigate actual Edge/Chrome/Chromium availability on the real interactive runner;
4. if a browser exists, build a real focused HTML input fixture and inspect structural/current-state UIA evidence without mutation;
5. add browser support only from real provider evidence, preserving password/content privacy gates;
6. only after read-only browser proof consider a separate narrow modern-edit mutation lifecycle;
7. keep M8/SM1+ open and `main` untouched.
