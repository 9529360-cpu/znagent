# ZN Implementation Status

这是一份当前实现事实表，不是 roadmap。真实代码、真实 Git、真实测试和真实 E2E 高于本文件。

Updated: 2026-09-13

## 仓库状态规则

- 唯一长期集成 / canonical / release 分支：`main`。
- 新开发从最新 `main` 拉短命 `work/*`，PR 以 `main` 为 base；适用 CI/E2E 在 PR 阶段通过后再合并。
- `dev/zn-agent` 仅为历史兼容，不再接收新产品开发。
- 文档里的 SHA 和 CI run 只能当历史 evidence；接手时必须重新查询 current `main` 和 live PR head。
- Git/CI/main 合并属于工程证据，不等于产品能力自动闭环。

## 状态语言

```text
Exists
Connected
Verified
Product-closed
```

`VERIFIED NARROW` / `representative path closed` 表示真实代表性路径已经验证，但不代表整个 capability 类别已经 product-closed。

## 当前能力事实

| 区域 | 当前状态 | 当前边界 / 仍需扩大 |
| --- | --- | --- |
| Resident Self / Body / Senses / Situation / Thought / Will | CONNECTED + VERIFIED | 真实任务广度仍需扩大 |
| Durable Work / restart recovery | CONNECTED + VERIFIED | 更长周期、跨天和更多真实任务上的连续体验仍需扩大 |
| Research & Information Work | VERIFIED NARROW; E2E-01/02/03 representative paths closed | bounded public-web research + provenance/conflict/grounding/restart continuation；不是 arbitrary Deep Research |
| Uncertain outside-world side effects | VERIFIED NARROW; E2E-36 representative path closed | exact replay-sensitive attempt 跨 restart fail closed；不是通用 exactly-once |
| Work continuity / steering | VERIFIED NARROW; E2E-27/33/35 representative paths closed | 更广长期使用仍开放 |
| Managed Browser / BrowserScene | CONNECTED + VERIFIED NARROW | complex frames/dialogs/general keyboard/OCR/任意网页仍未覆盖 |
| User Browser Bridge | CONNECTED + VERIFIED NARROW | E2E-05/07/08 representative paths 已关闭；真实网站和更复杂认证/导航仍需扩大 |
| Local Documents & Spreadsheet Work | VERIFIED NARROW; E2E-09/10 representative paths closed | 复杂 Office structures 仍开放；不是 Word/Excel/Office complete |
| Browser -> Spreadsheet | VERIFIED NARROW; E2E-11 representative path closed; PR #251 merged as `5dbc663c7035dc523e34477501fee59914a8cff4` | MANAGED Browser simple-table -> exact XLSX append-copy；不是 arbitrary website/Excel |
| Document Research Completion | VERIFIED NARROW; E2E-12 representative path closed | bounded public-Web evidence -> 1–3 DOCX placeholders；不是 arbitrary DOCX/Deep Research/Word complete |
| Windows machine/application awareness | CONNECTED + VERIFIED NARROW | 更多应用/系统语义继续扩大 |
| **Windows current-app content cleanup** | **VERIFIED NARROW; E2E-13 representative path closed; PR #252 merged as `cc3fd3edc25b436a5c42ec1e2d13d4b786fb18b3`** | current foreground non-browser process/HWND + unique multiline ValuePattern Edit + deterministic cleanup + guarded replacement + restart/no-replay reconciliation + one Save + fresh same-process read-only result verification；不是 Desktop complete / arbitrary app automation / Office / general RPA |
| Windows unexpected-modal recovery | VERIFIED NARROW; E2E-15 representative path closed | exact same-process safe-modal slice；任意 dialog/UAC/credentials/business decisions 不在 closure 内 |
| Browser + File + Desktop | VERIFIED NARROW; E2E-24 representative path closed | bounded three-surface path；更复杂任务仍需扩大 |
| Cognitive resources / routing | CONNECTED + VERIFIED | one ModelRouter, hard eligibility, route provenance, health-aware scoring；多-provider breadth继续扩大 |
| Delegated Work / WorkerRun lifecycle | CONNECTED + VERIFIED NARROW | bounded delegation/supervision/restart/readiness；不是 general scheduler / recursive orchestration |
| Long-task supervision | VERIFIED NARROW; E2E-28/34 representative paths closed | 更长、更复杂任务仍需扩大 |
| One-model multi-worker | VERIFIED; E2E-29 CLOSED | 一个实际 route 服务多个隔离 WorkerRun 已证明 |
| Delegated user progress | CONNECTED + VERIFIED NARROW / PARTIAL UX | 复杂 multi-workstream UX/解释质量继续扩大 |
| WorkItem dependency/readiness | CONNECTED + VERIFIED NARROW | bounded flat current-plan sibling graph；不是 general DAG scheduler |
| Memory / learned behavior | VERIFIED NARROW / PARTIAL | E2E-37/38/39 representative slice；不是 arbitrary workflow learning |
| Installed N -> N+1 continuity | PARTIAL / OPEN | 真实升级中的 identity/data/Work/uncertain effects 尚未 product-close |

