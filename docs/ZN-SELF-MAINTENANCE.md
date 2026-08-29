# ZN 自维护、自修复与自更新架构

> 状态：架构契约 / SM0 COMPLETE / SM1 PARTIAL / SM2 PARTIAL（可信只读源码调查已验证）/ SM3 CONNECTED + VERIFIED（自主候选、隔离修复、语义审查、attempt lifecycle 已接通）/ SM4 PARTIAL（accepted repair 可形成 local-only commit；远端 push/PR/CI feedback 尚未授权接通）
>
> 开发分支：`dev/zn-agent`
>
> Canonical source/release branch：`main`
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
-> 测试 / diff / independent semantic review
-> local publication commit
-> push / PR / CI feedback
-> verified promotion
-> canonical source
-> build / artifact verification
-> 用户确认更新
-> 安全切换新身体
-> 验证同一主体连续
-> 失败安全回退
```

当前原则：**ZN 已经可以在不获得仓库凭证权限的前提下，自主形成、验证、独立审查并本地提交一个受约束 repair candidate；远端 publication、正式更新与替换安装体仍是独立权限层。**

## 2. 主体连续性与权限边界

必须保护 Self/identity、长期 lived memory、Work/thread references、Will/attention、learning state、runtime/home/config/provider references 与 resident lifecycle。新版能启动不等于升级成功；若升级后失去主体连续性，应视为严重回归。

不可破坏的边界：

- ordinary Work workspace 不是 maintenance-source authority；
- maintenance task、passing oracle、semantic accept 都不自动授予更高 Git/release/update 权限；
- 模型不能获得 Git、terminal、arbitrary filesystem、push、merge、release 或 updater authority；
- 正式安装目录不是源码 worktree，正式更新不能实现成 `git pull`；
- 扩大仓库凭证权限、正式 updater/replacement、rollback、signing/notarization、release trust、审批规则和替换用户正式安装版本仍需明确人工批准。

## 3. 当前真实自维护链

### 3.1 Health -> maintenance task

Health 已接通多类真实 active caller。分类 fail-closed：外部网络、服务、配置、输入等失败不能轻易升级为源码维护；只有窄范围、重复出现的内部 defect evidence 才能形成 `probable_zn_defect` 维护任务。

### 3.2 Trusted source investigation

正式 resident 能绑定明确的 ZN source root，校验 Git top-level、ownership markers、origin、HEAD、branch、dirty state，并绑定现存 `tests/zn_agent/core/...` oracle。持久化证据不保存绝对 source path 或 changed-path 明文列表。

### 3.3 Bounded isolated repair

`MaintenanceIsolatedRepairOperator` 只允许：

- fresh dedicated `.zn-maintenance-worktrees/...` worktree；
- fresh safe `work/*` branch；
- 已存在的 `runtime/python/zn_agent/core` 或 `tests/zn_agent/core` Python 文件；
- bounded replacement count / file bytes / changed paths；
- fixed unittest oracle；
- `git diff --check`；
- privacy-safe hashes/results。

执行 oracle 时设置 `PYTHONDONTWRITEBYTECODE=1`，避免验证本身生成 `__pycache__` 污染 repair worktree。

### 3.4 Autonomous candidate derivation

正式 resident 通过受约束模型 cognition：

```text
trusted maintenance incident + source catalog
-> target selection
-> bounded source read
-> full-file repair authoring
-> isolated repair operator
```

模型只能选择已有 catalog path 并返回完整文件 replacement；任何越界路径、未选择路径、非 Python path 或过大内容都会被本地 deterministic contract 拒绝。

### 3.5 Durable cognition dispatch accounting

维护模型调用不会直接复用普通 transient worker 调用语义。每次 target-selection、repair-authoring、semantic-review 在真正 provider dispatch 前，都会持久化 privacy-safe dispatch journal：

```text
call fingerprint + phase + route/provider/model
-> status=dispatching
-> external provider call
-> completed / failed_terminal / outcome_uncertain
```

不会持久化源码、prompt context、diff 或 response text，只保存输入/输出 fingerprint 和 error type。若 provider 已可能执行但进程/连接失败，状态进入 `outcome_uncertain`，同一 logical call 不会被自动 replay，从而避免 crash 后重复付费或重复外部副作用。

### 3.6 Independent semantic review

Regression oracle 通过仍然不等于 semantic approval。

自动 accept 必须使用与 author 不同的 model route。若没有独立 reviewer，attempt 保持：

```text
status = investigating
acceptance_state = unreviewed
reason = independent_route_unavailable
```

不会消费 author route 的“自审”响应，也不会生成 publication commit。

如果 route health 在 review 期间发生竞态，最终 reviewer 实际退回 author route，自动 acceptance 仍 fail-closed，不允许 publication。

### 3.7 Pending review recovery

如果最初只有 author route，repair 不会永久卡死。后续独立 reviewer 上线时，resident 可调用 pending-review recovery：

- 不重新执行 target selection / repair authoring；
- 从 retained isolated worktree 重建 candidate；
- 重验 baseline、branch/HEAD、changed-path fingerprint、diff fingerprint、`diff --check`；
- 若该 task 曾经有任何 semantic-review provider dispatch（包括 `dispatching` / `outcome_uncertain` / `completed`），恢复会拒绝，避免绕过 at-most-once；
- 通过后只新增一次 independent semantic-review call。

### 3.8 Attempt lifecycle

Rejected attempt 可在严格条件下自动清理：必须仍是 exact recorded `work/*` branch、HEAD 未离开 baseline、worktree 位于专用目录。Accepted、committed、drifted 或未知 worktree 不会自动删除。

### 3.9 Local publication preparation

Semantic accept 后，ZN 可把 exact accepted repair 变成一个本地 Git commit：

- 重算 changed paths / diff fingerprints；
- `git diff --check`；
- 只 stage accepted paths；
- 固定维护身份、本地 commit、关闭 hooks/GPG side effects；
- 验证 commit parent == observed baseline；
- 验证 commit changed paths 与 accepted paths 完全一致；
- 验证 worktree clean；
- 持久化 privacy-safe publication-preparation evidence。

Authority 明确是：

```text
local_commit_only
```

这一步没有 push、PR、merge、release、updater、rollback、signing 或 repository credential access。

## 4. 当前验证证据

关键 targeted Windows evidence：

- `33275068276` — autonomous candidate derivation + semantic review success；
- `33275525810` — rejected-attempt lifecycle success；此前 `33275445850` 找出真实 Windows worktree parser bug；
- `33277113466` — local publication preparation success；此前 diagnostics 找出 oracle 生成 `__pycache__` 的真实污染问题；
- `33277291497` — cognition durable dispatch / provider disconnect no-replay success；
- `33277416824` — independent semantic-review fail-closed success；
- `33277598171` — pending-review recovery end-to-end success。

Whole-tree evidence：

- dev head `f555210c7417d4f81564ff238be65a0f82a6cc7b`；
- full ZN CI `33277689622` fully green：Source Boundary、zero-model boot、resident core compile、完整 Python core suite、Electron/TypeScript、readable status publication 全成功。

当前 canonical main 仍为 `3b47e517ad594728b05d7346ecbb4db25cd3e115`，其 ZN CI `33274781251` fully green；这一批 SM3/SM4 verified increment 尚待正常 promotion 到 main。

Hosted clean-install `33277689670` 与 release-candidate `33277689603` 都在没有 executable steps 的情况下结束，属于 runner allocation/infrastructure evidence，不是代码失败。

## 5. 当前真正的断层

### 5.1 Remote publication / PR / CI feedback 尚未接通

ZN 已经能得到 verified local commit，但 resident 还不能：

```text
push work/*
-> create PR
-> ingest CI result
-> CI failure -> bounded continuation
-> CI success -> promotion gate
```

这不是因为代码层完全做不到，而是因为 resident 当前没有 repository credential authority。

### 5.2 Repository credential expansion 是人工审批边界

让 ZN resident 自己使用 GitHub token / credential store 推送 branch、建 PR，会扩大凭证权限。根据项目安全规则，这一能力必须获得明确人工批准，不能因为“自维护目标”就隐式授予。

### 5.3 Installed N -> N+1 continuity 仍未闭环

即使 remote PR/CI 闭合，也不能直接推出正式 updater/replacement 已安全。正式安装更新仍必须继续保护 identity、长期记忆、Work、Will、learning、provider/config references 和 rollback continuity。

## 6. SM 分阶段

- **SM0 — COMPLETE**：仓库可恢复维护基础。
- **SM1 — PARTIAL / verified slices**：multi-organ health、分类、bounded task、reconciliation/status 已接通；统一 health 仍不完整。
- **SM2 — PARTIAL / CONNECTED + VERIFIED**：可信 read-only source investigation 已接通；更广主动调度/CI evidence ingestion 仍可增强。
- **SM3 — CONNECTED + VERIFIED**：candidate derivation、fresh isolated repair、oracle/diff、semantic review、accept/reject、attempt lifecycle 已形成真实 resident 路径。
- **SM4 — PARTIAL / local publication CONNECTED + VERIFIED**：accepted repair 能形成 verified `local_commit_only` commit；remote push/PR/CI feedback 未接通。
- **SM5 — release candidate**：仓库级 build/artifact candidate；当前 hosted runner capacity 仍有基础设施缺口。
- **SM6 — approval-gated update/rollback**：用户明确批准后，才允许切换正式 body 并验证主体连续性。

## 7. 下一条依赖顺序

在当前权限下，应先保持这条 source-maintenance chain 的 evidence/canonical state 同步并继续检查产品级可靠性缺口。

下一项真正让产品能力跃迁的层是：

```text
verified local maintenance commit
-> bounded remote publication
-> PR
-> CI evidence ingestion
-> failed-CI continuation
-> verified promotion
```

但在实现 resident-owned GitHub credential access 之前，必须先取得明确的 credential-permission approval。正式 updater/replacement、rollback、release signing/trust 和替换用户当前安装版本仍是后续独立审批边界。
