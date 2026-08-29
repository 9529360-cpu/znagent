# ZN Implementation Status

This is ZN's current implementation/evidence ledger, not a roadmap or changelog. Real code, Git state and actual test/build/CI results override this file when they disagree.

## Repository state

- Repository: `9529360-cpu/znagent`
- Primary development branch: `dev/zn-agent`
- Canonical/release branch: `main`
- Current product-code dev head: `d74b44aded2f04db39fc48acb10feba195cd4731` (PR #78 merge).
- Canonical `main` before the next promotion: `587fd3186107135d08c9a224d98fa9389cda9bca` (PR #77 promotion).
- Previous canonical ZN CI run `33272468328` is fully green on `587fd318...`.
- SM3 targeted Windows validation run `33273272755` succeeded.
- Full dev ZN CI run `33273363874` is fully green on `d74b44ad...`: ZN Kernel/Python, Electron/TypeScript and ZN Source Boundary all succeeded and readable commit statuses were published.
- Hosted Windows clean-install/release-candidate jobs may still terminate before executable steps are allocated in the current runner environment. Pre-step termination is infrastructure unavailability, not product pass/fail evidence.
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
| Multi-organ health observation | materially connected + verified | channel/lifecycle, foreground Sense, visual capture, provider invocation/construction and Native Body dispatch are covered; unified health remains partial |
| Maintenance investigation lifecycle | connected + verified | baseline/oracle/attempt/acceptance is bounded evidence/control state; health/task truth remains authoritative |
| Trusted maintenance source binding | connected + verified, read-only | exact ZN root/origin/ownership required; ordinary Work is not authority |
| Maintenance source-state observation | connected + verified | fixed Git argv observes HEAD/branch/dirty/bounded changed paths without shell/write authority |
| Regression-oracle binding | connected + verified | oracle is restricted to existing `tests/zn_agent/core/...`; SM3 now executes it only inside the isolated attempt |
| Resident source-evidence projection | connected + verified | privacy-safe repository/head/fingerprint/oracle evidence; no absolute source path or changed-path list persisted |
| Isolated maintenance repair operator | connected + full-CI verified, bounded source-write | only open `probable_zn_defect` investigations with trusted clean baseline may enter a fresh dedicated `work/*` worktree |
| Stale/dirty repair protection | connected + verified, fail-closed | root/origin/fingerprint/HEAD/dirty/oracle contract are rechecked before first source write |
| Bounded repair mutation | connected + verified | only declared existing `.py` files under ZN core runtime/tests; no generic terminal/NativeBody write path |
| Repair oracle + diff evidence | connected + verified | fixed unittest oracle + `git diff --check`; undeclared changed paths rejected; persisted evidence stores hashes/results rather than patch text |
| Investigation attempt recording | connected + verified | `record_attempt()` occurs only after worktree/diff/oracle evidence; attempt remains `unreviewed` |
| Autonomous repair diagnosis/candidate authoring | not connected | formal resident entry accepts caller-provided replacement content; no resident controller yet derives a patch from incident/source evidence |
| Semantic repair review/acceptance | not connected as product path | ledger supports acceptance state, but no real reviewer/controller evaluates repair semantics and accepts/rejects the live attempt |
| Repair branch publication / PR / CI feedback | not connected as resident product path | no commit, push, PR creation, CI ingestion or iterative repair continuation from the resident maintenance path |
| Installed N -> N+1 update continuity | approval-gated / incomplete | no formal updater/replacement transition executed |
| Rollback / signing / release trust | approval-gated / incomplete | high-risk release/update authority remains outside autonomous source development |

## Current self-maintenance path

The verified bounded path is now:

```text
real organ failure/success
-> durable privacy-safe health
-> conservative failure classification
-> repeated high-confidence maintenance task
-> evidence-only investigation lifecycle
-> explicit trusted ZN source root
-> read-only HEAD/branch/dirty/oracle evidence
-> exact clean observed baseline
-> formal resident isolated-repair entry
-> revalidate ZN root/origin/fingerprint/HEAD/dirty/oracle
-> create fresh dedicated work/* worktree
-> replace only declared existing ZN core Python/test files
-> fixed unittest regression oracle
-> git diff --check + bounded declared changed paths
-> privacy-safe repair evidence
-> MaintenanceInvestigationLedger.record_attempt()
-> unreviewed repair candidate
```

PR #78 deliberately stops at an **isolated repair candidate**. It does not provide autonomous patch authorship, semantic acceptance, commit/push/merge, PR/CI automation, release, updater/replacement or installed-body mutation.

Important invariants:

- ordinary Work workspace is not maintenance-source authority;
- source root remains unchanged by a repair attempt; source writes occur only in the dedicated isolated worktree;
- only an open `probable_zn_defect` task already in source investigation may create an attempt;
- the source root must still be the exact ZN repo with origin `9529360-cpu/znagent`;
- a source observed dirty cannot enter repair, and a source that becomes dirty or changes HEAD after observation fails before worktree creation/write;
- attempt branch must be a fresh safe `work/*` ref and attempt path must live under the dedicated sibling `.zn-maintenance-worktrees` directory;
- replacement targets are bounded existing regular `.py` files under `runtime/python/zn_agent/core` or `tests/zn_agent/core`;
- no generic shell/terminal command, NativeBody write, commit, push, merge, release or updater authority is used;
- durable repair status does not store local absolute source/attempt paths, replacement contents or raw diff text;
- passing regression is evidence, not semantic approval; the attempt remains unreviewed until a separate acceptance path evaluates it.

## Exact current evidence

- `33272468328` — previous canonical main ZN CI success on `587fd318...` after PR #77.
- `33273206772` — first SM3 targeted run: production success paths/stale/dirty guards passed; one test used a non-`.py` escape input and therefore hit an earlier valid guard than the assertion expected. Production constraints were not weakened.
- `33273272755` — corrected targeted Windows validation success: affected-module compilation and 21 SM3/source/investigation/resident regressions all passed.
- `33273363874` — full dev ZN CI success on PR #78 merge head `d74b44ad...`: Kernel/Python full core suite, Electron/TypeScript and Source Boundary all passed; all three readable commit statuses are success.

The targeted SM3 tests prove a real isolated worktree repair can make the fixed oracle pass while the source working tree remains unchanged, plus fail-closed rejection of stale HEAD, post-observation dirty source and out-of-bound replacement targets. Whole-tree CI proves the resident boot/core/Desktop/source-boundary surface remains compatible with this slice.

## Current product gaps

1. **Repair content is caller-provided, not resident-derived.** ZN can safely execute and verify a bounded candidate but cannot yet turn incident/source evidence into a patch proposal by itself.
2. **No semantic review/acceptance controller.** Passing the regression and diff checks is necessary evidence, not proof the repair is correct; the real product path must review the candidate and explicitly accept/reject it.
3. **No branch publication / PR / CI continuation.** The worktree branch is local only; no commit/push/PR, CI result ingestion or failure-driven iteration is connected to resident self-maintenance.
4. **Worktree lifecycle is not yet product-closed.** Repair attempts are retained for inspection; cleanup/retention/recovery rules need a bounded owner before long-running autonomous use.
5. **Unified health remains partial.** Add persistence/life-loop/config-plan boundaries only where active-call evidence closes a meaningful reliability gap.
6. **Installed N -> N+1 continuity remains approval-gated.** Source repair maturity does not grant updater/replacement, rollback, signing or release-trust authority.

## Next evidence-driven direction

Do not jump directly from a passing isolated oracle to autonomous merge/update. The next highest-value vertical slice is to connect one real high-confidence maintenance incident to **candidate derivation + semantic review** under the existing isolated operator:

```text
maintenance incident + trusted source evidence
-> bounded diagnosis/candidate proposal
-> existing isolated repair operator
-> oracle + diff evidence
-> semantic review against incident/changed paths/evidence
-> explicit accepted/rejected attempt
```

Only after that is verified should resident-owned branch publication / commit / push / PR / CI feedback become the next layer. Formal updater/replacement, rollback, release signing/trust and replacement of the user's installed version remain separate explicit approval boundaries.
