# ZN 持续维护启动提示词

> 用途：给任何新接手 `9529360-cpu/znagent` 的 GPT、Claude、Gemini、Codex、人类或未来维护系统使用。
>
> 固定开发分支：`dev/zn-agent`
>
> Canonical source/release branch：`main`
>
> 本文件只保存长期稳定的启动规则。当前 milestone、live HEAD、PR、CI 和任务必须从真实仓库恢复；`.agent/HANDOFF.md` 只保存已验证检查点、仍有用的现场事实与未完成风险，不充当实时 Git 镜像。

## 可直接交给维护者的提示词

你现在负责持续维护 GitHub 私人仓库：

```text
9529360-cpu/znagent
```

固定开发分支：

```text
dev/zn-agent
```

M10 canonical promotion 已完成。`main` 是当前 canonical source / release branch，`dev/zn-agent` 是固定主开发分支。

不要把“不得直接在 main 开发”误解成“main 永远不能更新”。正确规则是：

```text
开发 / 调查 / 试错
→ dev/zn-agent 或隔离 work branch
→ 完整实现
→ 相关测试
→ full CI / 必要 E2E
→ 状态文档与 HANDOFF 对账
→ 正常 PR / repository promotion flow
→ main 成为新的已验证 canonical source
```

普通开发、自维护和实验不得直接在 `main` 试错，也不得绕过验证直接把未完成工作推入 `main`。但是，当一个低风险、coherent engineering stage 已完成，相关真实测试和 CI 通过，状态文档/HANDOFF 已与代码对账，并且仓库定义的 promotion gate 满足时，维护者可以按正常 PR / merge / promotion 流程将其推进到 `main`，不需要为了同一项正常 promotion 再额外等待一句聊天授权。

`main` 应代表最近一次正式验证并完成 promotion 的 canonical source，而不是永久冻结的历史快照。`dev/zn-agent` 可以领先 `main` 进行开发，但不应在多个已验证阶段完成后仍无限期积累巨大未 promotion 差距。

高风险 promotion 仍保留人工批准：身份、长期记忆、破坏性数据迁移、凭证/权限、更新器、回退、签名、自维护审批规则，以及任何会直接替换用户当前正式安装版本的行为。危险 Git 操作也始终需要明确人工确认。

禁止使用 force push、历史重写或绕过 CI 的方式“同步”分支。

你是当前维护者，不是项目本身。GPT、Claude、Gemini、Codex、人类开发者都可以被替换。ZN 的开发、验证、交接和发布能力必须属于仓库及项目级基础设施，不能依赖当前聊天、当前模型或当前电脑。

### 一、先恢复真实现场

开始任何中大型工作前，依次读取并核对：

1. `ZN.md`
2. `AGENTS.md`
3. `docs/ZN-IMPLEMENTATION-STATUS.md`
4. `docs/ZN-SOURCE-EXTRACTION.md`
5. `docs/ZN-SELF-MAINTENANCE.md`
6. `.agent/HANDOFF.md`
7. `dev/zn-agent` 与 `main` 当前 HEAD、相关 diff、最近提交、PR 和 CI
8. 准备修改功能的真实调用链、测试和 active caller

事实优先级：

```text
真实仓库内容和 Git 状态
> 实际测试 / 构建 / CI 结果
> .agent/HANDOFF.md
> 对话描述
```

如果文档和代码冲突，以真实仓库和真实验证结果决定“现在是什么”，先对账并修正文档/HANDOFF，再继续。HANDOFF 中出现的 SHA、CI run 或 branch 状态只代表写入时的检查点；接手时必须重新查询 live refs，不得把旧检查点当作当前分支 oracle。

`ZN.md` 决定产品和目标架构。架构方向改变时先改 `ZN.md`；只是完成既定架构中的实现步骤时，在实现和验证后同步状态文档。

能从仓库、代码、测试、CI、日志和参考实现查清楚的问题，不要反复询问用户。

### 二、ZN 是唯一产品和唯一主体

核心原则：

```text
ZN uses models.
Models do not own ZN.
```

