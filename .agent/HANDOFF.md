# ZN Maintainer Handoff

This is the current engineering work site and fact index, not a chat summary or execution script. Real code, Git state and actual CI remain authoritative.

## Current goal

Close the managed-browser + bounded Work-restore stage cleanly, keep canonical `main` reasonably current after verification, and advance the next product gap: a read-only installed-N continuity baseline. The baseline is safe preparation for later continuity testing; an actual N -> N+1 replacement remains approval-gated.

## Repository state

- Repository: `9529360-cpu/znagent`
- Canonical/release branch: `main`
- Primary development branch: `dev/zn-agent`
- Current verified-development head entering this reconciliation: `5c347925490179748e44e35c43b0435ede9e1f14` (PR #35 merge).
- Reconciliation branch: `work/browser-stage-reconcile` / PR #36.
- Installed-N continuity work is isolated on `work/installed-n-continuity-baseline` / PR #37 until its own Windows evidence is green.
- `main` is still at `a4f9c95a32571add9bd16ec5aa08a618c8e5566b`; at the PR #35 merge head, `dev/zn-agent` was 103 commits ahead and 0 behind. Do not treat this divergence as a roadmap item; sync normally after exact-head validation and ledger reconciliation.

## Product reality

### Bounded Work restore

The old “read-only restore only” description is obsolete.

- PR #19 added the first mutation-capable restore slice for Windows: exact retained Work bytes may be restored only when the target is freshly/stably missing, through explicit `work_restore_prepare` then `work_restore_approve`.
- Existing parent identity is bound and revalidated; same-directory staging plus a no-replace namespace move ensures a target that reappears wins the race and is never overwritten.
- Application state is durable (`approval_required`, `applying`, `stage_ready`, `commit_started`, `completed`, `recovery_required`, `blocked`). Restart reconciliation observes reality but never silently resumes a mutation.
- PR #21 keeps full restore context behind exact Work-thread binding.
- PR #22 wired the bounded flow into the desktop with two explicit user actions: Prepare, then Approve exact restore. Unsafe/changed/unchanged targets stay inspection-only.
- PR #23 proved a prepared approval can be rediscovered after resident restart while still requiring a new explicit approval action.
- PRs #25/#26 closed desktop protocol and proposal-contract regressions.
- This is a narrow missing-target/no-replace product slice, not general destructive restore authority.

### Managed browser + Work

- PR #28 packages Playwright + Chromium inside the formal versioned Windows ZN runtime and verifies packaged Chromium can launch.
- PR #29 makes the formal resident expose bounded managed-browser RPC.
- PR #30 fixes Playwright thread affinity by owning all browser provider calls on one resident browser thread, including reconnecting TCP clients.
- PR #31 makes browser owner shutdown atomic against late calls.
- PR #32 wires structured `browser_navigate` into the real Work lifecycle. Permission is derived from the structured target URL; free text/model output is not browser authority.
- Navigation is treated as a non-replayable outside-world side effect. ZN durably records the attempt and blocks blind replay when certainty is lost.
- Provider success is not Work completion. ZN persists a `browser_url_equals` postcondition, independently re-observes the live page, closes the session, and only then finalizes Work.
- PR #33 composes browser behavior on the mature Body stack so atomic-overwrite, namespace-recovery, keyboard/pointer and generic side-effect protocols remain intact.
- PR #34 puts browser Work under the dedicated Work Recovery lane.
- PR #35 fixes the MRO regression exposed by that lane: non-browser verification now delegates via instance `super()` instead of bypassing the mature verification chain.
- Browser click/type/select/upload/download are intentionally not exposed through Work yet; they need stronger authority/replay/postcondition design.

## Verification evidence

Completed exact-head evidence:

- `ZN Managed Browser E2E` run `33219726246` on implementation head `1f4da5fae6d6481375290637027fa273714bb032`: success, including real Chromium Work navigation.
- `ZN Managed Browser E2E` run `33220567118` on PR #35 merge head `5c347925490179748e44e35c43b0435ede9e1f14`: success; browser contract tests and real local Chromium E2E both succeeded.
- `ZN Work Recovery E2E` run `33220567184` on the same PR #35 merge head: success; the full recovery lane passed after the MRO fix, so the 19 mature non-browser recovery regressions exposed by PR #34 are resolved in actual CI.
- Prior packaged-runtime clean-install proof `33216509252`: success, including packaged Chromium launch and installed resident start.

Still in flight at the latest check:

- `ZN CI` run `33220567183`, exact PR #35 merge head: Electron/TypeScript and Source Boundary are green; Kernel/Python full suite is still running.
- `ZN Windows Clean Install` run `33220521263` on exact PR #35 code head `aec2dcf72d6a91878e69930c9c93dfa8d014e3f5` is still building the unsigned installer candidate.
- PR #37 has its own latest Windows clean-install evidence run on the continuity-baseline head; do not claim the installed baseline product path is verified until that exact-head run succeeds.

Do not convert in-flight statements to success without fresh Actions evidence.

## Current risks / real gaps

- `main` is materially behind verified development and should be synchronized after the remaining exact-head general CI gate and status reconciliation.
- The installed-N continuity baseline is now being implemented, but it is not product-verified until a real installed resident emits the sanitized artifact in Windows clean-install CI.
- A real N -> N+1 installation replacement, failed-update rollback, signing/release trust and user-machine replacement remain explicit human-approval boundaries.
- Real Windows login/reboot autostart on persistent installed state remains a product gap.
- Managed browser mutation beyond navigation remains deliberately ungranted.

## Next candidates after current gates

1. Finish PR #36 once exact-head general CI truth is final, then normally merge the ledger reconciliation to `dev/zn-agent`.
2. Promote the verified development stack to canonical `main` through a normal PR if merge/check requirements remain satisfied.
3. Finish PR #37 by proving a real installed ZN emits a bounded, non-secret continuity baseline containing stable Self identity/reference, Work/thread references and sanitized provider metadata without invoking updater/replacement authority.
4. Re-rank product gaps after that evidence. An actual N -> N+1 transition remains separately approval-gated.

A later N -> N+1 transition is not authorized by this handoff.
