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
a6cc5619fee9d9e41d2fa0e885af0ba58db84f6c
feat: add verified managed browser check
```

Status: **VERIFIED NARROW MANAGED-BROWSER TARGET SENSING + FOCUS + ARIA-PRESSED TOGGLE CLICK + EMPTY-TEXTBOX TYPE_TEXT + NATIVE CHECK; UNCHECK OPEN; FINAL DOCUMENTATION-HEAD NORMAL WINDOWS CI REQUIRED**.

## 1. Narrow verified managed-browser CHECK lifecycle

The first CHECK slice is deliberately limited to a real native checkbox. It does not generalize checkbox semantics from ARIA roles and it does not implement `UNCHECK`.

Current call chain:

```text
BrowserTargetQuery(DOM_ID, main frame)
-> PlaywrightManagedBrowser.observe_target()
-> bounded ZN BrowserTarget + transient provider-local exact element handle
-> BrowserActionAuthority from the exact current observation
   requiring allow_page_interaction
-> execution-time exact-node revalidation
-> native checkbox-state read
-> require input[type=checkbox], enabled, checked=false
-> BrowserActionKind.CHECK
-> provider check()
-> fresh target acquisition
-> exact JS-node continuity check
-> fresh native checked-state read
-> require same ZN target identity + checked=true
-> BrowserEffectEvidence(postcondition="same_exact_target_checked")
```

Current guarantees and limits:

- current page/target/permission/freshness authority is required before dispatch;
- provider-local element handles remain disposable execution resources and never become ZN identity;
- target role must be `checkbox`, then provider state independently confirms the actual element is a connected native `input[type=checkbox]`;
- disabled and non-native checkbox targets fail closed;
- an already-checked target is refused before provider dispatch rather than being reported as a new successful CHECK;
- provider dispatch alone is never success;
- success requires fresh same-exact-node evidence, unchanged ZN target identity, and `checked=true` from current browser reality;
- provider no-effect fails closed;
- a page that replaces the checkbox with a same-shape node during the action fails exact-node continuity even if the replacement preserves `checked=true`;
- target observation continues to export bounded target metadata rather than raw page content;
- `UNCHECK` remains explicitly unimplemented and separately test-guarded;
- exact DOM-id targeting remains main-frame only.

This is **VERIFIED NARROW native CHECK**, not generic click/toggle semantics, ARIA checkbox control, or `UNCHECK`.

## 2. Exact-head real verification for CHECK

### Dedicated real local Chromium workflow

```text
run 32973414369
head a6cc5619fee9d9e41d2fa0e885af0ba58db84f6c
Windows local managed Chromium E2E   success

55 browser/core tests   OK
2 real Chromium E2E     OK
```

All eight new CHECK contract tests passed, covering:

- page-interaction permission at the authority boundary;
- native checkbox requirement;
- already-checked refusal before dispatch;
- success only from fresh same-node `checked=true` evidence;
- provider no-effect failure;
- same-shape replacement failure;
- disabled checkbox refusal;
- `UNCHECK` remains unimplemented and does not dispatch CHECK.

The real Chromium fixture additionally proves:

- navigation, bounded target sensing, exact-node `FOCUS`, verified `aria-pressed` toggle click, and verified empty-textbox `TYPE_TEXT` remain working;
- a real native checkbox transitions from unchecked to checked under the CHECK lifecycle;
- the postcondition is observed from current native `checked` state rather than inferred from provider return;
- a same-shape replacement during checking is not accepted as the same exact target;
- a following `UNCHECK` probe is still refused;
- existing target/privacy/network safety boundaries remain intact.

### Exact-head interactive Windows regression

```text
run 32973418964
head a6cc5619fee9d9e41d2fa0e885af0ba58db84f6c
Windows interactive computer-use E2E   success
```

The existing real pointer/UIA, native Unicode text-entry, WPF UIA text-capability, and isolated-profile installed-browser provider regressions all completed successfully on the exact CHECK head.

### Exact-head normal Windows CI

```text
run 32973414561
head a6cc5619fee9d9e41d2fa0e885af0ba58db84f6c

