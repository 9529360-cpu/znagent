# ZN Next Phase

这份文件只描述 current `main` 之后的产品选择原则和剩余产品缺口。它不给 updater、rollback、signing、release trust、credential、identity、installer 或 long-term memory 的高风险改动自动授权。

Updated: 2026-09-11

## 当前已关闭的 delegated baseline

2026-09-06～2026-09-11 已经形成一组代表性 closure；下一阶段不得重复把它们当“尚未开发”的默认主线。

已关闭的代表性 baseline：

- **E2E-01 / E2E-02 / E2E-03 Research & Information Work**：普通自然语言 public-web research 已有 bounded representative closure：existing `WebResource` search→extract、多源 source identity/provenance/freshness、冲突保留、claim-to-evidence grounding、同 Work durable continuation/restart，以及唯一 attached workspace 下的可编辑 Markdown fresh reread/identity verification。该 closure 是 `VERIFIED NARROW`，不等于 arbitrary-internet Deep Research、authenticated-browser research、任意 PDF/Office authoring、general citation engine、knowledge graph/vector DB 或 recursive research swarm。
- **E2E-09 / E2E-10 Local Documents & Spreadsheet Work**：真实 DOCX payment-date edit 与 zero-model XLSX exact-dedup/amount-format cleanup 已有 bounded representative closure；source authority/identity、ambiguity fail-closed、新输出文件和 reopen verification 已验证。实现 PR #248 squash merge 为 `22a0537ffe082a695355da42fde9a09d576916a8`。这不是 Word complete、Excel complete 或 Office Suite complete。
- **E2E-12 Document Research Completion**：普通自然语言“把这个方案补完整，不确定的地方你自己查资料，但别乱编。”已有 bounded representative closure：只处理 exact attached workspace 内一个真实 DOCX 的 1–3 个显式 `【待补充：...】`，复用 existing `WebResource` search→extract 与同一 Product Resident / Work / Body；search snippet 仅作 discovery，成功 extracted source-document 才能进入 evidence。retrieved content 先经过 deterministic instruction-like prompt-injection source screening；每个 replacement 在 mutation 前要求至少两个独立 prompt-safe extracted sources 的一致 exact-quote/anchor 支持，并由本地 target-relevant price/date/percentage consistency gate 检测模型漏报的 source conflict。unknown、conflict、unsafe source、unsupported support、source drift、output collision 均 all-or-nothing fail closed；成功只写新 DOCX copy，源文件不变，并 fresh reopen 验证 target、identity、非目标文本与 run formatting。PR #250 implementation exact-head `65d5ec40f705f4e6e4c624b4a3287f27a949d8dc` 的 Document Research Completion E2E #5、ZN CI #1804、Research #34、Local Documents #17、Windows Interactive #378、Memory #61 全部 success。准确状态是 `VERIFIED NARROW / CLOSED representative path`，不是 arbitrary DOCX completion、arbitrary Deep Research、general prompt-injection solution 或完整 Word/Office 自动化。
- **E2E-29**：一个实际 model route 服务多个隔离 WorkerRun；worker 数与模型数不绑定，Root completion 仍由 ZN 独立验收。
- **E2E-30 / E2E-42**：durable route/privacy policy、ModelRouter hard eligibility、route/provider provenance 与 guarded multiroute acceptance 已按当前 acceptance policy 关闭。closure 包含明确的 owner-approved environment waiver，因为当时缺少第二个真实 provider family；不能宣称已有双真实 provider family 完整生产证据。
- **E2E-28 / E2E-34**：durable worker progress supervision、heartbeat/no-progress/stall detection、dynamic health-aware routing、bounded retry、policy-safe fallback/reassignment、restart reconciliation、no-replay recovery 已有 guarded real-model representative closure。
- **E2E-27 / E2E-33**：natural-language same-Work steering、current-plan replan、plan-version stale gating、old-worker result protection、restart continuation、completed historical effects 不 replay 已有真实 representative closure。
- **E2E-35**：`昨天那个产品继续，先看看做到哪了。` 的 bounded status-first continuation 已验证：同一 WorkThread/Root/current plan/Resident event，durable goal/plan/completed/blocked/artifact/delegation projection，fresh read-only workspace/Git/artifact observation，zero model/WorkerRun/new-event/WorkItem-plan mutation，drift detection，以及 inspection 后同一 active Work 的 bare continue。
- **Delegated progress**：durable delegated facts 已 privacy-safe bounded projection 到既有 `work_progress` 和 Resident UI，没有第二套 progress truth。
- **Dependency/readiness**：durable bounded flat current-plan sibling dependency/readiness 已实现并验证，包括 fan-in、restart durability 与 corrupt/cyclic/dangling fail closed。

