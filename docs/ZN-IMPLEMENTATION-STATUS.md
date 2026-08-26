# ZN implementation status

> Architecture contract: [`../ZN.md`](../ZN.md)
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

Latest fully verified implementation/test head for the current computer-use slice:

```text
1a1e4959ec07ac5d67e39033611b9931e705e80e
test: guard modern text Sense ownership
```

Status: **VERIFIED ON WINDOWS X64 CI AND REAL INTERACTIVE WINDOWS E2E**.

Exact-head normal workflow:

```text
run 32942313022
head 1a1e4959ec07ac5d67e39033611b9931e705e80e

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
Ran 482 tests in 594.172s
OK (skipped=5)
```

Relevant real interactive workflow:

```text
run 32942284572
head ba25ffa9846eeb3c79f41f66572f9c408d02304b
job Windows interactive computer-use E2E
Ran 3 tests in 8.008s
OK
```

The later documentation head `8d84181bc8a236559c25cb54f79682f42ab1b487` also completed exact-head normal Windows workflow `32943582668`; Kernel, Electron, Source Boundary and status publisher all succeeded.

## 2. Architecture correction: browser is a product subsystem

Architecture commit:

```text
4a0f95d03debe737078bbc3ea430daf5989bc73d
docs: define product browser architecture
```

`ZN.md` now explicitly defines browser capability as two first-class resident Body/Senses planes:

```text
Resident Managed Browser
+ User Browser Bridge
= complete browser capability
```

This corrects the earlier implementation-led framing where Chromium/browser work was treated mainly as the next UIA evidence target.

The product requirement is broader:

1. **Resident Managed Browser** — ZN needs its own locally usable browser for autonomous web work, with headless and headed modes where supported. A cloud browser may be an optional provider, not the sole foundation.
2. **User Browser Bridge** — ZN also needs to operate the user's existing real browser session when task reality depends on already-authenticated tabs, enterprise SSO, MFA state, local certificates, site grants, extensions or other user-only browser context.
3. These paths must share ZN-owned target/action/evidence/permission semantics but must not share credentials by copying browser profiles, cookies, password stores or authentication databases.
4. Existing user sessions should be used through bounded interaction/bridge mechanisms rather than forcing duplicate login into a second ZN profile whenever possible.
5. Search/extract APIs remain useful WebResources but are not a substitute for an interactive managed browser.
6. Passing a narrow browser/UIA test is evidence for one slice only, never proof that the browser product is complete.

Potential implementation mechanisms named by the architecture include a local Chromium-class managed browser, optional cloud browser providers, Windows UIA/accessibility, and an optional explicit-permission browser companion extension/native bridge for high-fidelity user-session semantics. Provider choices remain replaceable; ZN owns resident state, authority, privacy and completion semantics.

## 3. What browser capability exists today

### 3.1 Web search/extract resources exist

ZN has resident-owned WebResource adapters for web search/extract providers such as Tavily, Exa and Firecrawl. They are HTTP/API resources, not a browser runtime.

They do not currently provide a real browser session with tab/page lifecycle, DOM interaction, JavaScript application state, downloads/uploads, authenticated browser UI flows or browser-side postcondition evidence.

### 3.2 Electron includes Chromium only for ZN's desktop shell

The desktop uses Electron/Chromium to render ZN's own UI. The current Electron `BrowserWindow` loads the local ZN shell and routes external navigation out to the system browser. It is not a resident managed-browser implementation.

### 3.3 No resident managed browser is implemented yet

The Python runtime currently has no Playwright/Selenium/Puppeteer-equivalent managed-browser dependency or ZN-owned browser session/action lifecycle.

Therefore the following remain **NOT IMPLEMENTED**:

- local headless browser owned by the resident;
- local headed managed-browser mode;
- resident browser tab/page/session lifecycle;
- DOM/action/evidence contracts for managed pages;
- managed downloads/uploads/file picker lifecycle;
- managed browser profile persistence/cleanup policy;
- optional cloud browser provider integration;
- managed-browser crash/recovery/health evidence.

### 3.4 No user browser bridge is implemented yet

The current Windows UIA work provides narrow generic desktop/browser-adjacent sensing primitives, but there is no product-grade browser-session bridge.

