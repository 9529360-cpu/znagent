# ZN Implementation Status

This is ZN's current implementation/evidence ledger, not a roadmap or changelog. Real code, Git state and actual test/build/CI results override this file when they disagree.

## Repository state

- Repository: `9529360-cpu/znagent`
- Primary development branch: `dev/zn-agent`
- Canonical/release branch: `main`
- Current verified dev head: `f555210c7417d4f81564ff238be65a0f82a6cc7b` (PR #86 merge).
- Canonical `main` before the next promotion: `3b47e517ad594728b05d7346ecbb4db25cd3e115` (PR #80 promotion).
- Canonical main ZN CI `33274781251` is fully green on `3b47e517...`.
- Latest full dev ZN CI `33277689622` is fully green on `f555210c...`: Source Boundary, Kernel/Python full core suite, Electron/TypeScript and readable commit status publication all succeeded.
- Latest hosted Windows clean-install run `33277689670` and release-candidate run `33277689603` created jobs with no executable steps. These are runner-allocation/infrastructure failures, not product pass/fail evidence.
- No force push, history rewrite, destructive identity/memory migration, updater replacement, rollback, release signing or production credential mutation is part of this stage.

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
| Trusted maintenance source binding | connected + verified, read-only | exact ZN root/origin/ownership required; ordinary Work is not authority |
| Isolated maintenance repair | connected + full-CI verified | fresh dedicated `work/*` worktree, bounded Python mutation, fixed oracle and diff evidence |
| Autonomous bounded candidate derivation | connected + verified | model can select/read bounded source and author complete-file replacements only inside the repair boundary |
| Maintenance cognition dispatch accounting | connected + verified, fail-closed | provider calls are durably reserved before dispatch; ambiguous outcomes are not replayed automatically; only fingerprints/route metadata are persisted |
| Independent semantic review | connected + verified, fail-closed | author route cannot grant its own automatic acceptance; no independent route leaves the attempt `unreviewed` |
| Pending semantic-review recovery | connected + verified | retained unreviewed attempts can be reconstructed from durable evidence/worktree and reviewed later without re-running author calls |
| Rejected-attempt cleanup / accepted retention | connected + verified | rejected exact baseline worktrees can be retired; accepted/drifted/committed attempts are preserved |
| Accepted local publication preparation | connected + verified, `local_commit_only` | accepted diff/path fingerprints are rechecked, exact paths staged, local commit created and clean state verified |
| Remote repair publication / PR / CI feedback | not connected as resident product path | resident has no repository credential/push/PR authority and no remote CI feedback continuation loop |
| Installed N -> N+1 update continuity | approval-gated / incomplete | no formal updater/replacement transition executed |
| Rollback / signing / release trust | approval-gated / incomplete | high-risk release/update authority remains outside autonomous source development |

## Current self-maintenance path

The verified bounded resident path is now:

```text
real organ failure/success
-> durable privacy-safe health
-> conservative probable_zn_defect task
-> evidence-only source investigation
-> exact clean ZN baseline + bound regression oracle
-> bounded model target selection (durably journaled dispatch)
-> bounded model repair authoring (durably journaled dispatch)
-> fresh dedicated work/* worktree
-> bounded existing core Python/test replacements
-> fixed unittest oracle + git diff --check
-> privacy-safe repair evidence
-> independent semantic review (durably journaled dispatch)
-> accept / reject / remain unreviewed
-> rejected: bounded cleanup
-> accepted: exact diff revalidation -> local-only commit -> clean worktree
-> unreviewed: retain and resume later when an independent reviewer is available
```

Important invariants:

- ordinary Work workspace is not maintenance-source authority;
- source root remains unchanged by repair execution;
- model cognition never receives Git, terminal, arbitrary filesystem, push/merge/release/updater authority;
- model source context, diff text and response bodies are not copied into the durable cognition journal;
- a recorded cognition dispatch is never automatically replayed after an ambiguous provider outcome;
- semantic acceptance requires an independent route; same-author fallback cannot publish;
- local publication stages only the previously accepted changed paths and verifies parent/path/clean-worktree invariants after commit;
- resident authority stops at `local_commit_only`; there is no push/PR/merge/release/updater credential authority in this path.

## Exact current evidence

- `33274781251` — canonical main ZN CI success on `3b47e517...` after PR #80; all three readable statuses succeeded.
- `33275068276` — targeted candidate derivation + semantic review validation success before PR #81.
- `33275525810` — corrected targeted attempt-lifecycle validation success before PR #82; an earlier run `33275445850` found and drove the real Windows worktree parser fix.
- `33277113466` — targeted local publication-preparation validation success before PR #83; earlier diagnostics identified oracle-generated `__pycache__` pollution and the clean-worktree guard was preserved.
- `33277291497` — targeted durable cognition-dispatch validation success before PR #84, including provider-disconnect no-replay behavior.
- `33277416824` — targeted semantic-independence validation success before PR #85; a single-route deployment remains unreviewed and does not produce a publication commit.
- `33277598171` — targeted pending-review recovery validation success before PR #86; author-only -> retained unreviewed attempt -> later independent reviewer -> accept -> clean local commit.
- `33277689622` — full dev ZN CI success on `f555210c...`: Source Boundary, zero-model boot, resident-core compile, full Python core suite, Electron/TypeScript and readable status publication all succeeded.

## Current product gaps

1. **Remote publication is not a resident capability.** ZN can prepare a verified local repair commit, but it cannot push a maintenance branch, create a PR, ingest remote CI results or continue a failed remote CI repair loop.
2. **Repository credential authority is intentionally absent.** Granting the resident a GitHub/repository credential would expand credential permissions and requires explicit human approval under the project safety contract.
3. **Installed N -> N+1 continuity remains approval-gated.** Local source-repair maturity does not authorize updater/replacement, rollback, signing, release trust or replacement of the user's installed body.
4. **Hosted clean-install/release-candidate capacity is currently unreliable.** Recent jobs terminate before executable steps are allocated; this remains infrastructure evidence rather than product evidence.
5. **Unified health remains partial.** Additional observation boundaries should be connected only where active-call evidence closes a meaningful reliability gap.

## Next evidence-driven direction

Within current authority, keep the self-maintenance source path conservative and complete the repository/canonical evidence loop around these verified changes. The next product capability after `local_commit_only` is a bounded remote publication/PR/CI feedback layer, but implementation of resident-owned GitHub credential use must not begin without explicit approval for that credential-permission expansion.

Formal updater/replacement, rollback, release signing/trust and replacement of the user's installed version remain separate explicit approval boundaries.
