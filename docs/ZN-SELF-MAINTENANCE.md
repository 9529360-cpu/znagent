# ZN 自维护、自修复与自更新架构

> 状态：架构契约 / SM0 COMPLETE / SM1 PARTIAL（多类 resident health + bounded maintenance task 已接通）/ SM2 PARTIAL（可信源码绑定与只读 source investigation 已接通并验证）/ SM3+ 未接通
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

ZN 是长期存在于计算机上的数字主体。代码和 runtime 是 ZN 当前的计算身体，但不是 ZN 的全部身份。

长期目标闭环：

```text
ZN 正常生活/工作
-> 观察自身健康和失败
-> 保存现实证据
-> 判断是否值得维护
-> 形成维护任务
-> 绑定可信源码并调查
-> 在隔离源码分支/工作区形成修复候选
-> 测试 / diff review / CI
-> verified promotion flow
-> canonical source
-> 构建不可变新版本
-> artifact verification
-> 用户确认更新
-> 安全切换新身体
-> 验证同一主体连续
-> 失败则回退并保留证据
```

当前原则：**ZN 可以高度自主地调查、开发、测试、提交、PR 和准备候选；替换用户当前机器上的正式版本默认仍需要用户明确确认。**

## 2. 维护者无关

ZN 的工程连续性不能属于某一个 GPT、Claude、Gemini、人类、聊天窗口或开发电脑。

```text
换模型       != 项目重来
聊天消失     != 项目失忆
开发电脑损坏 != 无法继续开发和发布
```

长期事实存在于仓库、Git、CI、发布自动化和项目级安全基础设施。新维护者应能仅凭仓库、Git/PR/CI 真实状态和必要项目权限恢复施工现场。

稳定事实位置：

- `ZN.md`：产品和架构；
- `AGENTS.md`：维护者接手规则；
- `docs/ZN-IMPLEMENTATION-STATUS.md`：当前真实实现与证据；
- `docs/ZN-SOURCE-EXTRACTION.md`：源码采用与 ZN ownership 边界；
- `docs/ZN-SELF-MAINTENANCE.md`：本契约；
- `.agent/HANDOFF.md`：当前施工现场；
- `.github/workflows/*`：可执行 CI、构建和发布规则。

## 3. 不可破坏的原则

### 3.1 ZN 维护自己，不是模型拥有维护权

外部模型只能提供认知帮助。模型说“成功”不能替代测试、构建、CI、真实运行或当前世界证据。

### 3.2 不修改正在运行的正式身体

```text
当前身体 N 运行
-> 独立源码分支/工作区产生 N+1 候选
-> CI / build / artifact verification
-> N 与 N+1 可并存
-> 用户确认更新
-> 安全切换
```

正式更新不得实现成对当前安装目录 `git pull` 最新源码。

### 3.3 身体可换，主体连续性不能丢

必须尽量保持：Self/identity、长期 lived memory、Work/thread references、Will/attention、learning state、合法配置和 provider references、resident lifecycle 与可追踪版本历史。状态格式变化必须有显式迁移、验证和回退策略。

### 3.4 活跃源码树保持 ZN-only

历史/外部项目只能作为参考，不能重新成为 ZN runtime、resident 主循环、正式 UI/control plane、gateway brain、Python distribution 或正式构建/发布依赖。

## 4. Git / canonical source / authority

- `main`：canonical source / release branch；
- `dev/zn-agent`：主开发分支；
- `work/*`：需要隔离的调查/维护/实验分支。

普通开发不得直接在 `main` 试错；已验证且 coherent 的低风险 stage 应通过正常可追踪 PR/CI 流程及时进入 canonical source，而不是长期堆在 dev。

以下高风险边界始终需要明确人工批准：身份/长期记忆破坏性迁移、生产凭证/权限扩大、正式 updater/replacement、rollback、signing/notarization、release trust root、自维护审批规则、自动批准自己、删除唯一回退版本、替换用户当前正式安装版本。

