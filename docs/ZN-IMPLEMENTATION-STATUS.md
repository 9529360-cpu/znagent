# ZN Implementation Status

这是一份当前实现事实表，不是 roadmap。真实代码、真实 Git、真实测试和真实 E2E 高于本文件。

Updated: 2026-09-08

## 仓库状态规则

- 唯一长期集成 / canonical / release 分支：`main`。
- 新开发从最新 `main` 拉短命 `work/*`，PR 以 `main` 为 base；适用 CI/E2E 在 PR 阶段通过后再合并。
- `dev/zn-agent` 仅为历史兼容，不再接收新产品开发。
- 文档里的 SHA 和 CI run 只能当历史 evidence；接手时必须重新查询 current `main`。
- Git/CI/main 合并属于工程证据，不等于产品能力自动闭环。

## 状态语言

本文件继续区分：

```text
Exists
Connected
Verified
Product-closed
```

`VERIFIED NARROW` / `representative path closed` 表示真实代表性路径已经验证，但不代表整个 capability 类别已经 product-closed。

## 已废弃方向

专用“自我维护 / 自我修复 / upstream BUG report”产品路线已经废弃并从当前代码树移除。不要重新增加 maintenance runtime、专用 maintenance cognition/repair、专用 BUG-report control plane 或因为目标仓库是 ZN 就自动扩大权限的特殊路径。

通用 Health、Recovery、Work、Memory、File、Terminal、Git、Browser、Desktop、Computer Use 和 Update 架构继续保留。

## 当前能力事实

| 区域 | 当前状态 | 当前边界 / 仍需扩大 |
| --- | --- | --- |
| Resident Self / Body / Senses / Situation / Thought / Will | CONNECTED + VERIFIED | 真实任务广度仍需扩大 |
| Durable Work / restart recovery | CONNECTED + VERIFIED | 更长周期、跨天和更多真实任务上的连续体验仍需扩大 |
| Work continuity / steering | VERIFIED NARROW; E2E-27/33 representative path closed | natural-language same-Work steering、plan-version replan、stale old-worker gating、restart continuation 已验证；更广长期使用仍开放 |
| Managed Browser / BrowserScene | CONNECTED + VERIFIED NARROW | 已有 bounded BrowserScene、tab/history、exact scene actions、causal popup、file transfer、stateless/stateful control clicks；复杂 frames/dialogs/general keyboard/OCR/任意网页仍未覆盖 |
| User Browser Bridge | CONNECTED + VERIFIED NARROW | E2E-05 authenticated research→mutation、E2E-07 causal child-tab、E2E-08 OTP user-presence representative paths 已关闭；真实网站和更复杂认证/导航仍需扩大 |
| File / workspace tasks | CONNECTED + VERIFIED NARROW | 歧义来源、复杂整理和更广任务类型 |
| Windows machine/application awareness | CONNECTED + VERIFIED NARROW | inventory/identity/launch/fresh verification 与 exact admitted existing-window activation 已有；任意应用生命周期/窗口拓扑仍未 product-close |
| Desktop computer use | CONNECTED + VERIFIED NARROW | 通用跨应用连续任务、目标漂移和更复杂应用语义 |
| Browser + File / Browser + Desktop | VERIFIED NARROW | 更多三-surface 联合与复杂 replanning |
| Cognitive resources | CONNECTED + VERIFIED | ZN-owned provider seam、多 route、热重配、provenance 已存在；更广 provider/product coverage 继续扩大 |
| Model routing hard eligibility | CONNECTED + VERIFIED NARROW | route/privacy policy、pin/deny/locality、dynamic health-aware routing 已接入；E2E-30/42 closure 包含 environment waiver，不等于双真实 provider family 生产证据 |
| Dynamic provider health -> routing | VERIFIED NARROW; E2E-28/34 representative path closed | `ResidentHealthJournal` 动态 observation 已进入 routing；更广 provider failures/长期运行仍需扩大 |
| Delegation admission | CONNECTED + VERIFIED NARROW | 更多真实任务上继续证明何时 direct、何时 delegated；避免 pointless delegation |
| Delegated Work coordinator | CONNECTED + VERIFIED NARROW | durable bounded delegation、routing、supervision、restart reconciliation 已接通；不是 general scheduler / recursive orchestration runtime |
| WorkerRun lifecycle | CONNECTED + VERIFIED NARROW | durable queued/running/completed/failed/stale、progress、bounded retry/reassign、restart reconcile 已存在；无限期/通用调度不在当前声明内 |
| Long-task supervision | VERIFIED NARROW; E2E-28/34 representative path closed | heartbeat/no-progress/stall detection、bounded retry、health-aware fallback/reassignment、restart reconcile 已验证；更长、更复杂任务仍需扩大 |
| One-model multi-worker | VERIFIED; E2E-29 CLOSED | 一个实际 route 服务多个隔离 WorkerRun 已证明；不是 worker/model 数绑定 |
| Strict WorkerContextPack | CONNECTED + VERIFIED NARROW | 未来 worker 类型继续审计；不是完整 DLP |
| Worker action authority | CONNECTED + VERIFIED NARROW | Body action admission，不是任意命令 OS sandbox |
| Worker completion verification | VERIFIED NARROW | worker `done` 仍只是 candidate result；Root completion 由 ZN 独立验收 |
| Stale delegated result protection | VERIFIED NARROW | plan-version stale gating 与 old-worker protection 已验证；更多任务继续覆盖 |
| Delegated user progress | CONNECTED + VERIFIED NARROW / PARTIAL UX | durable delegated facts 投影到既有 `work_progress` 与 Resident UI；复杂 multi-workstream UX/解释质量继续扩大 |
| WorkItem dependency/readiness | CONNECTED + VERIFIED NARROW | bounded flat current-plan sibling dependency/readiness、fan-in、restart durability、corrupt/cyclic/dangling fail closed 已实现；不是 general DAG scheduler |
| Autonomous Investigation / replanning | CONNECTED + VERIFIED NARROW | 已有代表性 re-ground/replan；更通用冲突、复杂跨 surface recovery 仍需扩大 |
| Resident local control plane | CONNECTED + HARDENED NARROW | loopback-only authenticated endpoint + per-process secret + endpoint ACL；更终局 Windows transport 仍可继续收敛 |
| Installed N -> N+1 continuity | PARTIAL / OPEN | 真实升级过程中 identity、data、Work 和 uncertain side effects 的全链路连续性尚未 product-close |

