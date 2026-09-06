# ZN Product Capability Map

> 这是一份产品能力地图，不是 feature checklist。
>
> 真实代码、真实 Git、真实测试和真实 E2E 高于本文件。

Updated: 2026-09-06

## 1. 产品判断标准

ZN 的目标不是拥有最多 capability，而是让普通用户用正常语言交代事情以后，ZN 能长期、连续、可靠地把事情办完。

能力成熟度统一按下面判断：

```text
Exists
-> Connected
-> Verified
-> Product-closed
```

有代码、有单测、有 CI，只能证明前几层，不等于普通用户已经能稳定使用。

## 2. Resident / continuity

| Product need | Current status | Remaining gap |
| --- | --- | --- |
| Persistent Self / identity | VERIFIED / PARTIAL product closure | 安装、升级、恢复后的长期连续性继续验证 |
| Resident long-lived process | VERIFIED | 更长时间真实运行场景 |
| Situation / Thought / Will loop | CONNECTED + VERIFIED | 更通用 investigation / replanning / supervision |
| Durable Work | CONNECTED + VERIFIED | E2E-27/33 natural continuation + active steering、delegated restart supervision |
| Memory / learned context | PARTIAL | “上次怎么做”“昨天那个继续”等真实长期体验 |
| Local Resident control plane | GUARDED / TRANSITIONAL | 当前 loopback TCP + per-process secret + endpoint ACL；长期 Windows transport 仍应 Named Pipe + per-user SID ACL |

## 3. Task ownership / delegation / routing

| Product need | Current status | Remaining gap |
| --- | --- | --- |
| ZN remains root task owner | VERIFIED NARROW | 从 E2E-29 扩大到多模型、restart、steering |
| Durable Work thread/item/run/artifact | CONNECTED + VERIFIED | dependency 与完整 supervision |
| Active user steering | PARTIAL / OPEN | E2E-27/33 真实同一 Root Work steering/continuation |
| Delegation admission | CONNECTED + VERIFIED NARROW | 真实更多任务上证明 direct/delegated 判断，避免 pointless delegation |
| Delegated coordinator | CONNECTED + VERIFIED NARROW | dependency/DAG、stall/reassign/restart supervision |
| Delegated WorkerRun lifecycle | CONNECTED + VERIFIED NARROW | cancel/reassign/no-progress/restart supervision |
| One-model multi-worker | **VERIFIED / E2E-29 CLOSED** | 不再是设计缺口 |
| Multiple ModelRoute support | EXISTS + CONNECTED | 真实 E2E-30/E2E-42 multi-route policy/privacy closure |
| Kernel-owned ModelRouter | **CONNECTED + VERIFIED NARROW** | hard eligibility 已覆盖 capability/pin/deny/static availability-health/privacy-locality/policy tags/authority scopes；dynamic health→reroute 与真实 multi-route E2E 仍缺 |
| Route learning in SelfModel | EXISTS + VERIFIED NARROW | 真实 delegated outcomes 上继续学习领域可靠性 |
| Strict WorkerContextPack | **CONNECTED + VERIFIED NARROW** | 递归 fail-closed boundary 已落地；未来 worker 类型继续审计，不等于完整 DLP |
| Worker action authority | **CONNECTED + VERIFIED NARROW** | Body effect 前 durable revalidation 已落地；这是 action admission，不是 OS process sandbox |
| Worker completion verification | **VERIFIED NARROW** | 复杂 Work 继续覆盖 |
| Stale delegated result protection | **VERIFIED NARROW** | steering/restart/reroute 继续覆盖 |
| Stall/no-progress supervision | PARTIAL / OPEN | systematic no-progress -> reroute/reassign/replan 尚未闭合 |
| Dynamic provider health routing | OPEN / foundations exist | `ResidentHealthJournal` observation 尚未实时进入 eligibility；E2E-28/34 待闭合 |

核心规则：**不要新建第二套 ModelRouter，也不要新建 Orchestrator Agent。** 模型选择扩展现有 `ModelRouter`；任务分解/监督扩展现有 `Work`；最终 owner 继续是同一个 ZN。

### 当前 routing substrate 的准确边界

现有 `ModelRouter` 已采用两阶段选择：

```text
hard eligibility
-> only legal candidates remain
-> SelfModel/reliability/cost/latency soft scoring
```

hard eligibility 当前可拒绝：未声明 required capability、retry excluded route、pinned mismatch、explicit deny、declared unavailable/unhealthy、违反 locality/privacy、缺 policy tags、缺 authority scopes，以及 malformed route policy。

这已经消除了“违规 route 只是低分 fallback”的架构问题，但 **没有自动关闭 E2E-30/E2E-42**。真实验收仍需要多个 user-approved routes，并证明 forbidden provider 没有接触受限上下文。

## 4. Browser

| Product need | Current status | Remaining gap |
| --- | --- | --- |
| Managed Browser | VERIFIED NARROW | 更广页面结构、popup/frame/download/upload、复杂失败恢复 |
| User Browser Bridge | CONNECTED + VERIFIED NARROW | 扩大真实已登录网站覆盖、授权 UX、漂移后的稳定重规划 |
| Semantic re-ground | VERIFIED NARROW | 更通用页面变化调查 |
| Sensitive-field protection | GUARDED | 继续保持 fail-closed，不复制 user profile/cookie/password DB |

真实 User Browser Bridge 是产品主线。临时 profile 或隔离测试浏览器只能作为验证设施，不能替代用户现有登录 session 的产品能力。

## 5. Desktop computer use

