# ZN Next Phase

这份文件只描述下一阶段产品主线，不给 updater、rollback、signing、release trust、credential、identity 或 long-term memory 的高风险改动自动授权。

Updated: 2026-09-06

## 当前已验证基线

E2E-29 已关闭。ZN 已在真实 Windows X64、自托管 `zn-interactive`、真实模型条件下证明：

```text
一个实际 model route
-> 多个 durable WorkerRun
-> research / coding / review 隔离职责
-> bounded context + scoped tools/authority
-> failed/schema-rejected attempt 终结当前 WorkerRun
-> 新语义重试获得新 durable identity
-> worker completion 不等于 Root completion
-> 独立 verifier WorkItem
-> Terminal 实际执行
-> ZN Body fresh persisted-state reread
-> Root Work acceptance
```

真实模型验收 run `34022287626`，HEAD `3b2a96633ed1d593f64e5526fb35ab460bd4ebeb`：

```text
ZN_E2E29_SKIPPED=0
ZN_E2E29_FAILURES=0
ZN_E2E29_ERRORS=0
ZN_E2E29_TERMINAL.success=true
model_route_id=default
```

同一 HEAD 的标准 `ZN CI` run `34022288706` 也为 success。

因此“一个模型能否服务多个隔离 worker”不再是设计问题。下一阶段不能继续在 E2E-29 上横向扩平台。

## 2026-09-06 新增的 delegated-work substrate

在 E2E-29 基线上，现有 Resident 又补齐了一组后续真实 E2E 所需的内核边界：

- conservative `BoundedDelegationPlanner`：小任务 direct path，显式 negation 优先；
- `DelegatedWorkCoordinator`：composition 在同一个 Resident 内，不创建第二 Resident/store/router/control plane；
- Body action authority：真实 effect 前 revalidate WorkerRun / WorkItem / plan / workspace / admitted action；
- strict recursive `WorkerContextPack`：bounded serialization、nested sensitive-key rejection、secret-like value rejection、provenance/classification；
- existing `ModelRouter`：hard eligibility before soft scoring，支持 capability、pin/deny、declared availability/health、privacy/locality、policy tags、authority scopes，malformed policy fail closed。

这些是 **substrate / narrow verification**，不是下面真实 E2E 的 product closure。

## 产品目标

ZN 的下一阶段不是继续堆基础设施，而是把已经存在的 Self、Body、Senses、Situation、Thought、Will、Work、Memory、Browser、Desktop、Computer Use、File、Terminal、Git、Recovery 和 Cognitive Resource 真正组合成普通用户能长期使用的完整任务闭环。

ZN 是 **长期常驻在个人电脑里的通用型个人助理**。用户只需要表达正常的人类目标；ZN 自己判断需要的 cognition、tools、authority、verification 和 delegated SubWork。

```text
用户目标
-> 恢复当前 Work / Memory / Situation
-> 判断真正缺口
-> direct work OR bounded SubWork
-> 选择满足用户 policy 的 cognition + tools + authority
-> Browser / Desktop / File / Terminal / Git / API 按需参与
-> 状态变化后重新 Sense / Situation / Thought
-> 独立验证用户真正要的结果
-> 保持后续连续性
```

模型、worker 和工具都是资源，ZN 继续拥有用户目标、Durable Work、权限边界、现实证据、任务连续性和最终 completion judgment。

## 下一阶段代码顺序

### 1. 真正关闭 E2E-30 + E2E-42：multi-route policy/privacy acceptance

不要再先造新的 router 或 eligibility layer。现有 `ModelRouter` 已有 hard gates，下一步必须证明这些 gates 在真实多 route 任务中真的保护用户并做对选择。

最小真实验收：

- 至少多个 user-approved routes；
- research/coding/general 等不同 SubWork 按显式 capability eligibility 选 route；
- user pin / deny / provider restriction 真正生效；
- `local_only` / `cloud_denied` 等数据策略在 scoring 前过滤；
- selected route provenance 可追溯到它服务的 WorkItem/WorkerRun；
- forbidden provider **没有收到**受限项目上下文；
- preferred route 不可用时，只能在仍满足用户 policy/capability 的候选中 fallback；
- 无合法候选时 fail closed，而不是绕过用户策略。

