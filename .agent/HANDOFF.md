# ZN Maintainer Handoff

This is the current engineering work site and fact index, not a chat transcript or execution script. Real code, Git state and actual test/build/CI results override this file when they disagree.

## Current objective

Keep the now-verified resident self-maintenance source loop coherent through canonical promotion, then continue toward the next highest-value product gap without crossing credential/update approval boundaries.

Current verified resident path:

`real organ failure -> durable health -> probable_zn_defect task -> trusted source investigation -> durable cognition target selection -> bounded repair authoring -> isolated worktree repair -> fixed oracle + diff evidence -> independent semantic review -> accept/reject/unreviewed -> rejected cleanup OR pending-review recovery OR accepted local-only publication commit`

## Repository state

- Repository: `9529360-cpu/znagent`
- Canonical/release branch: `main`
- Primary development branch: `dev/zn-agent`
- Canonical `main` before next promotion: `3b47e517ad594728b05d7346ecbb4db25cd3e115` (PR #80).
- Verified product-code `dev/zn-agent`: `f555210c7417d4f81564ff238be65a0f82a6cc7b` (PR #86).
- Full dev ZN CI `33277689622`: **fully green** — Source Boundary, zero-model boot, resident core compile, full Python core suite, Electron/TypeScript and readable status publication all succeeded.
- Combined commit statuses on `f555210c...`: ZN Source Boundary / ZN Kernel-Python / Electron-TypeScript all `success`.
- Canonical main ZN CI `33274781251` on `3b47e517...`: **fully green**.
- Hosted clean-install `33277689670` and release-candidate `33277689603` have jobs with no executable steps; treat as runner-allocation/infrastructure failures, not product pass/fail evidence.

## Verified product reality

### Candidate derivation + isolated repair

Formal resident derives a bounded candidate from trusted maintenance/source evidence. Model output is constrained to existing core Python/test paths and revalidated locally. The repair operator writes only inside a fresh dedicated `.zn-maintenance-worktrees/...` worktree and runs the bound unittest oracle plus `git diff --check`. Source root stays unchanged.

### Durable model dispatch safety

Target-selection, repair-authoring and semantic-review provider calls are durably reserved before dispatch. Journal state contains fingerprints and route/provider/model metadata only; no raw source, prompt context, diff or model response is persisted. Ambiguous provider outcomes become `outcome_uncertain` and are not automatically replayed.

### Independent semantic acceptance

Automatic acceptance requires a model route distinct from the repair author. With no independent route, repair remains `unreviewed` and cannot produce a publication commit. Same-author review fallback cannot grant publication.

### Review recovery

A retained `unreviewed` repair caused by independent-reviewer unavailability can later be resumed without re-running author calls. Recovery re-verifies baseline/branch/HEAD/changed-path/diff fingerprints and refuses if any prior semantic provider dispatch exists for that task.

### Attempt lifecycle

Rejected exact-baseline worktrees/branches can be cleaned safely. Accepted, committed, drifted or unknown attempts are not auto-deleted.

### Local publication preparation

Accepted repair can be revalidated, staged only on accepted paths and turned into one local commit. Parent, changed paths and clean-worktree state are checked after commit. Authority is explicitly `local_commit_only`.

No resident push, PR, merge, release, updater, rollback, signing or repository credential authority exists in this path.

## Exact evidence

- `33275068276` — candidate derivation + semantic review targeted validation success.
- `33275525810` — corrected attempt-lifecycle targeted validation success; earlier `33275445850` found the Windows worktree parser defect.
- `33277113466` — local publication targeted validation success after fixing oracle `__pycache__` worktree pollution.
- `33277291497` — durable cognition dispatch / provider-disconnect no-replay validation success.
- `33277416824` — independent semantic-review fail-closed validation success.
- `33277598171` — pending-review recovery end-to-end validation success.
- `33277689622` — full dev ZN CI success on `f555210c...` across all formal jobs.

## Current gaps / risks

1. **Remote publication / PR / CI feedback is not connected as a resident capability.** A verified local repair commit cannot yet be pushed, opened as a PR, observed through remote CI, or continued after remote CI failure by the resident itself.
2. **Repository credential expansion is an explicit approval boundary.** Resident-owned GitHub token/credential use must not be added silently.
3. **Installed N -> N+1 continuity remains approval-gated.** Updater/replacement, rollback, release signing/trust and replacement of the user's current installed body are not authorized by source-maintenance maturity.
4. **Hosted clean-install / release-candidate runner capacity is unreliable.** Pre-step failures remain infrastructure evidence.
5. **Unified health remains partial.** Add new health owners only where a real active caller closes a meaningful reliability gap.

## Next dependency-ready work

1. Promote the coherent verified SM3/SM4 source-maintenance stage to `main` through normal PR/merge and run canonical main ZN CI.
2. Reassess product gaps after canonical verification; do not manufacture more maintenance abstractions if a real active-call reliability gap is higher value.
3. Before implementing resident remote publication, obtain explicit approval for narrowly scoped repository credential authority and define fail-closed token/branch/PR/CI boundaries.
4. Keep formal updater/replacement, rollback, signing and release trust behind their existing explicit human approval gates.

No credential expansion, updater/replacement, rollback or signing action is authorized by this handoff.