GitHub outage 不是 ZN death；运行中的 ZN 应继续存在，维护任务可保持待同步状态。

## 5. 当前自维护闭环

### 5.1 Observe -> classify -> maintenance task

当前真实 health 边界包括：

```text
channel / channel lifecycle
foreground-window Sense
visual capture
provider invocation
provider resource construction
Native Body dispatch
```

它们进入 privacy-safe durable health。分类保持 fail-closed：网络、外部服务、环境、配置、输入等失败不能自动升级成源码维护；窄范围内部 invariant failure 才能成为高置信候选。

每个 organ 使用 bounded durable maintenance task；health truth 是权威，task projection 可重建，重复问题 dedup/reopen，恢复或 fingerprint 变化会关闭/重置旧任务状态。

### 5.2 Evidence-only investigation lifecycle

维护任务已有 bounded investigation state：

```text
authoritative maintenance task
-> reconciled investigation projection
-> baseline_ref
-> regression_oracle
-> work/* attempt + evidence_ref
-> regression_passed gate
-> accepted / rejected evidence state
```

`authority = evidence_only`。task/attempt/accepted 状态本身永远不授予文件写入、merge、release 或 updater 权限。

### 5.3 Trusted read-only maintenance source investigation

PR #75 已接通 SM2 的第一条真实源码路径：

```text
open maintenance task
-> HealthAwareResidentRuntime.investigate_maintenance_source(...)
-> explicit source_root
-> prove exact Git repository root
-> prove ZN ownership markers
-> prove origin == 9529360-cpu/znagent
-> fixed read-only git argv
-> observe HEAD / branch / dirty / bounded changed paths
-> prove test:tests/zn_agent/core/... oracle exists
-> persist privacy-safe source evidence
-> begin investigation at commit:<HEAD>
```

关键安全边界：

- 普通 Work workspace 不是 maintenance-source authority；
- `source_root` 必须精确等于 Git top-level，不能传子目录偷渡；
- 必须存在 ZN ownership markers：`ZN.md`、`AGENTS.md`、`runtime/python/zn_agent/core`、`tests/zn_agent/core`；
- origin 必须是 `9529360-cpu/znagent`；
- 只允许固定 `git -C <root> ...` 参数，不使用 shell、通用 terminal 或 NativeBody file-write capability；
- regression oracle 当前只接受存在的 `test:tests/zn_agent/core/...` 路径；只读阶段只证明 oracle 可用，不在这里执行任意命令；
- durable source evidence 不保存本地绝对 source path，也不保存 changed-path 列表，只保存 bounded/privacy-safe identity、fingerprint、HEAD/branch/dirty/count/oracle evidence；
- closed task 不能重新进入 source investigation；
- source evidence / investigation state 仍不授予 mutation authority。

验证证据：

- `33271612132`：targeted Windows self-hosted validation success；
- `33271661045`：PR #75 合并后 full dev ZN CI success，Kernel/Python、Electron/TypeScript、Source Boundary 全部 green。

因此 SM2 的 **trusted read-only source investigation slice = connected + verified**。它仍不是 product-closed：formal resident 入口是显式调用，尚无自主 maintenance controller 选择任务并完成隔离修复。

### 5.4 隔离修复（下一条真实产品路径）

SM3 尚未接通。未来真正产生 source attempt 前必须满足：

```text
high-confidence open task
+ trusted source evidence
+ exact baseline HEAD
+ explicit regression oracle
+ clean/fresh isolated worktree or work/* branch
-> narrowly scoped source mutation
-> run fixed oracle
-> bounded diff evidence
-> stale-baseline / dirty-state checks
-> record_attempt(...)
```

必须 fail-closed：

- baseline HEAD 已漂移；
- source tree 出现未知 dirty state；
- 分支/worktree 不属于预期隔离位置；
- regression-oracle contract 改变；
- 目标是 `main`、当前正式安装目录或未知仓库；
- 需要通用 shell/terminal 权限才能继续。

