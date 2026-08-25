# ZN implementation status

> Architecture contract: [`../ZN.md`](../ZN.md)
>
> Memory/learning architecture: [`ZN-MEMORY-LEARNING.md`](ZN-MEMORY-LEARNING.md)
>
> Next phase: [`ZN-NEXT-PHASE.md`](ZN-NEXT-PHASE.md)
>
> Source adoption boundary: [`ZN-SOURCE-EXTRACTION.md`](ZN-SOURCE-EXTRACTION.md)
>
> Self-maintenance contract: [`ZN-SELF-MAINTENANCE.md`](ZN-SELF-MAINTENANCE.md)
>
> Real code, Git state and CI outrank this ledger.

Development branch: `dev/zn-agent`. Canonical source/release branch: `main`.

## 1. Current checkpoint — 2026-08-25

The active repository remains physically ZN-only. M10 canonical source promotion is complete; `main` is canonical source/release and `dev/zn-agent` is the normal development branch.

The current Windows x64 steady-state CI path has recovered on the repository self-hosted runner and the latest reviewed code head has real exact-head evidence:

```text
head  7fe0444a6633536a3678074776c006f41b4dd7b2
run   32826260973

ZN Kernel / Python / Windows        success
ZN Source Boundary / Windows        success
Electron / TypeScript / Windows     success
Publish Windows CI statuses         success
```

The kernel job installed the isolated `znagent` runtime, booted ZN with no model, compiled the resident core, and ran the full Windows working-tree suite: **389 tests passed with 5 platform-appropriate skips**.

The preceding exact-head attempt exposed a test-isolation bug rather than a production Body bug: the CI host had less than ten percent disk free, so ZN correctly reported `body_health = constrained` and focused on `body resources`, while several tests incorrectly assumed every host was nominal. The repair keeps production low-disk sensing intact, gives unrelated cognition tests an explicit healthy-disk fixture, adds a low-disk regression, and closes stores in `finally` paths so Windows temporary-directory cleanup is not masked by SQLite handles.

## 2. Resident ownership — VERIFIED

The resident owns persistent Self/life state, Situation/Thought/Will, durable WorkingState, Investigation, native Body actions and senses, bounded cognition resources, provider settings, nervous memory/reconsolidation, verified experience/procedural tendencies, channel lifecycle and resident work/progress state.

Zero-model boot remains a hard CI contract and passed in run `32826260973`.

## 3. Engineering competence — VERIFIED NARROW SLICES

Current resident-owned engineering behavior includes structured Git state/diff evidence, bounded file/process/terminal/PTTY actions, exact text and command postcondition verification, tracked pre/post Git proof, evidence-bound anti-replay, current-reality-gated alternatives, bounded staging choices, targeted unittest verification and restart-safe side-effect verification.

The current Windows PowerShell kernel verifier contract is recognized strictly and fails closed on shell/runtime/PYTHONPATH/test-suite drift.

Repository-owned verifier selection now includes the bounded manifest:

```text
.agent/zn-engineering-verifiers.json
```

The manifest may declare only literal `target` + `test` relations. It cannot declare command, shell, workdir, timeout or model/task-prose authority. Runtime selection still requires tracked/clean same-HEAD evidence, safe paths, a direct top-level import relation, a discoverable unittest case, the current CI suite contract, execution anti-replay and fresh post-action verification.

Current real manifest relations:

```text
runtime/python/zn_agent/core/repo_test_semantics.py
→ tests/zn_agent/core/test_repo_test_semantics_authority.py

runtime/python/zn_agent/core/git_semantics.py
→ tests/zn_agent/core/test_git_staging_semantics.py
```

The repository manifest self-check verifies every declared relation. Run `32826260973` is the first exact-head Windows CI evidence covering the current manifest, both mappings and the current PowerShell verifier contract.

This remains a narrow engineering competence slice, not an arbitrary-command equivalence engine or unrestricted planner/mutation engine.

## 4. Memory and learning — VERIFIED FOUNDATION, MATURITY PARTIAL

Persistent traces, associations, schema formation, fading/pruning, prediction error, reconsolidation, independently verified episodic evidence and bounded procedural tendencies exist.

General procedural competence, mature computer use, broad local training and long-horizon growth benchmarks remain partial.

## 5. External cognition, web/world and channels — VERIFIED FOUNDATION

Supported model providers are bounded ZN-owned cognitive resources. Provider replacement does not replace resident identity, store or life state.

ZN owns URL/network safety and web resource boundaries. Channel lifecycle is resident-owned. Browser/computer-use Body/Senses remain a future ZN-owned capability seam.

