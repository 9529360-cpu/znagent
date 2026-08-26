# ZN Agent Handoff

Updated: 2026-08-26

## Current goal

Browser remains a two-plane ZN subsystem:

```text
Resident Managed Browser
+ User Browser Bridge
= complete browser capability
```

The managed plane now has verified narrow navigation, exact-DOM-id/main-frame target sensing, exact-node `FOCUS`, exact-node `CLICK` for explicit boolean `aria-pressed` transitions, and exact-node `TYPE_TEXT` for an empty writable non-password textbox with privacy-safe completion evidence. Generic click/text replacement/password typing remain unavailable.

The next narrow managed action should be `CHECK` first, then `UNCHECK`, but only after the final documentation HEAD from this handoff passes exact-head normal Windows CI.

Core principle:

> **ZN uses models. Models do not own ZN.**

Current maintainers/models are replaceable. Codex remains unavailable because its billing is exhausted; no current work depends on delegating to it.

## Branch / repository truth

- fixed development branch: `dev/zn-agent`
- canonical source/release branch: `main`
- latest fully verified implementation/test head before this documentation commit: `0002accb359351ec07761b3d017d13040d35c941`
- canonical `main`: `8234a835dea604783cea0bd9d28a40de654ec03d`
- PR #6 remains draft/open/unmerged, base `main`, head `dev/zn-agent`
- `main` was not modified
- no force push or history rewrite was used

A HANDOFF commit cannot contain its own resulting SHA. Re-read the resulting `dev/zn-agent` HEAD and require exact-head normal Windows CI before calling this handoff fully synchronized.

## Completed in current stage

### 1. Previous CLICK documentation P0 was closed before new implementation

The previous documentation head was:

```text
64313e19651fa5f9769e624ef7e14e6f3dd8c949
docs: record verified managed browser toggle click
```

Its exact-head normal Windows run `32968594833` completed with all four jobs `success`. New TYPE_TEXT work was not pushed until that P0 was closed.

### 2. Real TYPE_TEXT call chain was traced first

Before implementation, the actual contracts and mature privacy patterns were inspected:

```text
BrowserActionKind.TYPE_TEXT
-> BrowserPermissionContext.allows_action()
   requires allow_page_interaction + allow_text_entry
-> BrowserActionAuthority current observation/target/freshness binding
-> PlaywrightManagedBrowser exact DOM-ID target binding
-> provider-local transient exact element handle
```

Existing desktop text-state mechanisms were used only as evidence for the privacy boundary: raw current text may exist transiently while sensing/executing, but durable evidence is length + SHA-256. The browser implementation remains browser-owned rather than copying desktop architecture.

`provider_bridge.py` and resident ownership were also checked: the resident owns the lazy managed-browser resource but does not automatically persist browser action arguments. TYPE_TEXT raw input remains a transient execution value; normal `BrowserEffectEvidence` does not contain it.

### 3. Narrow managed-browser TYPE_TEXT implemented

Implementation commit:

```text
0002accb359351ec07761b3d017d13040d35c941
feat: add verified managed browser text entry
```

Net implementation diff from `64313e19` was reviewed before fast-forward and contains only:

```text
runtime/python/zn_agent/core/managed_browser.py
tests/zn_agent/core/test_managed_browser_type_text.py
tests/zn_agent/e2e/test_windows_managed_browser.py
```

The first TYPE_TEXT slice requires:

```text
current exact target observation
-> allow_page_interaction + allow_text_entry authority
-> provider-local exact-node revalidation
-> exact target role == textbox
-> current provider state is connected + supported + writable + non-password
-> current text is empty
-> explicit non-empty text, no control chars, <= 512 UTF-16 units
-> provider fill(text)
-> fresh target re-observation
-> same exact JS node
-> same ZN target identity
-> fresh text length + SHA-256 == requested length + SHA-256
-> success
```

Safety/privacy behavior:

- non-empty current fields are refused before dispatch;
- password targets are refused even with `allow_sensitive_fields=True` in this first slice;
- disabled/read-only/unsupported text targets fail closed;
- provider no-effect fails;
- same-shape node replacement fails even when replacement copies the requested value;
- provider dispatch returning successfully is not completion;
- raw requested/current text is not placed in `BrowserEffectEvidence`; normal evidence contains only lengths/digests and bounded metadata;
- no generic Playwright method surface was added.

