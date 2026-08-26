# ZN Agent Handoff

Updated: 2026-08-26

## Current goal

Browser remains a two-plane ZN subsystem:

```text
Resident Managed Browser
+ User Browser Bridge
= complete browser capability
```

The managed plane now has verified narrow navigation, exact-DOM-id/main-frame target sensing, exact-node `FOCUS`, exact-node `CLICK` for explicit boolean `aria-pressed` transitions, exact-node `TYPE_TEXT` for an empty writable non-password textbox, and exact-node native `CHECK` for an enabled unchecked checkbox. `UNCHECK` remains open and must be proven separately.

Core principle:

> **ZN uses models. Models do not own ZN.**

Current maintainers/models are replaceable. Codex remains unavailable because its billing is exhausted; no current work depends on delegating to it.

## Branch / repository truth

- fixed development branch: `dev/zn-agent`
- canonical source/release branch: `main`
- latest fully verified implementation/test head before this documentation commit: `a6cc5619fee9d9e41d2fa0e885af0ba58db84f6c`
- canonical `main`: `8234a835dea604783cea0bd9d28a40de654ec03d`
- PR #6 remains draft/open/unmerged, base `main`, head `dev/zn-agent`
- `main` was not modified
- no force push or history rewrite was used

A HANDOFF commit cannot contain its own resulting SHA. Re-read the resulting `dev/zn-agent` HEAD and require exact-head normal Windows CI before calling this handoff fully synchronized.

## Completed in current stage

### 1. Previous TYPE_TEXT documentation P0 was closed before CHECK

Previous docs head:

```text
04e48948bca64b8c9d179333ddd4498b61681dad
docs: record verified managed browser text entry
```

Exact-head normal run `32971420718` completed with Source Boundary, Kernel, Electron, and status publisher all `success`. CHECK was not pushed until this P0 closed.

### 2. CHECK real call chain was traced first

Existing contracts already contained `BrowserActionKind.CHECK` / `UNCHECK` and map both to `allow_page_interaction`. No new permission field was introduced.

The implementation target was deliberately narrowed to real native checkboxes:

```text
BrowserActionKind.CHECK
-> current BrowserActionAuthority
-> exact DOM-ID/main-frame target binding
-> provider-local exact-node revalidation
-> native checkbox-state evidence
-> provider check()
-> fresh target + exact-node comparison
-> fresh checked state
-> BrowserEffectEvidence
```

ARIA checkbox abstractions and `UNCHECK` were intentionally excluded from the CHECK claim.

### 3. Narrow managed-browser CHECK implemented

Implementation commit:

```text
a6cc5619fee9d9e41d2fa0e885af0ba58db84f6c
feat: add verified managed browser check
```

The candidate commit was built off-tree and its net diff was reviewed before fast-forward. It changes only:

```text
runtime/python/zn_agent/core/managed_browser.py
tests/zn_agent/core/test_managed_browser_check.py
tests/zn_agent/e2e/test_windows_managed_browser.py
```

CHECK lifecycle:

```text
current exact target observation
-> allow_page_interaction authority
-> target role == checkbox
-> provider confirms connected native input[type=checkbox]
-> require enabled + checked=false
-> provider check()
-> fresh target re-observation
-> same exact JS node
-> same ZN target identity
-> fresh checked=true
-> success
```

Safety behavior:

- non-native checkbox-like targets fail closed;
- disabled checkbox fails before dispatch;
- already-checked state is refused before dispatch instead of being claimed as a new transition;
- provider return alone is not success;
- provider no-effect fails;
- same-shape replacement fails even when the replacement preserves `checked=true`;
- `UNCHECK` remains explicitly unimplemented and test-guarded;
- no generic Playwright method surface was added.

### 4. Exact-head dedicated real Chromium proof is green

```text
run 32973414369
head a6cc5619fee9d9e41d2fa0e885af0ba58db84f6c
Windows local managed Chromium E2E   success

55 browser/core tests   OK
2 real Chromium E2E     OK
```

All eight new CHECK tests passed:

1. page-interaction permission required at authority boundary;
2. native checkbox required;
3. already-checked target refused before dispatch;
4. success only from fresh same-node `checked=true` evidence;
5. provider no-effect fails;
6. same-shape replacement fails;
7. disabled checkbox refused;
8. `UNCHECK` remains unimplemented and does not dispatch CHECK.

Real Chromium additionally proved the native unchecked->checked transition while retaining navigation, target sensing, focus, verified toggle click, verified TYPE_TEXT, replacement rejection, and metadata/private-network safety evidence.

### 5. Exact-head normal Windows CI is green

```text
run 32973414561
head a6cc5619fee9d9e41d2fa0e885af0ba58db84f6c

ZN Source Boundary / Windows      success
ZN Kernel / Python / Windows      success
Electron / TypeScript / Windows   success
Publish Windows CI statuses       success
```

