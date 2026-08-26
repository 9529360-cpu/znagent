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
73257f8c728778054faf74869243b356383fede1
feat: add verified managed browser uncheck
```

Status: **VERIFIED NARROW MANAGED-BROWSER TARGET SENSING + FOCUS + ARIA-PRESSED TOGGLE CLICK + EMPTY-TEXTBOX TYPE_TEXT + NATIVE CHECK + NATIVE UNCHECK; BROADER BROWSER PRODUCT LIFECYCLE OPEN; FINAL DOCUMENTATION-HEAD NORMAL WINDOWS CI REQUIRED**.

## 1. Verified native checkbox mutation lifecycle

CHECK and UNCHECK are separate ZN actions with separate preconditions and postconditions. Neither is implemented as generic click and neither claims ARIA-checkbox support.

CHECK:

```text
BrowserTargetQuery(DOM_ID, main frame)
-> exact current BrowserTarget + provider-local exact element handle
-> BrowserActionAuthority requiring allow_page_interaction
-> execution-time exact-node revalidation
-> provider proves connected enabled native input[type=checkbox]
-> require checked=false
-> provider check()
-> fresh target acquisition
-> exact JS-node continuity
-> unchanged ZN target identity
-> fresh checked=true
-> BrowserEffectEvidence(postcondition="same_exact_target_checked")
```

UNCHECK:

```text
BrowserTargetQuery(DOM_ID, main frame)
-> exact current BrowserTarget + provider-local exact element handle
-> BrowserActionAuthority requiring allow_page_interaction
-> execution-time exact-node revalidation
-> provider proves connected enabled native input[type=checkbox]
-> require checked=true
-> provider uncheck()
-> fresh target acquisition
-> exact JS-node continuity
-> unchanged ZN target identity
-> fresh checked=false
-> BrowserEffectEvidence(postcondition="same_exact_target_unchecked")
```

Current guarantees:

- current page/target/permission/freshness authority is required before dispatch;
- provider-local handles remain disposable execution resources and never become ZN identity;
- non-native and disabled checkbox targets fail closed;
- CHECK refuses an already-checked target before provider dispatch;
- UNCHECK refuses an already-unchecked target before provider dispatch;
- provider return alone is never success;
- provider no-effect fails closed;
- same-shape replacement fails exact-node continuity even if the replacement preserves the requested boolean state;
- provider dispatch exceptions do not become false success;
- normal evidence contains bounded state booleans rather than raw page content;
- exact DOM-id targeting remains main-frame only.

This is **VERIFIED NARROW native CHECK/UNCHECK**, not generic click semantics, ARIA checkbox control, or broad form automation.

## 2. Exact-head real verification for UNCHECK

### Dedicated real local Chromium workflow

```text
run 32979312465
head 73257f8c728778054faf74869243b356383fede1
Windows local managed Chromium E2E   success

62 browser/core tests   OK
2 real Chromium E2E     OK
```

The new UNCHECK contract coverage proves:

- page-interaction permission at the authority boundary;
- native checkbox requirement;
- already-unchecked refusal before dispatch;
- success only from fresh same-node `checked=false` evidence;
- provider no-effect failure;
- same-shape replacement failure;
- disabled checkbox refusal;
- provider dispatch failure does not claim success;
- UNCHECK dispatch is distinct from CHECK dispatch.

The real Chromium fixture additionally proves a real native checkbox can transition unchecked -> checked through CHECK and then checked -> unchecked through UNCHECK while retaining the same exact target identity. A separate checked checkbox that replaces itself during UNCHECK is rejected rather than accepted as successful continuity.

Existing managed navigation, target sensing, exact-node focus, verified aria-pressed toggle click, verified empty-textbox TYPE_TEXT, CHECK replacement rejection, metadata/privacy boundaries and private-network boundary regression all remained green.

### Exact-head interactive Windows regression

```text
run 32979312447
head 73257f8c728778054faf74869243b356383fede1
Windows interactive computer-use E2E   success
```

The real pointer/UIA, native Unicode text-entry, WPF UIA text-capability and isolated-profile installed-browser provider regressions remained green.

### Exact-head normal Windows CI

```text
run 32979312548
head 73257f8c728778054faf74869243b356383fede1

