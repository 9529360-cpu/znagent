# ZN Maintainer Handoff

This is the current engineering work site and fact index, not a chat summary or execution script. Real code, Git state and actual CI remain authoritative.

## Current goal

Move ZN from continuity/recovery hardening into the first real SM1 self-observation slice: preserve privacy-safe evidence when resident organs repeatedly fail, so a later maintenance decision can survive process restarts instead of relying on ephemeral counters.

## Repository state

- Repository: `9529360-cpu/znagent`
- Canonical/release branch: `main`
- Primary development branch: `dev/zn-agent`
- Current verified development head before this work slice: `887963d848840eb6789fefdf7cbe7ce35ef101dd` (PR #55 merge).
- Canonical `main` promotion: PR #56 merged normally at `92934464e6aabdb3f5e73b0ed80449578bc4a52a`.
- Current isolated product branch: `work/resident-health-observation`.
- Exact product head for this health slice before this HANDOFF update: `52be37ac6f7f1705e9a7773e922809c16831ac3d`.
- Temporary validation branch `work/resident-health-observation-validation` exists only to run self-hosted Windows validation and must not be merged as product code.

## Product reality

### Resident continuity and recovery

Recent verified development closed several previously documented gaps:

- PR #47 renews long Work handoff deadlines instead of allowing active long-running Work to age out incorrectly.
- PR #49 hardens fail-closed resident continuity v2 paths.
- PR #50 refreshes the installed resident autostart contract.
- PR #53 proves the installed Windows resident survives desktop termination and restarts from the real `ZN Resident` Scheduled Task while preserving the same resident home/continuity.
- PR #54 proves privacy-preserving durable reference continuity for resident state, Work/thread references, long-term memory and verified learning.
- PR #55 proves atomic-overwrite recovery authority continuity and bounds verified-attempt/terminal-event discharge witnesses to 4096 entries so continuity proof size does not grow without bound over the resident lifetime.

The old HANDOFF statements that persistent autostart and installed-N continuity were still absent are no longer true.

### SM1 resident health observation

The self-maintenance architecture still marks SM1+ as incomplete. A concrete gap was found in the active caller: channel failures were counted only in `ChannelLoopState`, so a resident restart erased the evidence needed to recognize repeated failures.

Current isolated implementation adds:

- `ResidentHealthJournal`, a bounded one-row-per-organ durable health ledger in the resident SQLite body.
- Raw exception messages are never persisted; only exception type plus a SHA-256 fingerprint are retained with total/consecutive failure counts and timestamps.
- `ResidentChannelSupervisor` records real channel poll/delivery failures into the journal and marks recovery after a successful channel cycle.
- Health-journal write failure is deliberately non-fatal to the communication organ.
- Restart/reopen preserves historical totals, while successful recovery resets only the consecutive-failure count.

This is the first connected SM1 observation slice. It does not yet classify failures, create source-maintenance tasks, modify code autonomously, or authorize updater/replacement actions.

## Verification evidence

Verified exact development/canonical evidence before the new SM1 slice:

- Dev merge head `887963d848840eb6789fefdf7cbe7ce35ef101dd`: `ZN CI` run `33235093606` succeeded across Source Boundary, Electron/TypeScript, full Kernel/Python and final status publication.
- Same dev merge head: managed Chromium E2E run `33235093581` succeeded, including real local Chromium E2E.
- Final bounded atomic-continuity product head: dedicated self-hosted Windows validation run `33235058715` succeeded.
- Hosted unsigned-candidate/clean-install jobs during this period repeatedly failed before step 1 with no job steps allocated; treat those runs as hosted-runner infrastructure unavailability, not as product-code passes or failures.

Current SM1 slice evidence:

- Exact product head `52be37ac6f7f1705e9a7773e922809c16831ac3d` was copied to validation branch without product changes.
- Self-hosted Windows validation run `33235652365` succeeded: isolated runtime preparation, compile of `health_observation.py` and `channel_runtime.py`, new durable health tests, and existing channel stop/quiesce lifecycle regressions all passed.
- The new tests prove failure evidence survives reopening the journal, successful recovery clears consecutive failures without erasing history, and a secret-bearing raw error string is absent from both the public health snapshot and SQLite database bytes.

Canonical `main` CI for promotion SHA `92934464e6aabdb3f5e73b0ed80449578bc4a52a` was still running at the time this handoff text was written. Source Boundary and Electron/TypeScript were already successful; Kernel/Python was still executing. Re-check the actual run before claiming canonical post-merge CI success.

## Current risks / real gaps

- SM1 is only partially connected: channel health now survives restart, but visual/provider/body failure observation is not yet unified into the same durable health model.
- Durable health evidence is not yet classified into external service/network/permission/configuration versus probable ZN code defect; therefore it must not automatically create a source-maintenance task yet.
- No maintenance-task deduplication/closure policy is implemented yet.
- Actual N -> N+1 updater/replacement, rollback, release signing/trust, destructive identity/memory migration and replacement of a user's installed formal version remain explicit human-approval boundaries.
- Managed browser mutation beyond the currently authorized structured navigation path remains deliberately constrained and should only expand with replay/authority/postcondition safety.

## Next candidates

1. Merge the verified `work/resident-health-observation` slice into `dev/zn-agent`, run exact dev full CI and inspect active-caller regressions.
2. Re-check canonical `main` post-promotion CI and keep canonical source reasonably synchronized after the health slice is verified.
3. Extend the same health evidence model to another real resident organ (vision/provider/body) only if the active caller can distinguish new failures from stale state without double counting.
4. Add bounded failure classification and maintenance-task formation only after the observation layer is reliable; do not jump directly from an external outage to autonomous source mutation.

No updater/replacement/rollback/signing action is authorized by this handoff.
