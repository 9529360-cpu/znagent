# ZN Implementation Status

This is ZN's implementation/evidence ledger, not a roadmap or changelog. Real code, live Git refs and actual test/build/CI results override this file when they disagree.

## Repository state contract

- Repository: `9529360-cpu/znagent`
- Primary development branch: `dev/zn-agent`
- Canonical/release branch: `main`
- Exact SHAs and run IDs below are evidence checkpoints, never live branch oracles.
- Fresh maintainers must query `main`, `dev/zn-agent`, relevant `work/*`, open PRs and current CI before acting.
- No force push, history rewrite, destructive identity/memory migration, updater replacement, rollback, release signing or production credential mutation is authorized by this stage.

Repository synchronization and documentation are continuity tools, not product milestones. Changed product truth should still be reconciled in the same coherent slice.

## Installed-upstream authority contract

Normal installed ZN instances may know and verify an official upstream update channel and may form bounded privacy-safe BUG/repair reports. They do not receive private source-repository push/PR/merge/release/signing authority merely by being installed.

Trusted source continuity uses an explicitly supplied ZN source root, ownership markers and an opaque one-way origin fingerprint. CI rejects private source identity if it reappears in shipped resident core or desktop package metadata.

## Capability maturity ledger

Use `exists -> connected -> verified -> product-closed`. File/interface presence is not proof that a capability is usable end to end.

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
| Upstream BUG / repair report transport | missing | no network sender/endpoint yet; future transport must preserve durable reserve + ambiguous-outcome reconciliation |
| Managed-browser navigation | connected + verified for bounded ordinary Work | one explicit safe HTTP(S) URL + navigation cue -> managed Chromium -> independently observed URL postcondition |
| Managed-browser exact checkbox by DOM id | connected + verified | one explicit URL + one explicit `#dom-id` + unambiguous check/uncheck -> fresh exact target -> same-node checked-state postcondition |
| Managed-browser exact checkbox by accessible name | connected + verified | quoted exact accessible checkbox name -> unique visible native main-frame checkbox -> same-node checked-state postcondition |
| Managed-browser exact button navigation | connected + verified for bounded ordinary Work | two explicit URLs + one quoted exact accessible button name + explicit click cue -> fresh unique native button -> same-origin navigation postcondition |
| Browser side-effect restart safety | connected + verified, fail-closed | navigate/checkbox/named-checkbox/named-button are classified as guarded side effects; uncertain durable attempts enter recovery and are not blindly replayed |
| Managed-browser broader interaction | partial | focus/text/form/download/upload and richer workflows are not product-closed |
| User browser bridge | architecture only / missing | authenticated existing-browser path not product-closed |
| Installed upstream update observation | partial | public channel infrastructure exists; installed read/verify/update-available loop still needs complete product evidence |
| Official repository push / PR / merge | intentionally outside installed resident | maintainer-environment authority |
| Installed N -> N+1 update continuity | approval-gated / incomplete | no formal updater/replacement transition executed |
| Rollback / signing / release trust | approval-gated / incomplete | high-risk release/update authority remains separate |

## Current managed-browser product path

The browser path is deliberately vertical rather than a general provider passthrough.

```text
ordinary durable Work
-> explicit user authority
-> resident forms one deterministic native intent
-> origin-bounded managed Chromium
-> fresh exact target observation where interaction is needed
-> action bound to that observation
-> independent provider postcondition
-> session cleanup
-> durable Work result
-> fail-closed restart recovery if dispatch outcome is uncertain
```

Supported ordinary Work authority is currently bounded to:

- navigation: exactly one explicit valid HTTP(S) URL plus an unambiguous navigation cue;
- checkbox by DOM id: one explicit URL, one explicit `#dom-id`, one unambiguous check/uncheck intent;
- checkbox by accessible name: one explicit URL, one quoted exact accessible checkbox name, one unambiguous check/uncheck intent;
- button navigation: exactly two explicit valid HTTP(S) URLs in task order (start and expected destination), one quoted exact accessible button name, and an explicit English/Chinese click cue.

For the semantic checkbox/button paths, provider sensing is main-frame only, exact role/name only, and fails closed on zero, multiple, hidden or unsupported native targets. No page-wide text or candidate list is returned to ZN. The button path currently requires a native `button` and same-origin expected destination.

Malformed button requests do not silently degrade into navigation-only Work. ZN does not ask a model to invent destination, target identity, boolean state or expected destination.

