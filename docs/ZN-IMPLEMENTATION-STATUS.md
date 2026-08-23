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

Development branch: `dev/zn-agent`. Canonical source branch: `main`.

## 1. Current checkpoint — 2026-08-24

The active repository is physically ZN-only. M10 canonical source promotion is complete.

Current topology:

```text
runtime/python/zn_agent/core/   resident implementation
runtime/python/zn_agent/        installed Python package
tests/zn_agent/core/            core verification
apps/desktop/electron/          ZN Electron control plane
apps/desktop/src/zn/            ZN renderer
apps/desktop/scripts/           ZN build/runtime/release tooling
.github/workflows/              ZN CI/update/release automation
```

Bulk source evacuation commit:

```text
6d5f78d22883857fcc99aff5cfd4ba1b9a2d3e6b
```

Verified one-shot run `32669071891` proved the reduced tree before committing it:

```text
fresh ZN-only Node lock/install          success
isolated ZN Python install               success
zero-model resident boot                 success
Python core unittest discovery           382 passed
desktop typecheck/bundle                 success
desktop vitest                           37 passed
retained Node release/runtime tests      8 passed
ZN-only Docker build + zero-model boot   success
verified deletion commit/push            success
```

The migration script and migration-only CI write path are retired.

## 2. Resident ownership — VERIFIED

The resident owns persistent Self/life state, Situation/Thought/Will, durable WorkingState, Investigation, native Body actions and senses, bounded cognition resources, provider settings, nervous memory/reconsolidation, verified experience/procedural tendencies, channel lifecycle and resident work/progress state.

Zero-model boot remains a hard CI contract.

## 3. Engineering competence — VERIFIED NARROW SLICES

Current resident-owned engineering behavior includes structured Git state/diff evidence, bounded file/process/terminal/PTTY actions, exact text and command postcondition verification, tracked pre/post Git proof, evidence-bound anti-replay, current-reality-gated alternatives, bounded staging choices, targeted unittest verification and restart-safe side-effect verification.

This is not a general arbitrary-command equivalence engine or unrestricted planner/mutation engine.

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

## 7. Runtime and artifact ownership — VERIFIED FOR EXERCISED TARGETS

Runtime identity:

```text
Python distribution: znagent
Python package:      zn_agent
entrypoint:          zn-resident
```

Historical artifact evidence includes Linux packages, Windows installers, macOS artifacts, fresh Ubuntu installation and installed Linux resident lifecycle evidence.

## 8. Release/update state — M8 PARTIAL

ZN owns release/update automation. Verified foundations include versioned runtime staging, immutable runtime identity metadata, package verification, channel preparation, `stable.json` last-write ordering, resident update gates and Linux installed/update smoke infrastructure.

Still open for M8:

1. intended Windows/macOS clean-install/login continuity where those remain formal targets;
2. real secure signing/notarization evidence;
3. rollback validation across a real version transition;
4. remaining release-matrix evidence required before formal release-complete claims.

M8 must not be reported complete until these are exercised. M10 canonical source promotion does not change this status.

## 9. Repository source boundary — COMPLETE AND CI-ENFORCED

Status: **COMPLETE**.

`.agent/verify_zn_source_boundary.py` scans tracked paths and tracked non-binary text to reject retired product identifiers, package namespaces and old physical paths from the active tree. `LICENSE` text is the only explicit scan exception because original legal attribution must remain verbatim.

The historical source quarry is preserved outside the active tree in a dedicated reference branch at the old baseline. It is not an active runtime/build/test/package/release dependency.

Key evidence:

```text
32671245421   exact reviewed PR CI success
32671435423   canonical main push CI success
```

On the canonical push run, Source Boundary, Python and Electron were successful. Container smoke is intentionally skipped on push by workflow design; it was successful on the exact reviewed PR commit before promotion.

## 10. Dependency security state

A normal full `npm ci` still reports two high-severity findings in the complete development/tooling dependency graph.

CI includes:

```text
npm audit --omit=dev --audit-level=high
```

The production-dependency gate passes. Therefore the two known high findings are currently bounded to development/tooling dependencies, not accepted production/runtime dependencies.

The exact development dependency chain remains to be traced and fixed where a safe stable update exists. Do not use blind forced audit fixes.

## 11. Self-maintenance — SM0 COMPLETE, SM1+ OPEN

Architecture is defined in `ZN-SELF-MAINTENANCE.md`. ZN does not yet autonomously own the full detect → investigate → isolated fix → PR → CI → merge → release workflow.

High-risk identity/memory/credential/updater/rollback/signing/self-approval changes remain human-approved by default.

## 12. M10 status — COMPLETE FOR CANONICAL SOURCE PROMOTION

The 2026-08-24 M10 review in `ZN.md` passed and the canonical source promotion was executed.

Verified/reviewed:

- ZN-owned resident/runtime and persistent-state boundary;
- ZN-owned desktop and product identity;
- ZN-owned build/package/release automation;
- CI-enforced active source boundary;
- preserved license/provenance obligations;
- historical source separated into a dedicated reference branch;
- production npm high-severity audit gate passes;
- unresolved M8 gaps explicitly remain **PARTIAL** and are accepted for canonical branch promotion only, not formal release-complete claims;
- user explicitly authorized promotion after cleanup;
- exact reviewed commit `c158517225ff7b8cf0a952a0ae1dd6ebcf9c2c5d` passed full PR CI run `32671245421`;
- `main` was non-forced fast-forwarded to that reviewed commit with no history rewrite;
- canonical `main` push CI run `32671435423` then passed for the promotion-record state.

Future documentation-only synchronization commits do not reopen M10. Their exact current CI state must still be checked from GitHub before reporting them green.

## 13. Current known debts

- two high-severity development/tooling npm findings need exact dependency-path investigation;
- M8 intended-platform continuity/signing/rollback gaps;
- browser/computer-use Body/Senses;
- broader resident engineering verifier selection;
- mature procedural competence/growth benchmarks;
- SM1+ autonomous self-maintenance.

## 14. Next real targets

```text
1. keep main and dev/zn-agent synchronized after final documentation closeout
2. retire verification-only PR #5 without merge
3. trace/fix development-tooling npm advisory paths
4. resume resident-owned engineering competence
5. close remaining M8 continuity/signing/rollback evidence
6. advance SM1+ behind existing safety boundaries
```

Any later status change must be reflected here only after real code/Git/CI evidence exists.