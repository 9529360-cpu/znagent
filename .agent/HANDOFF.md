# ZN Maintainer Handoff

这是一份施工现场说明，不是产品路线的永久命令。

真实代码、真实 Git、真实测试和真实 CI 高于这份文档。接手时必须重新查询 `main`、`dev/zn-agent`、相关 work branch、open PR 和 CI，不能把这里写的 SHA 或状态当成永远正确。

## 当前正在做的清理

PR #176：`Remove the special self-maintenance product lane`

这一轮的目标只有一个：把专用“自我维护 / 自我修复 / upstream BUG report”产品路线从当前代码树中拆掉，同时保留正常的 Resident、Health、Recovery、Work、Memory、Browser、Desktop、File、Terminal、Git、Repo Test 和 Update 架构。

专用自我维护路线已经明确废弃。它不再是产品能力，也不再是待办优先级。

详细废弃说明见 `docs/ZN-RETIRED-DIRECTIONS.md`。

## 当前产品主线

ZN 的产品目标不是继续堆内部能力模块，而是让普通用户给出正常人类任务以后，ZN 能自己理解、观察、执行、重新调查，并验证真实结果。

当前工作按下面的产品价值排序：

1. 打通更多真实用户任务的完整自主闭环，而不是继续验证单个 click、textbox、terminal 等 primitive。
2. 继续收紧真实 User Browser Bridge，让 ZN 在明确授权下可靠使用用户当前已经登录的浏览器状态。
3. 补齐 Investigation / replanning：目标、页面、窗口、文件或程序状态变化时，重新 Sense / Situation / Thought，再决定下一步。
4. 把 Work / Memory / Recovery 变成真实长期连续性，让“刚才那个继续”“昨天那个继续”成为可用体验。
5. 改善普通用户能看懂的任务状态、授权、失败和完成结果。

安装器、Release、签名、额外 CI、维护系统、文档整理和新的抽象默认都是支撑线。只有它们正在直接阻塞真实用户任务、安全边界、数据连续性或结果验证时，才提升优先级。

## 明确不再做的方向

不要重新增加：

- maintenance runtime / maintenance cognition / maintenance repair；
- 为“ZN 修自己”单独设计的 investigation / review / publication 状态机；
- upstream BUG report / transport / intake / reconcile 专用控制面；
- maintenance 专用 UI / IPC / RPC；
- 因为目标仓库刚好是 ZN，就自动扩大 Git、合并、发布、更新或凭证权限的特殊路径。

如果以后需要修改 ZN 自己的代码，就把 ZN 当普通代码仓库，用通用 Work、File、Terminal、Git、Repo Test 和编码能力处理。

## 接手者下一步怎么判断

每次准备开始一个新工作项，先问：

1. 普通用户现在具体在哪个真实任务上卡住？
2. 这次修改是否直接让这个任务更接近成功？
3. 修改完成后，哪个真实用户 E2E 会从失败变成成功？

如果第三个问题答不出来，默认重新评估，不要因为某个工程问题“看起来能修”就自动把它升成主线。

## 收尾怎么汇报

优先说明：

- ZN 以前不能完成什么真实任务；
- 现在能完成什么；
- 成功路径是什么；
- 用户还会在哪里失败；
- 下一项最阻塞真实使用的问题是什么。

测试数量、PR 数、commit 数和 CI 只作为证据，不作为产品成绩本身。
