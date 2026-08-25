# ZN Agent Handoff

更新时间：2026-08-25

## 当前目标

当前主线是 **ZN resident-owned engineering competence**。Windows x64 是 intended product / steady-state CI target；Linux/macOS 仅 optional/on-demand。M8 Windows clean install / N→N+1 / rollback / signing 仍是独立 partial milestone。

本阶段已把 bounded repo-owned verifier manifest 扩到三条真实 relation，并在 exact-head Windows CI 验证。下一步不能为了数量继续加 mapping：先调查是否还有真正非-canonical、结构明确、active caller 有意义的 verifier relation；如果没有，按 `ZN.md` 优先级进入 browser/computer Body/Senses。

核心原则：

> **ZN uses models. Models do not own ZN.**

## 当前分支 / HEAD

- 固定开发分支：`dev/zn-agent`
- canonical source/release branch：`main`
- 本 HANDOFF 写入前开发 HEAD：`9ec67267216665a7d62d1baa68f59cfa02eb3073`
- canonical `main`：`8234a835dea604783cea0bd9d28a40de654ec03d`
- `dev/zn-agent` 相对 `main`：ahead 65、behind 0；本状态同步 commit 会再前进一次
- PR #6：draft/open，base `main`，head `dev/zn-agent`，未合并
- `main` 未修改；没有 force push/history rewrite

## 已完成事项

### 1. Current Windows verifier contract

```text
d302421385409d205183031d4a1726ad3d2f419f  fix: recognize current Windows kernel verifier contract
dd237947a5122e2577ef75fd3556fa63b9a5e595  test: cover current Windows kernel verifier semantics
```

resident 严格识别当前 Windows PowerShell kernel unittest contract；shell、runtime Python、PYTHONPATH、test target/pattern 或额外 executable line 漂移均 fail closed。

### 2. Bounded repo-owned verifier manifest

关键提交：

```text
c3f0ffbd7e09020dbda38d62fecae4bae8f8ec84  feat: add repo-owned verifier manifest semantics
96ce7cd4fde054c8ae958bd593457621592f09a4  feat: form verifier identity from tracked manifest
aaf1ed22ccfa060c11a61fcf669bb7f8ae93d9f9  feat: declare bounded repo verifier mapping
2f338cc13b8f8bb458908609ce60aac2610628e5  test: prove manifest verifier authority boundaries
b344d477f8d21540816b7f8c7d3b8c089d3bf71f  feat: map git semantics to owned verifier
3289f3d418a8f63e318433b46501eebf03fefcc3  test: validate declared verifier mappings
9ec67267216665a7d62d1baa68f59cfa02eb3073  feat: map result semantics to owned verifier
```

`.agent/zn-engineering-verifiers.json` 只能声明 literal `target` + `test`。它不能携带 command/shell/workdir/timeout，也不能把模型建议或 task prose 变成执行 authority。

当前三条真实 relation：

```text
runtime/python/zn_agent/core/repo_test_semantics.py
→ tests/zn_agent/core/test_repo_test_semantics_authority.py

runtime/python/zn_agent/core/git_semantics.py
→ tests/zn_agent/core/test_git_staging_semantics.py

runtime/python/zn_agent/core/result_semantics.py
→ tests/zn_agent/core/test_verified_experience.py
```

第三条不是文件名猜测：不存在 canonical `test_result_semantics.py`；`test_verified_experience.py` 顶层直接 import `detect_masked_success` / `normalize_action_result`，有专门 masked-success/negative-evidence 断言；生产 resident completion/learning path 和 `verified_experience.py` 实际消费该语义。

runtime 仍要求 manifest/test/CI tracked + clean + same HEAD、安全路径、top-level direct import、discoverable unittest、current CI suite proof、execution anti-replay 和 fresh post-action verification。

### 3. Windows host-pressure test isolation

```text
40e1ae4f0d0043a9a2205f8b4299855f427de847  test: isolate life semantics from host disk pressure
a7d8e91985da62831d6ea95994d22d9b1d914a95  test: isolate endogenous attention from host disk pressure
d44e454fd3aa559c4c8e4445ba10224cd70e130a  test: isolate cognition rpc from host disk pressure
7fe0444a6633536a3678074776c006f41b4dd7b2  test: isolate visual attention from host disk pressure
```

生产 low-disk Body 语义没有改。测试对与 Body health 无关的场景固定健康磁盘，并保留 `disk_free_ratio < 0.10 → constrained → body resources` 直接回归；失败路径关闭 store，避免 Windows 临时目录清理被 SQLite handle 干扰。

