# ZN Implementation Status

This is ZN's current implementation/evidence ledger, not a roadmap or changelog. Real code, Git state and actual test/build/CI results override this file when they disagree.

## Repository state

- Repository: `9529360-cpu/znagent`
- Primary development branch: `dev/zn-agent`
- Canonical/release branch: `main`
- Canonical `main`: `4b3a7f1c1bc45565abaeb894702e96b1f1b2881d`, produced by promotion PR #92.
- Current `dev/zn-agent`: `b1c86ee2a20a26954d54450160144f921365617c`, 24 commits ahead of `main`, after PR #95 (privacy-safe local defect-report outbox) and PR #96 (ordinary Work -> managed-browser navigation).
- Full dev ZN CI run `33286758708` is green on `b1c86ee2...`: `ZN Source Boundary`, `ZN Kernel / Python`, and `Electron / TypeScript` all succeeded.
- The prior main push run `33285157720` was cancelled and therefore is not green canonical evidence; the last known-green canonical evidence before that promotion remains `33280722417` on the prior main. A new dev -> main promotion must therefore be followed by fresh main CI rather than treating the cancelled run as success.
- No force push, history rewrite, destructive identity/memory migration, updater replacement, rollback, release signing or production credential mutation is part of this stage.

## Installed-upstream authority contract

Normal installed ZN instances may know their official upstream **update channel** so they can detect and verify official updates. That knowledge is not source-repository authority and does not require exposing or accessing the private source repository.

The intended product boundary is:

```text
official upstream update channel -> installed ZN
installed ZN -> bounded BUG / repair report channel
```

An installed resident may:

- read official update metadata;
- determine whether a newer version is available;
- verify update identity/integrity/trust evidence;
- diagnose itself and form bounded local repair evidence when a source-maintenance environment exists;
- form a bounded privacy-safe BUG/repair report for upstream submission.

An installed resident must not receive, merely by being installed:

- private source-repository credentials or source-repository identity as an authority primitive;
- direct push authority to the official repository;
- direct official-PR creation authority;
- merge authority;
- release/signing/promotion authority.

Those official repository/release operations belong to a separately trusted maintainer environment.

## Private-source identity boundary

The shipped resident core does not need a compiled-in repository slug to prove source continuity. An explicitly supplied maintenance source must satisfy ZN ownership markers and have an `origin`; the investigator persists only a one-way `zn-maintenance-origin-v1` fingerprint. Repair, cleanup and local-publication owners re-read the live origin and require the same fingerprint before any source-side effect.

The actual private repository URL may remain in repository-internal maintainer docs/tests/release tooling where required, but CI rejects that private source identity if it reappears in shipped resident core or desktop package metadata.

## Capability maturity ledger

Use `exists -> connected -> verified -> product-closed`. File/interface presence is not proof that a product capability is closed end to end.

| Area | Current maturity | Evidence boundary / remaining gap |
| --- | --- | --- |
| Resident Self / Body / Senses / Situation / Thought / Will | connected + repeatedly verified | ZN-owned resident; zero-model boot remains required |
| Durable Work / restart recovery | connected + verified | existing Work/thread continuity retained |
| Installed resident desktop-independence/autostart | verified | real resident Scheduled Task continuity evidence exists |
| Durable resident reference continuity | verified | resident state, Work/thread references, long-term memory and verified learning survive restart/installed continuity proof |
| Resident health classification/task formation | connected + verified, fail-closed | only narrow repeated internal defects become maintenance candidates |
| Multi-organ health observation | materially connected + verified | unified health remains partial |
| Maintenance investigation lifecycle | connected + verified | baseline/oracle/attempt/acceptance is bounded evidence/control state |
| Trusted maintenance source binding | connected + verified, read-only | explicit source + ZN ownership markers + opaque origin fingerprint; private repository slug is not shipped authority |
| Isolated maintenance repair | connected + verified | fresh dedicated `work/*` worktree, bounded Python mutation, fixed oracle/diff evidence, source-origin drift fails closed |
| Autonomous bounded candidate derivation | connected + verified | model can select/read bounded source and author complete-file replacements only inside the repair boundary |
| Maintenance cognition dispatch accounting | connected + verified, fail-closed | ambiguous provider outcomes are not replayed automatically |
| Independent semantic review | connected + verified, fail-closed | author route cannot grant its own automatic acceptance |
| Pending semantic-review recovery | connected + verified | retained unreviewed attempts can be reconstructed and reviewed later |
| Rejected-attempt cleanup / accepted retention | connected + verified | cleanup re-verifies opaque source-origin continuity and exact baseline/worktree identity |
| Accepted local publication preparation | connected + verified, `local_commit_only` | no remote repository authority |
| Upstream BUG / repair report formation | connected + verified locally | repeated `probable_zn_defect` tasks project into one durable privacy-safe installation-pseudonymous local outbox envelope; restart repairs missing projection; status is explicitly `local_outbox_only`, `transport_available=false` |
| Upstream BUG / repair report transport | missing / intentionally ungranted | no endpoint or network sender exists yet; future transport must reserve dispatch durably and reconcile ambiguous outcomes without blind replay |
| Resident managed-browser navigation | connected + verified for narrow ordinary Work entry | one explicit HTTP(S) URL plus unambiguous navigation cue can become `browser_navigate`; managed Chromium E2E and durable Work facade path are green |
| Resident managed-browser page interaction | partial / not authorized by current slice | no general click/form/text-entry authority yet; broader page sensing/actions, downloads/uploads, stale-target recovery and richer postconditions remain product work |
| User browser bridge | architecture only / missing | authenticated existing-user-browser path is not product-closed |
| Installed upstream update observation | partial | public `stable.json` channel infrastructure exists; complete installed read/verify update loop still needs product evidence |
| Official repository push / PR / merge | intentionally outside installed resident | maintainer-environment authority, not a resident product gap |
| Installed N -> N+1 update continuity | approval-gated / incomplete | no formal updater/replacement transition executed |
| Rollback / signing / release trust | approval-gated / incomplete | high-risk release/update authority remains outside ordinary installed resident |

