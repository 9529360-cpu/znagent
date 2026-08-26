# ZN Agent Handoff

Updated: 2026-08-26

## Current goal

Develop ZN as a complete product-grade resident system while preserving the founding boundary:

> **ZN uses models. Models do not own ZN.**

Browser remains a two-plane ZN subsystem:

```text
Resident Managed Browser
+ User Browser Bridge
= complete browser capability
```

The managed plane now has verified narrow navigation, exact-DOM-id/main-frame target sensing, exact-node `FOCUS`, exact-node `CLICK` for explicit boolean `aria-pressed` transitions, exact-node `TYPE_TEXT` for an empty writable non-password textbox, and exact-node native `CHECK` + `UNCHECK`.

Do not optimize for feature count. New capabilities must remain resident-owned, permission-bound, independently verified against current reality, recoverable where applicable, and provider/model replaceable.

## Branch / repository truth

- fixed development branch: `dev/zn-agent`
- canonical source/release branch: `main`
- latest fully verified implementation/test head before this documentation commit: `73257f8c728778054faf74869243b356383fede1`
- implementation commit: `feat: add verified managed browser uncheck`
- canonical `main`: `8234a835dea604783cea0bd9d28a40de654ec03d`
- PR #6 remains draft/open/unmerged, base `main`, head `dev/zn-agent`
- `main` was not modified
- no force push or history rewrite was used

A HANDOFF commit cannot contain its own resulting SHA. Re-read the resulting `dev/zn-agent` HEAD and require exact-head normal Windows CI before calling this handoff fully synchronized.

## Completed in current stage

### 1. Previous CHECK documentation P0 was closed first

CHECK documentation head:

```text
abbea793359a032ded8f8d753ff0b4e2e8bc0a07
docs: record verified managed browser check
```

Exact-head normal run `32975379772` completed with Source Boundary, Kernel, Electron and status publisher all `success`. UNCHECK did not substitute for or cancel that P0.

### 2. UNCHECK real call chain was traced before editing

Existing ZN contracts already contained `BrowserActionKind.UNCHECK` and already mapped it to `allow_page_interaction`, so no new permission field or model-owned planner path was introduced.

The real implementation chain is:

```text
BrowserTargetQuery(DOM_ID, main frame)
-> PlaywrightManagedBrowser.observe_target()
-> bounded BrowserTarget + transient provider-local exact element handle
-> BrowserActionAuthority from the exact current observation
-> execution-time exact-node revalidation
-> native checkbox-state evidence
-> require connected enabled input[type=checkbox] + checked=true
-> BrowserActionKind.UNCHECK
-> provider uncheck()
-> fresh target acquisition
-> exact JS-node continuity
-> unchanged ZN target identity
-> fresh checked=false
-> BrowserEffectEvidence(postcondition="same_exact_target_unchecked")
```

CHECK remains a separate inverse lifecycle requiring fresh `checked=false` before provider `check()` and fresh `checked=true` after it.

### 3. Narrow managed-browser UNCHECK implemented

Implementation commit:

```text
73257f8c728778054faf74869243b356383fede1
feat: add verified managed browser uncheck
```

The commit changes only:

```text
runtime/python/zn_agent/core/managed_browser.py
tests/zn_agent/core/test_managed_browser_check.py
tests/zn_agent/e2e/test_windows_managed_browser.py
```

Safety/effect behavior:

- target must still be the exact current ZN target at execution time;
- provider independently proves a connected enabled native checkbox;
- already-unchecked state is refused before dispatch;
- provider `uncheck()` is the only dispatch for UNCHECK;
- provider return alone is never accepted as success;
- fresh post-state must prove the same exact JS node, same ZN target identity and `checked=false`;
- provider no-effect fails closed;
- same-shape replacement fails even if replacement state is false;
- provider exceptions remain failure evidence;
- CHECK and UNCHECK fake-provider tests prove they do not dispatch each other;
- unsupported checkbox state error text is now action-neutral rather than CHECK-specific;
- no generic Playwright action surface or ARIA-checkbox claim was added.