## 6. Desktop ownership — VERIFIED

Active desktop path:

```text
ZN Electron main
→ ZN preload / IPC
→ long-lived resident RPC
→ ZN renderer
```

Ownership tests protect window/protocol lifecycle, preload surface, `zn://` deep links, resident-backed work/provider/progress surfaces, packaged runtime identity, update/application gates and the single formal builder configuration.

Electron development/runtime tooling is pinned to `41.10.5` after the 2026-08-24 security cleanup. Run `32826260973` passed locked install, high-severity npm audit, typecheck, bundle, desktop ownership/runtime/update tests and release/runtime artifact verifier tests.

## 7. Runtime and artifact ownership — VERIFIED FOR EXERCISED TARGETS

Runtime identity:

```text
Python distribution: znagent
Python package:      zn_agent
entrypoint:          zn-resident
```

Historical artifact evidence includes Linux packages, Windows installers, macOS artifacts, fresh Ubuntu installation and installed Linux resident lifecycle evidence. Current steady-state development verification is Windows x64.

## 8. Release/update state — M8 PARTIAL

ZN owns release/update automation. Verified foundations include versioned runtime staging, immutable runtime identity metadata, package verification, channel preparation, `stable.json` last-write ordering and resident update gates.

Still open for the current Windows x64 M8 target:

1. clean Windows install/login evidence;
2. installed Windows N→N+1 continuity evidence;
3. rollback validation across a real Windows version transition;
4. applicable secure Windows signing evidence.

M8 must not be reported complete until those items are exercised. M10 canonical source promotion does not change this status.

## 9. Repository source boundary — COMPLETE AND CI-ENFORCED

Status: **COMPLETE**.

`.agent/verify_zn_source_boundary.py` scans tracked paths and tracked non-binary text to reject retired product identifiers, package namespaces and old physical paths from the active tree. `LICENSE` text is the only explicit scan exception because original legal attribution must remain verbatim.

The historical source quarry remains outside the active tree in the dedicated reference branch/Git history and is not an active runtime/build/test/package/release dependency.

Key evidence:

```text
32669071891   physically reduced ZN-only tree verification
32671245421   exact reviewed pre-M10 PR CI success
32671589664   final canonical main push CI success
32826260973   current dev exact-head Windows source-boundary success
```

## 10. Dependency security state — HIGH-SEVERITY DEBT CLOSED

Electron is on the patched `41.10.5` line. The old `extract-zip` chain is absent from the active Electron dependency path and steady-state CI uses locked install plus `npm audit --audit-level=high`.

The current Windows runner reports Node-action deprecation warnings for actions that still target Node 20 while GitHub forces Node 24. This did not fail run `32826260973`; it is tooling maintenance debt to resolve with verified stable action upgrades, not a reason to weaken CI.

## 11. Self-maintenance — SM0 COMPLETE, SM1+ OPEN

Architecture is defined in `ZN-SELF-MAINTENANCE.md`. ZN does not yet autonomously own the full detect → investigate → isolated fix → PR → CI → merge → release workflow.

High-risk identity/memory/credential/updater/rollback/signing/self-approval changes remain human-approved by default.

## 12. M10 status — COMPLETE

The 2026-08-24 M10 review passed and canonical source promotion was executed by non-forced fast-forward with no history rewrite.

`main` is canonical source/release; `dev/zn-agent` remains the normal development branch. Canonical promotion did not declare M8 complete.

## 13. Current known debts

- M8 Windows clean-install/login, installed N→N+1, rollback and signing evidence;
- browser/computer-use Body/Senses;
- broader resident engineering verifier selection where a real repository-owned relation exists;
- mature procedural competence/growth benchmarks;
- SM1+ autonomous self-maintenance;
- Node-action/deprecation warnings and other non-security third-party tooling warnings should be reduced through stable verified upgrades, without blind forced upgrades.

## 14. Next real targets

```text
1. keep automatic Windows x64 self-hosted CI green on each exact dev HEAD
2. continue resident-owned engineering competence only from real repo-owned structured evidence; do not turn the verifier manifest into a command catalog
3. strengthen browser/computer Body/Senses behind ZN ownership when the next bounded engineering relation is not justified by current evidence
4. close Windows M8 clean-install / N→N+1 / rollback / signing evidence
5. advance SM1+ behind the existing approval and verification boundaries
```

Do not modify `main` through ordinary development. Any later status change must be reflected here only after real code/Git/CI evidence exists.
