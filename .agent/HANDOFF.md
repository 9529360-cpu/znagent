# ZN Maintainer Handoff

This is an engineering handoff/evidence ledger, not a chat summary. Repository state, code and real CI remain authoritative.

## Current goal

The Windows x64 clean install + first resident start proof stage is complete, promoted, and canonically verified. The next engineering target is the low-risk isolated/read-only **installed-N baseline evidence** slice, without invoking updater/replacement/rollback/signing.

## Branch and Git state at this handoff write

- Repository: `9529360-cpu/znagent`
- Development branch: `dev/zn-agent`
- Canonical branch: `main`
- Clean-install implementation/proof head: `cb913d61f001af6c729a141a3c8631a72e8362cf`
- Clean-install documentation closeout head: `4b770345e1267db1cfdc37c9551ff967d6955c27`
- Canonical clean-install promotion merge: `a4f9c95a32571add9bd16ec5aa08a618c8e5566b`
- Before this ledger-reconciliation change, `main` and `dev/zn-agent` were synchronized at `a4f9c95a32571add9bd16ec5aa08a618c8e5566b`.
- The current `dev/zn-agent` HEAD is the final commit produced by this three-file ledger reconciliation; resolve the branch ref after all three updates rather than writing a stale intermediate SHA here.
- PR #11: merged, promoting the unsigned Windows candidate-proof stage to `main`.
- PR #12: merged, adding clean Windows install/first-start proof to `dev/zn-agent`.
- PR #13: merged, promoting the clean-install/first-start proof to canonical `main`.
- No force push/history rewrite is authorized or required.

## Completed clean-install engineering stage

- Promoted the verified Windows unsigned candidate-proof stage to canonical `main` via PR #11.
- Added a separate clean hosted Windows x64 install/start workflow and verifier rather than expanding formal release automation.
- Added contract tests for installed layout, exact runtime identity, materialized-Python ownership and loopback endpoint evidence.
- Built the real unsigned NSIS/MSI candidate and verified its packaged runtime/manifest before installation.
- Ran the real NSIS installer silently into isolated GitHub-hosted Windows state.
- Started the installed `ZN.exe` and exercised the production path through packaged runtime materialization and resident IPC/autostart.
- Verified the real resident TCP endpoint with `ping`, `status`, `self`, exact runtime id, materialized portable Python, live pulse, graceful shutdown and endpoint retirement.
- Bounded NSIS wait to three minutes after the first proof showed install exit latency; assertions were not weakened.
- Merged the verified implementation through PR #12 into `dev/zn-agent`.
- Closed the implementation ledger at `4b770345e1267db1cfdc37c9551ff967d6955c27` and verified exact docs-head CI.
- Promoted the completed low-risk clean-install stage through PR #13 to canonical merge `a4f9c95a32571add9bd16ec5aa08a618c8e5566b`.
- Verified post-merge canonical CI on `a4f9c95a32571add9bd16ec5aa08a618c8e5566b`.
- Reconciled `docs/ZN-IMPLEMENTATION-STATUS.md`, `docs/ZN-NEXT-PHASE.md`, and this HANDOFF to the real post-merge state.

## Verified evidence

### Implementation/proof head

`cb913d61f001af6c729a141a3c8631a72e8362cf`

- `ZN CI` run `33193710879`: substantive jobs success.
  - `ZN Source Boundary / Windows`: success.
  - `Electron / TypeScript / Windows`: success.
  - `ZN Kernel / Python / Windows`: success; **686 tests**, `609.959s`, `OK (skipped=5)`.
- `ZN Windows Release Candidate` run `33193711016`: success.
  - Artifact `9695032455`.
  - Archive digest `sha256:a5e65ee7b02ef977260e30365ba460cbd30dcfef1d46550c58a31b8cc7739aa6`.
- `ZN Windows Clean Install` run `33193710872`: success.
  - Installed runtime id: `cb913d61f001af6c729a141a3c8631a72e8362cf`.
  - Resident Python came from the materialized isolated runtime.
  - Observed resident `pulse_count=1`.
  - Artifact `9695069801`.
  - Archive digest `sha256:c55e2c72c3a86b8661273520874b1aec395804188cc34f8231071e4ce2407f06`.

### Documentation closeout head

`4b770345e1267db1cfdc37c9551ff967d6955c27`

