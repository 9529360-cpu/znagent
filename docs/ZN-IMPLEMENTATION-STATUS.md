# ZN Implementation Status

This is ZN's implementation/evidence ledger, not a roadmap or changelog. Real code, live Git refs and actual test/build/CI results override this file when they disagree.

## Repository state contract

- Repository: `9529360-cpu/znagent`
- Primary development branch: `dev/zn-agent`
- Canonical/release branch: `main`
- Exact SHAs below are evidence checkpoints, never live-oracle claims. Fresh maintainers must query live refs and CI.
- No force push, history rewrite, destructive identity/memory migration, updater replacement, rollback, release signing or production credential mutation is authorized by this stage.

Normal engineering flow remains: coherent product slice -> risk-proportional verification -> reconcile durable status/HANDOFF -> normal dev-to-main promotion -> canonical CI. Git synchronization is continuity hygiene, not a product milestone.

## Product model / authority invariants

ZN remains a persistent resident subject with ZN-owned Self, Body, Senses, Situation, Thought, Will and durable Work. Installed ZN may observe/verify an official update channel and form privacy-safe maintenance evidence, but installation does not grant private source repository push/PR/merge/release/signing authority.

Shipped resident core does not need a compiled-in private repository slug. Source continuity uses explicit source-root ownership evidence and opaque origin identity; source-maintenance mutation remains bounded to authorized maintenance contexts.

## Capability maturity ledger

Use `exists -> connected -> verified -> product-closed`. Presence of an interface or provider primitive is not enough.

| Area | Current maturity | Evidence boundary / remaining gap |
| --- | --- | --- |
| Resident Self / Body / Senses / Situation / Thought / Will | connected + repeatedly verified | zero-model resident boot remains required |
| Durable Work / restart recovery | connected + verified | thread/run continuity and bounded recovery retained |
| Resident identity/reference continuity | verified | restart continuity evidence exists; destructive migrations remain approval-gated |
| Resident health -> maintenance candidate | connected + verified, fail-closed | only bounded repeated internal defects escalate |
| Upstream BUG / repair report formation | connected + verified locally | durable privacy-safe local outbox only |
| Upstream BUG / repair report transport | missing | no network dispatch/intake/ack/reconciliation closed loop |
| Managed-browser navigation | connected + verified | ordinary Work can form explicit safe URL navigation with observed URL postcondition |
| DOM-id checkbox Work | connected + verified | technical target path retained for compatibility |
| Exact accessible-name checkbox Work | connected + verified | unique fresh semantic checkbox target + exact-node checked-state verification |
| Exact named button -> URL Work | connected + verified | unique native button + fresh-node revalidation + expected same-origin URL postcondition |
| Named-button restart recovery | connected + verified | an already durable provider-verified `observed` result resumes without replay; true pre-return uncertainty remains fail-closed |
| Exact accessible-name textbox sensing | connected + verified | unique visible writable native text/textarea target; password targets refused |
| Exact named textbox text entry Work | connected + verified | zero-model explicit URL + quoted plaintext + quoted textbox name; provider verifies exact-node length/SHA-256 result; no secret/password authority |
| Named-text restart recovery | connected + verified | durable verified result resumes without replay; `started` uncertainty remains fail-closed |
| Terminal stdin replay safety | connected + verified | terminal input aliases commit pre-dispatch guard and enter explicit recovery instead of blind replay |
| Sensitive Body action history | materially hardened + verified | command env values, terminal stdin args/echo and file-write content are redacted from durable Body history; general command strings/output still require an explicit sensitivity contract |
| User browser bridge | architecture only / missing | authenticated existing-browser path not product-closed |
| Installed upstream update observation | partial | read/verify/update-available product evidence remains incomplete |
| Installed N -> N+1 continuity / rollback / signing | approval-gated / incomplete | high-risk updater/release trust boundary remains separate |
| Unified health | partial | extend only from active-call evidence |

## Managed-browser ordinary Work

The browser path has progressed beyond technical DOM ids. Current vertical classes are deliberately narrow and deterministic:

```text
ordinary durable Work
-> explicit user authority (safe URL + exact requested target/value/state)
-> fresh resident-owned browser observation
-> exact target binding
-> one controlled effect
-> provider-owned postcondition evidence
-> close ephemeral session
-> durable Work completion
```

Supported ordinary Work classes include:

1. explicit safe HTTP(S) navigation;
2. check/uncheck one explicit DOM-id checkbox;
3. check/uncheck one unique exact accessible-name native checkbox;
4. click one unique exact accessible-name native button and require one explicit same-origin expected URL;
5. type one explicit quoted non-secret plaintext value into one unique exact accessible-name native textbox/textarea.

The natural parsers fail closed. They do not ask a model to invent URL, target, boolean state, destination, or text. Malformed interaction requests do not silently degrade into navigation-only completion. Natural Work never infers private-network authority; local E2E fixtures grant that authority only in explicit structured payloads.

### Text-entry privacy / authority boundary

The provider-level `TYPE_TEXT` path accepts only non-empty bounded text, exact fresh textbox authority and writable native text controls. Password targets are refused and sensitive-field permission stays disabled. Success requires the same exact target node plus exact requested text length and SHA-256 after dispatch.

`browser_type_named_text` removes the plaintext `text` argument from durable `native_body_actions.action_json`; provider/result evidence stores bounded metadata and text digests rather than the plaintext. The user's Work/task itself is durable user-authored content by design, so this path is **not** a secret-entry facility.

### Browser restart semantics

All browser mutations cross a durable side-effect boundary before dispatch. Two crash windows are intentionally distinguished:

