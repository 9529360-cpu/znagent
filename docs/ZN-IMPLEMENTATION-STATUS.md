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
| Upstream BUG / repair report transport | missing | no network sender/endpoint yet; future transport must preserve durable reserve + ambiguous-outcome reconciliation |
| Resident managed-browser navigation | connected + verified for narrow ordinary Work entry | explicit safe URL + navigation cue -> managed Chromium -> observed URL postcondition |
| Resident managed-browser checkbox interaction | connected + verified for one bounded ordinary Work class | exactly one explicit HTTP(S) URL + one explicit `#dom-id` + unambiguous check/uncheck cue; fresh exact target authority; provider verifies same-node checked state; zero-model path; guarded against blind replay |
| Resident managed-browser broader page interaction | partial | semantic target discovery, general click/focus/text/form workflows and interruption reconciliation are not product-closed |
| User browser bridge | architecture only / missing | authenticated existing-browser path not product-closed |
| Installed upstream update observation | partial | public channel infrastructure exists; installed read/verify/update-available loop still needs complete product evidence |
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

## Managed-browser ordinary Work path

Navigation remains the first closed ordinary Work browser path:

```text
ordinary durable Work
+ exactly one explicit HTTP(S) URL
+ explicit navigation intent
-> deterministic browser_navigate
-> managed Chromium navigation
-> independently observed current URL
-> durable Work completion/failure
```

PR #102 adds one deliberately narrow mutation path instead of pretending that general browser interaction is complete:

```text
ordinary durable Work
+ exactly one explicit HTTP(S) URL
+ exactly one explicit #dom-id
+ unambiguous check / uncheck intent
-> deterministic browser_set_checkbox
-> origin-bounded navigation + page-interaction authority
-> fresh DOM-id target observation
-> require checkbox role
-> CHECK / UNCHECK bound to that observation
-> same-exact-node checked-state postcondition
-> close ephemeral session
-> durable Work result
```

ZN does not ask a model to invent the destination, target identity or requested boolean state. Multiple/malformed URLs, embedded credentials, missing or multiple explicit target IDs, or ambiguous interaction text do not create this authority. This path does not grant text-entry, download or upload authority.

The mutation crosses the existing durable side-effect replay boundary. A reconstructed same event/signature is not blindly replayed after uncertainty. Cross-process reconciliation of an interrupted ephemeral browser mutation is **not** claimed yet; current behavior fails closed rather than guessing whether the outside-world effect happened.

PR #103 adds real local Chromium Work evidence for the checkbox path. The local fixture uses explicit private-network authority only inside the E2E payload; ordinary natural Work does not silently acquire private-network access.

This is one connected and verified interaction class, not a complete browser product.

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
- Current full ZN CI and canonical post-promotion CI must be read live rather than inferred from this file.

Older self-maintenance evidence remains valid where the underlying code has not changed; consult Git history and CI for exact runs when needed.

## Current product gaps

1. **Managed browser still lacks semantic target discovery for ordinary Work.** The new checkbox path requires a technical `#dom-id`; ZN still needs bounded fresh page/accessibility sensing that can discover a user-meaningful target without inventing authority.
2. **Browser interaction recovery is fail-closed but not fully reconciled.** An interrupted ephemeral mutation is not blindly replayed, but ZN cannot yet reopen/re-sense enough state to classify every unknown outcome as succeeded/failed.
3. **Broader browser interaction is partial.** General safe click/focus/text/form workflows are not connected to ordinary Work; expand vertically rather than exposing all provider primitives at once.
4. **BUG/repair reporting is locally connected but not remotely product-closed.** Bounded operator-controlled transport/intake/acknowledgement/reconciliation remains missing.
5. **User Browser Bridge is missing.** Existing authenticated user-session reality must not be solved by copying browser credentials/profile data.
6. **Installed update observation remains partial; N -> N+1 replacement/rollback/signing remain approval-gated.**
7. **Unified health remains partial.** Extend only where active-call evidence closes a meaningful reliability gap.

## Next evidence-driven direction

After live branch/CI state is confirmed, the strongest browser continuation is:

```text
ordinary managed-browser Work
-> bounded fresh accessibility/semantic observation
-> deterministic user-meaningful target selection under explicit authority
-> one controlled interaction
-> independent postcondition
-> interruption reconciliation / recovery
```

Reassess this against the local-report transport gap before each new slice. Repository synchronization and documentation reconciliation are required engineering hygiene, not product milestones.