## E2E-13 implementation facts

Representative natural-language task:

> 把我现在开的工作记录整理一下：去掉每行前后空格，删掉空行，重复内容只保留第一次，然后保存。

Implementation PR #252 final head was `fd6a7a576d8e0dbc466f36e2633298de638d2eca`. It was squash-merged to canonical `main` as `cc3fd3edc25b436a5c42ec1e2d13d4b786fb18b3`. Post-merge canonical ZN CI #1875 / run `34756719969` completed successfully.

The merged implementation reuses the existing Product Resident / Root Work / Body. No DesktopAgent, AppAgent, DialogAgent, second Router/Store or RPA engine was introduced.

### Goal / transform

`current_app_text_cleanup_goal.py` defines the bounded foreground-desktop text-cleanup goal. The representative transform is deterministic:

```text
split lines
-> trim each line
-> drop blank lines
-> stable exact dedupe
-> join CRLF
```

Source/result are bounded to 4096 characters and empty output fails closed.

### UIA content authority

`automation_text_content.py` provides the bounded native UIA ValuePattern read/replace seam. The mutation requires:

- current foreground non-browser process/HWND；
- exactly one named multiline Edit；
- enabled / onscreen / not password / writable ValuePattern；
- fresh process/HWND/name/control type/RuntimeId checks；
- current source chars/SHA-256 match；
- reacquisition immediately before `SetValue`；
- fresh reread after dispatch。

Raw application text is transient. Durable audit/state stores bounded semantic identity, counts and hashes only.

### Durable replacement ownership / crash-window repair

`CurrentAppTextAwareBody` keeps `automation_value_replace` inside the existing side-effect attempt journal. E2E-13 does **not** assume `ValuePattern.SetValue` is idempotent.

The restart repair closes the crash window where outside-world text may already equal result R but WorkingState still reflects source S. Before ordinary source-content drift is considered, the E2E-13 behavior queries durable replacement ownership by current event + action kind. Attempts in `started`, `observed`, or `verified_effect` remain authoritative across restart even if fresh content would form different replacement arguments/signature.

Recovery is observation-only:

```text
existing replacement attempt owns dispatch boundary
-> fresh exact foreground/process/window/Edit bind
-> fresh ValuePattern read
-> compare prior expected result chars/SHA-256
-> exact match: resolve/retain old attempt as verified_effect
-> continue with fresh replacement verification

mismatch / lost authority / ambiguity
-> fail closed
-> no new replacement signature
-> no additional SetValue
```

This also closes the second crash window after `verified_effect` is persisted but before WorkingState advances.

Persistent SQLite + Resident rebuild regressions cover:

- durable `started` + outside-world value already changed;
- Body `observed` before WorkingState checkpoint;
- `verified_effect` persisted before WorkingState stage advances;
- mismatch after restart / user edit;
- zero additional `automation_value_replace` dispatch on recovery.

### Save / final verification

Save reuses the existing durable pointer-click lifecycle. The exact Save Button is freshly revalidated immediately before input. Once a Save dispatch crosses its non-replayable boundary, E2E-13 never clicks Save again.

Final success discards old HWND/RuntimeIds and requires:

- same expected process identity；
- fresh replacement HWND；
- saved-semantics title；
- exact read-only Edit `保存内容`；
- result chars/SHA-256 equal the deterministic expected value；
- independent Root Work acceptance。

## E2E-07 Windows regression handling

PR #252's Windows suite exposed an E2E-07 failure. A zero-code same-head rerun reproduced the same failure, so it was treated as a stable regression rather than runner/browser timing variance.

