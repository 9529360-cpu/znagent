# ZN Agent Handoff

更新时间：2026-08-25

## 当前目标

当前主线是 ZN resident-owned engineering competence，不是 migration cleanup。

本阶段先恢复了 resident 对当前 Windows PowerShell kernel CI 的 targeted unittest authority，随后向 `docs/ZN-NEXT-PHASE.md` P1 推进一个更广但仍 fail-closed 的 verifier-selection 机制：repo-owned verifier manifest 只能声明非镜像 kernel module → unittest candidate relation；它不能提供任意命令，也不能单独形成执行 authority。

核心原则：

> **ZN uses models. Models do not own ZN.**

Linux/macOS 当前仅是 optional/on-demand evidence。Windows x64 是 intended product/steady-state CI target。M8 Windows clean install / N→N+1 / rollback / signing 仍是独立 partial milestone。

## 当前分支 / HEAD

- 固定开发分支：`dev/zn-agent`
- canonical source/release branch：`main`
- 本文件更新前开发 HEAD：`2f338cc13b8f8bb458908609ce60aac2610628e5`
- canonical `main`：`8234a835dea604783cea0bd9d28a40de654ec03d`
- `dev/zn-agent` 相对 `main`：线性 ahead / behind 0；禁止 force push/history rewrite
- PR #6：draft/open，base `main`，head `dev/zn-agent`，未合并
- 本文件提交后开发 HEAD 会再次前进；接手者必须重新读取真实 ref

## 已完成事项

### 1. Windows verifier contract regression

此前真实调用链：

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

旧语义只识别一行式 `run: python -m unittest ...`，无法识别当前 Windows PowerShell block，因此 steady-state CI 可以全绿而 resident verifier identity formation fail closed。

修复提交：

```text
d302421385409d205183031d4a1726ad3d2f419f
fix: recognize current Windows kernel verifier contract

dd237947a5122e2577ef75fd3556fa63b9a5e595
test: cover current Windows kernel verifier semantics
```

当前语义只接受精确 current Windows verifier contract：PowerShell shell、working-tree `PYTHONPATH`、isolated runtime Python、exact unittest discover target/pattern/verbosity；shell/path/target/extra executable line 漂移均 fail closed。

### 2. Broader repo-owned verifier selection — bounded manifest slice

新增提交：

```text
c3f0ffbd7e09020dbda38d62fecae4bae8f8ec84
feat: add repo-owned verifier manifest semantics

96ce7cd4fde054c8ae958bd593457621592f09a4
feat: form verifier identity from tracked manifest

aaf1ed22ccfa060c11a61fcf669bb7f8ae93d9f9
feat: declare bounded repo verifier mapping

2f338cc13b8f8bb458908609ce60aac2610628e5
test: prove manifest verifier authority boundaries
```

新增：

```text
.agent/zn-engineering-verifiers.json
```

当前只声明一个真实非镜像关系：

```text
runtime/python/zn_agent/core/repo_test_semantics.py
→ tests/zn_agent/core/test_repo_test_semantics_authority.py
```

manifest contract：

- JSON schema 极小：`version` + `mappings`；
- mapping 只有 `target` + `test`；
- 不能携带 command/shell/workdir/timeout 等执行参数；
- 只允许 ZN kernel top-level Python target 与 `tests/zn_agent/core/test_*.py`；
- duplicate target、未知字段、非法路径、错误版本、过大 mapping list 全部 fail closed；
- canonical mirrored test relation 仍优先，manifest 只补非 canonical relation。

resident authority 仍要求独立现实证据：

```text
manifest tracked + clean + same HEAD
+ selected test tracked + clean + same HEAD
+ selected test directly imports target module
+ selected test has discoverable unittest TestCase/test_ method
+ current CI still proves exact kernel unittest suite
+ runtime/python source root resolves safely
→ candidate python_unittest identity
```

形成 identity 后，仍走原来的 bounded executor、execution-start anti-replay、target/test/CI post-action recheck。manifest 自身 source/Git fingerprints 也进入 baseline/snapshot matching；manifest relation 漂移会撤销旧 identity。

### 3. 新测试

新增：

```text
tests/zn_agent/core/test_repo_manifest_verifier.py
```

覆盖：

- 一个 literal/unambiguous mapping 可解析；
- malformed JSON / wrong version / duplicate target / unknown command field / path escape fail closed；
- tracked clean manifest 可选择非 canonical unittest；
- dirty manifest 不能形成 command authority；
- test 不直接 import target 时不能形成 command authority。

现有 `test_repo_auto_targeted_test_recovery.py` 已覆盖 resident-formed verifier 的 restart、CI drift、test-source drift；manifest fingerprint 被接入同一 snapshot lifecycle，未复制第二套 recovery framework。

## 真实测试 / CI 结果

### 已有 Windows 绿基线

`993fef35f3734748cd72cb7f2a6cdf03ce0d3edb` 的 run `32701839271`：

```text
ZN Source Boundary / Windows        success
ZN Kernel / Python / Windows        success
Electron / TypeScript / Windows     success
Publish Windows CI statuses         success
```

