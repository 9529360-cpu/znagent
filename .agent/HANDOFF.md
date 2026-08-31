# ZN Maintainer Handoff

This is the current engineering work site and fact index, not a chat transcript or execution script. Real code, live Git refs and actual test/build/CI results override this file when they disagree.

## Current verified checkpoint

The latest verified development checkpoint is merge `5f14a6453aadba196060e954ce7bc674551ac3e8` on `dev/zn-agent`.

At that checkpoint:

- ZN CI `33340676146` completed successfully across Source Boundary, Kernel/Python full core tests and Electron/TypeScript.
- Work Recovery E2E `33340676170` completed successfully.
- Managed Browser E2E `33339937362` completed successfully on `f68ff28de63bc334033b5b8f05520c96deffbc70`; later commits in the same tranche changed compiler contract tests/workflow coverage and passed Work Recovery plus full ZN CI.
- Hosted Windows Clean Install and Release Candidate runs still fail before execution with `steps=[]` and `runner_id=0`. Treat this as runner-allocation infrastructure evidence unless a future run actually executes steps.

Fresh maintainers must still query live refs, open PRs and CI before acting. Exact SHAs in this file are evidence checkpoints, not permanent branch oracles.

## Managed-browser product reality

The same-session form transaction from PR #120 is merged and verified. Ordinary Work can now deterministically perform this bounded scenario:

```text
explicit start URL
-> fresh exact semantic textbox observation by accessible name
-> explicit bounded text entry
-> same-node length/SHA-256 verification
-> fresh exact semantic button observation by accessible name
-> submit in the same managed Chromium session
-> independent explicit same-origin final-URL verification
-> durable Work result
-> observed-result restart recovery without blind replay
```

The real Chromium fixture makes the final `/done` result depend on the exact text still being present when the button is clicked, proving same-session state retention rather than a sequence of disconnected primitives.

The verified ordinary Work browser surface now includes:

- safe navigation with observed URL completion;
- exact accessible-name checkbox selection and checked-state verification;
- exact accessible-name button click with explicit URL postcondition;
- exact accessible-name textbox entry with same-node digest/length verification;
- a bounded same-session textbox-plus-submit transaction;
- durable observed-result recovery for the verified button, textbox and form paths.

The structured-action compiler now limits historical `text -> content` compatibility to `write_text` / `write_file`. Browser, form and keyboard text no longer receive a duplicate plaintext `content` alias. Form Body history also retains a second defensive redaction boundary. The structured compiler and its tests are included in Managed Browser and Work Recovery workflow coverage.

## Resident reliability and reporting reality

PR #121 is merged. If a BUG-report dispatch was durably reserved and the resident stopped before recording delivery or uncertainty, reconstructing the outbox now promotes the abandoned `dispatching` record to `outcome_uncertain`, preserves `dispatch_attempts`, and continues to reject automatic replay. This recovery is covered by the successful Work Recovery run above.

BUG/repair reporting otherwise remains local-only. There is no operator-controlled network transport, acknowledgement or maintainer intake active caller. The user has explicitly deprioritized that missing transport for the current stage.

Normal installed ZN still has no official repository push, PR, merge, release or signing authority.

## Current repository hygiene

At the `5f14a645...` checkpoint, `dev/zn-agent` was 56 commits ahead of and 0 commits behind `main`. This documentation had fallen behind the verified code and CI; that drift is itself a recoverability defect. Reconcile these files and promote through the normal traceable `dev -> main` flow once the live comparison still shows no reverse drift.

Repository synchronization is engineering hygiene, not the product milestone, but canonical `main` must not remain arbitrarily detached from a fully verified development tranche.

## Current product gaps

1. User Browser Bridge is still sensing-only foundation. The real Windows proof uses an isolated temporary profile; attachment to an authenticated existing Edge/Chrome session, explicit permission and mutation are not product-closed. Never solve this by copying cookies, passwords or profile data.
2. Managed browser remains deliberately bounded. Generic target discovery, multi-tab/popup/frame authority, downloads/uploads and broad arbitrary interaction are not product-closed.
3. Browser recovery is strong where a trustworthy durable observed result exists; unknown external mutations without sufficient evidence still fail closed and require bounded re-sense/reclassification work.
4. Installed update observation and release machinery exist, including public-channel parsing and package verification, but formal N -> N+1 continuity, rollback and signing/trust remain approval-gated product stages.
5. BUG/repair transport/intake is missing but currently deprioritized by the user.
6. Unified health remains partial.

## Immediate continuation

1. Re-read live `dev/zn-agent`, `main`, open PRs and the latest CI.
2. Merge the documentation reconciliation without changing product claims beyond verified evidence.
3. Promote the verified development tranche to `main` through normal PR/merge flow if live refs remain `dev ahead / behind 0`, then verify canonical CI.
4. Resume a user-visible product stage. The strongest current candidate is a permissioned User Browser Bridge slice that operates an already-focused, non-password control in the user's existing browser without extracting profile credentials.
5. Keep each new browser mutation bound to fresh exact target evidence, explicit user authority, independent postcondition and restart-safe semantics.

No force push, history rewrite, repository credential expansion, updater replacement, rollback, release signing or destructive identity/memory migration is authorized by this handoff.
