# ZN Agent Handoff

更新时间：2026-08-25

## 当前目标

当前主线是 ZN resident-owned engineering competence。Windows x64 是 intended product / steady-state CI target；Linux/macOS 仅 optional/on-demand。M8 Windows clean install / N→N+1 / rollback / signing 仍是独立 partial milestone。

本阶段继续 `docs/ZN-NEXT-PHASE.md` P1：扩大 repo-owned structured verifier relation，但不扩大成任意命令 authority。

核心原则：

> **ZN uses models. Models do not own ZN.**

## 当前分支 / HEAD

- 固定开发分支：`dev/zn-agent`
- canonical source/release branch：`main`
- 本文件更新前开发 HEAD：`3289f3d418a8f63e318433b46501eebf03fefcc3`
- canonical `main`：`8234a835dea604783cea0bd9d28a40de654ec03d`
- `dev/zn-agent` 相对 `main`：线性 ahead，behind 0
- PR #6：draft/open，base `main`，head `dev/zn-agent`，未合并
- 本文件提交会再次前进 HEAD；接手者必须重读真实 ref

## 已完成事项

### 1. Current Windows verifier contract repair

提交：

```text
d302421385409d205183031d4a1726ad3d2f419f
fix: recognize current Windows kernel verifier contract

dd237947a5122e2577ef75fd3556fa63b9a5e595
test: cover current Windows kernel verifier semantics
```

resident 只接受当前严格 Windows PowerShell kernel unittest contract；shell、runtime Python、PYTHONPATH、test target/pattern 或额外 executable line 漂移均 fail closed。

### 2. Bounded repo-owned verifier manifest

提交：

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

manifest：

```text
.agent/zn-engineering-verifiers.json
```

只能声明 `target` + `test`，不能携带 command/shell/workdir/timeout。resident 仍要求：manifest/test/CI tracked + clean + same HEAD、test 顶层直接 import target、discoverable unittest、current CI exact suite proof、安全 source root、post-action recheck 与 execution anti-replay。

### 3. 第二个真实 verifier relation

本轮重新恢复真实仓库状态后，读取 `tests/zn_agent/core/test_git_staging_semantics.py`，确认其顶层直接导入：

```text
zn_agent.core.git_semantics
```

且包含顶层 `unittest.TestCase` / `test_*`。因此不是从文件名猜测，而是当前源码结构证明的 relation。

提交：

```text
b344d477f8d21540816b7f8c7d3b8c089d3bf71f
feat: map git semantics to owned verifier
```

当前 manifest 明确声明两条 relation：

```text
runtime/python/zn_agent/core/repo_test_semantics.py
→ tests/zn_agent/core/test_repo_test_semantics_authority.py

runtime/python/zn_agent/core/git_semantics.py
→ tests/zn_agent/core/test_git_staging_semantics.py
```

### 4. Repository manifest self-check

提交：

```text
3289f3d418a8f63e318433b46501eebf03fefcc3
test: validate declared verifier mappings
```

`tests/zn_agent/core/test_repo_manifest_verifier.py` 新增真实仓库 manifest 自检。对每条 mapping 验证：

- manifest parser 能形成唯一 identity；
- target 文件真实存在；
- test 文件真实存在；
- test 顶层直接 import target module；
- test 有 discoverable unittest case。

因此未来错误手工 mapping 不只在 resident runtime 静默 fail closed，也会被 kernel test suite 直接暴露。

## 真实调用链

```text
provider_bridge.build_resident_runtime()
→ RepositoryVerifyingResidentRuntime
→ _repo_targeted_test_spec()
→ canonical mirrored identity OR tracked/clean manifest mapping
→ observe selected test + optional manifest + .github/workflows/zn-ci.yml
→ direct-import proof + discoverable unittest proof + current CI suite proof
→ persist resident_repo_evidence identity
→ native action
→ existing _targeted_unittest_command()
→ execution-start anti-replay
→ command execution
→ fresh target/test/CI/manifest current-world snapshot
→ completion only if evidence still matches
```

