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
| Persistent Self / identity | VERIFIED / PARTIAL product closure | 继续验证安装、升级、恢复后的长期连续性 |
| Resident long-lived process | VERIFIED | 继续覆盖真实长期运行场景 |
| Situation / Thought / Will loop | CONNECTED + VERIFIED | 更通用的 investigation / replanning / supervision |
| Durable Work | CONNECTED + VERIFIED | 自然引用、active steering、跨重启 delegated supervision 仍需产品化 |
| Memory / learned context | PARTIAL | “上次怎么做”“昨天那个继续”等真实长期体验仍需扩大 |

## 3. Task ownership / delegation / routing

| Product need | Current status | Remaining gap |
| --- | --- | --- |
| ZN remains root task owner | VERIFIED NARROW | E2E-29 已证明 worker/model 不夺取 Work/authority/completion；继续扩大到多模型与重启 |
| Durable Work thread/run/artifact | CONNECTED + VERIFIED | 已扩展最小 WorkItem/WorkerRun/plan_version/acceptance 语义；dependency 与完整 supervision 仍缺 |
| Active user steering | PARTIAL / OPEN | 用户改变方向时要更新同一个 Root Work，并处理 running/stale work |
| Delegated WorkerRun lifecycle | CONNECTED + VERIFIED NARROW | durable queued/running/completed/failed/stale 已实现；cancel/reassign/stall/restart 仍缺 |
| One-model multi-worker | **VERIFIED / E2E-29 CLOSED** | 一个实际 route 已服务隔离 research/coding/review WorkerRun；不再是设计缺口 |
| Multiple ModelRoute support | EXISTS + CONNECTED | 下一步需要用户策略和 per-SubWork eligibility/routing 闭环 |
| Kernel-owned ModelRouter | EXISTS + VERIFIED NARROW | 已按 capability/route evidence/reliability/cost/latency 评分；缺 privacy/pin/deny/health/concurrency gating |
| Route learning in SelfModel | EXISTS + VERIFIED NARROW | 需要在真实 delegated outcome 上继续学习哪个 route 对哪个领域有效 |
| Worker completion verification | **VERIFIED NARROW** | worker `done` 已被证明不等于 WorkItem/root completion；继续覆盖更复杂 Work |
| Bounded WorkerContextPack | **VERIFIED NARROW** | 已限制 root goal/current item/evidence/tool/authority；继续审计未来 worker 类型 |
| Worker authority isolation | **VERIFIED NARROW** | research read-only Browser、coding workspace/terminal、review no-write 已验证；继续扩大权限模型 |
| Stale delegated result protection | **VERIFIED NARROW** | plan_version stale result 可保留 provenance 但不能推进 current plan；继续覆盖 active steering/restart |
| Stall/no-progress supervision | PARTIAL / OPEN | E2E-29 可从失败 WorkerRun 继续，但系统化 stall -> reroute/reassign/replan 仍未闭合 |

核心规则：**不要新建第二套 model router，也不要新建 Orchestrator Agent。** 模型选择扩展现有 `ModelRouter`；任务分解/监督扩展现有 `Work`；最终 owner 继续是同一个 ZN。

E2E-29 的真实验收在 Windows X64 `zn-interactive` 上完成：一个 `default` route 连续服务 research/coding/review WorkerRun，最终由独立 verifier WorkItem + Terminal + fresh persisted-state reread 完成 Root acceptance；`SKIPPED=0 / FAILURES=0 / ERRORS=0`。

详细设计：`docs/ZN-DELEGATED-WORK-DESIGN.md`。

## 4. Browser

| Product need | Current status | Remaining gap |
| --- | --- | --- |
| Managed Browser | VERIFIED NARROW | 更广页面结构、popup/frame/download/upload、复杂失败恢复 |
| User Browser Bridge | CONNECTED + VERIFIED NARROW | 扩大真实已登录网站覆盖、授权 UX、漂移后的稳定重规划 |
| Semantic re-ground | VERIFIED NARROW | 从已知模式扩展到更通用的页面变化调查 |
| Sensitive-field protection | GUARDED | 继续保持 fail-closed，不复制用户 profile / cookie / password DB |

真实 User Browser Bridge 是产品主线。临时 profile 或隔离测试浏览器只能作为验证设施，不能替代用户现有登录 session 的产品能力。

## 5. Desktop computer use

| Product need | Current status | Remaining gap |
| --- | --- | --- |
| Foreground / focused-control sensing | VERIFIED | 更复杂窗口切换和应用生命周期 |
| Pointer / keyboard / text entry | VERIFIED NARROW | 继续在完整真实任务中验证，而不是单独堆 primitive |
| Semantic desktop target re-ground | VERIFIED NARROW | 控件变化、窗口漂移、替代入口需要更通用 investigation |
| Cross-app task execution | PARTIAL | 浏览器 + 桌面 + 文件三 surface 联合任务仍需扩大 |

## 6. Files / workspace / terminal / Git

| Product need | Current status | Remaining gap |
| --- | --- | --- |
| File read/write/search | CONNECTED + VERIFIED NARROW | 模糊来源、复杂整理、多文件任务 |
| Workspace evidence / exact source identity | PARTIAL | 歧义来源必须先解决身份，再允许外部副作用 |
| Terminal/process | VERIFIED | 继续作为真实任务执行资源，不单独追 milestone |
| Git / repo task support | PARTIAL | 作为普通项目工作能力继续发展，不给 ZN 自身仓库特殊权限 |
| Coding specialist + real tools | VERIFIED NARROW | E2E-29 已打通 coding cognition + workspace + Terminal/Test；继续扩大真实 repo 场景 |

## 7. Multi-surface and long-task real work