- `ZN CI` run `33195494937`: `completed / success`.

### Canonical post-merge head

`a4f9c95a32571add9bd16ec5aa08a618c8e5566b`

- PR #13 merged successfully at this commit.
- `ZN CI` run `33196441295`: `completed / success`.
- Substantive jobs:
  - `ZN Kernel / Python / Windows`: success.
  - `Electron / TypeScript / Windows`: success.
  - `ZN Source Boundary / Windows`: success.
- `Publish Windows CI statuses`: success.

The clean-install stage therefore has implementation-head CI/E2E evidence, documentation-head CI evidence, normal traceable promotion, and successful canonical post-merge CI evidence.

## Relevant files

Clean-install implementation:

- `.github/workflows/zn-windows-clean-install.yml`
- `apps/desktop/scripts/verify-zn-windows-clean-install.mjs`
- `apps/desktop/scripts/verify-zn-windows-clean-install.test.mjs`

Production call chain inspected for the clean-install proof and next baseline slice:

- `apps/desktop/electron/zn-main.ts`
- `apps/desktop/electron/zn-packaged-runtime.ts`
- `apps/desktop/electron/zn-resident-ipc.ts`
- `runtime/python/zn_agent/core/daemon.py`
- `runtime/python/zn_agent/core/resident.py`
- `runtime/python/zn_agent/core/life.py`
- `runtime/python/zn_agent/core/provider_settings.py`
- `runtime/python/zn_agent/core/recovery_bounded_work.py`

Current ledger files:

- `docs/ZN-IMPLEMENTATION-STATUS.md`
- `docs/ZN-NEXT-PHASE.md`
- `.agent/HANDOFF.md`

## Safety boundary / risks

The completed clean-install stage did **not**:

- invoke the production updater or replace a user's installed formal version;
- execute N -> N+1 transition or rollback;
- modify identity/long-term-memory migration rules;
- modify credentials/permissions or expose credential values;
- alter signing keys, signing policy, release trust roots, branch protection or required checks;
- create a tag/GitHub Release or advance `stable.json`.

Still unproven:

- real Windows login/reboot autostart on a persistent installed machine;
- installed N baseline continuity evidence;
- N -> N+1 continuity;
- failed-update rollback;
- signing/release-trust validation;
- formal publication/stable-channel transition.

Updater/replacement, rollback, signing/release trust, identity/long-term-memory destructive migration, credential/permission expansion, and replacement of the user's installed formal version remain human-approval boundaries.

## Next target: installed-N baseline evidence

The next low-risk slice should create a privacy-safe continuity baseline from an isolated installed N without changing that installation.

Prefer the existing read-only production chain:

`resident endpoint -> ResidentRpcServer -> ping/status/self/provider_settings/work_list`.

Baseline evidence should retain only what a later N+1 continuity comparison needs:

- exact runtime/install identity;
- stable Self reference/identity fields;
- bounded Work/thread ids/counts/references, not message bodies;
- runtime/home/config path identity;
- sanitized provider/model/base URL and credential presence/source metadata, never secret values;
- endpoint/life pulse evidence.

Important implementation warning: current `work_list` snapshots include message and artifact content. A baseline collector must explicitly sanitize/bound these fields before writing proof artifacts, and tests should reject leakage of message bodies, artifact contents, credential values, or unrelated resident memory.

## Task queue

1. Resolve the current `dev/zn-agent` HEAD after this ledger reconciliation.
2. Inspect exact-head CI for the reconciliation commit(s). Do not claim the new docs head as CI-verified until GitHub has actually run it.
3. If the docs-only reconciliation gate is green, normally promote it to `main` so canonical ledger state matches canonical code/CI state.
4. Verify canonical post-merge CI for that docs reconciliation and re-check `main...dev` refs.
5. Begin the installed-N baseline slice by tracing the exact read-only evidence path and defining a sanitized baseline schema/verifier.
6. Add tests proving no updater/replacement/rollback/signing path is invoked and no secret/private body content leaks into the baseline artifact.
7. Add isolated Windows installed-N baseline E2E evidence, then run full CI and follow the ordinary promotion gate if green.

## Blockers

No implementation blocker is known for beginning the installed-N baseline evidence slice.

The only pending fact at this handoff write is remote verification/promotion of the current docs-only ledger reconciliation itself. It must not be described as CI-verified until its exact GitHub head has completed CI.
