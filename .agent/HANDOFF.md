# ZN Agent Handoff

Updated: 2026-08-26

## Current goal

Continue product development from the verified managed-browser `SELECT_OPTION` checkpoint. The next major foundation is durable resident-owned Work/checkpoint/recovery. Do not spend the current stage on the deferred Windows NetworkService 8.3 path-identity defect unless new work becomes blocked by it.

Founding boundary remains:

> **ZN uses models. Models do not own ZN.**

## Branch / repository truth

- repository: `9529360-cpu/znagent`
- fixed development branch: `dev/zn-agent`
- canonical source/release branch: `main`
- branch head immediately before this HANDOFF update: `286e1e967434e371fd9c9fdf71811217d9ac7d60`
- product/CI checkpoint head: `8c94f1ac9a3fdda2e704f45bdaf02efdc4d40271`
- canonical `main`: `8234a835dea604783cea0bd9d28a40de654ec03d`
- PR #6: draft/open/unmerged, base `main`, head `dev/zn-agent`
- `main` was not modified
- no force push or history rewrite was used

A HANDOFF commit cannot contain its own resulting SHA. Re-read `dev/zn-agent` after committing this file and report the resulting exact head externally.

## Completed in current stage

### 1. Interactive Windows runner recovery is real and no longer the active problem

The old handoff text about a queued hidden-watchdog migration is obsolete.

Verified Actions evidence:

```text
ZN Windows Runner Bootstrap             run 32999198210   success
ZN Interactive Runner Visible Watchdog  run 32999383631   success
```

Real interactive runner evidence from Actions logs:

```text
runner.name       zn-interactive
runner.session_id 1
runner.root       C:\actions-runner-znagent
startup           visible cmd.exe -> run.cmd
trigger           MSFT_TaskLogonTrigger / interactive user logon
hidden            false
```

The three `zn-ci` service workers remain the headless CI pool. Do not move interactive proof onto Session 0. Do not restore hidden runner launch, auto-logon or credential-dependent bootstrap.

### 2. Abandoned partial 8.3-path fix was removed cleanly

A partial path-canonicalization attempt was briefly committed as:

```text
16239c878867295a2441b0146688326d7d32571f
fix: canonicalize Windows lexical path identity
```

The user chose not to spend the current stage on that infrastructure/code issue. The partial implementation was therefore reverted by a normal forward commit:

```text
db647cb49c3de014aa82bc28ec87c1c4e5b02c15
revert: defer Windows short-path canonicalization
```

No history was rewritten and no half-fix remains active.

Known defect remains: on NetworkService runners the same Windows path can appear in long and DOS 8.3 forms, causing some strict Kernel path-identity checks to disagree. Treat this as deferred known debt, not as fixed or flaky.

### 3. Managed-browser `SELECT_OPTION` implemented

Real call chain before modification was:

```text
BrowserActionKind.SELECT_OPTION
-> BrowserPermissionContext page-interaction authority
-> PlaywrightManagedBrowser.act
-> current DOM-id provider binding
-> provider mutation
-> fresh target reacquisition
-> exact-node / target identity / effect verification
```

Implementation commits:

```text
3c5e8b30637ab2168c130eb1bffe0c4adc8eecb9
feat: add verified managed select option effect

7dcf67c8aa78449adb1404f3384f3e2d19e19b02
feat: route native select option through verified effect

de0e82a1e9036350fd0abf75e9901625786938a3
test: cover verified managed select option

39a087e5eab499b536f2d845311542e5e9c52804
test: verify managed select option in Chromium

8c94f1ac9a3fdda2e704f45bdaf02efdc4d40271
ci: run managed select option E2E
```

Behavior is intentionally narrow and fail-closed:

- native single `<select>` only;
- current target must be a fresh ZN-bound `combobox` target;
- one explicit bounded string option value;
- disabled and multi-select targets refused;
- already-selected value refused before dispatch;
- provider `select_option` return is ignored as completion truth;
- fresh post-dispatch target is reacquired;
- exact same DOM node and unchanged ZN target identity are required;
- independently observed selected value must match by length + SHA256;
- raw option values are not stored in effect evidence;
- same-shape replacement after dispatch fails even when replacement carries the requested selected value.

