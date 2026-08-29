# ZN Maintainer Handoff

This is the current engineering work site and fact index, not a chat transcript or execution script. Real code, Git state and actual test/build/CI results override this file when they disagree.

## Current objective

Advance resident self-maintenance from the now-verified trusted read-only source investigation into the smallest safe isolated `work/*` repair attempt. Do not couple this to updater/replacement, rollback, signing or release trust.

Current evidence/control path:

`real organ failure/success -> durable health -> conservative classification -> bounded maintenance task -> evidence-only investigation lifecycle -> explicit trusted ZN source root -> fixed read-only Git observation -> baseline commit + regression-oracle evidence -> resident status`

This is not yet a repair loop. No maintenance task can autonomously create/mutate an isolated checkout, run a patch, merge code or replace the installed body.

## Repository state

- Repository: `9529360-cpu/znagent`
- Canonical/release branch: `main`
- Primary development branch: `dev/zn-agent`
- `main`: `221da814bbab14492e82cf5d4c5e01a65250c4d6` from PR #74 promotion.
- Product-code `dev/zn-agent`: `4cd5469edb34cb60622964e5ffa34c3804375252` from PR #75.
- PR #75: `Connect maintenance tasks to read-only ZN source investigation`.
- Targeted Windows self-hosted validation run `33271612132`: **success**.
- Full dev ZN CI run `33271661045` on `4cd5469e...`: **fully green** — ZN Kernel/Python, Electron/TypeScript and ZN Source Boundary all succeeded.
- Canonical main CI for PR #74 is run `33271494803`; keep canonical and dev evidence distinct.
- Hosted Windows clean-install/release-candidate jobs may still terminate before executable steps are allocated; `steps=null`/pre-step termination is infrastructure unavailability, not product pass/fail evidence.

## Product reality

### Continuity / resident lifecycle

Previously verified continuity remains protected: installed resident desktop independence/autostart, durable Self/Work/thread/memory/learning continuity, bounded atomic-overwrite recovery and zero-model resident boot. Protect identity, lived memory, Will/intention, runtime/home/config/provider references and restart/install continuity while extending self-maintenance.

### Health / task / investigation

Connected health slices include channel/lifecycle, foreground-window Sense, visual capture, provider invocation/resource construction and Native Body dispatch. Health truth is authoritative over derived maintenance-task and investigation projections.

`MaintenanceInvestigationLedger` remains `authority = evidence_only`. Baseline/oracle/attempt/acceptance state never grants file write, branch, merge, release or updater authority.

### Trusted maintenance source investigation

PR #75 adds the first resident-owned source-reading path:

- explicit `source_root`; ordinary Work workspace is not consumed as authority;
- source must resolve exactly to the Git top-level root;
- ZN ownership markers are required: `ZN.md`, `AGENTS.md`, `runtime/python/zn_agent/core`, `tests/zn_agent/core`;
- `origin` must identify `9529360-cpu/znagent`;
- observation uses fixed `git -C <root> ...` argv only, never shell/general terminal execution;
- evidence observes HEAD, branch, dirty state and a bounded changed-path set;
- regression oracle is restricted to an existing `test:tests/zn_agent/core/...` path;
- durable source evidence persists privacy-safe repository/fingerprint/head/branch/dirty/count/oracle data, not the local absolute source path or changed-path list;
- formal `HealthAwareResidentRuntime.investigate_maintenance_source()` binds an open maintenance task to this observation and begins the evidence-only investigation at `commit:<HEAD>`;
- resident `status()` exposes the bounded persisted source-evidence projection read-only.

Targeted run `33271612132` proves exact-root/origin admission, dirty-state evidence, foreign repo/subdirectory/non-test-oracle rejection, closed-task rejection, fixed Git subprocess shape, formal resident integration and status privacy. Full dev run `33271661045` proves the change survives the whole current ZN Kernel/Desktop/Source-Boundary suite.

Capability maturity: **trusted read-only source investigation = connected + verified; not product-closed**. The discontinuity is now explicit source evidence -> autonomous high-confidence isolated repair attempt.

## Safety invariants

- ordinary Work context is not maintenance-source authority;
- task/investigation/source-evidence presence never implies mutation authority;
- source investigation does not use NativeBody writes, generic terminal commands or shell execution;
- raw exception messages, provider/model raw route text and arbitrary Body action strings remain privacy-bounded as already implemented;
- network/service/environment/config/input failures do not automatically become source-maintenance candidates;
- ambiguous failures remain fail-closed;
- updater/replacement/rollback/signing/release trust, destructive identity/long-term-memory migration and replacement of a user's installed version remain explicit human-approval boundaries.

## Exact current evidence

- `33270265444` — full dev ZN CI success on `cd2d21f...` before this source stage.
- `33271612132` — targeted maintenance-source validation success.
- `33271661045` — full dev ZN CI success on PR #75 merge head `4cd5469e...` across Kernel/Python, Electron/TypeScript and Source Boundary.

## Current risks / real gaps

1. **No isolated repair execution.** Trusted source can be read, but no resident maintenance controller creates a fresh clean `work/*` attempt, performs a bounded source write, runs a fixed oracle and records reviewed diff evidence.
2. **Source investigation is an explicit resident entry point, not an autonomous scheduler.** SM2 read-only slice is verified; the wider self-maintenance product loop is not closed.
3. **Stale-source protection must precede mutation.** Future repair must reject baseline drift, unexpected dirty state, wrong repo/branch/worktree ownership and oracle-contract changes before any write.
4. **Unified health remains partial.** Add other persistence/life-loop/config-plan boundaries only at real active failure/success sites where they close a meaningful reliability gap.
5. **Installed N -> N+1 continuity remains approval-gated and unproven for a formal replacement transition.** Source-development maturity does not grant updater authority.

## Next dependency-ready work

1. Design the smallest dedicated isolated-source operator: exact observed baseline, fresh clean worktree/`work/*` branch, narrow repository-only mutation scope, no running-install writes, no `main` writes and no generic terminal authority.
2. Require fixed regression-oracle execution, bounded diff evidence and stale-baseline/dirty-state checks before the real resident maintenance path may call `MaintenanceInvestigationLedger.record_attempt()`.
3. Targeted-verify that isolated attempt path, then run whole-tree CI.
4. Only after that should resident-owned PR/CI automation become the next product layer.

No updater/replacement/rollback/signing action is authorized by this handoff.