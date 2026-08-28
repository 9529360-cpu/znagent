# ZN Maintainer Handoff

This is an engineering handoff/evidence ledger, not a chat summary. Repository state, code and real CI remain authoritative.

## Current goal

Close and normally promote the low-risk Windows x64 **clean install + first resident start proof** stage, then begin the next isolated/read-only installed-N baseline evidence slice without invoking updater/replacement.

## Branch and Git state at this handoff write

- Repository: `9529360-cpu/znagent`
- Development branch: `dev/zn-agent`
- Canonical branch: `main`
- Canonical `main` before clean-install promotion: `3741db32c739322a3f921ea62798b2c698ef0771`
- Verified clean-install implementation/proof parent head: `cb913d61f001af6c729a141a3c8631a72e8362cf`
- This documentation closeout commit becomes the current `dev/zn-agent` HEAD; resolve the branch ref after the commit rather than inventing a self-referential SHA here.
- PR #11: merged `dev/zn-agent -> main`, promoting the unsigned candidate-proof stage.
- PR #12: merged `work/windows-clean-install-proof -> dev/zn-agent`, adding the clean-install proof.
- No force push/history rewrite is authorized or required.

## Completed in the current engineering stage

- Promoted the already verified Windows unsigned candidate-proof stage to canonical `main` via PR #11.
- Verified post-merge canonical `main` with `ZN CI` run `33192086069` (success).
- Added a separate clean hosted Windows x64 install/start workflow and verifier rather than expanding formal release automation.
- Added contract tests for installed layout, exact runtime identity, materialized-Python ownership and loopback endpoint evidence.
- Built the real unsigned NSIS/MSI candidate and verified its packaged runtime/manifest before installation.
- Ran the real NSIS installer silently into isolated GitHub-hosted Windows state.
- Started the installed `ZN.exe` and exercised the production path through packaged runtime materialization and resident IPC/autostart.
- Verified the real resident TCP endpoint with `ping`, `status`, `self`, exact runtime id, materialized portable Python, live pulse, graceful shutdown and endpoint retirement.
- Bounded NSIS wait to three minutes after the first proof showed install exit latency; assertions were not weakened.
- Merged the verified implementation through PR #12 into `dev/zn-agent`.
- Re-read `ZN.md`, `AGENTS.md`, implementation/source/self-maintenance docs, this handoff, branch heads, diff/PR/CI and the real installed desktop -> packaged runtime -> resident call chain before closeout.

## Exact implementation-head verification

Implementation/proof head: `cb913d61f001af6c729a141a3c8631a72e8362cf`.

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

The implementation head therefore has real full-CI + candidate-build + clean-install evidence. The documentation closeout head must still receive its own required CI before promotion.

## Relevant files

Current stage implementation:

- `.github/workflows/zn-windows-clean-install.yml`
- `apps/desktop/scripts/verify-zn-windows-clean-install.mjs`
- `apps/desktop/scripts/verify-zn-windows-clean-install.test.mjs`

Production call chain inspected during closeout:

- `apps/desktop/electron/zn-main.ts`
- `apps/desktop/electron/zn-packaged-runtime.ts`
- `apps/desktop/electron/zn-resident-ipc.ts`
- `runtime/python/zn_agent/core/resident_server.py`
- `runtime/python/zn_agent/core/daemon.py`

Ledger/status files updated by this closeout:

- `docs/ZN-IMPLEMENTATION-STATUS.md`
- `docs/ZN-NEXT-PHASE.md`
- `.agent/HANDOFF.md`

## Safety boundary / risks

This stage did **not**:

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

Those high-risk transition/trust operations remain human-approval boundaries.

## Task queue

1. Resolve this documentation closeout commit as the current `dev/zn-agent` HEAD.
2. Run/inspect exact-docs-head `ZN CI`; do not reuse implementation-head CI as if docs were remotely verified.
3. Re-check complete `main...dev` diff and unresolved blockers.
4. If the repository promotion gate remains green, open and normally merge a traceable `dev/zn-agent -> main` PR for the clean-install stage.
5. Verify canonical post-merge `main` `ZN CI` and reconcile refs/docs/HANDOFF.
6. Begin the next low-risk isolated installed-N baseline evidence slice. It may read sanitized Self/work/config/provider metadata, but it must not invoke updater/replacement/rollback/signing.

## Blockers

No implementation blocker is currently known for the clean-install slice. Promotion remains pending only on documentation-head verification and final promotion checks at the time of this handoff write.
