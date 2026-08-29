# ZN Maintainer Handoff

This is the current engineering work site and fact index, not a chat transcript or execution script. Real code, Git state and actual test/build/CI results override this file when they disagree.

## Current objective

Continue from broad resident self-health evidence into one real maintenance-task-driven, read-only source investigation without granting source mutation or updater/replacement authority prematurely.

The current evidence/control path is:

`real organ failure/success -> durable health -> conservative classification -> bounded maintenance task -> reconciled evidence-only investigation lifecycle -> read-only resident/RPC status`

Connected health boundaries now include channel/lifecycle, foreground-window Sense, visual capture, cognitive provider invocation/resource construction, and Native Body dispatch.

## Repository state

- Repository: `9529360-cpu/znagent`
- Canonical/release branch: `main`
- Primary development branch: `dev/zn-agent`
- Current product-code dev head before this docs reconciliation: `7827b155e18c561dca2f42e26d1817d653a5d03c` (PR #72 merge).
- Canonical `main` currently: `d7d06c665daed3400b86d792dd0eeabf16611cbb` (PR #66 merge).
- `main` ZN CI run `33262436187` is fully green on `d7d06c66...`.
- Combined dev ZN CI run `33269095288` is fully green on `7827b155...`, covering PRs #67-#72 across Source Boundary, Electron/TypeScript and Kernel/Python.
- Recent Windows clean-install/release-candidate push workflows still terminate before executable steps are allocated in this runner environment; treat that as infrastructure unavailability, not product evidence.

## Product reality

### Continuity / resident lifecycle

Previously verified continuity still matters and must not regress:

- installed Windows resident desktop-independence/autostart through the real `ZN Resident` Scheduled Task;
- durable resident state, Work/thread references, long-term memory and verified learning across restart/installed continuity proof;
- bounded atomic-overwrite recovery continuity;
- zero-model resident boot.

Protect Self/identity, lived memory, Work/thread references, Will/intention, learning state, runtime/home/config/provider references and resident restart/install continuity while extending self-maintenance.

### Resident health and maintenance evidence

Current connected/verified slices:

- channel failure/recovery and channel startup/shutdown lifecycle health;
- privacy-safe conservative health classification and repeated-fingerprint maintenance candidacy;
- bounded per-organ maintenance-task formation, dedup/reopen/closure and projection reconciliation;
- foreground-window Sense probe health at the real probe boundary;
- visual capture health at the real capture callable, without polling stale `last_error`;
- provider invocation failure/recovery health at the real `resource.invoke` boundary;
- provider resource-construction failure health before `ZNKernelRuntime` flattens factory failure;
- Native Body dispatch exception/recovery health on the already-composed final Body object;
- formal resident/RPC status for health, maintenance tasks and investigation projection.

Maintenance investigation lifecycle is implemented and verified as evidence/control state:

- reconciles from authoritative maintenance-task truth;
- requires explicit baseline reference and regression oracle;
- attempts require isolated `work/*` branch reference and evidence reference;
- accepted evidence requires a passing regression attempt;
- incident/contract changes reset stale attempts/acceptance;
- rejection cannot silently reuse old evidence;
- secondary projection damage cannot block health/task truth and can be rebuilt;
- authority remains `evidence_only`.

This does **not** yet form a source-maintenance product loop. There is no active caller that binds an open maintenance task to a trustworthy ZN source workspace and performs bounded read-only repository/test/CI investigation.

### Health semantics that must remain invariant

- raw exception messages are not persisted in health/task tables;
- provider route identity is privacy-safe; model text/raw route IDs do not enter resident health;
- arbitrary Body action-kind strings are hashed before health status;
- network/service/environment/config/input failures do not automatically become source-maintenance candidates;
- ambiguous exceptions fail closed rather than being assumed to be ZN defects;
- health observation is secondary and must never replace the original Sense/provider/Body result;
- provider construction success is not provider recovery; only a real successful invocation closes that route's invocation failure streak.

## Exact current evidence

- `33262436187` — canonical main ZN CI success on `d7d06c66...`.
- `33266191698` — full dev ZN CI success after foreground-window + visual-capture health integration.
- `33267074693` — maintenance investigation lifecycle targeted validation success.
- `33267155067` — full dev ZN CI success after maintenance investigation lifecycle merge.
- `33268424791` — cognitive provider invocation health targeted validation success.
- `33268678763` — Native Body dispatch health targeted validation success.
- `33269016466` — cognitive provider resource-construction health targeted validation success.
- `33269095288` — combined dev ZN CI success on `7827b155...` after PRs #67-#72.

PR #70's full run `33268511210` was cancelled/superseded and is not passing evidence.

## Current risks / real gaps

- The largest immediate self-maintenance gap is not another ledger: an open maintenance task still cannot bind to a trusted source workspace and gather source-state evidence under explicit read-only authority.
- Existing `Work` workspace association is user-work context; it must not be silently reused as maintenance-source authority.
- Existing Body `git_state`/`git_diff` are useful read-only primitives, but general terminal/file-write capabilities must not leak into a maintenance read-only investigator.
- Unified health is still partial; persistence/life-loop/config-plan and other real boundaries should be added only where active-call evidence shows a meaningful reliability gap.
- Actual N -> N+1 updater/replacement, failed-update recovery, rollback, release signing/trust, destructive identity/memory migration and replacement of a user's formal installation remain explicit human-approval boundaries.

## Next dependency-ready work

1. Merge this factual docs reconciliation, then normally promote the coherent verified dev stage to canonical `main` and verify canonical ZN CI.
2. Trace and implement a trustworthy maintenance-source workspace binding. It must prove repository root and ZN ownership, be separate from ordinary Work context, preserve a baseline commit, and default to read-only authority.
3. Connect one real open maintenance task through that binding to bounded repository state/diff/regression-oracle evidence. Do not grant mutation merely because investigation state exists.
4. Only after the read-only source-investigation path is connected + verified should high-confidence maintenance tasks be allowed to initiate isolated `work/*` source attempts.

No updater/replacement/rollback/signing action is authorized by this handoff.
