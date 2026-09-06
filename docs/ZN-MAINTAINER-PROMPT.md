# ZN 持续维护启动提示词

> 用途：给任何新接手 `9529360-cpu/znagent` 的维护者使用。
>
> Canonical / integration / release branch：`main`
>
> Active development：从最新 `main` 拉短命 `work/*` 分支，PR 直接回到 `main`。
>
> Historical compatibility：`dev/zn-agent` 仅保留兼容用途，不再作为主开发分支、集成分支或新 PR base；保留期间应与 `main` 对齐。

## 接手时先做什么

先读：

1. `ZN.md`
2. `AGENTS.md`
3. `docs/ZN-IMPLEMENTATION-STATUS.md`
4. `docs/ZN-SOURCE-EXTRACTION.md`
5. `docs/ZN-RETIRED-DIRECTIONS.md`
6. `.agent/HANDOFF.md`

然后现场查询 `main`、相关短命 `work/*`、open PR 和 CI。只有历史任务仍明确引用 `dev/zn-agent` 时才把它作为兼容分支检查，不能把它当新的开发主线。旧文档里的 SHA、CI run 和分支状态只能当历史检查点，不能当现在的事实。

事实优先级：

```text
真实代码和 Git 状态
> 实际测试、构建和 CI
> .agent/HANDOFF.md
> 对话描述
```

## 产品主线

维护目标只有一个：让 ZN 成为一个能长期存在在用户电脑上、理解普通人任务、自己观察环境、自己选择工具、自己执行多步骤操作、遇到变化会重新调查，并且真正验证结果的 Resident 智能体。

不要拿下面这些东西冒充产品进展：代码文件多了、测试多了、CI 绿了、安装包能出了、又加了一层抽象，或者又做了一个单独 capability demo。

优先选一个真实用户任务，找出它卡在哪，只补真正缺的能力，然后打通完整任务。

## 开发规则

开始改代码前，先看真实实现、caller、tests 和当前 CI。需要新方案时，先查 GitHub、Stack Overflow、官方文档或成熟技术案例，再决定怎么改。

默认开发闭环：

```text
恢复真实现场
→ 找当前最阻塞真实用户任务的问题
→ 追入口 / owner / state / caller / tests
→ 修改最少必要代码
→ 跑相关验证
→ 看真实结果
→ 修回归
→ commit / push / PR
→ 检查真实 CI
→ 只更新真正发生变化的文档事实
```

不要为了修一个问题重新设计整个项目，也不要恢复已经废弃的控制面或历史产品路线。

## 已废弃：专用“自我维护”系统

这条路线已经明确删除。详情见 `docs/ZN-RETIRED-DIRECTIONS.md`。

以后如果要修改 ZN 自己的仓库，就把它当普通代码仓库，使用通用 Work、File、Terminal、Git、Repo Test 和编码能力。不要重新增加专门的 maintenance runtime、repair intelligence、BUG 上报链、maintenance UI/RPC，也不要因为目标仓库是 ZN 就自动扩大权限。

通用 Health、Recovery、Work、Memory、File、Terminal、Git、Browser、Desktop、Computer Use 和 Update 能力继续保留。

## 权限边界

能写代码，不等于能自动合并、发布或替换用户当前安装版本。

以下高风险操作默认需要明确人工授权：

- force push 或普通情况下的 Git 历史重写；
- 身份或长期记忆的破坏性修改；
- 破坏性数据库迁移；
- 凭证、权限或签名信任变化；
- 替换用户当前正式安装版本；
- 删除唯一可恢复数据或回退路径。

2026-09-04 对已经废弃的专用“自我维护”文件做一次性 Git 历史清理，是项目所有者明确要求的例外，不代表以后可以随便改历史。

## 每次收尾

优先说明：

- ZN 以前具体不能完成什么真实任务；
- 现在具体能完成什么；
- 用户实际成功路径是什么；
- 还有哪里会失败；
- 下一项最阻塞真实使用的问题是什么。

测试数量、PR 数量、commit 数量和 CI 状态只作为证据，不作为产品成绩本身。