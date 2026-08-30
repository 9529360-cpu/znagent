# ZN Maintainer Handoff

This is the current engineering work site and fact index, not a chat transcript or execution script. Real code, Git state and actual test/build/CI results override this file when they disagree.

## Current objective

Preserve the resident self-maintenance loop while enforcing the installed-product upstream boundary:

```text
official public update channel -> installed ZN (read / verify / update availability)
installed ZN -> bounded BUG / repair report channel
maintainer environment -> private source branch / CI / review / merge / release
```

The normal installed resident must not receive official source-repository push, PR, merge, release, signing or repository-credential authority, and its shipped runtime should not need the private source-repository slug.

## Repository state

- Repository: `9529360-cpu/znagent`
- Canonical/release branch: `main`
- Primary development branch: `dev/zn-agent`
- Canonical `main`: `853916aca200848ebd16da3f11e2e1f6a6d4d136`; canonical ZN CI `33280722417` fully green.
- `dev/zn-agent`: `fb71661cda0d8269cd0e56c990a3356b73a3e2f6` after PRs #90-#91 corrected the installed-upstream authority model.
- PR #92 is the open dev -> main promotion of the corrected authority contract; do not merge until current privacy/source work is integrated and full dev CI is green.
- Current work branch: `work/remove-private-repo-runtime-identity`.

## Verified product reality

### Source-maintenance loop

The formal source-maintenance environment can derive a bounded repair candidate, execute it in an isolated `.zn-maintenance-worktrees/...` worktree, run bound oracle/diff checks, obtain independent semantic review, retain/recover unreviewed attempts, clean rejected attempts and create a verified `local_commit_only` commit for accepted repairs.

Model calls remain bounded and durably accounted. Model cognition does not receive repository push/merge/release/updater authority.

### Installed upstream boundary

Installed ZN may know the public official update channel. Current release infrastructure already supports an HTTPS `stable.json` channel and immutable release assets; update discovery does not require private source checkout or repository credentials.

Installed remote authority is limited to:

- read/verify official update metadata and artifacts;
- surface update availability;
- eventually submit bounded privacy-safe BUG/repair reports to an operator-controlled reporting channel.

Installed ZN must not directly push the official repository, create official PRs, merge, release, sign or promote versions.

### Private source identity no longer belongs in shipped runtime

Current work removes the hardcoded private source-repository slug from:

- `runtime/python/zn_agent/core/maintenance_source.py`;
- `maintenance_repair.py`;
- `maintenance_publication.py`;
- `maintenance_attempt_lifecycle.py`;
- `apps/desktop/package.json`.

Trusted source continuity now uses:

```text
explicit source_root
-> ZN ownership markers
-> live origin
-> one-way origin fingerprint
-> later source action must match the same fingerprint
```

The resident database keeps only the fingerprint for source-origin continuity. Repair, cleanup and local-publication actions fail closed if the origin changes after investigation. `.agent/verify_zn_source_boundary.py` now permanently rejects the private source slug if it reappears in shipped resident core or desktop package metadata.

## Exact evidence

- `33275068276` — candidate derivation + semantic review targeted success.
- `33275525810` — corrected attempt-lifecycle targeted success.
- `33277113466` — local publication targeted success after fixing oracle `__pycache__` pollution.
- `33277291497` — durable cognition dispatch/provider-disconnect no-replay success.
- `33277416824` — independent semantic-review fail-closed success.
- `33277598171` — pending-review recovery end-to-end success.
- `33277689622` — prior full dev ZN CI success on `f555210c...`.
- `33280722417` — canonical main ZN CI fully green on `853916ac...`.
- PR #90 / `8c4d187...` — removed the incorrect installed-resident repository-publication request path before it reached main.
- `33283442938` — first private-source validation attempt: source boundary + compilation green; tests did not start because the temporary workflow omitted runtime dependencies (`psutil`). Infrastructure/setup defect only.
- `33283483244` — corrected targeted Windows validation fully green: source privacy boundary, changed-owner compilation, source investigation, isolated repair including origin-drift rejection, local publication, attempt lifecycle, review recovery and semantic-independence regressions.

## Current gaps / risks

1. **Current privacy/source work still needs normal PR -> dev + full dev CI.** Targeted validation is green but is not whole-tree evidence.
2. **Installed update observation is not yet fully product-closed.** Verify the complete read/verify/update-available path from public channel through resident/UI evidence without private source access.
3. **Upstream BUG/repair reporting is not yet product-closed.** Needs bounded privacy-safe payload, durable dedup/retry semantics, acknowledgement and maintainer intake.
4. **Official repository publication is not an installed-resident gap.** Push/PR/merge/release belongs to trusted maintainer infrastructure.
5. **Installed N -> N+1 continuity remains approval-gated.** Updater/replacement, rollback and release signing/trust are not authorized by source-maintenance maturity.
6. **Hosted clean-install / release-candidate runner allocation can fail before steps.** Treat those as infrastructure evidence, not product pass/fail evidence.

## Next dependency-ready work

1. Merge the private-source identity removal to `dev/zn-agent` through normal PR and require full dev ZN CI green.
2. Let PR #92 advance to the new dev head, then promote the coherent authority/privacy stage to `main` and require canonical main CI green.
3. Implement the next safe installed-product layer: bounded upstream BUG/repair reporting without repository credentials or arbitrary remote authority.
4. Continue closing installed read-only update observation against the public update channel.
5. Keep official repository mutation, merge, release, updater/replacement, rollback and signing in their existing trusted/approval-gated boundaries.

No ordinary installed-resident repository write, merge, release, updater-replacement, rollback or signing authority is authorized by this handoff.
