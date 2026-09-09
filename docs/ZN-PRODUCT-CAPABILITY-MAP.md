# ZN Product Capability Map

> 这是一份产品能力地图，不是 feature checklist。
>
> 真实代码、真实 Git、真实测试和真实 E2E 高于本文件。

Updated: 2026-09-09

## 1. 产品判断标准

ZN 的目标不是拥有最多 capability，而是让普通用户用正常语言交代事情以后，ZN 能长期、连续、可靠地把事情办完。

能力成熟度统一按下面判断：

```text
Exists
-> Connected
-> Verified
-> Product-closed
```

`VERIFIED NARROW` / `representative path closed` 不等于整个 capability 类别 product-closed。

## 2. Resident / continuity

| Product need | Current status | Remaining gap |
| --- | --- | --- |
| Persistent Self / identity | VERIFIED / PARTIAL product closure | 安装、升级、恢复后的长期连续性继续验证 |
| Resident long-lived process | VERIFIED | 更长时间真实运行场景 |
| Situation / Thought / Will loop | CONNECTED + VERIFIED | 更通用 investigation / cross-surface replanning |
| Durable Work | CONNECTED + VERIFIED | 更长周期、更多真实任务的 continuation breadth |
| Natural continuation / active steering | VERIFIED NARROW; E2E-27/33 closed representative path | 跨天、更复杂长期任务与多 workstream 用户体验 |
| Memory / learned context | PARTIAL | “上次怎么做”等更成熟真实长期体验 |
| Local Resident control plane | GUARDED / TRANSITIONAL | loopback TCP + per-process secret + endpoint ACL；长期 Windows transport 可继续收敛，但不是默认主线 |

## 3. Task ownership / delegation / routing

| Product need | Current status | Remaining gap |
| --- | --- | --- |
| ZN remains root task owner | VERIFIED NARROW | 在更多真实任务、跨 surface/长期使用中扩大证据 |
| Durable Work thread/item/run/artifact | CONNECTED + VERIFIED | 更广任务与 UX；不是缺 dependency substrate |
| Active user steering | VERIFIED NARROW | representative real same-Work steering/continuation 已关闭；更广长期使用继续扩大 |
| Delegation admission | CONNECTED + VERIFIED NARROW | 更多任务上验证 direct/delegated 判断 |
| Delegated coordinator | CONNECTED + VERIFIED NARROW | 现有 bounded supervision/readiness 上扩大真实任务；不是 general orchestrator |
| Delegated WorkerRun lifecycle | CONNECTED + VERIFIED NARROW | queued/running/completed/failed/stale、progress、bounded retry/reassign/reconcile 已有；通用无限期 scheduler 不在声明内 |
| One-model multi-worker | VERIFIED / E2E-29 CLOSED | 不再是设计缺口 |
| Multiple ModelRoute support | CONNECTED + VERIFIED NARROW | E2E-30/42 已按 current acceptance policy 关闭；双真实 provider family evidence 仍受 environment waiver 限定 |
| Kernel-owned ModelRouter | CONNECTED + VERIFIED NARROW | hard eligibility + dynamic health-aware routing 已接通；扩大 provider/task coverage |
| Dynamic provider health routing | VERIFIED NARROW; E2E-28/34 closed representative path | 更多 provider failure/长时运行 coverage |
| Route learning in SelfModel | EXISTS + VERIFIED NARROW | 更多真实 delegated outcomes 上继续校准 |
| Strict WorkerContextPack | CONNECTED + VERIFIED NARROW | 未来 worker 类型继续审计；不是完整 DLP |
| Worker action authority | CONNECTED + VERIFIED NARROW | Body action admission，不是 OS process sandbox |
| Worker completion verification | VERIFIED NARROW | 更复杂 Work 继续覆盖 |
| Stale delegated result protection | VERIFIED NARROW | E2E-27/33 已验证 old-worker protection；更多任务继续覆盖 |
| Stall/no-progress supervision | VERIFIED NARROW; E2E-28/34 closed representative path | heartbeat/no-progress/stall、bounded retry/reassign、restart reconcile 已有；更广长任务继续扩大 |
| Flat dependency/readiness | CONNECTED + VERIFIED NARROW | bounded same-Root/thread/current-plan sibling dependency、fan-in、restart durability、invalid graph fail closed；不是 general DAG |
| Delegated user progress | CONNECTED + VERIFIED NARROW / PARTIAL UX | privacy-safe projection 到既有 `work_progress` + Resident UI；复杂 multi-workstream UX 继续扩大 |

核心规则：**不要新建第二套 ModelRouter、第二套 Work/progress truth，也不要新建 Orchestrator Agent。**

### Routing boundary

现有 `ModelRouter` 采用：

```text
hard eligibility
-> legal candidates only
-> dynamic health / SelfModel / reliability / cost / latency scoring
```

