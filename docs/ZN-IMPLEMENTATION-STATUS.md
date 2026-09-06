# ZN Implementation Status

这是一份当前实现事实表，不是 roadmap。真实代码、真实 Git、真实测试和真实 E2E 高于本文件。

Updated: 2026-09-06

## 仓库状态规则

- 唯一长期集成 / canonical / release 分支：`main`。
- 新开发从最新 `main` 拉短命 `work/*`，PR 直接以 `main` 为 base；适用 CI/E2E 在 PR 阶段通过后再合并。
- `dev/zn-agent` 只保留为历史兼容分支，不再接收新的产品开发或作为新 PR base；保留期间应与 `main` 对齐。
- 文档里的 SHA 和 CI run 只能当历史检查点，接手时必须重新查询。
- Git/CI/main 合并属于工程卫生，不是产品里程碑。

## 已废弃方向

专用“自我维护 / 自我修复 / upstream BUG report”产品路线已经明确废弃并从当前代码树中移除。不要重新增加 maintenance runtime、maintenance cognition/repair、专用 BUG-report transport/intake/reconcile、maintenance UI/IPC/RPC，或任何因为目标仓库是 ZN 就自动扩大权限的特殊路径。

通用 Health、Recovery、Work、Memory、File、Terminal、Git、Browser、Desktop、Computer Use 和 Update 架构继续保留。

## 当前能力事实

| 区域 | 当前状态 | 还缺什么 |
| --- | --- | --- |
| Resident Self / Body / Senses / Situation / Thought / Will | 已接通并有多轮验证 | 真实任务广度仍需继续扩大 |
| Durable Work / restart recovery | 已接通并验证 | 普通用户可感知的长期连续性与 delegated supervision 仍需扩大 |
| Managed Browser | 多个受限语义动作已验证 | 更广页面变化、弹窗、frame、下载上传等 |
| User Browser Bridge | 已有 existing-session 授权路径和语义控制基础 | 真实网站覆盖、授权 UX、漂移后的稳定重规划 |
| File / workspace tasks | 已有自然语言文件任务和跨 surface 闭环证据 | 歧义来源、复杂整理和更广任务类型 |
| Desktop computer use | 多个窄场景已真实验证 | 通用跨应用连续任务、窗口变化和目标漂移 |
| Browser + File / Browser + Desktop | 已有代表性真实闭环 | 三个 surface 联合与复杂重规划 |
| Work continuity | durable ledger、restart recovery、plan version 与 stale-result foundations 已存在 | E2E-27/E2E-33 真实 natural continuation + active steering 尚未 product-close |
| Cognitive resources | ZN-owned provider seam、多 route、热重配已存在 | transient health supervision、成本/并发策略继续扩大 |
| Model routing | **hard eligibility + soft scoring 已接通并验证窄范围** | E2E-30/E2E-42 真正多模型 policy/privacy 闭环；dynamic health→reroute 尚缺 |
| Delegation admission | **CONNECTED + VERIFIED NARROW** | 继续用真实任务验证何时 direct、何时 delegated；避免 pointless delegation |
| Delegated Work coordinator | **CONNECTED + VERIFIED NARROW** | dependency/DAG、stall/reroute/reassign、restart supervision 仍缺 |
| WorkerRun lifecycle | durable queued/running/completed/failed/stale + provenance/verification | cancel/reassign、systematic no-progress、跨重启 supervision |
| One-model multi-worker | **VERIFIED / E2E-29 CLOSED** | 已证明一个实际 route 服务隔离 research/coding/review；不再是设计缺口 |
| Strict WorkerContextPack | **CONNECTED + VERIFIED NARROW** | 未来 worker 类型继续审计；不是完整 DLP |
| Worker action authority | **CONNECTED + VERIFIED NARROW** | 当前是 Body action admission，不是任意命令 OS sandbox |
| Worker completion verification | **VERIFIED NARROW** | 继续覆盖更复杂 delegated Work |
| Stale delegated result protection | **VERIFIED NARROW** | 继续覆盖 active steering/restart/reroute |
| Autonomous Investigation / replanning | 基础机制和部分语义 re-ground 已存在 | 更通用处理目标不存在、冲突、worker failure/stall 与替代路径 |
| Long-task supervision | **PARTIAL / OPEN** | dynamic health、no-progress、reroute/reassign、restart reconcile 尚未完整闭合 |
| Resident local control plane | loopback-only authenticated endpoint + per-process secret + endpoint ACL 已加固 | Windows 最终 transport 仍应收敛 Named Pipe + per-user SID ACL |
| Installed N -> N+1 continuity | 不完整 | 真实升级过程中身份、数据、Work 和不确定副作用连续性尚未 product-close |

## Delegated-work substrate 已落地

当前 `main` 的 delegated-work 主链不是独立 multi-agent 平台，而是现有 Resident/Work/Router/Body 的纵向扩展：