Two speculative production stabilizations were reviewed and reverted because neither established the missing causal proof:

- extending the post-click observation window；
- broadly re-enumerating candidate tabs after the action。

The representative fixture keeps `target="_blank" rel="opener"` so the web-level intent is explicit, but Chromium's extension Tabs metadata still did not reliably expose `chrome.tabs.Tab.openerTabId` for this popup/new-window shape.

A first narrow repair tried to read CDP `Target.getTargets` / `TargetInfo.openerId` through the already attached root debugger session. Bounded diagnostic evidence then exposed the real first failure: **before any click was sent**, Edge returned CDP `-32000 Not allowed` for `Target.getTargets`, with action evidence `click_sent=false`. The later refusal to issue another click was the existing no-blind-replay guard doing its job; it was not the root cause.

The final narrow repair therefore does not add permissions and does not use a Target-domain discovery command. Its causal proof path is:

- fresh extension-level `chrome.debugger.getTargets()` snapshot identifies the exact authorized root debugger target and records a pre-click target-ID baseline；
- one exact button click is dispatched；
- the exact root debugger session must emit exactly one `Page.windowOpen` event with the expected child URL；
- the bounded action window records created tabs and rejects more than one new tab as ambiguous；
- a fresh `chrome.debugger.getTargets()` reread must map that single created tab to exactly one new `page` target whose target ID was absent from the pre-click baseline and whose URL equals the exact expected child URL；
- immediately before deriving child authority, another fresh debugger-target reread must prove the exact root target ID/tab/URL and exact child target ID/tab/URL are unchanged；
- existing task-scoped child debugger authority, exact child URL/title verification, root authorization-generation preservation, return to the exact root, fresh root re-ground and child detach requirements remain mandatory；
- ambiguity, missing/mismatched evidence, target replacement, authorization drift or any post-click uncertainty fails closed and never causes a blind click replay。

No `webNavigation` permission or other new extension permission was added. The causal child/root contract, fresh reread requirement and no-blind-replay policy were not weakened.

The separate authorization setup helper remains test-only and bounded: at most three real extension shortcuts, each only while fresh evidence proves explicit authorization is absent.

## Browser / Windows current boundary

Browser verified-narrow substrate includes BrowserScene sensing, tab/history, exact scene actions, causal popup attribution, file transfer and bounded command/control clicks. It is not arbitrary web automation.

Windows verified-narrow substrate now includes machine/application awareness, exact existing-window activation, E2E-13 current-app cleanup and E2E-15 same-process modal recovery. It is not arbitrary Windows application lifecycle, arbitrary dialog automation or general RPA.

## Current remaining product gaps

1. Research breadth beyond E2E-01/02/03/12.
2. Local Office breadth beyond E2E-09/10/11/12.
3. Cross-surface real tasks beyond E2E-24 and the bounded E2E-13 current-app slice.
4. Browser/User Browser breadth on real sites, complex frames/navigation/popups/user-presence boundaries.
5. Long-horizon/multi-workstream UX on top of existing continuity/supervision substrate.
6. Windows/application breadth beyond E2E-13 and E2E-15, driven by concrete real E2E failures.
7. Installed-version continuity only when explicitly authorized as a product problem.

## Do not misread as complete

Current implementation does **not** mean:

- Desktop complete；
- arbitrary Windows application automation；
- general RPA；
- arbitrary rich-text/document editing；
- arbitrary Windows dialog recovery；
- Word complete / Excel complete / Office Suite complete；
- arbitrary web automation；
- all MFA；
- arbitrary third-party exactly-once；
- full DLP / OS sandbox；
- general multi-agent platform or general DAG scheduler；
- all long-running/cross-day work solved；
- two real provider families fully production-validated；
- Memory/credential/installer/updater/release-trust granted expanded authority。

## Closure truth

E2E-13 status is **VERIFIED NARROW / representative path closed**. Implementation PR #252 final head `fd6a7a576d8e0dbc466f36e2633298de638d2eca` was squash-merged to canonical `main` as `cc3fd3edc25b436a5c42ec1e2d13d4b786fb18b3`. The post-merge `main` push ZN CI #1875 / run `34756719969` is completed / success.

This status remains a narrow representative closure, not `PRODUCT-CLOSED`. Any later docs-only synchronization PR must be judged from its own live head and applicable exact-head CI; PR #252's old checks are historical implementation evidence only.
