# ZN Windows CI topology

> Current intended platform: Windows x64
>
> Canonical integration/source branch: `main`
>
> Development branches: short-lived `work/*` branches created from current `main` and merged through PR.
>
> This file keeps its historical filename so existing repository links do not break.

Updated: 2026-09-16

## Purpose

Ordinary ZN development verification should run on disposable GitHub-hosted Windows x64 whenever the complete acceptance oracle can be reconstructed there.

Self-hosted Windows is a special resource for workflows that genuinely depend on persistent user/session/provider state or release-specific host state. It is not the default correctness oracle, not ZN identity, and not a maintainer-machine product contract.

## Ordinary PR and `main` verification

`.github/workflows/zn-ci.yml` runs on pull requests targeting `main`, pushes to `main`, and manual dispatch. Its required jobs are currently GitHub-hosted `windows-latest` jobs:

- ZN source boundary;
- isolated Python runtime install, zero-model boot and core tests;
- Electron/TypeScript dependency audit, typecheck, bundle and retained desktop/release tests.

Each job verifies that the actual runner is Windows x64 before executing product code.

Path-filtered product integration should also prefer GitHub-hosted Windows when its real acceptance environment can be reconstructed without persistent user credentials or host-specific state. Current hosted examples include Local Documents/Spreadsheet, Research, Document Research, Memory/Learned Behavior, the primary Windows Interactive Desktop Contract, and Windows Clean Install.

Hosted does not mean synthetic-only. The primary Windows Interactive Desktop lane proves a usable interactive Windows desktop before running real Win32/UIA/browser/desktop acceptance, and Windows Clean Install builds and installs the real NSIS candidate in isolated disposable state.

`dev/zn-agent` remains a historical compatibility branch only. It is not a CI integration target for new product development.

## Hosted interactive desktop boundary

The primary PR/push job in `.github/workflows/zn-windows-interactive-contract.yml` runs on `windows-latest`.

Before product acceptance it runs `.github/scripts/test-zn-interactive-desktop-readiness.ps1`, which fails closed unless the runner process is in a non-Session-0, WTS-active user session that can open and switch to the Windows input desktop, observe a same-session foreground window, and acquire foreground for a bounded probe window.

The hosted interactive lane then exercises the current product routes, including the retained Windows application/UIA and browser-to-desktop paths. A runner label by itself is never treated as proof of an interactive desktop.

The same workflow retains a manually dispatched legacy/full diagnostics job that may use the specialized self-hosted `zn-interactive` runner. That manual diagnostic path is separate from the ordinary PR/push acceptance path.

## Hosted clean-install boundary

`.github/workflows/zn-windows-clean-install.yml` runs on disposable GitHub-hosted Windows x64 for applicable PRs and `main` pushes.

Before installing the production-identity candidate it verifies that the disposable machine has no pre-existing ZN process, uninstall registration, or `zn:` protocol registration. The lane then stages the packaged runtime, builds the Electron application and NSIS installer, verifies packaged artifacts and release metadata, installs the real candidate into isolated test state, and starts the installed Desktop/Resident for acceptance.

After a successful `main` clean-install run, CI retains the exact Windows x64 EXE candidate and verified Windows release manifest as a seven-day GitHub Actions artifact for owner/developer evaluation. The retained artifact is an unsigned development candidate. It is not a formal GitHub Release, stable-channel publication, signed production installer, or authorization to replace a user's installed production version. Pull-request runs verify the same clean-install path but do not retain a downloadable installer candidate.

This is install/start verification and a bounded development-evaluation handoff, not authorization to publish a formal release or replace a user's installed production version.

## Specialized self-hosted `zn-interactive` boundary

Self-hosted `zn-interactive` remains valid only where the current workflow genuinely needs host-specific state that ordinary hosted CI does not provide.

Current examples include guarded real-model or existing-session acceptance, selected long-running real integration workflows, release/candidate packaging, runner bootstrap/watchdog maintenance, and manually dispatched legacy interactive diagnostics.

Where a workflow calls `.github/scripts/test-zn-interactive-user-context.ps1`, acceptance requires all of the following current facts:

```text
Windows x64
runner name = zn-interactive
process session != Session 0
current token is not Administrator/elevated
```

The script rejects an Administrator token instead of trusting a runner label or machine name as proof of ordinary-user semantics.

Credential-backed model acceptance remains a separate authorization boundary. Credentials, user profiles and provider secrets must not be copied into ordinary hosted jobs merely to eliminate a specialized runner.

## Release boundary

Formal release and candidate workflows are separate from ordinary development CI. For example, `.github/workflows/zn-release.yml` currently packages Windows on the specialized `zn-interactive` runner for a formal `zn-v*` tag or an explicitly dispatched package run.

Release signing, publishing, stable update-channel mutation, production installer replacement and related trust changes remain high-risk operations. Green ordinary CI or a green clean-install run does not authorize those effects.

If release packaging later becomes reproducible on disposable hosted Windows without weakening its trust boundary, migrate it deliberately and update this document from the real workflow rather than assuming the topology has changed.

## Self-hosted runner lifecycle

Ordinary ZN CI no longer depends on a maintainer-owned self-hosted Windows runner.

Keep self-hosted registration, bootstrap and watchdog infrastructure only while at least one live specialized workflow still needs it. If the last real consumer moves to hosted infrastructure, remove the runner-specific maintenance path instead of preserving an idle second CI architecture.

For specialized self-hosted use:

- prefer a dedicated standard-user account and isolated machine/VM where practical;
- do not store unrelated personal secrets, browser profiles, SSH keys or signing material in the runner workspace;
- do not grant Administrator privileges merely to make ordinary acceptance pass;
- keep real-model and release credentials scoped to the workflows that actually require them;
- treat changes that expand runner permissions, credential access or signing/release trust as security-sensitive.

## Observability and merge evidence

The main ZN CI jobs publish repository commit-status contexts while they execute. Treat those statuses as execution evidence, not as a substitute for checking the actual workflow identity and exact source SHA.

For a pull request, the merge decision must use checks for the current PR head. A green result from an older commit is not valid after the branch changes.

After merge, the `main` push workflows are canonical confirmation for the merge SHA. A queued workflow or missing status is infrastructure/scheduling evidence until a runner has accepted the job; it is not automatically a code failure.

When a specialized self-hosted lane is applicable, inspect its exact current-head result and user-context proof separately. Do not reuse a historical successful run from another head or assume that a generic hosted lane proves credential-backed or release-specific behavior.

## Secondary platforms

The repository retains optional/manual Linux mechanisms for historical or targeted verification. They are not the current Windows product-release baseline.

Restoring Linux or macOS as intended release targets requires an explicit product decision and corresponding build, install, runtime and release evidence.