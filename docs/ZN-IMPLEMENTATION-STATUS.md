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
> This is the current implementation ledger. Real code, Git state and CI outrank this document.

Active development branch: `dev/zn-agent`. `main` remains untouched until M10 conditions are deliberately reviewed and the user explicitly authorizes promotion.

## 1. Current checkpoint — 2026-08-23

The repository has completed its physical transition to a ZN-only active tree.

Current product topology:

```text
runtime/python/zn_agent/core/   resident implementation
runtime/python/zn_agent/        installed Python package
tests/zn_agent/core/             core verification
apps/desktop/electron/           ZN Electron control plane
apps/desktop/src/zn/             ZN renderer
apps/desktop/scripts/            ZN build/runtime/release tooling
.github/workflows/               ZN CI/update/release automation
```

The previous transitional physical core path is gone from `dev/zn-agent`. Root development metadata is ZN-owned; the old root Python distribution and unrelated product workspaces/source trees are absent.

Bulk evacuation commit:

```text
6d5f78d22883857fcc99aff5cfd4ba1b9a2d3e6b
refactor: evacuate inherited source from ZN
```

The one-shot verifier run `32669071891` validated the physically reduced tree before committing it:

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

The migration script deleted itself in the verified commit. The temporary one-shot CI job was retired immediately afterward; steady-state CI no longer has write permission to repository contents.

## 2. Resident ownership — VERIFIED

The resident is not a model-owned planner loop. Current implementation owns:

- durable Self/life state;
- Situation / Thought / Will;
- durable events and WorkingState;
- multi-pulse Investigation;
- native Body actions and structured senses;
- bounded external cognition resources;
- provider settings and secure credential references;
- persistent nervous memory, association, schema formation and reconsolidation;
- verified experience and procedural-tendency learning;
- channel lifecycle and restart-safe delivery state;
- resident work ledger and progress state.

Zero-model boot is a hard contract and is exercised by CI.

## 3. Body, verification and engineering competence — VERIFIED NARROW SLICES

Current resident-owned engineering behavior includes:

- structured read-only Git repository state;
- structured scoped Git diff evidence;
- bounded file/process/terminal/PTTY actions;
- exact text postcondition verification;
- explicit command postcondition verification;
- tracked exact-replacement pre-action Git baseline and post-action scoped delta proof;
- evidence-bound failed-action anti-replay;
- current-reality-gated structured alternatives;
- bounded resident-owned Git staging choices;
- fresh Git-state verification after staging;
- independently verified `VerifiedExperience` records;
- repeated-evidence procedural tendencies and bounded current-reality influence;
- targeted Python unittest verification for the tracked exact-replacement slice;
- resident-owned mirrored unittest identity formation under the repository's proven convention;
- restart-safe anti-replay semantics for potentially side-effecting verifier execution.

These are deliberately bounded. They are not a general arbitrary-command equivalence engine, unrestricted planner, general mutation engine or proof that any guessed test belongs to any changed file.

## 4. Memory and learning — VERIFIED FOUNDATION, MATURITY STILL PARTIAL

Implemented foundations include:

- persistent neural traces;
- repeated compatible experience strengthening existing traces;
- co-activation associations and spreading activation;
- fading/pruning of weak isolated detail;
- schema formation;
- reality-gated transfer;
- prediction error and reconsolidation;
- independently verified episodic execution evidence;
- transparent candidate procedural tendencies;
- current-reality applicability;
- low-risk bounded procedural influence;
- contradiction/inhibition paths.

Still not claimed complete:

- general resident procedural skill substrate across broad domains;
- mature learned computer-use competence;
- broad local policy/model training;
- general procedural fast path across arbitrary tasks;
- comprehensive growth benchmarks proving reduced external cognition over long practice horizons.

## 5. External cognition and provider ownership — VERIFIED

The production resident uses ZN-owned resource boundaries for supported provider families. Provider replacement does not replace resident identity, store or life state.

Important guarantees:

- model responses are bounded cognitive increments, not world truth;
- missing remote credentials may degrade cognition availability without killing the resident;
- secure credential storage has no plaintext fallback when unavailable;
- renderer does not receive stored provider secrets;
- provider reconfiguration does not reconstruct a new subject.

## 6. Web/world and channel ownership — VERIFIED FOUNDATION

ZN owns its web/world resource boundary, URL safety and provider failover behavior.

