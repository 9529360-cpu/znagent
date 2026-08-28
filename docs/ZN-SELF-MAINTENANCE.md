# ZN 自维护、自修复与自更新架构

> 状态：架构契约 / SM0 COMPLETE / SM1+ 待实现
>
> 开发分支：`dev/zn-agent`
>
> Canonical source/release branch：`main`
>
> 上位产品契约：[`../ZN.md`](../ZN.md)
>
> 仓库接手规则：[`../AGENTS.md`](../AGENTS.md)
>
> 当前实现事实：[`ZN-IMPLEMENTATION-STATUS.md`](ZN-IMPLEMENTATION-STATUS.md)

## 1. 目标

ZN 是长期存在于计算机上的数字主体。代码和运行时是 ZN 当前的计算身体，但不是 ZN 的全部身份。

目标闭环：

```text
ZN 正常生活/工作
→ 观察自身健康和失败
→ 保存现实证据
→ 判断是否值得维护
→ 形成维护任务
→ 在隔离源码分支/工作区调查
→ 修改代码并补测试
→ 运行验证
→ 审查 diff
→ 推送维护分支
→ PR / verified promotion flow
→ CI
→ 满足规则后进入 canonical source
→ 构建不可变新版本
→ 验证正式产物
→ 通知用户更新原因
→ 用户确认更新并重启
→ 安全切换新身体
→ 保持身份/记忆/工作连续
→ 失败则回退并保留证据
```

第一阶段原则：**ZN 可以高度自主地调查、开发、测试、提交、PR 和准备 release candidate；替换用户当前机器上的正式版本默认仍需要用户明确确认。**

## 2. 维护者无关

ZN 的工程连续性不能属于某一个 GPT、Claude、Gemini、人类、聊天窗口或开发电脑。

```text
换模型           ≠ 项目重来
聊天记录消失     ≠ 项目失忆
开发电脑损坏     ≠ 无法继续开发和发布
```

长期事实应存在于仓库、Git、CI、发布自动化和项目级安全基础设施中。

新维护者原则上只需要：

```text
仓库访问权限
+ 仓库内架构/状态/接手文档
+ Git/PR/CI 真实状态
+ 当前任务所需的项目级操作权限
```

不应该依赖上一段聊天、上一台电脑或上一位维护者保存的秘密。

## 3. 核心原则

### 3.1 ZN 维护自己，不是模型拥有维护权

外部模型只能提供认知帮助：

```text
问题 + 证据 + 明确未知点
→ 可选外部认知资源
→ candidate hypothesis / patch
→ ZN/维护流程检查
→ 测试 / 日志 / 实际运行验证
→ 接受、拒绝或继续调查
```

模型说“成功”不能替代测试、构建、CI 或当前世界证据。

### 3.2 不修改正在运行的身体

```text
当前身体 N 运行
→ 独立源码分支/工作区产生 N+1
→ CI / build / artifact verification
→ N 与 N+1 可并存
→ 用户确认更新
→ 安全切换
```

不得把正式更新实现成对当前安装目录 `git pull` 最新源码。

### 3.3 身体可换，主体连续性不能丢

允许变化：进程、runtime ID、Python/Node/依赖版本、程序代码、UI 和内部实现。

必须尽量保持连续：

- ZN 身份；
- living Self；
- 长期记忆和经历；
- 必要 Will/attention 连续性；
- 用户工作、线程、项目状态；
- 合法配置和凭证引用；
- 可追踪版本历史。

数据库/状态格式变化必须有显式迁移、验证和回退策略。

### 3.4 活跃源码仓库保持 ZN-only

自维护不能重新引入外部产品/agent framework 作为 resident runtime、主循环、UI、gateway brain、Python distribution、build/release dependency 或产品控制面。

需要成熟实现时，只能从 dedicated reference branch、Git 历史或外部参考源研究并适配到 ZN ownership。

## 4. GitHub 和仓库的角色

GitHub 是 ZN 的远程源码、协作、工程交接和版本历史边界之一，不是 ZN 的身份存储。

配置可包含：

```text
repository: 9529360-cpu/znagent
working_branch: dev/zn-agent
canonical_branch: main
```