这些 closure 证明当前 bounded substrate 已经存在，但不把 ZN 升格为通用 multi-agent platform、general DAG scheduler、无限期后台任务系统、通用 Deep Research 平台或完整 Office 自动化套件。

## Browser / Windows 已有的代表性 baseline

Current `main` 还已经拥有一批近期真实 Body 能力：

- E2E-05 USER Browser authenticated research -> persisted mutation；
- E2E-07 causal USER Browser child-tab attribution / popup / return path；
- E2E-08 standard HTML `autocomplete="one-time-code"` same-authorized-tab user-presence handoff；
- **E2E-15 bounded Windows unexpected-modal recovery**：同一 Resident / 同一 Work 内，fresh exact parent/modal/button authority、唯一安全 defer/continue action、单次 side effect、modal disappearance、parent readiness、旧 UIA RuntimeId 失效与 fresh re-ground 已在真实 WinForms `ShowDialog()` 路径验证；
- bounded BrowserScene sensing；
- tab lifecycle/history；
- exact BrowserScene actions；
- managed causal popup attribution；
- authority-safe causal upload/download；
- verified stateless/stateful control clicks；
- Windows Machine Capability / Application Awareness V1；
- exact Resident-admitted existing application window activation。

这些都只代表 bounded verified paths。特别是：E2E-08 不是“所有 MFA”；E2E-15 不是“任意 Windows dialog 自动处理”；Browser Body V2 不是“任意网页”；Windows application awareness 不是“所有 Windows 操作”。

## 下一阶段产品目标

ZN 的下一阶段不再是“把 delegated Work 基础补齐”，也不再是“补一个 ResearchAgent”或“从头补 Office 基础”。现在更重要的是：把已经存在的 Self、Body、Senses、Situation、Thought、Will、Work、Memory、Research/Web、Browser、Desktop、File、DOCX/XLSX、Terminal、Git、Recovery 和 CognitiveResources 组合到更多普通用户真实任务里，并扩大持续性、跨 surface、研究/文档广度和解释质量。

目标仍然是：

```text
用户给正常人类目标
-> ZN 恢复/建立 Root Work
-> Sense 当前电脑和任务上下文
-> 判断真正缺的 cognition / tools / authority / information
-> direct work 或 bounded delegation
-> 必要时做 bounded multi-source public-web research
-> 必要时跨 Browser / Desktop / File / Office / Terminal / Application
-> 状态变化后 fresh Sense / Situation / Thought
-> 遇到 blocker / stall / user steering 时使用现有 supervision/replan/recovery
-> 独立验证用户真正要的结果
-> 保留后续 continuation
```

模型、worker 和工具仍是资源；ZN 继续拥有用户目标、Durable Work、权限边界、现实证据、任务连续性和 completion judgment。

## Remaining product gaps

Current `main` 并不足以唯一指定一个“必然的下一开发任务”。因此下一阶段应从下面真实产品缺口中，按当前 E2E 阻塞程度选择最小高价值切片，而不是凭空发明 roadmap。

### 1. Cross-surface real task breadth

优先选择真正需要两个或更多 surface 的普通用户任务，例如：

```text
Browser/Web research
-> local File/Office mutation
-> Desktop/Application continuation
-> Terminal/Test verification
```

或：

```text
USER Browser existing session
-> causal child context
-> return to root page
-> local artifact/application update
-> fresh result verification
```

当前已有若干两-surface、一个 bounded Research→editable-file、E2E-09/10 Local Office 和 E2E-12 Research→DOCX completion 代表性闭环，但复杂三-surface任务、目标漂移、应用/网页/文档状态变化和跨 surface recovery 仍是主要产品广度问题。

开发规则：只补当前任务实际缺的 Body/Sense/Research/Office/verification 能力，不建立新的“cross-surface framework”、第二套 Research orchestration 或 OfficeAgent。

### 2. Browser / User Browser breadth beyond representative slices

现有 BrowserScene、tab/history、popup、file transfer、control click 与 E2E-05/07/08 已消除很多旧缺口，但下面更广问题仍可能阻塞真实站点：

- 更复杂 same-origin/cross-origin frame 情况；
- 浏览器/网页 dialogs 与复杂 navigation；
- 动态页面结构和更广 semantic controls；
- 真实站点的 popup/new-tab 变体；
- 复杂授权/用户在场流程；
- current exact semantic path 不足时的后续视觉/辅助感知需求；
- USER Browser session 漂移后的安全 re-ground。

