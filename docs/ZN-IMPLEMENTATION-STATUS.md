# ZN implementation status

> Architecture contract: [`../ZN.md`](../ZN.md)
>
> Product capability ledger: [`ZN-PRODUCT-CAPABILITY-MAP.md`](ZN-PRODUCT-CAPABILITY-MAP.md)
>
> Source adoption boundary: [`ZN-SOURCE-EXTRACTION.md`](ZN-SOURCE-EXTRACTION.md)
>
> Self-maintenance contract: [`ZN-SELF-MAINTENANCE.md`](ZN-SELF-MAINTENANCE.md)
>
> Real code, Git state and CI outrank this ledger.

Development branch: `dev/zn-agent`. Canonical source/release branch: `main`.

## Current checkpoint - 2026-08-26

M10 canonical source promotion remains complete. Ordinary development remains on `dev/zn-agent`; `main` was not modified in this stage.

Latest fully verified implementation/test head before this status-document update:

```text
0002accb359351ec07761b3d017d13040d35c941
feat: add verified managed browser text entry
```

Status: **VERIFIED NARROW MANAGED-BROWSER TARGET SENSING + FOCUS + ARIA-PRESSED TOGGLE CLICK + EMPTY-TEXTBOX TYPE_TEXT; FINAL DOCUMENTATION-HEAD NORMAL WINDOWS CI REQUIRED**.

## 1. Narrow verified managed-browser TYPE_TEXT lifecycle

The first managed text-entry slice is deliberately narrower than a generic browser typing API.

Current call chain:

```text
BrowserTargetQuery(DOM_ID, main frame)
-> PlaywrightManagedBrowser.observe_target()
-> bounded ZN BrowserTarget + transient provider-local exact element handle
-> BrowserActionAuthority from the exact current observation
   requiring allow_page_interaction + allow_text_entry
-> execution-time exact-node revalidation
-> bounded current text-state read
-> require empty writable non-password textbox
-> BrowserActionKind.TYPE_TEXT
-> provider fill(text)
-> fresh target acquisition
-> exact JS-node continuity check
-> fresh text-state read
-> requested length + SHA-256 match
-> BrowserEffectEvidence(postcondition="same_exact_target_text_equals_requested")
```

Current guarantees and limits:

- current page/target/permission/freshness authority is required before dispatch;
- `TYPE_TEXT` authority requires both `allow_page_interaction` and `allow_text_entry`;
- provider-local element handles are disposable execution resources, never ZN identity;
- the first slice accepts only an exact current textbox target backed by `input[type=text]` or `textarea`;
- disabled and read-only targets fail closed;
- password targets are refused even when `allow_sensitive_fields=True`; password entry is not enabled by this slice;
- the current target must be empty; replacing/editing existing non-empty text is not enabled;
- input must be an explicit non-empty string with no control characters and at most 512 UTF-16 code units;
- provider dispatch alone is never success;
- success requires a fresh target observation, the same exact JS node, unchanged ZN target identity, and fresh text length + SHA-256 matching the requested text;
- same-shape DOM replacement during input fails closed even if the replacement copies the requested value;
- provider dispatch with no observed text change fails closed;
- raw target/request text exists only in the transient provider/action execution path needed to perform and verify the mutation; normal `BrowserEffectEvidence` stores only bounded lengths/digests and never the raw text;
- target observation still exports no raw input value, HTML, or uncontrolled page dump;
- exact DOM-id targeting remains main-frame only in this slice.

This is **VERIFIED NARROW empty-textbox TYPE_TEXT**, not arbitrary text replacement, contenteditable editing, password entry, generic keyboard input, or authenticated user-browser typing.

## 2. Exact-head real verification for TYPE_TEXT

### Dedicated real local Chromium workflow

```text
run 32969877355
head 0002accb359351ec07761b3d017d13040d35c941
Windows local managed Chromium E2E   success

47 browser/core tests   OK
2 real Chromium E2E     OK
```

The dedicated suite includes seven TYPE_TEXT contract tests covering:

- `allow_text_entry` permission at the authority boundary;
- explicit non-empty text requirement;
- non-empty target refusal before dispatch;
- success only from fresh same-node length/digest evidence;
- provider no-effect failure;
- same-shape target replacement failure;
- password refusal even with sensitive-field permission.

The real Chromium fixture additionally proves:

- navigation, bounded target sensing, exact-node `FOCUS`, and verified `aria-pressed` toggle click remain working;
- real Unicode text is entered into an empty browser textbox;
- success evidence contains the requested length/digest, not the raw typed text;
- a page that replaces the textbox during input is rejected by exact-node continuity even when the replacement copies the typed value;
- existing target/privacy/network safety boundaries remain intact.

### Exact-head interactive Windows regression

```text
run 32969877468
head 0002accb359351ec07761b3d017d13040d35c941
Windows interactive computer-use E2E   success

Ran 4 tests in 11.183s
OK
```

The real pointer/UIA focus proof, native Unicode text-entry proof, WPF UIA text-capability proof, and isolated-profile real Edge browser-provider proof all remained green. The Edge proof again used the installed browser without forced renderer accessibility and without copying a user browser profile.

