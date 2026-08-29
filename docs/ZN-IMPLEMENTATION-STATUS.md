# ZN Implementation Status

This is ZN's current implementation/evidence ledger, not a roadmap or changelog. Real code, Git state and actual test/build/CI results override this file when they disagree. Historical detail remains available in Git history and merged PRs.

## Repository state

- Repository: `9529360-cpu/znagent`
- Primary development branch: `dev/zn-agent`
- Canonical/release branch: `main`
- Current product-code dev head: `4cd5469edb34cb60622964e5ffa34c3804375252` (PR #75 merge).
- Canonical `main`: `221da814bbab14492e82cf5d4c5e01a65250c4d6` (PR #74 merge).
- Full dev ZN CI run `33271661045` is green on `4cd5469e...`: ZN Source Boundary, Electron/TypeScript and ZN Kernel/Python all succeeded.
- Targeted maintenance-source validation run `33271612132` succeeded before PR #75 merge.
- Canonical main CI for PR #74 is a separate run (`33271494803`); do not substitute dev evidence for canonical evidence.
- Hosted Windows clean-install/release-candidate push jobs can still terminate before executable steps are allocated in the current runner environment. `steps=null`/pre-step termination is infrastructure unavailability, not product pass/fail evidence.
- No force push, history rewrite, destructive identity/memory migration, updater replacement, rollback, release signing or production credential mutation is part of this stage.

## Capability maturity ledger

Use `exists -> connected -> verified -> product-closed`. File/interface presence is not proof that a product capability is closed end to end.

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
| Resident/RPC maintenance status | connected + verified | formal resident/RPC expose bounded health/task/investigation evidence read-only |
| Channel startup/shutdown lifecycle health | connected + verified | all checkpoints restore before workers start; restore failures and stuck shutdown workers produce durable fail-closed health |
| Foreground-window Sense health | connected + verified | real probe exceptions are observed once per actual probe and a successful probe closes the failure streak |
| Visual capture health | connected + verified | capture exceptions are observed at the capture callable before `NativeVisualSense` flattens them |
| Cognitive provider invocation health | connected + verified | original invocation exceptions and real recovery are observed without changing provider semantics |
| Cognitive provider resource-construction health | connected + verified | factory/config/client construction exceptions are observed before kernel flattening; construction success is not invocation recovery |
| Native Body dispatch health | connected + verified | original dispatch exceptions are observed on the final Body; returned `success=False` evidence is not misclassified as an exception |
| Maintenance investigation lifecycle | connected + verified as evidence/control state | authoritative task truth reconciles to baseline/oracle/attempt/acceptance; authority remains `evidence_only` |
| Trusted maintenance source binding | connected + full-CI verified, bounded read-only | exact Git repo root + ZN ownership markers + `9529360-cpu/znagent` origin are required; ordinary Work workspace is not authority |
| Maintenance source-state observation | connected + full-CI verified | fixed Git argv observes HEAD/branch/dirty/bounded changed paths; no shell/terminal/file-write path is used |
| Maintenance regression-oracle binding | connected + full-CI verified, read-only | oracle is restricted to an existing `tests/zn_agent/core/...` test path; it is not executed by this read-only slice |
| Resident maintenance-source evidence projection | connected + full-CI verified | persists privacy-safe repository/fingerprint/head/dirty/oracle evidence; local absolute source root and changed-path list are not persisted |
| Autonomous isolated source repair attempt | not yet connected | no real resident controller creates a clean isolated `work/*` attempt, writes a patch, runs the oracle, reviews diff evidence and records an attempt |
| Unified resident health | materially expanded, still partial | major channel/Sense/provider/Body boundaries are connected; persistence/life-loop/config-plan and other real boundaries remain outside the journal |
| Installed N -> N+1 update continuity | approval-gated / incomplete | no formal updater/replacement transition executed in this stage |
| Rollback / signing / release trust | approval-gated / incomplete | high-risk release/update authority remains outside autonomous source-development work |

## Self-maintenance reality

The active bounded path is now:

```text
real organ failure/success
-> durable privacy-safe health evidence
-> conservative failure class
-> same-fingerprint repeat evidence across restart
-> fail-closed maintenance candidate
-> one durable per-organ maintenance task
-> reconciled evidence-only investigation
-> explicit trusted ZN source root
-> fixed read-only Git observation
-> baseline commit + regression-oracle evidence
-> bounded resident status projection
```

Connected health boundaries include channel/lifecycle, foreground-window Sense, visual capture, external cognition provider invocation/resource construction and Native Body dispatch.

The source-investigation addition in PR #75 is deliberately narrower than repair authority:

```text
open authoritative maintenance task
-> HealthAwareResidentRuntime.investigate_maintenance_source(...)
-> exact repository-root proof
-> ZN ownership-marker proof
-> exact origin identity proof
-> HEAD / branch / dirty / bounded changed-path observation
-> test-path oracle availability proof
-> privacy-safe durable source evidence
-> MaintenanceInvestigationLedger.begin(commit:<HEAD>, oracle)
```

Important invariants:

- ordinary Work workspace association is never silently treated as maintenance-source authority;
- source observation uses fixed `git -C <root> ...` argv and no shell/general terminal capability;
- raw exception messages are not persisted in resident health or task tables;
- provider route identity/model text and arbitrary Body action kinds remain privacy-bounded as previously implemented;
- network/service/environment/config/input failures do not automatically create source-maintenance candidates;
- ambiguous failures remain fail-closed;
- health/task truth is authoritative over derived investigation/source-evidence projections;
- task, investigation or source-evidence presence grants no source-write, branch, merge, updater, replacement, rollback, signing or release authority.

The read-only source slice is **connected and verified**, but self-maintenance is still not product-closed. There is no autonomous maintenance controller that selects an eligible high-confidence incident, creates a clean isolated `work/*` source attempt, applies a bounded repair, executes the oracle, reviews the resulting diff and records the attempt under stale-baseline protection.

## Exact current evidence

Selected evidence relevant to the current stage:

- `33269095288` — earlier combined dev ZN CI success on `7827b155...` after PRs #67-#72.
- `33270265444` — full dev ZN CI success on `cd2d21f...` after the prior health/investigation documentation reconciliation.
- `33271612132` — targeted Windows self-hosted maintenance-source validation success. It compiled affected resident modules and passed source-investigator, formal-resident, investigation-lifecycle and resident-maintenance-status regressions.
- `33271661045` — full dev ZN CI success on `4cd5469e...` after PR #75: ZN Kernel/Python, Electron/TypeScript and ZN Source Boundary all succeeded.

The targeted source tests cover exact ZN root/origin admission, bounded dirty-state evidence, foreign repository/subdirectory/non-test-oracle rejection, closed-task rejection, fixed Git subprocess shape, formal resident connection and status privacy.

Hosted candidate/clean-install jobs that terminate before executable steps remain infrastructure-unavailable evidence only.

## Current product gaps

1. **No autonomous isolated repair attempt.** Read-only source evidence is real; source mutation is intentionally absent. The next product discontinuity is a dedicated isolated-source operator with a fresh baseline, clean `work/*` worktree/branch, narrow mutation scope, fixed regression oracle and bounded diff evidence.
2. **The source-reading call is explicit, not scheduled autonomously.** The formal resident owns the path, but there is not yet a maintenance controller that safely selects which high-confidence task should enter source work. Do not call SM2/SM3 product-closed.
3. **Stale-source protection must precede mutation.** Baseline HEAD drift, unexpected dirty state, wrong branch/worktree ownership or oracle-contract change must fail closed before any future source write.
4. **Unified health remains incomplete.** Add persistence/life-loop/config-plan and other boundaries only at real failure/success sites where evidence shows a meaningful resident reliability gap.
5. **Fresh installed-product evidence is still constrained by hosted-runner availability.** Do not infer installed continuity from pre-step hosted failures.
6. **Installed N -> N+1 continuity remains unproven and approval-gated.** Updater/replacement, failed-update recovery, rollback, signing/trust and replacement of the user's current formal installation require explicit human approval.

## Next evidence-driven direction

- reconcile self-maintenance/HANDOFF status with the verified read-only source slice;
- design the smallest dedicated isolated-source operator that can only operate from a trusted observed baseline into a fresh `work/*` checkout/worktree and cannot write the running installation, `main` or an unknown dirty tree;
- require a fixed regression oracle, bounded diff evidence and stale-baseline checks before the real resident path may call `MaintenanceInvestigationLedger.record_attempt()`;
- verify the isolated attempt path with targeted regressions and whole-tree CI before adding PR/CI automation;
- continue health integration only at active failure/success boundaries where it closes an actual product reliability gap;
- updater/replacement/rollback/signing/release mutation remains separately approval-gated regardless of source-development maturity.