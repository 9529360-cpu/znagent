# E2E-13 — Windows current-app bounded content cleanup

Status: **VERIFIED NARROW / representative path closed on open PR #252; not merged to `main`.**

Updated: 2026-09-13

## User-facing scenario

Representative natural-language task:

> 把我现在开的工作记录整理一下：去掉每行前后空格，删掉空行，重复内容只保留第一次，然后保存。

The bounded fixture exposes one multiline UIA Edit named `工作记录`, one Button named `保存`, and after Save a fresh same-process result window titled `ZN 工作记录已保存` with one read-only UIA Edit named `保存内容`.

## Verified representative path

The existing Product Resident remains the only task owner and the existing product Body remains the only mutation surface. No DesktopAgent, AppAgent, DialogAgent, second router/store, clipboard path, OCR path, RPA engine, or generic rich-text editor is added.

The path is:

`desktop_user_event -> typed semantic cleanup goal -> fresh foreground HWND/PID/process -> exact named multiline Edit -> bounded ValuePattern read -> trim each line -> drop blank lines -> stable exact dedupe -> guarded exact ValuePattern replacement -> fresh post-replacement reread -> fresh exact Save Button -> existing durable pointer-click lifecycle -> one Save dispatch -> old HWND/RuntimeIds discarded -> fresh same-process result HWND -> exact read-only 保存内容 ValuePattern readback -> chars/SHA-256 verification -> independent Root Work acceptance`

The transform is deterministic:

1. split into lines;
2. trim leading/trailing whitespace from each line;
3. drop blank lines;
4. keep the first occurrence of each remaining exact line, preserving order;
5. join with CRLF.

Source and result are bounded to 4096 characters. An empty transformed result fails closed.

## Fresh authority and stale-evidence handling

Every mutation depends on fresh exact authority for the current foreground window/process and exact UIA target. Before `SetValue`, the implementation re-finds the exact Edit, verifies RuntimeId/process/HWND/name/control type/ValuePattern/writable state, checks the current source length and SHA-256, then re-acquires again immediately before dispatch.

If the Edit RuntimeId changes before mutation, old evidence is discarded and the source is freshly reread/retransformed. If source content drifts before any replacement attempt crosses the durable side-effect boundary, the stale transform is rejected and recomputed from fresh content. Ambiguous same-name Edits fail before mutation.

After `SetValue`, the target is freshly reacquired and reread. Save uses the existing pointer-click durable lifecycle. The exact Save Button is freshly reacquired immediately before input, and after one pointer dispatch the implementation never clicks Save again. Final verification is observation-only.

## Restart and no-replay reconciliation

`automation_value_replace` uses the existing durable side-effect attempt journal. E2E-13 does not treat `ValuePattern.SetValue` as an idempotent operation.

Recovery checks durable dispatch ownership by the same event plus action kind **before** ordinary content-drift logic. A previous `started`, `observed`, or already machine-resolved `verified_effect` replacement attempt therefore continues to own the mutation boundary even if a restart sees different current text and a newly computed replacement would otherwise have a different action signature.

For an unresolved prior replacement attempt, restart recovery is read-only:

- fresh-bind the same bounded foreground process/window and exact named Edit;
- fresh-read the current value without dispatching a new replacement;
- compare only bounded expected-result length/SHA-256 against the prior durable attempt evidence;
- exact expected result -> resolve/retain the old attempt as `verified_effect` and continue with fresh post-replacement verification;
- any mismatch, lost process/window authority, ambiguity, or inability to prove the expected result -> fail closed;
- no mismatch path is allowed to manufacture a new replacement signature or blindly call `SetValue` again.

Persistent-SQLite Resident rebuild regressions cover a crash after durable `started`, a crash after Body observation but before WorkingState checkpoint, a second crash after `verified_effect` reconciliation but before WorkingState advances, and a mismatch after restart. The recovery cases assert zero additional `automation_value_replace` dispatches.

## Privacy boundary

Raw current-app source and replacement text are transient only.