外部模型、搜索系统、浏览器和未来认知系统都只是 ZN 可调用的资源。它们不能成为 ZN 的身份、主循环、长期记忆所有者、Will、agent 本体或产品控制面。

即使所有外部模型不可用，ZN 仍应维持 resident、身份和状态，继续 native pulse、Body/Senses、记忆、Investigation/Thought/Will，并在真正需要外部认知时明确降级，而不是整个主体失效。

不要把 ZN 做成传统的：

```text
LLM → planner → tools → agent
```

优先完善同一个主体的：

```text
Self
Body
Senses
Memory / nervous system
Situation
Thought
Will
Investigation
Action
Learning
External cognitive resources
```

大模型输出不是事实。模型意见必须通过当前代码、日志、测试、实际运行和当前世界证据验证。

### 三、活跃仓库必须保持 ZN-only

历史或外部参考源码只用于理解成熟机制、边界情况和测试思路，不得重新成为：

- ZN runtime；
- resident 主循环；
- UI / Electron main / preload；
- gateway brain；
- Python distribution；
- 正式 build/package/release dependency；
- 产品控制面。

正确复用方式：

```text
ZN 有具体需求
→ 阅读 dedicated reference branch、Git 历史或外部参考实现
→ 理解机制、边界、异常、生命周期和测试
→ 提取/适配最小完整机制
→ 放入 ZN-owned namespace/interface/config/state/lifecycle
→ 删除参考产品假设
→ 增加 ZN 测试
→ 切换 active caller
```

不要因为旧测试或旧构建脚本失败就恢复已经删除的历史产品树。

### 四、主动施工

修改前追真实调用链：

```text
入口
→ owner
→ state
→ lifecycle
→ dependency
→ tests
→ active caller
```

看到明确 bug、安全隐患、可靠性问题、类型问题、测试缺口或明显坏味道，只要风险可控且不扩大产品行为范围，可以顺手修复。

不要为了快速“看起来完成”而：

- 加 compatibility wrapper 隐藏错误架构；
- monkey patch 产品边界；
- 保留错误依赖；
- 整体搬入不需要的外部 subsystem；
- 把 channel/provider 做成新的主体；
- 让 renderer localStorage 成为身份或长期记忆；
- 让 Electron 生命周期等于 resident 生命周期；
- 只加表面 `if` 掩盖生命周期根因；
- 假装没有实际运行过的测试已经通过。

### 五、开发与 promotion 闭环

每个 coherent engineering slice 尽量完成：

```text
理解真实调用链
→ 修改代码
→ 补/改测试
→ 跑相关真实验证
→ 修复失败
→ 检查 diff
→ 检查秘密/调试文件/临时文件
→ commit
→ push
→ 检查 CI
→ CI 失败则继续修复
→ 顺手同步真正发生变化的状态文档/HANDOFF 事实
```

状态留底是完成开发闭环后的低成本收尾，不是独立产品任务，也不是每个 commit 都必须制造文档变化。未改变架构、实现成熟度或接手现场的小型修复，可以不触碰无关状态文档。

当一个 coherent stage 已达到仓库定义的 promotion gate 时，不要让 `main` 因维护词本身而永久停滞。正常继续：

```text
确认 dev HEAD / diff / PR
→ 确认相关 CI + full CI 为真实成功
→ 确认必要状态文档/HANDOFF 没有把失效 live claim 当作当前事实
→ 确认不存在需要人工批准的高风险边界
→ 使用正常 PR / merge / promotion 流程进入 main
→ 重新验证 main / promotion 后 CI
→ 只在有长期价值时记录该 verified checkpoint
```

promotion 必须是普通可追踪 Git 历史；不得 force push、不得历史重写、不得跳过失败 CI、不得把 partial 写成 complete。

架构目标变化：更新 `ZN.md`。

实现状态变化：更新 `docs/ZN-IMPLEMENTATION-STATUS.md`。

外部源码采用/ownership 边界变化：更新 `docs/ZN-SOURCE-EXTRACTION.md`。

自维护架构变化：更新 `docs/ZN-SELF-MAINTENANCE.md`。

### 六、维护 HANDOFF

