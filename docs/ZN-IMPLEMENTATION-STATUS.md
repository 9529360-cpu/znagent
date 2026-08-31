# ZN Implementation Status

This is ZN's implementation/evidence ledger, not a roadmap or changelog. Real code, live Git refs and actual test/build/CI results override this file when they disagree.

## Repository state contract

- Repository: `9529360-cpu/znagent`
- Primary development branch: `dev/zn-agent`
- Canonical/release branch: `main`
- Exact SHAs below are evidence checkpoints, not permanent branch oracles. Fresh maintainers must query live refs, PRs and CI.
- No force push, history rewrite, destructive identity/memory migration, updater replacement, rollback, release signing or production credential mutation is authorized by this stage.

Maintenance rule:

```text
verified coherent product slice
-> reconcile changed implementation truth + HANDOFF
-> normal dev -> main promotion
-> verify canonical CI
-> keep long-lived branches reasonably synchronized
```

Repository synchronization is engineering hygiene, not a product milestone.

## Installed-upstream authority contract

Normal installed ZN may know and verify its official update channel and may form bounded privacy-safe BUG/repair reports. That does not grant private source-repository credentials or official push/PR/merge/release/signing authority.

```text
official upstream update channel -> installed ZN
installed ZN -> bounded BUG / repair report channel
```

## Capability maturity ledger

Use `exists -> connected -> verified -> product-closed`. File/interface presence is not proof of product closure.

| Area | Current maturity | Evidence boundary / remaining gap |
| --- | --- | --- |
| Resident Self / Body / Senses / Situation / Thought / Will | connected + repeatedly verified | ZN-owned resident; zero-model boot remains required |
| Durable Work / restart recovery | connected + verified | Work/thread continuity retained |
| Installed resident desktop-independence/autostart | verified | resident lifecycle evidence exists |
| Durable resident reference continuity | verified | identity/state/reference continuity survives restart evidence |
| Resident health classification/task formation | connected + verified, fail-closed | only narrow repeated internal defects become maintenance candidates |
| Multi-organ health observation | materially connected + verified | unified health remains partial |
| Trusted maintenance source investigation | connected + verified, read-only | explicit source + opaque origin fingerprint |
| Isolated maintenance repair | connected + verified | bounded `work/*`, oracle/diff evidence, origin drift fails closed |
| Autonomous bounded candidate derivation | connected + verified | model confined to bounded source catalog/replacement contract |
| Maintenance cognition dispatch accounting | connected + verified, fail-closed | ambiguous provider outcomes are not blindly replayed |
| Independent semantic review / recovery | connected + verified, fail-closed | author route cannot self-approve; pending review can resume safely |
| Accepted local publication preparation | connected + verified, `local_commit_only` | no remote repository authority |
| Upstream BUG / repair report formation | connected + verified locally | repeated `probable_zn_defect` truth projects to one durable privacy-safe installation-pseudonymous local outbox envelope |
| Upstream BUG / repair dispatch recovery | connected + verified, fail-closed | abandoned `dispatching` reservations become `outcome_uncertain` on restart; attempt count preserved; automatic replay blocked |
| Upstream BUG / repair transport / maintainer intake | missing in merged product; active isolated stage | operator-controlled transport, acknowledgement/reconciliation and maintainer intake are under separate isolated development and must be reviewed before merge |
| Resident managed-browser navigation | connected + verified | explicit safe URL -> managed Chromium -> independently observed URL |
| Resident managed-browser semantic checkbox | connected + verified | exact accessible-name target, fresh semantic authority, same-node checked-state postcondition |
| Resident managed-browser semantic button | connected + verified | exact accessible-name button, explicit same-origin URL postcondition, observed-result restart recovery |
| Resident managed-browser semantic textbox | connected + verified | exact accessible-name writable non-password textbox, digest/length verification, durable Body plaintext redaction, restart recovery |
| Resident managed-browser same-session form | connected + verified for one complete ordinary Work scenario | textbox entry and submit share one Chromium session; final URL depends on retained text state; guarded and recoverable from exact durable evidence |
| Resident managed-browser broader page interaction | partial | generic discovery, tabs/popups/frames, downloads/uploads and arbitrary interaction are not product-closed |
| User browser bridge | bounded mutation foundation, locally verified | explicit focused UIA Edit scope can reuse the non-replayable keyboard-text lifecycle and fresh digest verification; real evidence still uses an isolated temporary Edge profile, while authenticated existing-session attachment and permission UX remain open |
| Installed upstream update observation | partial / substantial desktop foundation | HTTPS channel parsing, version comparison, target selection, size/SHA-256 verification and desktop IPC/UI exist; formal continuity/replacement remains separate |
| Official repository push / PR / merge | intentionally outside installed resident | maintainer-environment authority |
| Installed N -> N+1 update continuity | approval-gated / incomplete | no formal updater/replacement transition executed |
| Rollback / signing / release trust | approval-gated / incomplete | high-risk release/update authority remains separate |

## Current self-maintenance / reporting path

```text
real organ failure/success
-> durable privacy-safe health
-> conservative probable_zn_defect task
-> best-effort local privacy-safe report projection
-> durable deduplicated local outbox envelope
-> durable dispatch reservation
-> crash-safe unknown-outcome classification
-> merged product currently stops before transport/intake
```

Health truth commits before report projection. Report payload excludes raw error text, local paths, repository identity, credentials, task id, organ name and local health fingerprint. Installation-scoped pseudonyms prevent direct cross-install incident correlation.