## Current self-maintenance / reporting path

```text
real organ failure/success
-> durable privacy-safe health
-> conservative probable_zn_defect task
-> local privacy-safe upstream-report projection
-> durable local outbox envelope (deduplicated per incident/install)
-> no transport authority yet

optional trusted source-maintenance environment:
probable_zn_defect
-> explicit source binding + opaque origin fingerprint
-> exact clean baseline + bound regression oracle
-> bounded candidate derivation
-> fresh dedicated work/* worktree
-> fixed unittest oracle + git diff --check
-> independent semantic review
-> accept / reject / remain unreviewed
-> accepted: exact diff revalidation -> local-only commit -> clean worktree
```

Important invariants:

- health truth commits before best-effort report projection, so reporting failure cannot roll back resident health;
- report payload does not expose raw error text, local paths, repository identity, credentials, organ name, task id or local health fingerprint;
- the same incident on different installations gets unrelated installation-scoped pseudonyms;
- any future report transport must durably reserve dispatch before external side effects; ambiguous outcomes remain `outcome_uncertain` until explicit reconciliation;
- ordinary Work workspace is not maintenance-source authority;
- model cognition never receives Git, terminal, arbitrary filesystem, push/merge/release/updater authority;
- resident source-maintenance authority stops at `local_commit_only`.

## Managed-browser ordinary Work path

PR #96 closes one narrow but real user-entry gap:

```text
ordinary durable Work
+ exactly one explicit HTTP(S) URL
+ explicit navigation intent
-> deterministic browser_navigate action
-> managed Chromium navigation
-> independently observed current URL postcondition
-> durable Work completion/failure state
```

The model is not allowed to invent the destination. Multiple URLs, malformed URLs, embedded credentials, or prose merely discussing a URL do not create browser authority. This is navigation closure only; it is not evidence that the full browser product is complete.

## Exact current evidence

- `33275068276` — targeted candidate derivation + semantic review success.
- `33275525810` — corrected attempt-lifecycle targeted validation success.
- `33277113466` — targeted local publication-preparation validation success.
- `33277291497` — durable cognition-dispatch / provider-disconnect no-replay validation success.
- `33277416824` — independent semantic-review fail-closed validation success.
- `33277598171` — pending-review recovery end-to-end validation success.
- `33277689622` — prior full dev ZN CI success on `f555210c...`.
- `33280722417` — last known-green canonical main CI before promotion PR #92.
- PR #92 / `4b3a7f1...` — promoted corrected upstream/private-source authority contract to main; its immediate push run `33285157720` was cancelled, so do not claim that run as green.
- `33284716266` — targeted Windows reporting-outbox validation success.
- PR #95 / `52a539650...` — connected resident health/maintenance truth to privacy-safe durable local report projection.
- `33286593120` — initial ordinary-Work browser navigation + real local Chromium E2E success.
- `33286655544` — durable `ResidentWorkLedger` user-entry browser path + existing real Chromium E2E success.
- `33286758708` — full dev ZN CI fully green on `b1c86ee2...` after PR #96.

## Current product gaps

1. **Canonical branch/document synchronization must remain part of each verified stage.** The #95/#96 stage became verified on dev while status/HANDOFF and main were still describing the earlier stage; this is repository-maintenance drift, not a product capability. Normal maintenance must reconcile changed truth in the same coherent slice and promote stable verified dev stages without letting large unexplained gaps accumulate.
2. **BUG/repair reporting is locally connected but not remotely product-closed.** The next report step is a bounded operator-controlled transport/intake/acknowledgement contract, without repository credentials or general network authority.
3. **Managed browser is only navigation-closed.** ZN still needs bounded page observation and interaction semantics, fresh-target checks, richer postconditions, and failure recovery before ordinary browser tasks are product-closed.
4. **User Browser Bridge is still missing.** Authenticated user-session reality cannot be solved by copying browser credentials into the managed profile.
5. **Installed update observation still needs full closure.** Read/verify/update-available must be proven end-to-end independently of private source access.
6. **Installed N -> N+1 continuity remains approval-gated.** Update availability does not authorize body replacement, rollback or signing changes.
7. **Unified health remains partial.** Add observation boundaries only where active-call evidence closes a meaningful reliability gap.

## Next evidence-driven direction

After repository/doc synchronization, prefer a vertical product closure rather than another maintenance-only slice. Two high-value dependency-ready candidates are:

```text
local report outbox -> bounded transport/intake/acknowledgement/reconciliation

or

ordinary browser navigation -> bounded page sensing/action/postcondition/recovery
```

Choose between them from active-caller reachability and risk, while keeping official repository mutation, updater/replacement, rollback and signing in their existing trusted/approval-gated boundaries.
