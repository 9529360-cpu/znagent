# ZN Implementation Status

This is ZN's current implementation/evidence ledger, not a roadmap or changelog. Real code, live Git refs and actual test/build/CI results override this file when they disagree.

## Repository state contract

- Repository: `9529360-cpu/znagent`
- Primary development branch: `dev/zn-agent`
- Canonical/release branch: `main`
- Do **not** treat an exact branch SHA written in this document as a live oracle. A documentation commit changes branch HEAD by definition. Fresh maintainers must query live `main` / `dev/zn-agent`, compare them, and inspect current CI/PR state.
- Promotion PR #98 synchronized the verified report/browser stage to canonical `main`; immediately afterward `dev/zn-agent` was fast-forwarded to the promotion merge without force, restoring branch equality at that point.
- Product-code head `b1c86ee2a20a26954d54450160144f921365617c` was fully green in ZN CI `33286758708` before the documentation reconciliation. Later reconciliation changes were documentation-only.
- No force push, history rewrite, destructive identity/memory migration, updater replacement, rollback, release signing or production credential mutation is part of this stage.

The repository maintenance rule is therefore:

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
| Resident managed-browser navigation | connected + verified for narrow ordinary Work entry | explicit safe URL + explicit navigation cue -> managed Chromium -> observed URL postcondition |
| Resident managed-browser page interaction | partial | general page sensing/click/form/text-entry/download/upload/stale-target recovery not yet closed |
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

PR #96 closed one narrow real user-entry gap:

```text
ordinary durable Work
+ exactly one explicit HTTP(S) URL
+ explicit navigation intent
-> deterministic browser_navigate
-> managed Chromium navigation
-> independently observed current URL
-> durable Work completion/failure
```

Multiple URLs, malformed URLs, embedded credentials, or prose merely discussing a URL do not create browser authority. ZN does not ask a model to invent the destination.

This is navigation closure only, not a complete browser product.

## Exact evidence that matters

- `33284716266` — targeted resident report-outbox validation success.
- PR #95 — connected resident maintenance truth to privacy-safe durable local report projection.
- `33286593120` — ordinary user-entry browser navigation + real local Chromium Work E2E success.
- `33286655544` — same natural path through durable `ResidentWorkLedger` + Chromium E2E success.
- PR #96 — ordinary Work -> managed-browser navigation.
- `33286758708` — full dev ZN CI fully green on product-code head `b1c86ee2...`.
- PR #97 — reconciled implementation status/HANDOFF with #95/#96 product reality.
- PR #98 — promoted the verified report/browser stage to canonical `main`; canonical post-promotion CI must be read live from GitHub rather than inferred from this file.

Older self-maintenance evidence remains valid where the underlying code has not changed; consult Git history and CI for exact runs when needed.

## Current product gaps

1. **BUG/repair reporting is locally connected but not remotely product-closed.** Next layer: bounded operator-controlled transport/intake/acknowledgement/reconciliation without repository credentials or general network authority.
2. **Managed browser is navigation-only.** Add bounded fresh page observation and one interaction class with explicit authority, postcondition and failure recovery before expanding breadth.
3. **User Browser Bridge is missing.** Existing authenticated user-session reality must not be solved by copying browser credentials/profile data.
4. **Installed update observation remains partial.** Read/verify/update-available must be proven end to end independently of private source access.
5. **Installed N -> N+1 continuity remains approval-gated.** Update availability does not authorize body replacement, rollback or signing changes.
6. **Unified health remains partial.** Extend only where active-call evidence closes a meaningful reliability gap.

## Next evidence-driven direction

After live branch/CI state is confirmed, prefer one vertical product closure rather than another maintenance-only slice:

```text
local report outbox -> bounded transport/intake/acknowledgement/reconciliation

or

ordinary browser navigation -> fresh page sensing -> one bounded interaction -> independent postcondition -> recovery
```

Repository synchronization and documentation reconciliation are required engineering hygiene, not product milestones.
