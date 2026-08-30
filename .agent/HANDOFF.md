# ZN Maintainer Handoff

This is the current engineering work site and fact index, not a chat transcript or execution script. Real code, live Git refs and actual test/build/CI results override this file when they disagree.

## Current objective

Continue vertical product closure while protecting resident continuity, non-replayable side effects and long-lived privacy boundaries. The browser path is no longer waiting for basic semantic target discovery: exact accessible-name checkbox, button and non-password textbox classes are now connected and browser/recovery E2E verified. Reassess the next product gap from active callers rather than repeating the old `#dom-id` roadmap.

Normal installed ZN still has no official repository push/PR/merge/release/signing authority.

## Repository recovery rule

Never treat SHAs in this file as live refs. Query `main`, `dev/zn-agent`, open PRs and current Actions first.

Current product-code evidence checkpoint before this documentation branch:

- `dev/zn-agent`: `08e3015440d4c64ee311d8c7c6fb043ab8946726`
- Managed Browser E2E `33337761860`: success, including contract suite + real local Chromium E2E.
- Work Recovery E2E `33337761862`: success, including named-text durable-result restart recovery.
- ZN CI `33337761865`: Electron/TypeScript + Source Boundary success; Kernel/Python core tests still running at this handoff update. Query final status before canonical promotion.

`main` was materially behind dev at takeover and must be re-compared live before normal promotion. Main sync is engineering continuity hygiene, not a product milestone.

## Current browser product reality

Ordinary durable Work has narrow deterministic classes for:

1. safe explicit HTTP(S) navigation;
2. explicit DOM-id checkbox mutation;
3. unique exact accessible-name native checkbox mutation;
4. unique exact accessible-name native button click with explicit expected same-origin URL;
5. unique exact accessible-name native non-password textbox text entry with one explicit quoted plaintext value.

The semantic provider fails closed on ambiguous/hidden/unsupported targets. The named-text class accepts writable `textarea` and normal text `<input>` controls, including an omitted/default HTML `type`; password, disabled and read-only targets are refused. Natural Work does not infer private-network authority and does not ask a model to invent target/value/destination.

Provider text-entry success requires exact-node continuity plus exact text length/SHA-256 postcondition. Durable Body action history removes the plaintext text argument. The Work task/event itself remains durable user-authored content, so this is not a secret/password entry facility.

### Browser interruption recovery

A browser mutation is durably marked before dispatch. Preserve the distinction:

- `started` with no durable Body result -> outside-world effect is unknown; replay remains blocked and recovery fails closed;
- `observed` with an exact successful durable result -> named-button and named-text actions may resume completion without replay, but only if the persisted provider evidence exactly proves the original target/postcondition and closed session.

Do not reopen an ephemeral browser and infer that an unknown effect happened.

## Terminal / durable-history safety

PR #113 removed command environment values, terminal stdin arguments and file-write content from generic durable Body action history. PR #116 additionally:

- guards `terminal_input`, `terminal_write`, `command_input` as non-replayable side effects;
- routes a restart into explicit side-effect recovery instead of ordinary local failure;
- removes PTY output and raw command text from the durable result row for input actions, preventing a typed secret from being copied back into history through terminal echo;
- leaves the live result available to the current pulse.

Verified evidence: Work Recovery E2E `33337246745`; managed-browser regression E2E `33337246757`.

Do not overclaim this boundary. Arbitrary shell command strings and normal terminal command/poll outputs can still contain secrets. `ResidentWorkLedger` intentionally forms terminal artifacts from command/output, so a broader change needs an explicit sensitivity/retention contract and consumer analysis, not blanket redaction.

## Resident maintenance/reporting reality

Repeated bounded `probable_zn_defect` truth projects to a durable privacy-safe local report outbox. Health commits before projection. Installation-scoped pseudonyms and bounded metadata avoid raw error/local-path/source-identity credential disclosure.

Still missing: external transport, maintainer intake, acknowledgement and ambiguous-outcome reconciliation. Installed ZN has no repository mutation/release authority merely because an outbox exists.

## Recent implementation / evidence index

- #109 — named-button side-effect recovery classification.
- #110 — exact named-button action connected to ordinary Work.
- #111 — real Chromium named-button Work progress-contract fix.
- `33334989444` — Work Recovery E2E green.
- `33335159923` — managed-browser contracts + real Chromium E2E green.
- #113 — sensitive Body action argument redaction.
- `33335856327` — full ZN CI green after #113.
- #114 — exact durable observed named-button result resumes after restart without replay.
- #115 — dedicated Browser/Recovery workflow coverage for recovery code.
- `33337029683` — Work Recovery E2E green.
- `33337029679` — managed-browser contracts + real Chromium E2E green.
- #116 — terminal stdin replay guard + echoed-input durable redaction.
- `33337246745` — Work Recovery E2E green including terminal-input recovery.
- `33337246757` — managed-browser contracts + real Chromium E2E green after #116.
- #117 — exact accessible-name textbox sensing + `browser_type_named_text` Body/ordinary Work/restart recovery + real Chromium Work E2E coverage.
- #118 — accepts HTML default text `<input>` semantics consistently with provider TYPE_TEXT.
- first #117 browser run `33337615276` exposed one Chinese natural parser failure while Body/history/recovery tests passed.
- #119 — CJK/full-width punctuation URL boundary repair for the natural named-text parser.
- `33337761860` — browser contracts + real local Chromium E2E green for #117-#119 checkpoint `08e3015...`.
- `33337761862` — Work Recovery E2E green for the same checkpoint.
- `33337761865` — current full ZN CI; query live final status before promotion.

Windows Clean Install / Release Candidate jobs may fail immediately with no runner (`runner_id=0`, no steps). This pre-existing infrastructure condition must not be “fixed” by weakening updater, signing or release-integrity controls.

## Current product gaps / candidate order

Reassess live, but current high-value candidates are:

1. **Terminal sensitivity / retention contract.** Command strings and normal command/poll output are useful Work artifacts but can contain secrets. Define explicit sensitivity authority and retention behavior before broadening automatic terminal workflows.
2. **BUG-report transport closure.** Local durable outbox exists; bounded transport, durable reserve, acknowledgement, outcome reconciliation and maintainer intake do not.
3. **Unknown side-effect recovery UX/evidence.** True pre-return uncertainty correctly blocks replay but still often requires an explicit human/lifecycle decision.
4. **User Browser Bridge.** Existing authenticated browser session path remains missing; never copy browser credentials/profile state as a shortcut.
5. **Installed update observation / continuity.** Read/verify/update-available path is partial; N -> N+1 replacement, rollback and signing remain approval-gated.
6. **Unified health.** Expand only where an active caller and meaningful reliability gap justify it.
7. **Additional browser action classes.** Lower priority than the above unless a real user path needs one; every mutation needs authority, postcondition, privacy and restart semantics.

## Immediate continuation procedure

1. Read final status of `33337761865` and repair any core failure immediately.
2. Merge the fresh status/HANDOFF PR only when it matches final code/CI evidence.
3. Fresh-compare `main` vs `dev/zn-agent`; if dev is verified and main has no conflicting work, use a normal tracked dev -> main PR/merge and verify canonical CI.
4. Continue the highest-value product gap above; do not stop at documentation or promotion.

No force push, history rewrite, destructive database/identity/memory migration, production credential expansion, updater replacement, rollback, release signing or equivalent high-risk operation is authorized by this handoff.