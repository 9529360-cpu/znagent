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
- `dev/zn-agent` 只保留为历史兼容分支，不再接收新的产品开发或作为新 PR base；保留期间应与 `main` 对齐。
- 专用 self-maintenance / self-repair / upstream BUG-report 产品路线已经废弃，不要恢复。
- PR #188 的 E2E-29 工作已经合并；不要再把 `work/e2e-29-one-model-multi-worker` 当当前开发主线。
- E2E-29 已于 2026-09-06 完成真实模型验收；临时真模型 workflow 已删除，不要恢复为长期 CI。

## 已落地的 delegated-work substrate

当前 `main` 已经形成同一个 Resident 内的最小纵向链路：

```text
normal user goal
-> durable Root Work
-> bounded delegation admission
-> DelegatedWorkCoordinator inside the same Resident
-> short-lived durable WorkerRun
-> strict WorkerContextPack
-> single ModelRouter
-> Body action-authority revalidation
-> fresh evidence / verification
-> Root completion remains ZN-owned
```

这不是第二个 Resident、第二个 router 或独立 multi-agent control plane。

### Delegation admission

`BoundedDelegationPlanner` 只在目标真正需要多个有意义阶段时委派。小而确定的任务保持 direct path；显式否定 delegation/research/review 优先于关键词匹配，例如：

> `不要调研，也不要 review，直接实现。`

不得因为系统“支持 worker”就把每个请求都拆 worker。

### Coordinator ownership

`DelegatedWorkCoordinator` 是现有 Resident 的内部 composition。它复用同一个 Work ledger、ModelRouter、Body、store 和 Root completion authority，不拥有第二套 scheduler/session/control plane。

### Strict WorkerContextPack

active delegated runtime 使用严格递归边界，而不是靠调用方随手截断字符串：

- recursion depth / node / mapping / sequence / string limits；
- final serialized byte limit；
- acceptance/evidence/artifact/scope top-level limits；
- nested credential/token/transcript/Memory/SelfModel/other-worker internals fail closed；
- secret-like bearer/API/GitHub-token value rejection；
- provenance + data classification；
- malformed mapping keys 和 malformed `plan_version` fail closed；
- classification hook 可以收紧 route-facing policy。

`private` 本身不等于 cloud forbidden；当前明确的 `local_only` / `cloud_denied` 才进入 locality hard gate。不要把这层描述成完整 DLP。

### Worker action authority

WorkerRun 的 tool/authority/workspace/plan contract 会绑定到持久化 action intent，并在真实 Body effect 前再次读取 durable state 验证：

- research/review WorkerRun 不能通过低层 Body 路径获得 workspace mutation；
- coding write 被限制在 attached workspace；
- stale plan authority 在 effect 前拒绝；
- unknown Worker-authorized primitive fail closed；
- denial 仍进入现有 Body audit。

这是 **action admission boundary**，不是任意命令的 OS sandbox。不要在文档或产品声明中把它升级描述成进程级安全隔离。

### ModelRouter hard eligibility

现有单一 `ModelRouter` 已扩展为：先做 hard eligibility，再对合法候选做 soft scoring。已实现的 hard gates 包括：

- retry/runtime exclusion；
- required capability 必须显式声明；
- user pinned provider/model；
- denied provider/model；
- declared availability / health metadata；
- `local_only` / `cloud_forbidden` / `cloud_denied` locality policy；
- required policy tags；
- required authority-policy scopes；
- malformed route-policy type/member fail closed；
- 无合法 route 时明确 `NoRouteAvailable`，不静默回退到违规模型。

legacy 单模型 product shortcut 显式声明它已经承担的 general/reasoning/research/coding/language-understanding roles；显式 `zn_kernel.routes` 不获得未声明 capability 的历史默认分。

**仍未闭合：** dynamic `ResidentHealthJournal` observation 尚未成为实时 eligibility/reroute 输入；一次 transient provider failure 后的 bounded reroute/reassign 仍属于 E2E-28/E2E-34 supervision 工作。

