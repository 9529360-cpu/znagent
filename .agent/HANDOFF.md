# ZN Agent Handoff

Updated: 2026-08-26

## Current goal

Browser remains a two-plane ZN subsystem:

```text
Resident Managed Browser
+ User Browser Bridge
= complete browser capability
```

The managed-browser foundation is implemented and verified. A real Windows interactive Edge provider proof now also exists for a narrow User Browser Bridge sensing slice. The next real target is bounded managed-browser DOM/accessibility target sensing and freshness; browser mutation must remain blocked until a current ZN-owned target observation can support authority and independent effect verification.

Core principle:

> **ZN uses models. Models do not own ZN.**

Current maintainers/models are replaceable. Project development/release capability belongs to the repository and its automation. Codex is currently unavailable because its billing is exhausted; no current work should depend on delegating to it.

## Branch / HEAD

- fixed development branch: `dev/zn-agent`
- canonical source/release branch: `main`
- latest fully verified implementation/test head before this documentation commit: `2e5a328e35a75e65ed1c3cedfc7b79d8f5bdf3ee`
- canonical `main`: `8234a835dea604783cea0bd9d28a40de654ec03d`
- PR #6 remains open/unmerged, base `main`, head `dev/zn-agent`
- `main` was not modified
- no force push or history rewrite was used

A HANDOFF commit cannot contain its own resulting SHA. Re-read the resulting `dev/zn-agent` HEAD and require exact-head normal Windows CI before calling this documentation handoff fully synchronized.

## Completed in current stage

### 1. Restored the real post-HANDOFF repository state

The previous HANDOFF was stale. Two implementation commits existed after it:

```text
a06d85a726cf6cc0eeb4b6c4cad4618435df0ef1
fix: harden browser authority after independent review

a62cf5a6ff3b8bacf19d12cf0fe4dfba3e5a2f4d
fix: close managed browser with resident service
```

`a06d85a` had real interactive evidence. The ordinary CI for `a62cf5a` was cancelled by a later push, so it was not treated as exact-head green evidence.

### 2. Traced the real User Browser Bridge sensing call chain

Active resident ownership is:

```text
provider_bridge.build_resident_runtime()
-> FocusedModernTextResidentRuntime
-> foreground_window
-> automation_element = NativeAutomationElementSense
-> automation_text_state = NativeFocusedAutomationTextSense
-> managed_browser = PlaywrightManagedBrowser
```

The UIA Senses are resident-owned and bounded. `NativeAutomationElementSense` exports identity/capability metadata without raw value/name/text. `NativeFocusedAutomationTextSense` performs safety checks and exports only current text length + SHA-256 digest for the focused writable Edit.

### 3. Real installed Edge/Chrome provider proof added

Commits:

```text
4f811ef49dea9c9d2ccc7cb436145eb9f2d925f3
test: prove real user browser UIA provider

4ef025bc2ef9ba5f67102cddfe863252393058b9
fix: define Windows enum callback type

2e5a328e35a75e65ed1c3cedfc7b79d8f5bdf3ee
fix: close browser proof store before cleanup
```

New test:

```text
tests/zn_agent/e2e/test_windows_interactive_user_browser_bridge.py
```

The fixture:

- discovers installed stable Edge/Chrome on the actual self-hosted Windows runner;
- launches an installed browser against a local HTML fixture using a temporary isolated `--user-data-dir`;
- never reads/copies the user's real profile, cookies, password stores or authentication material;
- deliberately does not pass `--force-renderer-accessibility`;
- requires an unlocked input desktop;
- aligns resident foreground-window, focused UIA-element and current-text evidence;
- performs no browser mutation;
- cleans up only processes belonging to the isolated temporary profile.

Real provider evidence on the runner showed Edge (`msedge.exe`, UIA framework `Chrome`) exposing the focused HTML input as `UIA_EditControlTypeId` (`50004`) with fixture AutomationId `zn-user-browser-text-target`, Value Pattern available/writable and Text Pattern available. Current-text evidence was exported only as length + digest.

The first proof run reached and printed valid Edge UIA evidence but then failed cleanup because the temporary SQLite store was still open. `2e5a328e` fixed the test resource lifecycle; no product behavior was broadened.

### 4. Exact-head real interactive E2E is green

```text
run 32953911536
head 2e5a328e35a75e65ed1c3cedfc7b79d8f5bdf3ee
ZN Windows Interactive Desktop E2E   success
```

This run includes all existing interactive tests plus the new real Edge User Browser Bridge provider proof.

### 5. Exact-head normal Windows CI is green

```text
run 32953911506
head 2e5a328e35a75e65ed1c3cedfc7b79d8f5bdf3ee

ZN Source Boundary / Windows      success
ZN Kernel / Python / Windows      success
Electron / TypeScript / Windows   success
Publish Windows CI statuses       success
```

Kernel zero-model boot and compile succeeded; full working-tree core tests succeeded. Electron dependency install/audit/typecheck/bundle and desktop ownership/update/handoff tests succeeded.