Durable WorkingState, audit data and Body history retain only bounded semantic/provenance metadata such as control names, HWND/PID/process identity, RuntimeIds where needed for authority, character/line counts, removal counts and SHA-256 digests. `replacement_text` is stripped from durable Body action history and replaced with redaction metadata. Raw source/result content is not sent to a model.

## Real Windows acceptance

The Windows Interactive workflow has an explicit `Run E2E-13 current-app content cleanup` step before E2E-15 and the broader product-route sweep. The real WinForms acceptance covers:

- happy path: deterministic cleanup, exactly one Save, fresh result-window readback and Root Work completion;
- stale Edit RuntimeId: stale authority rejected and freshly regrounded before mutation;
- source content drift before dispatch ownership: stale transform rejected and recomputed;
- ambiguous same-name Edit: zero mutation and zero Save;
- final application mismatch: Save may occur once, but final verification fails and Root Work does not complete.

The exact final merge-readiness evidence is intentionally not hard-coded here because synchronizing documentation itself creates a new PR head. PR #252 and its live checks are the authority for the eventual final head and run IDs.

## E2E-07 regression handling during E2E-13 closure

The E2E-13 PR exposed a stable Windows regression in the pre-existing E2E-07 causal USER Browser path. A same-head rerun reproduced the same failure: root `Page.windowOpen` matched the expected URL, but `chrome.tabs.Tab.openerTabId` did not provide the fresh opener relationship required by the acceptance contract. This was not classified as a one-off runner timing flake.

Two speculative production stabilizations were tried first—longer post-click observation and broader fresh tab enumeration. Neither established the missing opener proof, so both were reverted rather than kept as unrelated browser churn.

The fixture was also corrected to make its web-level contract explicit with `target="_blank" rel="opener"`; however that still did not make Chromium's extension Tabs metadata reliably expose `openerTabId` for this popup/new-window shape. The final narrow production repair therefore changes only the **proof source** for the already-required causal relationship: it uses the extension's existing `chrome.debugger` authority and fresh CDP `Target.getTargets` / `TargetInfo.openerId` evidence.

The final E2E-07 proof chain is:

- capture the exact authorized root CDP target ID and a fresh pre-click target baseline;
- dispatch the exact button click once;
- require exactly one matching root `Page.windowOpen` event;
- freshly enumerate CDP page targets and admit only a new target whose `openerId` equals the exact root target ID;
- map that exact child target to its tab identity using existing debugger target metadata;
- fresh re-read the same child target/opener relation again before deriving child authority;
- retain the existing exact child URL/title proof, task-scoped debugger authority, exact root authorization-generation preservation, return to the exact root, fresh root re-ground and child debugger detach requirements;
- fail closed on ambiguity, missing/mismatched opener evidence, target replacement, authorization drift or any post-click uncertainty;
- never blindly replay the possibly executed click.

No new extension permission was added and no causal safety condition was relaxed. This is a bounded repair to the pre-existing E2E-07 evidence source, not a new general popup framework and not an expansion of E2E-13's Desktop scope.

The separate bounded authorization helper remains test-only: at most three real extension shortcuts, each attempted only while fresh evidence says explicit tab authorization is absent. It does not bypass browser authorization.

## Safety boundary and non-claims

This is a narrow representative closure, not general Desktop automation completeness.

It does not claim:

- Desktop complete;
- arbitrary Windows application automation;
- general RPA;
- arbitrary rich-text/contenteditable/document editing;
- Microsoft Office automation;
- universal UIA support;
- Save As flows;
- clipboard or OCR authority;
- credential/password-field handling;
- arbitrary keyboard-shortcut automation;
- mutation of browser content through this path.

Browser processes, password fields, disabled/offscreen controls, missing ValuePattern, wrong process/HWND/control type, read-only mutation targets, stale RuntimeIds and ambiguous exact-name targets fail closed.

## Closure condition

The E2E-13 representative implementation is **VERIFIED NARROW / representative path closed** on open PR #252. The PR remains unmerged. Merge readiness is established only by the final live PR head after all applicable exact-head workflows—including E2E-13, E2E-15, the full Windows product-route suite including E2E-07, ZN CI and all other applicable PR workflows—finish successfully with no outstanding merge blocker.