## Delegated Work 当前主链

当前 `main` 的 delegated-work 主链不是独立 multi-agent 平台，而是现有 Resident/Work/Router/Body 的纵向扩展：

```text
Root Work
-> BoundedDelegationPlanner
-> DelegatedWorkCoordinator (same Resident)
-> durable short-lived WorkerRun
-> strict WorkerContextPack
-> existing ModelRouter hard eligibility + health-aware scoring
-> existing Body action-authority gate
-> durable progress / supervision / restart reconciliation
-> fresh verification
-> Root completion remains ZN-owned
```

### Admission 与 context boundary

小而确定的目标可以走 direct path。WorkerContextPack 维持递归 fail-closed boundary：depth/node/item/string/final-size limits、nested sensitive-key rejection、secret-like token rejection、provenance/classification hook、plan-version validation。

`private` 不自动等于 cloud forbidden；route locality 以显式 `local_only` / `cloud_denied` / `cloud_forbidden` 等策略为准。

### Action authority

WorkerRun authority 在真实 Body effect 前从 durable Work/WorkerRun state 重新验证。review/research 不因 delegation 获得 workspace mutation；coding write 受 attached workspace 约束；stale plan 被拒绝。

这是 **action admission boundary**，不是进程级或命令级 OS sandbox。

### ModelRouter hard eligibility + dynamic health

现有单一 `ModelRouter` 先 hard-filter，再 soft-score。hard gates 已覆盖 required capability、retry/runtime exclusion、pin/deny provider/model、declared availability、locality/privacy、policy tags、authority scopes 与 malformed-policy fail closed。无 eligible route => `NoRouteAvailable`，不违规 fallback。

2026-09-07 的 E2E-28/34 closure 已把 `ResidentHealthJournal` 的动态运行 observation 接入 health-aware routing，并验证 bounded retry/fallback/reassignment 与 restart-safe reconciliation 的代表性路径。

不要再写“dynamic ResidentHealthJournal 尚未进入 router”。

## Durable dependency/readiness

`WorkItem.dependency_ids` 已 durable persistence。当前 substrate 的准确范围是：

- bounded dependency list；
- same Root / work thread / current plan validation；
- immutable dependency edges；
- readiness 由 durable Work truth **derived**，不持久化第二套 readiness truth；
- WorkerRun creation、coordinator cognition binding 与 child completion 都受 readiness gate；
- restart durability 与 fan-in；
- dangling/corrupt/cyclic/cross-root/cross-plan graph fail closed；
- dependency 不继承 authority/tool scope。

这不是 general-purpose DAG scheduler、recursive delegation、critical-path scheduler、resource-pool scheduler 或 generic dependency UX。

## Delegated user progress

Delegated progress 已从 durable delegated Work facts 投影到既有 `work_progress` contract 和 Resident UI，采用 bounded privacy-safe normalization，并覆盖 restart / steering。

它没有创建第二套 progress truth。当前状态是：

```text
CONNECTED + VERIFIED NARROW / PARTIAL UX
```

复杂 multi-workstream 展示、长期任务解释质量、面向普通用户的阻塞/完成依据表达仍需扩大。

## 代表性 E2E closure

### E2E-29 — one model, multiple WorkerRuns

2026-09-06 已有真实模型代表性验收：一个实际 route 可连续服务隔离 research/coding/review WorkerRun；worker completion 不夺取 Root completion。

### E2E-30 / E2E-42 — route policy/privacy

按仓库当前 acceptance policy 已关闭。已验证 durable Work route/privacy policy、ModelRouter hard eligibility、route/provider provenance 与 guarded multiroute policy path。

