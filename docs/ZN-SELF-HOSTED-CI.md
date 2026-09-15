# ZN Windows CI topology

> This file keeps its historical name so existing repository links do not break.
>
> Current intended platform: Windows x64
>
> Canonical integration/source/release branch: `main`
>
> Development branches: short-lived branches created from current `main` and merged through PR.

## Purpose

ZN CI is hosted-first. Routine repository verification must not depend on a maintainer computer being powered on, logged in, unlocked, or carrying persistent local state.

The default execution environment for ordinary Windows validation is a fresh GitHub-hosted `windows-latest` runner. A workflow may keep a self-hosted runner only when its acceptance contract genuinely requires state or capabilities that cannot yet be reconstructed safely on a hosted runner.

Runner labels are infrastructure choices, not product authority. An old `self-hosted` or `zn-interactive` label is not evidence by itself that a test requires a local machine.

## Required ZN CI

`.github/workflows/zn-ci.yml` runs on pull requests targeting `main`, pushes to `main`, and manual dispatch.

The required Windows checks are:

- `ZN Source Boundary / Windows`;
- `ZN Kernel / Python / Windows`;
- `Electron / TypeScript / Windows`.

All three product-verification jobs run on GitHub-hosted Windows x64 and retain explicit `RUNNER_OS == Windows` / `RUNNER_ARCH == X64` fail-closed checks. Their test selection and product contracts are independent of any maintainer machine identity.

The final status-publisher job only projects completed job results to GitHub commit-status APIs. It does not establish Windows product truth and does not need a Windows product-verification runner.

For merge decisions, use the required checks for the exact current PR head and current `main` base. A green result from an older feature head or older base is historical evidence only.

## Hosted headless acceptance

Headless acceptance should use GitHub-hosted Windows when the workflow creates all of its own relevant state inside the job, for example:

- isolated Python virtual environments and `ZN_AGENT_HOME` directories;
- repository-owned temporary files, SQLite state, loopback services, and subprocesses;
- isolated Playwright-managed Chromium rather than an existing personal browser profile;
- generated DOCX/XLSX fixtures rather than host Office state;
- deterministic Work/Resident restart and side-effect recovery fixtures.

Current hosted examples include the research, document-research, memory, local documents/spreadsheet, atomic overwrite, local-service diagnosis, managed-browser, command-replanning, and required ZN CI lanes.

A hosted migration must preserve the original validation oracle. Changing `runs-on` is not permission to weaken test selection, retry until green, increase mutation authority, or replace a real effect with a mock.

## When self-hosted infrastructure is still justified

Keep a workflow on a special runner only when current evidence proves one of these boundaries matters.

### Real user desktop / input authority

UIA, foreground activation, pointer/keyboard input, and existing-user-browser acceptance may require a real interactive Windows session. Treat that requirement as empirical, not permanent.

A candidate hosted environment must prove at least:

- non-Session-0 execution;
- `WTSActive` session state;
- access to the input desktop;
- same-session foreground ownership;
- exact foreground acquisition for a test-owned window;
- the actual product-route acceptance cases, not only a readiness probe.

If the complete acceptance path is stable on GitHub-hosted Windows, remove the local-runner dependency instead of keeping it for historical reasons.

### Credential-backed real-model acceptance

Some guarded E2E workflows intentionally require a real cognitive provider route. Their migration boundary is secure, explicit provider configuration and secret injection, not desktop access.

Do not commit provider credentials or copy a maintainer's local config into the repository. A hosted design must reconstruct the minimum route configuration from GitHub Actions secrets/variables, keep logs secret-safe, and fail closed when no authorized route is configured.

### Installer, release, and publication

Installer and release workflows have additional identity and credential boundaries. Moving them to hosted infrastructure requires preserving the actual package/install/restart/update contract and isolating installer identity from any existing product installation.

In particular, an isolated destination directory alone does not prove an installer is isolated from upgrade/uninstall registration identity. Treat release signing, update publication, GitHub Release creation, and object-storage credentials as separate authorization surfaces.

### Runner bootstrap / watchdog

Runner bootstrap and watchdog workflows exist only to operate self-hosted infrastructure. They should disappear or be retired when the runner they manage is no longer part of the active CI topology.

## Windows/x64 contract

Hosted and self-hosted Windows jobs that rely on Windows semantics should verify the actual runner platform rather than trusting labels alone:

```text
RUNNER_OS   = Windows
RUNNER_ARCH = X64
```

A workflow that additionally requires an interactive session, a provider route, installer isolation, or another special capability must prove that capability explicitly in the job.

## Security boundary

GitHub-hosted runners are disposable job environments, but workflow permissions and secrets still require least privilege.

- Keep `GITHUB_TOKEN` permissions minimal.
- Do not expose release/provider credentials to routine pull-request jobs that do not need them.
- Do not print secrets or reconstructed provider configuration.
- Treat third-party action and dependency changes as supply-chain-sensitive.
- Keep outside-world mutations bounded and verify their postconditions independently.

For the remaining self-hosted jobs:

- use a dedicated low-privilege account or isolated machine/VM where practical;
- do not store unrelated personal secrets, SSH keys, or browser profiles in runner workspaces;
- do not grant administrator rights merely to make ordinary CI pass;
- assume repository-controlled code executes with the runner account's OS permissions.

## Observability and queue interpretation

A queued or pending GitHub-hosted job is scheduling evidence, not a product-test failure. A self-hosted job that remains queued may additionally indicate that its special runner is offline or busy.

For a failed job, classify the first real failing transition:

- assertion/product contract failure;
- fixture/environment setup failure;
- timeout;
- external cancellation/runner interruption;
- unavailable credential/capability.

Do not convert infrastructure interruption into a product patch without causal evidence, and do not dismiss a reproducible hosted-only product failure as infrastructure merely because the old local lane passed.

## Maintaining the topology

When moving a workflow from self-hosted to hosted Windows:

1. prove the workflow does not consume hidden host state;
2. preserve its test commands, timeout, permissions, concurrency, and acceptance oracle unless a separate reviewed change justifies otherwise;
3. keep an explicit Windows/x64 guard;
4. run the exact changed head on the hosted runner;
5. refresh against current `main` before merge;
6. remove stale local-runner documentation, bootstrap logic, and watchdog dependencies only after their final consumer is gone.

Prefer several small migration waves with exact-head evidence over one repository-wide runner-label replacement.

## Optional non-Windows platforms

The repository retains optional Linux workflows such as:

- `zn-linux-container-smoke.yml`;
- `zn-linux-appimage-update-smoke.yml`.

They do not replace Windows product evidence. Restoring Linux/macOS as intended desktop release targets requires an explicit product decision and corresponding CI/release acceptance.
