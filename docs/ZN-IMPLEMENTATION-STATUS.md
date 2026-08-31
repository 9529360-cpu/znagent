# ZN Implementation Status

This is ZN's implementation/evidence ledger, not a roadmap or changelog. Real code, live Git refs and actual test/build/CI results override this file when they disagree.

## Repository state contract

- Repository: `9529360-cpu/znagent`
- Primary development branch: `dev/zn-agent`
- Canonical/release branch: `main`
- Do **not** treat an exact branch SHA written here as a live oracle. Documentation and promotion commits change HEAD by definition. Fresh maintainers must query live `main` / `dev/zn-agent`, compare them, and inspect current CI/PR state.
- Exact SHAs below are evidence checkpoints only.
- No force push, history rewrite, destructive identity/memory migration, updater replacement, rollback, release signing or production credential mutation is authorized by this stage.

The repository maintenance rule remains:

```text
verified coherent product slice
-> reconcile changed implementation truth + HANDOFF in the same slice
-> normal dev -> main promotion
-> verify canonical CI
-> keep long-lived branches reasonably synchronized
```

Do not defer changed product truth to a later chat/session, and do not encode self-invalidating "current HEAD" claims as durable documentation truth.

## Installed-upstream authority contract

Normal installed ZN instances may know their official upstream **update channel** so they can detect and verify official updates. That knowledge is not source-repository authority and does not require exposing or accessing the private source repository.

```text
official upstream update channel -> installed ZN
installed ZN -> bounded BUG / repair report channel
```

An installed resident may read/verify update metadata, diagnose itself, form bounded local repair evidence in an authorized maintenance environment, and form bounded privacy-safe BUG/repair reports. It does not receive official repository push/PR/merge/release/signing authority merely by being installed.

## Private-source identity boundary

Shipped resident core does not need a compiled-in private repository slug. Trusted source continuity uses an explicitly supplied ZN source root, ownership markers and an opaque one-way origin fingerprint. Later repair/cleanup/local-publication actions must re-read the live origin and match the same fingerprint.

CI rejects the private source identity if it reappears in shipped resident core or desktop package metadata.

## Capability maturity ledger

Use `exists -> connected -> verified -> product-closed`. File/interface presence is not proof that a product capability is closed end to end.

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
| Autonomous bounded candidate derivation | connected + verified | model is confined to bounded source catalog/replacement contract |
| Maintenance cognition dispatch accounting | connected + verified, fail-closed | ambiguous provider outcomes are not blindly replayed |
| Independent semantic review / recovery | connected + verified, fail-closed | author route cannot self-approve; pending review can resume safely |
| Accepted local publication preparation | connected + verified, `local_commit_only` | no remote repository authority |
| Upstream BUG / repair report formation | connected + verified locally | repeated `probable_zn_defect` truth projects to one durable privacy-safe installation-pseudonymous local outbox envelope |
| Upstream BUG / repair report transport | missing / deprioritized | no network sender/endpoint; durable reserve, crash-to-uncertain reconciliation and no-blind-replay are verified, but the user has deprioritized remote transport |
| Resident managed-browser navigation | connected + verified for narrow ordinary Work entry | explicit safe URL + navigation cue -> managed Chromium -> observed URL postcondition |
| Resident managed-browser semantic checkbox | connected + verified for bounded ordinary Work | exact accessible-name target, fresh semantic authority, checked-state postcondition and zero-model Work path |
| Resident managed-browser semantic button | connected + verified for bounded ordinary Work | exact accessible-name button, explicit same-origin URL postcondition, real Chromium evidence and observed-result restart recovery |
| Resident managed-browser semantic textbox | connected + verified for bounded ordinary Work | exact accessible-name writable non-password textbox, privacy-safe length/digest evidence, real Chromium and restart recovery |
| Resident managed-browser same-session form | connected + verified for one complete ordinary Work scenario | textbox entry and button submit share one live Chromium session; final URL depends on retained text state; whole transaction is guarded and recoverable from exact durable evidence |
| Resident managed-browser broader page interaction | partial | generic discovery, multi-tab/popup/frame authority, downloads/uploads and arbitrary interaction are not product-closed |
| User browser bridge | sensing foundation only | real Edge/Chrome UIA sensing proof uses an isolated temporary profile; authenticated existing-session permission and mutation remain open |
| Installed upstream update observation | partial / substantial desktop foundation | HTTPS stable-channel parsing, version comparison, platform target selection, size/SHA-256 verification and desktop IPC/UI exist; formal continuity/replacement remains separate |
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
-> no transport authority yet
```

Health truth commits before report projection, so report formation failure cannot roll back resident health. Report payload excludes raw error text, local paths, repository identity, credentials, task id, organ name and local health fingerprint. Installation-scoped pseudonyms prevent direct cross-install incident correlation.

Any future transport must durably reserve dispatch before external side effects; ambiguous outcomes remain `outcome_uncertain` until explicit reconciliation.

## Managed-browser ordinary Work paths

Navigation remains a verified ordinary Work browser path:

```text
ordinary durable Work
+ exactly one explicit HTTP(S) URL
+ explicit navigation intent
-> deterministic browser_navigate
-> managed Chromium navigation
-> independently observed current URL
-> durable Work completion/failure
```

The original technical `#dom-id` checkbox slice has since been extended with exact accessible-name semantic checkbox, button and textbox paths. The strongest current vertical slice is the same-session form transaction merged by PR #120:

```text
ordinary durable Work
+ explicit start URL and explicit same-origin expected URL
+ exact accessible names for one textbox and one button
+ explicit bounded text
-> one managed Chromium session
-> fresh semantic textbox observation
-> same-node text length/SHA-256 verification
-> fresh semantic button observation
-> submit click
-> independent final URL observation
-> durable Work completion
-> restart recovery only from exact observed-result evidence
```

Natural English/Chinese parsing is deterministic and does not ask a model to invent the URLs, targets, text or expected result. Password/sensitive textboxes remain refused. Ordinary Work does not silently acquire private-network authority. Browser/form/keyboard plaintext is no longer duplicated through the structured action compiler's historical `content` alias, and form Body history has a second defensive redaction boundary.

These are connected and verified bounded interaction classes, not a complete browser product.

## Exact evidence that matters

- `33284716266` — targeted resident report-outbox validation success.
- PR #95 — connected resident maintenance truth to privacy-safe durable local report projection.
- `33286593120` — ordinary user-entry browser navigation + real local Chromium Work E2E success.
- `33286655544` — same natural path through durable `ResidentWorkLedger` + Chromium E2E success.
- PR #96 — ordinary Work -> managed-browser navigation.
- `33286758708` — earlier full dev ZN CI fully green on product-code checkpoint `b1c86ee2...`.
- PR #102 — ordinary Work -> explicit bounded checkbox mutation through managed-browser Body.
- `33297131660` — managed-browser contract suite and real local Chromium E2E green after PR #102; this run includes the new browser Work checkbox core tests.
- `33297131654` — all three primary ZN CI jobs (Source Boundary, Kernel/Python including full core tests, Electron/TypeScript) reached success on PR #102 merge checkpoint `f5a87ed...`; the workflow itself was subsequently cancelled only when the next dev push superseded its final status-publication phase.
- PR #103 — real local Chromium durable Work evidence for `browser_set_checkbox`.
- `33297795844` — managed-browser contract suite plus real local Chromium E2E green on PR #103 merge checkpoint `9668f883...`, including the checkbox Work E2E.
- PR #120 / merge `687d8f997f9850081c65a3767f6dbb9735276ea3` — connected the bounded same-session textbox-plus-submit form transaction to ordinary Work.
- `33339767489` — Managed Browser E2E success after the form plaintext-history repair.
- `33339937362` — final Managed Browser E2E success covering the structured action compiler boundary.
- `33339955722` — Work Recovery E2E success on the final structured compiler coverage checkpoint `7450582...`.
- `33339955736` — full ZN CI success on `7450582...`.
- PR #121 / merge `5f14a6453aadba196060e954ce7bc674551ac3e8` — abandoned report dispatch reservations recover to `outcome_uncertain` without replay.
- `33340676170` — Work Recovery E2E success including upstream report restart recovery.
- `33340676146` — full ZN CI success on `5f14a645...`.
- Current full ZN CI and canonical post-promotion CI must be read live rather than inferred from this file.

Older self-maintenance evidence remains valid where the underlying code has not changed; consult Git history and CI for exact runs when needed.

## Current product gaps

1. **User Browser Bridge is not product-closed.** Existing authenticated Edge/Chrome reality still needs explicit user permission and bounded mutation; never copy cookies, passwords or profile data.
2. **Managed browser breadth remains partial.** Generic discovery, tabs/popups/frames, downloads/uploads and arbitrary interaction remain open.
3. **Browser interaction recovery remains fail-closed outside proven observed results.** Unknown external mutations without sufficient durable evidence still need bounded re-sense/reclassification.
4. **Installed update continuity remains incomplete.** Public-channel observation and artifact verification exist, but formal N -> N+1 continuity, rollback and signing/trust remain approval-gated.
5. **BUG/repair transport remains missing but is currently deprioritized by the user.** Local formation and crash-safe dispatch accounting remain valid.
6. **Unified health remains partial.** Extend only where active-call evidence closes a meaningful reliability gap.

## Next evidence-driven direction

After documentation reconciliation and normal canonical promotion, the strongest product continuation is:

```text
explicit user confirmation
-> attach only to the current existing browser window/control
-> no profile, cookie or password extraction
-> fresh exact UIA/browser identity
-> one bounded non-sensitive action
-> independent current-state verification
-> permission expiry/revocation and restart-safe failure
```

Repository synchronization and documentation reconciliation are required engineering hygiene, not product milestones.
