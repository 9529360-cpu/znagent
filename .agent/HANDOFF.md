# ZN Agent Handoff

更新时间：2026-08-25

## 当前目标

当前主线已经从 post-M10 migration/cleanup 收口回到 ZN resident-owned engineering competence。

本轮发现并修复一个真实调用链回归：`RepositoryVerifyingResidentRuntime` 通过当前 `.github/workflows/zn-ci.yml` 证明 kernel module → mirrored unittest 的执行 authority，但 `ci_source_runs_kernel_unittest_suite()` 只识别旧的一行式 `run: python -m unittest ...`，无法识别当前 Windows PowerShell block。结果是 steady-state CI 本身可以全绿，但 resident 的“由当前仓库证据形成 targeted verifier identity”路径会 fail closed，退化为仅 repo-delta verification。

当前目标：让这条 resident-owned verifier authority 与真实 Windows CI 契约重新一致，并取得 exact-head Windows CI 证据。

核心原则：

> **ZN uses models. Models do not own ZN.**

Linux/macOS 现阶段是 optional/on-demand evidence；不得再把 Linux Container/AppImage manual smoke 当作阻塞 Windows 主线或 PR 收口的必需条件。M8 仍然是 Windows clean install / N→N+1 / rollback / signing evidence-based partial milestone。

## 当前分支 / HEAD

- 固定开发分支：`dev/zn-agent`
- canonical source/release branch：`main`
- 本文件更新前开发 HEAD：`dd237947a5122e2577ef75fd3556fa63b9a5e595`
- canonical `main`：`8234a835dea604783cea0bd9d28a40de654ec03d`
- `dev/zn-agent` 相对 `main`：ahead 50 / behind 0，仍为线性候选
- PR #6：draft/open，base `main`，head `dev/zn-agent`，未合并
- 本文件提交后 HEAD 会继续前进；接手者必须重新读取真实 ref

## 本轮已完成

### 1. 恢复真实现场

已重新读取：

- `ZN.md`
- `AGENTS.md`
- `docs/ZN-IMPLEMENTATION-STATUS.md`
- `docs/ZN-SOURCE-EXTRACTION.md`
- `docs/ZN-SELF-MAINTENANCE.md`
- `.agent/HANDOFF.md`
- `docs/ZN-NEXT-PHASE.md`

并检查：

- `dev/zn-agent` / `main` compare；
- PR #6；
- 最新 Windows CI；
- resident targeted verifier 的真实调用链；
- `.github/workflows/zn-ci.yml` 当前 kernel test step。

发现旧 HANDOFF 与最新产品契约冲突：HANDOFF 把 Linux manual evidence 作为 P1/P2 阻塞项，而最新 `ZN.md` 已明确 Windows x64 是当前 intended target，Linux/macOS 只属 optional/on-demand evidence。以最新架构契约和真实代码为准，本文件已纠正。

### 2. 确认此前 Windows 修复仍有真实 green evidence

开发基线 `993fef35f3734748cd72cb7f2a6cdf03ce0d3edb` 的 run：

```text
32701839271
```

真实结果：

```text
ZN Source Boundary / Windows        success
ZN Kernel / Python / Windows        success
Electron / TypeScript / Windows     success
Publish Windows CI statuses         success
```

这证明此前 SQLite connection ownership fix 与 Windows Git-Bash test portability fix 已收敛。

### 3. 追 resident-owned targeted verifier 调用链

真实链路：

```text
RepositoryVerifyingResidentRuntime
→ _repo_targeted_test_spec()
→ canonical_kernel_unittest_identity()
→ observe mirrored test + .github/workflows/zn-ci.yml
→ ci_source_runs_kernel_unittest_suite()
→ persist resident_repo_evidence identity
→ native verification
→ _targeted_unittest_command()
→ current-world post-test recheck
```

当前 `zn-ci.yml` 的 kernel suite 是：

```powershell
$env:PYTHONPATH = Join-Path $env:GITHUB_WORKSPACE 'runtime\python'
& .\.ci\runtime-venv\Scripts\python.exe -m unittest discover -s tests/zn_agent/core -p 'test_*.py' -v
```

但原 `ci_source_runs_kernel_unittest_suite()` 只识别单行：

```text
run: python -m unittest discover -s tests/zn_agent/core -p 'test_*.py' -v
```

因此当前真实 CI 文本不能形成 resident verifier authority。这是产品能力回归，不是 CI failure。

### 4. 修复 verifier contract 识别

提交：

```text
d302421385409d205183031d4a1726ad3d2f419f
fix: recognize current Windows kernel verifier contract
```

修改：

```text
runtime/python/zn_agent/core/repo_test_semantics.py
```

新逻辑保留旧单行精确契约，同时对当前 Windows steady-state CI 仅接受严格的 literal PowerShell block：

