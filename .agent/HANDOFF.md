# ZN Agent Handoff

Updated: 2026-08-26

## Current goal

Browser remains a two-plane ZN subsystem:

```text
Resident Managed Browser
+ User Browser Bridge
= complete browser capability
```

The managed-browser foundation, real local Chromium navigation, narrow exact-DOM-id/main-frame target sensing, and a narrow real Edge UIA provider sensing slice are now verified. The next real target is mutation-safe exact-node continuity followed by the first narrow managed-browser action lifecycle. Do not skip directly to generic click/type or expose a generic Playwright tool surface.

Core principle:

> **ZN uses models. Models do not own ZN.**

Current maintainers/models are replaceable. Project development/release capability belongs to the repository and its automation. Codex is currently unavailable because its billing is exhausted; no current work should depend on delegating to it.

## Branch / HEAD

- fixed development branch: `dev/zn-agent`
- canonical source/release branch: `main`
- latest fully verified implementation/test head before this documentation commit: `1c37dc1914b5fca7a6b8bd901cce55983d36429f`
- canonical `main`: `8234a835dea604783cea0bd9d28a40de654ec03d`
- PR #6 remains draft/open/unmerged, base `main`, head `dev/zn-agent`
- `main` was not modified
- no force push or history rewrite was used

A HANDOFF commit cannot contain its own resulting SHA. Re-read the resulting `dev/zn-agent` HEAD and require exact-head normal Windows CI before calling this documentation handoff fully synchronized.

## Completed in current stage

### 1. Prior documentation-head CI was closed first

Before new code was pushed, the previous documentation head was allowed to finish its own normal Windows CI instead of being cancelled by another push:

```text
head 23af35b76b5f065b48a898c71c93015f80243b53
run 32955217313

ZN Source Boundary / Windows      success
ZN Kernel / Python / Windows      success
Electron / TypeScript / Windows   success
Publish Windows CI statuses       success
```

This closed the prior P0 exactly rather than relying on an older implementation head.

### 2. Real managed-browser target call chain was traced

Before this stage the managed adapter had:

```text
PlaywrightManagedBrowser.observe()
-> _capture()
-> BrowserObservation(target=None)
```

`BrowserTarget` and freshness/authority semantics already existed in `browser.py`, but no real managed-browser target producer existed. Mutation therefore remained correctly unavailable.

### 3. Bounded managed-browser target sensing added

Implementation commit:

```text
1c37dc1914b5fca7a6b8bd901cce55983d36429f
feat: add bounded managed browser target sensing
```

Changed implementation/test files:

```text
runtime/python/zn_agent/core/browser.py
runtime/python/zn_agent/core/managed_browser.py
tests/zn_agent/core/test_browser_contract.py
tests/zn_agent/core/test_managed_browser.py
tests/zn_agent/e2e/test_windows_managed_browser.py
```

The new ZN-owned query contract is deliberately narrow:

```text
BrowserTargetQuery(
    kind=BrowserTargetQueryKind.DOM_ID,
    value=<exact DOM id>,
    frame_id="main",
)
```

Current sensing semantics:

- exact DOM-id only; no arbitrary CSS or generic provider method surface;
- main frame only;
- one unique, connected, visible element required;
- missing, ambiguous/duplicate, detached, hidden and unsupported-frame cases fail closed;
- bounded role/name/frame/selector-hint evidence;
- no raw input value, `textContent`, inner/outer HTML or uncontrolled page dump;
- password target requires explicit `allow_sensitive_fields` and does not export the target name on this path;
- ZN derives an opaque target ID rather than using a provider locator as product identity;
- each observation has current freshness;
- stale target evidence is rejected by existing authority rules;
- current target evidence can form action authority, but target mutations still return explicit `not implemented` failure evidence.

### 4. Real local Chromium target proof is green

Dedicated workflow:

```text
run 32956974100
head 1c37dc1914b5fca7a6b8bd901cce55983d36429f
Windows local managed Chromium E2E   success
```

Job log evidence:

```text
29 browser/core tests   OK
2 real Chromium E2E     OK
```

The real Chromium E2E proves:

- real local headless Chromium session/navigation;
- exact DOM-id/main-frame target sensing;
- bounded target role/name/frame/selector hint;
- raw fixture input value is absent from serialized observation evidence;
- fresh re-observation keeps stable current target identity while freshness changes;
- current click authority can form but actual click remains refused;
- missing/duplicate/hidden/password target safety boundaries;
- target semantic change from textbox to button after navigation changes target identity;
- stale/changed target evidence fails authority;
- metadata endpoint floor remains blocked even with normal private-network permission.

### 5. Exact-head normal Windows CI is green

```text
run 32956974160
head 1c37dc1914b5fca7a6b8bd901cce55983d36429f

ZN Source Boundary / Windows      success
ZN Kernel / Python / Windows      success
Electron / TypeScript / Windows   success
Publish Windows CI statuses       success

CPython 3.12.13
formal runtime install success
zero-model resident boot success
resident core compile success
Ran 511 tests in 575.382s
OK (skipped=5)
```

### 6. Exact-head interactive Windows regression is green after same-head rerun

Workflow:

```text
run 32956974135
head 1c37dc1914b5fca7a6b8bd901cce55983d36429f
```

Attempt 1 failed only the pre-existing pointer checkbox E2E because the real `SendInput` click did not toggle the fixture checkbox. In that same attempt, the native text, WPF current-text and real Edge provider tests passed. The feature net diff does not touch pointer/input/visual/UIA implementation.

The exact same-head interactive job was rerun. Attempt 2 completed `success` with all four substantive real interactive E2Es passing. No product or test change was made to mask the first failure. Treat attempt 1 as a transient self-hosted GUI/SendInput flake, not as a product bug fixed by this stage.

### 7. Development-history accident was kept auditable

An empty root file was accidentally committed as:

```text
0347f30ef4934ffe2713595ba6c6e17c967e9372
noop
```

No force push, reset or history rewrite was used to erase it. `1c37dc19` normally fast-forwards from that commit and deletes the `noop` file from the final tree. The net compare from the clean pre-feature baseline `23af35b7` to `1c37dc19` contains only the five intended browser implementation/test files. There is no `noop` file in the current product tree.

## Current implementation truth

Verified/foundation browser slices now exist for:

- resident-owned browser session/permission/query/target/observation/action/authority/effect semantics;
- lazy resident ownership and shutdown cleanup of the local managed-browser resource;
- real local headless Chromium navigation with fresh authority and post-action observation;
- real local Chromium exact-DOM-id/main-frame target sensing with bounded privacy-safe evidence and freshness;
- browser network/origin/private-network boundaries for the current adapter;
- real Windows interactive Edge default-UIA provider sensing of a focused HTML input without forced renderer accessibility.

Do not overstate this stage. Browser mutation beyond managed `NAVIGATE` is still unavailable. Generic DOM/accessibility targeting and authenticated User Browser Bridge are also incomplete.

## Mutation-safety dependency found during review

The current target ID intentionally changes when page URL or target semantic shape changes. However, a page could replace a DOM node with a new node that has the same DOM id and the same semantic shape; the current hash alone does not prove those are the same exact node.

This is acceptable for the current read-only sensing slice because no target mutation is dispatched. It must be fixed before first mutation.

The execution boundary should therefore use a provider-local transient current node/element handle or equivalent exact-node evidence behind ZN-owned target authority:

```text
fresh BrowserTarget observation
-> provider-local transient exact-node evidence
-> action authority
-> immediately revalidate same current node at dispatch
-> execute one narrow action
-> independently sense fresh postcondition
-> BrowserEffectEvidence
```

The provider-local handle is a disposable Body resource. It must never become ZN identity or a long-lived completion authority.

## Task queue

### P0 - final documentation-head normal CI
Status: **REQUIRED AFTER THIS HANDOFF COMMIT**

Re-read final `dev/zn-agent` HEAD and require its exact-head normal Windows CI before calling repository state synchronized. The feature head itself is already green in normal CI, real Chromium E2E and same-head interactive rerun.

### P1 - exact-node continuity + managed-browser FOCUS
Status: **NEXT / OPEN**

Implement the first narrow target mutation without widening provider authority:

1. bind current ZN target evidence to a provider-local transient exact node/element handle or equivalent;
2. revalidate at execution time that the handle still represents the same connected/current target;
3. implement `BrowserActionKind.FOCUS` only;
4. require current page/target/permission authority;
5. focus the exact current target;
6. independently verify a fresh focused-element postcondition, such as `document.activeElement` matching the same current target;
7. return success only from that fresh postcondition;
8. fail closed on replacement/detach/identity drift;
9. add unit tests + real Chromium E2E;
10. do not expose generic Playwright methods.

`FOCUS` is preferred before click because it has a narrower side effect and a clean independent postcondition.

### P2 - managed-browser CLICK then TYPE_TEXT
Status: **OPEN / BLOCKED ON P1**

Add one lifecycle at a time. Each must re-establish current exact-node authority immediately before dispatch and independently observe its own effect. Do not infer click/type support from target sensing or focus support.

### P3 - broader target sensing
Status: **OPEN**

Expand only as needed to iframe/child-frame targets, generic accessibility semantics and multi-target disambiguation. Preserve bounded evidence and stale-target handling.

### P4 - authenticated User Browser Bridge lifecycle
Status: **FOUNDATION / OPEN**

Use the real Edge UIA provider result as one evidence input. Design attachment/session/tab/permission/mutation lifecycle for the user's existing browser without copying authentication/profile data. Add extension/native messaging only if real evidence shows it is required.

### P5 - isolated parallel Work / Investigation + checkpoints
Status: **OPEN / HIGH PRODUCT PRIORITY**

Must be resident-owned work isolation, not multiple autonomous product identities. Do not make progress depend on Codex or any one model/provider.

### P6 - MCP/connectors / external systems
Status: **OPEN**

Treat MCP/connectors as bounded Body/Channel adapters behind ZN permission/evidence semantics.

### P7 - scheduled/event-driven resident work
Status: **OPEN**

Persist independently of any chat/model session.

### P8 - M8 Windows continuity / rollback / signing
Status: **PARTIAL**

### P9 - SM1+ self-maintenance
Status: **OPEN**

## Risks / boundaries

- `main` remains untouched through ordinary development.
- no force push/history rewrite.
- browser providers are replaceable resources; ZN owns resident semantics.
- target ID/freshness is evidence, but exact-node continuity must be strengthened before mutation.
- a Playwright locator/element handle must not become product identity.
- real browser UIA sensing is not authenticated browser control.
- managed/user browser profiles must remain distinct.
- do not copy browser credentials/profile state as login integration.
- browser mutation beyond managed navigation is unavailable.
- downloads/uploads remain disabled until file authority exists.
- browser network policy is not yet a complete network sandbox/DNS-rebinding solution.
- current desktop text mutation remains native-empty-Edit-only.
- one self-hosted Windows runner means normal and interactive jobs can serialize; exact-head completed runs are the authority.
- the first interactive attempt for `1c37dc19` had one transient pointer failure; only the same-head successful rerun should be used as the regression result.
- M8 remains partial; SM1+ remains open.

## Related files

```text
ZN.md
docs/ZN-PRODUCT-CAPABILITY-MAP.md
docs/ZN-IMPLEMENTATION-STATUS.md
docs/ZN-SOURCE-EXTRACTION.md
docs/ZN-SELF-MAINTENANCE.md
.agent/HANDOFF.md
runtime/python/zn_agent/core/browser.py
runtime/python/zn_agent/core/managed_browser.py
runtime/python/zn_agent/core/provider_bridge.py
runtime/python/zn_agent/core/automation_element_sense.py
runtime/python/zn_agent/core/automation_text_state_sense.py
tests/zn_agent/core/test_browser_contract.py
tests/zn_agent/core/test_managed_browser.py
tests/zn_agent/e2e/test_windows_managed_browser.py
tests/zn_agent/e2e/test_windows_interactive_user_browser_bridge.py
.github/workflows/zn-managed-browser-e2e.yml
.github/workflows/zn-windows-interactive-e2e.yml
.github/workflows/zn-ci.yml
```

## Next real target

Finish exact-head normal CI for this documentation commit. Then implement exact-node continuity plus a narrow managed-browser `FOCUS` lifecycle with execution-time revalidation and independent fresh focus evidence. Keep `main` untouched.