在这条路径验证前，不允许因为 SM2 已成功就直接开放“自动改源码”。

## 6. 验证分层

按风险从近到远验证：

1. 最相关 regression；
2. 相关模块测试；
3. typecheck/static checks；
4. build/package smoke（涉及 runtime/desktop/package 时）；
5. 必要集成/E2E；
6. 数据兼容/安全检查；
7. GitHub CI；
8. 正式更新场景才需要真实 artifact/install/upgrade/rollback evidence。

不能为了过 CI 删除有效测试、降低断言或关闭保护机制。

## 7. PR / CI / promotion

```text
review diff
-> 检查秘密/临时文件/调试输出
-> commit / push work or dev branch
-> PR / CI
-> 读取真实失败并修复
-> 状态文档/HANDOFF 对账
-> 满足 gate 后进入 canonical source
```

CI 失败必须重新进入调查；“已 push”不等于完成。正常低风险 promotion 不需要等待聊天口令，但不得 force push、重写历史或绕过失败 CI。

## 8. Release / update

发布能力属于仓库：

```text
traceable commit/tag
-> repository CI
-> formal build
-> artifact verification
-> immutable assets
-> release metadata
-> stable.json LAST
```

正式客户端 updater 必须验证版本、平台/架构、完整性和 release metadata；签名/公证是独立于 hash 的信任层。

第一阶段更新语义仍是：发现新版 -> 展示原因/影响 -> 用户确认 -> 下载与验证 -> 保留回退版本 -> 停止/交接 resident -> 激活新身体 -> 验证身份/记忆/Work 连续 -> 成功完成或失败回退。

本阶段没有执行正式 updater/replacement、rollback 或 signing。

## 9. SM 分阶段

### SM0 — 仓库可恢复维护基础

状态：**COMPLETE**。

### SM1 — 维护事件与证据

状态：**PARTIAL / connected + verified for current health/task slices**。

已经有多类真实 resident health、保守分类、bounded task、reconciliation 和 formal resident/RPC status；统一 health 仍未覆盖所有 persistence/life-loop/config-plan 边界。

### SM2 — 源码调查 Body/Senses

状态：**PARTIAL / trusted read-only source slice CONNECTED + VERIFIED**。

真实 open task 能通过 formal resident 绑定可信 ZN source root，产生 HEAD/branch/dirty/oracle 等 bounded source evidence，且不能通过 Work/terminal/file-write 偷渡 mutation authority。

未闭合：自主 maintenance controller、CI/test result ingestion 更广泛证据，以及从 source evidence 到隔离修复 attempt 的主动调度。

### SM3 — 隔离修复候选

状态：**NOT CONNECTED**。

目标：只在可信 baseline 上创建 fresh isolated `work/*` source attempt，形成最小修复、运行 regression、生成 bounded reviewable diff evidence，并 fail-closed 防止 stale/dirty/错误目标写入。

### SM4 — PR/CI 闭环

状态：**NOT CONNECTED as resident self-maintenance product loop**。

### SM5 — Release candidate

目标：仓库自动构建并验证候选版本，ZN 能解释变化和风险，但不自行替换用户机器。

### SM6 — 用户确认更新与安全回退

目标：用户批准后完成 N -> N+1 切换，验证同一主体连续；失败安全回退。

## 10. 当前下一步

下一条 dependency-ready 纵向路径不是继续加 ledger，而是 SM3 的最小隔离 source attempt：

```text
verified read-only source evidence
-> exact fresh baseline
-> dedicated isolated worktree/work/* branch
-> narrow repository-only mutation
-> fixed regression oracle
-> bounded diff evidence
-> stale-source rejection
-> MaintenanceInvestigationLedger.record_attempt()
-> targeted validation + full CI
```

只有这条路径 verified 后，才继续 resident-owned PR/CI 自动化。正式 updater/replacement、rollback、release signing/trust 和替换用户当前安装版本始终是独立人工审批边界。