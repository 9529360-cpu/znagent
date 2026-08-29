# ZN Maintainer Handoff

This is the current engineering work site and fact index, not a chat transcript or execution script. Real code, Git state and actual test/build/CI results override this file when they disagree.

## Current objective

Continue from the verified bounded SM3 isolated-repair candidate into the next missing product layer: derive a candidate from a real high-confidence maintenance incident, then semantically review/accept or reject it. Do not jump directly from a passing oracle to automatic push/merge/update.

Current verified path:

`real organ failure -> durable health -> probable_zn_defect task -> investigation -> trusted ZN source evidence -> exact clean baseline -> fresh dedicated work/* worktree -> bounded declared core Python/test replacements -> fixed unittest oracle + diff check -> privacy-safe attempt evidence -> record_attempt() -> unreviewed repair candidate`

## Repository state

- Repository: `9529360-cpu/znagent`
- Canonical/release branch: `main`
- Primary development branch: `dev/zn-agent`
- Canonical `main` before next promotion: `587fd3186107135d08c9a224d98fa9389cda9bca` (PR #77).
- Product-code `dev/zn-agent`: `d74b44aded2f04db39fc48acb10feba195cd4731` (PR #78).
- PR #78: `Connect resident self-maintenance to isolated repair attempts`.
- Targeted SM3 validation `33273272755`: **success**.
- Full dev ZN CI `33273363874`: **fully green** — Kernel/Python full core suite, Electron/TypeScript, Source Boundary and readable status publication all succeeded.
- Previous canonical main ZN CI `33272468328` on `587fd318...`: **fully green**.
- Hosted clean-install/release-candidate pre-step failures remain runner/infrastructure evidence only, not product pass/fail evidence.

## Product reality

### Protected continuity

Keep existing verified Self/identity, lived memory, Work/thread references, learning, resident lifecycle/autostart, zero-model boot and restart continuity intact. Source-maintenance maturity never grants updater/replacement authority.

### SM2 read-only source investigation

Formal resident can bind an open maintenance task to an explicit exact ZN repository root, verify ownership/origin, observe HEAD/branch/dirty/bounded changed paths with fixed Git argv, bind an existing `tests/zn_agent/core/...` oracle and persist privacy-safe source evidence. Ordinary Work context, terminal and file-write capability are not used as source authority.

### SM3 isolated repair candidate

`MaintenanceIsolatedRepairOperator` is now connected through `HealthAwareResidentRuntime.run_maintenance_repair_attempt()`.

Before any write it requires and re-verifies:

- open `probable_zn_defect` task in `investigating` state;
- evidence-only investigation + trusted read-only source evidence;
- exact ZN repo root/origin/root fingerprint;
- live HEAD equal to the observed baseline;
- source still clean;
- unchanged regression-oracle contract;
- fresh safe `work/*` branch;
- fresh attempt path under sibling `.zn-maintenance-worktrees`.

Mutation is limited to caller-declared existing regular `.py` files under `runtime/python/zn_agent/core` or `tests/zn_agent/core`. The source working tree remains unchanged. The operator rejects undeclared changed paths, runs `git diff --check`, executes the fixed unittest oracle in the isolated worktree, persists only bounded hashes/results and then records the attempt. Passing evidence leaves the attempt `unreviewed`.

The path does **not** commit, push, merge, create PRs, release, update the installed body, use generic shell/terminal, use NativeBody writes or treat ordinary Work as source authority.

## Exact evidence

- `33272468328` — previous canonical main ZN CI success on `587fd318...`.
- `33273206772` — first targeted SM3 run; production success/stale/dirty paths passed, one test expected a later guard while its input hit an earlier valid `.py` guard. Production constraints were not weakened.
- `33273272755` — corrected targeted validation success, including 21 SM3/source/investigation/resident regressions.
- `33273363874` — full dev ZN CI success on `d74b44ad...` across Kernel/Python, Electron/TypeScript and Source Boundary; all three commit statuses are success.

## Current gaps / risks

1. **Candidate derivation is missing.** The formal resident repair entry currently receives caller-provided replacement content; ZN does not yet derive a bounded patch proposal from the maintenance incident/source evidence.
2. **Semantic acceptance is missing.** Passing the oracle/diff checks is evidence only. No product caller reviews incident intent, changed paths and resulting behavior before accepting/rejecting the attempt.
3. **Attempt lifecycle is incomplete.** Isolated worktrees are retained for inspection; bounded retention/restart recovery/stale-attempt cleanup still needs an owner.
4. **SM4 publication loop is missing.** No resident commit/push/PR/CI ingestion or failed-CI continuation exists yet.
5. **Unified health remains partial.** Only add new health boundaries at real active failure/success sites where product reliability benefits.
6. **Updater/replacement/rollback/signing/release trust remain explicit human-approval boundaries.**

## Next dependency-ready work

1. Trace the resident cognition/source-analysis primitives that could derive a narrowly scoped repair proposal without handing the model arbitrary filesystem/terminal authority.
2. Define a bounded typed candidate contract (task/baseline/oracle/declared paths/replacement bytes or equivalent) that the existing isolated operator can validate independently of model claims.
3. Connect one real high-confidence incident through candidate derivation -> isolated execution -> oracle/diff -> semantic review -> explicit ledger accept/reject.
4. Verify that path with adversarial stale/path/scope/model-output regressions and whole-tree CI.
5. Only after semantic acceptance is real should resident-owned commit/push/PR/CI feedback become the next layer.

No updater/replacement/rollback/signing action is authorized by this handoff.