**不能因为 unit tests、standard CI 或单模型 regression 绿，就把 E2E-30/E2E-42 标记为关闭。**

### 2. Supervision / stall / dynamic reroute — E2E-28 + E2E-34

当前已有 durable WorkerRun、stale-plan gate、reconcile foundations，但还缺系统化长期监督：

- repeated no-progress detection；
- bounded retry budget；
- dynamic provider availability/health；
- `ResidentHealthJournal` observation 进入 route eligibility；
- policy-safe reroute / reassign / replan；
- Resident restart 后 reconcile WorkerRun / WorkItem / plan/current reality；
- completed side effect 不 replay；
- stale worker result 不推进 current plan。

静态 route metadata 的 `healthy=false` hard gate 不等于 dynamic health→reroute 已完成。

### 3. Natural continuation + active steering — E2E-33 + E2E-27

用户：

> “昨天那个产品继续。登录先别做，先把核心记账跑起来。”

必须在同一个 durable Root Work 上安全修改当前计划：保留仍有效的 completed work，取消/supersede 受影响 pending work，旧 plan running result 必须 stale-gated，已发生 side effect 不 replay。

plan-version/unit tests 是 foundation，不等于这两个 E2E 已 product-close。

### 4. 继续扩大真实 Body / cross-surface 闭环

每当真实 E2E 暴露 Browser/Desktop/File/Terminal/OS semantic substrate 缺口，只补直接阻塞当前任务的最小能力。不要单独把“OS integration”做成新的基础设施主线。

Resident 本地 control plane 当前的 loopback TCP + per-process secret + endpoint ACL 是过渡实现；Windows 长期 transport 仍应收敛到 Named Pipe + per-user SID ACL，但只有在它直接阻塞产品安全/可靠性时才提升优先级。

## 调度必须服务真实任务

不要为了“支持多 Agent / 多模型”先建庞大通用编排平台，再很久以后才接真实用户任务。

正确顺序：

```text
选择一个真实长任务
-> 看它哪里真的需要拆分、专业模型或监督
-> 在现有 Work / Will / Thought / ModelRouter / Body 上补最小缺口
-> 让这个真实 E2E 从失败变成功
-> 再把可复用机制扩展到下一个任务
```

只有一个模型时系统也必须工作；E2E-29 已经把这条约束从设计变成真实验收事实。

## 当前优先顺序

1. 真实 multi-route + policy/privacy E2E（E2E-30 + E2E-42）。
2. worker/model failure、dynamic health、stall、reroute、restart supervision（E2E-28 + E2E-34）。
3. active Work steering + natural continuation（E2E-27 + E2E-33）。
4. 真实 User Browser Bridge 和跨 surface Body 能力。
5. 普通用户能看懂的任务状态、授权、失败和完成体验。

Installer、Release Candidate、签名、额外 CI、维护系统、文档整理、新抽象、新 provider、新状态机默认都是支撑线，不得自动抢主线。

## E2E 在 ZN 里的定义

```text
primitive success != E2E success
worker done != E2E success
model answer != E2E success
tool dispatch success != E2E success
unit tests / CI green != product E2E success
```

E2E-29 关闭，是因为真实模型、真实 Browser、真实 workspace write、真实 Terminal/Test、独立 review 和 Root fresh persisted-state verification 形成了完整闭环。同样标准必须用于 E2E-30/42、28/34、27/33。

## 已废弃方向

专用“自我维护 / 自我修复 / upstream BUG report”路线已经删除，不属于下一阶段，不属于 backlog 优先级，也不属于未来产品路线。

需要修改 ZN 自己的代码时，把 ZN 当成普通代码仓库，用通用 Work、File、Terminal、Git、Repo Test 和编码能力处理。

## 完成一个阶段以后怎么汇报

优先说明：ZN 以前不能完成什么真实任务、现在能完成什么、成功路径、参与的 cognition/workers/tools/authority/verification、失败是否能恢复、用户还会在哪里失败，以及下一个最阻塞真实使用的问题。不要把 model 数、worker 数、Action 数、测试数、PR 数或 CI 当产品成绩。