E2E-08 只覆盖 standard HTML `one-time-code`、same authorized tab/generation/origin 的用户手工 OTP path。CAPTCHA、WebAuthn/passkey automation、cross-origin IdP handoff、password/payment automation 都不能因为 E2E-08 closure 被列为“已支持”。

### 3. Long-horizon continuity and user experience

现有 E2E-27/33、E2E-28/34 与 E2E-35 已证明 steering、supervision、dynamic health、stall/restart recovery，以及 bounded next-day status-first reconstruction/continue 的代表性路径。E2E-03 的 Research restart 也证明 bounded research evidence 可从现有 durable Work 恢复并继续 synthesis。下一步如果真实长任务仍失败，应聚焦“广度与产品体验”，而不是重新实现同一套机制。

重点包括：

- 超出 E2E-35 bounded yesterday reference 的更长时间窗口、多候选/更复杂项目引用和真实 continuation；
- 多 workstream 情况下用户可理解的 progress；
- blocker、等待用户、reassign/retry、完成依据的解释质量；
- steering 后哪些工作被保留/取消/过期的可理解表达；
- 长时间环境变化后如何重新建立 current evidence。

当前 delegated progress 应视为 `CONNECTED + VERIFIED NARROW / PARTIAL UX`，而不是 internal-only；但复杂长期 UX 仍未 product-close。

### 4. Research breadth beyond E2E-01/02/03 and E2E-12

E2E-01/02/03 已关闭 bounded public-web Research representative path；E2E-12 又关闭了一个 bounded public-Web-evidence→real-DOCX completion 组合路径。因此不要再把“多来源搜索、source identity/provenance/freshness、conflict、grounded synthesis、restart continuity、research→editable Markdown”整体描述成未开发，也不要把“Research 不能进入真实 DOCX 补全”继续当作完全空白。

仍然开放的是超出这些 bounded slices 的产品广度，例如：

- arbitrary-internet / much-longer-horizon Deep Research；
- authenticated USER-browser research 与 public-web evidence 的安全组合；
- PDF/复杂文档/多媒体 source extraction 的真实任务闭环；
- 更复杂 source conflict、freshness policy 与 citation UX；
- Research 与 Desktop/Terminal/Office 等更多 surface 的组合；
- 需要真实任务证明后才考虑的 provider/source breadth。

不要因此建立第二个 ResearchAgent、第二套 Work/store/router、general citation engine、knowledge graph/vector DB 或 recursive research swarm。

### 5. Local Office breadth beyond E2E-09/10/12

E2E-09/10 已关闭两个 bounded Local Office representative paths，E2E-12 已关闭一个 bounded Research→DOCX completion representative path，因此不要再把“真实 DOCX 修改”“真实 XLSX 清理”或“外部研究证据进入一个窄 DOCX 补全路径”整体描述成完全没有实现。

仍然开放的是：

- 更复杂 DOCX package、headers/footers、fields/content controls、tracked changes、drawings/embedded objects、复杂表格等；
- XLSX formulas、tables、charts/drawings、pivots、external links/Power Query、merges、多 sheet 等；
- 更广文档/表格变换，而不是只有付款日期替换、exact-row dedupe/amount format 和 1–3 个显式 placeholder 补全；
- Browser/Research/Desktop 与 Office 的更广真实组合任务，例如 E2E-11 和超出 E2E-12 bounded scope 的路径；
- PDF/PPT 等未由 E2E-09/10/12 覆盖的 Office/document 类任务。

继续复用 existing Product Resident / Work / Body / file identity；不要建立 WordAgent、ExcelAgent、OfficeAgent、第二套 file store 或默认 Office GUI automation。准确状态是 `VERIFIED NARROW`，不是 Word complete、Excel complete 或 Office Suite complete。

### 6. Windows / application capability breadth

Windows Machine Capability / Application Awareness、exact existing-window activation，以及 E2E-15 bounded unexpected-modal recovery 已经存在。后续不应再把“machine/application awareness 尚缺”或“Windows dialog recovery 完全没有”作为空泛基础设施任务。

E2E-15 的准确边界是：exact same-process directly owned UIA modal、parent `BlockedByModalWindow`、唯一 deterministic safe defer/continue/close-notice action、input 前 fresh revalidation、单次 side effect、modal absence + exact parent UIA/Win32 readiness 后 fresh desktop re-ground。`WaitForInputIdle` 只作为 telemetry，不是硬 gate；credentials/UAC/security/save-discard/delete/overwrite/file-picker/payment/installer/restart/update decision、跨进程或歧义 dialog 仍 fail closed。

