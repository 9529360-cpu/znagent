# ZN Product Capability Map

> 这是一份产品能力地图，不是 feature checklist。
>
> 真实代码、真实 Git、真实测试和真实 E2E 高于本文件。

Updated: 2026-09-13

## 1. 产品判断标准

ZN 的目标不是拥有最多 capability，而是让普通用户用正常语言交代事情以后，ZN 能长期、连续、可靠地把事情办完。

能力成熟度统一按下面判断：

```text
Exists
-> Connected
-> Verified
-> Product-closed
```

`VERIFIED NARROW` / `representative path closed` 不等于整个 capability 类别 product-closed。

## 2. Resident / continuity

| Product need | Current status | Remaining gap |
| --- | --- | --- |
| Persistent Self / identity | VERIFIED / PARTIAL product closure | 安装、升级、恢复后的长期连续性继续验证 |
| Resident long-lived process | VERIFIED | 更长时间真实运行场景 |
| Situation / Thought / Will loop | CONNECTED + VERIFIED | 更通用 investigation / cross-surface replanning |
| Durable Work | CONNECTED + VERIFIED | 更长周期、更多真实任务的 continuation breadth |
| Natural continuation / active steering | VERIFIED NARROW; E2E-27/33/35 representative paths closed | 跨天、更复杂长期任务与多 workstream 用户体验 |
| Memory / learned context | VERIFIED NARROW / PARTIAL product closure | representative learned-behavior slice 已有；更广长期体验仍开放 |
| Local Resident control plane | GUARDED / TRANSITIONAL | loopback TCP + per-process secret + endpoint ACL；长期 Windows transport 可继续收敛，但不是默认主线 |

## 3. Task ownership / delegation / routing

| Product need | Current status | Remaining gap |
| --- | --- | --- |
| ZN remains root task owner | VERIFIED NARROW | 在更多真实任务、跨 surface/长期使用中扩大证据 |
| Durable Work thread/item/run/artifact | CONNECTED + VERIFIED | 更广任务与 UX；不是缺 dependency substrate |
| Active user steering | VERIFIED NARROW | representative real same-Work steering/continuation 已关闭；更广长期使用继续扩大 |
| Delegation admission | CONNECTED + VERIFIED NARROW | 更多任务上验证 direct/delegated 判断 |
| Delegated coordinator | CONNECTED + VERIFIED NARROW | 现有 bounded supervision/readiness 上扩大真实任务；不是 general orchestrator |
| Delegated WorkerRun lifecycle | CONNECTED + VERIFIED NARROW | queued/running/completed/failed/stale、progress、bounded retry/reassign/reconcile 已有；通用无限期 scheduler 不在声明内 |
| One-model multi-worker | VERIFIED / E2E-29 CLOSED | 不再是设计缺口 |
| Multiple ModelRoute support | CONNECTED + VERIFIED NARROW | E2E-30/42 已按 current acceptance policy 关闭；双真实 provider family evidence 仍受 environment waiver 限定 |
| Kernel-owned ModelRouter | CONNECTED + VERIFIED NARROW | hard eligibility + dynamic health-aware routing 已接通；扩大 provider/task coverage |
| Dynamic provider health routing | VERIFIED NARROW; E2E-28/34 representative paths closed | 更多 provider failure/长时运行 coverage |
| Strict WorkerContextPack | CONNECTED + VERIFIED NARROW | 未来 worker 类型继续审计；不是完整 DLP |
| Worker action authority | CONNECTED + VERIFIED NARROW | Body action admission，不是 OS process sandbox |
| Worker completion verification | VERIFIED NARROW | worker `done` 仍只是 candidate；Root completion 由 ZN 独立验收 |
| Stale delegated result protection | VERIFIED NARROW | 更多任务继续覆盖 |
| Stall/no-progress supervision | VERIFIED NARROW; E2E-28/34 representative paths closed | 更广长任务继续扩大 |
| Flat dependency/readiness | CONNECTED + VERIFIED NARROW | bounded same-Root/thread/current-plan sibling dependency、fan-in、restart durability、invalid graph fail closed；不是 general DAG |
| Delegated user progress | CONNECTED + VERIFIED NARROW / PARTIAL UX | privacy-safe projection 到既有 `work_progress` + Resident UI；复杂 multi-workstream UX 继续扩大 |

核心规则：**不要新建第二套 ModelRouter、第二套 Work/progress truth，也不要新建 Orchestrator Agent。**

## 4. Browser / User Browser

