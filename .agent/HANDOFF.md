# ZN Maintainer Handoff

这是一份施工现场说明，不是产品路线的永久命令。

真实代码、真实 Git、真实测试和真实 CI 高于这份文档。接手时必须重新查询 `main`、`dev/zn-agent`、相关 work branch、open PR 和 CI，不能把这里写的 SHA 或状态当成永远正确。

## 当前产品定位

ZN 是长期常驻在个人电脑中的 **通用型个人助理**，不是办公 Agent、coding agent、browser agent、desktop automation agent 或 multi-agent framework 中的某一个。

用户面对的始终是一个 ZN。模型、specialist agent、worker、Browser、Desktop、File、Terminal、Git、Web/API 都是 ZN 为完成用户目标而组合的资源。

核心边界：

```text
用户目标 / Root Work / continuity / authority / completion judgment = ZN owned
specialist cognition / delegated worker                         = bounded resource
real-world action                                               = Body/tools under authority
truth/completion                                                = fresh evidence + ZN verification
```

## 当前真实仓库现场

- `dev/zn-agent` 是固定主开发分支；`main` 是 canonical/release branch。
- 专用 self-maintenance / self-repair / upstream BUG-report 产品路线已经废弃，不要恢复。
- open PR #166：`Continue durable Work from natural references and fresh follow-ups`。它处理“刚才/上次/昨天那个继续”等 durable Work continuity，并明确把 **active task steering** 留作独立未解决产品问题。接手时必须重新查询该 PR 的实际 mergeability/base/head，不要依赖这里的历史状态。
- 2026-09-04 已完成 delegated Work / model routing 的产品调研与设计文档，但这些是设计事实，不等于 runtime 已实现。

## 已完成的策划/调研文档

先读：

1. `ZN.md`
2. `docs/ZN-NEXT-PHASE.md`
3. `docs/ZN-ORCHESTRATION-RESEARCH.md`
4. `docs/ZN-DELEGATED-WORK-DESIGN.md`
5. `docs/ZN-REAL-TASK-E2E-CATALOG.md`
6. `docs/ZN-IMPLEMENTATION-STATUS.md`
7. `docs/ZN-PRODUCT-CAPABILITY-MAP.md`

其中：

- `ZN-ORCHESTRATION-RESEARCH.md`：OpenClaw、Hermes Agent、OpenHuman、Magentic-One/AutoGen、LangGraph、OpenAI Agents SDK、Claude Code、model gateway 等成熟机制的取舍。
- `ZN-DELEGATED-WORK-DESIGN.md`：如何在现有 Work / ModelRouter / CognitiveResource / Body 上实现 SubWork、WorkerRun、supervision、steering、routing、restart continuity。
- `ZN-REAL-TASK-E2E-CATALOG.md`：50 个真实用户 E2E 长期验收场景。

## 非常重要的真实代码事实

不要误以为“模型路由还没有”。现有代码已经有：

- `runtime/python/zn_agent/core/router.py` 的 kernel-owned `ModelRouter`；
- `Goal.required_capabilities`；
- `ModelRoute.capabilities/reliability/cost_weight/latency_weight`；
- `SelfModel.route_score()` 和 verified outcome-driven route learning；
- `provider_bridge.py` 的多 route 配置、OpenAI-compatible/Anthropic/Gemini resource seam 和 hot reconfigure。

所以 **禁止新建第二套 model router**。

真正缺口是 Work 层：当前 `ResidentWorkLedger` 有 durable thread/message/artifact/run，但没有完整 durable：

```text
WorkItem / SubWork
dependency
plan version
executor / WorkerRun
acceptance criteria / acceptance evidence
blocker
stale delegated result
stall / reroute / reassign
active user steering
```

这才是下一阶段调度主线。

## 当前产品主线

当前最高价值目标是让 ZN 能处理这种真实任务：

> “帮我开发一个个人记账产品。你先调研一下市场，跟我确认关键方向，然后自己推进，做出能运行的第一版。”

ZN 应该能：

```text
理解 / 关键澄清
-> 自主调研
-> Root Work
-> 滚动拆 WorkItem
-> 判断直接做还是 delegated worker
-> 选择 cognition + tools + authority + verification
-> 单模型也能多个 worker
-> 多模型时按用户策略 + capability + route evidence 路由
-> 监督 progress / blocker / stall
-> worker/model/tool 失败后重新调查 / reroute / reassign
-> 用户中途改方向时 steering 同一个 Work
-> restart / cross-day 后继续
-> 最终验证真实产物，而不是相信 worker/model done
```

