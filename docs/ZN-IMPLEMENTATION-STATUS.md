# ZN implementation status

> Architecture contract: [`../ZN.md`](../ZN.md)
>
> Product capability ledger: [`ZN-PRODUCT-CAPABILITY-MAP.md`](ZN-PRODUCT-CAPABILITY-MAP.md)
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

Latest fully verified implementation/test head before this status-document update:

```text
1c37dc1914b5fca7a6b8bd901cce55983d36429f
feat: add bounded managed browser target sensing
```

Status: **VERIFIED MANAGED-BROWSER FOUNDATION + VERIFIED NARROW DOM-ID TARGET SENSING + VERIFIED NARROW REAL EDGE UIA PROVIDER SENSING**.

Exact-head normal Windows x64 CI:

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

Dedicated exact-head real managed Chromium evidence:

```text
run 32956974100
head 1c37dc1914b5fca7a6b8bd901cce55983d36429f
Windows local managed Chromium E2E   success

29 browser/core tests   OK
2 real Chromium E2E     OK
```

Exact-head interactive Windows regression:

```text
run 32956974135
head 1c37dc1914b5fca7a6b8bd901cce55983d36429f
attempt 2 / rerun   success
```

Attempt 1 of the same run had one failure in the pre-existing real pointer checkbox test because a `SendInput` click did not toggle the fixture checkbox. The browser UIA provider proof, native text test and WPF test succeeded in that attempt. No pointer/input/visual/UIA product code was changed. The same-head rerun then passed all four interactive tests, so this is recorded as a transient self-hosted GUI/SendInput failure, not as a product fix.

## 2. Browser remains a two-plane ZN subsystem

`ZN.md` requires:

```text
Resident Managed Browser
+ User Browser Bridge
= complete browser capability
```

The managed plane serves ZN-owned web work. The user-browser plane serves task reality already present in the user's browser. Browser engines, accessibility providers, extensions and cloud services remain replaceable resources; they do not own ZN intent, identity, memory or completion truth.

Managed browsing must not solve login by copying browser cookies, password stores, profile databases or other credentials. Richer access to a user's existing browser must preserve browser/OS boundaries and explicit permission.

## 3. Managed-browser foundation

Key foundation commits include:

```text
0ffe253fa57f1da003a28cdec200d304a7bbe71f
feat: add ZN browser session contracts

25da7bb75ab4e46a7f7feef1216eff8e09e29da1
feat: add local managed browser adapter

4dd03d2ee79d8a078ea0fa8cf18217b33c193891
feat: make managed browser resident-owned

cc8513db404c2507c11077b7d3e7e754ca8eb450
fix: require observed browser target authority

86753e29d318272970f258e3c1691312f3a0685c
test: reject unobserved browser target authority

a06d85a726cf6cc0eeb4b6c4cad4618435df0ef1
fix: harden browser authority after independent review

a62cf5a6ff3b8bacf19d12cf0fe4dfba3e5a2f4d
fix: close managed browser with resident service
```

`runtime/python/zn_agent/core/browser.py` owns browser session, permission, target, observation, action, authority and effect semantics. Targeted authority fails closed when current observation lacks the target or target ID/kind/frame/freshness has drifted.

`runtime/python/zn_agent/core/managed_browser.py` provides the first adapter, `PlaywrightManagedBrowser`:

- Playwright is lazy/optional and does not own resident life;
- managed sessions are ephemeral Chromium contexts;
- service workers are blocked and downloads/uploads remain disabled in this slice;
- HTTP(S) and supported WebSocket routes use ZN URL/private-network/origin policy;
- page observation exports bounded URL/title/load-state/viewport/provider metadata, not uncontrolled raw page dumps;
- `NAVIGATE` remains the only implemented browser mutation;
- navigation requires current observation + permission + fresh authority;
- success is formed only from fresh post-navigation observation and safe final URL;
- unimplemented actions return explicit failure evidence;
- resident service shutdown closes the resident-owned managed-browser resource.

