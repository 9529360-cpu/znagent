# ZN Agent Handoff

Updated: 2026-08-26

## Current goal

Keep ZN's Windows CI and real interactive verification planes repository-owned and recoverable, then resume bounded managed-browser product work.

Founding boundary remains:

> **ZN uses models. Models do not own ZN.**

Do not trade away the real Windows interactive-session boundary merely to make CI green.

## Branch / repository truth

- repository: `9529360-cpu/znagent`
- fixed development branch: `dev/zn-agent`
- canonical source/release branch: `main`
- implementation head before this HANDOFF update: `f1ed2326e7536120ac0b8d362c2604f72a020e53`
- implementation commit: `ci: verify hidden interactive runner handoff`
- canonical `main`: `8234a835dea604783cea0bd9d28a40de654ec03d`
- PR #6: draft/open/unmerged, base `main`, head `dev/zn-agent`
- `main` was not modified
- no force push or history rewrite was used

A HANDOFF commit cannot contain its own resulting SHA. Re-read `dev/zn-agent` after this file is committed and record/report the resulting exact head externally; do not pretend this file can self-reference its own commit.

## Completed in current stage

### 1. Restored repository truth instead of following stale handoff state

The prior HANDOFF still pointed at browser UNCHECK/documentation work, but the real branch had advanced through a Windows self-hosted runner/CI maintenance sequence. The real code/Git/Actions state was used as authority.

The previous browser implementation remains verified at:

```text
73257f8c728778054faf74869243b356383fede1
feat: add verified managed browser uncheck
```

Its recorded exact-head normal CI, managed Chromium E2E, and interactive Windows E2E remain green. `SELECT_OPTION` has not been implemented and must not be reported as started or complete.

### 2. Headless and interactive Windows runner responsibilities are separated

Normal CI now targets:

```text
[self-hosted, Windows, X64, zn-ci]
```

Interactive desktop/browser proof targets:

```text
[self-hosted, Windows, X64, zn-interactive]
```

Repository bootstrap targets three isolated `zn-ci` workers. `zn-ci` service workers are not substitutes for a logged-on desktop session.

### 3. Hidden interactive-runner handoff now has a real active caller

Implementation commit:

```text
f1ed2326e7536120ac0b8d362c2604f72a020e53
ci: verify hidden interactive runner handoff
```

Changed files:

```text
.github/scripts/handoff-zn-interactive-runner-watchdog.ps1
.github/workflows/zn-interactive-runner-hidden-watchdog.yml
```

The workflow now launches a detached repository-owned handoff process from `zn-interactive`, waits until the current GitHub Worker drains, performs a second fail-closed drain check, restarts the matching listener through the hidden scheduled watchdog, writes a marker unique to the exact workflow run/attempt only after a listener returns, then verifies on a later `zn-interactive` job that the exact marker exists and live process ancestry is:

```text
Runner.Listener.exe
-> cmd.exe / run.cmd
-> hidden PowerShell watchdog
```

It also keeps verification off the interactive label for a short `zn-ci` handoff window. Merely spawning the handoff process is not success.

## Real test / CI truth

### Exact implementation-head normal CI

```text
run 32992305928
head f1ed2326e7536120ac0b8d362c2604f72a020e53

ZN Source Boundary / Windows       success
Electron / TypeScript / Windows    success
ZN Kernel / Python / Windows       in progress at last inspection
```

Kernel had completed isolated setup, zero-model resident boot and resident compilation, and was still running the full core suite. Do not call this run green until Kernel and the final status job complete successfully.

### Exact implementation-head hidden migration

```text
run 32992305981
head f1ed2326e7536120ac0b8d362c2604f72a020e53

Migrate interactive runner watchdog to hidden launch   queued
runner assignment                                     none at last inspection
```

### Independent evidence of interactive-plane outage

An older bootstrap workflow is also queued on the same label:

```text
run 32991717258
Bootstrap parallel Windows runners   queued
runs-on                              [self-hosted, Windows, X64, zn-interactive]
```

