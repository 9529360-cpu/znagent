# ZN Maintainer Handoff

This is the current engineering work site and fact index, not a chat transcript or execution script. Real code, Git state and actual test/build/CI results override this file when they disagree.

## Current objective

Continue the resident self-maintenance path from verified read-only source investigation toward a high-confidence isolated `work/*` repair attempt, while keeping source mutation, updater/replacement, rollback, signing and release trust behind their existing authority boundaries.

The current evidence/control path is now:

`real organ failure/success -> durable health -> conservative classification -> bounded maintenance task -> evidence-only investigation lifecycle -> explicit trusted ZN source root -> fixed read-only Git observation -> baseline commit + regression-oracle evidence -> resident status`

This path is not yet a repair loop. No maintenance task can autonomously create or mutate an isolated source attempt, run a patch, accept a diff, merge code or replace the installed body.

## Repository state

- Repository: `9529360-cpu/znagent`
- Canonical/release branch: `main`
- Primary development branch: `dev/zn-agent`
- `main` was promoted through PR #74 to `221da814bbab14492e82cf5d4c5e01a65250c4d6`.
- Read-only maintenance source investigation was merged through PR #75; current product-code `dev/zn-agent` head is `4cd5469edb34cb60622964e5ffa34c3804375252`.
- Targeted Windows self-hosted validation run `33271612132` succeeded for the new source investigator, formal resident connection, existing investigation lifecycle and maintenance-status regressions.
- Full dev ZN CI run `33271661045` is the current whole-tree gate for `4cd5469e...`. At this handoff update, Electron/TypeScript and ZN Source Boundary jobs are success; ZN Kernel/Python is still running the full core test suite. Do not call this run fully green until that job completes successfully.
- Canonical main ZN CI run `33271494803` was also still running its full Kernel core suite at the same observation point; its Electron/TypeScript and Source Boundary jobs were success.
- Hosted clean-install/release-candidate workflows can still terminate before executable steps are allocated in this runner environment; `steps=null`/pre-step termination is infrastructure unavailability, not product pass/fail evidence.

## Product reality

### Continuity / resident lifecycle

Previously verified continuity remains a protected invariant:

- installed Windows resident desktop-independence/autostart through the real `ZN Resident` Scheduled Task;
- durable resident state, Work/thread references, long-term memory and verified learning across restart/installed continuity proof;
- bounded atomic-overwrite recovery continuity;
- zero-model resident boot.

Protect Self/identity, lived memory, Work/thread references, Will/intention, learning state, runtime/home/config/provider references and resident restart/install continuity while extending self-maintenance.

### Resident health and maintenance evidence

Connected/verified health slices include channel/lifecycle, foreground-window Sense, visual capture, provider invocation/resource construction and Native Body dispatch. Health truth remains authoritative over maintenance-task and investigation projections.

The maintenance investigation ledger remains `authority = evidence_only`: baseline/oracle/attempt/acceptance state is bounded and reconstructible, but the ledger itself grants no file write, branch, merge, release or updater authority.

### Maintenance source investigation

PR #75 adds the first resident-owned trusted source-reading path:

- `MaintenanceSourceInvestigator` accepts an explicit source root; it does not consume ordinary Work workspace association;
- the source path must resolve exactly to the Git repository root;
- ZN ownership markers must exist (`ZN.md`, `AGENTS.md`, `runtime/python/zn_agent/core`, `tests/zn_agent/core`);
- `origin` must identify `9529360-cpu/znagent`;
- observation uses fixed `git -C <root> ...` argv only, never shell/terminal execution;
- observed evidence includes HEAD, branch, dirty state and a bounded changed-path set;
- a regression oracle must be `test:tests/zn_agent/core/...` and the file must exist;
- durable resident evidence stores repository identity, fingerprints, HEAD/branch/dirty/count/oracle and `authority=read_only`, but not the local absolute source path or changed-path list;
- the formal `HealthAwareResidentRuntime.investigate_maintenance_source()` entry point binds this evidence to an open maintenance task and begins the existing evidence-only investigation at the observed commit baseline;
- resident `status()` exposes the persisted bounded source-evidence projection read-only.

Targeted validation run `33271612132` proves exact-root/origin admission, foreign-repository/subdirectory/oracle rejection, closed-task rejection, bounded dirty-state evidence, privacy-safe persistence, fixed Git invocation shape and formal resident/status integration.

Capability maturity: **source investigation exists + is connected to the formal resident + is targeted-verified; it is not product-closed**. The remaining discontinuity is between this explicit resident source-reading entry point and an autonomous high-confidence maintenance controller/isolated repair attempt.

## Safety invariants

- ordinary Work context is not maintenance-source authority;
- task/investigation/source-evidence presence never implies mutation authority;
- raw exception messages are not persisted in health/task tables;
- provider/model/raw route text and arbitrary Body action strings remain privacy-bounded as already implemented;
- network/service/environment/config/input failures do not automatically become source-maintenance candidates;
- ambiguous exceptions fail closed rather than being assumed to be ZN defects;
- health observation remains secondary to the actual Sense/provider/Body behavior;
- source investigation never uses NativeBody write actions, general terminal commands or shell execution;
- updater/replacement/rollback/signing/release trust, destructive identity or long-term-memory migration and replacement of a user's installed version remain explicit human-approval boundaries.

## Exact current evidence

- `33269095288` — earlier combined dev ZN CI success on `7827b155...` after PRs #67-#72.
- `33270265444` — full dev ZN CI success on `cd2d21f...` after the prior documentation reconciliation.
- `33271612132` — targeted Windows self-hosted maintenance-source validation success.
- `33271661045` — full dev ZN CI for PR #75 merge head `4cd5469e...`; Electron/TypeScript and Source Boundary success, Kernel/Python still running at this snapshot.
- `33271494803` — canonical main ZN CI for PR #74 merge head `221da814...`; Electron/TypeScript and Source Boundary success, Kernel/Python still running at this snapshot.

## Current risks / real gaps

1. **No isolated repair execution yet.** A trusted source workspace can now be read and bound to a task, but no resident maintenance controller can create a safe `work/*` attempt, modify only that isolated checkout, run a fixed oracle and record reviewed diff evidence.
2. **The source-read entry point is explicit rather than autonomous.** Formal resident ownership is established, but no lifecycle scheduler automatically chooses an eligible high-confidence task/source binding. Do not describe SM2 as product-closed.
3. **Stale-source protection becomes critical before mutation.** A future repair operator must reject baseline drift, unknown dirty state, unexpected branch/worktree ownership and changed oracle contracts before any source write.
4. **Unified health is still partial.** Persistence/life-loop/config-plan and other real failure boundaries should only be added where active-call evidence shows a meaningful reliability gap.
5. **Installed N -> N+1 continuity remains approval-gated and unproven for a real replacement transition.** Do not couple source-maintenance progress to updater authority.

## Next dependency-ready work

1. Finish reading full dev CI `33271661045`; if Kernel/Python fails, repair that regression before widening authority.
2. Once the read-only slice remains green, design the smallest dedicated isolated-source operator: exact trusted baseline, fresh clean worktree/`work/*` branch, narrow repository-only mutation scope, no current-install writes and no generic terminal authority.
3. Require a fixed regression oracle and bounded diff evidence before `MaintenanceInvestigationLedger.record_attempt()` can be called by the real resident maintenance path; reject stale baseline/dirty-state changes fail-closed.
4. Only after the isolated attempt path is connected and verified should PR/CI automation be considered the next product layer.

No updater/replacement/rollback/signing action is authorized by this handoff.