Kernel completed formal runtime install, zero-model resident boot, resident core compile, and the full core suite successfully. The maintenance connector did not expose a stable bounded exact test-count line after completion, so this handoff records the completed job result rather than inventing a count.

### 6. Exact-head interactive Windows regression is green

```text
run 32973418964
head a6cc5619fee9d9e41d2fa0e885af0ba58db84f6c
Windows interactive computer-use E2E   success
```

The real pointer/UIA, native Unicode text-entry, WPF UIA text-capability, and installed-browser provider regressions all completed successfully on the exact CHECK head.

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
- managed `CHECK` only for an enabled unchecked native `input[type=checkbox]`, with fresh same-node `checked=true` evidence;
- real local Chromium proof for all managed slices above;
- real Windows Edge default-UIA focused-input sensing in an isolated profile.

Do not overstate this stage. Still unavailable/incomplete:

- `UNCHECK`;
- generic managed-browser click semantics without an action-specific independent postcondition;
- editing/replacing non-empty text;
- password/sensitive text entry;
- contenteditable/rich-text mutation;
- ARIA checkbox mutation;
- `SELECT_OPTION`, `PRESS` and other target mutations;
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

## Task queue

### P0 - final CHECK documentation-head normal CI
Status: **REQUIRED AFTER THIS HANDOFF COMMIT**

Re-read final `dev/zn-agent` HEAD and require its exact-head normal Windows CI success. Implementation head `a6cc5619` is already green in normal CI, dedicated real Chromium E2E and interactive Windows E2E.

### P1 - managed-browser UNCHECK
Status: **NEXT / BLOCKED ON P0**

Implement as its own lifecycle, not as a side effect of CHECK:

1. current exact DOM-ID/main-frame target;
2. `allow_page_interaction` authority;
3. execution-time exact-node revalidation;
4. provider confirms connected enabled native checkbox;
5. require current `checked=true`;
6. refuse already-unchecked state before dispatch;
7. dispatch only `BrowserActionKind.UNCHECK`;
8. fresh re-observe the same exact node;
9. require unchanged ZN target identity + fresh `checked=false`;
10. fail closed on replacement/detach/identity drift/provider no-effect;
11. unit tests + real Chromium E2E.

Do not infer generic click semantics or ARIA-checkbox support from CHECK/UNCHECK.

### P2 - SELECT_OPTION / PRESS / broader click semantics
Status: **OPEN / BLOCKED ON ACTION-SPECIFIC EVIDENCE**

### P3 - broader target sensing/browser lifecycle
Status: **OPEN**

Frames, accessibility queries, multi-target disambiguation, tabs/popups, headed UX, visual fusion and recovery remain separate work.

### P4 - authenticated User Browser Bridge
Status: **FOUNDATION / OPEN**

Use real Edge UIA evidence as one input. Never copy user cookies/password/profile stores. Add extension/native messaging only if real evidence shows it is needed and permission is explicit.

### P5 - isolated parallel Work / Investigation + checkpoints
Status: **OPEN / HIGH PRODUCT PRIORITY**

Must be resident-owned work isolation and must not depend on Codex or another single model/provider.

### P6 - MCP/connectors
Status: **OPEN**

### P7 - scheduled/event-driven resident work
Status: **OPEN**

### P8 - M8 Windows continuity / rollback / signing
Status: **PARTIAL**

### P9 - SM1+ self-maintenance
Status: **OPEN**

## Development-history audit

Earlier history contains the already-recorded accidental root `noop` commit; it was removed by a later normal fast-forward commit and remains auditable.

The preceding accidental `docs/.tmp` file was created in `e3eb38cce090c6c268866f911cffc0d5ce288636` and removed in normal fast-forward commit `37fe40556caafb9113a08c1e22d2beb519fc64b5`. It is absent from the product tree. No force push, reset, or history rewrite was used to hide either mistake.

## Risks / boundaries

- `main` remains untouched.
- no force push/history rewrite.
- provider handles are disposable execution resources, not ZN identity.
- verified native CHECK does not imply `UNCHECK`, ARIA checkbox or generic click support.
- TYPE_TEXT raw content remains transient execution data; do not add raw input/current text to durable evidence/logging.
- current TYPE_TEXT refuses non-empty and password targets.
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
tests/zn_agent/core/test_managed_browser_check.py
tests/zn_agent/e2e/test_windows_managed_browser.py
tests/zn_agent/e2e/test_windows_interactive_user_browser_bridge.py
.github/workflows/zn-managed-browser-e2e.yml
.github/workflows/zn-windows-interactive-e2e.yml
.github/workflows/zn-ci.yml
```

## Next real target

Finish exact-head normal Windows CI for this documentation HEAD. Then implement one narrow managed-browser `UNCHECK` lifecycle with current exact-node authority and a fresh independently observed native `checked=false` postcondition. Keep `main` untouched.
