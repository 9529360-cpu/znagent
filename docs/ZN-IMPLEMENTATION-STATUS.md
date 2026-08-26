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
a6a014d836ad3f61d14b4c6a25221957a5dca9a1
test: prove verified managed browser toggle click
```

Status: **VERIFIED NARROW MANAGED-BROWSER FOCUS + VERIFIED NARROW ARIA-PRESSED TOGGLE CLICK; FINAL DOCUMENTATION-HEAD NORMAL WINDOWS CI REQUIRED**.

## Narrow verified managed-browser CLICK lifecycle

The first click slice is deliberately not a generic browser click API. It is a bounded, independently verifiable toggle transition.

Current call chain:

```text
BrowserTargetQuery(DOM_ID, main frame)
-> PlaywrightManagedBrowser.observe_target()
-> bounded ZN BrowserTarget + transient provider-local exact element handle
-> BrowserActionAuthority from the exact current observation
-> execution-time provider revalidation of the same current node
-> BrowserActionKind.CLICK with expected={"aria_pressed": <bool>}
-> observe boolean aria-pressed precondition
-> provider click dispatch
-> fresh target acquisition
-> exact JS node continuity check
-> fresh boolean aria-pressed observation
-> BrowserEffectEvidence(postcondition="same_exact_target_aria_pressed")
```

Current guarantees and limits:

- current page/target/permission/freshness authority is required before dispatch;
- the Playwright element handle is a disposable provider-local execution resource, not ZN identity;
- generic click without an independently verifiable postcondition remains unavailable;
- this slice requires an explicit boolean `expected["aria_pressed"]` postcondition;
- the target must expose a current boolean `aria-pressed` state;
- if the requested state is already present, ZN refuses to claim a click transition and does not dispatch;
- provider dispatch alone is never success;
- success requires a fresh post-action target observation, exact-node continuity, unchanged ZN target identity, and the requested `aria-pressed` transition;
- a provider dispatch that does not produce the requested state fails closed;
- same-shape DOM replacement during click fails closed even if the replacement reports the requested `aria-pressed` value;
- raw page content, input values and HTML are not exported as completion evidence;
- exact DOM-id targeting remains main-frame only in this slice.

This is **VERIFIED NARROW toggle click**, not arbitrary link/button activation, navigation click, checkbox/select semantics, or a generic Playwright click surface.

## Exact-head real verification for the CLICK implementation

### Dedicated real local Chromium workflow

```text
run 32967137365
head a6a014d836ad3f61d14b4c6a25221957a5dca9a1
Windows local managed Chromium E2E   success

40 browser/core tests   OK
2 real Chromium E2E     OK
```

The real Chromium fixture proves:

- navigation and bounded exact-DOM-id target sensing remain working;
- exact-node managed `FOCUS` remains working;
- generic click without an explicit verified postcondition remains refused;
- `aria-pressed=false -> true` succeeds only from fresh same-node evidence;
- a fresh second action proves `aria-pressed=true -> false` on the same target lifecycle;
- a click handler that replaces the target with a same-shape clone fails exact-node continuity even when the replacement has `aria-pressed=true`;
- existing password/hidden/ambiguous/missing target boundaries remain fail-closed;
- the metadata/private-network safety floor remains intact.

### Exact-head interactive Windows regression

```text
run 32967137348
head a6a014d836ad3f61d14b4c6a25221957a5dca9a1
Windows interactive computer-use E2E   success

4 real interactive tests   OK
```

This preserved the real pointer/UIA focus proof, native Unicode text-entry proof, WPF UIA text-capability proof, and isolated-profile real Edge user-browser provider proof. The Edge proof continued to run without forced renderer accessibility or copying a user browser profile.

### Exact-head normal Windows CI

```text
run 32967137328
head a6a014d836ad3f61d14b4c6a25221957a5dca9a1

ZN Source Boundary / Windows      success
ZN Kernel / Python / Windows      success
Electron / TypeScript / Windows   success
Publish Windows CI statuses       success