```text
Root Work
-> BoundedDelegationPlanner
-> DelegatedWorkCoordinator (same Resident)
-> durable short-lived WorkerRun
-> strict WorkerContextPack
-> existing ModelRouter hard eligibility
-> existing Body action-authority gate
-> fresh verification
-> Root completion remains ZN-owned
```

### Admission

小而确定的目标走 direct path。显式 negation 优先于关键词，例如 `不要调研，也不要 review，直接实现。` 不应产生 research/review workers。

### WorkerContextPack

active delegated runtime 已使用递归 fail-closed boundary：depth/node/item/string/final-size limits、nested sensitive-key rejection、secret-like token rejection、provenance、classification hook、原生字符串 mapping key 与正整数 plan version 校验。

`private` 并不自动等于 cloud forbidden；当前 routing locality gate 以 `local_only` / `cloud_denied` / `cloud_forbidden` 等明确策略为准。

### Action authority

WorkerRun authority 在真实 Body effect 前从 durable Work/WorkerRun state 重新验证。review/research 不能借低层 Body path 获得 workspace mutation；coding write 受 attached workspace 约束；stale plan 会被拒绝。

这是一层 **action admission boundary**，不是进程/命令级 OS sandbox。

### ModelRouter hard eligibility

现有单一 `ModelRouter` 已改为先 hard-filter，再 soft-score。hard gates 已覆盖：

- required capability 必须显式声明；
- retry/runtime exclusion；
- pinned provider/model；
- denied provider/model；
- declared availability/health；
- locality/privacy (`local_only` / `cloud_forbidden` / `cloud_denied`)；
- required policy tags；
- required authority scopes；
- malformed route policy/list member fail closed；
- no eligible route => `NoRouteAvailable`，不违规 fallback。

route eligibility metadata 继续走现有 ModelRoute/config path，没有第二套 router/policy store。

**未完成：** `ResidentHealthJournal` 的动态 provider observation 尚未实时进入 router eligibility；因此 transient model failure -> policy-safe reroute/reassign 仍属于后续 supervision。

## E2E-29 已完成：一个模型，多 WorkerRun

2026-09-06 在 Windows X64 自托管 `zn-interactive` 上完成真实模型验收。真实模型 run `34022287626`，HEAD `3b2a96633ed1d593f64e5526fb35ab460bd4ebeb`：

```text
ZN_E2E29_SKIPPED=0
ZN_E2E29_FAILURES=0
ZN_E2E29_ERRORS=0
ZN_E2E29_TERMINAL.success=true
model_route_id=default
```

这证明一个实际 route 可连续服务隔离 research/coding/review WorkerRun，且 worker completion 不夺取 Root completion；最终需要独立 verifier、真实 Terminal 和 fresh persisted-state reread。

## 当前最大的产品缺口

1. **E2E-30 + E2E-42 尚未 product-close。** policy/eligibility substrate 已存在，但仍需真实多个 user-approved routes、真实 privacy/pin/deny、route provenance 与“forbidden provider 没收到受限上下文”的端到端证据。
2. **Long-task supervision / dynamic reroute 仍未闭合。** 需要 no-progress detection、bounded retry、dynamic provider health、policy-safe reroute/reassign，以及 restart reconcile。
3. **E2E-27 + E2E-33 尚未 product-close。** plan-version/stale gates 是 foundation，不等于正常用户语言下对同一个 durable Work 的 steering/continuation 已完成。
4. **真实 Browser/Desktop/File/Terminal 联合能力仍需扩大。** delegated Work 没有真实 Body 能力仍办不了用户任务。
5. **普通用户可见的长期任务 UX 仍不足。** 用户应看到可理解的进度、阻塞、授权和完成依据，而不是内部 WorkerRun/route ids。

## 下一阶段真实 E2E 驱动项

1. **E2E-30 + E2E-42**：直接用现有 hard eligibility substrate 跑真正 multi-route + privacy/policy E2E；不再先造 routing abstraction。
2. **E2E-28 + E2E-34**：worker/model failure、stall、dynamic health、restart 后 supervision + reroute/reassign。
3. **E2E-33 + E2E-27**：natural continuation + active steering，同一个 durable Work 安全换方向。
4. 继续扩大 broad-goal 与 Browser/Desktop/File/Terminal 的真实联合闭环。

## 判断产品完成的标准

代码、单测、CI、installer、provider、多个 worker 或多个模型都不是 product closure。真正要看的是：

```text
普通用户给正常人类任务
-> ZN 保持 Root Work
-> Sense 当前电脑状态
-> 判断 direct / delegated
-> 选择 cognition + tools + authority + verification
-> 状态变化/失败/用户改方向后重新观察和判断
-> 保留 authority / fresh evidence / non-replay
-> 独立验证关键结果和最终目标
-> 中断、重启、跨天后仍能继续
```

每次只补高价值真实 E2E 真正缺的能力，不回到“先造完整 multi-agent/router/framework，再很久以后验证用户任务”的路线。