当前已经有 Browser + File、Browser + Desktop、File + Desktop 等真实闭环基础；E2E-29 又补上了 `Browser research -> coding workspace -> Terminal/Test -> review -> Root verification` 的一条真实长任务链。

下一阶段重点不是继续证明单动作，而是扩大这些完整任务：

```text
normal human goal
-> Root Work
-> Sense current computer state
-> Situation
-> Thought / Investigation
-> direct work OR create ready SubWork
-> select cognition + tools + authority + verification
-> action / delegated WorkerRun
-> fresh observation
-> accept / reject / replan / reroute / steer
-> independent root completion evidence
-> durable continuation
```

“帮我开发一个产品”是代表性长任务，不是为了把 ZN 变成 coding agent，而是用它验证通用个人助理是否具备：澄清、调查、计划、delegation、模型路由、代码/工具执行、监督、测试、失败恢复、用户 steering 和长期连续性。

## 8. Recovery / non-replay

| Product need | Current status | Remaining gap |
| --- | --- | --- |
| Resident restart recovery | VERIFIED / PARTIAL | 更多真实任务和 delegated runs 跨重启恢复 |
| Unknown external-effect handling | FAIL-CLOSED foundations exist | 继续保证不确定副作用不盲目重放 |
| Fresh evidence before mutation | CORE RULE | 扩展到所有新的真实任务和 delegated result acceptance |
| Independent completion verification | VERIFIED NARROW | E2E-29 已验证独立 Root verifier + fresh persisted reread；继续覆盖复杂 Work |
| Stale delegated result protection | VERIFIED NARROW | 已有 plan_version stale gate；继续覆盖 steering/restart/reroute |
| Fresh semantic retry identity | VERIFIED NARROW | malformed/failed WorkerRun 结束后新尝试使用新 durable identity，避免复用已绑定 goal id |

Recovery 是为了让真实任务能继续，不是独立产品路线。

## 9. Product UX

| Product need | Current status | Remaining gap |
| --- | --- | --- |
| User-visible root task progress | PARTIAL | 用户看到已完成/进行中/等待/阻塞，而不是内部 runtime id |
| Delegated progress | OPEN / INTERNAL FOUNDATIONS | WorkerRun 已有 durable status/provenance，但用户层仍需人类可懂表达 |
| Permission / revoke UX | PARTIAL / OPEN | Browser、敏感操作、外部副作用需要更清楚的授权范围 |
| Model/privacy policy UX | OPEN | 用户可指定主模型、coding preference、禁用 provider、敏感数据限制 |
| Failure explanation | PARTIAL | 说明遇到什么、是否还能继续、需要用户做什么 |
| Completion result | PARTIAL | 明确完成了什么、什么没完成、依据是什么 |

用户不应该需要理解 worker_run_id、provider RPC、semantic target、resident recovery 或 route-score 公式。

## 10. Real E2E acceptance set

`docs/ZN-REAL-TASK-E2E-CATALOG.md` 当前定义 50 个真实任务验收场景。E2E-29 已于 2026-09-06 完成真实模型验收并关闭；它证明的是“worker 数量与 model route 数量解耦”，不是“多模型 routing 已完成”。

下一组最直接的 delegated-work 验收应转向：

- E2E-30 + E2E-42：多模型、用户 policy、per-SubWork routing；
- E2E-28 + E2E-34：worker/model failure、stall、restart 后 supervision/reroute；
- E2E-33 + E2E-27：durable continuation + active steering。

不是要求一次性实现 50 个测试，而是作为长期产品验收集，按高价值真实任务纵向推进。

## 11. Release / update continuity

Installer、CI、Release、签名本身不是当前产品主线。

只有当它们直接阻塞真实用户长期安装、身份/Memory/Work 连续性、安全边界或数据可靠性时，才提升优先级。

当前真正未闭合的是：真实 N -> N+1 后，ZN 是否还是同一个长期存在的 ZN，原有身份、Memory、Work、配置和不确定副作用状态是否安全连续。

## 12. 已废弃：专用自我维护系统

专用“自我维护 / 自我修复 / upstream BUG report”路线已经明确删除。

它不是当前 capability，不是 backlog，不是 P0/P1/P2/P3，也不属于 near-term product order。

不要重新增加 maintenance runtime / cognition / repair、专用 BUG report transport/intake/reconcile、maintenance UI/IPC/RPC，或因为目标仓库是 ZN 就获得特殊 Git/合并/发布权限的路径。

详情见 `docs/ZN-RETIRED-DIRECTIONS.md`。

## 13. 当前产品优先顺序

E2E-29 已完成。下一阶段不能把 delegated work 扩成独立“multi-agent 平台工程”，而应继续服务真实任务：

1. 多模型按用户 policy / per-SubWork routing（E2E-30 + E2E-42）。
2. worker failure/stall/restart 后 supervision + reroute（E2E-28 + E2E-34）。
3. 自然 Work continuation + active steering（E2E-33 + E2E-27）。
4. 继续补真实 User Browser Bridge、Investigation/replanning 和跨 surface Body 能力。

支撑线默认包括 Installer、Release Candidate、签名、额外 CI、维护系统、文档整理、新 governance、新 provider、新状态机和新的抽象。只有它们直接阻塞真实任务时才升优先级。

## 14. 最终判断

每做完一个阶段，只看这件事：

**一个普通用户不学习 ZN 内部结构，只用正常语言告诉它事情，它现在比以前多能独立、连续、可靠地完成哪些真实任务？**

对长任务再多问一句：

**当用户中途改方向、某个 worker/model/tool 失败、Resident 重启或任务跨天时，ZN 是否仍然能自己盯住同一个目标继续办？**

如果答案没有明显改善，就不能把“接了更多模型、spawn 更多 worker、加了更多调度代码”当成产品主线已经推进。