### 4. Dedicated exact-head real managed Chromium proof is green

```text
run 32969877355
head 0002accb359351ec07761b3d017d13040d35c941
Windows local managed Chromium E2E   success

47 browser/core tests   OK
2 real Chromium E2E     OK
```

All seven TYPE_TEXT contract tests passed:

1. text-entry permission required at authority boundary;
2. explicit non-empty string required;
3. non-empty target refused before dispatch;
4. success requires fresh same-node requested digest;
5. provider no-effect fails;
6. same-shape replacement fails;
7. password target refused even with sensitive-field permission.

Real Chromium additionally proved Unicode empty-textbox entry with fresh digest evidence and same-shape replacement rejection while preserving navigation, target sensing, focus, toggle click and network-safety evidence.

### 5. Exact-head interactive Windows regression is green

```text
run 32969877468
head 0002accb359351ec07761b3d017d13040d35c941
Windows interactive computer-use E2E   success

Ran 4 tests in 11.183s
OK
```

The real pointer/UIA, native Unicode text-entry, WPF text-capability and installed Edge provider proofs all passed. Edge remained isolated-profile, default accessibility, no forced renderer accessibility, no copied user profile/auth state.

### 6. Exact-head normal Windows CI is green

```text
run 32969877380
head 0002accb359351ec07761b3d017d13040d35c941

ZN Source Boundary / Windows      success
ZN Kernel / Python / Windows      success
Electron / TypeScript / Windows   success
Publish Windows CI statuses       success

CPython 3.12.13
formal runtime install success
zero-model resident boot success
resident core compile success
Ran 529 tests in 571.144s
OK (skipped=5)
```

The full Kernel suite includes the seven new TYPE_TEXT tests.

## Current implementation truth

Verified/foundation browser slices now exist for:

- resident-owned browser session/permission/query/target/observation/action/authority/effect semantics;
- resident ownership/shutdown of local managed Chromium;
- managed navigation with fresh observed result;
- bounded exact-DOM-id/main-frame target sensing;
- provider-local exact-node continuity at mutation boundaries;
- managed `FOCUS` with fresh independent focus evidence;
- managed `CLICK` only for explicit boolean `aria-pressed` transitions;
- managed `TYPE_TEXT` only for an empty writable non-password `input[type=text]`/`textarea`, using fresh length+SHA-256 completion evidence;
- real local Chromium proof for all managed slices above;
- real Windows Edge default-UIA focused-input sensing in an isolated profile.

Do not overstate this stage. Still unavailable/incomplete:

- generic managed-browser click semantics without an action-specific independent postcondition;
- editing/replacing non-empty text;
- password/sensitive text entry;
- contenteditable/rich-text mutation;
- `CHECK`, `UNCHECK`, `SELECT_OPTION`, `PRESS` and other target mutations;
- iframe/child-frame/generic accessibility target sensing;
- multiple-target/disambiguation lifecycle;
- tab/popup/frame lifecycle;
- headed managed-browser UX and visual fusion;
- download/upload/file-picker authority;
- persistent managed profile policy;
- cloud browser adapter;
- browser crash/health/recovery and complete network sandbox hardening;
- formal Chromium/Playwright release packaging;
- authenticated User Browser Bridge control of the user's existing browser session;
- browser permission UX and MFA/sensitive-field handoff.

## Task queue

### P0 - final TYPE_TEXT documentation-head normal CI
Status: **REQUIRED AFTER THIS HANDOFF COMMIT**

Re-read final `dev/zn-agent` HEAD and require its exact-head normal Windows CI success. Implementation head `0002accb` is already green in normal CI, dedicated real Chromium E2E and interactive Windows E2E.

### P1 - managed-browser CHECK
Status: **NEXT / BLOCKED ON P0**

Trace the real current checkbox call chain before coding. Preferred narrow lifecycle:

1. current exact DOM-ID/main-frame target;
2. `allow_page_interaction` authority;
3. execution-time exact-node revalidation;
4. require a real checkbox target and current boolean checked pre-state;
5. refuse if already checked rather than claiming a new transition;
6. dispatch only `BrowserActionKind.CHECK`;
7. fresh re-observe the same exact node;
8. require fresh `checked == true` plus unchanged ZN target identity;
9. fail closed on replacement/detach/identity drift/provider no-effect;
10. unit tests + real Chromium E2E.

