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

Latest verified implementation/test head for the managed-browser foundation:

```text
86753e29d318272970f258e3c1691312f3a0685c
test: reject unobserved browser target authority
```

Status: **VERIFIED FOUNDATION ON WINDOWS X64 NORMAL CI + REAL LOCAL HEADLESS CHROMIUM E2E**.

Exact-head normal workflow:

```text
run 32948299745
head 86753e29d318272970f258e3c1691312f3a0685c

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
Ran 500 tests in 654.485s
OK (skipped=5)
```

Dedicated real managed-browser workflow:

```text
run 32948299721
head 86753e29d318272970f258e3c1691312f3a0685c
job Windows local managed Chromium E2E
success
```

That workflow installs `znagent[browser]`, installs Playwright Chromium on the real Windows x64 runner, passes the browser contract/lifecycle tests and passes the real local Chromium navigation E2E.

Existing desktop interaction regression evidence after browser ownership:

```text
run 32947957948
head 4dd03d2ee79d8a078ea0fa8cf18217b33c193891
Windows interactive computer-use E2E
success
```

The previous pointer/UIA, native Win32 text-entry and WPF current-text evidence therefore remained green after the resident began owning the lazy managed-browser resource.

## 2. Browser is a first-class product subsystem

`ZN.md` requires two complementary planes:

```text
Resident Managed Browser
+ User Browser Bridge
= complete browser capability
```

The managed plane serves ZN's own web work. The user-browser plane serves task reality that already exists inside the user's authenticated Edge/Chrome session. Neither replaces the other.

Both must converge on ZN-owned session/target/observation/action/authority/effect/permission semantics. Browser engines, cloud services, extensions and desktop providers remain replaceable resources rather than owners of resident intent, identity, memory or completion truth.

The managed browser must not solve user authentication by silently copying cookies, password stores, profile databases or other browser credentials. The user-browser bridge must preserve the user's browser/OS security boundary and require explicit permission for richer integrations.

## 3. Managed-browser foundation now implemented