## Current implementation truth

Verified/foundation browser slices now exist for:

- resident-owned browser session/permission/target/observation/action/authority/effect semantics;
- lazy resident ownership and shutdown cleanup of local managed browser;
- real local headless Chromium navigation with fresh authority and post-action observation;
- browser network/origin/private-network boundaries for the current managed adapter;
- real Windows interactive Edge default-UIA provider sensing of a focused HTML input without forced renderer accessibility.

Do not overstate this stage. The User Browser Bridge is **not** complete.

The real Edge proof does not prove:

- attaching to or operating the user's existing authenticated browser profile/session;
- cookies/login/session access;
- tabs/popups/frames lifecycle;
- browser click/focus/type mutation;
- extension/native messaging;
- site/session permission UX;
- MFA/sensitive-field handling.

## Real next dependency found in code

`BrowserTarget` and target freshness/authority contracts exist, but `PlaywrightManagedBrowser._capture()` still produces only page-level `BrowserObservation(target=None)`.

Therefore the next dependency is target sensing, not generic actions:

```text
PlaywrightManagedBrowser.observe()
-> _capture()
-> bounded DOM/accessibility target producer
-> BrowserObservation(target=current BrowserTarget)
-> fresh BrowserActionAuthority
-> only then narrow mutation
```

Target identity must remain ZN-owned evidence. A Playwright selector or locator handle must not become long-lived truth by itself.

## Task queue

### P0 - final documentation-head normal CI
Status: **REQUIRED AFTER THIS HANDOFF COMMIT**

Re-read final `dev/zn-agent` HEAD and require its exact-head normal Windows CI before calling repository state synchronized.

### P1 - managed-browser target sensing
Status: **NEXT / OPEN**

Implement a bounded explicit target observation slice that:

1. resolves one intended target rather than dumping arbitrary page content;
2. records ZN-owned target identity, target kind, frame identity and observation freshness;
3. bounds role/name/selector hints and avoids secret/raw-page leakage;
4. re-observes target state independently before authority/mutation;
5. fails closed for missing, ambiguous, detached or changed targets;
6. adds unit/contract tests and a real local Chromium E2E before any click/type implementation.

### P2 - managed-browser actions
Status: **OPEN / BLOCKED ON P1**

Add one action lifecycle at a time, starting with a narrow low-risk interaction. Require explicit permission, current target authority and independent effect evidence. Do not expose all Playwright methods as generic tools.

### P3 - authenticated User Browser Bridge lifecycle
Status: **FOUNDATION / OPEN**

Use the real Edge UIA provider result as one evidence input. Design attachment/session/tab/permission/mutation lifecycle for the user's existing browser without copying authentication/profile data. Add an extension/native-messaging bridge only if evidence shows it is needed.

### P4 - isolated parallel Work / Investigation + checkpoints
Status: **OPEN / HIGH PRODUCT PRIORITY**

Must be resident-owned work isolation, not multiple autonomous product identities. Do not make progress depend on Codex or any one model/provider.

### P5 - MCP/connectors / external systems
Status: **OPEN**

Treat MCP/connectors as bounded Body/Channel adapters behind ZN permission/evidence semantics.

### P6 - scheduled/event-driven resident work
Status: **OPEN**

Persist independently of any chat/model session.

### P7 - M8 Windows continuity / rollback / signing
Status: **PARTIAL**

### P8 - SM1+ self-maintenance
Status: **OPEN**

## Risks / boundaries

- `main` remains untouched through ordinary development.
- no force push/history rewrite.
- browser providers are replaceable resources; ZN owns resident semantics.
- real browser UIA sensing is not authenticated browser control.
- managed/user browser profiles must remain distinct.
- do not copy browser credentials/profile state as login integration.
- browser mutation beyond managed navigation is unavailable.
- downloads/uploads remain disabled until file authority exists.
- browser network policy is not yet a complete network sandbox/DNS-rebinding solution.
- current desktop text mutation remains native-empty-Edit-only.
- one self-hosted Windows runner means normal and interactive jobs can serialize; concurrency cancellation means only exact-head completed runs count.
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
runtime/python/zn_agent/core/focused_modern_text_resident.py
tests/zn_agent/core/test_browser_contract.py
tests/zn_agent/core/test_managed_browser.py
tests/zn_agent/e2e/test_windows_managed_browser.py
tests/zn_agent/e2e/test_windows_interactive_uia_text_capability.py
tests/zn_agent/e2e/test_windows_interactive_user_browser_bridge.py
.github/workflows/zn-managed-browser-e2e.yml
.github/workflows/zn-windows-interactive-e2e.yml
.github/workflows/zn-ci.yml
```

## Next real target

Finish exact-head normal CI for this documentation commit, then implement and prove bounded managed-browser target sensing/freshness before introducing any browser click/type mutation. Keep `main` untouched.
