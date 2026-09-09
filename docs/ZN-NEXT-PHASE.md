# ZN Next Phase

这份文件只描述 current `main` 之后的产品选择原则和剩余产品缺口。它不给 updater、rollback、signing、release trust、credential、identity、installer 或 long-term memory 的高风险改动自动授权。

Updated: 2026-09-09

## 当前已关闭的 delegated baseline

2026-09-06～2026-09-08 已经形成一组代表性 closure；下一阶段不得重复把它们当“尚未开发”的默认主线。

已关闭的代表性 baseline：

- **E2E-29**：一个实际 model route 服务多个隔离 WorkerRun；worker 数与模型数不绑定，Root completion 仍由 ZN 独立验收。
- **E2E-30 / E2E-42**：durable route/privacy policy、ModelRouter hard eligibility、route/provider provenance 与 guarded multiroute acceptance 已按当前 acceptance policy 关闭。closure 包含明确的 owner-approved environment waiver，因为当时缺少第二个真实 provider family；不能宣称已有双真实 provider family 完整生产证据。
- **E2E-28 / E2E-34**：durable worker progress supervision、heartbeat/no-progress/stall detection、dynamic health-aware routing、bounded retry、policy-safe fallback/reassignment、restart reconciliation、no-replay recovery 已有 guarded real-model representative closure。
- **E2E-27 / E2E-33**：natural-language same-Work steering、current-plan replan、plan-version stale gating、old-worker result protection、restart continuation、completed historical effects 不 replay 已有真实 representative closure。
- **Delegated progress**：durable delegated facts 已 privacy-safe bounded projection 到既有 `work_progress` 和 Resident UI，没有第二套 progress truth。
- **Dependency/readiness**：durable bounded flat current-plan sibling dependency/readiness 已实现并验证，包括 fan-in、restart durability 与 corrupt/cyclic/dangling fail closed。

这些 closure 证明当前 bounded substrate 已经存在，但不把 ZN 升格为通用 multi-agent platform、general DAG scheduler 或无限期后台任务系统。

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

ZN 的下一阶段不再是“把 delegated Work 基础补齐”。现在更重要的是：把已经存在的 Self、Body、Senses、Situation、Thought、Will、Work、Memory、Browser、Desktop、File、Terminal、Git、Recovery 和 CognitiveResources 组合到更多普通用户真实任务里，并扩大持续性、跨 surface 和解释质量。

目标仍然是：

```text
用户给正常人类目标
-> ZN 恢复/建立 Root Work
-> Sense 当前电脑和任务上下文
-> 判断真正缺的 cognition / tools / authority / information
-> direct work 或 bounded delegation
-> 必要时跨 Browser / Desktop / File / Terminal / Application
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
Browser research
-> local File mutation
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

当前已有若干两-surface代表性闭环，但复杂三-surface任务、目标漂移、应用/网页状态变化和跨 surface recovery 仍是主要产品广度问题。

开发规则：只补当前任务实际缺的 Body/Sense/verification 能力，不建立新的“cross-surface framework”。

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

现有 E2E-27/33 与 E2E-28/34 已证明 steering、supervision、dynamic health、stall/restart recovery 的代表性路径。下一步如果真实长任务仍失败，应聚焦“广度与产品体验”，而不是重新实现同一套机制。

重点包括：

- 跨更长时间窗口、跨天的真实 continuation；
- 多 workstream 情况下用户可理解的 progress；
- blocker、等待用户、reassign/retry、完成依据的解释质量；
- steering 后哪些工作被保留/取消/过期的可理解表达；
- 长时间环境变化后如何重新建立 current evidence。

当前 delegated progress 应视为 `CONNECTED + VERIFIED NARROW / PARTIAL UX`，而不是 internal-only；但复杂长期 UX 仍未 product-close。

### 4. Windows / application capability breadth

Windows Machine Capability / Application Awareness、exact existing-window activation，以及 E2E-15 bounded unexpected-modal recovery 已经存在。后续不应再把“machine/application awareness 尚缺”或“Windows dialog recovery 完全没有”作为空泛基础设施任务。

E2E-15 的准确边界是：exact same-process directly owned UIA modal、parent `BlockedByModalWindow`、唯一 deterministic safe defer/continue/close-notice action、input 前 fresh revalidation、单次 side effect、modal absence + exact parent UIA/Win32 readiness 后 fresh desktop re-ground。`WaitForInputIdle` 只作为 telemetry，不是硬 gate；credentials/UAC/security/save-discard/delete/overwrite/file-picker/payment/installer/restart/update decision、跨进程或歧义 dialog 仍 fail closed。

只有当真实 E2E 暴露具体应用/OS 缺口时，才增加最小语义能力，例如某个真实应用所需的 current-state sensing、safe activation/selection、structured application action 或独立 postcondition。

不要把这条扩张成“先做完整 OS intelligence layer”。

### 5. Installed-version continuity remains separate

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
E2E-30/42 closure 本身
ResidentHealthJournal dynamic health -> routing 接线
E2E-28/34 systematic no-progress/stall supervision
restart-safe delegated reconciliation
E2E-27/33 representative steering / continuation closure
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
- generic DAG/workflow engine；
- credential platform；
- installer/updater/release-trust 大改；
- 未经真实 E2E 驱动的 OS substrate 扩建。

下一阶段仍应是：**选择真实用户任务，找到 current main 真正缺的最小能力，把完整任务闭环做实。**