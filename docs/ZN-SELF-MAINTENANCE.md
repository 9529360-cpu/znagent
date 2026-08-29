# ZN 自维护、自修复与自更新架构

> 状态：架构契约 / SM0 COMPLETE / SM1 PARTIAL / SM2 PARTIAL（可信只读源码调查已验证）/ SM3 PARTIAL（bounded isolated repair candidate 已接通并验证）/ SM4+ 未接通
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

长期闭环：

```text
ZN 正常生活/工作
-> 观察自身健康和失败
-> 保存现实证据
-> 判断是否值得维护
-> 形成维护任务
-> 绑定可信源码并调查
-> 形成隔离修复候选
-> 测试 / diff / semantic review
-> commit / push / PR / CI feedback
-> verified promotion
-> canonical source
-> build / artifact verification
-> 用户确认更新
-> 安全切换新身体
-> 验证同一主体连续
-> 失败安全回退
```

当前原则：**ZN 可以逐步获得自主调查、候选开发、测试、PR 和 release-candidate 准备能力；替换用户当前正式安装版本默认仍需要明确人工确认。**

## 2. 维护者无关与主体连续性

ZN 的工程连续性不能属于某一个模型、聊天或开发电脑。长期事实应存在于仓库、Git、CI、发布自动化和项目级安全设施。

必须保护 Self/identity、长期 lived memory、Work/thread references、Will/attention、learning state、runtime/home/config/provider references 与 resident lifecycle。新版能启动不等于升级成功；若升级后失去主体连续性，应视为严重回归。

## 3. 不可破坏的权限原则

- 普通开发不得直接在 `main` 试错；已验证 coherent stage 应通过正常 PR/CI promotion 进入 canonical source。
- ordinary Work workspace 不是 maintenance-source authority。
- maintenance task / investigation / passing test 永远不自动等于更高 mutation/merge/update authority。
- 模型文字不能替代真实测试、diff、CI、运行时证据。
- 当前正式安装目录不是源码开发 worktree；正式更新不能实现成 `git pull`。
- 身份/长期记忆破坏性迁移、生产凭证权限、正式 updater/replacement、rollback、signing/notarization、release trust、审批规则、自行批准高风险更新、替换用户正式安装版本仍需明确人工批准。

## 4. 当前自维护链

### 4.1 Health -> maintenance task

当前 health 已接通 channel/lifecycle、foreground-window Sense、visual capture、provider invocation/resource construction 与 Native Body dispatch。分类 fail-closed：网络、外部服务、环境、配置、输入等失败不能自动升级为源码维护；窄范围、重复出现的内部 invariant failure 才能形成高置信候选。

Health truth 是权威；task/investigation 是可重建派生状态。

### 4.2 Evidence-only investigation

维护任务具有 bounded investigation lifecycle：

```text
maintenance task
-> baseline_ref
-> regression_oracle
-> work/* attempt + evidence_ref
-> regression_passed
-> accepted / rejected
```

`authority = evidence_only`。ledger 中出现 attempt/accepted 本身不授予文件写、push、merge、release 或 updater 权限。

### 4.3 SM2 — Trusted read-only source investigation

已验证路径：

```text
open maintenance task
-> HealthAwareResidentRuntime.investigate_maintenance_source(...)
-> explicit source_root
-> exact Git top-level
-> ZN ownership markers
-> origin == 9529360-cpu/znagent
-> fixed read-only Git argv
-> HEAD / branch / dirty / bounded changed paths
-> existing test:tests/zn_agent/core/... oracle
-> privacy-safe source evidence
-> investigation baseline commit:<HEAD>
```

关键约束：不使用 Work attachment、NativeBody file-write、generic shell/terminal；持久化状态不保存绝对 source path 或 changed-path list。

验证：targeted `33271612132` + full dev CI `33271661045`。

### 4.4 SM3 — Bounded isolated repair candidate

PR #78 已接通第一条真实 source-write 路径，但权限被限制在 **fresh isolated maintenance worktree** 内。

入口：

```text
HealthAwareResidentRuntime.run_maintenance_repair_attempt(...)
```

进入条件：

```text
open maintenance task
+ failure_class == probable_zn_defect
+ investigation.status == investigating
+ authority == evidence_only
+ trusted read_only source evidence
+ observed source clean
+ exact baseline_ref == commit:<observed HEAD>
+ unchanged regression oracle contract
```

任何第一次源码写入之前，operator 会再次证明：

```text
source_root 仍是 exact repo top-level
origin 仍是 9529360-cpu/znagent
root fingerprint 未变化
live HEAD == observed baseline HEAD
live source tree clean
branch ref 是 fresh safe work/*
attempt path 是 source sibling .zn-maintenance-worktrees/<attempt>
```

