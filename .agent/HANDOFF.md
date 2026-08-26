# ZN Agent Handoff

Updated: 2026-08-26

## Current goal

Browser remains a two-plane ZN subsystem:

```text
Resident Managed Browser
+ User Browser Bridge
= complete browser capability
```

The managed-browser foundation now includes a verified narrow exact-node `FOCUS` lifecycle on real local Chromium. The next browser mutation is `CLICK`, but only after the final documentation HEAD completes exact-head normal Windows CI. Do not skip directly to generic click/type or expose a generic Playwright method surface.

Core principle:

> **ZN uses models. Models do not own ZN.**

Current maintainers/models are replaceable. Codex is currently unavailable because its billing is exhausted; current development does not depend on it.

## Branch / repository truth

- fixed development branch: `dev/zn-agent`
- canonical source/release branch: `main`
- canonical `main`: `8234a835dea604783cea0bd9d28a40de654ec03d`
- PR #6 remains draft/open/unmerged, base `main`, head `dev/zn-agent`
- `main` was not modified
- no force push or history rewrite was used

A HANDOFF commit cannot contain its own resulting SHA. Re-read resulting `dev/zn-agent` HEAD and require its exact-head normal Windows CI before calling this handoff fully synchronized.

## Completed in this stage

### 1. Real state was restored before modifying code

The prior HANDOFF still listed exact-node continuity + `FOCUS` as next, but real `dev/zn-agent` had already advanced to:

```text
61d3bc36b4f18697f5ab5f68da9d52c17c9da97f
feat: add exact managed browser focus lifecycle
```

That commit was reviewed instead of reimplementing it.

Its real CI state was not green:

- interactive Windows E2E: success;
- normal Windows CI: Kernel failure;
- managed-browser E2E: browser contract step failure and real Chromium step skipped.

Both failures came from the same focus freshness assertion.

### 2. Exact-node managed-browser FOCUS implementation was audited

Current lifecycle:

```text
bounded current BrowserTarget
-> provider-local transient exact element handle
-> BrowserActionAuthority
-> execution-time current-node revalidation
-> FOCUS dispatch
-> fresh target acquisition
-> exact JS node equality check
-> independent document.activeElement check
-> BrowserEffectEvidence(postcondition="same_exact_target_focused")
```

Safety behavior verified in unit tests:

- same-shape target replacement before dispatch fails closed;
- replacement during focus fails closed;
- focus blocked by the page fails the independent postcondition;
- target handle is disposable provider state, not ZN identity;
- observation replacement/session close disposes old handles;
- click remains unimplemented.

### 3. Freshness collision was fixed in production code

At `61d3bc36`, pre- and post-focus observations could receive the same microsecond UTC string. Authority currently uses `observation_captured_at` equality as freshness identity, so this was a real correctness defect rather than merely a brittle test.

Fix:

```text
7fd6f191f2f099b86d3573fca4be06fc64783211
fix: make resident timestamps freshness-safe
```

`runtime/python/zn_agent/core/models.py` now emits thread-safe, process-monotonic ISO UTC timestamps: if wall clock output repeats or moves backward relative to the previous emitted value, the next value advances by one microsecond.

The focus freshness assertion was preserved; it was not weakened or removed.

### 4. Browser CI trigger coverage was corrected

Commit:

```text
37f273a43a07d3d316055a47019da4fffe4bb9a3
ci: cover browser freshness clock changes
```

`runtime/python/zn_agent/core/models.py` is now included in `.github/workflows/zn-managed-browser-e2e.yml` path filters because that shared clock directly affects browser authority/freshness semantics.

### 5. Exact-head real managed Chromium proof is green

```text
run 32963487090
head 37f273a43a07d3d316055a47019da4fffe4bb9a3
Windows local managed Chromium E2E   success
```

Real log evidence:

```text
35 browser/core tests   OK
2 real Chromium E2E     OK
```

The real Chromium test explicitly passed:

```text
test_local_headless_chromium_observes_targets_focuses_exact_node_and_verifies_navigation ... ok
```

