# ZN Next Phase

这份文件只描述下一阶段产品主线，不给 updater、rollback、signing、release trust、credential、identity 或 long-term memory 的高风险改动自动授权。

Updated: 2026-09-06

## 当前已验证基线

E2E-29 已关闭。ZN 现在已经在真实 Windows X64、自托管 `zn-interactive`、真实模型条件下证明：

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

验收 HEAD：`3b2a96633ed1d593f64e5526fb35ab460bd4ebeb`。

真实模型验收 run `34022287626`：

```text
ZN_E2E29_SKIPPED=0
ZN_E2E29_FAILURES=0
ZN_E2E29_ERRORS=0
ZN_E2E29_TERMINAL.success=true
model_route_id=default
```

同一 HEAD 的标准 `ZN CI` run `34022288706` 也为 success。

因此“一个模型能否服务多个隔离 worker”不再是设计问题。下一阶段不能继续在 E2E-29 上横向扩平台，而应使用现有 WorkerRun 基线进入更难的真实问题。

## 产品目标

ZN 的下一阶段不是继续堆基础设施，而是把已经存在的 Self、Body、Senses、Situation、Thought、Will、Work、Memory、Browser、Desktop、Computer Use、File、Terminal、Git、Recovery 和 Cognitive Resource 真正组合成普通用户能长期使用的完整任务闭环。

ZN 的产品定位是 **长期常驻在个人电脑里的通用型个人助理**。它不是办公 Agent、代码 Agent、浏览器 Agent、桌面自动化 Agent 或命令行 Agent 中的某一个，也不应围绕任何单一垂直领域收缩产品定义。

用户只需要表达正常的人类目标。ZN 自己判断完成目标需要什么资源组合：

```text
用户目标
-> 恢复当前 Work / Memory / Situation
-> 判断真正缺口
-> 组合需要的 cognition + tools + authority + verification
-> Browser / Desktop / File / Terminal / Git / API / specialist model 按需参与
-> 必要时拆成多个 delegated SubWork / WorkerRun
-> 状态变化后重新 Sense / Situation / Thought
-> 独立验证用户真正要的结果
-> 保持后续连续性
```

模型、worker 和工具都是资源，ZN 继续拥有用户目标、Durable Work、权限边界、现实证据、任务连续性和最终 completion judgment。

## ZN 负责调度和持续盯住整个任务

对于“帮我开发一个产品”这类长期、复杂、跨专业任务，ZN 不应该把整件事一次性扔给某一个模型或 Agent 后等待结果。ZN 应持续拥有根目标，并在需要时完成：

```text
理解用户意图
-> 自主调查
-> 形成当前计划和验收目标
-> 拆分可执行 SubWork
-> 为每个 SubWork 选择合适资源
-> 委派 bounded WorkerRun 或直接调用工具
-> 跟踪依赖、进度、结果和 blocker
-> 收集 fresh evidence
-> 发现偏差后重规划 / 重分配 / 升级资源
-> 用户改变方向时安全 steering 现有 Work
-> 汇总子任务结果
-> 独立验证整个用户目标
-> restart / cross-day 后继续
```

worker 是当前 Work 下的受限执行上下文，不是新的 Resident 主体。它不得自动继承整个用户身份、全部 Memory、全部凭据、全部工具权限或根 Work 的 completion authority。

worker 返回的“done”“success”或模型自评只是候选结果。ZN 必须检查真实产物、测试、页面状态、文件状态、运行结果或其他独立证据，再决定该 SubWork 是否真正完成以及整个 root Work 是否可以继续。

## worker 数量和模型数量已确认解耦

E2E-29 已经真实证明：一个模型 route 不等于一个 worker。Research、coding、review 可以使用同一个 cognitive provider route，但拥有不同 WorkerRun identity、context、tool scope、authority 和 verification。

因此下一步多模型能力只解决 **资源选择策略**，不是为了获得多 worker。

如果用户接入多个模型，ZN 应扩展现有 `ModelRouter` 的 eligibility/policy layer，根据当前 SubWork 需要，在用户允许的模型集合里选择合适资源：

```text
这个 SubWork 需要什么能力？
-> 哪些已连接模型具备该能力？
-> 用户是否 pin / deny / 指定 provider？
-> 当前数据敏感性允许哪些 route？
-> 是否要求 local-only？
-> route 是否可用？
-> fallback 是否仍满足用户策略？
-> 当前 evidence 中哪个 route 对该领域更可靠？
```

