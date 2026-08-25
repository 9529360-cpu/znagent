# ZN Agent Handoff

更新时间：2026-08-25

## 当前目标

当前主线仍是 **ZN resident-owned engineering competence**。Windows x64 是 intended product / steady-state CI target；Linux/macOS 仅 optional/on-demand。M8 Windows clean install / N→N+1 / rollback / signing 仍是独立 partial milestone。

本阶段刚完成 P0 exact-head Windows CI 恢复与 verifier narrow slice 的首次当前 Windows CI 验证。下一步继续 P1/P2，但只能从真实 repo-owned structured evidence 扩大，不把 verifier manifest 变成任意命令 authority。

核心原则：

> **ZN uses models. Models do not own ZN.**

## 当前分支 / HEAD

- 固定开发分支：`dev/zn-agent`
- canonical source/release branch：`main`
- 本 HANDOFF 写入前开发 HEAD：`7fe0444a6633536a3678074776c006f41b4dd7b2`
- canonical `main`：`8234a835dea604783cea0bd9d28a40de654ec03d`
- `dev/zn-agent` 相对 `main`：线性 ahead 63、behind 0（本 HANDOFF/status 同步 commit 会再前进一次）
- PR #6：draft/open，base `main`，head `dev/zn-agent`，mergeable，未合并
- `main` 未修改；没有 force push/history rewrite

## 已完成事项

### 1. Current Windows verifier contract repair

```text
d302421385409d205183031d4a1726ad3d2f419f  fix: recognize current Windows kernel verifier contract
dd237947a5122e2577ef75fd3556fa63b9a5e595  test: cover current Windows kernel verifier semantics
```

resident 严格识别当前 Windows PowerShell kernel unittest contract；shell、runtime Python、PYTHONPATH、test target/pattern 或额外 executable line 漂移均 fail closed。

### 2. Bounded repo-owned verifier manifest

```text
c3f0ffbd7e09020dbda38d62fecae4bae8f8ec84  feat: add repo-owned verifier manifest semantics
96ce7cd4fde054c8ae958bd593457621592f09a4  feat: form verifier identity from tracked manifest
aaf1ed22ccfa060c11a61fcf669bb7f8ae93d9f9  feat: declare bounded repo verifier mapping
2f338cc13b8f8bb458908609ce60aac2610628e5  test: prove manifest verifier authority boundaries
b344d477f8d21540816b7f8c7d3b8c089d3bf71f  feat: map git semantics to owned verifier
3289f3d418a8f63e318433b46501eebf03fefcc3  test: validate declared verifier mappings
```

`.agent/zn-engineering-verifiers.json` 只能声明 literal `target` + `test`。它不能携带 command/shell/workdir/timeout，也不能把模型建议或 task prose 变成执行 authority。

当前两条真实 relation：

```text
runtime/python/zn_agent/core/repo_test_semantics.py
→ tests/zn_agent/core/test_repo_test_semantics_authority.py

runtime/python/zn_agent/core/git_semantics.py
→ tests/zn_agent/core/test_git_staging_semantics.py
```

runtime 仍要求 manifest/test/CI tracked + clean + same HEAD、安全路径、top-level direct import、discoverable unittest、current CI suite proof、execution anti-replay 和 fresh post-action verification。

### 3. Windows host-pressure test isolation repair

第一次 runner 恢复后的完整 Kernel run 暴露：真实 CI 主机磁盘 free ratio 低于 10%，ZN 正确形成 `body_health = constrained` / `body resources` attention；旧测试错误地把宿主资源状态假设为 `nominal`。断言失败后部分 store 没有先关闭，又叠加 Windows `WinError 32` 临时目录清理噪音。

修复只改测试，不改生产 `life.py`：

```text
40e1ae4f0d0043a9a2205f8b4299855f427de847  test: isolate life semantics from host disk pressure
a7d8e91985da62831d6ea95994d22d9b1d914a95  test: isolate endogenous attention from host disk pressure
d44e454fd3aa559c4c8e4445ba10224cd70e130a  test: isolate cognition rpc from host disk pressure
7fe0444a6633536a3678074776c006f41b4dd7b2  test: isolate visual attention from host disk pressure
```

新增低磁盘回归测试明确保护 `constrained → body resources` 语义；相关失败路径使用 `finally` 关闭 store。

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

Body resource path remains:

```text
ZNLifeCore.pulse()
→ _sense_body()
→ _build_situation()
→ disk_free_ratio < 0.10 => body_health = constrained
→ _derive_drives() / _form_thought()
→ preserve body resources / inspect body constraint
```