该 closure 明确包含 **owner-approved environment waiver**：验收环境当时缺少第二个真实 provider family。因此：

```text
representative acceptance = closed
actual two-real-provider-family production evidence = not claimed
```

guarded two-provider acceptance 保留；真正配置两个 provider family 时要求无 skip / fail closed。

### E2E-28 / E2E-34 — supervision / dynamic health / restart

代表性真实路径已关闭：durable progress supervision、heartbeat/no-progress/stall detection、dynamic health-aware routing、bounded retry、policy-safe fallback/reassignment、restart reconciliation 和 no-replay recovery。

不代表无限期通用 long-task scheduler 已完成。

### E2E-27 / E2E-33 — steering / continuation

代表性真实路径已关闭：natural-language same-Work steering、current plan replanning、plan-version stale gating、old-worker result protection、restart continuation，以及 completed historical effect 不 replay。

不代表所有跨天/长期 continuity 场景都已解决。

### E2E-05 — authenticated research mutation

已有真实 USER Browser authenticated research -> persisted mutation representative closure。

### E2E-07 — causal USER Browser child tab

已有 task-scoped causal child-tab attribution、causal popup handling、authorization generation binding、fresh opener reread、child -> root return 与 unverified causal click no-replay 的真实 interactive representative closure。

### E2E-08 — OTP/MFA user-presence representative path

已验证：standard HTML `autocomplete="one-time-code"`、same explicitly authorized USER-browser tab、same authorization generation、same origin、`waiting_for_user` 非终态、用户手工完成 OTP、fresh Sense/re-ground 后同一 Work resume。

安全边界：ZN 不读取或自动输入 OTP；blocker 期间 model/Body 不继续；OTP 不进入 cognition、Work progress、Body history 或 durable SQLite；authorization generation 变化时 fail closed。

未支持：CAPTCHA solving、WebAuthn/passkey automation、cross-origin IdP handoff、password automation、payment-field automation。

## Browser Body V2 / Windows 当前边界

Browser 近期 verified narrow slices 包括：

- bounded BrowserScene sensing；
- tab lifecycle/history；
- exact BrowserScene focus/type/check/uncheck/navigation；
- managed causal popup attribution；
- authority-safe causal upload/download；
- stateless `target_absent_equals` command clicks；
- bounded stateful `aria-pressed` / `aria-expanded` / `aria-selected` clicks。

这些都坚持 exact current target、fresh revalidation、authority 和 independent postcondition。不要扩张成任意 popup/frame/dialog/site、general keyboard、OCR/visual fallback 或完整 web automation。

Windows 当前已有 Machine Capability / Application Awareness V1，以及后续 exact admitted existing-window activation。应用 inventory/identity、Installed/Running/Window/Foreground facts、identity-bound launch、fresh process/window verification、Resident-admitted app/HWND/PID revalidation 都已有代表性验证。不要扩张成全 Windows application lifecycle 或任意窗口自动化。

## 当前主要剩余产品缺口

下面是仍然真实存在的“广度/产品体验”缺口，不再把已经关闭的三组 delegated E2E 当新开发任务：

1. **Cross-surface real tasks**：Browser + Desktop + File/Terminal/Application 在更复杂真实任务中的连续完成率和 recovery。
2. **Browser/User Browser breadth**：真实站点变化、复杂 frame/dialog/navigation、更多授权/用户在场边界；E2E-08 只覆盖代表性 OTP path。
3. **Long-horizon experience**：在现有 supervision/steering/restart substrate 上扩大跨天、长周期、多个 workstream 的真实使用与 progress/explanation UX。
4. **Windows/application breadth**：当前 machine/application substrate 之外，由真实 E2E 暴露的应用语义、窗口/系统能力缺口。
5. **Upgrade continuity**：installed N -> N+1 的身份、数据、Work、rollback/uncertain-effect 连续性仍未 product-close。

如果 current main 不能从真实 E2E 唯一确定下一开发任务，应按真实用户任务阻塞程度选择，而不是凭空新增 roadmap。

## 不要误判为完成

当前实现不等于：

- 完整 multi-agent orchestration 平台；
- general-purpose DAG scheduler / recursive delegation；
- 所有 MFA；
- 任意网页或任意 popup/frame/dialog；
- 完整 DLP / OS sandbox；
- 所有长期任务已解决；
- 双真实 provider family 已有完整生产证据；
- Memory、credential、installer/updater/release trust 已因此获得自动扩张授权。

## 判断产品完成的标准

代码、单测、CI、installer、provider、worker 或模型数量都不是 product closure。真正要看：

```text
普通用户给正常人类任务
-> ZN 保持 Root Work
-> Sense 当前电脑状态
-> 判断 direct / delegated
-> 选择 cognition + tools + authority + verification
-> 状态变化/失败/用户改方向后重新观察和判断
-> 保留 authority / fresh evidence / non-replay
-> 独立验证关键结果和最终目标
-> 中断、重启、跨天后在足够当前证据下继续
```

每次只补高价值真实 E2E 真正缺的能力，不回到“先造完整 multi-agent/router/framework，再很久以后验证用户任务”的路线。
