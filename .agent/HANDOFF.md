# ZN Maintainer Handoff

这是一份施工现场说明，不是产品路线的永久命令。

真实代码、真实 Git、真实测试和真实 CI 高于这份文档。接手时必须重新查询 `main`、相关 `work/*`、open PR 和 CI；只有历史任务仍明确引用 `dev/zn-agent` 时才把它作为兼容分支检查，不能再把它当新的开发主线。

Updated: 2026-09-06

## 当前产品定位

ZN 是长期常驻在个人电脑中的 **通用型个人助理**，不是办公 Agent、coding agent、browser agent、desktop automation agent 或 multi-agent framework 中的某一个。

用户面对的始终是一个 ZN。模型、specialist cognition、worker、Browser、Desktop、File、Terminal、Git、Web/API 都是 ZN 为完成用户目标而组合的资源。

核心边界：

```text
用户目标 / Root Work / continuity / authority / completion judgment = ZN owned
specialist cognition / delegated WorkerRun                       = bounded resource
real-world action                                                = Body/tools under authority
truth/completion                                                 = fresh evidence + ZN verification
```

长期仍按 `ZN.md`、`docs/ZN-OS-INTELLIGENCE-SUBSTRATE.md` 和 Personal Intelligence Layer 蓝图推进：优先原生/语义能力，再回退 UIA/DOM/visual computer use；认知资源可以本地/云端分层，但 CognitiveResource 永远不拥有事实、authority 或 completion。

## 当前真实仓库现场

- `main` 是唯一长期集成主线、canonical source 和 release branch。
- 新开发固定从最新 `main` 拉短命 `work/*`，PR 直接以 `main` 为 base；核心 CI 和适用真实 E2E 必须在 PR 阶段运行并通过。
- `dev/zn-agent` 只保留为历史兼容分支，不再接收新的产品开发或作为新 PR base。
- 专用 self-maintenance / self-repair / upstream BUG-report 产品路线已经废弃，不要恢复。
- 当前 E2E-29 工作分支：`work/e2e-29-one-model-multi-worker`，PR #188。
- E2E-29 已于 2026-09-06 完成真实模型验收；临时真模型 workflow 已删除，不要恢复为长期 CI。

## E2E-29 已正式关闭

### 用户能力变化

以前：ZN 虽然已有 Work、ModelRouter、CognitiveResource 和 Body，但不能证明“一个模型 route 被 ZN 当作多个隔离 worker 使用，同时 Root Work 仍由 ZN 自己持有并独立验收”。

现在：同一个实际 model route `default` 已真实服务多个不同 WorkerRun，完成 research、coding、review，并最终由独立 Root verifier 验收真实产物。

### 已实现的最小 delegated Work 基线

`runtime/python/zn_agent/core/evidence_bound_work.py` 现在有 durable WorkerRun / WorkerContextPack 基础：

- `worker_run_id`
- `work_item_id`
- `plan_version`
- `executor_kind`
- `model_goal_id`
- `model_route_id`
- `tool_scope`
- `authority_scope`
- `state = queued/running/completed/failed/stale`
- result / artifacts / verification / error / metrics provenance

WorkerRun identity 由 ZN 创建，模型不能自选 id、plan_version 或 authority。一个 WorkerRun 内 cognition/model goal identity 稳定；如果 malformed proposal 或当前语义尝试失败并终结 WorkerRun，下一次语义重试必须创建新的 WorkerRun/cognition/model goal identity，不能复用已经绑定到旧 task 的 durable goal id。

### bounded context

WorkerContextPack 只允许当前任务所需的 bounded context：root goal 摘要、当前 WorkItem objective/acceptance、plan_version、相关 evidence/artifact、tool/authority scope、forbidden actions 和 result schema。

不要把完整 transcript、Memory dump、SelfModel internals、credentials、其他 worker internals 或无关历史直接塞给 worker。

### 权限边界

已真实验证的 E2E-29 scopes：

- research：`managed_browser.navigate/read`，authority=`web_read`
- coding：workspace read/write + terminal python/test + read-only git status/diff
- review：workspace read + terminal verify + git status/diff，无 workspace write

任何 worker 都不能 push/release/message/accept Root。

### completion / stale 规则

- WorkerRun completed != WorkItem completed != Root Work completed。
- worker/model 的 “done/success” 不是 acceptance evidence。
- plan_version 已变化时旧 worker result 可保留为 stale provenance，但不得推进 current plan。
- Root completion 由 ZN 自己做 criterion-bound verification。

### 真实验收证据

Windows X64 self-hosted runner：`zn-interactive`。

真实模型 run：`34022287626`，验收 HEAD：`3b2a96633ed1d593f64e5526fb35ab460bd4ebeb`。