### Exact-head normal Windows CI

```text
run 32969877380
head 0002accb359351ec07761b3d017d13040d35c941

ZN Source Boundary / Windows      success
ZN Kernel / Python / Windows      success
Electron / TypeScript / Windows   success
Publish Windows CI statuses       success

CPython 3.12.13
formal runtime install success
zero-model resident boot success
resident core compile success
Ran 529 tests in 571.144s
OK (skipped=5)
```

The full Kernel suite includes all seven new managed-browser TYPE_TEXT contract tests.

## 3. Previously verified managed-browser mutations remain narrow

Earlier verified managed slices remain:

- real local headless Chromium navigation with fresh authority and observed final URL;
- exact `DOM_ID` / main-frame target sensing with bounded metadata and freshness;
- provider-local exact-node continuity at the mutation boundary;
- `FOCUS` with execution-time revalidation and independent `document.activeElement` postcondition;
- `CLICK` only for explicit boolean `aria-pressed` transitions, with fresh pre/post state and same-node continuity;
- process-monotonic resident timestamps preventing same-process observation-freshness collisions;
- stale authority/target rejection;
- password target fail-closed behavior without explicit sensitive-field sensing permission;
- no raw input value/HTML/uncontrolled page dump in target observation evidence.

The verified click implementation remains deliberately non-generic. Arbitrary links/buttons are not considered successfully clicked merely because Playwright dispatch returns without error.

## 4. User Browser Bridge proof remains narrow

The real Windows interactive Edge proof still establishes only a provider fact:

- installed stable Edge/Chrome can be discovered on the real runner;
- the proof uses an isolated temporary browser profile;
- no user cookies/password/profile database is copied;
- renderer accessibility is not forced;
- a focused HTML input is sensed through resident Windows UIA;
- text-state evidence remains bounded length + SHA-256 rather than raw text.

This does **not** prove attachment to or mutation of the user's existing authenticated browser session.

## 5. Current browser product truth

Browser is not complete.

Verified narrow/foundation slices now include:

- resident-owned browser contracts and managed resource lifecycle;
- managed navigation;
- managed exact DOM-id/main-frame target sensing;
- managed exact-node `FOCUS`;
- managed exact-node `CLICK` only for explicit boolean `aria-pressed` transitions;
- managed exact-node `TYPE_TEXT` only for an empty writable non-password text input/textarea with privacy-safe length/digest completion evidence;
- real local Chromium proof for all of those managed slices;
- isolated-profile real Edge UIA focused-input sensing proof.

Still incomplete:

- generic managed-browser click semantics without an action-specific independent postcondition;
- editing/replacing non-empty text;
- password/sensitive-field typing;
- contenteditable/rich-text entry;
- `CHECK` / `UNCHECK`, `SELECT_OPTION`, `PRESS`, and other browser mutations;
- iframe/child-frame and generic accessibility target sensing;
- multiple-target/disambiguation UX;
- multi-tab/popup/frame lifecycle;
- headed managed-browser product UX;
- screenshots/visual target fusion;
- download/upload/file-picker authority;
- persistent managed profile policy;
- cloud browser adapter;
- browser crash/health/recovery lifecycle;
- complete DNS-rebinding/network-sandbox hardening;
- formal Chromium/Playwright release packaging;
- authenticated User Browser Bridge attachment/session/tab/permission/mutation lifecycle;
- browser permission UX and MFA/sensitive-field handoff.

## 6. Development-history audit notes

The earlier accidental empty root `noop` commit remains visible in history and was removed by a later normal fast-forward commit; no history rewrite was used.

A preceding maintenance pass also accidentally created `docs/.tmp` in `e3eb38cce090c6c268866f911cffc0d5ce288636` and removed it immediately with normal fast-forward commit `37fe40556caafb9113a08c1e22d2beb519fc64b5`. It is absent from the product tree. No force push or history rewrite was used to hide either mistake.

## 7. Next implementation order

First require exact-head normal Windows CI for the final documentation HEAD created from this update.

The next narrow managed-browser action should be `CHECK` first, followed by `UNCHECK`, because the boolean current `checked` state provides a strong independently observable postcondition. This is a target for investigation, not a claim that checkbox mutation already exists.

Preferred order:

```text
1. finish final docs exact-head normal Windows CI
2. trace CHECK's real permission/target/state/effect call chain
3. require current exact-node authority and an actual checkbox target
4. observe boolean checked pre-state before mutation
5. reject already-satisfied transitions rather than claiming a new action
6. dispatch CHECK only
7. fresh re-observe same exact node + checked=true
8. reject replacement/detach/identity drift/provider no-effect
9. add unit + real Chromium evidence
10. add UNCHECK only after CHECK is independently verified
```

After that, `SELECT_OPTION`, `PRESS`, broader click semantics, richer target sensing/lifecycle, authenticated User Browser Bridge, isolated parallel Work/Investigation, connectors, scheduling, M8 continuity, and SM1+ remain open according to dependency and risk.

M8 Windows continuity remains PARTIAL. SM0 remains verified foundation; SM1+ remains open. High-risk identity, long-term memory, credential/permission, updater/signing, and destructive self-maintenance changes continue to require human approval.