hard eligibility 可拒绝 capability mismatch、retry excluded route、pin mismatch、explicit deny、declared unavailable/unhealthy、locality/privacy violation、missing policy tags、missing authority scopes 和 malformed policy。

E2E-30/42 已按仓库当前 acceptance policy 关闭，但 closure 含 owner-approved environment waiver：当时没有第二个真实 provider family。因此不能写成“两个真实 provider family 完整生产验证已完成”。Guarded two-provider acceptance 仍保留，并在真实双-provider配置时要求 no-skip / fail closed。

### Dependency/readiness boundary

当前实现是：

```text
bounded flat current-plan sibling dependency/readiness
same Root / thread / current plan
immutable dependency edges
derived readiness from durable Work truth
WorkerRun / cognition / completion gates
fan-in + restart durability
corrupt/cyclic/dangling/cross-plan fail closed
```

它不是 general-purpose DAG scheduler、recursive delegation、critical-path/resource-pool scheduler 或 generic dependency UX。Dependency 不继承 authority/tool scope。

## 4. Browser / User Browser

| Product need | Current status | Remaining gap |
| --- | --- | --- |
| Bounded BrowserScene sensing | VERIFIED NARROW | 更复杂 frame/site/layout coverage |
| Tab lifecycle/history | VERIFIED NARROW | 更复杂 real-site topology/navigation |
| Exact BrowserScene actions | VERIFIED NARROW | 当前 focus/type/check/uncheck/navigation + bounded command/control clicks；更多 semantic controls 继续扩大 |
| Managed causal popup | VERIFIED NARROW | bounded exact causal popup path 已有；任意 popup/site complexity 仍开放 |
| Browser file transfer | VERIFIED NARROW | exact authority-safe managed upload/download 已有；USER-plane file transfer 仍按当前安全边界 fail closed |
| User Browser Bridge | CONNECTED + VERIFIED NARROW | 真实已登录网站覆盖、授权 UX、漂移后的 stable re-ground |
| E2E-05 authenticated research mutation | CLOSED representative path | 不等于任意 authenticated site |
| E2E-07 causal USER child-tab | CLOSED representative path | general arbitrary popup/frame complexity 仍开放 |
| E2E-08 OTP user presence | CLOSED representative path | 仅 standard HTML `one-time-code` same tab/generation/origin；不是所有 MFA |
| Sensitive-field protection | GUARDED | 继续 fail closed；不复制 user profile/cookie/password/OTP secret |

E2E-08 明确不支持 CAPTCHA solving、WebAuthn/passkey automation、cross-origin IdP handoff、password automation、payment-field automation。

## 5. Windows / desktop computer use

| Product need | Current status | Remaining gap |
| --- | --- | --- |
| Machine/application awareness | CONNECTED + VERIFIED NARROW | 多源 inventory、deterministic identity、Installed/Running/Window/Foreground、bounded machine facts 已有；更多应用/系统语义继续扩大 |
| Identity-bound application launch | VERIFIED NARROW | 更多 app families/edge cases |
| Existing application activation | VERIFIED NARROW | Resident-admitted exact app/HWND/PID、fresh foreground proof 已有；任意多窗口拓扑/生命周期未闭环 |
| Foreground / focused-control sensing | VERIFIED | 更复杂窗口切换和应用生命周期 |
| Pointer / keyboard / text entry | VERIFIED NARROW | 完整真实任务继续验证 |
| Semantic desktop target re-ground | VERIFIED NARROW | 控件变化、窗口漂移、替代入口 |
| Cross-app task execution | VERIFIED NARROW; E2E-24 closed representative path | same-Root USER Browser -> exact File -> exact Desktop customer record 已有 bounded real closure；更复杂 Browser/Desktop/File/Terminal/Application 联合任务仍开放 |

## 6. Files / workspace / terminal / Git

| Product need | Current status | Remaining gap |
| --- | --- | --- |
| File read/write/search | CONNECTED + VERIFIED NARROW | 模糊来源、复杂整理、多文件任务 |
| Workspace evidence / exact source identity | PARTIAL | 歧义来源先解决身份再允许外部副作用 |
| Terminal/process | VERIFIED | 继续作为真实任务执行资源 |
| Git / repo task support | PARTIAL | 普通项目能力发展；不给 ZN 自身仓库特殊权限 |
| Coding specialist + real tools | VERIFIED NARROW | 扩大真实 repo 场景 |

## 7. Multi-surface and long-task real work

当前已有多条代表性组合闭环，但下一阶段重点是扩大完整真实任务，而不是继续证明单动作：

```text
normal human goal
-> Root Work
-> Sense current computer state
-> Situation / Thought
-> direct work OR bounded SubWork
-> policy-eligible cognition + tools + authority
-> action / WorkerRun
-> fresh observation
-> accept / reject / replan / reroute / steer
-> independent root completion evidence
-> durable continuation
```

