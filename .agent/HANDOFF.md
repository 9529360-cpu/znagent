# ZN Agent Handoff

Updated: 2026-08-26

## Current goal

Browser is now a first-class ZN product subsystem with two required planes:

```text
Resident Managed Browser
+ User Browser Bridge
= complete browser capability
```

The first local managed-browser foundation is implemented and verified. The next real browser target is the user's actual Edge/Chrome environment: prove what the Windows provider exposes, then build the User Browser Bridge from real evidence without copying authentication/profile data.

The broader product backlog is tracked in `docs/ZN-PRODUCT-CAPABILITY-MAP.md` so future maintainers, including a separate Desktop Codex session, can own different capability domains without inventing a second product/control plane.

Core principle:

> **ZN uses models. Models do not own ZN.**

## Branch / HEAD

- fixed development branch: `dev/zn-agent`
- canonical source/release branch: `main`
- latest fully verified implementation/test head: `86753e29d318272970f258e3c1691312f3a0685c`
- status ledger commit for this handoff: `d4db4c5160fbad6d5bef79a35e1719c4ad308f3c`
- canonical `main`: `8234a835dea604783cea0bd9d28a40de654ec03d`
- PR #6 remains draft/open/unmerged, base `main`, head `dev/zn-agent`
- `main` was not modified
- no force push or history rewrite was used

A HANDOFF commit cannot contain its own resulting SHA. Re-read resulting `dev/zn-agent` HEAD and require its exact-head normal Windows CI before calling this documentation handoff fully synchronized.

## Completed in current stage

### 1. Product browser architecture corrected

`ZN.md` now treats browser as two complementary Body/Senses planes rather than a narrow UIA test target.

Managed browser is for ZN's own autonomous web work. User Browser Bridge is for reality already present in the user's authenticated browser. Neither may become ZN identity/control plane, and managed browsing must not copy user cookies/password/profile databases as a shortcut.

### 2. Product capability map added

Commit:

```text
77b524e799af8f1f14a08cff14f7f98dd45992e9
docs: add product capability map
```

`docs/ZN-PRODUCT-CAPABILITY-MAP.md` distinguishes product need, ZN owner, current status and open work across continuity, memory, code/workspace, browser, desktop computer-use, MCP/connectors, communications, automation, parallel Work/Investigation, permissions, UI/observability, release and self-maintenance.

Mainstream agent capabilities are inputs to product research, not a blueprint for an LLM-agent control plane.

### 3. Interactive CI trigger gap fixed

Commit:

```text
921c979b6de14e4c24d506827dca291b0092594f
ci: cover modern text interactive changes
```

The real Windows interactive lane now watches `automation_text_state_sense.py` and `focused_modern_text_resident.py`, closing the known path-filter reliability gap.

### 4. ZN-owned browser contracts implemented

Commits:

```text
0ffe253fa57f1da003a28cdec200d304a7bbe71f
feat: add ZN browser session contracts

20dddad4bfff1ba2fdce6fec8adb704851ae8e49
test: guard ZN browser ownership contracts
```

`runtime/python/zn_agent/core/browser.py` owns browser plane/session/profile/permission/target/observation/action/authority/effect semantics plus a replaceable adapter protocol.

Key fail-closed rules:

- managed sessions cannot claim the user's existing profile;
- user sessions cannot masquerade as ephemeral managed sessions;
- allowed origins normalize before authority use;
- malformed/duplicate origins fail closed;
- action authority binds to exact current session/page observation;
- targeted actions require a current target observation;
- target ID/kind/frame drift blocks authority;
- success/failure effect evidence is unambiguous.

### 5. Local managed Chromium adapter implemented

Commits:

```text
25da7bb75ab4e46a7f7feef1216eff8e09e29da1
feat: add local managed browser adapter

3df714e7169dc9c3ea308fc2d12378862a2947bf
test: guard managed browser lifecycle

223352d78a0eb28c7e5536b0ae00ebd630748909
build: add managed browser optional runtime
```

`PlaywrightManagedBrowser` currently provides:

- optional/lazy `playwright==1.62.0` Chromium adapter;
- ephemeral managed context;
- no browser startup during zero-model resident boot;
- downloads disabled and service workers blocked in this slice;
- HTTP(S) and routed WebSocket endpoints checked through ZN URL/private-network/origin policy;
- bounded URL/title/load-state/viewport metadata observations rather than raw page dumps;
- `NAVIGATE` only;
- fresh authority before navigation;
- fresh observed safe current URL after navigation before success;
- explicit failure evidence for unimplemented actions.

Downloads/uploads are intentionally refused until file authority is designed.

### 6. Managed browser is resident-owned but lazy

Commits:

```text
4dd03d2ee79d8a078ea0fa8cf18217b33c193891
feat: make managed browser resident-owned

3f2a2def735e126184a88a8a4bef352521e762e6
test: guard managed browser resident ownership
```

Active `FocusedModernTextResidentRuntime` owns `managed_browser`, but constructing the resident does not start Chromium and does not require the optional browser package.

Known architecture debt: the feature-specific resident subclass chain should converge on stable product-resident composition. Do not create a new resident subclass name for every future organ/capability.

### 7. Real local Chromium E2E added

Commits:

```text
ed7a6dcdb1ef057210e2ed1ed88be525172c0a60
test: prove local managed Chromium navigation

9b60e9621c1099dce7a10c776c37e77ee84f8367
ci: cover resident managed browser ownership
```

Dedicated workflow:

```text
.github/workflows/zn-managed-browser-e2e.yml
```

