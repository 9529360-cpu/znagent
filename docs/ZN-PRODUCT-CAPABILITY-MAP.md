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
| Situation / Thought / Will loop | CONNECTED + VERIFIED | 更通用的 investigation / replanning |
| Durable Work | CONNECTED + VERIFIED | 自然引用、active steering、跨重启继续需要产品化 |
| Memory / learned context | PARTIAL | “上次怎么做”“昨天那个继续”等真实长期体验仍需扩大 |

## 3. Browser

| Product need | Current status | Remaining gap |
| --- | --- | --- |
| Managed Browser | VERIFIED NARROW | 更广页面结构、popup/frame/download/upload、复杂失败恢复 |
| User Browser Bridge | CONNECTED + VERIFIED NARROW | 扩大真实已登录网站覆盖、授权 UX、漂移后的稳定重规划 |
| Semantic re-ground | VERIFIED NARROW | 从已知模式扩展到更通用的页面变化调查 |
| Sensitive-field protection | GUARDED | 继续保持 fail-closed，不复制用户 profile / cookie / password DB |

真实 User Browser Bridge 是产品主线。临时 profile 或隔离测试浏览器只能作为验证设施，不能替代用户现有登录 session 的产品能力。

## 4. Desktop computer use

| Product need | Current status | Remaining gap |
| --- | --- | --- |
| Foreground / focused-control sensing | VERIFIED | 更复杂窗口切换和应用生命周期 |
| Pointer / keyboard / text entry | VERIFIED NARROW | 继续在完整真实任务中验证，而不是单独堆 primitive |
| Semantic desktop target re-ground | VERIFIED NARROW | 控件变化、窗口漂移、替代入口需要更通用 investigation |
| Cross-app task execution | PARTIAL | 浏览器 + 桌面 + 文件三 surface 联合任务仍需扩大 |

## 5. Files / workspace / terminal / Git

| Product need | Current status | Remaining gap |
| --- | --- | --- |
| File read/write/search | CONNECTED + VERIFIED NARROW | 模糊来源、复杂整理、多文件任务 |
| Workspace evidence / exact source identity | PARTIAL | 歧义来源必须先解决身份，再允许外部副作用 |
| Terminal/process | VERIFIED | 继续作为真实任务执行资源，不单独追 milestone |
| Git / repo task support | PARTIAL | 作为普通项目工作能力继续发展，不给 ZN 自身仓库特殊权限 |

## 6. Multi-surface real tasks

当前已经有 Browser + File、Browser + Desktop、File + Desktop 等真实闭环基础。

下一阶段重点不是继续证明单动作，而是扩大这些完整任务：

```text
normal human goal
-> Sense current computer state
-> Situation
-> Thought / Investigation
-> choose Browser / Desktop / File / Terminal / network resource
-> action
-> fresh observation
-> compare result
-> continue / replan
-> independent completion evidence
```

页面、窗口、文件或目标发生变化时，必须重新观察再决定，而不是继续用旧 target 或预设脚本。

## 7. Recovery / non-replay

| Product need | Current status | Remaining gap |
| --- | --- | --- |
| Resident restart recovery | VERIFIED / PARTIAL | 更多真实任务跨重启恢复 |
| Unknown external-effect handling | FAIL-CLOSED foundations exist | 继续保证不确定副作用不盲目重放 |
| Fresh evidence before mutation | CORE RULE | 扩展到所有新的真实任务 |
| Independent completion verification | VERIFIED NARROW | 继续覆盖更复杂任务 |

Recovery 是为了让真实任务能继续，不是独立产品路线。

## 8. Product UX

| Product need | Current status | Remaining gap |
| --- | --- | --- |
| User-visible task progress | PARTIAL | 用户只需要知道 ZN 在做什么、是否还在继续 |
| Permission / revoke UX | PARTIAL / OPEN | Browser、敏感操作、外部副作用需要更清楚的授权范围 |
| Failure explanation | PARTIAL | 说明遇到什么、是否还能继续、需要用户做什么 |
| Completion result | PARTIAL | 明确完成了什么、什么没完成、依据是什么 |

用户不应该需要理解 runtime id、provider、semantic target、resident RPC、Work recovery 等内部工程概念。

## 9. Release / update continuity

Installer、CI、Release、签名本身不是当前产品主线。

只有当它们直接阻塞真实用户长期安装、身份/Memory/Work 连续性、安全边界或数据可靠性时，才提升优先级。

当前真正未闭合的是：真实 N -> N+1 后，ZN 是否还是同一个长期存在的 ZN，原有身份、Memory、Work、配置和不确定副作用状态是否安全连续。

## 10. 已废弃：专用自我维护系统

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

## 11. 当前产品优先顺序

1. 真实任务自主闭环。
2. 真实 User Browser Bridge。
3. 自主 Investigation / replanning。
4. 长期 Work / Memory / Resident 连续性。
5. 普通用户任务状态、授权、失败和完成体验。

支撑线默认包括 Installer、Release Candidate、签名、额外 CI、维护系统、文档整理、新 governance、新 provider、新状态机和新的抽象。只有它们直接阻塞上面五项时才升优先级。

## 12. 最终判断

每做完一个阶段，只看这件事：

**一个普通用户不学习 ZN 内部结构，只用正常语言告诉它事情，它现在比以前多能独立、连续、可靠地完成哪些真实任务？**

如果这个数字没有明显增加，就不能把工程工作当成产品主线已经推进。
