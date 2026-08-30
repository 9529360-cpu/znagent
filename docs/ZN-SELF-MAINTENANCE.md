# ZN 自维护、自修复与自更新架构

> 状态：架构契约 / SM0 COMPLETE / SM1 PARTIAL / SM2 PARTIAL（可信只读源码调查已验证）/ SM3 CONNECTED + VERIFIED（自主候选、隔离修复、语义审查、attempt lifecycle 已接通）/ SM4 PARTIAL（accepted repair 可形成 local-only commit；installed upstream 仅允许更新观察与缺陷/修复报告，不允许官方仓库写入）
>
> 开发分支：`dev/zn-agent`
>
> Canonical source/release branch：`main`
>
> 当前实现事实：[`ZN-IMPLEMENTATION-STATUS.md`](ZN-IMPLEMENTATION-STATUS.md)

## 1. 目标

ZN 是长期存在于计算机上的数字主体。代码和 runtime 是 ZN 当前的计算身体，但不是 ZN 的全部身份。

长期闭环应拆成两个产品方向，而不是让 installed resident 直接成为官方仓库维护者：

```text
官方上游更新方向：
maintainer/release environment
-> build / artifact verification
-> publish official update metadata/assets
-> installed ZN 检查更新
-> 验证 update metadata/artifact
-> 用户允许后安全切换新身体
-> 验证同一主体连续
-> 失败安全回退

installed ZN 自维护/反馈方向：
ZN 正常生活/工作
-> 观察自身健康和失败
-> 保存现实证据
-> 判断是否值得维护
-> 形成维护任务
-> 本地调查 / 隔离修复候选
-> 测试 / diff / independent semantic review
-> optional local-only commit / repair proposal
-> 向官方上游报告 BUG / 修复建议
-> maintainer 决定是否进入官方源码、CI、merge 和 release
```

当前原则：**普通安装实例可以知道和读取自己的官方更新通道，也可以把 bounded BUG/repair evidence 上报给维护者；它不获得官方源码仓库写权限。**

## 2. 主体连续性与权限边界

必须保护 Self/identity、长期 lived memory、Work/thread references、Will/attention、learning state、runtime/home/config/provider references 与 resident lifecycle。新版能启动不等于升级成功；若升级后失去主体连续性，应视为严重回归。

不可破坏的边界：

- official upstream identity/update channel 可以随产品存在，用于检查和验证更新；
- 知道 upstream/update identity 不等于拥有 private source repository 读取或写入权限；
- installed resident 可以提交 bounded BUG/repair report，但不能直接 push 官方仓库、创建官方 PR、merge、release、sign 或 promote official version；
- ordinary Work workspace 不是 maintenance-source authority；
- maintenance task、passing oracle、semantic accept 都不自动授予更高 Git/release/update 权限；
- 模型不能获得 Git、terminal、arbitrary filesystem、repository push/merge/release 或 updater authority；
- 正式安装目录不是源码 worktree，正式更新不能实现成 `git pull`；
- 官方仓库凭证、maintainer token、deploy key、release/signing secrets 不能随安装体分发，也不能进入普通 resident memory/status/evidence；
- 正式 updater/replacement、rollback、signing/notarization、release trust、审批规则和替换用户正式安装版本仍是独立高风险边界。

## 3. 当前真实自维护链

### 3.1 Health -> maintenance task

Health 已接通多类真实 active caller。分类 fail-closed：外部网络、服务、配置、输入等失败不能轻易升级为源码维护；只有窄范围、重复出现的内部 defect evidence 才能形成 `probable_zn_defect` 维护任务。

### 3.2 Trusted source investigation

在开发/维护源码环境中，正式 resident 能绑定明确的 ZN source root，校验 Git top-level、ownership markers、origin、HEAD、branch、dirty state，并绑定现存 `tests/zn_agent/core/...` oracle。持久化证据不保存绝对 source path 或 changed-path 明文列表。

这不是对所有 installed client 的要求。普通安装体可以没有源码 checkout，也不应需要访问 private repository 才能更新或报告问题。

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

Semantic accept 后，在源码维护环境中 ZN 可把 exact accepted repair 变成一个本地 Git commit：

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

### 3.10 Upstream update observation

普通 installed ZN 应该能够知道自己的 official update channel，并读取版本/manifest/artifact 元数据来判断是否存在新版本。

该能力必须满足：

- read/verify only；
- 不需要 private source repository checkout；
- 不需要 GitHub/source-repository credential；
- update manifest/artifact 与 source repository authority 分离；
- 正式替换 body 前仍走 updater/replacement continuity gate。

### 3.11 BUG / repair report submission

普通 installed ZN 可以向 operator-controlled upstream report channel 上送 bounded 报告，例如：

