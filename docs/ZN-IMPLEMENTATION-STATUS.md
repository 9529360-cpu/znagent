# ZN Implementation Status

这是一份当前实现事实表，不是 roadmap。真实代码、真实 Git、真实测试和真实 CI 高于本文件。

Updated: 2026-09-06

## 仓库状态规则

- 唯一长期集成 / canonical / release 分支：`main`
- 新开发从最新 `main` 拉短命 `work/*`，PR 直接以 `main` 为 base；适用 CI/E2E 在 PR 阶段通过后再合并。
- `dev/zn-agent` 只保留为历史兼容分支，不再接收新的产品开发或作为新 PR base；保留期间应与 `main` 对齐。
- 文档里的 SHA 和 CI run 只能当历史检查点，接手时必须重新查询。
- Git/CI/main 合并属于工程卫生，不是产品里程碑。

## 已废弃方向

专用“自我维护 / 自我修复 / upstream BUG report”产品路线已经明确废弃并从当前代码树中移除。

它不再属于 ZN 的现役能力，不再属于产品缺口，不再属于后续优先级。

不要重新增加 maintenance runtime、maintenance cognition、maintenance repair、专用 BUG report transport/intake/reconcile、maintenance UI/IPC/RPC，或任何因为目标仓库是 ZN 就自动扩大权限的特殊路径。

详细说明见 `docs/ZN-RETIRED-DIRECTIONS.md`。

通用 Health、Recovery、Work、Memory、File、Terminal、Git、Browser、Desktop、Computer Use 和 Update 架构继续保留。

## 当前能力事实

| 区域 | 当前状态 | 还缺什么 |
| --- | --- | --- |
| Resident Self / Body / Senses / Situation / Thought / Will | 已接通并有多轮验证 | 真实任务广度仍需继续扩大 |
| Durable Work / restart recovery | 已接通并验证 | 需要继续转化成普通用户可感知的长期连续性 |
| Managed Browser | 多个受限语义动作已验证 | 更广泛页面变化、弹窗、frame、下载上传等仍不完整 |
| User Browser Bridge | 已有真实 existing-session 授权路径和语义控制基础 | 仍需扩大真实网站覆盖、权限 UX、漂移后的稳定重规划 |
| File / workspace tasks | 已有自然语言文件任务和跨 surface 闭环证据 | 歧义来源、复杂整理和更广任务类型仍需加强 |
| Desktop computer use | 多个窄场景已真实验证 | 通用跨应用连续任务、窗口变化和目标漂移仍需加强 |
| Browser + File / Browser + Desktop | 已有代表性真实闭环 | 三个 surface 联合、复杂重规划仍是缺口 |
| Work continuity | 有 durable ledger 和恢复基础；PR #166 正在处理自然引用 continuation | active task steering、跨天产品化和与后续 SubWork 监督整合仍缺 |
| Cognitive resources | 已支持 OpenAI-compatible / Anthropic / Gemini 等 ZN-owned resource seam，可多 route、可热重配 | 下一步要把用户模型策略真正接入 per-SubWork eligibility |
| Model routing | `ModelRouter` 已存在；会按 required capabilities、SelfModel 学到的 route performance、reliability、cost、latency 评分 | 缺用户 pin/deny/privacy policy、per-SubWork eligibility、route health/concurrency 约束和真实多模型 E2E |
| Delegated Work / SubWork | **E2E-29 所需最小闭环已实现并真实验证** | 仍缺 dependency/DAG、stall/reroute/reassign、restart reconcile、并行与更完整 supervision |
| WorkerRun lifecycle | **已实现 durable queued/running/completed/failed/stale 与 verification/provenance** | 还需跨重启 supervision、cancel/reassign 和更广 worker 类型 |
| One-model multi-worker | **VERIFIED / E2E-29 closed** | 已证明一个实际 model route 可连续服务隔离 research/coding/review WorkerRun；下一步转向多模型策略 |
| Worker completion verification | **VERIFIED NARROW** | 已证明 worker `done` 不等于 WorkItem/root completion；继续扩大到更复杂 delegated Work |
| Stale delegated result protection | **VERIFIED NARROW** | 已有 plan-version stale result 保留但不得推进当前计划；继续覆盖更复杂 steering/restart |
| Autonomous Investigation / replanning | 已有基础机制和部分语义 re-ground | 仍偏已知模式驱动，需要更通用地处理目标不存在、状态冲突、worker failure/stall 和替代路径 |
| Long-task supervision | **部分闭环** | E2E-29 已验证失败 worker 后可继续形成新 WorkerRun 并最终完成；系统化 stall/reroute/reassign/restart 仍未闭合 |
| Installed N -> N+1 continuity | 不完整 | 真实升级过程中身份、数据、Work 和不确定副作用连续性尚未产品闭环 |

## E2E-29 已完成：一个模型，多 WorkerRun