ZN Source Boundary / Windows      success
ZN Kernel / Python / Windows      success
Electron / TypeScript / Windows   success
Publish Windows CI statuses       success
```

The normal Kernel path completed isolated runtime preparation, zero-model resident boot, resident core compilation and the full core test suite. Source Boundary independently proved the active tree remains ZN-only.

## 3. Previously verified managed-browser slices remain narrow

Verified/foundation slices now include:

- resident-owned browser session/permission/query/target/observation/action/authority/effect contracts;
- resident ownership and shutdown of local managed Chromium;
- real local headless Chromium navigation with fresh authority and observed final URL;
- exact `DOM_ID` / main-frame target sensing with bounded metadata and freshness;
- provider-local exact-node continuity at mutation boundaries;
- `FOCUS` with execution-time revalidation and fresh independent `document.activeElement` evidence;
- `CLICK` only for explicit boolean `aria-pressed` transitions;
- `TYPE_TEXT` only for an empty writable non-password `input[type=text]`/`textarea`, requiring `allow_page_interaction + allow_text_entry`, bounded Unicode input and fresh length + SHA-256 completion evidence;
- native `CHECK` from fresh unchecked state to fresh checked state;
- native `UNCHECK` from fresh checked state to fresh unchecked state;
- process-monotonic resident timestamps preventing same-process observation-freshness collisions;
- stale authority/target rejection;
- password target fail-closed boundaries and no raw input value/HTML/uncontrolled page dump in normal target evidence.

`TYPE_TEXT` raw current/request text exists only in transient execution/provider state needed to perform and verify the mutation; durable effect evidence stores bounded lengths/digests rather than raw text.

## 4. User Browser Bridge proof remains narrow

The real Windows interactive Edge proof still establishes only a provider fact:

- an installed stable Edge/Chrome can be discovered on the real runner;
- the proof uses an isolated temporary browser profile;
- no user cookies/password/profile database is copied;
- renderer accessibility is not forced;
- a focused HTML input is sensed through resident Windows UIA;
- text-state evidence remains bounded length + SHA-256 rather than raw text.

This does **not** prove attachment to or mutation of the user's existing authenticated browser session.

## 5. Current browser product truth

Browser is not complete.

Still incomplete:

- `SELECT_OPTION`, `PRESS` and other action-specific browser mutations;
- generic managed-browser click semantics without an independently observable action-specific postcondition;
- editing/replacing non-empty text;
- password/sensitive-field typing;
- contenteditable/rich-text entry;
- ARIA checkbox mutation;
- iframe/child-frame and generic accessibility target sensing;
- multiple-target/disambiguation UX;
- multi-tab/popup/frame lifecycle;
- headed managed-browser product UX;
- screenshots/visual target fusion;
- download/upload/file-picker authority;
- persistent managed profile policy;
- optional cloud browser adapter;
- browser crash/health/recovery lifecycle;
- complete DNS-rebinding/network-sandbox hardening;
- formal Chromium/Playwright release packaging;
- authenticated User Browser Bridge attachment/session/tab/permission/mutation lifecycle;
- browser permission UX and MFA/sensitive-field handoff.

## 6. Broader product gaps remain material

Browser breadth is only one part of product completeness. High-leverage open foundations remain:

- durable resident-owned Work checkpoints, restore and per-task recovery;
- isolated parallel Work / Investigation without creating multiple ZN identities;
- MCP/connector interoperability behind ZN-owned permission/evidence contracts;
- scheduled/event-driven resident work;
- unified permission/audit control surfaces;
- Windows M8 installation/update/rollback/signing continuity;
- SM1+ isolated self-repair lifecycle.

These must not be implemented by making a model, an agent framework, MCP, a browser provider or the desktop UI the owner of ZN.

## 7. Development-history audit notes

The earlier accidental empty root `noop` commit remains visible in history and was removed by a later normal fast-forward commit; no history rewrite was used.

A preceding maintenance pass also accidentally created `docs/.tmp` in `e3eb38cce090c6c268866f911cffc0d5ce288636` and removed it immediately with normal fast-forward commit `37fe40556caafb9113a08c1e22d2beb519fc64b5`. It is absent from the product tree. No force push or history rewrite was used to hide either mistake.

## 8. Next implementation order

First require exact-head normal Windows CI for the final documentation HEAD created from this update.

Then continue the browser stage with the next bounded action only if its precondition and independently observable effect can be made product-grade. Current candidate order is:

```text
1. close final UNCHECK documentation-head CI
2. trace SELECT_OPTION contract/provider/effect lifecycle
3. implement one narrow native-select slice with fresh selected-value evidence
4. add unit + real Chromium replacement/no-effect coverage
5. reassess whether PRESS has a sufficiently bounded effect contract
6. stop the browser action sequence at a useful checkpoint rather than exposing arbitrary provider methods
7. move the next major foundation to durable Work / checkpoint / recovery
```

After durable Work, the intended leverage order is isolated parallel Investigation, MCP/connectors, scheduled/event-driven work, authenticated User Browser Bridge, unified permission/audit control surfaces, M8 continuity and SM1+ according to dependency and risk.

M8 Windows continuity remains PARTIAL. SM0 remains verified foundation; SM1+ remains open. High-risk identity, long-term memory, credential/permission, updater/signing and destructive self-maintenance changes continue to require human approval.