## E2E-29 已正式关闭

2026-09-06 在 Windows X64 自托管 `zn-interactive` 上，真实模型 run `34022287626`（HEAD `3b2a96633ed1d593f64e5526fb35ab460bd4ebeb`）证明：一个实际 model route `default` 可以连续服务隔离 research/coding/review WorkerRun，而 Root Work、authority 和 completion judgment 始终由 ZN 持有。

```text
ZN_E2E29_SKIPPED=0
ZN_E2E29_FAILURES=0
ZN_E2E29_ERRORS=0
ZN_E2E29_TERMINAL.success=true
model_route_id=default
```

同一 HEAD 的标准 `ZN CI` run `34022288706` 也为 success。

这才是 E2E-29 关闭依据，不是“有 WorkerRun 代码”或“CI 绿”本身。

## 当前不要误报为已关闭的事项

- **E2E-30 / E2E-42 仍未 product-close。** hard routing/privacy substrate 已落地，但仍需要真正多 route、用户 policy/privacy 的端到端验收，证明不允许的 provider 从未收到受限项目上下文，并且每个选中 route 可追溯到它服务的 WorkItem/WorkerRun。
- **E2E-28 / E2E-34 仍未 product-close。** stale-run reconciliation 和 recovery foundations 已存在，但 dynamic health -> reroute、systematic no-progress supervision、restart-safe reassign 仍缺完整闭环。
- **E2E-27 / E2E-33 不能仅凭 plan-version/unit tests 宣称关闭。** active steering / natural continuation 需要正常用户语言到同一个 durable Work 的真实验收。
- Resident 本地 control plane 当前是 loopback TCP + per-process secret + endpoint ACL 的过渡实现；长期 Windows transport 仍应收敛到 Named Pipe + per-user SID ACL。

## 下一阶段代码顺序

### 1. 真实关闭 E2E-30 + E2E-42

不要再新造 eligibility abstraction；现有 hard gates 已经足够作为 substrate。下一步要做真实多模型验收：

- 多个 user-approved routes；
- per-SubWork capability routing；
- pin / deny / privacy / locality policy；
- selected route provenance；
- 明确证明 forbidden route 没看到受限数据；
- preferred route 不可用时只在仍满足 policy 的候选中 fallback。

### 2. Supervision / stall / restart — E2E-28 + E2E-34

重点补真实 supervision，而不是 worker 状态字段：

- repeated no-progress detection；
- bounded retry budget；
- dynamic model availability/health；
- reroute / reassign / replan；
- Resident restart 后 reconcile WorkerRun / WorkItem / plan/current reality；
- completed side effect 不 replay；
- stale result 不推进 current plan。

### 3. Natural continuation + active steering — E2E-33 + E2E-27

用户说“昨天那个继续”“登录先别做”时，要修改同一个 durable Work 的当前计划，不能新开根任务，也不能重复已发生副作用。

### 4. 继续扩大真实 Body / cross-surface 能力

User Browser Bridge、Browser/Desktop/File/Terminal/Git、Investigation/replanning、restart/cross-day continuity 都继续保留主线地位。只有真实 E2E 因 OS semantic substrate 缺口被卡住时，再补对应 native integration；不要横向造 OSAgent/SystemAgent/DeviceAgent。

## 安全和成本边界

- worker `done` 永远不是 root completion evidence；
- worker 不自动继承全部 Memory、credentials、tools、browser tabs、Git/release authority；
- user routing/privacy policy 在 route scoring 前作为硬过滤；
- 模型强不代表工具存在，工具强也不代表认知足够；
- wait/poll/status 等机械监督不要反复调用大模型；
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

优先说明用户能力变化、成功路径、参与的 cognition/workers/tools/authority/verification、失败恢复、仍会失败的地方和下一个真实阻塞。不要把 model 数量、worker 数量、Action 数量、测试数量、PR 数、commit 数或 CI 当产品成绩。