Channel lifecycle is resident-owned; Telegram coverage includes authorization, restart-safe checkpoints, inbound attachment handling, outbound document authorization and bounded delivery behavior. Channels are I/O organs for the same resident, not separate agents.

Browser/computer-use Body/Senses remain a future owned capability seam. No external browser/session product should become the resident control plane.

## 7. Desktop ownership — VERIFIED

The active desktop is ZN-owned:

```text
ZN Electron main
→ ZN preload / IPC
→ long-lived resident RPC
→ ZN renderer in src/zn
```

Current ownership tests protect:

- window/protocol lifecycle;
- preload bridge surface;
- `zn://` deep-link behavior;
- resident-backed provider/work/progress surfaces;
- packaged runtime identity;
- update/readiness/application gates;
- one formal `electron-builder.zn.yml` product configuration.

The root Node workspace contains only the ZN desktop workspace.

## 8. Runtime and artifact ownership — VERIFIED FOR EXERCISED TARGETS

Runtime identity:

```text
Python distribution: znagent
Python package:      zn_agent
entrypoint:          zn-resident
```

Historical real artifact evidence exists for:

- Linux AppImage/deb/rpm;
- Windows NSIS/MSI;
- macOS arm64 DMG/ZIP;
- fresh Ubuntu deb installation;
- installed Linux resident autostart/start-stop continuity.

Current package/runtime verifiers require the ZN resident core and reject foreign product package content.

## 9. Release/update state — M8 PARTIAL

Release ownership is ZN-owned, but release continuity is not complete.

Verified foundations include:

- versioned runtime staging;
- immutable runtime identity metadata;
- package verification;
- release-channel preparation;
- stable-channel publication ordering with `stable.json` written last;
- resident update readiness/application gates;
- Linux installed package/autostart evidence.

Still open for M8:

1. installed N → N+1 application/runtime/resident handoff evidence;
2. intended Windows/macOS clean-install/login continuity evidence where those platforms remain release targets;
3. signing/notarization using the real secure release process;
4. rollback validation across a real version transition;
5. any final release-matrix evidence required before M10.

Do not report M8 complete until these are actually exercised.

## 10. Self-maintenance — SM0 COMPLETE, SM1+ OPEN

Architecture is defined in `ZN-SELF-MAINTENANCE.md`.

Current project infrastructure already supports human/model maintainers using isolated branches, PRs, CI and repository release automation. ZN itself does not yet autonomously own the full detect → investigate → isolated fix → PR → CI → merge → release workflow.

High-risk identity/memory/credential/updater/rollback/signing/self-approval changes remain human-approved by default.

## 11. Repository source boundary — COMPLETE

Status: **COMPLETE on `dev/zn-agent`**.

The active tree no longer carries the historical product source quarry. Reference access is through Git history or an external/upstream repository only.

Steady-state rule:

```text
need mature mechanism
→ inspect external/history reference
→ understand mechanism
→ adapt behind ZN ownership
→ test ZN behavior
→ keep active repository source-independent
```

The migration-only baseline document and one-shot migration machinery are retired.

## 12. Known risks

Current known engineering risks/debts:

- M8 continuity/signing gaps listed above;
- browser/computer-use ownership still incomplete;
- resident engineering verifier mapping remains deliberately narrow;
- general procedural competence is still partial;
- npm install during the evacuation verifier reported two high-severity dependency advisories; these require dependency-tree investigation rather than blind forced upgrades;
- `main` still represents the pre-M10 branch state and must not be changed before explicit M10 review/authorization.

## 13. M10 status — NOT YET COMPLETE

Source independence is now satisfied on `dev/zn-agent`, but that is only one M10 condition.

Before promotion, re-evaluate current evidence for:

- resident/runtime ownership;
- desktop ownership;
- build/release ownership;
- reproducible current CI;
- provenance/license obligations;
- M8 release-continuity risk;
- current open PR/CI state;
- explicit user authorization.

Until that review concludes that the full contract is satisfied, `main` remains untouched.

## 14. Next real targets

Priority order after the source-boundary cleanup:

```text
1. finish post-evacuation repository/doc/CI audit
2. investigate the reported Node high-severity advisories without forced upgrades
3. resume resident-owned engineering competence from the physical zn_agent core
4. close M8 installed N→N+1 continuity and intended-platform release gaps
5. advance SM1+ self-maintenance only behind existing safety boundaries
6. evaluate M10 from fresh evidence, never from migration optimism
```

Any later status change must be reflected here only after real code/CI evidence exists.