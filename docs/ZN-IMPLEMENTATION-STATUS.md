# ZN Implementation Status

This file is the implementation/evidence ledger for ZN. It is not a mandatory roadmap. Real code, Git state and actual test/build/CI results override this ledger when they disagree.

## Repository state

- Repository: `9529360-cpu/znagent`
- Primary development branch: `dev/zn-agent`
- Canonical/release branch: `main`
- Development head entering this reconciliation: `5c347925490179748e44e35c43b0435ede9e1f14` (PR #35 merge).
- Canonical `main` is still at `a4f9c95a32571add9bd16ec5aa08a618c8e5566b`; at that development head, `dev/zn-agent` was 103 commits ahead and 0 behind.
- No force push or history rewrite is part of the current stage.

## Capability ledger

| Area | Current maturity | Evidence boundary |
| --- | --- | --- |
| Resident Self / Body / Senses / Situation / Thought / Will | implemented, wired, continuously tested | ZN-owned Python resident; zero-model boot remains required |
| Durable Work / restart recovery | implemented in bounded product slices | broad Windows core/recovery suites; exact PR #35 recovery rerun is the current regression gate |
| Work restore inspection | wired and verified | resident + desktop can inspect restore state without mutation |
| Missing-target Work restore application | wired and verified, narrow authority | Windows-only explicit prepare -> approve, exact retained bytes, missing target only, no replacement, durable restart reconciliation |
| Managed Chromium runtime | wired and verified | formal versioned Windows runtime packages Playwright/Chromium and launch-smokes the packaged browser |
| Resident managed-browser RPC | wired and verified | observation by default; explicit bounded navigation; resident-owned browser thread survives reconnecting TCP clients |
| Structured Work browser navigation | wired and real-E2E verified | structured `browser_navigate` -> durable side-effect attempt -> real Chromium -> independent URL observation -> session cleanup -> Work completion |
| Browser mutation beyond navigation | not granted | click/type/select/upload/download are intentionally absent from Work authority |
| Windows x64 unsigned release-candidate build | canonical narrow proof | clean hosted Windows build, packaged runtime boot, unsigned NSIS/MSI and independent manifest/hash verification |
| Windows x64 clean install + first resident start | canonical narrow proof | real NSIS install in isolated state, installed `ZN.exe`, materialized runtime, resident RPC/life and graceful shutdown |
| Installed-N continuity baseline | not yet product-closed | current clean-install proof reads `self`/`status`, but does not persist a bounded baseline sufficient for later continuity comparison |
| Installed N -> N+1 continuity | approval-gated / incomplete | no formal updater/replacement transition has been executed |
| Rollback / signing / release trust | approval-gated / incomplete | not exercised by the current stage |
| Formal release/stable-channel publication | incomplete | no current-stage tag, GitHub Release, stable-channel advance or user-machine replacement |
| Self-maintenance | SM0 complete; later phases incomplete | see `docs/ZN-SELF-MAINTENANCE.md` |

Use `exists -> wired -> verified -> product-closed` rather than treating the presence of code as proof that the user scenario is complete.

## Bounded Work restore application

The previous statement that P5 restore was only read-only is obsolete.

PR #19 introduced the first mutation-capable recovery slice without granting general destructive restore authority:

- the target must be freshly and stably missing;
- exact retained Work bytes are the only restore content;
- the existing non-reparse parent directory is identity-bound during preparation and revalidated before commit;
- bytes are staged in the same directory and committed using a Windows no-replace move, so a target that reappears is never overwritten;
- application progress is durable across `approval_required`, `applying`, `stage_ready`, `commit_started`, `completed`, `recovery_required` and `blocked` states;
- restart recovery observes actual namespace/content reality and never automatically resumes an uncertain mutation;
- preparing and approving are separate explicit authority steps.

PR #21 keeps full restore application context behind exact Work-thread ownership. PR #22 wires the flow into the desktop with separate Prepare and Approve controls while unsafe/changed/unchanged targets remain inspection-only. PR #23 proves prepared approval continuity across resident restart without converting it into automatic mutation authority. PRs #25 and #26 close desktop protocol/proposal-contract regressions.

This means the bounded missing-target/no-replace scenario has advanced through existence, wiring and product-path verification. It does **not** authorize overwriting a changed/current target, directory replacement, model-driven automatic restore, or destructive identity/memory recovery.

## Managed browser product path

The browser path is no longer test-only or an uncalled module.

PR #28 stages Playwright and Chromium inside the formal versioned Windows runtime, records the runtime-owned browser path, binds `PLAYWRIGHT_BROWSERS_PATH`, isolates N/N+1 runtime browser roots and launch-smokes packaged Chromium before installation.

PR #29 makes the formal resident browser-aware and exposes a deliberately bounded RPC path. Default permission remains observation-only; navigation requires explicit permission and fresh observed authority.

A real Windows reconnect E2E then exposed Playwright sync API thread affinity. PR #30 moved all provider access onto one resident-owned browser thread so session lifecycle does not depend on TCP handler thread identity. PR #31 made final browser cleanup atomic against late/reconnecting calls.

PR #32 wires structured `browser_navigate` into the actual Work lifecycle:

1. a structured Body action provides the target URL;
2. ZN derives only the minimal browser permission context required for that origin (plus optional explicit private-network allowance);
3. navigation is classified as a non-replayable outside-world side effect and enters the existing durable attempt/recovery boundary before dispatch;
4. provider dispatch produces effect evidence but does not complete the Work;
5. ZN persists a `browser_url_equals` verification contract tied to the real session/page;
6. a later resident pulse independently observes the live page, compares the URL, closes the session, and only then finalizes success/learning;
7. uncertainty/restart blocks blind replay and enters the existing explicit recovery-decision path.

The formal resident constructor is the active caller. The real Windows E2E drives `work_start/work_progress` over resident TCP, lets the resident life loop execute the structured Work against real local Chromium, requires independent URL observation/cleanup, and observes finalized Work.

PR #33 corrected the browser Body composition so the final runtime inherits the mature atomic-overwrite, namespace-recovery, keyboard/pointer and generic side-effect protocols rather than replacing them with an earlier Body layer.

PR #34 added browser Work modules/tests to the dedicated Work Recovery lane. That lane exposed a second composition bug: browser verification hard-called a base class as a static function, dropping `self` from the effective procedural verification method and causing 19 mature non-browser recovery errors. PR #35 changed browser verification to instance delegation via `super()`, preserving the full MRO below the browser specialization.

### Browser evidence

- Windows clean-install run `33216509252`: success on the packaged-browser implementation head; packaged Chromium launch and installed resident start both succeeded.
- `ZN Managed Browser E2E` run `33219726246`: success on implementation head `1f4da5fae6d6481375290637027fa273714bb032`, including real Chromium structured Work navigation.
- `ZN Managed Browser E2E` run `33220567118`: success on exact PR #35 merge head `5c347925490179748e44e35c43b0435ede9e1f14`; managed-browser contract tests and real local Chromium E2E succeeded after the MRO fix.
- `ZN Work Recovery E2E` run `33220567184`: running on the exact PR #35 merge head at the time this reconciliation was written. It is the hard gate proving the 19 mature recovery regressions are actually gone.
- `ZN CI` run `33220567183`: Electron/TypeScript and Source Boundary jobs are green on the exact merge head; Kernel/Python full suite is still running at the time of this reconciliation.

Do not upgrade the two in-flight entries to success without fresh Actions evidence.

## Windows candidate and clean-install proof

The canonical clean-install proof remains the narrow Windows x64 unsigned evidence promoted through PR #13 to `main` at `a4f9c95a32571add9bd16ec5aa08a618c8e5566b`.

Historical exact-head evidence remains valid for that bounded capability:

- `ZN CI` run `33193710879`: success; Python kernel suite reported 686 tests, 5 skipped at that earlier head; Electron/TypeScript and Source Boundary also succeeded.
- `ZN Windows Release Candidate` run `33193711016`: success.
- `ZN Windows Clean Install` run `33193710872`: success.
- canonical post-merge `ZN CI` run `33196441295`: success on `main`.

The clean-install lane follows the real ownership chain:

`installed ZN.exe -> Electron main -> packaged runtime materialization -> resident process -> Python resident TCP service`.

The current verifier requires the installed executable/app.asar/bundled runtime, exact materialized runtime id, resident Python under that runtime, real `ping`, `status`, `self`, life pulse, graceful resident shutdown and endpoint retirement.

It is a clean-install/start proof, not proof of update continuity, rollback, signing, publication or user-machine replacement.

## Open product gaps

Known gaps that still matter after the restore/browser work include:

- installed-N continuity baseline that binds stable non-secret Self identity/reference, Work/thread references, runtime/home/config identity, sanitized provider-setting metadata and resident-life evidence into a later-comparable snapshot;
- real installed N -> N+1 application transition and continuity across it;
- failed-update recovery and formal rollback;
- actual Windows login/reboot autostart behavior on persistent installed state;
- Windows code signing, trust-chain verification and release-signing policy;
- production tag/release/stable-channel publication;
- replacing a user's current formal installation;
- richer browser actions, but only after authority/replay/postcondition semantics are designed strongly enough for non-replayable page mutation;
- any higher-priority identity, memory, reliability, security, active-caller or product-path defect found in real code.

Updater/replacement, formal rollback, signing/release trust and replacement of a user's formal installation remain explicit human-approval boundaries.

## Leading safe next candidate: installed-N continuity baseline

Current triage still makes the installed-N baseline a strong next candidate after the browser/restore stage is fully green and canonical source is reconciled. It is useful because “new version starts” is not enough for a resident subject; later transition work needs a pre-transition truth set capable of detecting continuity loss.

A useful baseline should remain read-only and non-secret while binding, at minimum:

- exact installed/runtime identity;
- stable Self identity/reference required for continuity comparison;
- bounded Work/thread references and counts rather than message bodies;
- runtime/home/config path identity;
- sanitized provider/model/base-URL metadata plus credential presence/source metadata, never secret values;
- resident endpoint/life evidence.

It must not invoke the updater, replace installed N, mutate identity or long-term memory, alter credentials/permissions, execute rollback, change release trust, publish a release, or advance a stable channel.

A later N -> N+1 experiment remains separately approval-gated and must not be inferred from completion of the baseline.