只有当真实 E2E 暴露具体应用/OS 缺口时，才增加最小语义能力，例如某个真实应用所需的 current-state sensing、safe activation/selection、structured application action 或独立 postcondition。

不要把这条扩张成“先做完整 OS intelligence layer”。

### 7. Installed-version continuity remains separate

Installed N -> N+1 的 identity/data/Work/uncertain-side-effect continuity 仍未 product-close，但 updater、rollback、signing、release trust 属于高风险边界。

本文件不自动授权这类改动。只有当 owner 明确选择该产品问题并授权相应 trust boundary 时，才能进入实现。

## Selection criteria

从上述缺口中选下一项时，按下面顺序判断：

1. 哪个普通用户真实任务当前失败或可靠性最差？
2. 失败点属于 cognition、Sense、Body、authority、verification、continuity 还是 UX？
3. current `main` 已有机制能否被直接复用/扩展？
4. 哪个最小变化可以让一个真实 E2E 从失败变成成功，而不是只增加单独 capability demo？
5. 是否保持 one Resident / one Root Work truth / one ModelRouter / fresh evidence / non-replay？
6. 是否有代表性 closure 被误判为“完全没有实现”，从而导致重复开发？

如果没有足够证据确定唯一优先任务，就保留候选缺口，不凭空排列一个虚假的精确 roadmap。

## 不再作为下一阶段开发项

下面这些不能继续原样出现在“下一阶段待开发”列表中：

```text
E2E-01/02/03 bounded Research & Information Work representative closure
E2E-09/10 bounded Local Documents & Spreadsheet Work representative closure
E2E-12 bounded evidence-driven DOCX completion representative closure
E2E-30/42 closure 本身
ResidentHealthJournal dynamic health -> routing 接线
E2E-28/34 systematic no-progress/stall supervision
restart-safe delegated reconciliation
E2E-27/33 representative steering / continuation closure
E2E-35 bounded next-day status-first continuation closure
delegated user progress projection
bounded flat WorkItem dependency/readiness
E2E-15 bounded same-process safe modal recovery representative closure
```

如果新的真实任务在相关区域失败，应描述为“新覆盖/新边界缺口”，并证明 existing substrate 为什么不足。

## Orchestration boundary

不要因为 delegated Work 已经更完整，就把下一阶段变成通用调度平台。

当前 dependency/readiness 的准确范围是：

```text
bounded
flat
current-plan sibling dependencies
same Root / thread / plan
fan-in supported
derived readiness
restart durable
invalid/cyclic/dangling fail closed
```

它不是：

- general-purpose DAG scheduler；
- recursive delegation tree；
- arbitrary parallel DAG runtime；
- critical-path scheduler；
- resource-pool scheduler；
- generic dependency UX。

除非未来一个高价值真实任务明确证明 current bounded model 不能表达所需关系，否则不要把这些列为默认主线。

## Multi-route acceptance boundary

E2E-30/42 已按 current acceptance policy 关闭，但必须保留 waiver 语义：

- environment 当时没有第二个真实 provider family；
- owner-approved waiver 是 closure evidence 的一部分；
- 不得写成已经在两个真实 provider families 上完成完整生产验证；
- guarded two-provider acceptance 仍保留，并在真实双 provider 配置时要求 no-skip / fail closed。

如果以后获得真实双 provider family evidence，它是新的 coverage strengthening，不是重做 E2E-30/42 的 routing substrate。

## E2E 在 ZN 里的定义

```text
primitive success != E2E success
worker done != E2E success
model answer != E2E success
tool dispatch success != E2E success
unit tests / CI green != product E2E success
representative E2E closure != entire capability class product-closed
```

一个新阶段应说明：真实用户以前在哪里失败；本次后真实成功路径是什么；用到哪些 cognition/tools/authority/verification；状态变化和 restart 如何处理；仍有哪些明确边界。

## 已废弃 / 非默认路线

专用“自我维护 / 自我修复 / upstream BUG report”路线已删除，不属于 backlog。

同样不要默认恢复：

- multi-agent platform；
- second Resident / second ModelRouter / second orchestration truth；
- second ResearchAgent / Research store/router/orchestrator；
- WordAgent / ExcelAgent / OfficeAgent / second file truth；
- generic DAG/workflow engine；
- credential platform；
- installer/updater/release-trust 大改；
- 未经真实 E2E 驱动的 OS substrate 扩建。

下一阶段仍应是：**选择真实用户任务，找到 current main 真正缺的最小能力，把完整任务闭环做实。**