Therefore the following remain **NOT IMPLEMENTED**:

- explicit integration with the user's existing authenticated Edge/Chrome session;
- browser companion extension;
- native-messaging or equivalent high-fidelity local page bridge;
- per-site/session browser permissions;
- browser-specific DOM/accessibility target identity shared with desktop evidence;
- popup/new-tab/download/file-picker integration for user sessions;
- explicit MFA/user-presence browser handoff;
- browser-specific privacy policy enforcement beyond the current narrow focused-text Sense.

## 4. Existing computer-use evidence remains valid but narrow

The active product runtime is `FocusedModernTextResidentRuntime`, which owns the existing pointer/foreground/UIA/native text Senses and a read-only `NativeFocusedAutomationTextSense`.

Existing mutation remains limited to an already-focused empty native Win32 `Edit`. The modern text Sense is not mutation authority.

The real WPF E2E proves privacy-safe current text length + SHA-256 for one focused non-native WPF TextBox without exporting raw text. It does **not** prove Chromium/browser integration, browser DOM semantics, authenticated browser session control or modern-widget mutation.

## 5. Product-level browser requirements now tracked explicitly

The target browser subsystem must eventually cover, with real tests and provider evidence:

- local-first autonomous browsing;
- headless/headed managed mode;
- optional cloud capacity without cloud lock-in;
- existing authenticated user-browser sessions without duplicate login where possible;
- no hidden copying of cookies/passwords/profile databases;
- shared ZN-owned BrowserTarget/Observation/Action/Authority/EffectEvidence/Session/Permission semantics;
- stale-target rejection and post-action verification;
- browser navigation, redirects, tabs/popups and crashes;
- downloads/uploads and explicit file authority;
- screenshots/DOM/accessibility evidence with privacy boundaries;
- sensitive/password/payment/recovery field handling;
- explicit MFA/user-presence handoff;
- bounded managed-profile persistence and cleanup;
- observable browser provider/session health;
- real managed-browser E2E;
- real user-browser integration E2E.

These are product requirements, not claims of current implementation.

## 6. Repository source boundary / desktop / release

The previous verified Windows CI remains green. No source-boundary scanner exemption, product ownership rule, desktop control plane, runtime staging, update or release contract was weakened.

M8 remains **PARTIAL**. Still open for Windows x64:

1. clean Windows install/login evidence;
2. installed Windows N->N+1 continuity evidence;
3. rollback validation across a real Windows version transition;
4. applicable secure Windows signing evidence.

## 7. Self-maintenance

SM0 remains complete. SM1+ remains open. No self-maintenance architecture changed in this browser-contract correction.

## 8. Current known debts / boundaries

- resident managed browser: not implemented;
- user existing-session browser bridge: not implemented;
- Chromium/browser provider behavior through Windows UIA: not yet proven;
- current mutation remains native-empty-Edit-only;
- replacement/editing, navigation keys and shortcuts remain open;
- broader real-application interactive coverage remains open;
- M8 Windows install/upgrade/rollback/signing remains partial;
- SM1+ remains open;
- GitHub Actions JavaScript runtime deprecation warnings remain non-blocking tooling debt;
- Pillow `Image.getdata` deprecation warning remains non-blocking visual-code debt.

## 9. Next real targets

```text
1. keep the product-grade dual-plane browser contract authoritative
2. fix CI coverage so changes to the new modern text product files always trigger the interactive Windows lane
3. define the smallest ZN-owned managed-browser interfaces and session/evidence lifecycle before choosing a provider implementation
4. establish a local Chromium-class managed-browser path with real headless E2E, keeping cloud providers optional
5. independently investigate the real Windows user's Edge/Chrome provider/UIA behavior
6. design user-session bridging so authenticated state remains in the user's browser security boundary rather than being copied into ZN
7. add browser companion/native bridge only behind explicit permission if real evidence shows it is needed for semantic fidelity
8. preserve common browser action/evidence/privacy semantics across managed-browser and user-browser paths
9. do not widen modern browser mutation until target identity, current state and post-action evidence are independently proven
10. keep M8 and SM1+ explicitly partial/open and leave main untouched through ordinary development
```
