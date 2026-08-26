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

Latest implementation/test head before this status-document update:

```text
2e5a328e35a75e65ed1c3cedfc7b79d8f5bdf3ee
fix: close browser proof store before cleanup
```

Status: **VERIFIED MANAGED-BROWSER FOUNDATION + VERIFIED NARROW REAL EDGE UIA PROVIDER SENSING**.

Exact-head normal Windows x64 CI:

```text
run 32953911506
head 2e5a328e35a75e65ed1c3cedfc7b79d8f5bdf3ee

ZN Source Boundary / Windows      success
ZN Kernel / Python / Windows      success
Electron / TypeScript / Windows   success
Publish Windows CI statuses       success
```

The same head also has exact real interactive Windows evidence:

```text
run 32953911536
head 2e5a328e35a75e65ed1c3cedfc7b79d8f5bdf3ee
ZN Windows Interactive Desktop E2E   success
```

The interactive lane ran the existing pointer/UIA, native Win32 text-entry and WPF current-text tests plus the new real browser provider proof.

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

Key commits include:

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
- observation exports bounded URL/title/load-state/viewport/provider metadata, not uncontrolled raw page dumps;
- only `NAVIGATE` is implemented as browser mutation;
- navigation requires current observation + permission + fresh authority;
- success is formed only from fresh post-navigation observation and safe final URL;
- unimplemented actions return explicit failure evidence.

Resident service shutdown now closes the resident-owned managed-browser resource rather than relying on process teardown.

Dedicated managed Chromium proof remains valid:

```text
run 32948299721
head 86753e29d318272970f258e3c1691312f3a0685c
Windows local managed Chromium E2E   success
```

Formal release packaging of Playwright/Chromium is still open.

## 4. User Browser Bridge provider proof now exists

Commits:

```text
4f811ef49dea9c9d2ccc7cb436145eb9f2d925f3
test: prove real user browser UIA provider

4ef025bc2ef9ba5f67102cddfe863252393058b9
fix: define Windows enum callback type

2e5a328e35a75e65ed1c3cedfc7b79d8f5bdf3ee
fix: close browser proof store before cleanup
```

`tests/zn_agent/e2e/test_windows_interactive_user_browser_bridge.py` now proves a narrow but real provider fact on the self-hosted interactive Windows runner:

- stable Edge and Chrome are discovered from the actual machine;
- the proof selects installed Edge when available;
- the browser is launched with a temporary isolated `--user-data-dir`;
- no user profile, cookies, password store or authentication material is copied;
- `--force-renderer-accessibility` is deliberately not passed;
- a real focused HTML `<input>` is observed through the resident's existing Windows UIA Senses;
- foreground window, focused automation element and focused text-state evidence are aligned;
- Edge exposed the HTML input as `UIA_EditControlTypeId` (`50004`), framework `Chrome`, with the fixture AutomationId;
- Value Pattern and Text Pattern were available and the Value was writable;
- resident text-state exported only bounded `text_length` + SHA-256 digest, not raw text/value/name;
- the test performs no browser mutation.

The first run proved the provider path but exposed a Windows test-cleanup bug because SQLite was still open when the temporary directory was removed. That test lifecycle was fixed; the exact-head interactive rerun `32953911536` then completed successfully.

This evidence means **the default Edge Windows accessibility provider is sufficient for this isolated focused-input sensing slice**. It does **not** prove that ZN can operate the user's existing authenticated session.

Not yet proven by this test:

- attaching to or controlling a user's already-running authenticated Edge/Chrome profile;
- cookies/login/session access;
- tabs, popups, iframes or stale-page lifecycle;
- browser click/focus/type mutation;
- extension/native-messaging integration;
- per-site/session permission UX;
- MFA or sensitive-field handoff.

## 5. Current browser target gap

The next managed-browser dependency is now explicit in the real call chain:

```text
PlaywrightManagedBrowser.observe()
-> _capture()
-> BrowserObservation(target=None)
```

`BrowserTarget` and freshness/authority contracts already exist, but the managed adapter still has no bounded DOM/accessibility target producer. Therefore click/type must remain unavailable.

The next implementation slice should establish a target observation API that:

- resolves one explicit page target rather than dumping uncontrolled page content;
- produces stable-enough ZN-owned target identity for the current observation;
- records frame identity and freshness;
- bounds role/name/selector hints and avoids secret/raw-page leakage;
- can be re-observed independently before mutation;
- fails closed when a target is absent, ambiguous, detached or changed.

Only after that evidence exists should narrow click/focus/type action lifecycles be added one at a time with independent effect verification.

## 6. Product completeness truth

Browser is not complete.

Verified/foundation slices now include:

- resident-owned browser contracts and authority/effect semantics;
- lazy resident ownership of managed browser;
- real local headless Chromium navigation;
- managed browser resource cleanup with resident service lifecycle;
- real Windows interactive Edge UIA focused-input sensing without forced renderer accessibility.

Still incomplete:

- headed managed-browser UX/evidence;
- bounded managed DOM/accessibility target sensing;
- managed browser click/focus/type/select/check/keyboard actions;
- multi-tab/popup/frame lifecycle;
- screenshots/visual browser evidence integration;
- explicit downloads/uploads/file-picker authority;
- managed persistent profile policy and cleanup;
- cloud browser adapter;
- browser crash/health/recovery lifecycle;
- complete DNS-rebinding/network-sandbox hardening;
- formal release packaging of browser runtime;
- authenticated User Browser Bridge lifecycle;
- extension/native messaging if real evidence shows it is needed;
- site/session browser permission UX;
- MFA/sensitive-field browser handoff.

Desktop text mutation remains limited to an already-focused empty native Win32 `Edit`. WPF and browser UIA current-text evidence are read-only sensing evidence, not modern/browser mutation authority.

## 7. Other product debts

M8 remains **PARTIAL** for Windows x64:

1. clean Windows install/login evidence;
2. installed Windows N->N+1 continuity evidence;
3. rollback validation across a real Windows version transition;
4. applicable secure Windows signing evidence.

SM0 remains complete; SM1+ remains open.

GitHub Actions JavaScript runtime deprecation warnings and Pillow `Image.getdata` deprecation remain non-blocking tooling debt.

## 8. Next real targets

```text
1. keep exact-head normal Windows CI and real interactive browser sensing trustworthy
2. add bounded managed-browser DOM/accessibility target sensing and freshness
3. prove target identity in a real local Chromium E2E before adding mutation
4. add one narrow browser action at a time with permission + authority + independent effect evidence
5. design authenticated User Browser Bridge from real provider evidence without copying credentials/profile data
6. converge managed-browser and user-browser paths on shared ZN-owned target/authority/effect semantics
7. then advance isolated parallel Work/Investigation + checkpoints and MCP/connectors from the product capability map
8. keep M8 and SM1+ explicitly partial/open
9. leave main untouched through ordinary development
```
