# ZN Product Capability Map

> 这是一份产品能力地图，不是 feature checklist。
>
> 真实代码、真实 Git、真实测试和真实 E2E 高于本文件。

Updated: 2026-09-04

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
| Durable Work | CONNECTED + VERIFIED | 自然引用、active steering、SubWork、跨重启继续需要产品化 |
| Memory / learned context | PARTIAL | “上次怎么做”“昨天那个继续”等真实长期体验仍需扩大 |

## 3. Task ownership / delegation / routing

| Product need | Current status | Remaining gap |
| --- | --- | --- |
| ZN remains root task owner | ARCHITECTURE CONTRACT + existing resident ownership | 继续在 delegated E2E 中证明 worker/model 不夺取 Work/authority/completion |
| Durable Work thread/run/artifact | CONNECTED + VERIFIED | 需要扩展成真实 WorkItem/SubWork/dependency/acceptance semantics |
| Active user steering | PARTIAL / OPEN | 用户改变方向时要更新同一个 Root Work，并处理 running/stale work |
| Delegated worker lifecycle | DESIGN ONLY / NOT PRODUCT-CLOSED | 缺 bounded WorkerRun、tool scope、result ingestion、cancel/reassign/stall handling |
| One-model multi-worker | DESIGN ONLY | 需要真实 E2E 证明 worker 数量和 model route 数量解耦 |
| Multiple ModelRoute support | EXISTS + CONNECTED | 需要真实用户策略和 per-SubWork 路由闭环 |
| Kernel-owned ModelRouter | EXISTS + VERIFIED NARROW | 已按 capability/route evidence/reliability/cost/latency 评分；缺 privacy/pin/deny/health/concurrency gating |
| Route learning in SelfModel | EXISTS + VERIFIED NARROW | 需要在真实 delegated outcome 上学习哪个 route 对哪个领域有效 |
| Worker completion verification | CORE DESIGN / partial evidence elsewhere | 需要明确 WorkerRun `done` 不等于 WorkItem/root completion |
| Stall/no-progress supervision | OPEN | 重复失败、无新 evidence、worker lost 等要回到 Situation/Thought/Investigation |

核心规则：**不要新建第二套 model router，也不要新建 Orchestrator Agent。** 模型选择扩展现有 `ModelRouter`；任务分解/监督扩展现有 `Work`；最终 owner 继续是同一个 ZN。

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
| Coding specialist + real tools | PARTIAL FOUNDATIONS | 要打通 coding cognition + File/Git/Terminal/Test + runtime verification，而不是只生成代码建议 |

## 7. Multi-surface and long-task real work

当前已经有 Browser + File、Browser + Desktop、File + Desktop 等真实闭环基础。

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
| Independent completion verification | VERIFIED NARROW | 继续覆盖复杂 WorkItem/root Work |
| Stale delegated result protection | DESIGN ONLY | plan version 改变后旧 worker 结果不能自动推进新计划 |

Recovery 是为了让真实任务能继续，不是独立产品路线。

## 9. Product UX

| Product need | Current status | Remaining gap |
| --- | --- | --- |
| User-visible root task progress | PARTIAL | 用户看到已完成/进行中/等待/阻塞，而不是内部 runtime id |
| Delegated progress | OPEN | 子任务/worker 应显示人类可懂的工作状态，不展示模型 plumbing 为主 |
| Permission / revoke UX | PARTIAL / OPEN | Browser、敏感操作、外部副作用需要更清楚的授权范围 |
| Model/privacy policy UX | OPEN | 用户可指定主模型、coding preference、禁用 provider、敏感数据限制 |
| Failure explanation | PARTIAL | 说明遇到什么、是否还能继续、需要用户做什么 |
| Completion result | PARTIAL | 明确完成了什么、什么没完成、依据是什么 |

用户不应该需要理解 worker_run_id、provider RPC、semantic target、resident recovery 或 route-score 公式。

## 10. Real E2E acceptance set

`docs/ZN-REAL-TASK-E2E-CATALOG.md` 当前定义 50 个真实任务验收场景，覆盖：

- research；
- authenticated web；
- documents/files/spreadsheets；
- desktop apps；
- coding/repos；
- terminal/system；
- cross-surface；
- long-running product development；
- single-model multi-worker；
- multi-model routing；
- steering；
- restart/cross-day continuity；
- learned behavior；
- privacy/permission；
- model/tool availability；
- independent final verification。

不是要求一次性实现 50 个测试，而是作为长期产品验收集，按高价值真实任务纵向推进。

## 11. Release / update continuity

Installer、CI、Release、签名本身不是当前产品主线。

只有当它们直接阻塞真实用户长期安装、身份/Memory/Work 连续性、安全边界或数据可靠性时，才提升优先级。

当前真正未闭合的是：真实 N -> N+1 后，ZN 是否还是同一个长期存在的 ZN，原有身份、Memory、Work、配置和不确定副作用状态是否安全连续。

## 12. 已废弃：专用自我维护系统

专用“自我维护 / 自我修复 / upstream BUG report”路线已经明确删除。

它不是当前 capability，不是 backlog，不是 P0/P1/P2/P3，也不属于 near-term product order。

不要重新增加：

- maintenance runtime / cognition / repair；
- 专用 self-repair investigation / review / publication；
- upstream BUG report / transport / intake / reconcile；
- maintenance UI / IPC / RPC；
- 因为目标仓库是 ZN 就获得特殊 Git、合并、发布、更新或凭证权限的路径。

需要修改 ZN 仓库时，把它当普通代码仓库，用通用 Work、File、Terminal、Git、Repo Test 和编码能力处理。

详情见 `docs/ZN-RETIRED-DIRECTIONS.md`。

## 13. 当前产品优先顺序

下一阶段不能再把 delegated work 作为独立“multi-agent 平台工程”。它必须服务真实任务。推荐五个连续产品工作项：

1. 自然 Work continuation + active steering。
2. Broad goal -> 调研 -> runnable MVP 的真实长任务。
3. 单模型多 worker。
4. 多模型按用户 policy/per-SubWork routing。
5. worker failure/stall/restart 后 supervision + reroute。

同时继续补真实 User Browser Bridge、Investigation/replanning 和跨 surface Body 能力，因为调度没有真实工具同样办不成事。

支撑线默认包括 Installer、Release Candidate、签名、额外 CI、维护系统、文档整理、新 governance、新 provider、新状态机和新的抽象。只有它们直接阻塞真实任务时才升优先级。

## 14. 最终判断

每做完一个阶段，只看这件事：

**一个普通用户不学习 ZN 内部结构，只用正常语言告诉它事情，它现在比以前多能独立、连续、可靠地完成哪些真实任务？**

对长任务再多问一句：

**当用户中途改方向、某个 worker/model/tool 失败、Resident 重启或任务跨天时，ZN 是否仍然能自己盯住同一个目标继续办？**

如果答案没有明显改善，就不能把“接了更多模型、spawn 更多 worker、加了更多调度代码”当成产品主线已经推进。