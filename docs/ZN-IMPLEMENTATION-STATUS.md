# ZN Implementation Status

这是一份当前实现事实表，不是 roadmap。真实代码、真实 Git、真实测试和真实 CI 高于本文件。

## 仓库状态规则

- 主开发分支：`dev/zn-agent`
- canonical / release 分支：`main`
- 文档里的 SHA 和 CI run 只能当历史检查点，接手时必须重新查询。
- Git/CI/main 同步属于工程卫生，不是产品里程碑。

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
| Cognitive resources | 已支持 OpenAI-compatible / Anthropic / Gemini 等 ZN-owned resource seam，可多 route、可热重配 | 需要把资源选择真正用于 delegated SubWork，而不是只停留在单 Goal cognition |
| Model routing | `ModelRouter` 已存在；会按 required capabilities、SelfModel 学到的 route performance、reliability、cost、latency 评分 | 缺用户 pin/deny/privacy policy、per-SubWork eligibility、route health/concurrency 约束和真实多模型 E2E |
| Delegated Work / SubWork | **未实现完整产品能力** | 当前 Work 没有 durable WorkItem/SubWork、dependency、executor、acceptance evidence、plan version、worker supervision |
| Autonomous Investigation / replanning | 已有基础机制和部分语义 re-ground | 仍偏已知模式驱动，需要更通用地处理目标不存在、状态冲突、worker failure/stall 和替代路径 |
| Long-task supervision | **未产品闭环** | 缺 event-driven worker lifecycle、stall detection、reroute/reassign、user steering、restart reconcile |
| Installed N -> N+1 continuity | 不完整 | 真实升级过程中身份、数据、Work 和不确定副作用连续性尚未产品闭环 |

## 这轮策划已完成但尚未等于实现

2026-09-04 已完成一轮成熟同类产品/框架调研，并把下一阶段设计写入：

- `docs/ZN-ORCHESTRATION-RESEARCH.md`
- `docs/ZN-DELEGATED-WORK-DESIGN.md`
- `docs/ZN-REAL-TASK-E2E-CATALOG.md`
- `docs/ZN-NEXT-PHASE.md`

调研覆盖 OpenClaw、Hermes Agent、OpenHuman、Magentic-One/AutoGen、LangGraph、OpenAI Agents SDK、Claude Code 以及 model-gateway 类实践。

这些文档证明“方向已经收敛”，不证明 delegated Work 或多模型调度已经存在于 runtime。

## 当前最大的产品缺口

当前优先级只围绕“普通用户真实任务能不能完成”排序：

1. **Root Work 还不能真正监督复杂 SubWork。** 这是“帮我开发一个产品并持续推进”这类长任务最直接的阻塞。现有 Work 有 thread/message/artifact/run 和恢复，但没有 task decomposition/dependency/delegated executor/acceptance 的 durable product semantics。
2. **active Work steering 仍未闭合。** 用户在进行中说“登录先不做，先做核心功能”时，ZN 需要安全修改同一个 Work 的计划而不是拒绝、重开或重放。PR #166 解决自然 continuation 的重要基础，但其说明也明确把 active steering 留作后续问题。
3. **已有 ModelRouter 尚未成为真正的 per-SubWork routing。** 不能再造第二套 router；应把用户模型策略、privacy/pin/deny、SubWork capability 和 route health 接到现有选择链。
4. **长任务 supervision / stall / reroute 缺产品闭环。** worker/model/tool 失败后，ZN 应重新 Sense/Situation/Thought、收集 fresh evidence、换路径/模型/工具，而不是 fire-and-forget 或根任务直接失败。
5. **真实 Browser/Desktop/File/Terminal 联合能力仍需继续扩大。** 调度系统没有这些真实工具也办不了事，因此 delegated Work 必须和现有 Body 主线一起用真实 E2E 推进。

## 下一阶段五个真实 E2E 驱动项

详细验收见 `docs/ZN-REAL-TASK-E2E-CATALOG.md`。推荐连续顺序：

1. **E2E-33 + E2E-27**：`昨天那个继续` + active steering，同一个 durable Work 安全换方向。
2. **E2E-26**：从“帮我开发一个个人记账产品”出发，调研、拆 Work、开发、测试并形成可运行 MVP。
3. **E2E-29**：只有一个模型时，仍可以有多个隔离 worker / WorkItem，证明 worker 数量与模型数量解耦。
4. **E2E-30 + E2E-42**：多模型按任务能力 routing，同时严格遵守用户 privacy/pin/deny 策略。
5. **E2E-28 + E2E-34**：worker/model failure、stall 和 Resident restart 后仍能 reconcile、reroute、继续。

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