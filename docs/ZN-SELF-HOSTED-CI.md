# ZN Windows self-hosted CI

> Current intended platform: Windows x64
>
> Development branch: `dev/zn-agent`
>
> Canonical source/release branch: `main`

## Purpose

Steady-state ZN development CI is repository-owned automation executed by a replaceable Windows x64 self-hosted GitHub Actions runner.

The runner is infrastructure, not ZN identity and not a specific maintainer machine contract. A computer may be replaced without changing the workflow as long as a suitable Windows x64 runner is registered and online.

## Automatic behavior

`.github/workflows/zn-ci.yml` runs automatically on every push to:

- `dev/zn-agent`;
- `main`.

It may also be started manually with `workflow_dispatch`.

The required checks are:

- ZN source boundary;
- isolated Python runtime install, zero-model boot and core tests;
- Electron/TypeScript dependency audit, typecheck, bundle and retained desktop/release tests.

Linux Container and Linux AppImage checks are optional manual workflows and do not block normal Windows development.

## Runner selection

The workflow dispatches to the generic GitHub Actions `self-hosted` label, then immediately verifies:

```text
RUNNER_OS   = Windows
RUNNER_ARCH = X64
```

This deliberately avoids binding the project to a runner name, computer name, user profile or installation path.

If additional non-Windows self-hosted runners are ever added to this repository, runner groups or dedicated project labels should be introduced before enabling them for unrelated workloads.

## Recovery on another Windows computer

A replacement maintainer should use the repository's GitHub UI:

```text
Settings
→ Actions
→ Runners
→ New self-hosted runner
→ Windows x64
```

Run GitHub's generated registration commands locally on that computer. The registration token is short-lived infrastructure credential material: never commit it, put it in HANDOFF, paste it into ordinary logs, or make it part of ZN resident memory.

After registration, keep the runner listener online. For unattended CI across logout/reboot, install/run the GitHub Actions runner using the supported Windows service mode on the runner host.

Then verify repository connectivity with `.github/workflows/zn-self-hosted-runner-check.yml` and confirm a normal push produces real step execution in `ZN CI`.

## Host safety boundary

A self-hosted runner executes repository-controlled code with the operating-system permissions of its runner account. Therefore:

- prefer a dedicated low-privilege runner account or isolated machine/VM where practical;
- do not store personal secrets, browser profiles, SSH private keys or unrelated credentials in the runner workspace;
- do not grant administrator privileges merely to make ordinary CI pass;
- do not expose release/signing secrets to routine development jobs;
- keep workflow `GITHUB_TOKEN` permissions minimal;
- treat changes that expand runner permissions or secret access as security-sensitive review items.

The steady-state development workflow currently uses repository contents read access and commit-status write access only.

## Observability

Each main Windows CI job publishes its commit status as `pending` once a runner has actually accepted the job, then the final status publisher records success/failure.

This means:

```text
no pending status     = no runner has accepted the job yet
pending               = Windows self-hosted execution is active/accepted
success/failure/error = terminal repository-visible evidence
```

A queued workflow without any pending status is infrastructure availability evidence, not a code-test failure.

## Secondary platforms

The repository retains optional manual Linux workflows so historical mechanisms can still be exercised when useful:

- `zn-linux-container-smoke.yml`;
- `zn-linux-appimage-update-smoke.yml`.

They are not current M8 blockers. Restoring Linux/macOS as intended release targets requires an explicit product decision and corresponding CI/release evidence.