M10 canonical promotion 已完成。`main` 不再是“未来目标”，而是 canonical source/release branch；`dev/zn-agent` 是固定主开发分支。普通开发和自动修复仍必须先在 `dev/zn-agent` 或隔离 work branch 验证，不能直接在 `main` 试错。

但是 `main` 也不能因为“不能直接开发”而永久冻结。低风险 coherent maintenance/development stage 在实现完整、相关测试及 full CI/必要 E2E 通过、diff 已审查、状态文档/HANDOFF 已对账、无未解决 blocker 且没有触及人工审批边界时，可按正常可追踪 PR / merge / promotion flow 进入 canonical source，不需要额外依赖某段聊天再次授权同一项正常 promotion。

高风险边界仍必须人工批准，包括身份、长期记忆、破坏性数据迁移、凭证/权限、updater/rollback/signing、release trust root、自维护审批规则，以及替换用户当前正式安装版本。

源码仓库连接信息属于配置。Token/密钥必须进入安全凭证存储，不能写入普通日志、记忆、提交或 HANDOFF。

GitHub 不可用时：

```text
GitHub outage ≠ ZN death
```

ZN 继续运行，维护任务可保持待同步状态。

长期稳定规则位置：

- `ZN.md`：产品和架构；
- `AGENTS.md`：任何维护者如何接手施工；
- `docs/ZN-IMPLEMENTATION-STATUS.md`：当前真实实现；
- `docs/ZN-SOURCE-EXTRACTION.md`：外部/历史源码采用与 ownership 边界；
- `docs/ZN-SELF-MAINTENANCE.md`：自维护、自修复、自更新闭环；
- `.agent/HANDOFF.md`：当前施工现场；
- `.github/workflows/*`：可执行 CI、构建和发布规则。

## 5. 自维护闭环

### 5.1 观察

ZN 应有界地观察：

- resident 异常退出；
- 同类错误重复出现；
- Body/Sense/provider/channel 连续失败；
- 更新失败；
- 数据库或状态异常；
- 性能/资源明显退化；
- CI/测试发现回归；
- 用户明确报告 ZN 自身问题。

不能把每个普通失败都升级为源码维修任务。

### 5.2 判断

形成源码维护任务前至少区分：

```text
外部服务故障
网络故障
权限/配置问题
用户输入问题
暂时性错误
第三方 API 变化
ZN 自身代码缺陷
未知
```

只有足够证据指向自身实现，或源码调查确有必要时，才进入维护流程。

### 5.3 形成维护任务

维护任务至少记录：问题、现实证据、影响、风险、已做调查、成功条件和允许的自动化级别。

重复问题应合并，失效问题应关闭或降级，不能形成无限增长的任务垃圾场。

### 5.4 隔离开发

真正进入开发的维护任务使用 `dev/zn-agent` 上的明确小修改，或隔离分支/工作区，例如：

```text
work/self-maintenance-<issue-id>-<short-name>
```

要求：

- 不直接修改当前正式安装目录；
- 不直接在 `main` 试错；
- 开始前记录基线 commit；
- 未知 dirty state 不能覆盖；
- 改动范围保持小而可验证。

### 5.5 调查与修复

```text
复现 / 收集证据
→ 找相关代码
→ 追真实调用链
→ 理解已有约定和测试
→ 建立回归测试（适用时）
→ 最小修复
→ 相关测试
→ 扩大验证
→ 审查 diff
```

模型生成的候选代码必须经过同样验证。

### 5.6 验证

按风险分层：

1. 最相关测试；
2. 相关模块测试；
3. typecheck/static checks；
4. build/package smoke（涉及 runtime/desktop/package 时）；
5. 必要集成/E2E；
6. 数据兼容/安全检查；
7. GitHub CI；
8. 涉及正式更新时的真实 artifact/install/upgrade/rollback evidence。

不能为了通过而删除有效测试、降低断言或关闭保护机制，除非证明测试本身错误并记录理由。

### 5.7 提交、PR、CI 与 promotion

```text
review diff
→ 检查秘密/临时文件/调试输出
→ commit
→ push development/isolated branch
→ create/update PR or follow repository promotion flow
→ CI
→ 读取真实结果
→ 同步状态文档/HANDOFF
→ 满足 promotion gate 后进入 canonical source
```