Formal release packaging of Playwright/Chromium is still open.

## 4. Narrow managed-browser target sensing is now real

Commit:

```text
1c37dc1914b5fca7a6b8bd901cce55983d36429f
feat: add bounded managed browser target sensing
```

The previous real call-chain gap was:

```text
PlaywrightManagedBrowser.observe()
-> _capture()
-> BrowserObservation(target=None)
```

The adapter now also supports a deliberately narrow ZN-owned target-sensing path:

```text
BrowserTargetQuery(kind=DOM_ID, value=..., frame_id="main")
-> PlaywrightManagedBrowser.observe_target()
-> provider resolves exactly one current main-frame DOM node
-> bounded BrowserTarget
-> BrowserObservation(target=current BrowserTarget)
-> BrowserActionAuthority can bind to that exact current observation
```

Current target-sensing guarantees:

- the query contract is typed and bounded;
- the first query kind is exact `DOM_ID` only, not arbitrary CSS or a generic Playwright surface;
- only the main frame is supported in this slice;
- exactly one connected, visible matching element is required;
- missing, duplicate/ambiguous, detached, hidden or non-main-frame targets fail closed;
- target evidence is bounded to identity-relevant metadata such as role/name/frame/selector hint;
- raw input value, `textContent`, inner/outer HTML and uncontrolled page content are not exported;
- password targets require explicit `allow_sensitive_fields`; even then their accessible name is not exported by this path;
- ZN derives its own opaque target ID rather than treating a Playwright locator/selector as product identity;
- fresh re-observation produces a fresh observation timestamp;
- stale target evidence is rejected by existing authority rules;
- URL or semantic target-shape changes produce a changed target identity in the current implementation;
- the real Chromium E2E proves these boundaries on the actual Windows browser runtime.

The real Chromium fixture also verifies that a target input's raw value does not appear in serialized ZN observation evidence, and that changing the same DOM id from a textbox to a button after navigation changes target identity.

This is **narrow target sensing**, not generic DOM/accessibility completion. Still open:

- iframe/child-frame target sensing;
- generic accessibility-node queries;
- multiple-target result sets and disambiguation UX;
- robust page/tab/frame lifecycle;
- headed-browser product UX;
- visual-browser target fusion.

A further mutation-safety dependency was identified during review: the current opaque target ID distinguishes page/semantic-shape changes but does not by itself prove continuity when a page replaces one DOM node with another node that has the same DOM id and identical semantic shape. That is acceptable while target sensing is read-only, but mutation must not rely on the hash alone.

Before the first managed-browser target mutation, execution must establish exact-node continuity using a provider-local transient node/element handle or equivalent current-node evidence behind ZN-owned authority. Provider handles remain disposable execution resources; they must not become long-lived ZN identity.

## 5. User Browser Bridge provider proof remains verified and narrow

Commits:

```text
4f811ef49dea9c9d2ccc7cb436145eb9f2d925f3
test: prove real user browser UIA provider

4ef025bc2ef9ba5f67102cddfe863252393058b9
fix: define Windows enum callback type

2e5a328e35a75e65ed1c3cedfc7b79d8f5bdf3ee
fix: close browser proof store before cleanup
```

`tests/zn_agent/e2e/test_windows_interactive_user_browser_bridge.py` proves a narrow but real provider fact on the self-hosted interactive Windows runner:

- stable Edge/Chrome are discovered from the actual machine;
- the proof uses a temporary isolated `--user-data-dir`;
- no user profile, cookies, password store or authentication material is copied;
- `--force-renderer-accessibility` is deliberately not passed;
- a real focused HTML `<input>` is observed through resident Windows UIA Senses;
- foreground-window, focused automation-element and focused text-state evidence align;
- Edge exposes the HTML input as `UIA_EditControlTypeId` (`50004`), framework `Chrome`;
- Value Pattern and Text Pattern are available on the fixture;
- resident text-state exports only bounded text length + SHA-256 digest, not raw text/value/name;
- the proof performs no browser mutation.