manifest 没有独立 executor，也不能绕过 existing typed `python_unittest` lifecycle。

## 真实测试 / CI

已有可信 Windows 绿基线：

```text
run 32701839271
head 993fef35f3734748cd72cb7f2a6cdf03ce0d3edb
ZN Source Boundary / Windows        success
ZN Kernel / Python / Windows        success
Electron / TypeScript / Windows     success
Publish Windows CI statuses         success
```

该 run 不覆盖当前 manifest 工作。

当前 exact code HEAD `3289f3d418a8f63e318433b46501eebf03fefcc3` 的 run：

```text
32799836504
status = pending
conclusion = none
jobs = []
```

self-hosted Windows runner 尚未接受任何 job。前一 commit `b344d477...` 的 run 因后续 push / workflow concurrency 被取消，这不是代码 failure。

当前环境没有私有仓库本地 checkout，因此没有伪装运行完整 working-tree suite。当前 manifest code/tests 仍需 exact-head Windows CI 执行作为权威验证。

## Diff / ownership 对账

本轮 `d842206c...` 后只新增两类预期变化：

```text
.agent/zn-engineering-verifiers.json
  + git_semantics → test_git_staging_semantics relation

tests/zn_agent/core/test_repo_manifest_verifier.py
  + live repository manifest relation self-check
```

没有修改 `main`，没有 force push/history rewrite，没有外部产品 runtime/control-plane 回流。

## 风险 / 边界

- 不修改 `main`，除非用户明确要求且 promotion 条件真实满足。
- 禁止 force push / history rewrite。
- manifest 不是 command catalog；不得加入 shell command、模型建议命令或 task-prose-derived authority。
- dirty/stale/ambiguous manifest 必须 fail closed。
- manifest 不能绕过 Git clean/HEAD proof、test structure proof、CI proof、post-action verification 或 anti-replay。
- `pending / jobs=[]` 是 self-hosted runner 基础设施阻塞，不是代码成功或失败。
- 在 exact-head Windows CI 真正执行并通过前，不更新 `docs/ZN-IMPLEMENTATION-STATUS.md` 为 VERIFIED。
- 为避免 runner 离线期间堆积大量未验证行为，当前暂停继续扩大 manifest mappings。
- M8 updater/rollback/signing 仍是高风险 release boundary。

## Task Queue

### P0 — exact-head Windows CI
Status: **BLOCKED ON SELF-HOSTED RUNNER ACCEPTING JOB**

需要真实执行并通过：

```text
ZN Source Boundary / Windows
ZN Kernel / Python / Windows
Electron / TypeScript / Windows
Publish Windows CI statuses
```

### P1 — bounded verifier manifest
Status: **IMPLEMENTED / TWO REAL RELATIONS / TESTS ADDED / EXACT CI NOT EXECUTED**

### P2 — broader resident-owned engineering verifier selection
Status: **PARTIAL; HOLD FURTHER EXPANSION UNTIL P0**

### P3 — M8 Windows continuity / rollback / signing
Status: **PENDING / PARTIAL**

### P4 — browser/computer Body/Senses
Status: **PENDING**

### P5 — SM1+ self-maintenance
Status: **PENDING**

## 下一真实目标

1. 重新读取本 HANDOFF commit 后的真实 `dev/zn-agent` HEAD；
2. 读取该 exact HEAD Windows CI；
3. 若 runner 执行且失败，读真实 job logs 修复，不降低 authority/assertion 边界；
4. 若 exact-head Windows CI 全绿，更新 `docs/ZN-IMPLEMENTATION-STATUS.md`，记录 current Windows verifier relation、bounded manifest 与两条真实 mapping 已经 CI 验证；
5. CI 绿后再继续下一个 repo-owned structured verifier relation；不要在 runner 离线期间继续堆未验证 mapping。