E2E-24 已关闭一个 bounded 三-surface representative path：同一 Root Work 从显式授权的已登录 USER Browser 保持 exact business identity，经唯一 exact workspace target 的一次写入 + fresh reread，再重新建立当前 Desktop HWND/PID/UIA semantic authority并完成一次 exact record mutation；stale UIA RuntimeId 需要 fresh re-ground，ambiguous file target 必须 fail closed。它不等于 arbitrary cross-surface automation 或 general RPA。

## 8. Recovery / non-replay

| Product need | Current status | Remaining gap |
| --- | --- | --- |
| Resident restart recovery | CONNECTED + VERIFIED NARROW | 更多跨天/复杂真实 Work breadth |
| Delegated restart reconciliation | VERIFIED NARROW; E2E-28/34 | bounded restart-safe reconcile/no-replay 已有；更广任务继续覆盖 |
| Unknown external-effect handling | FAIL-CLOSED foundations exist | 不确定副作用继续不盲重放 |
| Fresh evidence before mutation | CORE RULE | 扩展到所有新任务和 delegated result acceptance |
| Independent completion verification | VERIFIED NARROW | 复杂 Work 继续覆盖 |
| Stale delegated result protection | VERIFIED NARROW | steering/restart/reassign breadth |

Recovery 是为了让真实任务继续，不是独立产品路线。

## 9. Product UX

| Product need | Current status | Remaining gap |
| --- | --- | --- |
| User-visible root task progress | PARTIAL | 更清晰的已完成/进行中/等待/阻塞/依据 |
| Delegated progress | CONNECTED + VERIFIED NARROW / PARTIAL UX | durable delegated facts 已投影到既有 progress truth；复杂 multi-workstream UX/解释质量继续扩大 |
| Permission / revoke UX | PARTIAL / OPEN | Browser、敏感操作、外部副作用授权范围 |
| Model/privacy policy UX | PARTIAL | hard policy 已落地；用户配置、解释与更广多-provider体验继续扩大 |
| Failure explanation | PARTIAL | 说明遇到什么、是否还能继续、需要用户做什么 |
| Completion result | PARTIAL | 明确完成了什么、没完成什么、依据是什么 |

用户不应该需要理解 worker_run_id、provider RPC、route-score 或 recovery internals。

## 10. Real E2E acceptance set

`docs/ZN-REAL-TASK-E2E-CATALOG.md` 保持 50 个原始真实任务定义。当前需要记住的代表性 closure：

- E2E-05 closed representative authenticated research/mutation；
- E2E-07 closed bounded causal USER child-tab path；
- E2E-08 closed representative OTP user-presence path；
- E2E-24 closed representative same-Root USER Browser -> exact File -> exact Desktop customer-record path；
- E2E-27/33 closed representative steering/continuation；
- E2E-28/34 closed representative supervision/dynamic-health/restart；
- E2E-29 closed one-route multi-worker；
- E2E-30/42 closed under documented current acceptance + environment-waiver semantics。

这些 closure 不等于 50 个 E2E 全部完成，也不等于上述 capability classes 全部 product-closed。

## 11. Release / update continuity

Installer、CI、Release、签名本身不是当前产品主线。Installed N -> N+1 的 identity/data/Work/uncertain-effect continuity 仍是独立未闭环问题；涉及 updater/rollback/signing/release trust 时必须保留高风险授权边界。

## 12. 已废弃：专用自我维护系统

专用“自我维护 / 自我修复 / upstream BUG report”路线已经删除。不要恢复 maintenance runtime/cognition/repair、BUG-report transport/intake、maintenance UI/RPC 或特殊 Git 权限路径。

## 13. 当前产品选择原则

不再按旧顺序重复开发 E2E-30/42、28/34、27/33 的 substrate。下一项应从真实剩余产品缺口中选择：

1. E2E-24 bounded closure 之外更复杂的 cross-surface real tasks；
2. Browser/User Browser 在真实站点和复杂 frame/dialog/navigation/用户在场边界的广度；
3. 现有 supervision/steering/restart 基础上的跨天/长期 continuity + progress/explanation UX；
4. 由真实 E2E 暴露的 Windows/application semantic gap；
5. 只有 owner 明确选择并授权时才进入高风险 installed-version continuity / release-trust work。

如果 current evidence 不能确定唯一下一任务，就保留选择标准，不凭空发明 roadmap。

## 14. 最终判断

**一个普通用户不学习 ZN 内部结构，只用正常语言告诉它事情，它现在比以前多能独立、连续、可靠地完成哪些真实任务？**

对长任务再问：**当用户中途改方向、worker/model/tool 失败、Resident 重启或任务跨天时，ZN 是否仍能在 current evidence 下盯住同一个目标继续办？**

如果答案没有明显改善，就不能把“更多模型、更多 worker、更多调度代码”当成产品主线已经推进。