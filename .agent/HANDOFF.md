# ZN Maintainer Handoff

This is the current engineering work site and fact index, not a chat transcript or execution script. Real code, live Git refs and actual test/build/CI results override this file when they disagree.

## Current verified checkpoint

The latest verified development checkpoint is merge `5f14a6453aadba196060e954ce7bc674551ac3e8` on `dev/zn-agent`.

At that checkpoint:

- ZN CI `33340676146` completed successfully across Source Boundary, Kernel/Python full core tests and Electron/TypeScript.
- Work Recovery E2E `33340676170` completed successfully.
- Managed Browser E2E `33339937362` completed successfully on `f68ff28de63bc334033b5b8f05520c96deffbc70`; later commits in the same tranche changed compiler contract tests/workflow coverage and passed Work Recovery plus full ZN CI.
- Hosted Windows Clean Install and Release Candidate runs still fail before execution with `steps=[]` and `runner_id=0`. Treat this as runner-allocation infrastructure evidence unless a future run actually executes steps.

PR #123 promoted the reconciled verified tranche to canonical `main`; canonical merge SHA is `ac6b3846d621dd790f587cbc08311b162eba6b97`. Fresh maintainers must still query live refs, open PRs and CI before acting. Exact SHAs in this file are evidence checkpoints, not permanent branch oracles.

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

PR #125 is the current User Browser Bridge candidate. On candidate commit `f1ded231d44dc58e9d9a597213f8f738ea5560f4`, Windows Interactive Desktop E2E `33354912873`, full ZN CI `33354911263` and Work Recovery E2E `33354930689` all completed successfully. Hosted clean-install run `33354874932` failed before execution with `steps=[]`; it is runner-allocation evidence, not an executed candidate failure.

## Resident reliability and reporting reality

PR #121 is merged. If a BUG-report dispatch was durably reserved and the resident stopped before recording delivery or uncertainty, reconstructing the outbox now promotes the abandoned `dispatching` record to `outcome_uncertain`, preserves `dispatch_attempts`, and continues to reject automatic replay. This recovery is covered by the successful Work Recovery run above.

BUG/repair reporting otherwise remains local-only in merged product code. There is no merged operator-controlled network transport, acknowledgement or maintainer intake active caller yet.

The current large-stage collaboration has an isolated transport/intake implementation lane. That lane owns the new transport/intake modules plus the related `upstream_bug_report.py` / `reporting_maintenance_resident.py` call chain until it produces a reviewable PR. The promotion/documentation lane must not concurrently edit those product files. When the isolated PR arrives, re-anchor to its live base/head/diff and verification evidence before merge.

Normal installed ZN still has no official repository push, PR, merge, release or signing authority.

## Current repository hygiene

The verified development tranche has been promoted through PR #123 to canonical `main`. Canonical ZN CI run `33353573721` is the post-promotion authority; inspect its live final state rather than inferring success from the dev run.

Repository synchronization is engineering hygiene, not the product milestone. `dev/zn-agent` may temporarily trail `main` by the promotion merge commit; reconcile normal branch ancestry without force updates and without disturbing active isolated product branches.

## Current product gaps

1. BUG/repair transport/intake is the active isolated product stage: local formation and crash-safe dispatch accounting are verified, but operator-controlled transport, acknowledgement/reconciliation and maintainer intake are not merged yet.
2. User Browser Bridge has a bounded local mutation foundation: an explicitly scoped, already-focused, empty non-password HTML Edit can receive one non-replayable text input and be independently verified by fresh UIA RuntimeId plus privacy-safe length/digest evidence. Current real Windows evidence still uses an isolated temporary Edge profile; attachment to an authenticated existing Edge/Chrome session and user-facing permission UX are not product-closed. Never solve this by copying cookies, passwords or profile data.
3. Managed browser remains deliberately bounded. Generic target discovery, multi-tab/popup/frame authority, downloads/uploads and broad arbitrary interaction are not product-closed.
4. Browser recovery is strong where a trustworthy durable observed result exists; unknown external mutations without sufficient evidence still fail closed and require bounded re-sense/reclassification work.
5. Installed update observation and release machinery exist, including public-channel parsing and package verification, but formal N -> N+1 continuity, rollback and signing/trust remain approval-gated product stages.
6. Unified health remains partial.

## Immediate continuation

1. Finish reading canonical ZN CI `33353573721` for PR #123's main merge and classify only executed-code failures as product failures.
2. Preserve the transport/intake ownership boundary; do not modify its reserved product files from the promotion/documentation lane.
3. When the isolated transport/intake PR arrives, review its live base/head/diff, authority boundaries, retry/reconciliation semantics and actual tests before merge.
4. After that merge, re-evaluate the highest-value product gap from real code and runtime evidence rather than from this queue alone.

No force push, history rewrite, repository credential expansion, updater replacement, rollback, release signing or destructive identity/memory migration is authorized by this handoff.