Key commits:

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
```

### 3.1 ZN-owned browser semantics

`runtime/python/zn_agent/core/browser.py` defines resident-owned concepts for:

- managed vs user browser plane;
- browser session identity and profile scope;
- permission context and allowed-origin scope;
- page/element/accessibility/visual/desktop targets;
- observations;
- typed actions;
- action authority bound to fresh observation/session/page/target evidence;
- effect evidence whose success/failure semantics are explicit;
- replaceable browser-adapter protocol.

Managed sessions cannot claim a `user_existing` profile, and user-browser sessions cannot masquerade as ephemeral managed sessions.

Targeted actions fail closed if the current observation has no target or if target ID, kind or frame identity drifted before authority formation.

### 3.2 Local Playwright Chromium adapter

`runtime/python/zn_agent/core/managed_browser.py` provides the first adapter: `PlaywrightManagedBrowser`.

Current verified behavior:

- Playwright is lazy and optional; zero-model resident construction does not import/start Chromium;
- managed sessions use an ephemeral Chromium context;
- downloads are disabled and service workers are blocked in this first slice;
- HTTP(S) requests pass through ZN URL/private-network/origin policy;
- WebSocket routes use the same ZN policy where the installed Playwright API supports routing;
- observation exports bounded URL/title/load state/viewport/provider/session metadata, not uncontrolled raw HTML/page dumps;
- only `NAVIGATE` is implemented as a browser mutation;
- navigation requires matching permission + fresh authority;
- navigation success is formed only after a fresh observed current page and safe final URL;
- optional exact expected-URL postcondition can contradict success;
- other browser action kinds return explicit failure evidence instead of silently dispatching.

The optional runtime dependency is currently:

```text
znagent[browser] -> playwright==1.62.0
```

This optional dependency and CI-installed Chromium are not yet formal proof that the packaged ZN desktop release ships a browser runtime. Release bundling remains open.

### 3.3 Real local Chromium proof

`tests/zn_agent/e2e/test_windows_managed_browser.py` starts a local HTTP fixture and a real headless Chromium session, then proves:

- a real ephemeral managed browser session exists;
- navigation from `about:blank` to the exact local origin succeeds only through a fresh ZN action authority;
- current URL/title/load state are re-observed after navigation;
- a second navigation requires a new current observation/authority;
- raw page text/content/HTML are not exported in observation metadata;
- the link-local metadata endpoint remains blocked even when the test explicitly permits normal private-network access.

Dedicated workflow `.github/workflows/zn-managed-browser-e2e.yml` installs the optional browser runtime and real Chromium before running browser contracts and the real E2E.

## 4. Resident ownership and zero-model continuity

The active runtime remains `FocusedModernTextResidentRuntime`, and now owns:

```text
automation_text_state
managed_browser
```

`managed_browser` is lazy. Constructing or booting the resident does not open a browser and does not require Playwright in the base runtime install. Exact-head normal CI independently proves the zero-model resident still boots without the browser optional dependency.

This is intentionally a transitional composition point. The feature-specific resident inheritance chain is now a known architecture debt: future product growth should converge on stable product-resident composition rather than creating a new resident subclass name for each organ/capability.

## 5. Interactive Windows reliability fix

Commit:

```text
921c979b6de14e4c24d506827dca291b0092594f
ci: cover modern text interactive changes
```

The interactive E2E workflow path filters now include both:

```text
runtime/python/zn_agent/core/automation_text_state_sense.py
runtime/python/zn_agent/core/focused_modern_text_resident.py
```

Future changes to those product files therefore cannot silently bypass the real interactive lane merely because the workflow path filter was stale.

## 6. Product completeness ledger

Commit:

```text
77b524e799af8f1f14a08cff14f7f98dd45992e9
docs: add product capability map
```

`docs/ZN-PRODUCT-CAPABILITY-MAP.md` now tracks product needs separately from implementation/test status across:

- Self/continuity;
- memory/learning/competence;
- files/workspace/terminal/code;
- web/browser;
- desktop computer use;
- connectors/MCP;
- communication/personal work;
- long-running work/automation/recovery;
- parallel Work/Investigation;
- security/permission/trust;
- product UI/observability;
- self-maintenance/release.

Mainstream agent capabilities are treated as evidence of useful user needs, then mapped into ZN-owned organs/resources/lifecycles. They are not copied as an LLM-planner/tool control plane.

## 7. What remains incomplete

The managed browser is a verified **foundation**, not a complete browser product.

Still open:

- headed managed-browser UX/evidence;
- bounded DOM/accessibility target sensing;
- click/focus/type/select/check/keyboard browser actions;
- multi-tab, popup, frame and stale-page lifecycle;
- screenshots/visual browser evidence integration;
- explicit download/upload/file-picker authority;
- managed persistent profile policy and cleanup;
- cloud browser adapter;
- browser health/crash/recovery lifecycle;
- complete DNS-rebinding/network-sandbox hardening;
- formal release packaging of Playwright/Chromium;
- the User Browser Bridge;
- actual authenticated Edge/Chrome session integration;
- browser companion extension/native messaging if real evidence shows it is needed;
- per-site/session browser permission UX;
- sensitive/MFA browser handoff lifecycle.

Desktop text mutation remains limited to an already-focused empty native Win32 `Edit`. WPF text-state evidence remains read-only and is not modern/browser mutation authority.

## 8. Other product debts

M8 remains **PARTIAL** for Windows x64:

1. clean Windows install/login evidence;
2. installed Windows N->N+1 continuity evidence;
3. rollback validation across a real Windows version transition;
4. applicable secure Windows signing evidence.

SM0 remains complete; SM1+ remains open.

GitHub Actions JavaScript runtime deprecation warnings remain non-blocking tooling debt. Pillow `Image.getdata` deprecation remains non-blocking visual-code debt.

## 9. Next real targets

```text
1. preserve exact-head managed-browser + normal Windows CI evidence
2. investigate actual Edge/Chrome availability and UIA/accessibility behavior on the real interactive Windows runner
3. prove a focused real browser text field through resident Senses without inferring browser support from WPF
4. establish bounded managed-browser DOM/accessibility target identity before adding click/type mutation
5. converge managed-browser and user-browser paths on shared ZN-owned authority/effect semantics
6. design authenticated User Browser Bridge without copying user credentials/profile data
7. then advance isolated parallel Work/Investigation + checkpoints and MCP/connectors from the product capability map
8. keep M8 and SM1+ explicitly partial/open
9. leave main untouched through ordinary development
```
