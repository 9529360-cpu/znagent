# ZN Windows self-hosted CI

> Current intended platform: Windows x64
>
> Canonical integration/source/release branch: `main`
>
> Development branches: short-lived `work/*` branches created from current `main` and merged through PR.

## Purpose

Steady-state ZN product verification is repository-owned automation executed by a replaceable Windows x64 self-hosted GitHub Actions runner.

The runner is infrastructure, not ZN identity and not a specific maintainer machine contract. A computer may be replaced without changing the workflow as long as a suitable Windows x64 runner is registered and online.

## Automatic behavior

`.github/workflows/zn-ci.yml` runs automatically on:

- pull requests targeting `main`, so the candidate is verified before merge;
- pushes to `main`, so the merged canonical source is verified again.

It may also be started manually with `workflow_dispatch`.

The required core checks are:

- ZN source boundary;
- isolated Python runtime install, zero-model boot and core tests;
- Electron/TypeScript dependency audit, typecheck, bundle and retained desktop/release tests.

Applicable product E2E workflows such as managed-browser, Work-recovery and Windows interactive computer-use are also configured to run on relevant pull requests targeting `main`, with path filters so unrelated changes do not consume scarce runners unnecessarily.

`dev/zn-agent` is a historical compatibility branch only. It is not a CI integration target for new product development and should not accumulate independent work.

Linux Container and Linux AppImage checks are optional manual workflows and do not block normal Windows development.

## Runner selection

The product-verification jobs dispatch to the generic GitHub Actions `self-hosted` label plus the repository's Windows/x64 project labels, then immediately verify the actual runner OS/architecture where appropriate.

```text
RUNNER_OS   = Windows
RUNNER_ARCH = X64
```

This deliberately avoids making a maintainer's personal computer identity part of the product contract. The dedicated interactive runner remains a special resource only for tests that genuinely require a logged-on desktop session.

The final `publish-status` job is deliberately different: it does not check out or execute repository code and only projects completed job results back to GitHub commit-status APIs. It runs on a disposable GitHub-hosted runner so terminal status publication cannot sit behind scarce Windows product-verification capacity. The Windows truth still comes exclusively from the three self-hosted required jobs.

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

After registration, keep the runner listener online. For unattended CI across logout/reboot, install/run the GitHub Actions runner using the supported Windows service mode on the runner host where that mode matches the workload. Interactive desktop E2E still requires a real logged-on interactive session.

Then verify repository connectivity with `.github/workflows/zn-self-hosted-runner-check.yml` and confirm a pull request to `main` produces real step execution in `ZN CI`.

## Host safety boundary

A self-hosted runner executes repository-controlled code with the operating-system permissions of its runner account. Therefore:

- prefer a dedicated low-privilege runner account or isolated machine/VM where practical;
- do not store personal secrets, browser profiles, SSH private keys or unrelated credentials in the runner workspace;
- do not grant administrator privileges merely to make ordinary CI pass;
- do not expose release/signing secrets to routine development jobs;
- keep workflow `GITHUB_TOKEN` permissions minimal;
- treat changes that expand runner permissions or secret access as security-sensitive review items.

The steady-state core development workflow currently uses repository contents read access and commit-status write access only.

## Observability

Each main Windows CI job publishes its commit status as `pending` once a runner has actually accepted the job, then the runner-agnostic final status publisher records success/failure without consuming another Windows slot.

This means:

```text
no pending status     = no runner has accepted the job yet
pending               = Windows self-hosted execution is active/accepted
success/failure/error = terminal repository-visible evidence
```

A queued workflow without any pending status is infrastructure availability evidence, not a code-test failure.

For a pull request, the merge decision must use the checks for the current PR head. A green result from an older commit is not a substitute after the branch changes. Post-merge `main` CI is canonical confirmation, not the first merge gate.

## Secondary platforms

The repository retains optional manual Linux workflows so historical mechanisms can still be exercised when useful:

- `zn-linux-container-smoke.yml`;
- `zn-linux-appimage-update-smoke.yml`.

They are not current M8 blockers. Restoring Linux/macOS as intended release targets requires an explicit product decision and corresponding CI/release evidence.