ZN Source Boundary / Windows      success
ZN Kernel / Python / Windows      success
Electron / TypeScript / Windows   success
Publish Windows CI statuses       success
```

The normal Kernel path completed formal runtime installation, zero-model resident boot, resident core compilation, and the full core test suite successfully. The exact normal-suite count is intentionally not copied here because the completed job log did not expose a stable bounded count through the maintenance connector; the completed job result is the authority.

## 3. Previous TYPE_TEXT documentation P0 was closed first

Before CHECK was pushed, the previous documentation head:

```text
04e48948bca64b8c9d179333ddd4498b61681dad
docs: record verified managed browser text entry
```

completed exact-head normal Windows run `32971420718` with Source Boundary, Kernel, Electron, and status publisher all `success`. CHECK therefore did not cancel or substitute for the prior documentation-head P0.

## 4. Previously verified managed-browser mutations remain narrow

Earlier verified managed slices remain:

- real local headless Chromium navigation with fresh authority and observed final URL;
- exact `DOM_ID` / main-frame target sensing with bounded metadata and freshness;
- provider-local exact-node continuity at mutation boundaries;
- `FOCUS` with execution-time revalidation and independent `document.activeElement` evidence;
- `CLICK` only for explicit boolean `aria-pressed` transitions, with fresh pre/post state and exact-node continuity;
- `TYPE_TEXT` only for an empty writable non-password `input[type=text]`/`textarea`, requiring `allow_page_interaction + allow_text_entry`, bounded Unicode input, exact-node continuity, and fresh text length + SHA-256 completion evidence;
- process-monotonic resident timestamps preventing same-process observation-freshness collisions;
- stale authority/target rejection;
- password target fail-closed boundaries and no raw input value/HTML/uncontrolled page dump in normal target evidence.

`TYPE_TEXT` raw current/request text exists only in transient execution/provider state required to perform and verify the mutation; normal effect evidence stores bounded lengths/digests rather than raw text.

## 5. User Browser Bridge proof remains narrow

The real Windows interactive Edge proof still establishes only a provider fact:

- an installed stable Edge/Chrome can be discovered on the real runner;
- the proof uses an isolated temporary browser profile;
- no user cookies/password/profile database is copied;
- renderer accessibility is not forced;
- a focused HTML input is sensed through resident Windows UIA;
- text-state evidence remains bounded length + SHA-256 rather than raw text.

This does **not** prove attachment to or mutation of the user's existing authenticated browser session.

## 6. Current browser product truth

Browser is not complete.

Verified narrow/foundation slices now include:

- resident-owned browser contracts and managed resource lifecycle;
- managed navigation;
- managed exact DOM-id/main-frame target sensing;
- managed exact-node `FOCUS`;
- managed exact-node `CLICK` only for explicit boolean `aria-pressed` transitions;
- managed exact-node `TYPE_TEXT` only for an empty writable non-password text input/textarea;
- managed exact-node native `CHECK` only for an enabled unchecked `input[type=checkbox]`;
- real local Chromium proof for all managed slices above;
- isolated-profile real Edge UIA focused-input sensing proof.

Still incomplete:

- `UNCHECK`;
- generic managed-browser click semantics without an action-specific independent postcondition;
- editing/replacing non-empty text;
- password/sensitive-field typing;
- contenteditable/rich-text entry;
- ARIA checkbox mutation;
- `SELECT_OPTION`, `PRESS`, and other browser mutations;
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

## 7. Development-history audit notes

The earlier accidental empty root `noop` commit remains visible in history and was removed by a later normal fast-forward commit; no history rewrite was used.

A preceding maintenance pass also accidentally created `docs/.tmp` in `e3eb38cce090c6c268866f911cffc0d5ce288636` and removed it immediately with normal fast-forward commit `37fe40556caafb9113a08c1e22d2beb519fc64b5`. It is absent from the product tree. No force push or history rewrite was used to hide either mistake.

## 8. Next implementation order

First require exact-head normal Windows CI for the final documentation HEAD created from this update.

The next narrow managed-browser action is `UNCHECK`, kept separate from CHECK so its own precondition, dispatch, replacement behavior, and fresh postcondition are independently proven.

Preferred order:

```text
1. finish final CHECK docs exact-head normal Windows CI
2. trace UNCHECK's current permission/target/state/effect call chain
3. require current exact-node native checkbox authority
4. observe checked=true before mutation
5. refuse already-unchecked state rather than claiming a new transition
6. dispatch UNCHECK only
7. fresh re-observe same exact node + checked=false
8. reject replacement/detach/identity drift/provider no-effect
9. add unit + real Chromium evidence
10. only then move to SELECT_OPTION / PRESS / broader click semantics
```

After that, richer target sensing/lifecycle, authenticated User Browser Bridge, isolated parallel Work/Investigation, connectors, scheduling, M8 continuity, and SM1+ remain open according to dependency and risk.

M8 Windows continuity remains PARTIAL. SM0 remains verified foundation; SM1+ remains open. High-risk identity, long-term memory, credential/permission, updater/signing, and destructive self-maintenance changes continue to require human approval.