然后仅允许：

- `git worktree add -b work/* <dedicated-attempt> <baseline>`；
- 替换调用者明确声明的、已经存在的普通 `.py` 文件；
- 目标只能位于 `runtime/python/zn_agent/core` 或 `tests/zn_agent/core`；
- replacement 数量/单文件大小/changed-path 数量有界；
- worktree 初始必须 clean，HEAD/branch 必须与 contract 一致；
- 写后只能出现声明过的 changed paths；
- 执行 `git diff --check`；
- 执行已绑定的固定 Python unittest oracle；
- 只持久化 branch/baseline/count/fingerprints/oracle/pass flags 等 privacy-safe evidence；
- 最后才调用 `MaintenanceInvestigationLedger.record_attempt()`。

这条路径明确 **不会**：

- 修改 source root working tree；
- 修改 `main`；
- 使用 ordinary Work workspace；
- 使用 NativeBody generic file write；
- 开放通用 shell/terminal；
- commit、push、merge、建 PR；
- release/update installed body。

Passing oracle 只说明回归证据通过，不是 semantic approval；attempt 仍保持 `unreviewed`。

验证证据：

- `33273206772`：首轮 targeted run 暴露一个测试输入未命中目标 guard 的断言问题；生产约束未修改；
- `33273272755`：修正测试输入后，affected-module compile + 21 个 SM3/source/investigation/resident regression 全部成功；
- `33273363874`：PR #78 merge head `d74b44ad...` 全量 dev ZN CI 成功，Kernel/Python 完整 core suite、Electron/TypeScript、Source Boundary 及状态发布均成功。

因此 SM3 当前应描述为：**isolated repair candidate exists + connected to formal resident + full-CI verified, but not product-closed/autonomous**。

## 5. 当前真正的断层

### 5.1 Candidate derivation 尚未接通

`run_maintenance_repair_attempt()` 当前需要调用者提供 `replacements`。ZN 还不会从真实 incident + source evidence 自己推导一个受约束 patch proposal。不能把“能够安全执行候选”描述为“能够自主修 bug”。

### 5.2 Semantic review / acceptance 尚未接通

Regression 和 diff check 是必要证据，但不能证明修复没有改变错误语义。已有 ledger 能表示 accepted/rejected，但真实 resident path 尚没有 owner 对 incident、changed paths、测试证据和 repair intent 做语义审查后调用 acceptance。

### 5.3 Worktree lifecycle 尚未闭合

当前 attempt 会保留以便检查。长期 resident 需要明确 retention、restart recovery、stale attempt、cleanup 和失败后隔离规则，且不能删除唯一有价值的证据。

### 5.4 SM4 publication/CI loop 尚未接通

当前 work/* branch 是本地源码仓库分支，没有 commit/push/PR、CI ingestion、failed-CI continuation。SM4 不能因为 repo 外部维护者能做 PR 就宣称 resident self-maintenance 已闭环。

## 6. 下一条依赖顺序

下一条最高价值纵向路径应先完成 **candidate derivation + semantic review**，而不是直接把 passing regression 自动 push/merge：

```text
high-confidence maintenance incident
+ trusted source evidence
-> bounded diagnosis / candidate proposal
-> existing isolated repair operator
-> fixed oracle + bounded diff evidence
-> semantic review against incident + intended scope
-> explicit accepted / rejected attempt
```

只有这条链 verified 后，再进入：

```text
accepted isolated candidate
-> bounded commit
-> push work/*
-> PR
-> CI evidence ingestion
-> failure -> continue repair / success -> promotion gate
```

正式 updater/replacement、rollback、release signing/trust 和替换用户当前安装版本仍是独立人工审批边界。

## 7. SM 分阶段

- **SM0 — COMPLETE**：仓库可恢复维护基础。
- **SM1 — PARTIAL / verified current slices**：multi-organ health、分类、bounded task、reconciliation/status 已接通；统一 health 仍不完整。
- **SM2 — PARTIAL / trusted read-only slice CONNECTED + VERIFIED**：真实 task 能读可信 ZN source state；主动调度和更广 CI evidence ingestion 未闭合。
- **SM3 — PARTIAL / bounded isolated candidate CONNECTED + VERIFIED**：fresh worktree/source-write/oracle/diff/record_attempt 已打通；candidate derivation、semantic review、lifecycle 未闭合。
- **SM4 — NOT CONNECTED as resident loop**：commit/push/PR/CI feedback continuation 未接通。
- **SM5 — release candidate**：仓库构建验证候选，仍不自行替换用户机器。
- **SM6 — approval-gated update/rollback**：用户批准后切换身体并验证主体连续性。
