# ZN Implementation Status

This is ZN's current implementation/evidence ledger, not a roadmap or changelog. Real code, Git state and actual test/build/CI results override this file when they disagree.

## Repository state

- Repository: `9529360-cpu/znagent`
- Primary development branch: `dev/zn-agent`
- Canonical/release branch: `main`
- Canonical `main`: `853916aca200848ebd16da3f11e2e1f6a6d4d136` with ZN CI `33280722417` fully green.
- PR #89 temporarily introduced a credentialless request envelope aimed at `push_branch_open_pull_request`; product-intent review determined that this was the wrong default installed-resident authority model.
- PR #90 merged as `8c4d187038010c4eb524d2ddca362b105ce52610` and removed that remote-publication request path, restoring accepted repair authority to `local_commit_only`.
- CI for `8c4d187...` is still pending at the time of this reconciliation; do not claim it green until the run completes.
- No force push, history rewrite, destructive identity/memory migration, updater replacement, rollback, release signing or production credential mutation is part of this stage.

## Installed-upstream authority contract

Normal installed ZN instances may know their official upstream update identity/channel. That knowledge exists so they can detect and verify official updates; it is not source-repository authority.

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
- submit a bounded privacy-safe BUG/repair report upstream.

An installed resident must not receive, merely by being installed:

- private source-repository read/write credentials;
- direct push authority to the official repository;
- direct official-PR creation authority;
- merge authority;
- release/signing/promotion authority.

Those official repository/release operations belong to a separately trusted maintainer environment.

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
| Trusted maintenance source binding | connected + verified, read-only | source-maintenance environment only; ordinary installed client need not have private source checkout |
| Isolated maintenance repair | connected + verified | fresh dedicated `work/*` worktree, bounded Python mutation, fixed oracle and diff evidence |
| Autonomous bounded candidate derivation | connected + verified | model can select/read bounded source and author complete-file replacements only inside the repair boundary |
| Maintenance cognition dispatch accounting | connected + verified, fail-closed | ambiguous provider outcomes are not replayed automatically |
| Independent semantic review | connected + verified, fail-closed | author route cannot grant its own automatic acceptance |
| Pending semantic-review recovery | connected + verified | retained unreviewed attempts can be reconstructed and reviewed later |
| Rejected-attempt cleanup / accepted retention | connected + verified | rejected exact-baseline worktrees can be retired; accepted/drifted/committed attempts are preserved |
| Accepted local publication preparation | connected + verified, `local_commit_only` | exact accepted paths/commit evidence revalidated; no remote authority |
| Installed upstream update observation | partial | release/update infrastructure exists; complete installed read/verify update loop still needs product evidence |
| Upstream BUG / repair reporting | not yet product-closed | needs bounded privacy-safe report submission and maintainer-side intake/acknowledgement semantics |
| Official repository push / PR / merge | intentionally outside installed resident | maintainer-environment authority, not a resident product gap |
| Installed N -> N+1 update continuity | approval-gated / incomplete | no formal updater/replacement transition executed |
| Rollback / signing / release trust | approval-gated / incomplete | high-risk release/update authority remains outside ordinary installed resident |

## Current self-maintenance path

The verified bounded source-maintenance path remains:

```text
real organ failure/success
-> durable privacy-safe health
-> conservative probable_zn_defect task
-> evidence-only source investigation
-> exact clean ZN baseline + bound regression oracle
-> bounded model target selection
-> bounded model repair authoring
-> fresh dedicated work/* worktree
-> fixed unittest oracle + git diff --check
-> independent semantic review
-> accept / reject / remain unreviewed
-> rejected: bounded cleanup
-> accepted: exact diff revalidation -> local-only commit -> clean worktree
-> unreviewed: retain and resume later when an independent reviewer is available
```

Important invariants:

- ordinary Work workspace is not maintenance-source authority;
- source root remains unchanged by repair execution;
- model cognition never receives Git, terminal, arbitrary filesystem, push/merge/release/updater authority;
- semantic acceptance requires an independent route;
- local publication stages only the previously accepted changed paths and verifies parent/path/clean-worktree invariants after commit;
- resident source-maintenance authority stops at `local_commit_only`;
- knowing official upstream/update identity never implies source-repository credential authority;
- installed remote behavior is limited to read/verify update observation plus bounded BUG/repair reporting.

## Exact current evidence

- `33275068276` — targeted candidate derivation + semantic review success.
- `33275525810` — corrected attempt-lifecycle targeted validation success; an earlier run found the Windows worktree parser defect.
- `33277113466` — targeted local publication-preparation validation success after fixing oracle `__pycache__` pollution.
- `33277291497` — durable cognition-dispatch / provider-disconnect no-replay validation success.
- `33277416824` — independent semantic-review fail-closed validation success.
- `33277598171` — pending-review recovery end-to-end validation success.
- `33277689622` — full dev ZN CI success on `f555210c...`.
- `33280722417` — canonical main ZN CI fully green on `853916ac...`.
- PR #90 / merge `8c4d187...` — removed the incorrect installed-resident remote-publication request path. Current CI for this merge remains pending and must be checked before calling it fully verified.

## Current product gaps

1. **Installed update observation needs full closure.** ZN should be able to read and verify official update metadata/artifacts without source checkout or private repository credentials.
2. **BUG/repair reporting needs a bounded product path.** Installed ZN should be able to report a defect or repair proposal upstream with privacy-safe, deduplicated, retry-safe evidence.
3. **Maintainer intake remains separate.** Turning an incoming report into an official `work/*` branch, CI, review, merge and release belongs to the trusted maintainer environment, not to every installed resident.
4. **Installed N -> N+1 continuity remains approval-gated.** Update availability does not authorize body replacement, rollback or signing changes.
5. **Hosted clean-install/release-candidate capacity remains unreliable when jobs fail before executable steps.** Treat those as infrastructure evidence.
6. **Unified health remains partial.** Add observation boundaries only where active-call evidence closes a meaningful reliability gap.

## Next evidence-driven direction

The next safe product work is not resident repository publication. It is:

```text
official update metadata -> installed read/verify/update-available observation
self-diagnosis -> bounded privacy-safe BUG/repair report -> maintainer intake
```

Official source mutation, CI promotion, merge, signing and release stay in the separately trusted maintainer/release environment. Formal updater/replacement, rollback and release trust remain separate explicit approval boundaries.
