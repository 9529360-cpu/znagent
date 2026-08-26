# ZN implementation status

> Architecture contract: [`../ZN.md`](../ZN.md)
>
> Product capability ledger: [`ZN-PRODUCT-CAPABILITY-MAP.md`](ZN-PRODUCT-CAPABILITY-MAP.md)
>
> Source adoption boundary: [`ZN-SOURCE-EXTRACTION.md`](ZN-SOURCE-EXTRACTION.md)
>
> Self-maintenance contract: [`ZN-SELF-MAINTENANCE.md`](ZN-SELF-MAINTENANCE.md)
>
> Real code, Git state and CI outrank this ledger.

Development branch: `dev/zn-agent`. Canonical source/release branch: `main`.

## Current checkpoint - 2026-08-26

M10 canonical source promotion remains complete. Ordinary development remains on `dev/zn-agent`; `main` remains unchanged at `8234a835dea604783cea0bd9d28a40de654ec03d`.

Latest product/CI implementation head before this status-document update:

```text
8c94f1ac9a3fdda2e704f45bdaf02efdc4d40271
ci: run managed select option E2E
```

Status: **MANAGED-BROWSER `SELECT_OPTION` IS IMPLEMENTED AND VERIFIED IN REAL LOCAL CHROMIUM. THE REAL INTERACTIVE WINDOWS RUNNER IS ALSO RECOVERED. NORMAL KERNEL CI STILL HAS A SEPARATE WINDOWS SERVICE-ACCOUNT 8.3 PATH-IDENTITY DEFECT THAT IS CURRENTLY DEFERRED RATHER THAN BLOCKING PRODUCT WORK.**

## 1. Verified managed-browser product slice

The managed browser remains a ZN-owned Body resource behind resident-owned session, permission, target-authority and effect-evidence contracts. Playwright is only the current adapter.

Verified narrow behavior now includes:

- ephemeral managed Chromium sessions with ZN URL/origin policy;
- exact DOM-id target sensing in the main frame;
- fresh target authority tied to session/page/observation identity;
- `FOCUS` with fresh exact-node focus evidence;
- explicit boolean `aria-pressed` toggle `CLICK` with observed state transition;
- empty writable non-password `TYPE_TEXT` with fresh text digest/length evidence;
- native checkbox `CHECK` and `UNCHECK` with fresh exact-node checked-state evidence;
- native single-select `SELECT_OPTION` by one explicit option value, with fresh exact-node selected-value evidence.

`SELECT_OPTION` implementation is intentionally fail-closed:

- only native `<select>` / `combobox` targets are accepted;
- disabled and multi-select targets are refused in this first slice;
- the requested value must be one bounded explicit string;
- already-selected state is refused before dispatch;
- Playwright `select_option` return data is not treated as completion truth;
- the target is reacquired after dispatch;
- success requires the same exact DOM node, unchanged ZN target identity and independently observed selected-value digest/length matching the requested value;
- raw option values are not persisted in effect evidence;
- same-shape node replacement after selection is reported as failure even if the replacement exposes the requested value.

Exact-head managed-browser verification for `8c94f1ac`:

```text
ZN Managed Browser E2E run 33001748123   success
runner                                     zn-ci-02 / Windows X64
managed browser contract tests             71 passed
real local Chromium E2E                    4 passed
new SELECT_OPTION real Chromium cases      2 passed
```

The two new real Chromium cases prove both the successful native select mutation and rejection of a same-shape node replacement after dispatch.

Key implementation/test files:

```text
runtime/python/zn_agent/core/browser.py
runtime/python/zn_agent/core/managed_browser.py
runtime/python/zn_agent/core/managed_browser_select.py
tests/zn_agent/core/test_managed_browser_select.py
tests/zn_agent/e2e/test_windows_managed_browser_select.py
.github/workflows/zn-managed-browser-e2e.yml
```

Still incomplete browser scope includes `PRESS`, generic click, non-empty text replacement, password/sensitive entry, contenteditable, ARIA checkbox mutation, multi-select, broader option identities, frame/multi-target/tab/popup lifecycle, headed managed UX, file authority, persistent profile policy, cloud adapter, browser health/recovery, complete network hardening, formal Chromium packaging, and authenticated User Browser Bridge control.

## 2. Real Windows runner topology

Normal headless CI remains isolated on:

```text
[self-hosted, Windows, X64, zn-ci]
```

Three `zn-ci` workers remain repository-managed service runners.

Interactive desktop/browser proof remains isolated on:

```text
[self-hosted, Windows, X64, zn-interactive]
```

The interactive runner recovery is verified reality, not a pending migration:

```text
ZN Windows Runner Bootstrap                     run 32999198210   success
ZN Interactive Runner Visible Watchdog          run 32999383631   success
runner name                                     zn-interactive
runner session                                  SessionId 1
runner root                                     C:\actions-runner-znagent
startup                                         visible cmd.exe -> run.cmd
scheduled trigger                               user logon / Interactive
hidden                                          false
```

The old hidden-watchdog migration is historical and is no longer a success criterion. Do not reintroduce hidden launch, Session-0 interactive claims, auto-logon, credential exposure or weakened labels.

## 3. Current ordinary ZN CI truth

For product head `8c94f1ac9a3fdda2e704f45bdaf02efdc4d40271`, normal `ZN CI` run `33001747960` has, at the latest inspection:

```text
ZN Source Boundary / Windows       success
Electron / TypeScript / Windows    success
ZN Kernel / Python / Windows       in progress - full core suite running
```

Earlier normal CI on the recovered service-runner topology exposed a real Windows path-identity defect: the same NetworkService path may be represented as both the long form and DOS 8.3 short form, causing strict resident repo/terminal path checks to disagree. A partial attempted canonicalization commit was intentionally reverted in `db647cb49c3de014aa82bc28ec87c1c4e5b02c15`; no half-fix remains active.

This defect is currently deferred. Do not report normal Kernel CI green unless a later exact-head run actually succeeds. It does not invalidate the separate exact-head managed-browser Chromium evidence above.

## 4. Broader product gaps

The next major product foundation after this useful browser checkpoint is durable resident-owned Work/checkpoint/recovery. Work must survive UI/chat/model replacement and process restarts without making an external model or provider the owner of ZN.

Other high-leverage gaps remain isolated parallel Work/Investigation, MCP/connectors behind ZN-owned permission/evidence contracts, scheduled/event-driven resident work, unified permission/audit controls, M8 installation/update/rollback/signing continuity, User Browser Bridge control, and SM1+ isolated self-maintenance.

M8 Windows continuity remains PARTIAL. SM0 remains verified foundation; SM1+ remains open. High-risk identity, long-term memory, credential/permission, updater/signing and destructive self-maintenance changes continue to require human approval.

## 5. Next implementation order

```text
1. keep the verified SELECT_OPTION checkpoint intact
2. record normal CI truth without spending the current stage on the deferred 8.3 path defect
3. build the next major foundation: durable resident-owned Work/checkpoint/recovery
4. keep PRESS and broader browser lifecycle as bounded follow-on browser work
5. preserve separate real interactive Windows verification for features that actually require a logged-on desktop
```
