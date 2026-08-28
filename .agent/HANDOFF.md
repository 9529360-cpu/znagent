# ZN Maintainer Handoff

This is the current engineering work site and fact index, not a chat summary or a script. Repository state, real code and actual CI are authoritative. The next maintainer inherits facts, then independently chooses the highest-value product work.

## Current goal

Restore the earlier product-first autonomous maintenance behavior while preserving practical lessons learned since then: coherent work is committed/pushed, CI is respected, and `main` does not silently fall far behind verified development.

The maintenance rule now also teaches product judgment: a maintainer must actively diagnose ZN, distinguish code existence from a real product closure, protect resident continuity, and prioritize real product impact over evidence/process volume.

Git/CI/main synchronization is normal engineering hygiene, not the ZN roadmap.

## Current repository state

- Repository: `9529360-cpu/znagent`
- Canonical branch: `main`
- Development branch: `dev/zn-agent`
- Maintenance branch / PR: `work/maintainer-agency-reset` / PR #14
- PR #13 clean-install promotion is already merged to `main` at `a4f9c95a32571add9bd16ec5aa08a618c8e5566b`.
- At maintenance-branch creation, `dev/zn-agent` was 3 commits ahead of `main` and 0 behind; those commits were post-PR #13 ledger/status reconciliation.
- Historical regression point: `934de7ab19174de5ca1fe81494c9f3ca565f4c97` (`docs: align maintainer promotion rules`) elevated promotion/canonical synchronization into the explicit development loop.
- Useful pre-regression baseline: `AGENTS.md` at `58d416f0527d191f4a752290375d3814ce8be484`.
- Product-judgment refinement commit: `a6ebcd32e54918ab5e5feeb67d3481843006bb61`.
- Implementation-status de-script commit: `852d1e0195165b5e32381857339c74ac5287cdd8`.

## What the maintenance rule now means

- ZN product progress is the primary objective.
- A new maintainer must understand current product state, actively look for real gaps, rank them, and start working without step-by-step user direction.
- HANDOFF queues and status-file candidate work are evidence/suggestions, not immutable commands.
- Important capabilities are judged as `exists -> wired -> verified -> product-closed`; `implemented` alone is not enough.
- ZN identity/memory/work/Will/config/resident continuity receives stronger regression scrutiny than ordinary feature completion.
- Prefer a vertical real-world product closure over many horizontal half-finished modules.
- Documentation, test counts, evidence artifacts, PR/commit counts and branch synchronization must not substitute for real product progress.
- Do not stop after every small step; continue autonomously until a real approval/blocker boundary is reached.
- Commit/push coherent verified increments instead of leaving long-lived unpublished work.
- Keep `main` reasonably synchronized through normal PR/CI when development is stable, but treat this as background Git hygiene rather than a product milestone.
- Preserve explicit human approval for destructive/high-risk identity, memory, credential, updater/replacement, rollback/signing/release-trust and self-approval-boundary changes.

## Completed product evidence still relevant

- Clean-install implementation/proof head `cb913d61f001af6c729a141a3c8631a72e8362cf`.
- `ZN CI` run `33193710879`: success; Python kernel reported 686 tests, 5 skipped.
- `ZN Windows Release Candidate` run `33193711016`: success.
- `ZN Windows Clean Install` run `33193710872`: success.
- Documentation closeout head `4b770345e1267db1cfdc37c9551ff967d6955c27`; CI run `33195494937`: success.
- PR #13 canonical post-merge CI run `33196441295`: success.

These prove completed capability; they do not dictate the next product task.

## Task Queue

| Priority | Status | Task | Completion condition |
| --- | --- | --- | --- |
| P1 | in_progress | Finish PR #14 with product-first autonomy + product judgment | Review exact PR diff and check requirements/current CI state |
| P1 | planned | Merge PR #14 to `dev/zn-agent` through normal traceable flow | No safety-boundary regression; repository merge/check requirements satisfied |
| P1 | planned | Keep `main` reasonably current through normal CI/PR flow | Background engineering hygiene, not a separate product phase |
| P1 | planned | Resume autonomous ZN development | Re-read product contract/status/active code, actively diagnose gaps, then choose highest-value safe vertical closure |

## Known gaps to reassess, not a fixed roadmap

- installed-N continuity baseline and later N -> N+1 continuity;
- failed-update rollback;
- Windows login/reboot autostart on persistent installed state;
- signing/release-trust/formal publication readiness;
- remaining P5 restore/recovery capabilities;
- any higher-priority correctness, security, reliability, active-caller wiring or user-facing blocker found in active code.

`docs/ZN-IMPLEMENTATION-STATUS.md` no longer declares installed-N baseline as the mandatory next slice. It records it as one useful candidate and explicitly requires re-ranking against current product reality.

## Verification state

- Historical AGENTS versions and the promotion-rule regression commit were actually inspected through GitHub.
- The user-provided Actions screenshot showed a successful `dev/zn-agent` ZN CI run for commit `9a72374`; it was not the later PR #14 head.
- Earlier GitHub inspection reported PR #14 open and mergeable; re-check after these latest commits before merge.
- No runtime/product code changed in this maintenance branch; changes are maintainer rules/status/HANDOFF.
- Exact latest-head CI/check state still needs fresh inspection before merge; do not claim it green without GitHub evidence.

## Next action

Inspect PR #14's final three-file diff and exact latest-head check state. If repository requirements are satisfied, merge normally into `dev/zn-agent`, reconcile branch state, and return attention to autonomous product development. The next maintainer should diagnose ZN's current product gaps rather than automatically continuing an inherited evidence slice.