It installs `znagent[browser]`, installs real Playwright Chromium on the self-hosted Windows x64 runner, runs browser contracts/lifecycle tests, then runs the real local Chromium E2E.

The E2E proves an ephemeral headless Chromium session, two separately authorized local navigations with fresh observations, bounded current URL/title/load-state evidence, no raw page-content metadata, and continued blocking of the link-local metadata endpoint even when ordinary private-network access is explicitly enabled for the local fixture.

### 8. Browser authority was tightened before mutation work

Commits:

```text
cc8513db404c2507c11077b7d3e7e754ca8eb450
fix: require observed browser target authority

86753e29d318272970f258e3c1691312f3a0685c
test: reject unobserved browser target authority
```

A future click/type cannot form authority from a target that is absent from current observation or has changed target kind/frame identity.

## Real verification

### Exact-head normal Windows CI

```text
run 32948299745
head 86753e29d318272970f258e3c1691312f3a0685c

Electron / TypeScript / Windows   success
ZN Source Boundary / Windows      success
ZN Kernel / Python / Windows      success
Publish Windows CI statuses       success

CPython 3.12.13
formal runtime install success
zero-model resident boot success
resident core compile success
Ran 500 tests in 654.485s
OK (skipped=5)
```

### Exact-head real managed Chromium

```text
run 32948299721
head 86753e29d318272970f258e3c1691312f3a0685c
Windows local managed Chromium E2E   success
```

All substantive steps succeeded: isolated browser runtime, Playwright Chromium install, browser contract tests, real local Chromium E2E.

### Existing real desktop interaction regression

```text
run 32947957948
head 4dd03d2ee79d8a078ea0fa8cf18217b33c193891
Windows interactive computer-use E2E   success
```

Existing pointer/UIA, native Win32 text entry and WPF current-text behavior remained green after the resident began owning the lazy browser resource.

## Current implementation truth

Verified foundation now exists for:

- resident-owned browser semantic contracts;
- lazy resident ownership of a managed browser resource;
- real local headless Chromium session;
- safe managed navigation with fresh authority and observed postcondition;
- origin/private-network/metadata safety on this path;
- browser-specific CI and real E2E.

Still incomplete:

- headed browser product path;
- DOM/accessibility target sensing;
- browser click/focus/type/select/check/keyboard actions;
- multi-tab/popup/frame lifecycle;
- downloads/uploads/file picker authority;
- browser screenshot/visual evidence integration;
- managed persistent profile policy;
- cloud browser provider;
- full browser health/crash recovery;
- complete DNS-rebinding/network sandbox;
- formal release packaging of Chromium/Playwright;
- User Browser Bridge;
- authenticated existing Edge/Chrome session control;
- extension/native messaging bridge;
- browser permission-management UX;
- MFA/sensitive-field handoff.

Do not report the browser product complete.

## Task queue

### P0 - final docs exact-head CI
Status: **REQUIRED**

Re-read the resulting HANDOFF head and its normal Windows CI before calling this stage fully synchronized.

### P1 - User Browser Bridge provider proof
Status: **NEXT / OPEN**

On the actual Windows interactive runner:

1. discover actual Edge/Chrome availability;
2. launch a controlled real browser fixture without touching the user's real profile;
3. inspect focused HTML input through resident UIA/current-text Senses;
4. record actual RuntimeId/control type/capabilities/current-state evidence;
5. if default renderer accessibility is insufficient, investigate the real reason before adding special flags;
6. do not infer support from WPF and do not copy authentication material.

This first provider proof is not yet authenticated-user-session support; it establishes which desktop bridge is technically real.

### P2 - managed browser target sensing
Status: **OPEN**

Add bounded DOM/accessibility target identity and freshness. Only after target authority is real may click/focus/type be introduced.

### P3 - managed browser actions
Status: **OPEN**

Add one action lifecycle at a time with explicit permission and independent effect evidence. Do not expose all Playwright methods as generic tools.

### P4 - isolated parallel Work / Investigation + checkpoints
Status: **OPEN / HIGH PRODUCT PRIORITY**

This is a good separable domain for another maintainer/Desktop Codex later. It must be resident-owned work isolation, not multiple autonomous product identities.

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
- one real navigation E2E is foundation evidence, not browser completion.
- managed/user browser profiles must remain distinct.
- do not copy browser credentials/profile state as login integration.
- downloads/uploads remain disabled until file authority exists.
- current browser network policy is not a complete network sandbox/DNS-rebinding solution.
- browser mutation beyond navigation is still unavailable.
- current desktop text mutation remains native-empty-Edit-only.
- M8 remains partial; SM1+ remains open.

## Related files

```text
ZN.md
docs/ZN-PRODUCT-CAPABILITY-MAP.md
docs/ZN-IMPLEMENTATION-STATUS.md
.agent/HANDOFF.md
runtime/python/pyproject.toml
runtime/python/zn_agent/core/browser.py
runtime/python/zn_agent/core/managed_browser.py
runtime/python/zn_agent/core/focused_modern_text_resident.py
runtime/python/zn_agent/core/provider_bridge.py
runtime/python/zn_agent/core/url_safety.py
tests/zn_agent/core/test_browser_contract.py
tests/zn_agent/core/test_managed_browser.py
tests/zn_agent/core/test_modern_text_resident_ownership.py
tests/zn_agent/e2e/test_windows_managed_browser.py
.github/workflows/zn-managed-browser-e2e.yml
.github/workflows/zn-windows-interactive-e2e.yml
```

## Next real target

Close final docs-head CI, then start real Edge/Chrome provider/UIA evidence for the User Browser Bridge while preserving the verified managed-browser foundation and keeping `main` untouched.