### 4. Exact-head dedicated real Chromium proof is green

```text
run 32979312465
head 73257f8c728778054faf74869243b356383fede1
Windows local managed Chromium E2E   success

62 browser/core tests   OK
2 real Chromium E2E     OK
```

The real Chromium fixture proves:

- native unchecked -> checked via CHECK;
- fresh same-target checked -> unchecked via UNCHECK;
- fresh `checked=false` is observed rather than inferred from provider return;
- same-shape replacement during UNCHECK is rejected;
- navigation, target sensing, FOCUS, verified aria-pressed CLICK, TYPE_TEXT, CHECK, privacy metadata and network-safety regressions remain green.

### 5. Exact-head interactive Windows regression is green

```text
run 32979312447
head 73257f8c728778054faf74869243b356383fede1
Windows interactive computer-use E2E   success
```

Existing real pointer/UIA, native Unicode text-entry, WPF UIA text-capability and isolated-profile installed-browser provider regressions remained green.

### 6. Exact-head normal Windows CI is green

```text
run 32979312548
head 73257f8c728778054faf74869243b356383fede1

ZN Source Boundary / Windows      success
ZN Kernel / Python / Windows      success
Electron / TypeScript / Windows   success
Publish Windows CI statuses       success
```

Kernel completed isolated runtime setup, zero-model resident boot, resident core compilation and the full core suite. Source Boundary independently verified the active tree remains ZN-only.

## Current implementation truth

Verified/foundation browser slices now exist for:

- resident-owned browser session/permission/query/target/observation/action/authority/effect semantics;
- resident ownership/shutdown of local managed Chromium;
- managed navigation with fresh observed result;
- bounded exact-DOM-id/main-frame target sensing;
- provider-local exact-node continuity at mutation boundaries;
- managed `FOCUS` with fresh independent focus evidence;
- managed `CLICK` only for explicit boolean `aria-pressed` transitions;
- managed `TYPE_TEXT` only for an empty writable non-password `input[type=text]`/`textarea`, with fresh length+SHA-256 completion evidence;
- managed native `CHECK` with fresh same-node `checked=true` evidence;
- managed native `UNCHECK` with fresh same-node `checked=false` evidence;
- real local Chromium proof for all managed slices above;
- real Windows Edge default-UIA focused-input sensing in an isolated profile.

Do not overstate this stage. Still unavailable/incomplete:

- `SELECT_OPTION`, `PRESS` and other action-specific browser mutations;
- generic browser click without a bounded independently observable postcondition;
- editing/replacing non-empty text;
- password/sensitive text entry;
- contenteditable/rich-text mutation;
- ARIA checkbox mutation;
- iframe/child-frame/generic accessibility target sensing;
- multiple-target/disambiguation lifecycle;
- tab/popup/frame lifecycle;
- headed managed-browser UX and visual fusion;
- download/upload/file-picker authority;
- persistent managed profile policy;
- cloud browser adapter;
- browser crash/health/recovery and complete network-sandbox hardening;
- formal Chromium/Playwright release packaging;
- authenticated User Browser Bridge control of the user's existing browser session;
- browser permission UX and MFA/sensitive-field handoff.

Broader high-leverage product gaps also remain: durable Work checkpoints/recovery, isolated parallel Investigation, MCP/connectors, scheduled/event-driven work, unified permission/audit controls, M8 continuity and SM1+ self-maintenance.

## Task queue

### P0 - final UNCHECK documentation-head normal CI
Status: **REQUIRED AFTER THIS HANDOFF COMMIT**

Re-read final `dev/zn-agent` HEAD and require exact-head normal Windows CI success. Implementation head `73257f8c` is already green in normal CI, dedicated real Chromium E2E and interactive Windows E2E.

### P1 - managed-browser SELECT_OPTION
Status: **NEXT CANDIDATE / BLOCKED ON P0 + CALL-CHAIN TRACE**

Implement only if a narrow native-select lifecycle can satisfy product-grade evidence:

1. current exact target + `allow_page_interaction` authority;
2. execution-time exact-node revalidation;
3. native/select capability validation;
4. explicit bounded option/value request;
5. refuse pre-existing requested state when no new transition can be claimed;
6. provider dispatch;
7. fresh exact-node re-observation;
8. unchanged ZN target identity;
9. independent fresh selected-value/index evidence;
10. replacement/no-effect/provider-failure coverage;
11. unit + real Chromium E2E.

Do not expose arbitrary provider methods to gain breadth.

### P2 - managed-browser PRESS / next action-specific mutations
Status: **OPEN / REQUIRES BOUNDED EFFECT SEMANTICS**

PRESS must not be added as “send arbitrary key and trust dispatch”. Decide only after tracing a concrete product need and independently observable postcondition.

### P3 - browser checkpoint / broader sensing lifecycle
Status: **OPEN**

After enough useful action coverage, stop adding isolated actions and reassess frames/accessibility/multi-targets/tabs/popups/recovery as a browser lifecycle checkpoint.

### P4 - durable Work / checkpoint / recovery
Status: **OPEN / NEXT MAJOR FOUNDATION**

This is the highest-leverage post-browser foundation. Work must be resident-owned, persist across restarts, support cancellation/recovery and not depend on one model/chat/provider.

### P5 - isolated parallel Work / Investigation
Status: **OPEN / HIGH PRODUCT PRIORITY**

One ZN may own multiple isolated investigations/workspaces. Do not model them as multiple product identities.

### P6 - MCP/connectors
Status: **OPEN**

Build ZN-owned resource/action/credential-reference/permission/effect contracts first; MCP is an adapter, not execution authority or identity.

### P7 - scheduled/event-driven resident work
Status: **OPEN**

### P8 - authenticated User Browser Bridge + permission/control UX
Status: **FOUNDATION / OPEN**

Never copy user cookies/password/profile stores. Add extension/native messaging only if real provider evidence shows it is needed and user permission is explicit.

### P9 - M8 Windows continuity / rollback / signing
Status: **PARTIAL**

### P10 - SM1+ self-maintenance
Status: **OPEN**

## Development-history audit

Earlier history contains the already-recorded accidental root `noop` commit; it was removed by a later normal fast-forward commit and remains auditable.

The preceding accidental `docs/.tmp` file was created in `e3eb38cce090c6c268866f911cffc0d5ce288636` and removed in normal fast-forward commit `37fe40556caafb9113a08c1e22d2beb519fc64b5`. It is absent from the product tree. No force push, reset or history rewrite was used to hide either mistake.

## Risks / boundaries

- `main` remains untouched.
- no force push/history rewrite.
- ZN remains the only product subject; models/providers are replaceable resources.
- provider browser handles are disposable execution resources, not ZN identity.
- native CHECK/UNCHECK do not imply ARIA-checkbox or generic click support.
- TYPE_TEXT raw content remains transient execution data; do not add raw input/current text to durable evidence/logging.
- current TYPE_TEXT refuses non-empty and password targets.
- real Edge UIA sensing does not imply authenticated user-browser control.
- downloads/uploads remain disabled until file authority exists.
- one self-hosted Windows runner serializes many jobs; completed exact-head runs are the authority.
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
tests/zn_agent/core/test_browser_contract.py
tests/zn_agent/core/test_managed_browser.py
tests/zn_agent/core/test_managed_browser_click.py
tests/zn_agent/core/test_managed_browser_type_text.py
tests/zn_agent/core/test_managed_browser_check.py
tests/zn_agent/e2e/test_windows_managed_browser.py
tests/zn_agent/e2e/test_windows_interactive_user_browser_bridge.py
.github/workflows/zn-managed-browser-e2e.yml
.github/workflows/zn-windows-interactive-e2e.yml
.github/workflows/zn-ci.yml
```

## Next real target

Finish exact-head normal Windows CI for this documentation HEAD. Then trace and, if the evidence contract is sound, implement one narrow native `SELECT_OPTION` lifecycle. After a useful browser action checkpoint, move the next major foundation to durable resident-owned Work/checkpoint/recovery. Keep `main` untouched.
