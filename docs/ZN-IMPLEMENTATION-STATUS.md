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

M10 canonical source promotion remains complete. Ordinary development remains on `dev/zn-agent`; `main` was not modified in this stage.

Latest implementation head before this status-document update:

```text
f1ed2326e7536120ac0b8d362c2604f72a020e53
ci: verify hidden interactive runner handoff
```

Status: **NORMAL HEADLESS WINDOWS CI POOL OPERATIONAL; INTERACTIVE RUNNER RECOVERY/HIDDEN-WATCHDOG MIGRATION IMPLEMENTED BUT NOT YET VERIFIED BECAUSE `zn-interactive` IS NOT ACCEPTING JOBS. MANAGED-BROWSER PRODUCT WORK REMAINS AT VERIFIED UNCHECK AND MUST NOT ADVANCE UNTIL THE INTERACTIVE TEST PLANE IS RECOVERED.**

## 1. Previously verified managed-browser product slice

The latest fully verified browser implementation remains:

```text
73257f8c728778054faf74869243b356383fede1
feat: add verified managed browser uncheck
```

Exact-head verification already recorded for that implementation:

```text
normal Windows CI                  run 32979312548   success
managed local Chromium E2E        run 32979312465   success
interactive Windows E2E           run 32979312447   success
```

Verified narrow managed-browser behavior still includes resident ownership, exact DOM-id/main-frame target sensing, `FOCUS`, explicit boolean `aria-pressed` `CLICK`, empty writable non-password `TYPE_TEXT`, native `CHECK`, and native `UNCHECK`, all with action-specific fresh evidence rather than provider return alone.

Still incomplete includes `SELECT_OPTION`, `PRESS`, generic click, non-empty text replacement, password/sensitive entry, contenteditable, ARIA checkbox mutation, frame/multi-target/tab/popup lifecycle, headed managed UX, file authority, persistent profile policy, cloud adapter, browser health/recovery, complete network hardening, formal Chromium packaging, and authenticated User Browser Bridge control.

## 2. Windows CI runner topology now encoded in the repository

Normal CI is routed to dedicated headless workers:

```text
[self-hosted, Windows, X64, zn-ci]
```

Repository bootstrap targets three isolated `zn-ci` service workers. Interactive desktop/browser jobs remain deliberately separate:

```text
[self-hosted, Windows, X64, zn-interactive]
```

This separation is a product boundary. Session-0 service runners must not be used as a substitute for real interactive Windows/UIA/browser proof.

Relevant repository-owned automation now includes:

```text
.github/workflows/zn-ci.yml
.github/workflows/zn-runner-bootstrap.yml
.github/workflows/zn-interactive-runner-hidden-watchdog.yml
.github/scripts/bootstrap-zn-windows-runners.ps1
.github/scripts/install-zn-interactive-runner-watchdog.ps1
.github/scripts/watch-zn-interactive-runner.ps1
.github/scripts/handoff-zn-interactive-runner-watchdog.ps1
```

## 3. Hidden interactive-runner handoff is now an active verified workflow contract

Commit `f1ed2326` closes the previous code-path gap where the handoff script existed but had no active caller.

The hidden-watchdog workflow now:

1. runs migration only on `zn-interactive` in a non-Session-0 logged-on session;
2. installs and validates the repository-owned hidden interactive scheduled task;
3. starts a detached hidden handoff process with `RUNNER_TRACKING_ID` cleared so GitHub worker cleanup does not own it;
4. waits for the current `Runner.Worker.exe` to drain before touching the listener;
5. performs a second fail-closed drain check immediately before listener termination;
6. stops only the matching foreground listener / dedicated `run.cmd` console;
7. starts the hidden scheduled watchdog;
8. writes a marker unique to `GITHUB_RUN_ID` + `GITHUB_RUN_ATTEMPT` only after exactly one listener is online;
9. leaves an isolated `zn-ci` handoff window before verification;
10. verifies the exact marker plus live process ancestry `Runner.Listener.exe -> run.cmd -> hidden watchdog PowerShell` on `zn-interactive`.

Starting the migration process is not considered success. The exact marker and live ancestry are required.

## 4. Current CI truth

For implementation head `f1ed2326`:

```text
ZN CI run 32992305928
- ZN Source Boundary / Windows      success
- Electron / TypeScript / Windows   success
- ZN Kernel / Python / Windows      in progress at last inspection (core suite running)
```

The exact-head hidden migration workflow is:

```text
ZN Interactive Runner Hidden Watchdog run 32992305981
- Migrate interactive runner watchdog to hidden launch   queued
- runner assignment                                     none at last inspection
```

An older independent bootstrap run is also queued waiting for `zn-interactive`:

```text
ZN Windows Runner Bootstrap run 32991717258
- Bootstrap parallel Windows runners   queued
- runs-on                              [self-hosted, Windows, X64, zn-interactive]
```

Therefore the current evidence points to the interactive runner plane being unavailable, not a queue problem unique to the new hidden-watchdog workflow. The connector available to the maintainer cannot read the repository self-hosted-runner administration endpoint, so the runner's GitHub registration/online bit cannot be asserted directly from that endpoint here.

Do not mark the hidden-watchdog migration verified until run `32992305981` actually executes and its verify job succeeds.

## 5. Current product and infrastructure blockers

- `zn-interactive` is not currently accepting queued jobs, so real desktop/UIA/browser interactive verification cannot proceed.
- The repository can define and verify recovery once that runner is online, but a headless `zn-ci` service worker cannot safely manufacture a logged-on Windows desktop session without crossing credential/permission boundaries.
- Do not introduce auto-logon, credential expansion, Session-0 UI claims, or weaken interactive labels merely to clear CI.
- Managed-browser `SELECT_OPTION` remains the next product candidate only after the interactive test plane is restored and the runner migration is verified.

## 6. Broader product gaps remain material

High-leverage open foundations remain durable resident-owned Work checkpoints/recovery, isolated parallel Work/Investigation, MCP/connectors behind ZN-owned permission/evidence contracts, scheduled/event-driven resident work, unified permission/audit controls, M8 installation/update/rollback/signing continuity, and SM1+ isolated self-maintenance.

These must not make a model, agent framework, browser provider, MCP server, or desktop UI the owner of ZN.

## 7. Next implementation order

```text
1. finish exact-head normal CI for f1ed2326 and diagnose any real failure
2. recover zn-interactive without weakening the interactive-session boundary
3. run and require green hidden-watchdog migration + exact-marker/live-ancestry verification
4. synchronize status/HANDOFF on the resulting exact head and require normal CI
5. only then trace SELECT_OPTION's real call chain and effect contract
6. after a useful browser checkpoint, move the next major foundation to durable Work/checkpoint/recovery
```

M8 Windows continuity remains PARTIAL. SM0 remains verified foundation; SM1+ remains open. High-risk identity, long-term memory, credential/permission, updater/signing and destructive self-maintenance changes continue to require human approval.