Browser mutations and navigation cross the durable side-effect replay boundary. PR #109 fixed a resident-layer gap where the newly added named-button action was guarded by Body but missing from the resident guarded-side-effect classifier. A reconstructed uncertain button action now enters `side_effect_recovery` with replay blocked rather than being misclassified as an ordinary local failure.

Cross-process outcome reconciliation is still incomplete. Current behavior is intentionally conservative: if an ephemeral browser mutation may have happened but durable completion was lost, ZN can require a user decision rather than guessing or replaying.

## Text-entry boundary discovered during current audit

`BrowserActionKind.TYPE_TEXT` exists at the managed-browser provider layer and already verifies same-node text state using length/SHA-256 evidence while refusing password fields. It is **not** connected to ordinary Work.

Do not connect it by simply forwarding user text into a Body action. `NativeBody._record()` currently persists full action args in `native_body_actions.action_json`; doing so would durably store raw entered text and could turn passwords/tokens or other sensitive user input into resident history. A product-safe text-entry slice must define and test secret/redaction/persistence semantics first.

## Self-maintenance / reporting path

```text
real organ failure/success
-> durable privacy-safe health
-> conservative probable_zn_defect task
-> best-effort local privacy-safe report projection
-> durable deduplicated local outbox envelope
-> no transport authority yet
```

Health truth commits before report projection, so report formation failure cannot roll back resident health. Future transport must durably reserve dispatch before external side effects; ambiguous outcomes remain uncertain until explicit reconciliation.

## Evidence checkpoints

- PR #95 — resident maintenance truth -> privacy-safe durable local report projection.
- PR #96 — ordinary Work -> managed-browser navigation.
- PR #102 / #103 — bounded DOM-id checkbox Work + real local Chromium evidence.
- PR #106 and subsequent dev commits — bounded exact accessible-name checkbox sensing/action.
- PR #108 — exact semantic named-button navigation provider/Body/structured Work slice.
- PR #109 — named-button resident restart/replay classification repair.
- PR #110 — exact named-button action connected to normal ordinary Work with zero model invention.
- PR #111 — corrected the real Chromium E2E assertion to the public Work progress contract (`summary`, not private/raw `output`).
- `33334989444` — ZN Work Recovery E2E success on the button ordinary-Work checkpoint.
- `33335159923` — Managed Browser E2E success on `ef720097...`: browser contract tests and real local Chromium E2E both green after the progress-contract repair.
- `33335159900` — current full dev ZN CI for `ef720097...`; read live before claiming its final workflow conclusion.
- Windows Clean Install / Release Candidate jobs around this checkpoint can fail before acquiring a runner (`runner_id=0`, no steps). The same failure mode existed before the current browser changes; do not attribute it to this slice or alter release trust merely to clear that platform failure.

Older evidence remains valid where underlying code has not changed; consult Git history and CI for exact runs when needed.

## Current product gaps

1. **Browser interruption recovery is fail-closed but not fully reconciled.** Unknown external outcomes still need bounded re-sense/reclassification where safely possible.
2. **Safe text entry is blocked on persistence/privacy semantics.** Provider-level `TYPE_TEXT` exists, but ordinary Work must not durably record raw sensitive text in generic Body action history.
3. **Broader browser workflows remain partial.** Focus, forms, downloads/uploads, richer navigation/click sequences and general semantic observation should be added one complete scenario at a time.
4. **BUG/repair reporting is locally connected but not remotely product-closed.** Bounded operator-controlled transport/intake/acknowledgement/reconciliation remains missing.
5. **User Browser Bridge is missing.** Existing authenticated user-session reality must not be solved by copying browser credentials/profile data.
6. **Installed update observation remains partial; N -> N+1 replacement/rollback/signing remain approval-gated.**
7. **Unified health remains partial.** Extend only where active-call evidence closes a meaningful reliability gap.

## Next evidence-driven direction

After reading live Git/CI, prefer one of these complete vertical closures rather than adding disconnected primitives:

```text
browser uncertain side effect
-> durable minimal reconciliation evidence
-> safe re-sense when technically possible
-> classify succeeded / failed / still uncertain
-> never blind replay
```

or, only after the persistence boundary is designed:

```text
explicit user text-entry Work
-> exact user-meaningful target
-> no raw sensitive text in durable generic action history
-> one provider dispatch
-> digest/length postcondition
-> restart/failure semantics
```

Reassess these against the local-report transport gap before each new slice.