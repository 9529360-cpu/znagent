# ZN Implementation Status

This is ZN's current implementation/evidence ledger, not a roadmap or changelog. Real code, Git state and actual test/build/CI results override this file when they disagree. Historical detail remains available in Git history and merged PRs.

## Repository state

- Repository: `9529360-cpu/znagent`
- Primary development branch: `dev/zn-agent`
- Canonical/release branch: `main`
- Latest verified product-code dev head before this documentation reconciliation: `2703aaae5dfacee32f5609c3130f0c607d63b5b2` (PR #64 merge).
- Canonical `main` head before the pending SM1 promotion: `67751e8d69df41eae04a74f28829faaf6304a744` (PR #58 merge).
- Dev ZN CI run `33256153287` is fully green on `2703aaae...` across Source Boundary, Electron/TypeScript, full Kernel/Python and status publication.
- Canonical main ZN CI run `33236277979` is fully green on `67751e8d...`.
- Hosted clean-install run `33256153330` ended with `steps=null`, meaning no executable job steps were allocated. Treat it as infrastructure unavailability, not product pass/fail evidence.
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
| Resident/RPC maintenance status | connected + verified | formal resident `status()` and existing RPC expose bounded health/task evidence read-only |
| Channel startup/shutdown lifecycle health | connected + verified | all checkpoints restore before any worker starts; restore failures and stuck shutdown workers produce durable fail-closed health |
| Maintenance-task-driven investigation/repair | not yet connected | no task-owned provenance/attempt/regression/patch/acceptance lifecycle yet |
| Visual/provider/body unified health | incomplete | channel is the only organ currently wired into the unified journal |
| Installed N -> N+1 update continuity | approval-gated / incomplete | no formal updater/replacement transition executed in this stage |
| Rollback / signing / release trust | approval-gated / incomplete | high-risk release/update authority remains outside autonomous SM1 work |

## SM1 self-maintenance reality

The old statement `SM0 complete; SM1+ not implemented` is obsolete. The connected channel slice now implements and verifies:

```text
real channel failure/success
-> durable privacy-safe health evidence
-> conservative failure class
-> same-fingerprint repeat evidence across restart
-> fail-closed maintenance candidate
-> one durable per-organ maintenance task
-> recovery/evidence-change closure
-> reconstruction if derived task projection fails
-> read-only formal resident/RPC status
```

The channel lifecycle boundary is also closed for the currently known escape paths:

```text
start
-> restore every adapter checkpoint
-> if any restore fails: start zero workers + persist health + re-raise
-> only after all restores succeed: launch workers

stop
-> close adapters + bounded join
-> worker still alive: retain ownership + persist fail-closed TimeoutError health
```

Important invariants:

- raw exception messages are not persisted in health or maintenance-task tables;
- network/service/environment/configuration failures do not create source-maintenance candidates;
- ambiguous programming/data-contract exceptions remain fail-closed rather than assumed to be ZN defects;
- maintenance-task projection is derived from health truth and cannot roll back health failure/recovery;
- task presence grants no source-write, merge, updater, replacement, rollback, signing or release authority;
- one per-organ task bounds task cardinality and avoids repeated-failure task spam.

SM1 is **partial**, not complete. Observation, classification, task formation/reconciliation, read-only consumption and known channel lifecycle failure observation are connected and verified. Autonomous investigation/source repair and other resident organs are not yet connected.

## Current exact evidence

- `33235093606` — earlier bounded atomic-continuity dev ZN CI success.
- `33235093581` — managed Chromium E2E success including real local Chromium.
- `33235058715` — bounded atomic recovery continuity validation success.
- `33235652365` — initial resident channel-health observation validation success.
- `33236277979` — canonical main ZN CI success on `67751e8d...` after PR #58.
- `33236443127` — conservative health-classification validation success.
- `33236842735` — maintenance-task formation validation success.
- `33237072446` — formal resident/RPC maintenance-status validation success.
- `33237199676` — maintenance-task failure-isolation/reconciliation validation success.
- `33237362908` — intermediate combined dev ZN CI success on `05f9086b...`.
- `33237642294` — channel lifecycle health validation success.
- `33256153287` — final product-code dev ZN CI success on `2703aaae...`.

Hosted Windows release-candidate/clean-install jobs that terminate with `steps=null` are infrastructure-unavailable evidence only. Earlier successful installed-product evidence remains valid for the bounded scenarios it exercised but is not fresh proof for the current SM1 head.

## Current product gaps

1. **Other resident organs are outside unified health.** Vision/provider/body need integration at their actual failure/success boundaries. For vision, do not poll persisted `last_error` repeatedly and double-count stale failures.
2. **Maintenance tasks are inspectable evidence, not yet an autonomous repair engine.** A bounded investigation/attempt/regression/patch/acceptance lifecycle is still missing.
3. **Fresh hosted installed-product evidence is unavailable.** Recent hosted Windows jobs fail before step 1.
4. **Installed N -> N+1 continuity remains unproven and approval-gated.** Updater/replacement, failed-update recovery, rollback, signing/trust and replacement of the user's current formal installation require explicit human approval.

## Next evidence-driven direction

After this factual documentation reconciliation and canonical promotion are clean:

- connect another real resident organ, preferably vision, at its true capture failure/success boundary;
- define a bounded maintenance-task investigation contract with provenance, deduped attempts, regression oracle, isolated source branch and acceptance state;
- only after that boundary is verified consider allowing a high-confidence task to initiate ordinary source-maintenance work;
- updater/replacement/release mutation remains separately approval-gated regardless of SM1 source-development maturity.