## 下一步代码开发顺序

不要先做完整 multi-agent framework。按下面真实 E2E 纵向推进：

### 1. Natural continuation + active steering

对应：E2E-33 + E2E-27。

用户：

> “昨天那个产品继续。登录先别做，先把核心记账跑起来。”

先处理/整合 PR #166 的自然 continuation 基础，然后补 active Work steering、最小 plan version / WorkItem semantics。完成后用户改方向不再需要新开任务，也不会重放已发生副作用。

### 2. Broad goal -> researched runnable MVP

对应：E2E-26。

用户从一句宽目标开始，ZN 调研、拆工作、调用 coding cognition + File/Git/Terminal/Test，最后必须得到可运行并验证的第一版。

只在这个 E2E 真正需要的位置加入 delegated Work；不要横向先做所有 worker 类型。

### 3. One model, multiple workers

对应：E2E-29。

只配置一个 model route，也能把 research / coding / review 分成隔离 WorkItem/WorkerRun；证明 worker 数与模型数完全解耦。

### 4. Multi-model per-SubWork routing

对应：E2E-30 + E2E-42。

扩展现有 `ModelRouter` 的 **eligibility/policy layer**，而不是重写 router。先支持：

- user primary model preference；
- coding/research/vision capability requirement；
- allow/deny/pin；
- privacy/locality constraint；
- route unavailable/fallback；
- route provenance in WorkerRun。

### 5. Supervision / stall / restart

对应：E2E-28 + E2E-34。

worker 重复失败、模型不可用、无进展或 Resident 重启时，ZN 要 reconcile real state、fresh Sense、Situation/Thought，然后 reroute/reassign/replan，而不是根任务直接失败或盲重试。

## 与三类参考产品的吸收关系

- OpenClaw：借 worker isolation、push completion、bounded concurrency、scoped tools、existing-session browser UX；不借它成为新的控制平面。
- Hermes Agent：借 strong planner + cheaper/specialist workers、final-summary-only、terminal isolation、bounded leaf authority、经验学习触发；不新增 Hermes-style skill runtime。
- OpenHuman：借 durable goals/task board、acceptance evidence、steering、checkpoint/resume、user-readable progress；不引入第二 workflow/graph resident。
- Magentic-One：借 task/progress ledger 和 stall->replan 思路，分别落入现有 Work + Situation/Thought。
- LangGraph：借 checkpoint/interrupt/non-rerun lesson，不替换 ZN Resident。
- OpenAI Agents SDK：坚持 manager-style，专家在背后工作，用户-facing owner 不 handoff 出 ZN。

## 安全和成本边界

- worker `done` 永远不是 root completion evidence；
- worker 不自动继承全部 Memory、credentials、tools、browser tabs、Git/release authority；
- user routing/privacy policy 在 route scoring 前作为硬过滤；
- 模型强不代表工具存在，工具强也不代表认知足够；
- wait/poll/status 等机械监督不要反复调用大模型；
- 真正 coding/research/reasoning 需要强模型时，不要为了省 token 降低任务质量；
- completed side effect 不因 replan/restart 自动 replay；
- old plan worker result 返回后必须检查 plan version/current reality，不能直接推进新计划。

## 继续保留的其他产品主线

Delegated Work 不取代：

- real User Browser Bridge；
- Browser/Desktop/File/Terminal/Git 真正工具能力；
- Autonomous Investigation/replanning；
- Memory/learning；
- restart/cross-day continuity；
- ordinary-user task/progress/permission UX。

调度只有和真实 Body/tool 一起工作才有产品价值。

## 接手者每次开始工作先问

1. 普通用户现在具体在哪个真实任务上卡住？
2. 这次修改是不是直接关掉这个卡点？
3. 如果不做它，真实任务具体停在哪里？
4. 有没有更直接的改法？
5. 完成以后 `ZN-REAL-TASK-E2E-CATALOG.md` 的哪个 E2E 会从失败/partial 变成 verified？

如果第 5 条答不出来，默认重新评估。

## 收尾怎么汇报

优先说明：

- ZN 以前不能完成什么真实任务；
- 现在能完成什么；
- 成功路径是什么；
- 哪些 cognition + workers + tools 真正参与；
- worker/model/tool failure 是否能恢复；
- 用户还会在哪里失败；
- 下一个最阻塞真实使用的问题是什么。

不要拿 model 数量、worker 数量、测试数量、PR 数、commit 数和 CI 当产品成绩。