Dispatch semantics are fail-closed: `reserve_dispatch()` commits `pending -> dispatching` and increments `dispatch_attempts` before any external effect. If the process restarts with an abandoned reservation, outbox construction promotes it to `outcome_uncertain`, records interruption evidence, preserves the prior attempt count and keeps automatic replay blocked.

## Managed-browser ordinary Work reality

The current verified bounded surface includes:

```text
navigation:
explicit URL -> managed Chromium -> independent URL observation

semantic checkbox:
explicit URL + exact accessible name + explicit desired state
-> fresh semantic observation
-> exact-target CHECK/UNCHECK
-> same-node checked-state verification

semantic button:
explicit URL + exact accessible button name + explicit expected URL
-> fresh semantic observation
-> exact-target click
-> independent final URL observation
-> durable observed-result recovery

semantic textbox:
explicit URL + exact accessible textbox name + explicit bounded text
-> fresh semantic observation
-> exact-target text entry
-> digest/length + exact-node continuity verification
-> durable Body plaintext redaction
-> durable observed-result recovery

same-session form transaction:
explicit start URL
-> exact textbox observation
-> bounded text entry
-> text postcondition verification
-> fresh exact button observation
-> click in the same browser session
-> independent explicit same-origin final URL observation
-> durable result / crash recovery without blind replay
```

Natural Work does not gain private-network authority. Password/sensitive textbox targets remain refused. Structured action compilation no longer duplicates browser/keyboard plaintext from `text` into generic `content`; legacy compatibility remains scoped to file-write actions only.

The form Chromium E2E reaches `/done` only when the exact typed value is still present at click time, proving same-session state retention rather than merely sequential actions.

## Evidence checkpoints

- `fb720e3a6facf3514fd8ff2952751082460487bd` — restored Body health observation after final browser Body composition.
- ZN CI `33338816909` — full Source Boundary, Kernel/Python and Electron validation success for that repair checkpoint.
- Managed Browser E2E `33338816911` — success.
- Work Recovery E2E `33338816913` — success.
- PR #120 / merge `687d8f997f9850081c65a3767f6dbb9735276ea3` — same-session managed-browser form transaction.
- Managed Browser E2E `33339937362` — contract suite + real local Chromium E2E success after structured text alias scoping.
- Work Recovery E2E `33339955722` — success on the final structured compiler/recovery checkpoint.
- ZN CI `33339955736` — full success on `7450582...`.
- PR #121 / merge `5f14a6453aadba196060e954ce7bc674551ac3e8` — interrupted upstream-report dispatch recovery.
- Work Recovery E2E `33340676170` — complete success including upstream-report restart regression.
- ZN CI `33340676146` — full Source Boundary, Kernel/Python, Electron and final status publication success on `5f14a645...`.
- PR #123 / merge `ac6b3846d621dd790f587cbc08311b162eba6b97` — promoted the verified development tranche to canonical `main`.
- Canonical ZN CI `33353573721` — post-promotion run for `ac6b3846...`; read live final state before claiming canonical closure.
- PR #125 candidate `f1ded231d44dc58e9d9a597213f8f738ea5560f4` — connects bounded focused UIA Edit text mutation to the existing non-replayable resident lifecycle.
- Windows Interactive Desktop E2E `33354912873` — success including real installed Edge text mutation through default UIA plus keyboard input.
- ZN CI `33354911263` — full success on the PR #125 candidate.
- Work Recovery E2E `33354930689` — success on the PR #125 candidate.
- Hosted Windows Clean Install / Release Candidate runs that fail with `runner_id=0` and `steps=[]` are runner-allocation infrastructure evidence, not executed-code failures.

Older self-maintenance evidence remains valid where the underlying code has not changed; consult Git history and CI for exact runs when needed.

## Current product gaps

1. **Upstream BUG/repair transport and maintainer intake are the active isolated product stage.** Local formation and crash-safe dispatch accounting are verified; operator-controlled transport, explicit acknowledgement/reconciliation and maintainer intake are not merged yet.
2. **User Browser Bridge is not product-closed.** Bounded focused non-password text mutation is locally verified against a real installed Edge provider with an isolated temporary profile, but existing authenticated Edge/Chrome attachment and user-facing permission/revocation still need proof; never copy cookies, passwords or profile data.
3. **Managed browser breadth remains partial.** Generic discovery, tabs/popups/frames, downloads/uploads and arbitrary interaction remain open.
4. **Browser interaction recovery remains fail-closed outside proven observed results.** Unknown external mutations without sufficient durable evidence still need bounded re-sense/reclassification.
5. **Installed update continuity remains incomplete.** Public-channel observation and artifact verification exist, but formal N -> N+1 continuity, rollback and signing/trust remain approval-gated.
6. **Unified health remains partial.** Extend only where active-call evidence closes a meaningful reliability gap.

## Current parallel ownership boundary

For the current large-stage collaboration, the report transport/intake implementation lane owns its new product modules and the related `upstream_bug_report.py` / `reporting_maintenance_resident.py` active-caller chain. Documentation/promotion work must not concurrently modify those product files. When the isolated PR arrives, review its live base/head/diff, authority boundary, retry/reconciliation semantics and actual tests before merge.

## Next evidence-driven direction

Finish canonical CI verification for PR #123 while preserving the isolated report lane. The active product candidate is:

```text
pending report
-> durable reserve
-> operator-controlled transport
-> explicit acknowledgement / reconciliation
-> durable terminal state
-> maintainer intake evidence
```

The installed resident must not become a generic GitHub/repository write client. Unknown external effects remain non-replayable until explicitly reconciled.
