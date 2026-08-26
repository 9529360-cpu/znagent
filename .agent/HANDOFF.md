# ZN Agent Handoff

Updated: 2026-08-26

## Current goal

Browser work is now treated as a product subsystem, not a narrow P3 test target. ZN must eventually have both:

```text
Resident Managed Browser
+ User Browser Bridge
= complete browser capability
```

The managed-browser plane serves ZN's own autonomous web work with local headless/headed browsing and optional cloud providers. The user-browser plane serves reality that already exists in the user's authenticated Edge/Chrome session without forcing duplicate login or copying cookies/password/profile databases into ZN.

Core principle:

> **ZN uses models. Models do not own ZN.**

## Branch / HEAD

- fixed development branch: `dev/zn-agent`
- canonical source/release branch: `main`
- latest verified implementation/test head: `1a1e4959ec07ac5d67e39033611b9931e705e80e`
- previous synchronized documentation head: `8d84181bc8a236559c25cb54f79682f42ab1b487`
- architecture correction: `4a0f95d03debe737078bbc3ea430daf5989bc73d`
- browser status correction: `2c33e840420e422a24c5b7344892125c826619c4`
- canonical `main`: `8234a835dea604783cea0bd9d28a40de654ec03d`
- PR #6 remains draft/open/unmerged, base `main`, head `dev/zn-agent`
- `main` was not modified
- no force push or history rewrite was used

Re-read the resulting dev HEAD and require its exact-head Windows CI before calling this documentation handoff synchronized.

## Real verified evidence retained

### Normal Windows CI

Implementation/test head:

```text
run 32942313022
head 1a1e4959ec07ac5d67e39033611b9931e705e80e
Electron / TypeScript / Windows   success
ZN Source Boundary / Windows      success
ZN Kernel / Python / Windows      success
Publish Windows CI statuses       success
Ran 482 tests in 594.172s
OK (skipped=5)
```

Previous docs head:

```text
run 32943582668
head 8d84181bc8a236559c25cb54f79682f42ab1b487
Kernel          success
Electron        success
Source Boundary success
Status publish  success
```

### Interactive Windows E2E

```text
run 32942284572
head ba25ffa9846eeb3c79f41f66572f9c408d02304b
Ran 3 tests in 8.008s
OK
```

That real input-desktop run proves pointer/UIA focus, native Win32 Edit Unicode text entry, and privacy-safe read-only current-text digest evidence for a non-native WPF TextBox.

It does not prove browser product capability.

## Architecture correction completed

Commit:

```text
4a0f95d03debe737078bbc3ea430daf5989bc73d
docs: define product browser architecture
```

`ZN.md` now requires two first-class browser planes.

### Resident Managed Browser

Product intent:

- local-first Chromium-class browser resource;
- headless and headed modes where supported;
- optional remote/cloud provider, never mandatory for basic resident web ability;
- ZN-owned page/tab/session/action/evidence lifecycle;
- DOM/accessibility/page-state sensing;
- screenshots/visual evidence where needed;
- navigation/click/focus/form interaction;
- bounded downloads/uploads/file authority;
- profile persistence/cleanup policy;
- crash/recovery/provider-health evidence;
- post-action verification and stale-target rejection.

Search/extract APIs remain complementary WebResources, not substitutes for a real browser.

### User Browser Bridge

Product intent:

- use task reality already present in the user's authenticated browser;
- avoid forcing duplicate login into a second ZN-managed profile;
- preserve browser/OS authentication boundaries;
- do not silently copy cookies, passwords, browser databases or profile directories;
- use bounded mechanisms such as Windows UIA/accessibility/desktop evidence and, if justified, an explicit-permission browser companion extension/native bridge;
- preserve sensitive-field, MFA/user-presence and per-site/session permission boundaries.

### Shared semantics

Both planes should converge on ZN-owned concepts such as:

```text
BrowserTarget
BrowserObservation
BrowserAction
BrowserActionAuthority
BrowserEffectEvidence
BrowserSessionIdentity
BrowserPermissionContext
```

Providers do not own intent, permission, memory or completion truth.

## Current implementation truth

Implemented today:

- WebResource search/extract providers;
- Electron Chromium only as the ZN desktop shell renderer;
- generic Windows pointer/foreground/UIA Senses;
- narrow native Win32 Edit mutation;
- privacy-safe focused modern-text digest Sense;
- real WPF current-state E2E.

Not implemented today:

- resident managed browser;
- local Playwright/Selenium/Puppeteer-equivalent browser lifecycle;
- managed headless/headed browser E2E;
- cloud browser provider integration;
- user existing-session Edge/Chrome bridge;
- browser companion extension/native messaging bridge;
- browser-specific shared target/action/evidence layer;
- popup/tab/download/upload/MFA browser lifecycle;
- real browser authenticated-session E2E.

Do not report any of these as complete.

## Reliability issue already discovered

`.github/workflows/zn-windows-interactive-e2e.yml` path filters currently do not include:

```text
runtime/python/zn_agent/core/automation_text_state_sense.py
runtime/python/zn_agent/core/focused_modern_text_resident.py
```

A future change only to those product files could skip the real interactive lane. Fix this before relying on the next browser/UIA result.

## Task queue

### P0 - close exact-head documentation CI
Status: **REQUIRED**

Re-read the new HANDOFF resulting HEAD and its normal Windows CI.

### P1 - interactive CI path coverage
Status: **PENDING / RELIABILITY BUG KNOWN**

Add the two modern-text product files to the interactive workflow path filters and verify both normal + interactive CI.

### P2 - managed-browser foundation
Status: **PENDING / PRODUCT REQUIREMENT**

Define the smallest ZN-owned browser interfaces/session/evidence lifecycle first, then establish a local Chromium-class headless path with real E2E. Cloud remains optional.

### P3 - user-browser bridge evidence
Status: **PENDING / PRODUCT REQUIREMENT**

Investigate actual Edge/Chrome availability and UIA provider behavior on the real interactive Windows runner. Then determine whether UIA alone is sufficient or an explicit browser companion/native bridge is required for semantic fidelity.

Do not extract/copy authentication material as a shortcut.

### P4 - browser mutation/actions
Status: **PENDING**

Do not widen modern browser mutation until target identity, current state, permission and post-action evidence are independently proven.

### P5 - M8 Windows continuity / rollback / signing
Status: **PENDING / PARTIAL**

### P6 - SM1+ self-maintenance
Status: **PENDING**

## Risks / boundaries

- `main` remains untouched through ordinary development.
- No force push/history rewrite.
- Passing a narrow test is not product completion.
- Managed and user browser sessions serve different realities and neither replaces the other.
- Do not copy user browser credentials/profile state into the managed browser.
- Password/payment/recovery-code content must not become ordinary observation or memory.
- Browser providers are replaceable resources; ZN owns resident semantics.
- Current text mutation remains limited to an already-focused empty native Win32 `Edit`.
- WPF evidence is not Chromium/browser evidence.
- M8 remains partial and SM1+ remains open.

## Next real target

1. close exact-head docs/HANDOFF CI;
2. fix interactive workflow path coverage;
3. define the ZN-owned browser action/evidence/session contract;
4. implement and verify the first local managed-browser headless slice;
5. independently prove real user Edge/Chrome integration behavior on Windows;
6. choose any extension/native bridge only from real evidence, behind explicit permission;
7. keep both browser planes converging on the same ZN-owned semantics;
8. keep `main` untouched.
