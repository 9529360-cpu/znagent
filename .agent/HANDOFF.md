# ZN Agent Handoff

Updated: 2026-08-26

## Current goal

Browser remains a two-plane ZN subsystem:

```text
Resident Managed Browser
+ User Browser Bridge
= complete browser capability
```

The managed-browser foundation now includes verified narrow navigation, exact-DOM-id/main-frame target sensing, exact-node `FOCUS`, and an exact-node `CLICK` slice for explicit boolean `aria-pressed` transitions. Generic click remains unavailable. The next browser mutation is `TYPE_TEXT`, but only after this final documentation HEAD completes exact-head normal Windows CI.

Core principle:

> **ZN uses models. Models do not own ZN.**

Current maintainers/models are replaceable. Codex is currently unavailable because its billing is exhausted; current development does not depend on it.

## Branch / repository truth

- fixed development branch: `dev/zn-agent`
- canonical source/release branch: `main`
- latest fully verified implementation/test head before this documentation commit: `a6a014d836ad3f61d14b4c6a25221957a5dca9a1`
- canonical `main`: `8234a835dea604783cea0bd9d28a40de654ec03d`
- PR #6 remains draft/open/unmerged, base `main`, head `dev/zn-agent`
- `main` was not modified
- no force push or history rewrite was used

A HANDOFF commit cannot contain its own resulting SHA. Re-read the resulting `dev/zn-agent` HEAD and require exact-head normal Windows CI before calling this documentation handoff fully synchronized.

## Completed in this stage

### 1. Real state was restored before continuing CLICK

The stage began at:

```text
9c360e02bd5730c32f0bd84a281e5a515f28c9b8
feat: add verified managed browser toggle click
```

The real call chain was traced before changing anything:

```text
BrowserActionKind.CLICK
-> BrowserPermissionContext.allows_action()
-> BrowserActionAuthority current observation/target/freshness binding
-> PlaywrightManagedBrowser.act()
-> _click()
-> _revalidate_target_binding()
-> provider click dispatch
-> fresh target acquisition
-> exact-node continuity check
-> fresh aria-pressed state
-> BrowserEffectEvidence
```

Provider-local element handles remain disposable execution resources and never become ZN identity.

### 2. First CLICK implementation failures were reconciled instead of hidden

At `9c360e02`:

```text
managed-browser workflow run 32965439542   failed
normal Windows CI run 32965439522          Kernel failed
```

Source Boundary and Electron were green. All five new click-specific contract tests passed. The two failures were pre-existing generic-click tests that still expected the old refusal text to contain `not implemented`.

The click lifecycle itself was not removed and the new tests were not weakened. The final implementation keeps the generic boundary explicit:

```text
generic browser click is not implemented;
verified toggle click requires explicit boolean expected aria_pressed postcondition
```

### 3. Narrow verified toggle CLICK is implemented

CLICK is deliberately limited to a state transition ZN can independently verify.

Required path:

```text
current exact target observation
-> allow_page_interaction authority
-> provider-local exact-node revalidation
-> explicit expected={"aria_pressed": <bool>}
-> current boolean aria-pressed pre-state
-> require requested state to differ from current state
-> provider click
-> fresh target re-observation
-> same exact node
-> same ZN target identity
-> fresh aria-pressed == expected
-> success evidence
```

Safety behavior:

- generic arbitrary click is unavailable;
- non-boolean/missing `aria_pressed` expected state fails before provider dispatch;
- a target without boolean `aria-pressed` fails before provider dispatch;
- if the requested state is already present, ZN refuses to claim a transition and does not click;
- provider dispatch without the requested observed state fails;
- same-shape node replacement during click fails exact-node continuity even if the replacement reports the requested state;
- success never comes from Playwright returning without error.

Implementation/test chain:

```text
c888128608aeef6b04daa1bf8fb1c46ab4b4f711
test: define managed browser toggle click contract

9c360e02bd5730c32f0bd84a281e5a515f28c9b8
feat: add verified managed browser toggle click

a6a014d836ad3f61d14b4c6a25221957a5dca9a1
test: prove verified managed browser toggle click
```

`a6a014d8` also makes the generic-click refusal boundary explicit and adds the real Chromium fixture/evidence.

### 4. Exact-head dedicated real Chromium proof is green

```text
run 32967137365
head a6a014d836ad3f61d14b4c6a25221957a5dca9a1
Windows local managed Chromium E2E   success

40 browser/core tests   OK
2 real Chromium E2E     OK
```

Real Chromium proves:

- navigation and bounded target sensing still work;
- exact-node `FOCUS` still works;
- generic click without explicit independent postcondition remains refused;
- toggle `false -> true` succeeds from fresh same-node evidence;
- a fresh second action proves `true -> false`;
- same-shape replacement during click fails with `exact_node_continuity=false` even though the replacement has the requested `aria-pressed` state;
- the metadata/private-network safety floor remains intact.

### 5. Exact-head interactive Windows regression is green

```text
run 32967137348
head a6a014d836ad3f61d14b4c6a25221957a5dca9a1
Windows interactive computer-use E2E   success

Ran 4 tests in 16.337s
OK
```

The four real interactive tests cover:

- pointer/UIA focus;
- native Unicode text entry;
- WPF UIA text capability;
- installed Edge/Chrome user-browser provider sensing.

The browser provider proof again selected real Edge on the runner, used an isolated temporary profile, did not force renderer accessibility, and exported bounded text length/digest rather than raw browser text.

### 6. Exact-head normal Windows CI is green

