# ZN Maintainer Handoff

This is the current engineering work site and fact index, not a chat transcript or execution script. Real code, Git state and actual test/build/CI results override this file when they disagree.

## Current objective

Continue SM1 from durable self-observation toward a safe maintenance control loop without prematurely granting autonomous source mutation or updater/replacement authority.

The connected resident-channel path is now:

`real failure/success -> durable health -> conservative classification -> repeated-fingerprint evidence -> bounded maintenance task -> recovery/evidence reconciliation -> read-only resident/RPC status`

Channel startup/shutdown lifecycle failures are also health-visible: checkpoint recovery is two-phase before any worker starts, and a worker that remains alive after shutdown timeout records fail-closed durable health evidence.

## Repository state

- Repository: `9529360-cpu/znagent`
- Canonical/release branch: `main`
- Primary development branch: `dev/zn-agent`
- Latest verified product-code dev head before this documentation reconciliation: `2703aaae5dfacee32f5609c3130f0c607d63b5b2` (PR #64 merge).
- Canonical `main` head before the pending SM1 promotion: `67751e8d69df41eae04a74f28829faaf6304a744` (PR #58 merge).
- `main` ZN CI run `33236277979` is fully green on `67751e8d...`.
- Final product-code dev ZN CI run `33256153287` is fully green on `2703aaae...` across Source Boundary, Electron/TypeScript, full Kernel/Python and status publication.
- Intermediate combined dev ZN CI run `33237362908` is also fully green on `05f9086b...` before PR #64.
- Hosted clean-install run `33256153330` failed with `steps=null`; GitHub allocated no executable job steps, so this is infrastructure unavailability rather than product pass/fail evidence.

Temporary `work/*-validation` branches contain validation-only workflows and must not be merged as product code.

## Product reality

### Continuity / resident lifecycle

Recent verified work already established:

- installed Windows resident desktop-independence/autostart through the real `ZN Resident` Scheduled Task;
- durable reference continuity for resident state, Work/thread references, long-term memory and verified learning;
- bounded atomic-overwrite recovery continuity with discharge witnesses capped at 4096 entries;
- canonical `main` contains the first resident channel-health observation slice through PR #58.

Protect Self/identity, lived memory, Work/thread references, Will/intention, learning state, runtime/home/config/provider references and resident restart/install continuity while extending SM1.

### SM1 resident health and maintenance evidence

Verified connected channel work:

- PR #57: `ResidentHealthJournal` persists one privacy-safe health row per organ and the real `ResidentChannelSupervisor` records channel failure/recovery.
- PR #59/#60: bounded repeated-fingerprint classification with fail-closed semantics. Only narrow internal invariant failures (`AssertionError`, `NotImplementedError`) may become `probable_zn_defect`; ambiguous programming/data-contract and external/environment failures do not automatically become source-maintenance candidates.
- PR #61: repeated high-confidence evidence forms exactly one durable maintenance task per organ; recovery closes it; raw exception messages are not persisted.
- PR #63: health truth is authoritative over derived maintenance-task projection. Task projection faults cannot roll back health observations; stale/orphaned task state is reconciled from health truth.
- PR #62: formal resident ownership exposes bounded `resident_health` and `maintenance_tasks` through existing read-only resident/RPC `status`, without a parallel UI-owned control plane.
- PR #64: channel checkpoint restore is all-or-nothing before worker start, checkpoint-restore failures enter durable health, and stuck shutdown workers record fail-closed `TimeoutError` health evidence while remaining owned for teardown.

Current maturity:

- channel health observation: connected + verified;
- conservative classification: connected + verified;
- maintenance-task formation/dedup/closure/reconciliation: connected + verified;
- resident/RPC read-only consumption: connected + verified;
- channel startup/shutdown lifecycle health: connected + verified;
- visual/provider/body unified health: not yet connected;
- maintenance-task-driven investigation/patch/regression/PR lifecycle: not yet connected;
- updater/replacement/rollback/signing/release trust: outside SM1 authority and still human approval-gated.

## Exact evidence

- `33235652365` — initial channel-health validation success.
- `33236277979` — canonical main ZN CI success on `67751e8d...`.
- `33236443127` — conservative classification validation success.
- `33236842735` — maintenance-task formation validation success.
- `33237072446` — formal resident/RPC maintenance-status validation success.
- `33237199676` — maintenance-task failure-isolation/reconciliation validation success.
- `33237362908` — combined dev ZN CI success on `05f9086b...`.
- `33237642294` — channel lifecycle health validation success.
- `33256153287` — final product-code dev ZN CI success on `2703aaae...`.

Recent hosted Windows candidate/clean-install jobs that end with `steps=null` remain infrastructure-unavailable evidence only; do not label them product passes or failures.

## Current risks / real gaps

- Vision/provider/body are still outside the unified health model. Integrate only at the real failure/success boundary; for vision, do not repeatedly poll persisted `last_error` and double-count stale failures.
- A maintenance task remains evidence/control-plane state. It does not yet own a bounded investigation, attempt ledger, regression oracle, patch or acceptance lifecycle.
- No automatic source mutation should be triggered from ambiguous/external failures. Fail-closed classification is a safety invariant.
- Fresh hosted installed-product evidence is currently unavailable while hosted jobs fail before step 1.
- Actual N -> N+1 updater/replacement, failed-update recovery, rollback, release signing/trust, destructive identity/memory migration and replacement of a user's formal installation require explicit human approval.

## Next dependency-ready candidates

1. Merge this factual documentation reconciliation, verify the docs-only dev head, then normally promote the verified SM1 stage to canonical `main` and verify canonical CI.
2. Connect another real resident organ to the same health model at its true failure/success site; vision is the strongest current candidate.
3. Define a bounded maintenance-task investigation lifecycle with provenance, deduped attempts, regression oracle, isolated branch and acceptance state before allowing a task to initiate ordinary source work.
4. Keep updater/replacement/rollback/signing and release trust outside this autonomous path.

No updater/replacement/rollback/signing action is authorized by this handoff.