CI 失败必须重新进入调查；“已 push”不等于完成。满足低风险 promotion gate 后，也不应因为维护者等待聊天口令而无限期让 canonical source 停滞。

## 6. 合并与审批策略

风险不是由模型自我声明决定，而由受影响的产品边界决定。

可逐步自动化、并可在仓库 gate 满足后正常 promotion 的低风险示例：

- 文档；
- 非关键 UI；
- 明确小范围 bug；
- 测试补强；
- 不改变权限/身份/更新语义的内部重构。

低风险不等于“无需验证”。至少仍需与改动匹配的真实测试/CI、diff 审查、状态对账和正常可追踪 Git/PR 历史。

默认保留人工批准的高风险区域：

- 身份/长期记忆；
- 数据库破坏性迁移；
- 凭证和权限；
- updater / rollback；
- signing / notarization；
- release trust root；
- self-maintenance approval rules；
- 自动批准自己；
- 删除唯一可回退版本；
- 替换用户当前正在使用的正式安装版本。

即使未来允许更多自动合并，也必须在分支保护、CI 和可回退版本基础上进行。任何 force push、历史重写、绕过失败 CI、关闭保护机制的“promotion”都不属于正常 promotion flow。

## 7. 发布与更新

发布能力必须属于仓库：

```text
traceable commit/tag
→ repository CI
→ formal build
→ artifact verification
→ immutable version assets
→ release metadata
→ stable.json LAST
```

秘密由 GitHub Secrets、发布平台安全存储或签名系统持有。

正式 updater 必须验证版本、平台/架构、完整性和 release metadata；签名/公证是独立于 hash 的信任层。

第一阶段客户端流程：

```text
发现新版
→ 显示版本/原因/影响
→ 用户点击更新
→ 下载并验证
→ 保存当前可回退版本
→ 停止/交接 resident
→ 激活新 runtime/app
→ 验证健康与身份/状态连续
→ 成功则完成
→ 失败则回退
```

## 8. SM 分阶段

### SM0 — 仓库可恢复维护基础

状态：**COMPLETE**。

含义：仓库有架构、接手规则、实现状态、HANDOFF、CI 和 release automation；维护者可替换。

### SM1 — 维护事件与证据

目标：ZN 能从运行证据形成 bounded maintenance event，而不是每次都靠用户手工描述。

### SM2 — 源码调查 Body/Senses

目标：ZN 能读取自己的仓库状态、diff、测试结果和 CI evidence，并保持 read-only/typed authority 边界。

### SM3 — 隔离修复候选

目标：ZN 能在隔离分支形成小修复、测试并生成可审查 diff。

### SM4 — PR/CI 闭环

目标：ZN 能创建/更新 PR、读取失败 CI、继续修复直到满足合并规则。

### SM5 — Release candidate

目标：仓库自动构建并验证候选版本，ZN 能解释变化和风险，但不自行替换用户机器。

### SM6 — 用户确认更新与安全回退

目标：用户批准后完成 N→N+1 切换，验证同一主体连续；失败自动回退。

后续更高自动化必须以真实安全证据逐步获得，不预设无人批准自升级。

## 9. 必须保留的安全边界

- 强制推送、历史重写、大规模删除仍需人工明确确认；
- 不泄露或扩大密钥权限；
- 不关闭 CI、分支保护、签名或更新完整性验证；
- 不把模型文字当事实；
- 不把动作 exit code 当任务完成证明；
- 不允许 self-maintenance 修改审批规则后自动批准自己；
- 不允许更新破坏身份、长期记忆或唯一回退路径。

## 10. 当前下一步

SM1+ 不是当前唯一主线。当前实现优先级由 `ZN-IMPLEMENTATION-STATUS.md` 和 HANDOFF 决定。

当恢复自维护工作时，优先建立：

```text
真实故障/健康证据
→ bounded maintenance event
→ ZN-owned repository/CI read sense
→ 隔离调查
```

不要跳过这些证据层直接做“自动改自己 + 自动发布 + 自动安装”。