This makes the current blocker broader than the new hidden migration workflow: `zn-interactive` is not accepting jobs.

The available GitHub connector cannot read the repository self-hosted-runner administration endpoint, so do not claim a direct online/offline flag from that API.

## Current risks / blockers

- `zn-interactive` is unavailable to Actions at the current checkpoint.
- Hidden-watchdog migration code is implemented but **not verified** until run `32992305981` executes through its final verify job.
- Real interactive Windows/UIA/browser regression cannot be rerun while `zn-interactive` is unavailable.
- Do not move interactive tests onto Session-0 `zn-ci` workers.
- Do not introduce auto-logon, expose credentials, broaden secret permissions, or weaken runner labels to bypass the blocker.
- The exact implementation-head normal CI is still incomplete while Kernel is running.
- Documentation/HANDOFF synchronization after this update will itself create a new head requiring exact-head normal CI.
- `main` remains untouched.

## Task queue

### P0 - finish current normal CI

Status: **IN PROGRESS**

Require exact-head normal CI for `f1ed2326`. If Kernel fails, inspect the real failure and fix it before proceeding.

### P1 - restore `zn-interactive`

Status: **BLOCKED ON REAL INTERACTIVE RUNNER AVAILABILITY**

Exhaust repository-controlled recovery paths first. Preserve the logged-on interactive-session requirement. If the machine-side interactive listener is stopped and repository automation has no running interactive control plane, that is a genuine external bootstrap boundary rather than a reason to fake interactive proof.

### P2 - verify hidden watchdog migration

Status: **IMPLEMENTED / NOT VERIFIED**

Require run `32992305981` (or a later exact-head equivalent) to complete migration, handoff window, and exact-marker/live-ancestry verification successfully.

### P3 - synchronize docs/HANDOFF exact head

Status: **REQUIRED AFTER RUNNER STATE IS SETTLED**

Keep `docs/ZN-IMPLEMENTATION-STATUS.md` and `.agent/HANDOFF.md` aligned with code, branch and CI reality; require normal CI on the resulting exact head.

### P4 - managed-browser `SELECT_OPTION`

Status: **NEXT PRODUCT CANDIDATE / DEFERRED**

Only after interactive verification is restored, trace the real contract/provider/effect call chain. Any implementation must use exact current target authority, native-select capability validation, bounded option/value request, provider dispatch, fresh exact-node re-observation, unchanged ZN target identity and independent selected-state evidence. Provider return alone is not success.

### P5 - durable Work / checkpoint / recovery

Status: **NEXT MAJOR FOUNDATION AFTER USEFUL BROWSER CHECKPOINT**

Work must remain resident-owned, restart-safe, cancellable/recoverable and independent of one model/chat/provider.

## Related files

```text
ZN.md
AGENTS.md
docs/ZN-IMPLEMENTATION-STATUS.md
docs/ZN-SOURCE-EXTRACTION.md
docs/ZN-SELF-MAINTENANCE.md
.agent/HANDOFF.md
.github/workflows/zn-ci.yml
.github/workflows/zn-runner-bootstrap.yml
.github/workflows/zn-interactive-runner-hidden-watchdog.yml
.github/workflows/zn-managed-browser-e2e.yml
.github/workflows/zn-windows-interactive-e2e.yml
.github/scripts/bootstrap-zn-windows-runners.ps1
.github/scripts/install-zn-interactive-runner-watchdog.ps1
.github/scripts/watch-zn-interactive-runner.ps1
.github/scripts/handoff-zn-interactive-runner-watchdog.ps1
runtime/python/zn_agent/core/managed_browser.py
tests/zn_agent/core/test_managed_browser_check.py
tests/zn_agent/e2e/test_windows_managed_browser.py
```

## Next real target

Finish the exact implementation-head normal CI and recover the real `zn-interactive` execution plane without weakening its session boundary. Then require the hidden-watchdog migration's exact-marker/live-process verification. Only after that return to `SELECT_OPTION`. Keep `main` untouched.