```text
installed version
failure class / reproduction summary
privacy-safe evidence fingerprints
bounded diagnostics
optional repair proposal / patch evidence
verification result
```

报告能力不是仓库写权限。接收侧由 maintainer 决定是否复现、是否在官方源码建立 `work/*` 分支、是否跑 CI、是否 merge/release。

## 4. 当前验证证据

关键 targeted Windows evidence：

- `33275068276` — autonomous candidate derivation + semantic review success；
- `33275525810` — rejected-attempt lifecycle success；此前 `33275445850` 找出真实 Windows worktree parser bug；
- `33277113466` — local publication preparation success；此前 diagnostics 找出 oracle 生成 `__pycache__` 的真实污染问题；
- `33277291497` — cognition durable dispatch / provider disconnect no-replay success；
- `33277416824` — independent semantic-review fail-closed success；
- `33277598171` — pending-review recovery end-to-end success；
- PR #90 / merge `8c4d187038010c4eb524d2ddca362b105ce52610` — removed the incorrect resident remote-publication request path introduced by PR #89 and restored ordinary self-maintenance authority to `local_commit_only`.

Whole-tree evidence before the authority correction:

- canonical main `853916aca200848ebd16da3f11e2e1f6a6d4d136`；
- canonical main ZN CI `33280722417` fully green；
- PR #89 dev head introduced a request-only push/PR envelope, but product intent review showed that even this was the wrong default installed-resident direction；
- PR #90 removed that path. Its dev CI must be treated as pending until the current run finishes; do not infer green from the code diff alone.

Hosted clean-install/release-candidate jobs may still fail before executable steps due runner allocation. Those are infrastructure evidence, not code-failure evidence.

## 5. 当前真正的断层

### 5.1 Installed upstream update observation 仍需形成完整产品闭环

ZN 已有 release/update 基础设施，但需要明确验证 installed resident 能在不接触 private source repository 的情况下：

```text
read official update metadata
-> compare version/channel
-> verify artifact identity/integrity/trust
-> expose update availability
```

正式 body replacement 仍是单独的 continuity/security gate。

### 5.2 BUG / repair report channel 仍未完整接通

需要一个 bounded、privacy-safe、可重试/可去重的上报路径，让 installed ZN 可以把问题和修复建议交给维护者，但不能演化成通用 GitHub/repository write client。

### 5.3 Official repository mutation 属于 maintainer 环境，不是 installed resident gap

下面这些不再是普通 resident 的产品目标：

```text
push official work/*
create official PR
merge
release
sign/promote official version
```

它们属于 separately trusted maintainer/release environment。普通 ZN 是否能“自维护”不以获得这些权限为完成条件。

### 5.4 Installed N -> N+1 continuity 仍未闭环

即使 update observation 和 report channel 闭合，也不能直接推出正式 updater/replacement 已安全。正式安装更新仍必须继续保护 identity、长期记忆、Work、Will、learning、provider/config references 和 rollback continuity。

## 6. SM 分阶段

- **SM0 — COMPLETE**：仓库可恢复维护基础。
- **SM1 — PARTIAL / verified slices**：multi-organ health、分类、bounded task、reconciliation/status 已接通；统一 health 仍不完整。
- **SM2 — PARTIAL / CONNECTED + VERIFIED**：可信 read-only source investigation 已接通；更广主动调度/CI evidence ingestion 仍可增强。
- **SM3 — CONNECTED + VERIFIED**：candidate derivation、fresh isolated repair、oracle/diff、semantic review、accept/reject、attempt lifecycle 已形成真实 resident 路径。
- **SM4 — PARTIAL / local repair CONNECTED + VERIFIED**：accepted repair 能形成 verified `local_commit_only` commit；普通安装实例的远端目标是 update observation + BUG/repair reporting，而不是 repository publication。
- **SM5 — release/update channel**：maintainer 侧形成可验证 official artifact/update metadata，installed ZN 可只读检查并验证更新；当前完整 installed E2E 仍有缺口。
- **SM6 — approval-gated update/rollback**：用户明确批准并满足连续性条件后，才允许切换正式 body 并验证主体连续。

## 7. 下一条依赖顺序

正确的产品依赖顺序是：

```text
installed ZN knows official update channel
-> bounded read/verify update observation

self-diagnosis / optional local repair evidence
-> bounded privacy-safe upstream BUG/repair report
-> maintainer receives/reproduces
-> maintainer-controlled source branch / CI / review / merge / release
-> official update channel advances
-> installed ZN observes new version
```

普通 resident 不需要也不应该获得官方仓库 credential/push/PR/merge/release 权限。正式 updater/replacement、rollback、release signing/trust 和替换用户当前安装版本仍是独立高风险边界。