- 前一 sibling 必须是 `shell: powershell`；
- 必须设置 working-tree `PYTHONPATH` 为 `runtime\python`；
- 必须调用 `.ci\runtime-venv\Scripts\python.exe`；
- unittest discover target/pattern/verbosity 必须精确匹配；
- run block 不能夹带额外 executable lines；
- 任一 shell/path/target/command 漂移都会 fail closed，直到重新证明当前 verifier relation。

### 5. 补回归测试

提交：

```text
dd237947a5122e2577ef75fd3556fa63b9a5e595
test: cover current Windows kernel verifier semantics
```

修改：

```text
tests/zn_agent/core/test_repo_test_semantics_authority.py
```

新增正例覆盖当前 Windows kernel run block，并增加负例：

- shell 改为 bash；
- runtime venv path 漂移；
- tests target 漂移；
- PYTHONPATH 漂移；
- command 被注释；
- block 添加额外 executable line。

## 本地 / 隔离验证

因为当前环境没有私有仓库本地 checkout，本轮不能伪装成运行了完整 working tree tests。

已在隔离最小模块副本中真实运行新增语义测试：

```text
3 tests passed
```

覆盖：

- 非 run 文本不能形成 authority；
- 旧单行精确 verifier 仍可识别；
- 当前 Windows PowerShell verifier 可识别；
- 上述漂移负例全部 fail closed。

这只是局部语义验证，不替代仓库 Windows CI。

## 当前真实 CI

本轮 exact-head run：

```text
32783489487
head = dd237947a5122e2577ef75fd3556fa63b9a5e595
```

当前状态：

```text
status = pending
jobs = none assigned yet
conclusion = none
```

即 GitHub 已创建 push run，但当前 self-hosted Windows runner 尚未接走 job。不要把它写成 success，也不要把 pending 当代码 failure。

前一个代码提交 `d302421...` 的 run 因连续 push / concurrency 可能被后续 exact-head run 取代；最终只认最新 exact HEAD 的真实执行结果。

## 相关文件

```text
runtime/python/zn_agent/core/repo_test_semantics.py
runtime/python/zn_agent/core/repo_test_resident.py
runtime/python/zn_agent/core/procedural_resident.py
tests/zn_agent/core/test_repo_test_semantics_authority.py
tests/zn_agent/core/test_repo_auto_targeted_test_verification.py
.github/workflows/zn-ci.yml
docs/ZN-NEXT-PHASE.md
docs/ZN-IMPLEMENTATION-STATUS.md
.agent/HANDOFF.md
```

## 风险 / 边界

- 不修改 `main`，除非用户明确要求且 promotion 条件真实满足。
- 禁止 force push / history rewrite。
- 不能因 CI workflow 改写就静默扩大 command authority；verifier mapping 必须由当前 repo-owned 结构证据形成并 fail closed。
- CI success 与 resident ability 是两个不同事实；CI 绿不能证明 resident 的 verifier identity parser 仍认识当前 CI。
- 不能把 pending/cancelled Actions run 写成成功或代码失败。
- Linux/macOS evidence 当前不阻塞 Windows intended target；但历史 evidence 不能被改写成不存在。
- M8 updater / rollback / signing 仍属高风险 release boundary。

## 当前未完成 / Task Queue

### P0 — current Windows verifier contract regression
Status: **PATCHED + LOCAL SEMANTIC TESTED / EXACT CI PENDING**

### P1 — exact-head Windows CI
Status: **PENDING SELF-HOSTED RUNNER EXECUTION**

需要真实通过：

```text
ZN Source Boundary / Windows
ZN Kernel / Python / Windows
Electron / TypeScript / Windows
Publish Windows CI statuses
```

### P2 — broader resident-owned engineering verifier selection
Status: **NEXT PRODUCT LANE AFTER P0/P1**

继续 `docs/ZN-NEXT-PHASE.md` P1：寻找 repo-owned structured verifier mappings，不从文件名、模型建议或 task prose 猜任意命令。

### P3 — M8 Windows continuity / rollback / signing
Status: **PENDING / PARTIAL**

### P4 — browser/computer Body/Senses
Status: **PENDING**

### P5 — SM1+ self-maintenance
Status: **PENDING**

## 下一真实目标

1. 读取本 HANDOFF 提交后的真实 `dev/zn-agent` HEAD；
2. 读取该 exact HEAD 的 Windows CI，只有真实 job 执行且全绿才把本轮 verifier regression 标 verified；
3. 若 CI failure，读取真实 job logs 并修复，不降低断言或 authority 边界；
4. CI 通过后更新 `docs/ZN-IMPLEMENTATION-STATUS.md`，记录当前 Windows verifier relation 已恢复；
5. 然后继续 resident-owned engineering verifier selection，而不是回到已结束的 migration 主线或让 optional Linux evidence 阻塞 Windows 开发。