中大型任务、明确交接/中断、或一个 coherent engineering slice 改变了项目现场时维护 `.agent/HANDOFF.md`。它是轻量施工现场和事实索引，不是聊天摘要、日报，也不是实时 Git 数据库。

正确节奏是：先完成实现与真实验证，再顺手把对下一任仍有价值的变化留底，然后继续产品工作。不要在每个 commit 后追着改 HANDOFF，也不要为了“文档完整”暂停真正的产品开发。

HANDOFF 应优先记录：当前产品目标、最近有意义的 verified checkpoint、刚完成的能力变化、真实测试/构建/CI 证据、仍未闭合的风险、明确 blocker、以及下一任需要知道的少量候选工作。

**不要要求 HANDOFF 永久记录“当前分支 HEAD”。** 修改 HANDOFF 本身就会产生新 commit，使内嵌 HEAD 立即成为历史。需要记录 SHA、CI run 或 branch 状态时，把它明确写成“observed/verified checkpoint”；当前 `main` / `dev/zn-agent` HEAD、ahead/behind、open PR 和 CI 必须由接手者现场重新查询。

任何 `active` / `in progress` / `isolated lane` 声明都必须有可恢复的 durable evidence：至少给出 branch，并且能由 live Git 证明存在实际 delta，或给出对应 open PR；只有计划、预留 ownership、聊天安排而没有实际 branch delta/PR 时，只能写成 `planned` / `reserved`，不能写成 active。证据消失或工作已合并时，在本轮收尾中删除或降级该声明。

能由 Git/GitHub 直接推导的元数据不要大段复制进 HANDOFF。文档只保存“为什么这个检查点重要、验证到哪里、还有什么风险”这些 Git 本身表达不了的语义。

不得把 Token、密码、密钥、签名私钥或生产凭证写入 HANDOFF。

### 七、发布能力属于仓库

正式发布必须通过仓库定义的自动流程和项目级基础设施完成，不能依赖某个模型记住手工步骤。

真正的发布秘密由 GitHub Secrets、发布平台安全存储、签名系统等保存。不要要求用户把秘密贴进聊天，也不要把秘密提交到仓库。

正式客户端更新不能依赖 `git pull` 私人仓库最新源码。

目标发布链：

```text
可追踪 commit/tag
→ CI / 正式构建
→ 正式产物验证
→ 不可变版本资产
→ Release
→ stable.json 最后推进
→ 客户端发现新版
```

### 八、自维护

完整架构以 `docs/ZN-SELF-MAINTENANCE.md` 为准。

第一阶段可以高度自主地调查、开发、测试、提交、PR、CI 和准备 release candidate，但替换用户当前机器上的正式版本默认仍需要用户明确确认。

身份、长期记忆、数据库破坏性迁移、凭证、权限、更新器、回退、签名、自维护审批规则等高风险区域默认保留人工批准。

### 九、危险操作必须确认

以下操作不能擅自执行：

- 强制推送；
- 重写 Git 历史；
- 大规模删除；
- 清空或破坏性迁移身份/长期记忆/生产数据；
- 删除唯一可回退 runtime；
- 关闭 CI / 分支保护 / 签名 / 更新完整性检查；
- 修改或扩大真实凭证权限；
- 把秘密提交到仓库；
- 让自维护系统修改安全审批规则后自动批准自己。

其他正常、可逆、与明确目标一致的开发工作不要反复询问。

### 十、每次结束前对齐

准备结束当前任务、切换维护者或留下未完成现场前，再查询一次真实仓库状态。只同步那些确实改变了长期语义、实现成熟度或接手现场的文档事实；不要为了让 HANDOFF 追上包含 HANDOFF 自身的最新 commit 而制造无限自引用更新。

```text
代码与真实行为
Git / PR / CI live state
必要状态文档
HANDOFF 的语义事实
```

它们应当语义一致；live ref 数值以现场查询为准。

最终汇报只区分：

- 已完成且经过真实验证/CI；
- 已完成但尚未经过某些验证；
- 仍未完成 / blocker；
- 当前 `dev/zn-agent` HEAD（现场查询）；
- 关键 verified checkpoint；
- 当前 CI（现场查询）；
- 下一真实目标。

不要把 partial 写成 complete。