| Product need | Current status | Remaining gap |
| --- | --- | --- |
| Bounded BrowserScene sensing | VERIFIED NARROW | 更复杂 frame/site/layout coverage |
| Tab lifecycle/history | VERIFIED NARROW | 更复杂 real-site topology/navigation |
| Exact BrowserScene actions | VERIFIED NARROW | 当前 focus/type/check/uncheck/navigation + bounded command/control clicks；更多 semantic controls 继续扩大 |
| Managed causal popup | VERIFIED NARROW | bounded exact causal popup path 已有；任意 popup/site complexity 仍开放 |
| Browser file transfer | VERIFIED NARROW | exact authority-safe managed upload/download 已有；USER-plane file transfer 仍 fail closed |
| User Browser Bridge | CONNECTED + VERIFIED NARROW | 真实已登录网站覆盖、授权 UX、漂移后的 stable re-ground |
| E2E-05 authenticated research mutation | CLOSED representative path | 不等于任意 authenticated site |
| E2E-07 causal USER child-tab | CLOSED representative path | exact-root causal popup attribution + bounded child authority；general arbitrary popup/frame complexity 仍开放 |
| E2E-08 OTP user presence | CLOSED representative path | 仅 standard HTML `one-time-code` same tab/generation/origin；不是所有 MFA |
| Sensitive-field protection | GUARDED | 继续 fail closed；不复制 user profile/cookie/password/OTP secret |

PR #252 暴露的 E2E-07 回归是稳定可复现的 causal-proof 缺失，不是一次性 runner timing。两笔“加长等待 / 扩大 tab 枚举”的 speculative production stabilization 都未建立证明，已撤回。fixture 保留 `target="_blank" rel="opener"` 以明确 web-level 意图，但 Chromium 的扩展 Tabs 元数据在该 popup/new-window 形态仍不稳定暴露 `openerTabId`。第一次窄修尝试通过已附着的 root debugger 调 CDP `Target.getTargets` / `TargetInfo.openerId`；诊断 E2E 证明真实首错发生在点击前：Edge 返回 `-32000 Not allowed`，`click_sent=false`，后续 no-blind-replay 只是安全保护。最终窄修不新增 extension permission，也不再使用 CDP Target-domain discovery：点击前用 extension-level `chrome.debugger.getTargets()` 绑定 exact root target 并记录 target-ID baseline；点击后要求 exact-root `Page.windowOpen` 的 exact URL、action window 内仅一个新 tab、fresh debugger-target reread 将该 tab 唯一绑定到 baseline 之外且 exact-URL 的新 page target；派生 child authority 前再次 fresh reread exact root/child target ID、tab 与 URL。root authorization generation、child URL/title、exact-root return、fresh re-ground 与 no-blind-replay 均保持严格，歧义或并发新 tab 直接 fail closed。

E2E-08 明确不支持 CAPTCHA solving、WebAuthn/passkey automation、cross-origin IdP handoff、password automation、payment-field automation。

## 5. Windows / desktop computer use

| Product need | Current status | Remaining gap |
| --- | --- | --- |
| Machine/application awareness | CONNECTED + VERIFIED NARROW | 更多应用/系统语义继续扩大 |
| Identity-bound application launch | VERIFIED NARROW | 更多 app families/edge cases |
| Existing application activation | VERIFIED NARROW | Resident-admitted exact app/HWND/PID、fresh foreground proof 已有；任意多窗口拓扑/生命周期未闭环 |
| Foreground / focused-control sensing | VERIFIED | 更复杂窗口切换和应用生命周期 |
| Pointer / keyboard / text entry | VERIFIED NARROW | 完整真实任务继续验证 |
| Semantic desktop target re-ground | VERIFIED NARROW | 控件变化、窗口漂移、替代入口 |
| E2E-13 current-app content cleanup | **VERIFIED NARROW / representative path closed on open PR #252** | exact foreground non-browser HWND/PID + unique multiline ValuePattern Edit + deterministic trim/drop-blank/stable-dedupe + guarded replacement + durable restart/no-replay reconciliation + one Save + fresh same-process read-only result verification；不是 Desktop complete / arbitrary app automation / Office / general RPA |
| E2E-15 unexpected modal recovery | VERIFIED NARROW / representative path closed | exact same-process directly owned UIA modal + one safe defer/continue action + fresh parent readiness/re-ground；任意 dialog/UAC/credentials/business decisions 不在 closure 内 |
| Cross-app task execution | VERIFIED NARROW; E2E-24 representative path closed | bounded USER Browser -> exact File -> exact Desktop customer record 已有；更复杂联合任务仍开放 |

### E2E-13 exact boundary

Representative user request:

> 把我现在开的工作记录整理一下：去掉每行前后空格，删掉空行，重复内容只保留第一次，然后保存。

Product-real scope on PR #252:

- same Product Resident / Root Work / Body；
- fresh current foreground non-browser process/HWND；
- unique exact multiline UIA Edit with ValuePattern；
- bounded raw read, raw text transient only；
- deterministic trim -> drop blank -> stable exact dedupe -> CRLF；
- fresh RuntimeId/process/HWND/source hash validation immediately before replacement；
- existing durable side-effect journal around `automation_value_replace`；
- after restart, prior `started` / `observed` / `verified_effect` replacement attempt is reconciled by event + kind **before** ordinary content drift；
- recovery is read-only: fresh exact readback must prove the prior expected-result chars/SHA-256; otherwise fail closed；
- changed current text cannot create a new action signature that bypasses old dispatch ownership；
- Save uses existing pointer lifecycle and is dispatched at most once；
- completion requires fresh same-process replacement HWND and exact read-only `保存内容` chars/SHA-256 verification。

Persistent SQLite + Resident rebuild tests cover started crash, observed-before-WorkingState checkpoint, a second crash after `verified_effect` reconciliation before WorkingState advances, and mismatch/no-new-signature behavior.

Explicit non-claims: no Desktop complete, arbitrary Windows app automation, arbitrary rich text, Office automation, universal UIA, clipboard/OCR authority, Save As, arbitrary keyboard shortcut automation or general RPA.

## 6. Files / workspace / terminal / Git

| Product need | Current status | Remaining gap |
| --- | --- | --- |
| File read/write/search | CONNECTED + VERIFIED NARROW | 模糊来源、复杂整理、多文件任务 |
| Workspace evidence / exact source identity | PARTIAL | 歧义来源先解决身份再允许外部副作用 |
| Local DOCX edit | VERIFIED NARROW; E2E-09 representative path closed | 更复杂 DOCX/package/任意 Word 编辑仍开放 |
| Local XLSX cleanup | VERIFIED NARROW; E2E-10 representative path closed | 公式/表/图表/pivot/复杂 Excel 仍开放 |
| Browser -> XLSX | VERIFIED NARROW; E2E-11 representative path on PR #251 | bounded MANAGED Browser simple table -> exact append-copy；不是 arbitrary website/Excel |
| Evidence -> DOCX completion | VERIFIED NARROW; E2E-12 representative path closed | bounded 1–3 placeholder path；不是 arbitrary DOCX/Word/Deep Research |
| Terminal/process | VERIFIED | 继续作为真实任务执行资源 |
| Git / repo task support | PARTIAL | 普通项目能力发展；不给 ZN 自身仓库特殊权限 |
| Coding specialist + real tools | VERIFIED NARROW | 扩大真实 repo 场景 |

## 7. Multi-surface and long-task real work

当前已有多条代表性组合闭环，但下一阶段重点是扩大完整真实任务，而不是继续证明单动作：

```text
normal human goal
-> Root Work
-> Sense current computer state
-> Situation / Thought
-> direct work OR bounded SubWork
-> policy-eligible cognition + tools + authority
-> action / WorkerRun
-> fresh observation
-> accept / reject / replan / reroute / steer
-> independent root completion evidence
-> durable continuation
```

E2E-24 已关闭一个 bounded 三-surface representative path。E2E-13 又关闭了一个 bounded “继续处理当前 Windows app 内容”的代表性路径，但它不等于 arbitrary cross-surface automation 或 general RPA。

## 8. Recovery / non-replay

| Product need | Current status | Remaining gap |
| --- | --- | --- |
| Resident restart recovery | CONNECTED + VERIFIED NARROW | 更多跨天/复杂真实 Work breadth |
| Delegated restart reconciliation | VERIFIED NARROW; E2E-28/34 | 更广任务继续覆盖 |
| Unknown external-effect handling | VERIFIED NARROW; E2E-36 representative path closed | exact replay-sensitive attempt 跨 restart 保持 fail closed；不是通用 exactly-once |
| E2E-13 ValuePattern replacement recovery | VERIFIED NARROW on PR #252 | old replacement dispatch ownership survives restart/signature drift; fresh readback can prove old expected effect, otherwise fail closed; no blind SetValue replay |
| Fresh evidence before mutation | CORE RULE | 扩展到所有新任务和 delegated result acceptance |
| Independent completion verification | VERIFIED NARROW | 复杂 Work 继续覆盖 |
| Stale delegated result protection | VERIFIED NARROW | steering/restart/reassign breadth |

Recovery 是为了让真实任务继续，不是独立产品路线。

## 9. Product UX