| Product need | Current status | Remaining gap |
| --- | --- | --- |
| Foreground / focused-control sensing | VERIFIED | 更复杂窗口切换和应用生命周期 |
| Pointer / keyboard / text entry | VERIFIED NARROW | 完整真实任务继续验证 |
| Semantic desktop target re-ground | VERIFIED NARROW | 控件变化、窗口漂移、替代入口需要更通用 investigation |
| Cross-app task execution | PARTIAL | 浏览器 + 桌面 + 文件三 surface 联合任务 |

## 6. Files / workspace / terminal / Git

| Product need | Current status | Remaining gap |
| --- | --- | --- |
| File read/write/search | CONNECTED + VERIFIED NARROW | 模糊来源、复杂整理、多文件任务 |
| Workspace evidence / exact source identity | PARTIAL | 歧义来源必须先解决身份，再允许外部副作用 |
| Terminal/process | VERIFIED | 继续作为真实任务执行资源 |
| Git / repo task support | PARTIAL | 作为普通项目工作能力发展，不给 ZN 自身仓库特殊权限 |
| Coding specialist + real tools | VERIFIED NARROW | E2E-29 已打通 cognition + workspace + Terminal/Test；扩大真实 repo 场景 |

## 7. Multi-surface and long-task real work

当前已经有 Browser + File、Browser + Desktop、File + Desktop 等真实闭环基础；E2E-29 又验证了 `Browser research -> coding workspace -> Terminal/Test -> review -> Root verification` 的代表性长任务链。

下一阶段重点是完整任务，而不是继续证明单动作：

```text
normal human goal
-> Root Work
-> Sense current computer state
-> Situation / Thought
-> direct work OR bounded SubWork
-> select policy-eligible cognition + tools + authority
-> action / WorkerRun
-> fresh observation
-> accept / reject / replan / reroute / steer
-> independent root completion evidence
-> durable continuation
```

## 8. Recovery / non-replay

| Product need | Current status | Remaining gap |
| --- | --- | --- |
| Resident restart recovery | VERIFIED / PARTIAL | delegated runs 跨重启 supervision/reassign |
| Unknown external-effect handling | FAIL-CLOSED foundations exist | 不确定副作用继续保持不盲重放 |
| Fresh evidence before mutation | CORE RULE | 扩展到所有新任务和 delegated result acceptance |
| Independent completion verification | VERIFIED NARROW | 复杂 Work 继续覆盖 |
| Stale delegated result protection | VERIFIED NARROW | steering/restart/reroute |
| Fresh semantic retry identity | VERIFIED NARROW | failure 后继续确保新 durable identity |

Recovery 是为了让真实任务继续，不是独立产品路线。

## 9. Product UX

| Product need | Current status | Remaining gap |
| --- | --- | --- |
| User-visible root task progress | PARTIAL | 人类可懂的已完成/进行中/等待/阻塞 |
| Delegated progress | OPEN / INTERNAL FOUNDATIONS | durable status/provenance 已有，用户层表达仍缺 |
| Permission / revoke UX | PARTIAL / OPEN | Browser、敏感操作、外部副作用授权范围 |
| Model/privacy policy UX | OPEN / substrate exists | pin/deny/locality hard gates 已有；用户配置、解释和真实 multi-model体验尚未 product-close |
| Failure explanation | PARTIAL | 说明遇到什么、是否还能继续、需要用户做什么 |
| Completion result | PARTIAL | 明确完成了什么、什么没完成、依据是什么 |

用户不应该需要理解 worker_run_id、provider RPC、route-score 或 resident recovery internals。

## 10. Real E2E acceptance set

`docs/ZN-REAL-TASK-E2E-CATALOG.md` 定义 50 个真实任务验收场景。E2E-29 已于 2026-09-06 完成真实模型验收并关闭；它证明的是“worker 数量与 model route 数量解耦”，不是“多模型 routing 已完成”。

下一组最直接的 delegated-work 验收：

- **E2E-30 + E2E-42**：用已落地 hard eligibility substrate 跑真正 multi-route + privacy/policy acceptance；
- **E2E-28 + E2E-34**：worker/model failure、dynamic health、stall、restart 后 supervision/reroute；
- **E2E-33 + E2E-27**：durable continuation + active steering。

## 11. Release / update continuity

Installer、CI、Release、签名本身不是当前产品主线。只有直接阻塞真实用户长期安装、身份/Memory/Work 连续性、安全边界或数据可靠性时才提升优先级。

## 12. 已废弃：专用自我维护系统

专用“自我维护 / 自我修复 / upstream BUG report”路线已经明确删除。不要恢复 maintenance runtime/cognition/repair、BUG-report transport/intake、maintenance UI/RPC 或特殊 Git 权限路径。

## 13. 当前产品优先顺序

1. 真正关闭 multi-route policy/privacy（E2E-30 + E2E-42）。
2. worker/model failure、dynamic health、stall、restart supervision + reroute（E2E-28 + E2E-34）。
3. natural Work continuation + active steering（E2E-33 + E2E-27）。
4. 继续补真实 User Browser Bridge、Investigation/replanning 和跨 surface Body。

支撑线默认包括 Installer、Release Candidate、签名、额外 CI、文档、新 governance、新 provider、新状态机和新抽象；只有直接阻塞真实任务时才升优先级。

## 14. 最终判断

**一个普通用户不学习 ZN 内部结构，只用正常语言告诉它事情，它现在比以前多能独立、连续、可靠地完成哪些真实任务？**

对长任务再问：**当用户中途改方向、worker/model/tool 失败、Resident 重启或任务跨天时，ZN 是否仍能自己盯住同一个目标继续办？**

如果答案没有明显改善，就不能把“接了更多模型、spawn 更多 worker、加了更多调度代码”当成产品主线已经推进。
