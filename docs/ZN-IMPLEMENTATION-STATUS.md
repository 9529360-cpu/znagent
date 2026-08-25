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

Latest verified implementation head before this ledger sync:

```text
head  83f45fd922ebc216933987d269b3c797d3875f2b
run   32844167956

ZN Kernel / Python / Windows        success
ZN Source Boundary / Windows        success
Electron / TypeScript / Windows     success
Publish Windows CI statuses         success
```

The Windows kernel job created a fresh isolated Python 3.12 environment, installed the `znagent` runtime from `runtime/python`, booted ZN without a model, compiled the resident core, and ran the complete working-tree suite: **393 tests passed with 5 platform-appropriate skips**.

The three new pointer tests passed:

```text
test_pointer_move_is_bounded_normalized_body_movement
test_structured_pointer_move_waits_for_fresh_position_verification
test_pointer_drift_contradicts_success_and_returns_to_investigation
```

This verifies the first bounded computer-action slice without claiming mature computer use.

## 2. Resident ownership — VERIFIED

The resident owns persistent Self/life state, Situation/Thought/Will, durable WorkingState, Investigation, native Body actions and senses, bounded cognition resources, provider settings, nervous memory/reconsolidation, verified experience/procedural tendencies, channel lifecycle and resident work/progress state.

Zero-model boot remains a hard CI contract and passed at exact head `83f45fd922ebc216933987d269b3c797d3875f2b`.

## 3. Engineering competence — VERIFIED NARROW SLICES

Current resident-owned engineering behavior includes structured Git state/diff evidence, bounded file/process/terminal/PTTY actions, exact text and command postcondition verification, tracked pre/post Git proof, evidence-bound anti-replay, current-reality-gated alternatives, bounded staging choices, targeted unittest verification and restart-safe side-effect verification.

The current Windows PowerShell kernel verifier contract is recognized strictly and fails closed on shell/runtime/PYTHONPATH/test-suite drift.

Repository-owned non-canonical verifier selection is bounded by `.agent/zn-engineering-verifiers.json`. The manifest may declare only literal `target` + `test` relations. It cannot declare command, shell, workdir, timeout or model/task-prose authority. Runtime selection still requires tracked/clean same-HEAD evidence, safe paths, a direct top-level import relation, a discoverable unittest case, the current CI suite contract, execution anti-replay and fresh post-action verification.

Current real manifest relations:

```text
runtime/python/zn_agent/core/repo_test_semantics.py
→ tests/zn_agent/core/test_repo_test_semantics_authority.py

runtime/python/zn_agent/core/git_semantics.py
→ tests/zn_agent/core/test_git_staging_semantics.py

runtime/python/zn_agent/core/result_semantics.py
→ tests/zn_agent/core/test_verified_experience.py
```

The third relation is intentionally non-canonical and evidence-based. Run `32829830325` verified all three relations with the live repository self-check and complete Windows kernel suite; later exact-head runs keep the contract green. Do not expand the manifest merely for count.

## 4. Memory and learning — VERIFIED FOUNDATION, MATURITY PARTIAL

Persistent traces, associations, schema formation, fading/pruning, prediction error, reconsolidation, independently verified episodic evidence and bounded procedural tendencies exist.

General procedural competence, mature computer use, broad local training and long-horizon growth benchmarks remain partial.

## 5. Body / Senses / computer interaction — VERIFIED FOUNDATION, MATURITY PARTIAL

Resident-owned visual sensing is a verified foundation: `ResidentSocketService` owns a persistent `NativeVisualSense`; default capture uses local Pillow `ImageGrab`; raw pixels are discarded inside capture; only compact frame/region/luminance structure enters the resident nervous system. The formal runtime declares and installs `Pillow==12.3.0`.

The first bounded computer movement is now verified:

```text
structured event authority
→ NativeActionIntent(kind="pointer_move")
→ resident-owned NativeBody
→ Windows primary-screen pointer movement
→ persist movement result
→ separate native_verification stage
→ fresh pointer_state observation
→ complete only if current cursor position matches the expected bounded position
→ contradiction returns to Investigation and records negative evidence
```

Properties of this slice:

- only typed `pointer_move`; no click, keyboard or generic browser agent;
- only finite normalized primary-screen coordinates in `[0, 1]`;
- no coordinate inference from model prose, task text or procedural memory;
- movement API success is not completion proof;
- fresh cursor position is independently observed after the action;
- drift or contradictory observation fails verification and returns to Investigation;
- active procedural/runtime inheritance was kept compatible with the verification-result contract.

Run `32844167956` verifies this lifecycle with 393 passing core tests. Tests use an injected/fake pointer body and therefore do **not** claim real interactive-desktop click or cursor E2E on the CI host.

Real-session screen capture and interactive-desktop availability/permission remain environmental evidence gaps. Mature click/browser interaction still requires an independent current-world postcondition stronger than an input API return code.

