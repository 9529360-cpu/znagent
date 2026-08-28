# ZN Maintainer Handoff

This is the current engineering work site and fact index, not a chat summary or a script. Repository state, real code and actual CI are authoritative. The next maintainer inherits facts, then independently chooses the highest-value product work.

## Current goal

Restore the earlier product-first autonomous maintenance behavior while preserving the practical lessons learned since then: work must be committed/pushed in coherent increments, CI must be respected, and `main` must not silently fall far behind verified development.

Git/CI/main synchronization is normal engineering hygiene, not the ZN roadmap. After this maintenance change lands, resume product development by re-reading ZN goals/status/code and choosing the highest-value real product gap.

## Current repository state

- Repository: `9529360-cpu/znagent`
- Canonical branch: `main`
- Development branch: `dev/zn-agent`
- Maintenance branch / PR: `work/maintainer-agency-reset` / PR #14
- PR #13 clean-install promotion is already merged to `main` at `a4f9c95a32571add9bd16ec5aa08a618c8e5566b`.
- At maintenance-branch creation, `dev/zn-agent` was 3 commits ahead of `main` and 0 behind; those commits were post-PR #13 ledger/status reconciliation.
- Historical regression point identified: `934de7ab19174de5ca1fe81494c9f3ca565f4c97` (`docs: align maintainer promotion rules`) elevated promotion/canonical synchronization into the explicit development loop.
- Useful pre-regression baseline: `AGENTS.md` at `58d416f0527d191f4a752290375d3814ce8be484`.
- Current maintenance-rule head after restoring the product-first wording: `04db1d24ec230d6fc7c94e90f60f6e6a009ba8db` before this HANDOFF commit.

## What the maintenance rule now means

- ZN product progress is the primary objective.
- A new maintainer must understand current product state, identify the most valuable real gap and start working without waiting for step-by-step user direction.
- HANDOFF queues are evidence and suggestions, not immutable commands.
- Do not stop after every small step; continue autonomously until a real approval/blocker boundary is reached.
- Commit/push coherent verified increments instead of leaving long-lived uncommitted/unpublished work.
- Keep `main` reasonably synchronized through normal PR/CI when development is stable, but treat this as background Git hygiene rather than a product milestone.
- Do not repeatedly ask the user whether to commit, push, open a normal PR, inspect/fix CI, or perform low-risk branch synchronization.
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
| P1 | in_progress | Finish PR #14 with the restored product-first/autonomous rule | Exact PR head reviewed; required checks green or repository policy confirms docs-only path needs no separate run |
| P1 | planned | Merge PR #14 to `dev/zn-agent` and reconcile normal branch state | Traceable merge, no safety-boundary regression |
| P1 | planned | Keep `main` reasonably current through normal CI/PR flow | Treat as engineering hygiene, not a separate product phase |
| P1 | planned | Resume autonomous ZN development | Re-read `ZN.md`, implementation status and active code; choose highest-value gap based on product impact/risk/dependencies |

## Candidate product gaps to reassess

- installed-N continuity and later N -> N+1 continuity;
- failed-update rollback;
- Windows login/reboot autostart on persistent installed state;
- signing/release-trust/formal publication readiness;
- remaining P5 restore/recovery capabilities;
- any higher-priority correctness, security, reliability or user-facing blocker found in active code.

This list is not a fixed sequence. The maintainer should inspect current reality and choose.

## Verification state

- Historical AGENTS versions and the promotion-rule regression commit were actually inspected through GitHub.
- The user-provided Actions screenshot shows a successful recent `dev/zn-agent` ZN CI run, but that run is for commit `9a72374`, not the current PR #14 head.
- GitHub currently reports PR #14 as open and mergeable.
- GitHub Actions API currently shows no workflow run for the PR #14 work-branch head; commit status has no reported checks. Do not mislabel the screenshot as exact-head PR #14 CI.
- This maintenance change modifies documentation/rules only; no runtime/product code was changed.

## Next action

Inspect the updated PR #14 diff and repository check requirements for its exact head. If no required check is missing, merge normally to `dev/zn-agent`. Then keep branch synchronization routine and return attention to autonomous product development rather than creating another promotion/evidence phase.