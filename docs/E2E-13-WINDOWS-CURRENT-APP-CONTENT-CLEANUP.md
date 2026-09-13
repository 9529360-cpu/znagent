# E2E-13 — Windows current-app bounded content cleanup

Status: **VERIFIED NARROW / representative path closed.**

Updated: 2026-09-13

Implementation PR: #252

Final PR head: `fd6a7a576d8e0dbc466f36e2633298de638d2eca`

Squash merge to canonical `main`: `cc3fd3edc25b436a5c42ec1e2d13d4b786fb18b3`

Post-merge canonical verification: ZN CI #1875 / run `34756719969` — completed / success.

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

Implementation PR #252 final head `fd6a7a576d8e0dbc466f36e2633298de638d2eca` passed all applicable exact-head workflows before merge. PR #252 was squash-merged to canonical `main` as `cc3fd3edc25b436a5c42ec1e2d13d4b786fb18b3`. The post-merge `main` push ZN CI #1875 / run `34756719969` completed successfully. This docs-only synchronization must use its own exact-head CI and does not reuse PR #252's checks.

## E2E-07 regression handling during E2E-13 closure

The E2E-13 PR exposed a stable Windows regression in the pre-existing E2E-07 causal USER Browser path. A zero-code same-head rerun reproduced the failure, so it was not classified as a one-off runner timing flake.

Two speculative production stabilizations were tried first—longer post-click observation and broader fresh tab enumeration. Neither established the missing causal proof, so both were reverted rather than kept as unrelated browser churn.

The fixture keeps `target="_blank" rel="opener"` to make the web-level intent explicit, but Chromium's extension Tabs metadata still did not reliably expose `chrome.tabs.Tab.openerTabId` for this popup/new-window shape.

A first narrow production repair tried to use the already attached root debugger session to call CDP `Target.getTargets` and prove `TargetInfo.openerId`. Bounded diagnostic evidence showed the actual first failure happened **before dispatch**: Edge returned `-32000 Not allowed` for `Target.getTargets`, and the action evidence recorded `click_sent=false`. The subsequent refusal to issue another click was the existing no-blind-replay guard, not the root cause.

The final narrow production repair therefore keeps the same causal safety contract without adding any extension permission and without using a CDP Target-domain discovery command. It uses the extension-level debugger target inventory that is actually allowed.

The final E2E-07 proof chain is:

- capture a fresh pre-click `chrome.debugger.getTargets()` snapshot, identify the exact authorized root debugger target and retain its target ID plus the full target-ID baseline;
- dispatch the exact button click once;
- require exactly one `Page.windowOpen` event from the exact root debugger session with the exact expected child URL;
- record tabs created only inside the bounded action window and fail closed if more than one new tab appears;
- freshly call `chrome.debugger.getTargets()` and require that the single created tab maps to exactly one new `page` target whose target ID was not present in the pre-click baseline and whose URL is the exact expected child URL;
- fresh re-read the exact root target ID/tab/URL and exact child target ID/tab/URL immediately before deriving task-scoped child authority;
- retain the existing exact child URL/title proof, root authorization-generation preservation, exact-root return, fresh root re-ground and child debugger detach requirements;
- fail closed on ambiguity, missing/mismatched target evidence, target replacement, authorization drift or any post-click uncertainty;
- never blindly replay a possibly executed click.

No `webNavigation` permission or other new extension permission was added. No causal/fresh-read/no-replay safety condition was relaxed. This is a bounded repair to the pre-existing E2E-07 evidence source, not a new general popup framework and not an expansion of E2E-13's Desktop scope.

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

The E2E-13 representative implementation remains **VERIFIED NARROW / representative path closed**. Implementation PR #252 final head `fd6a7a576d8e0dbc466f36e2633298de638d2eca` was squash-merged to canonical `main` as `cc3fd3edc25b436a5c42ec1e2d13d4b786fb18b3`, and post-merge ZN CI #1875 / run `34756719969` is completed / success. This representative closure is not `PRODUCT-CLOSED` and does not broaden any of the explicit non-claims above.
