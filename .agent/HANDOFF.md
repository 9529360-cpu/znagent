# ZN Maintainer Handoff

This is the current engineering work site and fact index, not a chat summary or a script for the next maintainer. Repository state, code and real CI remain authoritative. Re-evaluate priorities from the product and code before blindly continuing this queue.

## Current goal

The Windows x64 clean-install + first resident-start proof is complete and canonically verified. The immediate maintenance goal is to restore strong maintainer autonomy: keep the safe `work/* -> dev/zn-agent -> main` promotion model, while ensuring future maintainers choose work from ZN's real product gaps rather than mechanically extending the previous evidence slice.

After this maintenance-rule change is verified and promoted, the next product task must be selected by re-reading `ZN.md`, implementation status, current code and remaining milestone gaps. The previously proposed installed-N baseline evidence remains a candidate, not an automatic mandate.

## Repository state at branch creation

- Repository: `9529360-cpu/znagent`
- Canonical branch: `main`
- Development branch: `dev/zn-agent`
- Maintenance branch: `work/maintainer-agency-reset`
- Canonical clean-install promotion merge: `a4f9c95a32571add9bd16ec5aa08a618c8e5566b`
- At inspection time `dev/zn-agent` was 3 commits ahead of `main` and 0 behind; those commits reconcile post-PR #13 ledger/status documentation.
- This maintenance branch was created from that current `dev/zn-agent` state.
- PR #13 is already merged; any older HANDOFF text describing clean-install promotion as pending is stale.
- No force push/history rewrite is authorized or required.

## Completed product evidence

The clean-install stage already has real implementation and canonical verification:

- Implementation/proof head `cb913d61f001af6c729a141a3c8631a72e8362cf`.
- `ZN CI` run `33193710879`: success; Python kernel reported 686 tests, 5 skipped.
- `ZN Windows Release Candidate` run `33193711016`: success.
- `ZN Windows Clean Install` run `33193710872`: success; installed resident runtime identity matched the implementation head and the materialized isolated Python runtime was exercised.
- Documentation closeout head `4b770345e1267db1cfdc37c9551ff967d6955c27`; CI run `33195494937`: success.
- Canonical promotion merge `a4f9c95a32571add9bd16ec5aa08a618c8e5566b` via PR #13.
- Canonical post-merge CI run `33196441295`: success.

This evidence should remain available as proof, but generating ever-more evidence is not itself the product roadmap.

## Maintenance-rule change in progress

`AGENTS.md` is being adjusted to make these points explicit:

- advancing ZN is the primary objective; process artifacts are supporting tools;
- maintainers should independently re-evaluate the highest-value next task from current product gaps;
- HANDOFF Task Queue is advisory operational state, not an immutable instruction chain;
- small tasks use a lightweight verified loop; medium/large/high-risk tasks use progressively stronger process;
- low-risk reversible engineering decisions should be made autonomously when repository evidence is sufficient;
- evidence should prove product capability rather than replace product capability;
- the existing safe promotion path to `main` remains intact;
- human approval remains mandatory for the existing high-risk boundaries.

## Relevant files

- `AGENTS.md` — durable maintainer behavior and repository rules.
- `.agent/HANDOFF.md` — current operational state only.
- `ZN.md` — product/architecture source used when choosing future work.
- `docs/ZN-IMPLEMENTATION-STATUS.md` — implementation reality and gaps.
- `docs/ZN-NEXT-PHASE.md` — roadmap input, not an unquestionable command queue.
- `docs/ZN-SELF-MAINTENANCE.md` — safety boundaries.

## Safety boundary

This maintenance change must not alter product runtime behavior, identity, long-term memory, credentials, updater/replacement, rollback, signing, release trust, stable channel or installed user versions.

Existing human-approval boundaries remain unchanged for destructive identity/long-term-memory migration, credential/permission expansion, updater/replacement/rollback/signing/release-trust actions, destructive data operations, and self-approval-rule weakening.

## Task Queue

| Priority | Status | Task | Dependency / completion condition |
| --- | --- | --- | --- |
| P1 | in_progress | Verify the maintainer-agency rule diff is narrow and preserves safety/promotion boundaries | Review `AGENTS.md` + HANDOFF diff |
| P1 | planned | Run/inspect appropriate CI for this docs/rules branch | Exact branch head must be green; do not claim success before GitHub reports it |
| P1 | planned | Merge this maintenance change back to `dev/zn-agent` through a traceable PR | CI green, diff clean, no safety regression |
| P1 | planned | Reconcile `dev/zn-agent` with canonical `main` through the normal promotion gate | Include the already-pending ledger reconciliation; verify post-merge canonical state |
| P1 | planned | Re-evaluate ZN's next product task from current code/status instead of automatically inheriting the old installed-N evidence plan | Read product/status/active code after maintenance promotion |

## Known product gaps for the next maintainer to evaluate

These are candidates to prioritize, not a fixed sequence:

- installed-N continuity/baseline and later N -> N+1 continuity;
- failed-update rollback;
- Windows login/reboot autostart proof on persistent installed state;
- signing/release-trust validation and formal publication readiness;
- remaining P5 restore/recovery capabilities recorded in implementation status;
- any higher-priority correctness, security, reliability or user-facing blocker found in the current active code.

Choose among them by impact, dependency, risk and closeness to a usable ZN product. Do not select a task merely because it is the next numbered evidence slice.

## Verification state

- Repository/branch/HANDOFF/AGENTS inspection: actually performed through GitHub.
- `main...dev/zn-agent` comparison at inspection: `dev/zn-agent` ahead by 3, behind by 0.
- Product tests were not rerun before this rule edit because no runtime/product code was changed.
- The exact maintenance-branch CI result is still pending and must be checked before merge/promotion.

## Next action

Review the exact two-file maintenance diff, then inspect CI for the resulting branch head. If green, merge normally into `dev/zn-agent`, re-check the cumulative `main...dev` state, and promote through the existing safe gate. After canonical reconciliation, select the next product task afresh from real ZN gaps.