CPython 3.12.13
formal runtime install success
zero-model resident boot success
resident core compile success
Ran 522 tests in 552.760s
OK (skipped=5)
```

The normal Kernel suite includes all five new managed-browser click contract tests.

## Failed predecessor runs remain part of the evidence trail

The first implementation head was:

```text
9c360e02bd5730c32f0bd84a281e5a515f28c9b8
feat: add verified managed browser toggle click
```

Its dedicated managed-browser run `32965439542` and normal run `32965439522` failed because two pre-existing tests still expected the old generic-click error text to contain `not implemented`. All five new click-specific contract tests themselves passed.

The implementation was not removed or the tests weakened. The follow-up commit `a6a014d8` made the generic boundary explicit in production error evidence:

```text
generic browser click is not implemented;
verified toggle click requires explicit boolean expected aria_pressed postcondition
```

It also added real Chromium success/failure proof for the narrow toggle-click lifecycle.

## Previously verified browser foundations retained

Earlier verified slices remain:

- resident-owned browser session/permission/query/target/observation/action/authority/effect contracts;
- lazy resident ownership and shutdown cleanup of managed Chromium;
- real local headless Chromium navigation with fresh authority and observed final URL;
- bounded exact-DOM-id/main-frame target sensing;
- provider-local exact-node continuity at the mutation boundary;
- narrow managed-browser `FOCUS` with execution-time revalidation and independent `document.activeElement` evidence;
- process-monotonic resident timestamps preventing same-process freshness collisions;
- stale target/authority rejection;
- password target fail-closed behavior without explicit sensitive-field permission;
- no raw input value/HTML/uncontrolled page dump in target observation evidence;
- real Windows interactive Edge default-UIA sensing of a focused HTML input without forced renderer accessibility or user-profile copying.

The User Browser Bridge proof remains sensing-only and does not prove control of the user's authenticated browser session.

## Current browser product truth

Browser is not complete.

Verified narrow/foundation slices now include:

- managed navigation;
- managed exact DOM-id/main-frame target sensing;
- managed exact-node `FOCUS` with fresh independent focus evidence;
- managed exact-node `CLICK` only for explicit boolean `aria-pressed` state transitions;
- real local Chromium proof for all of those managed slices;
- isolated-profile real Edge UIA focused-input sensing proof.

Still incomplete:

- generic managed-browser click semantics for links/buttons/actions without a bounded independent postcondition;
- managed `TYPE_TEXT`;
- select/check/keyboard and other browser mutations;
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

Desktop text mutation remains limited to the already-focused empty native Win32 `Edit`; WPF/Edge current-text sensing must not be treated as browser text-mutation authority.

## Development-history audit notes

The earlier accidental empty root `noop` commit remains visible in history and was removed by a later normal fast-forward commit; no history rewrite was used.

During the preceding maintenance pass, an accidental `docs/.tmp` file was created in `e3eb38cce090c6c268866f911cffc0d5ce288636` and removed immediately by normal fast-forward commit `37fe40556caafb9113a08c1e22d2beb519fc64b5`. It is absent from the product tree. No force push or history rewrite was used to hide either mistake.

## Next implementation order

The next managed-browser mutation is `TYPE_TEXT`, but only after the final documentation HEAD completes exact-head normal Windows CI.

Preferred order:

```text
1. finish final docs exact-head normal Windows CI
2. trace TYPE_TEXT's real permission/target/state/effect call chain
3. require allow_text_entry + current exact-node authority
4. define privacy-safe pre/post text-state evidence before provider mutation
5. keep raw text/value out of normal observation/effect logs
6. handle sensitive/password fields under an explicit stricter permission boundary
7. dispatch one narrow text-entry lifecycle
8. independently verify the fresh postcondition from current reality
9. add unit + real Chromium evidence
10. only then consider broader click/select/check/keyboard semantics
```

A likely reusable evidence shape is bounded text length plus digest, consistent with existing modern UI/Edge read-only text-state sensing, but the exact TYPE_TEXT contract must be decided from the real call chain rather than copied mechanically.

M8 Windows continuity remains PARTIAL. SM0 remains verified foundation; SM1+ remains open. High-risk identity, long-term memory, credential/permission, updater/signing and destructive self-maintenance changes continue to require human approval.