2026-09-06 在 Windows X64 自托管 `zn-interactive` 上完成真实模型验收，当前实现已经证明：

- ZN Resident 仍是唯一长期 root task/completion owner；
- 一个实际 model route `default` 被重复用于多个不同 WorkerRun；
- research、coding、review 使用不同 durable WorkerRun、不同 `worker_run_id` / cognition request / model goal identity；
- WorkerContextPack 只携带受限当前任务上下文，不把完整 transcript、Memory、credentials 或其他 worker internals 倾倒进去；
- research worker 只拥有受限 Browser read；coding worker 拥有 workspace write + Terminal/Test + read-only Git 状态；review worker 无 workspace write；
- malformed proposal、execution failure 等尝试会终结当前 WorkerRun，新的语义重试得到新的 durable identity，不复用已绑定 goal id；
- worker 声称完成不会直接完成 Root Work；
- stale plan result 被保留为 stale provenance，但不能推进 current plan；
- 最终 Root completion 需要单独 verifier WorkItem、真实 Terminal 执行和 ZN Body 对声明持久化状态的 fresh reread。

真实验收 run：`34022287626`，HEAD `3b2a96633ed1d593f64e5526fb35ab460bd4ebeb`。

验收结果：

```text
ZN_E2E29_SKIPPED=0
ZN_E2E29_FAILURES=0
ZN_E2E29_ERRORS=0
ZN_E2E29_TERMINAL.success=true
model_route_id=default
```

同一 HEAD 的标准 `ZN CI` run `34022288706` 也为 success。

临时真模型 workflow 仅用于这一阶段 guarded acceptance，验收成功后已从工作分支删除；后续不要把它当长期 CI 基础设施恢复。

## 当前最大的产品缺口

当前优先级只围绕“普通用户真实任务能不能完成”排序：

1. **active Work steering 仍未闭合。** 用户在进行中说“登录先不做，先做核心功能”时，ZN 需要安全修改同一个 Work 的计划而不是拒绝、重开或重放。
2. **已有 ModelRouter 尚未成为真正受用户策略约束的 per-SubWork routing。** E2E-29 已证明 worker 数量与模型数量解耦，下一步应把 privacy/pin/deny、capability eligibility、route unavailable/fallback 和 provenance 接到现有 router，而不是新建 router。
3. **长任务 supervision / stall / reroute / restart 缺完整产品闭环。** E2E-29 能从单次 worker failure 继续，但还没有系统化 no-progress detection、reroute/reassign 和 Resident restart reconcile。
4. **真实 Browser/Desktop/File/Terminal 联合能力仍需继续扩大。** 调度系统没有真实工具也办不了事，因此 delegated Work 必须和现有 Body 主线一起用真实 E2E 推进。
5. **普通用户可见的长期任务 UX 仍不足。** 内部 WorkerRun/route/provenance 已有，但用户看到的应是可理解的进度、阻塞、权限与完成依据。

## 下一阶段真实 E2E 驱动项

详细验收见 `docs/ZN-REAL-TASK-E2E-CATALOG.md`。E2E-29 已关闭，不再作为未完成项重复施工。

1. **E2E-30 + E2E-42**：多模型按 SubWork 能力 routing，同时严格遵守用户 privacy/pin/deny 策略。
2. **E2E-28 + E2E-34**：worker/model failure、stall 和 Resident restart 后仍能 reconcile、reroute、继续。
3. **E2E-33 + E2E-27**：自然 continuation + active steering，同一个 durable Work 安全换方向。
4. 继续扩大 broad-goal 长任务与 Browser/Desktop/File/Terminal 的真实联合闭环，不横向建设独立 multi-agent 平台。

每项只补它真正需要的现有架构缺口；不要先实现完整通用 multi-agent framework。

## 判断产品完成的标准

不要把下面这些当成“产品已经完成”：

- 有代码；
- 有测试；
- CI green；
- 有 installer；
- 有 recovery module；
- 有新的抽象或 provider；
- 有多个 worker；
- 接入了多个模型；
- 某个 primitive 单独 verified。

真正要看的是：

```text
普通用户给正常人类任务
-> ZN 自己理解并保持 Root Work
-> 自己 Sense 当前电脑状态
-> 自己判断直接做还是拆 SubWork
-> 自己选择 cognition + tools + authority + verification
-> 必要时委派 bounded worker
-> 状态变化/worker失败/用户改方向后重新观察和判断
-> 保留 authority / fresh evidence / non-replay
-> 独立验证每个关键结果和最终用户目标
-> 中断、重启、跨天后能继续
```

## 当前开发原则

选择一个高价值真实用户任务，找到它真正缺的能力，只补这些缺口，打通完整 E2E，再进入下一个更难任务。

不要重新回到“单个 capability -> 大量 contract/test/CI -> 下一个 capability”的开发方式，也不要变成“multi-agent abstraction -> router abstraction -> worker framework -> 很久以后才做真实任务”。
