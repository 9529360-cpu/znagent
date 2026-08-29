# ZN Implementation Status

This is ZN's current implementation/evidence ledger, not a roadmap or changelog. Real code, Git state and actual test/build/CI results override this file when they disagree. Historical detail remains available in Git history and merged PRs.

## Repository state

- Repository: `9529360-cpu/znagent`
- Primary development branch: `dev/zn-agent`
- Canonical/release branch: `main`
- Current product-code dev head before this documentation reconciliation: `7827b155e18c561dca2f42e26d1817d653a5d03c` (PR #72 merge).
- Canonical `main` currently remains at `d7d06c665daed3400b86d792dd0eeabf16611cbb` (PR #66 merge).
- Canonical main ZN CI run `33262436187` is fully green on `d7d06c66...`.
- Current dev ZN CI run `33269095288` is the authoritative combined validation for PRs #67-#72; Source Boundary and Electron/TypeScript are green and the full Kernel/Python job is still running while this branch is prepared.
- Hosted Windows clean-install/release-candidate push runs continue to terminate before executable steps are allocated in this runner environment. Treat `steps=null`/pre-step termination as infrastructure unavailability, not product pass/fail evidence.
- No force push, history rewrite, destructive migration, updater replacement, rollback, release signing or production credential mutation is part of this stage.

## Capability maturity ledger

Use `exists -> connected -> verified -> product-closed` rather than treating file/interface presence as proof of a real product capability.

| Area | Current maturity | Evidence boundary / remaining gap |
| --- | --- | --- |
| Resident Self / Body / Senses / Situation / Thought / Will | connected + repeatedly verified | ZN-owned resident; zero-model boot remains a required invariant |
| Durable Work / restart recovery | connected + verified | mature Work/recovery path retained through later browser and continuity changes |
| Bounded missing-target Work restore | connected + verified | explicit prepare -> approve; exact retained bytes; no overwrite/replacement authority |
| Managed Chromium + structured navigation | product-path verified for bounded navigation | real local Chromium, durable side-effect attempt, independent URL observation and cleanup |
| Installed resident desktop-independence/autostart | verified | real `ZN Resident` Scheduled Task restores the same resident home/continuity after desktop termination |
| Durable resident reference continuity | verified | resident state, Work/thread references, long-term memory and verified learning survive restart/installed continuity proof |
| Atomic-overwrite recovery continuity | verified + bounded | discharge witnesses capped at 4096 entries |
| Resident channel health observation | connected + verified | real channel success/failure path persists privacy-safe per-organ health across restart |
| Health failure classification | connected + verified, fail-closed | only narrow internal-invariant failures can become `probable_zn_defect`; ambiguous/external failures remain non-candidates |
| Maintenance-task formation | connected + verified | one bounded durable task per organ with repeat threshold, dedup/reopen and recovery/evidence-change closure |
| Maintenance-task failure isolation/reconciliation | connected + verified | health truth commits independently; derived task projection reconstructs from health after task-table faults |
| Resident/RPC maintenance status | connected + verified | formal resident `status()` and existing RPC expose bounded health/task/investigation evidence read-only |
| Channel startup/shutdown lifecycle health | connected + verified | all checkpoints restore before any worker starts; restore failures and stuck shutdown workers produce durable fail-closed health |
| Foreground-window Sense health | connected + verified | real probe exceptions are observed once per actual probe and a real successful probe closes the failure streak |
| Visual capture health | connected + verified | capture exceptions are observed at the capture callable before `NativeVisualSense` flattens them; stale `last_error` is not polled |
| Cognitive provider invocation health | connected + targeted verified | original provider invocation exceptions and real recovery are observed without changing worker semantics; privacy-safe route identity is persisted |
| Cognitive provider resource-construction health | connected + targeted verified | original factory/config/client construction exceptions are observed before kernel flattening; construction success does not falsely clear an invocation failure |
| Native Body dispatch health | connected + targeted verified | original dispatch exceptions are observed in place on the final Body object; returned `success=False` evidence is not misclassified as an exception |
| Maintenance investigation lifecycle | connected + verified as evidence/control state | authoritative maintenance-task truth reconciles to baseline/oracle/attempt/acceptance state; projection failure cannot block health/task truth |
| Maintenance-task-driven source investigation/repair | not yet connected | no active caller binds a maintenance task to a trusted source workspace and runs the read-only source-investigation path |
| Unified resident health | materially expanded, still partial | channel + foreground Sense + visual capture + provider invocation/construction + Body dispatch are connected; other lifecycle/persistence/configuration boundaries remain outside the journal |
| Installed N -> N+1 update continuity | approval-gated / incomplete | no formal updater/replacement transition executed in this stage |
| Rollback / signing / release trust | approval-gated / incomplete | high-risk release/update authority remains outside autonomous SM1/SM2 work |

## SM1 self-maintenance reality

The statement that channel is the only health-connected organ is obsolete. The current connected evidence path is:

```text
real organ failure/success
-> durable privacy-safe health evidence
-> conservative failure class
-> same-fingerprint repeat evidence across restart
-> fail-closed maintenance candidate
-> one durable per-organ maintenance task
-> recovery/evidence-change closure
-> reconstruction if derived task projection fails
-> read-only formal resident/RPC status
```

Real active boundaries now connected to that journal include:

```text
resident channel + channel lifecycle
foreground-window Sense probe
visual capture callable
external cognition provider invocation
external cognition resource construction
Native Body dispatch
```

The maintenance task has also gained a bounded evidence-only investigation lifecycle:

```text
authoritative maintenance task
-> reconciled investigation projection
-> explicit baseline commit reference
-> explicit regression oracle
-> isolated work/* attempt + evidence reference
-> passing-regression gate
-> accepted/rejected evidence state
```

This lifecycle does **not** grant source-write, merge, updater, replacement, rollback, signing or release authority. It is also not yet product-closed: there is still no active task-owned source investigator that binds a trusted ZN source workspace, collects repository/test/CI evidence, and advances a real maintenance incident into ordinary source work.

Important invariants:

- raw exception messages are not persisted in resident health or maintenance-task tables;
- provider route identity in health is hashed and model text/raw route IDs are not persisted there;
- arbitrary Body action-kind strings are hashed before entering health status;
- network/service/environment/configuration failures do not create source-maintenance candidates;
- ambiguous programming/data-contract exceptions remain fail-closed rather than assumed to be ZN defects;
- health/task truth remains authoritative over the secondary investigation projection;
- health observation failures cannot replace Sense/provider/Body behavior;
- provider resource construction does not count as provider recovery; only a real successful invocation clears the same route's invocation failure;
- task/investigation presence grants no source-write, merge, updater, replacement, rollback, signing or release authority.

SM1 remains **partial**. Health coverage is now materially broader and maintenance investigation state exists, but the real maintenance-task -> trusted source workspace -> read-only evidence -> isolated repair candidate path is not yet connected end to end.

## Current exact evidence

Selected earlier continuity/SM1 evidence remains valid for its bounded scenarios. Current stage evidence:

- `33262436187` — canonical main ZN CI success on `d7d06c66...` after PR #66.
- `33266191698` — full dev ZN CI success after foreground-window + visual-capture health integration.
- `33267074693` — maintenance investigation lifecycle targeted validation success.
- `33267155067` — full dev ZN CI success after maintenance investigation lifecycle merge.
- `33268424791` — cognitive provider invocation health targeted validation success.
- `33268678763` — Native Body dispatch health targeted validation success.
- `33269016466` — cognitive provider resource-construction health targeted validation success.
- `33269095288` — current combined dev ZN CI on `7827b155...`; full Kernel/Python completion is pending while this documentation branch is prepared.

PR #70's earlier full dev run `33268511210` was cancelled/superseded by a later dev push and is not counted as passing evidence. Hosted Windows candidate/clean-install jobs that terminate before step 1 remain infrastructure-unavailable evidence only.

## Current product gaps

1. **Maintenance tasks do not yet drive a real source investigation.** The ledger can bound baseline/oracle/attempt/acceptance, but no active caller binds the incident to a trusted source workspace and gathers repository/test/CI evidence under read-only authority.
2. **Unified health is still incomplete.** Major active Sense/provider/Body boundaries are connected, but persistence/life-loop/config-plan and other organ boundaries still need evidence-driven integration rather than blanket wrapping.
3. **Fresh installed-product evidence is unavailable from current hosted jobs.** Recent Windows candidate/clean-install runs terminate before executable steps.
4. **Installed N -> N+1 continuity remains unproven and approval-gated.** Updater/replacement, failed-update recovery, rollback, signing/trust and replacement of the user's current formal installation require explicit human approval.

## Next evidence-driven direction

After the current combined dev CI is green and this factual reconciliation is merged:

- normally promote the coherent verified dev stage to canonical `main` and verify canonical CI;
- define a trustworthy maintenance-source workspace binding and connect one real open maintenance task to a bounded read-only source investigation that can prove repository root, branch/head/dirty state and regression-oracle availability without granting mutation authority;
- only after that read-only path is connected and verified should a high-confidence task be allowed to initiate an isolated `work/*` source attempt;
- continue health integration only at real exception/success boundaries where it closes an actual resident reliability gap;
- updater/replacement/release mutation remains separately approval-gated regardless of source-development maturity.