```text
ZN_E2E29_SKIPPED=0
ZN_E2E29_FAILURES=0
ZN_E2E29_ERRORS=0
ZN_E2E29_TERMINAL.success=true
model_route_id=default
```

真实路径中出现过 schema rejection、command mismatch、timeout 等失败尝试，但 ZN 没把它们当 Root failure；后续使用新的 WorkerRun 继续，最后出现 accepted research/coding/review，并由独立 verifier WorkItem 执行真实 Terminal 检查，再由 ZN Body fresh reread `data.json` 后完成 Root acceptance。

同一 HEAD 的标准 `ZN CI` run `34022288706` 也为 success。

这才是 E2E-29 关闭依据，不是“有代码”或“CI 绿”本身。

## 非常重要的真实代码事实

现有代码早已有 kernel-owned `ModelRouter`、Goal required capabilities、route reliability/cost/latency scoring、SelfModel route evidence learning 和多 provider resource seam。

所以：**禁止新建第二套 model router。**

E2E-29 又新增了一条同样重要的事实：**禁止把 WorkerRun 再升级成第二个 Resident/Agent control plane。** WorkerRun 是当前 Root Work 下的受限执行上下文，不拥有 scheduler/router/store/session/conversation/root completion。

## 下一阶段代码顺序

E2E-29 已关闭，不要继续在“单模型多 worker”上扩平台。下一步按真实 E2E 纵向推进：

### 1. Multi-model per-SubWork routing — E2E-30 + E2E-42

扩展现有 `ModelRouter` 的 eligibility/policy layer，而不是重写 router。最小范围：

- user primary model preference；
- coding/research/vision capability requirement；
- allow / deny / pin；
- privacy / locality constraint；
- route unavailable / fallback；
- selected route provenance 写回 WorkerRun；
- 用户策略先于 route scoring 做硬过滤。

不要提前实现完整并发 scheduler、复杂成本优化或独立 orchestration framework。

### 2. Supervision / stall / restart — E2E-28 + E2E-34

E2E-29 已证明单个失败 WorkerRun 后可以继续，但还没系统化闭合：

- repeated no-progress detection；
- bounded retry budget；
- reroute / reassign / replan；
- model unavailable；
- Resident restart 后 reconcile WorkItem/WorkerRun/plan/current reality；
- completed side effect 不 replay；
- stale result 不推进新计划。

### 3. Natural continuation + active steering — E2E-33 + E2E-27

用户说“昨天那个继续”“登录先别做”时，要修改同一个 durable Work 的当前计划，不能新开根任务，也不能重复已发生副作用。

### 4. 继续扩大真实 Body / cross-surface 能力

User Browser Bridge、Browser/Desktop/File/Terminal/Git、Investigation/replanning、restart/cross-day continuity 都继续保留主线地位。只有真实 E2E 因 OS semantic substrate 缺口被卡住时，再补对应 native integration；不要横向造 OSAgent/SystemAgent/DeviceAgent。

## 成熟案例吸收边界

- OpenAI Agents SDK：借 manager-style，专家在背后工作，user-facing owner 不 handoff 出 ZN。
- Magentic-One / AutoGen：借 task/progress ledger、stall->replan 思路，不引入第二 Orchestrator Agent。
- LangGraph：借 checkpoint/interrupt/non-rerun lesson，不替换 ZN Resident。
- OpenClaw / Hermes / OpenHuman：借 worker isolation、bounded authority、durable task/acceptance/supervision 思路，不复制其 control plane。
- provider/model gateway：只帮助完善现有 `ModelRouter` eligibility/policy，不另造 routing runtime。

## 安全和成本边界

- worker `done` 永远不是 root completion evidence；
- worker 不自动继承全部 Memory、credentials、tools、browser tabs、Git/release authority；
- user routing/privacy policy 在 route scoring 前作为硬过滤；
- 模型强不代表工具存在，工具强也不代表认知足够；
- wait/poll/status 等机械监督不要反复调用大模型；
- 真正 coding/research/reasoning 需要强模型时，不要为了省 token 降低任务质量；
- completed side effect 不因 replan/restart 自动 replay；
- old plan worker result 返回后必须检查 plan version/current reality；
- OS/system event 只提供 Situation evidence，不自动授权主动外部副作用。

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
- 哪些 cognition + workers + tools + OS/native capabilities 真正参与；
- worker/model/tool failure 是否能恢复；
- 用户还会在哪里失败；
- 下一个最阻塞真实使用的问题是什么。

不要拿 model 数量、worker 数量、Action 数量、OS API 数量、测试数量、PR 数、commit 数和 CI 当产品成绩。
