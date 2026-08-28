# ZN Implementation Status

This file is the implementation/evidence ledger for ZN. It is not a wish list or a mandatory execution order. When it conflicts with code, Git state, or real CI, the repository and real execution evidence win and this file must be corrected. Candidate next work must be re-ranked against current product gaps before implementation starts.

## Repository state

- Repository: `9529360-cpu/znagent`
- Primary development branch: `dev/zn-agent`
- Canonical/release branch: `main`
- Windows clean-install implementation/proof head: `cb913d61f001af6c729a141a3c8631a72e8362cf`
- Clean-install documentation closeout head: `4b770345e1267db1cfdc37c9551ff967d6955c27`
- Canonical clean-install promotion head: `a4f9c95a32571add9bd16ec5aa08a618c8e5566b`
- Before the post-promotion ledger reconciliation, `main` and `dev/zn-agent` were synchronized at `a4f9c95a32571add9bd16ec5aa08a618c8e5566b`.
- PR #11 promoted the Windows x64 unsigned candidate-proof stage to `main`.
- PR #12 merged the clean Windows install/first-start proof into `dev/zn-agent`.
- PR #13 promoted the clean Windows install/first-start proof to canonical `main`.
- No force push or Git history rewrite is part of this stage.

## Stage summary

| Area | Status | Evidence boundary |
| --- | --- | --- |
| Resident Self / Body / Senses / Situation / Thought / Will | implemented and continuously tested | ZN-owned Python resident; zero-model boot remains required |
| Durable work/recovery/restart semantics | implemented in bounded slices | covered by the Windows kernel suite; destructive restore remains outside current authority |
| P5 recovery-control program | PARTIAL | read-only restore proposals are canonical; restore execution is not granted |
| Windows x64 unsigned release-candidate build | COMPLETE / CANONICAL NARROW PROOF | clean hosted Windows build, packaged runtime boot, unsigned NSIS/MSI and independent manifest/hash verification |
| Windows x64 clean install + first resident start | COMPLETE / CANONICAL CI-VERIFIED NARROW PROOF | real NSIS install in isolated hosted-runner state, launch installed `ZN.exe`, materialize packaged runtime, observe resident RPC and graceful shutdown; promoted through PR #13 |
| Installed N baseline evidence | NOT STARTED / CANDIDATE | useful low-risk continuity prerequisite, but must be ranked against other current product gaps |
| Installed N -> N+1 continuity | INCOMPLETE / HUMAN-APPROVAL BOUNDARY | no formal updater/replacement transition has been executed |
| Rollback / signing / release trust | INCOMPLETE / HUMAN-APPROVAL BOUNDARY | not exercised by this stage |
| Formal release/stable-channel publication | INCOMPLETE | no tag, GitHub Release, stable-channel advance, or user-machine replacement in this stage |
| Self-maintenance | SM0 complete; later phases incomplete | see `docs/ZN-SELF-MAINTENANCE.md` |

A status of `implemented` means code exists and has the stated evidence; it does not by itself prove that every real product entry point, recovery path, installation transition or user scenario is closed. Maintainers should use `AGENTS.md`'s `exists -> wired -> verified -> product-closed` distinction when deciding what to do next.

## Windows unsigned candidate proof

The bounded Windows candidate stage is canonical on `main` through PR #11 at `3741db32c739322a3f921ea62798b2c698ef0771`.

Post-merge `ZN CI` run `33192086069` completed successfully on that canonical commit. The candidate stage proves a clean Windows x64 runner can:

- install locked build dependencies;
- stage ZN-owned portable CPython and the ZN Python distribution;
- boot the staged runtime with no model;
- build the independent Electron control plane;
- build unsigned NSIS and MSI candidates;
- boot the packaged runtime before publication;
- generate a Windows release manifest and independently verify exact installer size/SHA-256;
- upload bounded candidate evidence.

This is a build/integrity proof, not a signed or published formal release.

## Windows clean install and first-start proof

Implementation/proof head: `cb913d61f001af6c729a141a3c8631a72e8362cf`.

Exact implementation-head remote evidence:

- `ZN CI` run `33193710879`: all three substantive jobs succeeded; Windows kernel suite ran **686 tests** in `609.959s`, `OK (skipped=5)`; Source Boundary and Electron/TypeScript also succeeded.
- `ZN Windows Release Candidate` run `33193711016`: success. Artifact `9695032455`, archive digest `sha256:a5e65ee7b02ef977260e30365ba460cbd30dcfef1d46550c58a31b8cc7739aa6`.
- `ZN Windows Clean Install` run `33193710872`: success. Artifact `9695069801`, archive digest `sha256:c55e2c72c3a86b8661273520874b1aec395804188cc34f8231071e4ce2407f06`.