### 4. Status/HANDOFF recovery sync

```text
2d37df8fb100b8117e47345381fe13ec5a0569ec  docs: record exact-head Windows CI recovery
```

该 docs head 自身 run `32827685146` 四个 Windows job 全绿后，才继续第三 relation。

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
→ existing typed python_unittest lifecycle
→ execution-start anti-replay
→ command execution
→ fresh target/test/CI/manifest current-world snapshot
→ completion only if evidence still matches
```

`result_semantics` active relation：

```text
Body action / command verification result
→ result_semantics.normalize_action_result()
→ resident completion / contradiction semantics
→ verified_experience safe causal record
→ procedural learning evidence
```

manifest 没有独立 executor，也不能绕过 existing typed `python_unittest` lifecycle。

## 真实测试 / CI

最新权威 verifier-head Windows 证据：

```text
run  32829830325
head 9ec67267216665a7d62d1baa68f59cfa02eb3073

ZN Kernel / Python / Windows        success
  isolated znagent install          success
  zero-model resident boot          success
  resident core compile             success
  full core unittest discovery      389 tests passed, 5 skipped
  repository manifest self-check    success
  test_verified_experience          success

ZN Source Boundary / Windows        success
Electron / TypeScript / Windows     success
Publish Windows CI statuses         success
```

上一 docs/HANDOFF head：

```text
run  32827685146
head 2d37df8fb100b8117e47345381fe13ec5a0569ec
all four Windows jobs                 success
```

当前环境没有私有仓库本地 checkout；没有把未执行的本地 suite 伪装成验证。以上结论来自真实 GitHub Actions。

## Diff / ownership 对账

- `main` 仍是 `8234a835dea604783cea0bd9d28a40de654ec03d`，未修改。
- `dev/zn-agent` 在本 HANDOFF 写入前相对 `main` ahead 65 / behind 0。
- 本轮第三 relation 只修改 `.agent/zn-engineering-verifiers.json`；没有修改 executor、production semantics、workflow、release、identity、memory 或 updater。
- `terminal.py → test_terminal.py` 已确认是 canonical mirror，所以没有冗余加入 manifest。
- `body.py → test_native_body.py` 未满足当前 direct-module relation 的干净证据，因此没有硬加。
- 没有外部产品 runtime/control-plane 回流。

## 风险 / 边界

- 不修改 `main`，除非用户明确要求且 promotion 条件真实满足。
- 禁止 force push / history rewrite。
- manifest 不是 command catalog；不得加入 shell command、模型建议命令或 task-prose-derived authority。
- dirty/stale/ambiguous manifest 必须 fail closed。
- manifest 不能绕过 Git clean/HEAD proof、test structure proof、CI proof、post-action verification 或 anti-replay。
- 当前 Windows runner 主机曾真实处于低磁盘状态；这是 Body 可感知现实，不通过削弱生产感知来修 CI。
- Actions 仍有 Node 20 action runtime deprecation warning；只能通过稳定、验证过的 action 升级处理。
- M8 updater/rollback/signing 仍是高风险 release boundary。

## Task Queue

### P0 — exact-head Windows CI
Status: **GREEN THROUGH `9ec672...` / RUN `32829830325`**

本 HANDOFF/status 同步产生的新 exact HEAD 仍需自动 Windows CI 再确认。

### P1 — bounded verifier manifest
Status: **VERIFIED NARROW SLICE / THREE REAL RELATIONS / EXACT WINDOWS CI GREEN**

### P2 — broader resident-owned engineering competence
Status: **PARTIAL / ACTIVE**

只在新的 relation 真正非-canonical、结构可证明、对 active caller 有意义时继续 manifest；禁止为了数量扩张。

### P3 — browser/computer Body/Senses
Status: **NEXT IF NO STRONGER VERIFIER RELATION**

### P4 — M8 Windows continuity / rollback / signing
Status: **PENDING / PARTIAL**

### P5 — SM1+ self-maintenance
Status: **PENDING**

## 下一真实目标

1. 确认包含本状态同步的最终 `dev/zn-agent` HEAD 自动 Windows x64 CI 全绿；
2. 只读调查下一条真正非-canonical verifier relation；若没有明确增益，不再扩 manifest；
3. 没有合适 relation 时进入 browser/computer Body/Senses，先追当前 visual/world/body seam 和 active caller，再做最小 ZN-owned capability；
4. 保持 M8 Windows clean-install / installed N→N+1 / rollback / signing 为 partial；
5. 不触碰 `main`，除非用户明确要求并重新核验 promotion 条件。