- `started` with no durable dispatch result: effect may have happened; blind replay is refused and resident recovery remains fail-closed/user-decision bounded;
- `observed` with an exact durable successful Body result: for named-button and named-text actions, ZN can resume resident completion without replay only when that persisted provider evidence exactly proves the original intent and closed-session postcondition.

ZN does not reopen an ephemeral browser and guess that an unknown outside-world effect happened. Automatic recovery is based only on already durable verified result evidence.

## Terminal / durable-history safety

`SideEffectAwareBody` now protects more than command execution and append writes:

- explicit command/terminal/shell environment values are removed from durable Body action history while key names/count remain bounded audit metadata;
- `terminal_input`, `terminal_write` and `command_input` arguments are redacted and are now non-replayable guarded side effects;
- durable result rows for terminal input drop PTY output and raw command text so terminal echo cannot silently copy the typed value back into long-lived Body/Work history; the live in-pulse result remains available to the current resident decision;
- file-write content is removed from the generic durable action row while replay identity still uses the real pre-dispatch arguments.

This does **not** prove arbitrary shell command strings or ordinary terminal command/poll output are secret-safe. Work intentionally uses terminal command/output as artifacts, so a broader fix needs an explicit sensitivity/retention contract rather than indiscriminate deletion.

## Self-maintenance / reporting path

```text
real organ failure/success
-> durable privacy-safe health
-> conservative probable_zn_defect task
-> best-effort privacy-safe local report projection
-> durable deduplicated local outbox
-> no transport authority yet
```

Health truth commits before report projection. Report payload excludes raw error text, local paths, source identity, credentials and local task identifiers. Future transport must durably reserve external dispatch and reconcile ambiguous outcomes rather than replay blindly.

## Evidence checkpoints

Important recent evidence:

- PR #95 — privacy-safe durable local upstream-report projection.
- PR #96 — ordinary Work -> managed-browser navigation.
- PR #102 / #103 — bounded checkbox Work + real Chromium durable Work evidence.
- PR #106 / #108 — exact accessible-name semantic checkbox/button progression.
- PR #109 — named-button resident side-effect recovery classification.
- PR #110 — exact named-button action connected to ordinary zero-model Work.
- PR #111 — real Chromium named-button Work E2E aligned with public Work progress contract.
- `33334989444` — Work Recovery E2E success for the button-era recovery path.
- `33335159923` — managed-browser contracts + real local Chromium E2E success including named-button Work.
- PR #113 — durable Body action argument redaction for command env / terminal input / file content.
- `33335856327` — full ZN CI success after #113 (Electron/TypeScript, Python core, source boundary and status publication).
- PR #114 — resume exact durable observed named-button result after restart without replay.
- PR #115 — dedicated browser/recovery workflow trigger coverage for the new recovery path.
- `33337029683` — Work Recovery E2E success after #114/#115.
- `33337029679` — managed-browser contracts + real local Chromium E2E success after #114/#115.
- PR #116 — terminal stdin replay guard + durable echoed-input redaction.
- `33337246745` — Work Recovery E2E success including terminal-input recovery tests.
- `33337246757` — managed-browser contracts + real Chromium E2E success after terminal-input hardening.
- PR #117 — exact accessible-name textbox + ordinary named-text Work + durable digest recovery.
- PR #118 — align semantic textbox target with HTML default `<input>` text semantics.
- first #117 browser run `33337615276` exposed one Chinese natural parser failure while Body/history/recovery tests passed.
- PR #119 — CJK/full-width punctuation URL-boundary fix for natural named-text Work after CI exposed the parser defect.
- `33337761860` — managed-browser contract suite and real local Chromium E2E success for the #117-#119 checkpoint `08e3015440d4c64ee311d8c7c6fb043ab8946726`.
- `33337761862` — Work Recovery E2E success for the same checkpoint, including named-text durable-result restart recovery.
- Full ZN CI `33337761865` for the same checkpoint has Electron/TypeScript and Source Boundary green while Kernel/Python core tests are still running at the time of this evidence update; query its final status live before canonical promotion.

Windows Clean Install / Release Candidate workflow failures seen around these checkpoints have repeatedly allocated no runner (`runner_id=0`, no test steps) and predate these product slices. They are infrastructure failures, not permission to weaken release/update/signing integrity.

## Current product gaps

1. **True unknown external side effects remain intentionally unresolved.** If a browser/command/input effect crossed the pre-dispatch boundary but no durable provider result exists, ZN blocks replay. Product UX for explicit evidence/reconciliation/user decision can improve, but must not guess.
2. **Terminal secret handling needs an explicit sensitivity contract.** Arguments and stdin echo are materially safer, but arbitrary command strings and normal command/poll outputs can contain secrets and are currently useful Work artifacts. Design retention/redaction authority before broadening automatic terminal use.
3. **BUG/repair reporting is local-only.** Transport, maintainer intake, acknowledgement and ambiguous-outcome reconciliation are missing.
4. **User Browser Bridge is missing.** Existing authenticated browser reality must not be solved by copying browser credentials or profiles.
5. **Installed update observation is partial; replacement/rollback/signing remain approval-gated.**
6. **Unified health remains partial.**
7. **Broader browser form/action coverage remains intentionally partial.** Expand only one vertical class at a time with explicit authority, postcondition, privacy and recovery semantics.

## Next evidence-driven direction

After current full ZN CI and normal canonical synchronization are complete, reassess between the strongest remaining product closures rather than consuming an old roadmap mechanically. Likely high-value candidates are:

```text
terminal sensitivity/retention contract
or
local BUG outbox -> bounded transport/intake/ack/reconciliation
or
explicit unknown-side-effect recovery UX/evidence path
```

Choose from active callers and product risk. Do not add browser mutation breadth merely because provider primitives exist.