This means the default Edge Windows accessibility provider is sufficient for that isolated focused-input sensing slice. It does **not** prove attachment to or control of the user's existing authenticated browser session.

## 6. Current browser product truth

Browser is not complete.

Verified/foundation slices now include:

- resident-owned browser session/permission/target/observation/action/authority/effect semantics;
- lazy resident ownership and shutdown cleanup of local managed browser;
- real local headless Chromium navigation with fresh authority and post-action observation;
- real local Chromium exact-DOM-id/main-frame target sensing with bounded privacy-safe evidence and freshness;
- browser network/origin/private-network boundaries for the current managed adapter;
- real Windows interactive Edge default-UIA provider sensing of a focused HTML input without forced renderer accessibility.

Still incomplete:

- exact-node continuity at the managed-browser mutation boundary;
- managed browser focus/click/type/select/check/keyboard actions;
- iframe/child-frame and generic accessibility target sensing;
- multi-tab/popup/frame lifecycle;
- headed managed-browser UX/evidence;
- screenshots/visual browser evidence integration;
- explicit downloads/uploads/file-picker authority;
- managed persistent profile policy and cleanup;
- cloud browser adapter;
- browser crash/health/recovery lifecycle;
- complete DNS-rebinding/network-sandbox hardening;
- formal release packaging of browser runtime;
- authenticated User Browser Bridge attachment/session/tab/permission/mutation lifecycle;
- extension/native messaging if real evidence shows it is needed;
- site/session browser permission UX;
- MFA/sensitive-field browser handoff.

Desktop text mutation remains limited to an already-focused empty native Win32 `Edit`. WPF and browser UIA current-text evidence are read-only sensing evidence, not modern/browser mutation authority.

## 7. Other product debts

M8 Windows x64 continuity remains **PARTIAL**. The repository has update/release machinery and packaged-runtime contracts, but complete install -> upgrade -> continuity -> rollback -> signing evidence is still required before treating Windows release continuity as complete.

M9 production hardening remains incomplete. Browser health/recovery, unified permissions/audit, broader crash recovery and packaging remain open product work.

Self-maintenance remains:

```text
SM0   VERIFIED foundation/evidence pipeline
SM1+  OPEN
```

The first self-maintenance stage must continue to preserve human approval for identity, long-term memory, credentials/permissions, updater/signing and other high-risk changes.

## 8. Development-history note

During this stage an empty root `noop` file was accidentally committed in:

```text
0347f30ef4934ffe2713595ba6c6e17c967e9372
noop
```

No force push, reset or history rewrite was used to hide it. The following normal fast-forward feature commit `1c37dc19` removes `noop` from the final tree. The net compare from the clean pre-feature baseline `23af35b7` to `1c37dc19` contains only the five intended browser implementation/test files. The accidental commit remains visible in history for auditability.

## 9. Next implementation order

The next real dependency is not generic click/type. It is mutation-safe exact-node continuity followed by one narrow action lifecycle.

Preferred order:

```text
1. bind a provider-local transient current node/element handle to fresh ZN target evidence
2. immediately revalidate the same current node at execution time
3. implement managed-browser FOCUS first
4. independently verify the postcondition from fresh current reality (for example activeElement identity)
5. add real Chromium proof
6. only then add CLICK, TYPE_TEXT and other actions one at a time
```

`FOCUS` is the preferred first mutation because its side effect is narrower than click and can be verified from a fresh focused-element postcondition. Do not expose a generic Playwright method surface and do not let provider handles become ZN identity.

In parallel, authenticated User Browser Bridge lifecycle, isolated parallel Work/Investigation, connector interoperability, scheduled/event-driven resident work, M8 Windows continuity and SM1+ remain open according to their respective dependency/risk boundaries.