## 6. External cognition, web/world and channels — VERIFIED FOUNDATION

Supported model providers are bounded ZN-owned cognitive resources. Provider replacement does not replace resident identity, store or life state.

ZN owns URL/network safety and web resource boundaries. Channel lifecycle is resident-owned.

## 7. Desktop ownership — VERIFIED

Active desktop path:

```text
ZN Electron main
→ ZN preload / IPC
→ long-lived resident RPC
→ ZN renderer
```

Ownership tests protect window/protocol lifecycle, preload surface, `zn://` deep links, resident-backed work/provider/progress surfaces, packaged runtime identity, update/application gates and the single formal builder configuration.

Electron development/runtime tooling remains pinned to `41.10.5`. Run `32844167956` passed locked install, high-severity npm audit, typecheck, bundle, desktop ownership/runtime/update tests and release/runtime artifact verifier tests.

## 8. Runtime and artifact ownership — VERIFIED FOR EXERCISED TARGETS

Runtime identity:

```text
Python distribution: znagent
Python package:      zn_agent
entrypoint:          zn-resident
```

The runtime project explicitly owns its default visual-capture dependency:

```text
Pillow==12.3.0
```

Fresh isolated Windows runtime installation continues to resolve the declared runtime distribution before zero-model boot and the working-tree suite.

Historical artifact evidence includes Linux packages, Windows installers, macOS artifacts, fresh Ubuntu installation and installed Linux resident lifecycle evidence. Current steady-state development verification is Windows x64.

## 9. Release/update state — M8 PARTIAL

ZN owns release/update automation. Verified foundations include versioned runtime staging, immutable runtime identity metadata, package verification, channel preparation, `stable.json` last-write ordering and resident update gates.

Still open for the current Windows x64 M8 target:

1. clean Windows install/login evidence;
2. installed Windows N→N+1 continuity evidence;
3. rollback validation across a real Windows version transition;
4. applicable secure Windows signing evidence.

M8 must not be reported complete until those items are exercised. M10 canonical source promotion does not change this status.

## 10. Repository source boundary — COMPLETE AND CI-ENFORCED

Status: **COMPLETE**.

`.agent/verify_zn_source_boundary.py` scans tracked paths and tracked non-binary text to reject retired product identifiers, package namespaces and old physical paths from the active tree. `LICENSE` text is the only explicit scan exception because original legal attribution must remain verbatim.

The historical source quarry remains outside the active tree in the dedicated reference branch/Git history and is not an active runtime/build/test/package/release dependency.

Key evidence includes current exact-head Windows Source Boundary success in run `32844167956`.

## 11. Dependency security state — HIGH-SEVERITY DEBT CLOSED

Electron is on the patched `41.10.5` line. The old `extract-zip` chain is absent from the active Electron dependency path and steady-state CI uses locked install plus `npm audit --audit-level=high`.

The Windows workflow still reports Node-action deprecation warnings for actions that target Node 20 while GitHub forces Node 24. This is non-blocking tooling maintenance debt and should be changed only through stable, verified action upgrades.

## 12. Self-maintenance — SM0 COMPLETE, SM1+ OPEN

Architecture is defined in `ZN-SELF-MAINTENANCE.md`. ZN does not yet autonomously own the full detect → investigate → isolated fix → PR → CI → merge → release workflow.

High-risk identity/memory/credential/updater/rollback/signing/self-approval changes remain human-approved by default.

## 13. M10 status — COMPLETE

The 2026-08-24 M10 review passed and canonical source promotion was executed by non-forced fast-forward with no history rewrite.

`main` is canonical source/release; `dev/zn-agent` remains the normal development branch. Canonical promotion did not declare M8 complete.

## 14. Current known debts

- M8 Windows clean-install/login, installed N→N+1, rollback and signing evidence;
- independent post-action evidence strong enough to support a future click/browser mutation rather than merely input-delivery success;
- real-session screen-capture and interactive-desktop availability evidence;
- mature procedural competence/growth benchmarks;
- SM1+ autonomous self-maintenance;
- Node-action/deprecation warnings and other non-security third-party tooling warnings.

## 15. Next real targets

```text
1. keep automatic Windows x64 self-hosted CI green on each exact dev HEAD
2. do not expand the verifier manifest without a genuine repo-owned relation that adds capability
3. investigate the smallest click/browser action whose success can be independently proven from fresh ZN-owned current-world evidence
4. if no such verifier is currently trustworthy, strengthen Senses/current-world evidence before adding another side effect
5. close Windows M8 clean-install / N→N+1 / rollback / signing evidence
6. advance SM1+ behind existing approval and verification boundaries
```

Do not modify `main` through ordinary development. Any later status change must be reflected here only after real code/Git/CI evidence exists.
