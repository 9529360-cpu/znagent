# ZN Maintainer Handoff

This is the current engineering work site and fact index, not a chat transcript or execution script. Real code, Git state and actual test/build/CI results override this file when they disagree.

## Current objective

Continue SM1 from durable self-observation toward a safe maintenance control loop without granting autonomous source mutation or updater/replacement authority prematurely.

The currently connected product path is:

`real resident channel failure -> durable health -> conservative classification -> repeated-fingerprint evidence -> bounded maintenance task -> recovery/evidence reconciliation -> read-only resident/RPC status`

## Repository state

- Repository: `9529360-cpu/znagent`
- Canonical/release branch: `main`
- Primary development branch: `dev/zn-agent`
- Current development head before this documentation reconciliation: `05f9086bb9be5861ebd836c9a5b59c520b85f702` (PR #62 merge).
- Current canonical main head: `67751e8d69df41eae04a74f28829faaf6304a744` (PR #58 merge).
- `main` post-PR58 ZN CI run `33236277979` completed successfully across Source Boundary, Electron/TypeScript, Kernel/Python and status publication.
- Final combined dev ZN CI for `05f9086b...` is run `33237362908`; it was still executing when this isolated documentation branch was created. Re-check the real run before promotion or claiming full combined-CI success.

Temporary `work/*-validation` branches contain validation-only workflows and are not product branches.

## Product reality

### Continuity / resident lifecycle

The earlier continuity stage is materially beyond the old handoff baseline:

- installed Windows resident autostart/desktop-independence was proven through the real `ZN Resident` Scheduled Task;
- durable references for resident state, Work/thread continuity, long-term memory and verified learning were proven;
- atomic-overwrite recovery authority continuity was proven and discharge witnesses were bounded to 4096 entries;
- canonical main already contains the first resident channel-health observation slice through PR #58.

Do not regress Self/identity, lived memory, Work/thread references, Will/intention, learning state, runtime/home/config/provider references, or resident restart/install continuity while extending SM1.

### SM1 self-maintenance state

SM1 is now partially implemented, connected and independently verified for resident channels:

- PR #57: `ResidentHealthJournal` persists one privacy-safe health row per organ; the real `ResidentChannelSupervisor` records failure/recovery through the active channel path.
- PR #59: health evidence gains bounded failure classification and repeated-fingerprint counters across restarts.
- PR #60: classification fails closed. Only narrow internal-invariant signals (`AssertionError`, `NotImplementedError`) can become `probable_zn_defect`; ambiguous programming/data-contract and external/environment failures cannot automatically become source-maintenance candidates.
- PR #61: a repeated high-confidence candidate forms exactly one durable maintenance task per organ; successful recovery closes it; raw exception messages are never persisted.
- PR #63: health truth is authoritative over derived maintenance-task projection. Task write/close failures cannot roll back health failure/recovery, stale tasks close when evidence changes, and task state is reconstructible from health truth after restart.
- PR #62: the formal resident owns a `ResidentHealthJournal` and projects bounded `resident_health` plus `maintenance_tasks` through the existing read-only resident `status()` and therefore the existing RPC status path. No parallel UI-owned control plane was introduced.

Current maturity for this channel slice:

- health storage: connected + verified;
- conservative classification: connected + verified;
- maintenance-task formation/dedup/closure/reconciliation: connected + independently verified;
- resident/RPC read-only consumption: connected + independently verified;
- autonomous investigation/patch/test/PR loop initiated by those tasks: not yet connected;
- updater/replacement/release mutation: not authorized by SM1 and remains approval-gated.

## Exact evidence

- Main canonical ZN CI: `33236277979` — success on `67751e8d69df41eae04a74f28829faaf6304a744`.
- Initial channel health validation: `33235652365` — success.
- Conservative health classification validation: `33236443127` — success.
- Maintenance-task formation validation: `33236842735` — success.
- Resident/RPC maintenance-status validation: `33237072446` — success.
- Maintenance-task reconciliation/failure-isolation validation: `33237199676` — success.
- Final combined dev ZN CI: `33237362908` — pending at documentation-branch creation; verify actual conclusion before promotion.

Hosted Windows clean-install/release-candidate jobs in this period repeatedly failed with `steps=null`, meaning GitHub did not allocate/execute job steps. Treat those as hosted-runner infrastructure unavailability, not as product-code pass/fail evidence.

## Current risks / real gaps

- Only the resident channel organ is wired into the unified health model. Visual/provider/body health still needs active-caller integration; do not poll stale `last_error` state and double-count failures.
- Channel lifecycle faults such as checkpoint-restore failure before worker start and a worker that remains alive after shutdown are not yet unified into durable health evidence.
- A maintenance task is currently evidence/control-plane state only. It does not yet own a bounded investigation, patch, regression, PR, or acceptance lifecycle.
- No automatic source mutation should be triggered from ambiguous/external failures. The current fail-closed classification is an invariant.
- Actual N -> N+1 updater/replacement, rollback, release signing/trust, destructive identity/memory migration, and replacement of a user's installed formal version remain explicit human-approval boundaries.
- Hosted candidate/clean-install infrastructure currently cannot provide fresh installed-product evidence while jobs fail before step 1.

## Next dependency-ready candidates

1. Finish/inspect final combined dev CI `33237362908`; if green, reconcile status docs and promote the verified SM1 slice to `main` through a normal PR, then verify canonical CI.
2. Close channel lifecycle health gaps where failures currently escape the durable health model, especially checkpoint restore/startup and stuck shutdown.
3. Integrate another real resident organ (vision is a strong candidate) at the actual failure/success boundary, not by repeatedly reading stale error state.
4. Define the bounded, read-only-to-write transition for a maintenance task: investigation evidence, deduped attempt ledger, regression oracle, isolated branch and acceptance result. Do not jump directly from task presence to autonomous source mutation.

No updater/replacement/rollback/signing action is authorized by this handoff.