Do not implement `UNCHECK` in the same claim unless its lifecycle is independently tested. Do not turn CHECK into a generic provider click.

### P2 - managed-browser UNCHECK
Status: **OPEN / BLOCKED ON P1**

Mirror the same authority/evidence discipline with `checked == false` as a fresh observed postcondition.

### P3 - SELECT_OPTION / PRESS / broader click semantics
Status: **OPEN**

Add one action at a time only when a bounded independent postcondition exists.

### P4 - broader target sensing/browser lifecycle
Status: **OPEN**

Frames, accessibility queries, multi-target disambiguation, tabs/popups, headed UX, visual fusion and recovery remain separate work.

### P5 - authenticated User Browser Bridge
Status: **FOUNDATION / OPEN**

Use real Edge UIA evidence as one input. Never copy user cookies/password/profile stores. Add extension/native messaging only if real evidence shows it is needed and permission is explicit.

### P6 - isolated parallel Work / Investigation + checkpoints
Status: **OPEN / HIGH PRODUCT PRIORITY**

Must be resident-owned work isolation and must not depend on Codex or another single model/provider.

### P7 - MCP/connectors
Status: **OPEN**

### P8 - scheduled/event-driven resident work
Status: **OPEN**

### P9 - M8 Windows continuity / rollback / signing
Status: **PARTIAL**

### P10 - SM1+ self-maintenance
Status: **OPEN**

## Development-history audit

Earlier history contains the already-recorded accidental root `noop` commit; it was removed by a later normal fast-forward commit and remains auditable.

The preceding accidental `docs/.tmp` file was created in `e3eb38cce090c6c268866f911cffc0d5ce288636` and removed in normal fast-forward commit `37fe40556caafb9113a08c1e22d2beb519fc64b5`. It is absent from the product tree. No force push, reset, or history rewrite was used to hide either mistake.

## Risks / boundaries

- `main` remains untouched.
- no force push/history rewrite.
- provider handles are disposable execution resources, not ZN identity.
- TYPE_TEXT raw content is transient execution data; do not add raw input/current text to durable evidence/logging.
- current TYPE_TEXT refuses non-empty and password targets; do not infer broader editing authority from the verified empty-textbox slice.
- verified toggle click does not imply generic click/check/select support.
- real Edge UIA sensing does not imply authenticated user-browser control.
- downloads/uploads remain disabled until file authority exists.
- one self-hosted Windows runner can serialize jobs; completed exact-head runs are the authority.
- M8 remains partial; SM1+ remains open.

## Related files

```text
ZN.md
docs/ZN-PRODUCT-CAPABILITY-MAP.md
docs/ZN-IMPLEMENTATION-STATUS.md
docs/ZN-SOURCE-EXTRACTION.md
docs/ZN-SELF-MAINTENANCE.md
.agent/HANDOFF.md
runtime/python/zn_agent/core/models.py
runtime/python/zn_agent/core/browser.py
runtime/python/zn_agent/core/managed_browser.py
runtime/python/zn_agent/core/provider_bridge.py
runtime/python/zn_agent/core/automation_text_state_sense.py
runtime/python/zn_agent/core/focused_text_entry_resident.py
runtime/python/zn_agent/core/keyboard_text_body.py
tests/zn_agent/core/test_browser_contract.py
tests/zn_agent/core/test_managed_browser.py
tests/zn_agent/core/test_managed_browser_click.py
tests/zn_agent/core/test_managed_browser_type_text.py
tests/zn_agent/e2e/test_windows_managed_browser.py
tests/zn_agent/e2e/test_windows_interactive_user_browser_bridge.py
.github/workflows/zn-managed-browser-e2e.yml
.github/workflows/zn-windows-interactive-e2e.yml
.github/workflows/zn-ci.yml
```

## Next real target

Finish exact-head normal Windows CI for this documentation HEAD. Then implement one narrow managed-browser `CHECK` lifecycle with current exact-node authority and a fresh independently observed boolean checked-state postcondition. Keep `main` untouched.