Relevant files:

```text
runtime/python/zn_agent/core/managed_browser.py
runtime/python/zn_agent/core/managed_browser_select.py
tests/zn_agent/core/test_managed_browser_select.py
tests/zn_agent/e2e/test_windows_managed_browser_select.py
.github/workflows/zn-managed-browser-e2e.yml
```

## Real test / CI truth

### Managed-browser exact product checkpoint

```text
run 33001748123
head 8c94f1ac9a3fdda2e704f45bdaf02efdc4d40271
runner zn-ci-02 / Windows X64
conclusion success
```

Real logs show:

```text
managed browser contract tests   71 passed
real local Chromium E2E           4 passed
```

The real Chromium suite includes both new SELECT_OPTION cases:

```text
test_native_select_requires_fresh_same_node_selected_value_evidence   ok
test_native_select_rejects_same_shape_node_replacement_after_dispatch ok
```

This is real Chromium evidence, not mock-only validation.

### Ordinary ZN CI at product checkpoint

```text
run 33001747960
head 8c94f1ac9a3fdda2e704f45bdaf02efdc4d40271

ZN Source Boundary / Windows       success
Electron / TypeScript / Windows    success
ZN Kernel / Python / Windows       in progress at last inspection; full core suite running
```

Do not call normal CI green until Kernel actually completes successfully. If it fails only on the already-known NetworkService 8.3 path-identity defect, record that truth and continue product work per the current user decision rather than restarting the deferred fix automatically.

Any documentation commit after `8c94f1ac` creates a newer exact head; do not pretend `33001748123` validates unrelated later documentation bytes. It is the exact product implementation checkpoint evidence.

## Current risks / blockers

- `SELECT_OPTION` itself is verified on real Chromium.
- `zn-interactive` is recovered and verified; runner availability is not a blocker.
- normal Kernel CI may remain red on the deferred Windows 8.3 path-identity defect.
- `PRESS`, generic click, non-empty text replacement, multi-select and broader browser lifecycle remain unimplemented.
- User Browser Bridge control is still incomplete.
- M8 Windows continuity remains partial.
- SM1+ self-maintenance remains open.
- `main` remains untouched.

## Task queue

### P0 - durable Work/checkpoint/recovery

Status: **NEXT REAL PRODUCT TARGET**

Trace the existing Work lifecycle before modification. The goal is resident-owned durable work that survives UI/chat/model replacement and process restart, with explicit checkpoint/recovery semantics and no external model/provider owning continuation.

Before coding, inspect at least:

```text
runtime/python/zn_agent/core/work.py
runtime/python/zn_agent/core/store.py
runtime/python/zn_agent/core/resident.py
runtime/python/zn_agent/core/daemon.py
runtime/python/zn_agent/core/worker.py
relevant work/resident/store tests
```

Follow the real caller chain from desktop/RPC input through work ledger -> resident event -> working state -> persisted result/recovery.

### P1 - browser follow-ons

Status: **OPEN / NOT CURRENT MAJOR TARGET**

Bounded candidates include `PRESS`, generic click semantics, richer text editing, multi-select and broader page/target lifecycle. Preserve fresh authority and independent effect evidence.

### P2 - deferred Windows 8.3 path identity

Status: **KNOWN / DEFERRED BY CURRENT USER DECISION**

Do not claim fixed. Resume only if explicitly reprioritized or if it materially blocks the next product stage.

### P3 - M8 / SM1+

Status: **OPEN**

Continue only under their existing repository contracts and human-approval boundaries for high-risk identity, memory, credentials, updater/signing and destructive self-maintenance changes.

## Next real target

Build durable resident-owned Work/checkpoint/recovery from the existing real Work/store/resident call chain. Keep the verified browser checkpoint intact, keep interactive/headless Windows execution planes separate, and keep `main` untouched.
