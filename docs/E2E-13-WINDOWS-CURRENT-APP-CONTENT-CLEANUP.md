# E2E-13 — Windows current-app bounded content cleanup

Status: VERIFIED NARROW representative path on draft PR #252; not yet merged to `main`.

Updated: 2026-09-12

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

If the Edit RuntimeId changes, old evidence is discarded and the source is freshly reread/retransformed before any mutation. If source content drifts, the stale transform is rejected and recomputed from fresh content. Ambiguous same-name Edits fail before mutation.

After `SetValue`, the target is freshly reacquired and reread. If dispatch outcome is uncertain, the implementation resolves only through a fresh exact readback; it never blindly replays the replacement.

Save uses the existing pointer-click durable lifecycle. The exact Save Button is freshly reacquired immediately before input, and after a pointer dispatch the implementation never clicks Save again. Final verification is observation-only.

## Privacy boundary

Raw current-app source and replacement text are transient only.

Durable WorkingState, audit data and Body history retain only bounded semantic/provenance metadata such as control names, HWND/PID/process identity, RuntimeIds where needed for authority, character/line counts, removal counts and SHA-256 digests. `replacement_text` is stripped from durable Body action history and replaced with redaction metadata. Raw source/result content is not sent to a model.

## Real Windows acceptance

On head `2968c203566d92601ab66f44ae985cefc3383f33`, the dedicated E2E-13 step in Windows Interactive CI passed all five scenarios:

- happy path: real WinForms ValuePattern cleanup, exactly one Save, fresh result-window readback, Root Work completion;
- stale Edit RuntimeId: stale authority rejected and freshly regrounded before mutation;
- source content drift: stale transform rejected and recomputed before mutation;
- ambiguous same-name Edit: zero mutation and zero Save;
- final application mismatch: Save occurs once, but final verification fails and Root Work does not complete.

The same head also passed ZN CI, Managed Browser E2E, Memory/Learned Behavior E2E, Research and Information Work E2E, Local Documents/Spreadsheet Work E2E, and Document Research Completion E2E. The Windows workflow later failed only in an existing E2E-07 browser-extension authorization setup race after E2E-13 and E2E-15 had already passed. That test now uses the repository's existing bounded explicit-shortcut retry pattern: at most three real shortcuts, each attempted only while fresh evidence proves authorization is still absent; no authorization bypass is introduced.

The current draft head also includes workflow path coverage for the E2E-13 completion owner, security tests, real WinForms fixture, and the E2E-07 test touched by that stabilization. Final merge-readiness evidence must be bound to the eventual final PR head, not to an earlier green SHA.

## Safety boundary and non-claims

This is a narrow representative closure, not general Desktop automation completeness.

It does not claim:

- arbitrary Windows application automation;
- arbitrary rich-text/contenteditable/document editing;
- Microsoft Office automation;
- universal UIA support;
- generic RPA macros;
- Save As flows;
- clipboard or OCR authority;
- credential/password-field handling;
- arbitrary keyboard-shortcut automation;
- mutation of browser content through this path.

Browser processes, password fields, disabled/offscreen controls, missing ValuePattern, wrong process/HWND/control type, read-only mutation targets, stale RuntimeIds and ambiguous exact-name targets fail closed.

## Closure condition

The representative implementation is complete on draft PR #252. The PR must remain unmerged until the eventual final head has passed all applicable exact-head CI and GitHub still reports no merge blocker.