So the narrow real provider path is now proven:

```text
target sensing
-> current exact-node authority
-> FOCUS
-> exact-node continuity
-> independent activeElement evidence
```

The second real Chromium E2E also preserved the private-network metadata safety floor.

## Current implementation truth

Verified/foundation browser slices now include:

- resident-owned browser session/permission/query/target/observation/action/authority/effect semantics;
- lazy resident ownership and shutdown cleanup of local managed Chromium;
- real headless Chromium navigation with fresh authority and observed postcondition;
- bounded exact-DOM-id/main-frame target sensing;
- provider-local exact-node continuity at the first mutation boundary;
- narrow managed-browser `FOCUS` with execution-time revalidation and independent focused-element evidence;
- real local Chromium evidence for navigation, target sensing and focus;
- real Windows Edge default-UIA focused-input sensing in an isolated profile without forced renderer accessibility.

Do not overstate this stage. Still unavailable/incomplete:

- managed-browser `CLICK`;
- `TYPE_TEXT`, select/check/keyboard and other target mutations;
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

## CI truth

### Failed implementation-head runs that must remain visible

At `61d3bc36`:

- normal Windows CI failed one focus freshness assertion;
- managed-browser workflow failed the same assertion before real Chromium E2E;
- interactive Windows E2E succeeded.

These failures led to the real freshness fix; they were not hidden.

### Corrected real managed-browser evidence

```text
run 32963487090
head 37f273a43a07d3d316055a47019da4fffe4bb9a3
conclusion: success
```

All 35 browser/core tests and both real Chromium E2Es passed.

### Final documentation-head normal CI

Status: **REQUIRED AFTER THIS HANDOFF COMMIT**.

The final `dev/zn-agent` documentation HEAD must complete `ZN CI` with Source Boundary, Kernel, Electron and published status jobs green before this stage is called synchronized.

## Development-history audit

Earlier history contains the already-recorded accidental empty root `noop` commit; it was removed by a later normal fast-forward commit and remains auditable.

This maintenance pass also accidentally created `docs/.tmp` in:

```text
e3eb38cce090c6c268866f911cffc0d5ce288636
tmp
```

It was immediately removed by normal fast-forward commit:

```text
37fe40556caafb9113a08c1e22d2beb519fc64b5
chore: remove accidental temp file
```

`docs/.tmp` is absent from the final tree. No force push, reset or history rewrite was used to hide the mistake.

## Task queue

### P0 - final documentation-head normal CI
Status: **REQUIRED**

Require exact final `dev/zn-agent` HEAD normal Windows CI success.

### P1 - managed-browser CLICK
Status: **NEXT / BLOCKED ON P0**

Trace the real click call chain before coding. Reuse the existing ZN target authority and provider-local exact-node revalidation boundary, but define a click-specific independent postcondition instead of treating provider dispatch as success.

Do not make a generic Playwright click tool. Add one narrow lifecycle and real Chromium evidence.

### P2 - managed-browser TYPE_TEXT
Status: **OPEN / BLOCKED ON P1**

Requires explicit text-entry permission, current exact-node authority, sensitive-field policy, and fresh independent value/state evidence. Do not infer support from focus/click.

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

## Risks / boundaries

- `main` remains untouched.
- no force push/history rewrite.
- provider handles are disposable execution resources, not ZN identity.
- timestamp freshness is process-monotonic, but broader authority should continue moving toward explicit evidence identities rather than assuming wall-clock time alone proves reality.
- focus support does not imply click/type support.
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
tests/zn_agent/core/test_managed_browser.py
tests/zn_agent/e2e/test_windows_managed_browser.py
.github/workflows/zn-managed-browser-e2e.yml
.github/workflows/zn-windows-interactive-e2e.yml
.github/workflows/zn-ci.yml
```

## Next real target

Finish exact-head normal Windows CI for this documentation HEAD. Then implement one narrow managed-browser `CLICK` lifecycle with current exact-node authority and independent fresh effect evidence. Keep `main` untouched.