它证明此前 SQLite connection ownership fix 与 Windows Git-Bash portability fix 已收敛，但不覆盖本阶段新 manifest verifier 代码。

### 本阶段 exact-head CI

当前代码 HEAD `2f338cc13b8f8bb458908609ce60aac2610628e5` 对应 run：

```text
32789614531
status = pending
conclusion = none
jobs = []
```

GitHub 已创建 workflow run，但 self-hosted runner 尚未接走任何 job。连续 push 会取消旧 run，因此只认最新 exact HEAD 的真实执行结果。

不要把 pending 写成 success，也不要把 `jobs=[]` 写成代码 failure。

当前连接器没有暴露 repository runner inventory/online-state API，因此只能从 Actions run 无 job assignment 这一现实证据判断 runner 尚未接受任务。

### 本地/当前环境限制

当前环境没有私有仓库本地 checkout，因此没有伪装运行完整 working-tree suite。上一阶段只对 Windows verifier semantics 做过最小隔离语义验证；本阶段 manifest integration tests 尚需仓库 Windows CI 作为权威执行证据。

## Diff 对账

相对本阶段起点 `ac7a5ffb26bb119000ceec58fcf208938ace2d1f`，当前仅新增/修改：

```text
.agent/zn-engineering-verifiers.json
runtime/python/zn_agent/core/repo_test_semantics.py
runtime/python/zn_agent/core/repo_test_resident.py
tests/zn_agent/core/test_repo_manifest_verifier.py
```

无 main 修改，无 force push/history rewrite，无外部产品 runtime/control-plane 回流。

## 相关文件

```text
ZN.md
AGENTS.md
docs/ZN-NEXT-PHASE.md
docs/ZN-IMPLEMENTATION-STATUS.md
.agent/HANDOFF.md
.agent/zn-engineering-verifiers.json
.github/workflows/zn-ci.yml
runtime/python/zn_agent/core/procedural_resident.py
runtime/python/zn_agent/core/repo_test_semantics.py
runtime/python/zn_agent/core/repo_test_resident.py
tests/zn_agent/core/test_repo_test_semantics_authority.py
tests/zn_agent/core/test_repo_auto_targeted_test_verification.py
tests/zn_agent/core/test_repo_auto_targeted_test_recovery.py
tests/zn_agent/core/test_repo_manifest_verifier.py
```

## 风险 / 边界

- 不修改 `main`，除非用户明确要求且 promotion 条件真实满足。
- 禁止 force push / history rewrite。
- manifest 不是 command catalog；不得加入任意 shell command、模型建议命令或 task-prose-derived authority。
- manifest 不能绕过 test direct-import proof、CI proof、Git clean/HEAD proof、post-action verification 或 anti-replay。
- dirty/stale/ambiguous manifest 必须 fail closed。
- CI success 与 resident ability 是两个不同事实；必须测试 resident identity formation，而不能只看 workflow 自己绿。
- self-hosted runner pending 是基础设施阻塞，不等于代码失败。
- `docs/ZN-IMPLEMENTATION-STATUS.md` 暂不把 manifest slice 写成 VERIFIED，直到 exact-head Windows CI 真正执行并通过。
- M8 updater/rollback/signing 仍属于高风险 release boundary。

## Task Queue

### P0 — exact-head Windows CI for verifier work
Status: **BLOCKED ON SELF-HOSTED RUNNER ACCEPTING JOB**

需要真实通过：

```text
ZN Source Boundary / Windows
ZN Kernel / Python / Windows
Electron / TypeScript / Windows
Publish Windows CI statuses
```

### P1 — repo-owned verifier manifest slice
Status: **IMPLEMENTED + TESTS ADDED / CI NOT YET EXECUTED**

若 CI 失败，按真实日志修复，不降低 authority/assertion 边界。

### P2 — broader resident-owned verifier selection
Status: **PARTIAL**

当前只支持 canonical mirrored unittest + 一个明确 manifest relation。不要扩成任意命令或自动猜测。下一步应基于真实 repo-owned structure/evidence 评估是否需要更多 verifier kind/relations。

### P3 — M8 Windows continuity / rollback / signing
Status: **PENDING / PARTIAL**

### P4 — browser/computer Body/Senses
Status: **PENDING**

### P5 — SM1+ self-maintenance
Status: **PENDING**

## 下一真实目标

1. 重新读取本 HANDOFF 提交后的真实 `dev/zn-agent` HEAD；
2. 读取该 exact HEAD 的 Windows CI；
3. 若 runner 执行并 CI failure，读取真实 job logs并修复；
4. 若 exact-head Windows CI 全绿，更新 `docs/ZN-IMPLEMENTATION-STATUS.md`，把 current Windows verifier relation 与 bounded manifest slice 按实际证据写入 VERIFIED NARROW SLICES；
5. 然后继续 `docs/ZN-NEXT-PHASE.md` P1，寻找下一个 repo-owned structured verifier relation，不从文件名、模型建议或 task prose 猜任意命令。