| Product need | Current status | Remaining gap |
| --- | --- | --- |
| User-visible root task progress | PARTIAL | 更清晰的已完成/进行中/等待/阻塞/依据 |
| Delegated progress | CONNECTED + VERIFIED NARROW / PARTIAL UX | 复杂 multi-workstream UX/解释质量继续扩大 |
| Permission / revoke UX | PARTIAL / OPEN | Browser、敏感操作、外部副作用授权范围 |
| Model/privacy policy UX | PARTIAL | 用户配置、解释与更广多-provider体验继续扩大 |
| Failure explanation | PARTIAL | 说明遇到什么、是否还能继续、需要用户做什么 |
| Completion result | PARTIAL | 明确完成了什么、没完成什么、依据是什么 |

用户不应该需要理解 worker_run_id、provider RPC、route-score 或 recovery internals。

## 10. Real E2E acceptance set

`docs/ZN-REAL-TASK-E2E-CATALOG.md` 保持 50 个原始真实任务定义。当前代表性 closure 包括：

- E2E-01/02/03 Research & Information Work；
- E2E-05 authenticated research/mutation；
- E2E-07 causal USER child-tab；
- E2E-08 OTP user presence；
- E2E-09/10 Local Documents & Spreadsheet；
- E2E-11 Browser -> Spreadsheet（PR #251，unmerged）；
- E2E-12 evidence-driven DOCX completion；
- **E2E-13 current-app content cleanup（PR #252，`VERIFIED NARROW / representative path closed`, unmerged）**；
- E2E-15 bounded unexpected-modal recovery；
- E2E-24 Browser + File + Desktop；
- E2E-27/33 steering/continuation；
- E2E-28/34 supervision/restart；
- E2E-29 one-route multi-worker；
- E2E-30/42 current-policy closure with environment waiver；
- E2E-35 next-day status-first continuation；
- E2E-36 uncertain-side-effect restart resolution；
- E2E-37/38/39 Memory & Learned Behavior representative slice。

这些 closure 不等于 50 个 E2E 全部完成，也不等于上述 capability classes 全部 product-closed。

## 11. Release / update continuity

Installed N -> N+1 的 identity/data/Work/uncertain-effect continuity 仍是独立未闭环问题；涉及 updater/rollback/signing/release trust 时必须保留高风险授权边界。

## 12. 已废弃：专用自我维护系统

专用“自我维护 / 自我修复 / upstream BUG report”路线已经删除。不要恢复 maintenance runtime/cognition/repair、BUG-report transport/intake、maintenance UI/RPC 或特殊 Git 权限路径。

## 13. 当前产品选择原则

不要重复开发已经关闭的 bounded substrate。下一项应从真实剩余产品缺口中选择：

1. E2E-24 / E2E-13 bounded closure 之外更复杂的 cross-surface / desktop real tasks；
2. Browser/User Browser 在真实站点和复杂 frame/dialog/navigation/用户在场边界的广度；
3. E2E-01/02/03/12 之外的 Research breadth；
4. E2E-09/10/11/12 之外的 Local Office breadth；
5. 现有 supervision/steering/restart 基础上的跨天/长期 continuity + progress/explanation UX；
6. E2E-13/E2E-15 之外由真实 E2E 暴露的 Windows/application semantic gap；
7. 只有 owner 明确选择并授权时才进入高风险 installed-version continuity / release-trust work。

如果 current evidence 不能确定唯一下一任务，就保留选择标准，不凭空发明 roadmap。

## 14. 最终判断

**一个普通用户不学习 ZN 内部结构，只用正常语言告诉它事情，它现在比以前多能独立、连续、可靠地完成哪些真实任务？**

对长任务再问：**当用户中途改方向、worker/model/tool 失败、Resident 重启或任务跨天时，ZN 是否仍能在 current evidence 下盯住同一个目标继续办？**

如果答案没有明显改善，就不能把“更多模型、更多 worker、更多调度代码”当成产品主线已经推进。

## E2E-13 closure note

Status: **VERIFIED NARROW / representative path closed on open PR #252; not merged to canonical `main`.**

PR #252 contains one narrow E2E-07 production repair required by the stable regression. The failed intermediate `Target.getTargets` approach is not the final implementation: bounded diagnostics proved Edge rejected that command before any click with `-32000 Not allowed` and `click_sent=false`. The final repair uses exact-root `Page.windowOpen` plus extension-level `chrome.debugger.getTargets()` pre-click target baselining, one action-window-created tab, unique fresh new page-target binding, and a fresh root/child identity+URL reread before child authority. More than one created tab or any ambiguity fails closed. The speculative wait/enumeration stabilizations were removed, no new permission was added, and the causal/fresh-read/no-replay acceptance contract remains strict. The final merge-readiness authority is the live final PR head and its applicable exact-head CI; documentation deliberately does not hard-code a self-referential final SHA before those checks finish.