生产语义保留，测试隔离宿主偶发资源压力。

## 真实测试 / CI

当前权威 exact-code-head Windows 证据：

```text
run  32826260973
head 7fe0444a6633536a3678074776c006f41b4dd7b2

ZN Kernel / Python / Windows        success
  isolated znagent install          success
  zero-model resident boot          success
  resident core compile             success
  full core unittest discovery      389 tests passed, 5 skipped

ZN Source Boundary / Windows        success
Electron / TypeScript / Windows     success
Publish Windows CI statuses         success
```

Electron job 同时通过 locked install、high-severity npm audit、typecheck、bundle、desktop ownership/runtime/update tests 和 release/runtime artifact verifier tests。

该 run 是当前 verifier manifest、两条真实 mapping 和 current Windows PowerShell verifier contract 的真实 exact-head CI 证据。

当前 runner：repository self-hosted Windows x64 `ah-windows` 已恢复接单。runner 是可替换基础设施，不得成为产品身份或不可替换依赖。

当前环境没有私有仓库本地 checkout，因此没有把未执行的本地 suite 伪装成验证；以上结论来自真实 GitHub Actions。

## Diff / ownership 对账

`main` 仍是 `8234a835dea604783cea0bd9d28a40de654ec03d`，未修改。

`dev/zn-agent` 在本 HANDOFF 写入前相对 `main` ahead 63 / behind 0；PR #6 draft/open，changed files 40。本轮实际修复只涉及 4 个 cognition/life 测试文件；生产 low-disk sensing 没有削弱，没有外部产品 runtime/control-plane 回流。

`ZN.md`、`AGENTS.md`、`ZN-SOURCE-EXTRACTION.md`、`ZN-SELF-MAINTENANCE.md` 本轮无需架构/status 变更；实现状态变化记录在 `ZN-IMPLEMENTATION-STATUS.md` 与本 HANDOFF。

## 风险 / 边界

- 不修改 `main`，除非用户明确要求且 promotion 条件真实满足。
- 禁止 force push / history rewrite。
- manifest 不是 command catalog；不得加入 shell command、模型建议命令或 task-prose-derived authority。
- dirty/stale/ambiguous manifest 必须 fail closed。
- manifest 不能绕过 Git clean/HEAD proof、test structure proof、CI proof、post-action verification 或 anti-replay。
- 当前 Windows runner 主机曾真实处于低磁盘状态；这是 Body 可感知现实，不应通过削弱生产感知来“修 CI”。
- GitHub Actions 日志出现 Node 20 action runtime deprecation warning（当前被 runner 强制用 Node 24 执行且本轮成功）；后续只能通过稳定、验证过的 action 升级处理，不盲目升级或降低 CI。
- M8 updater/rollback/signing 仍是高风险 release boundary。

## Task Queue

### P0 — exact-head Windows CI
Status: **COMPLETE FOR CODE HEAD `7fe0444...` / RUN `32826260973`**

四个 steady-state Windows jobs 全绿。状态/HANDOFF 同步 commit 产生的新 exact HEAD 仍需按正常 push CI 再确认。

### P1 — bounded verifier manifest
Status: **VERIFIED NARROW SLICE / TWO REAL RELATIONS / EXACT WINDOWS CI GREEN**

### P2 — broader resident-owned engineering verifier selection
Status: **PARTIAL / ACTIVE**

只在真实 target→test relation 和完整 authority/evidence 边界成立时继续；没有合适 relation 时不要为了数量扩 manifest。

### P3 — browser/computer Body/Senses
Status: **PENDING**

### P4 — M8 Windows continuity / rollback / signing
Status: **PENDING / PARTIAL**

### P5 — SM1+ self-maintenance
Status: **PENDING**

## 下一真实目标

1. 读取包含本 HANDOFF/status 同步的真实 `dev/zn-agent` HEAD，并确认其自动 Windows x64 CI；
2. CI 继续全绿后，恢复 resident-owned engineering competence P2，先找真实 repo-owned structured verifier relation，不从文件名或模型文字猜 authority；
3. 若当前代码没有值得新增的 bounded verifier relation，按 `ZN.md` 优先级进入 browser/computer Body/Senses 调查；
4. 保持 M8 Windows clean-install / installed N→N+1 / rollback / signing 为 partial，未经真实证据不得标 complete；
5. 不触碰 `main`，除非用户明确要求并重新核验 promotion 条件。
