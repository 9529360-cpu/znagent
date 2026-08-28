# ZN Next Phase

This file describes the next engineering sequence after reconciling the current repository state. It does not grant authority for updater, rollback, signing, release-trust, credential/permission, identity, or long-term-memory changes.

## Current verified foundation

ZN remains the only product/runtime owner. The resident owns Self, Body, Senses, Memory, Situation, Thought, Will, Investigation, Action and Learning; external models are optional cognitive resources rather than the agent owner.

The Windows-first release evidence now has two canonical bounded layers:

1. **Unsigned Windows x64 release candidate proof — complete/canonical.** PR #11 is on `main` at `3741db32c739322a3f921ea62798b2c698ef0771`; canonical post-merge `ZN CI` run `33192086069` succeeded.
2. **Clean Windows install + first resident start proof — complete/canonical.** The implementation/proof head was `cb913d61f001af6c729a141a3c8631a72e8362cf`; exact-head full `ZN CI` run `33193710879`, candidate run `33193711016`, and clean-install run `33193710872` succeeded. Documentation closeout head `4b770345e1267db1cfdc37c9551ff967d6955c27` then passed `ZN CI` run `33195494937`. PR #13 promoted the stage to canonical `main` at `a4f9c95a32571add9bd16ec5aa08a618c8e5566b`, and canonical post-merge `ZN CI` run `33196441295` completed successfully with Kernel/Python, Electron/TypeScript, and Source Boundary jobs all green.

Before the current ledger-reconciliation change, `main` and `dev/zn-agent` were synchronized at `a4f9c95a32571add9bd16ec5aa08a618c8e5566b`.

The clean-install lane installs the real unsigned NSIS candidate into isolated hosted-runner state, starts installed `ZN.exe`, materializes the packaged ZN runtime into an isolated `ZN_AGENT_HOME`, verifies exact runtime identity through the real resident loopback endpoint, proves resident life, and shuts the resident down cleanly.

This does **not** prove a formal release, updater transition, rollback, signing, or replacement of a user's installed copy.

## Windows-first M8 sequence

The intended sequence is now:

1. Clean hosted Windows x64 candidate build and integrity verification — **done/canonical**.
2. Real clean NSIS install and installed first-start/resident proof — **done/canonical**.
3. Installed **N baseline evidence** in isolated state — **next low-risk slice**.
4. Installed N -> N+1 continuity experiment — **not started; explicit human approval required before actual replacement/update execution**.
5. Failed-update/rollback evidence — **not started; explicit human approval required**.
6. Signing/release-trust validation — **not started; explicit human approval required**.
7. Formal repository release flow and stable-channel advance — only after repository gates, immutable artifacts, trust checks and required approvals are real.

## Next concrete low-risk slice: installed N baseline evidence

Before attempting a version transition, prove that an installed ZN can expose a small, privacy-safe baseline that a later N+1 run could compare against.

The baseline should be created only in isolated test state and should prefer existing resident RPC/read-only surfaces. Useful evidence includes:

- exact installed/runtime identity;
- stable resident Self identity/reference needed for continuity checks;
- bounded work/thread references and counts rather than private message bodies;
- runtime/home/config path identity;
- sanitized provider-setting metadata (`provider`, model/base URL as configured, credential presence/source metadata) without secret values;
- resident endpoint and pulse/life evidence.

The baseline must not:

- call `update_apply`, run an installer over an existing formal version, or otherwise replace installed N;
- modify identity or long-term memory;
- mutate provider credentials or permissions;
- execute rollback;
- alter signing/release trust roots;
- publish a tag, GitHub Release, or `stable.json`.

A later transition test should consume this baseline as evidence rather than inventing continuity criteria after the update has already happened.

## Current implementation path to inspect for the baseline slice

The existing call chain already exposes most of the needed evidence through ZN-owned read-only surfaces:

```text
installed ZN.exe
-> zn-main.ts / resident process ownership
-> resident endpoint
-> ResidentRpcServer
-> ping / status / self / provider_settings / work_list
-> ZN resident/store/life/provider settings/work ledger
```

Important constraints for implementation:

- `self` currently exposes the living Self snapshot and should be bounded to continuity-safe fields in the baseline artifact rather than copied wholesale.
- `provider_settings` already returns credential presence/source metadata without secret values and should remain the provider evidence source.
- `work_list` currently includes messages/artifacts; baseline collection must deliberately retain only bounded thread identity/count/reference information and must not persist message bodies or artifact contents.
- runtime/home/config and endpoint identity should come from installed/materialized paths and resident endpoint evidence, not guessed values.
- a baseline verifier should make privacy/sanitization requirements executable through tests.

## Other active program status

- P5 recovery-control remains **PARTIAL**. Read-only restore proposals are evidence, not restore authority.
- `docs/ZN-SOURCE-EXTRACTION.md` remains the extraction/source-boundary ledger; the clean-install promotion did not change source ownership.
- `docs/ZN-SELF-MAINTENANCE.md` remains the self-maintenance authority document; the clean-install promotion did not change its approval boundaries.

## Promotion rule for the next slice

The installed-N baseline stage may enter `main` only through the repository's normal traceable promotion flow after:

- the bounded baseline implementation is complete;
- privacy/sanitization and read-only behavior are covered by tests;
- exact-head relevant tests and full CI are green;
- any applicable isolated installed-N E2E evidence is green;
- documentation and `.agent/HANDOFF.md` reflect the real evidence;
- final `main...dev` diff inspection shows only the intended low-risk stage;
- no unresolved blocker or high-risk boundary has been crossed.

No updater/replacement, rollback, signing, release-trust or user-machine replacement authority is granted by this plan.
