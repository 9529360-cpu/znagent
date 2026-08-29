# ZN Implementation Status

This is ZN's current implementation/evidence ledger, not a mandatory roadmap and not a changelog. Real code, Git state and actual test/build/CI results override this file when they disagree. Historical detail remains available in Git history and merged PRs.

## Repository state

- Repository: `9529360-cpu/znagent`
- Primary development branch: `dev/zn-agent`
- Canonical/release branch: `main`
- Development head before this status reconciliation: `05f9086bb9be5861ebd836c9a5b59c520b85f702` (PR #62 merge).
- Canonical main head: `67751e8d69df41eae04a74f28829faaf6304a744` (PR #58 merge).
- Canonical main ZN CI run `33236277979` is fully green.
- Combined dev ZN CI run `33237362908` for `05f9086b...` was still executing when this isolated documentation branch was created; use its actual conclusion before promotion.
- No force push, history rewrite, destructive migration, updater replacement, rollback, release signing, or production credential mutation is part of the current stage.

## Capability maturity ledger

Use `exists -> connected -> verified -> product-closed` rather than treating file/interface presence as proof of a real product capability.

| Area | Current maturity | Evidence boundary / remaining gap |
| --- | --- | --- |
| Resident Self / Body / Senses / Situation / Thought / Will | connected + repeatedly verified | ZN-owned resident; zero-model boot remains a required invariant |
| Durable Work / restart recovery | connected + verified | mature Work/recovery path retained through later browser and continuity changes |
| Work restore inspection | connected + verified | read-only restore inspection is available through resident/desktop |
| Missing-target Work restore application | connected + verified for bounded scenario | explicit prepare -> approve; missing target only; exact retained bytes; no overwrite/replacement authority |
| Managed Chromium runtime | connected + verified | versioned Windows runtime owns Playwright/Chromium; structured navigation has real local Chromium E2E evidence |
| Structured browser Work navigation | product-path verified for bounded navigation | durable side-effect attempt -> real Chromium -> independent URL observation -> cleanup -> Work completion |
| Browser mutation beyond granted navigation | intentionally not granted | click/type/select/upload/download remain outside current Work authority unless separately designed and verified |
| Installed resident desktop-independence/autostart | verified | real `ZN Resident` Scheduled Task survives desktop termination and restores the resident using the same home/continuity |
| Durable resident reference continuity | verified | resident state, Work/thread references, long-term memory and verified learning survive restart/installed continuity proof without persisting raw secret/provider values |
| Atomic-overwrite recovery continuity | verified + bounded | verified-attempt/terminal-event discharge witnesses capped at 4096 so resident-lifetime proof size is bounded |
| Resident channel health observation | connected + verified | real channel success/failure path persists privacy-safe per-organ health across restart |
| Health failure classification | connected + verified, fail-closed | only narrow internal-invariant failures can become `probable_zn_defect`; ambiguous/external failures remain non-candidates |
| Maintenance-task formation | connected + independently verified | one bounded durable task per organ; repeat threshold, dedup/reopen, recovery closure and evidence-change closure are verified |
| Maintenance-task failure isolation/reconciliation | connected + independently verified | health truth commits independently; derived task projection can be reconstructed from health after task-table write faults |
| Resident/RPC maintenance status | connected + independently verified | formal resident `status()` and existing RPC expose bounded health/task evidence read-only |
| Maintenance-task-driven investigation/repair | not yet connected | no task-owned investigation/patch/regression/PR lifecycle yet |
| Visual/provider/body unified health | incomplete | only channel active caller currently feeds the unified health journal |
| Installed N -> N+1 update continuity | approval-gated / incomplete | no formal updater/replacement transition has been executed in this stage |
| Rollback / signing / release trust | approval-gated / incomplete | high-risk release/update authority remains outside autonomous SM1 work |
| Formal release/stable publication | incomplete for current SM1 stage | no tag/stable-channel/user-machine replacement is implied by development promotion |

## SM1 self-maintenance reality

The old blanket statement `SM0 complete; SM1+ not implemented` is obsolete.

The connected channel slice now implements and verifies the early SM1 control path:

```text
real channel failure
-> durable privacy-safe health evidence
-> conservative failure class
-> same-fingerprint repeat evidence across restart
-> fail-closed maintenance candidate
-> one durable per-organ maintenance task
-> recovery/evidence-change closure
-> reconstruction if derived task projection fails
-> read-only formal resident/RPC status
```

Important invariants:

- raw exception messages are not persisted in the health or maintenance-task tables;
- a network/service/environment/configuration failure is not enough to create a source-maintenance candidate;
- ambiguous programming/data-contract exceptions remain fail-closed rather than being assumed to be ZN source defects;
- maintenance-task projection is derived from health truth and cannot roll back health failure/recovery;
- maintenance task presence does not grant source-write, merge, updater, replacement, rollback, signing, or release authority;
- one per-organ task bounds task cardinality and avoids repeated-failure task spam.

SM1 is therefore **partial**, not complete. Observation/classification/task formation/reconciliation/read-only consumption are connected for resident channels; autonomous investigation and source repair are not yet connected, and other organs are not yet unified.

## Current exact evidence

- `33235093606` — ZN CI success on the bounded atomic-continuity dev merge stage.
- `33235093581` — managed Chromium E2E success including real local Chromium.
- `33235058715` — bounded atomic recovery continuity validation success.
- `33235652365` — initial resident channel-health observation validation success.
- `33236277979` — canonical main ZN CI success on `67751e8d69df41eae04a74f28829faaf6304a744` after PR #58.
- `33236443127` — conservative health-classification validation success.
- `33236842735` — maintenance-task formation validation success.
- `33237072446` — formal resident/RPC maintenance-status validation success.
- `33237199676` — maintenance-task failure-isolation/reconciliation validation success.
- `33237362908` — combined dev ZN CI for `05f9086bb9be5861ebd836c9a5b59c520b85f702`; pending at documentation-branch creation and must be re-checked before promotion.

Hosted Windows release-candidate and clean-install jobs during the current period repeatedly terminated with `steps=null`, meaning no job steps were allocated/executed. Treat that as hosted-runner infrastructure unavailability, not as product-code pass or failure. Earlier successful installed-product evidence remains historical evidence for the bounded scenarios it exercised; it is not fresh proof for the current SM1 head.

## Current product gaps

Highest-value open gaps after the current SM1 channel slice:

1. **Other resident organs are outside unified health.** Vision/provider/body need integration at their actual active failure/success boundary. For vision, do not repeatedly poll persisted `last_error`, which could double-count a stale failure.
2. **Channel lifecycle failures are incomplete.** Startup checkpoint-restore failure and a channel worker that remains alive after requested shutdown are not yet unified into durable health evidence.
3. **Maintenance tasks are inspectable evidence, not an autonomous repair engine.** A bounded investigation/attempt/regression/patch/acceptance lifecycle still needs design and connection before task presence may drive source work.
4. **Installed N -> N+1 continuity remains unproven.** Updater/replacement, failed-update recovery, rollback, signing/trust and replacement of a user's current formal installation remain explicit approval boundaries.
5. **Hosted fresh install/release evidence is currently blocked by infrastructure.** Recent hosted Windows jobs fail before step 1, so do not infer product failure or success from them.

## Next evidence-driven direction

After final combined dev CI and canonical promotion are clean, prefer another vertical SM1 slice over broad framework expansion:

- first close real channel lifecycle health escapes or connect vision at its true capture exception/success site;
- then define a bounded maintenance-task investigation contract with deduped attempts, explicit evidence, a regression oracle, isolated source branch and acceptance state;
- only after that boundary is verified should ZN consider automatically initiating ordinary source-maintenance work from a high-confidence task;
- updater/replacement/release mutation remains separately approval-gated regardless of SM1 source-development maturity.