```text
run 32967137328
head a6a014d836ad3f61d14b4c6a25221957a5dca9a1

ZN Source Boundary / Windows      success
ZN Kernel / Python / Windows      success
Electron / TypeScript / Windows   success
Publish Windows CI statuses       success

CPython 3.12.13
formal runtime install success
zero-model resident boot success
resident core compile success
Ran 522 tests in 552.760s
OK (skipped=5)
```

The full Kernel suite includes the five click contract tests and all passed.

## Current implementation truth

Verified/foundation browser slices now include:

- resident-owned browser session/permission/query/target/observation/action/authority/effect semantics;
- lazy resident ownership and shutdown cleanup of local managed Chromium;
- real headless Chromium navigation with fresh authority and observed postcondition;
- bounded exact-DOM-id/main-frame target sensing;
- provider-local exact-node continuity at mutation boundaries;
- narrow managed-browser `FOCUS` with execution-time revalidation and independent focused-element evidence;
- narrow managed-browser `CLICK` for explicit boolean `aria-pressed` transitions with independent fresh state evidence;
- real local Chromium evidence for navigation, target sensing, focus and toggle click;
- real Windows Edge default-UIA focused-input sensing in an isolated profile without forced renderer accessibility.

Do not overstate this stage. Still unavailable/incomplete:

- generic managed-browser click semantics without a bounded independent postcondition;
- `TYPE_TEXT`;
- select/check/keyboard and other target mutations;
- iframe/child-frame and generic accessibility target sensing;
- multiple-target/disambiguation lifecycle;
- tabs/popups/frames lifecycle;
- headed managed-browser UX;
- visual-browser fusion;
- download/upload/file-picker authority;
- persistent managed profile policy;
- cloud browser adapter;
- browser health/crash recovery and complete network sandbox hardening;
- formal Chromium/Playwright release packaging;
- authenticated User Browser Bridge control of the user's existing session;
- browser permission UX and MFA/sensitive-field handoff.

## Task queue

### P0 - final documentation-head normal CI
Status: **REQUIRED AFTER THIS HANDOFF COMMIT**

Re-read final `dev/zn-agent` HEAD and require its exact-head normal Windows CI success. The implementation/test head `a6a014d8` is already green in normal CI, dedicated real Chromium E2E and interactive Windows E2E.

### P1 - managed-browser TYPE_TEXT
Status: **NEXT / BLOCKED ON P0**

Trace the real text-entry call chain before coding. Current contract support already includes `BrowserPermissionContext.allow_text_entry`, but the managed adapter must not infer text mutation authority from focus/click.

Required design constraints:

1. require `allow_text_entry` plus the normal current page/target/permission/freshness authority;
2. require provider-local exact-node revalidation immediately before mutation;
3. define a privacy-safe current-text pre-state and post-state contract before provider dispatch;
4. avoid raw input values/text in normal observation/effect logs and persisted evidence;
5. independently verify the postcondition from fresh current reality, likely using bounded length + digest or an equally privacy-safe state identity;
6. treat password/sensitive targets more strictly and require explicit `allow_sensitive_fields` where appropriate;
7. fail closed on same-shape replacement, detach, identity drift, provider dispatch without observed effect, or unobservable current state;
8. add unit tests + real Chromium E2E;
9. keep Playwright a provider resource, not a generic tool surface.

### P2 - broader managed-browser click/select/check/keyboard
Status: **OPEN / BLOCKED ON P1 OR ACTION-SPECIFIC EVIDENCE**

The verified toggle click must not be generalized into arbitrary click success. Add each action only when it has a bounded independent postcondition and current exact-node authority.

### P3 - broader target sensing and browser lifecycle
Status: **OPEN**

Frames, accessibility queries, multiple targets, tabs/popups, headed UX, visual fusion and recovery remain separate work.

### P4 - authenticated User Browser Bridge
Status: **FOUNDATION / OPEN**

Use real Edge UIA evidence as one input. Do not copy user cookies/password/profile stores. Add extension/native messaging only if real evidence shows it is needed and permission is explicit.

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

Earlier history contains the already-recorded accidental empty root `noop` commit; it was removed by a later normal fast-forward commit and remains auditable.

A preceding maintenance pass also accidentally created `docs/.tmp` in:

```text
e3eb38cce090c6c268866f911cffc0d5ce288636
tmp
```

It was immediately removed by normal fast-forward commit:

```text
37fe40556caafb9113a08c1e22d2beb519fc64b5
chore: remove accidental temp file
```

`docs/.tmp` is absent from the product tree. No force push, reset or history rewrite was used to hide either mistake.

## Risks / boundaries

- `main` remains untouched.
- no force push/history rewrite.
- provider handles are disposable execution resources, not ZN identity.
- process-monotonic timestamp freshness reduces collision risk, but action authority remains tied to current observations and must continue to prefer explicit reality identities where needed.
- verified toggle click does not imply generic click/type/select/check support.
- text mutation must not leak raw user/browser text into normal evidence.
- real Edge UIA sensing does not imply authenticated user-browser control.
- downloads/uploads remain disabled until file authority exists.
- one Windows self-hosted runner can serialize jobs; completed exact-head evidence is authoritative.
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
tests/zn_agent/core/test_browser_contract.py
tests/zn_agent/core/test_managed_browser.py
tests/zn_agent/core/test_managed_browser_click.py
tests/zn_agent/e2e/test_windows_managed_browser.py
tests/zn_agent/e2e/test_windows_interactive_user_browser_bridge.py
.github/workflows/zn-managed-browser-e2e.yml
.github/workflows/zn-windows-interactive-e2e.yml
.github/workflows/zn-ci.yml
```

## Next real target

Finish exact-head normal Windows CI for this documentation HEAD. Then implement one narrow managed-browser `TYPE_TEXT` lifecycle with current exact-node authority, privacy-safe current-text evidence and independent fresh post-action verification. Keep `main` untouched.
