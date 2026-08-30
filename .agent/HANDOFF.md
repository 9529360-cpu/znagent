# ZN Maintainer Handoff

This is the current engineering work site and fact index, not a chat transcript or execution script. Real code, Git state and actual test/build/CI results override this file when they disagree.

## Current objective

Preserve the resident self-maintenance loop while enforcing the installed-product upstream authority boundary:

```text
official upstream update channel -> installed ZN (read / verify / update availability)
installed ZN -> bounded BUG / repair report channel
maintainer environment -> official source branch / CI / review / merge / release
```

The normal installed resident must not receive official source-repository push, PR, merge, release or signing authority.

## Repository state

- Repository: `9529360-cpu/znagent`
- Canonical/release branch: `main`
- Primary development branch: `dev/zn-agent`
- Canonical `main`: `853916aca200848ebd16da3f11e2e1f6a6d4d136`; canonical ZN CI `33280722417` fully green.
- PR #89 introduced a credentialless request envelope aimed at future `push_branch_open_pull_request`. Product-intent review determined that this was the wrong default installed-resident direction.
- PR #90 merged as `8c4d187038010c4eb524d2ddca362b105ce52610` and removed that remote-publication request path, restoring resident maintenance authority to `local_commit_only`.
- CI for `8c4d187...` is pending at this handoff update; do not claim green until checked.

## Verified product reality

### Source-maintenance loop

The formal source-maintenance environment can derive a bounded repair candidate, execute it in an isolated `.zn-maintenance-worktrees/...` worktree, run the bound oracle and diff checks, obtain independent semantic review, retain/recover unreviewed attempts, clean rejected attempts, and create a verified local-only commit for accepted repairs.

Model calls remain bounded and durably accounted. Model cognition does not receive repository push/merge/release/updater authority.

### Installed upstream boundary

Installed ZN instances may know their official update identity/channel. That is required for update discovery and verification and does not imply access to the private source repository.

Installed remote authority is limited to:

- read/verify official update metadata and artifacts;
- surface update availability;
- submit bounded privacy-safe BUG/repair reports to an operator-controlled upstream reporting channel.

Installed ZN must not directly push the official repository, create official PRs, merge, release, sign or promote versions. Those actions belong to a separately trusted maintainer/release environment.

### Maintainer authority

The maintainer environment may consume an incoming report, reproduce it, create a repository `work/*` branch, run CI, review, merge and release according to repository policy. This authority is not distributed with ZN installations.

## Exact evidence

- `33275068276` — candidate derivation + semantic review targeted success.
- `33275525810` — corrected attempt-lifecycle targeted success.
- `33277113466` — local publication targeted success after fixing oracle `__pycache__` pollution.
- `33277291497` — durable cognition dispatch/provider-disconnect no-replay success.
- `33277416824` — independent semantic-review fail-closed success.
- `33277598171` — pending-review recovery end-to-end success.
- `33277689622` — full dev ZN CI success on `f555210c...`.
- `33280722417` — canonical main ZN CI fully green on `853916ac...`.
- PR #90 / `8c4d187...` — removed the incorrect installed-resident repository-publication request path; current CI pending.

## Current gaps / risks

1. **Installed update observation is not yet fully product-closed.** Verify the complete read/verify/update-available path without private source access.
2. **Upstream BUG/repair reporting is not yet product-closed.** Needs bounded privacy-safe payload, deduplication/retry semantics, acknowledgement and maintainer intake.
3. **Official repository publication is not an installed-resident gap.** Push/PR/merge/release belongs to trusted maintainer infrastructure.
4. **Installed N -> N+1 continuity remains approval-gated.** Updater/replacement, rollback and release signing/trust are not authorized by source-maintenance maturity.
5. **Hosted clean-install / release-candidate runner allocation can fail before steps.** Treat those as infrastructure evidence, not product pass/fail evidence.
6. **Unified health remains partial.** Add owners only where a real active caller closes a meaningful reliability gap.

## Next dependency-ready work

1. Finish CI verification for PR #90 authority correction.
2. Keep architecture/status docs aligned with the two-direction upstream model.
3. Implement/verify installed read-only update observation against the official update channel without private repository credentials.
4. Implement a bounded privacy-safe BUG/repair report path and maintainer-side intake semantics.
5. Keep official repository mutation, merge, release, updater/replacement, rollback and signing in their existing trusted/approval-gated boundaries.

No ordinary installed-resident repository write, merge, release, updater-replacement, rollback or signing authority is authorized by this handoff.