用户显式指定必须优先于自动路由。自动 routing 不能绕过模型、隐私、成本或权限偏好。

## 下一阶段代码顺序

### 1. Multi-model per-SubWork routing — E2E-30 + E2E-42

这是 E2E-29 后最自然的下一跳。

只扩展现有 `ModelRouter` 和 WorkerRun provenance，不新建第二套路由器。最小范围：

- user primary model preference；
- coding/research/vision capability eligibility；
- allow / deny / pin；
- privacy / locality constraint；
- route unavailable / fallback；
- selected route provenance 写回 WorkerRun；
- 用户策略作为 route scoring 前硬过滤。

不要提前实现完整成本优化、复杂并行 scheduler 或独立 orchestration framework。

### 2. Supervision / stall / restart — E2E-28 + E2E-34

E2E-29 已证明单个失败 WorkerRun 可以被后续新 WorkerRun 替代并最终完成，但还缺系统化长期监督：

- repeated no-progress detection；
- bounded retry budget；
- reroute / reassign / replan；
- model unavailable；
- Resident restart 后 reconcile WorkerRun / WorkItem / plan version / real state；
- completed side effect 不 replay；
- stale worker result 不推进 current plan。

### 3. Natural continuation + active steering — E2E-33 + E2E-27

用户：

> “昨天那个产品继续。登录先别做，先把核心记账跑起来。”

在同一个 durable Work 上安全修改计划，已有完成副作用不能重放，旧 plan 的运行结果必须 stale-gated。

### 4. 继续扩大真实 Body / cross-surface 闭环

每当真实 E2E 暴露 Browser/Desktop/File/Terminal/OS semantic substrate 缺口，只补直接阻塞当前任务的最小能力。不要单独把“OS integration”做成新的基础设施主线。

## 调度必须服务真实任务

不要为了“支持多 Agent / 多模型”先建一个庞大的通用编排平台，再很久以后才接真实用户任务。

正确顺序：

```text
选择一个真实长任务
-> 看它哪里真的需要拆分、专业模型或监督
-> 在现有 Work / Will / Thought / Cognitive Resource / Body 上补最小缺口
-> 让这个真实 E2E 从失败变成功
-> 再把可复用机制扩展到下一个任务
```

只有一个模型时系统也必须能工作；E2E-29 已经把这条约束从设计变成真实验收事实。

## 当前优先顺序

1. 多模型 per-SubWork policy/routing。
2. 长任务 supervision / stall / reroute / restart。
3. active Work steering + natural continuation。
4. 真实 User Browser Bridge 和跨 surface Body 能力。
5. 普通用户能看懂的任务状态、授权、失败和完成体验。

Installer、Release Candidate、签名、额外 CI、维护系统、文档整理、新抽象、新 provider、新状态机默认都是支撑线，不得自动抢主线。

## E2E 在 ZN 里的定义

E2E 不是“多个 primitive 串起来跑通”，而是从用户真实目标入口一直到用户真正需要的结果被独立验证。

```text
primitive success != E2E success
worker done != E2E success
model answer != E2E success
tool dispatch success != E2E success
CI green != product E2E success
```

E2E-29 之所以关闭，不是因为“有 WorkerRun 代码”或“CI 绿”，而是因为真实模型、真实 Browser、真实 workspace write、真实 Terminal/Test、独立 review 和 Root fresh persisted-state verification 已经形成闭环。

## 已废弃方向

专用“自我维护 / 自我修复 / upstream BUG report”路线已经删除，不属于下一阶段，不属于 backlog 优先级，也不属于未来产品路线。

不要恢复专用 maintenance runtime、repair cognition、BUG report transport/intake、maintenance UI/RPC 或特殊仓库权限路径。

需要修改 ZN 自己的代码时，把 ZN 当成普通代码仓库，用通用 Work、File、Terminal、Git、Repo Test 和编码能力处理。

## 完成一个阶段以后怎么汇报

优先说明：

- ZN 以前不能完成什么真实任务；
- 现在能完成什么；
- 成功路径是什么；
- 哪些 cognition + workers + tools + authority + verification 真正参与；
- worker/model/tool failure 是否能恢复；
- 用户还会在哪里失败；
- 下一个最阻塞真实使用的问题是什么。

不要拿 model 数量、worker 数量、Action 数量、OS API 数量、测试数量、PR 数、commit 数和 CI 当产品成绩。