The clean-install lane uses the production ownership chain rather than an unpacked/mock shortcut:

`installed ZN.exe -> zn-main.ts -> packaged runtime materialization -> resident IPC/autostart path -> Python resident socket service`.

The exact-head run proved that a clean hosted Windows x64 runner can:

1. build and independently verify the real unsigned NSIS/MSI candidate;
2. silently install the real NSIS executable into isolated runner state;
3. start the installed `ZN.exe`;
4. require installed `resources/app.asar` and bundled `resources/zn-runtime`;
5. materialize the packaged runtime into isolated `ZN_AGENT_HOME/runtime/<runtime_id>`;
6. require resident endpoint `runtime_id` to equal the exact Git commit;
7. require resident Python to live inside that materialized runtime;
8. connect to the real loopback TCP resident endpoint and verify `ping`, `status`, and `self`;
9. observe `pulse_count >= 1` (exact run observed `pulse_count=1`);
10. request graceful resident shutdown and require endpoint retirement;
11. upload bounded proof logs/runtime manifest.

The same run observed resident runtime id `cb913d61f001af6c729a141a3c8631a72e8362cf` and portable Python under the isolated installed runtime.

### Clean-install promotion and canonical verification

The documentation closeout head `4b770345e1267db1cfdc37c9551ff967d6955c27` received exact-head `ZN CI` run `33195494937`; the workflow completed successfully.

PR #13 then normally promoted the completed low-risk clean-install stage to canonical `main`, producing merge commit `a4f9c95a32571add9bd16ec5aa08a618c8e5566b`.

Canonical post-merge `ZN CI` run `33196441295` ran on `a4f9c95a32571add9bd16ec5aa08a618c8e5566b` and completed successfully. Its substantive jobs all succeeded:

- `ZN Kernel / Python / Windows`;
- `Electron / TypeScript / Windows`;
- `ZN Source Boundary / Windows`.

The clean-install/first-start stage is therefore complete and canonical as a bounded unsigned Windows x64 proof. This does not expand its authority into updater, rollback, signing, publication, or user-machine replacement.

## Open product gaps

The clean-install proof must not be broadened into a release-ready claim. Current known gaps include:

- actual Windows login/reboot autostart behavior on a persistent installed machine; unit contracts exist, but a real login-cycle proof does not;
- an installed-version continuity baseline covering stable Self/work/config references before a transition;
- a real installed **N -> N+1** application transition;
- identity, memory, work, provider-setting and resident continuity across that transition;
- failed-update recovery and rollback;
- Windows code signing, trust-chain verification and release signing policy;
- production tag/release/stable-channel publication;
- replacing a user's current formal installation;
- remaining P5 restore/recovery capability beyond the currently canonical read-only proposals;
- any higher-priority correctness, security, reliability, active-caller wiring or user-facing blocker discovered in the current code.

Updater/replacement, rollback, signing, release-trust and installed-version replacement remain explicit human-approval boundaries. The clean-install stage did not invoke them.

This list is evidence of known gaps, not a fixed roadmap. A maintainer must compare these items with newly discovered code/runtime problems and choose the highest-value safe next increment using `AGENTS.md`.

## Candidate next work: installed N baseline

An **installed N baseline evidence** lane remains a useful low-risk candidate because it can establish read-only continuity evidence before any later N -> N+1 experiment. It is not automatically the next task.

If current product triage selects this candidate, the lane should read and bind non-secret resident evidence needed for a later continuity comparison, for example:

- exact installed/runtime identity;
- stable Self identity/reference required for continuity checks;
- bounded Work/thread references and counts rather than message bodies;
- runtime/home/config path identity;
- sanitized provider-setting metadata such as provider/model/base URL plus credential presence/source metadata, never secret values;
- resident endpoint and pulse/life evidence.

It must not:

- call the updater or replace installed N;
- mutate credentials or permissions;
- execute rollback;
- change signing/release trust;
- modify identity or long-term memory;
- publish a tag/GitHub Release or advance `stable.json`.

A later N -> N+1 transition experiment remains separately approval-gated. Before proposing it, verify that the selected baseline evidence is actually sufficient to detect continuity loss rather than merely producing another artifact.
