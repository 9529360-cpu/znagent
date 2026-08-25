# ZN Agent Handoff

更新时间：2026-08-25

## 当前目标

当前主线已从 verifier manifest 的第三条真实 relation 转入 **browser/computer Body/Senses**。Windows x64 是 intended product / steady-state CI target；Linux/macOS 仅 optional/on-demand。M8 Windows clean install / N→N+1 / rollback / signing 仍是独立 partial milestone。

核心原则：

> **ZN uses models. Models do not own ZN.**

## 当前分支 / HEAD

- 固定开发分支：`dev/zn-agent`
- canonical source/release branch：`main`
- 本 HANDOFF 写入前开发 HEAD：`58aee1ea4331264fcc0abcf73843b91ca6dc0879`
- canonical `main`：`8234a835dea604783cea0bd9d28a40de654ec03d`
- `dev/zn-agent` 相对 `main`：ahead 67、behind 0；本状态同步 commit 会再前进一次
- PR #6：draft/open，base `main`，head `dev/zn-agent`，mergeable，未合并
- `main` 未修改；没有 force push/history rewrite

## 已完成事项

### 1. Bounded repo-owned verifier manifest — three real relations

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

当前三条真实 relation：

```text
runtime/python/zn_agent/core/repo_test_semantics.py
→ tests/zn_agent/core/test_repo_test_semantics_authority.py

runtime/python/zn_agent/core/git_semantics.py
→ tests/zn_agent/core/test_git_staging_semantics.py

runtime/python/zn_agent/core/result_semantics.py
→ tests/zn_agent/core/test_verified_experience.py
```

manifest 只能声明 literal `target` + `test`，不能携带 command/shell/workdir/timeout，也不能把模型建议或 task prose 变成执行 authority。第三 relation 已由 run `32829830325` exact-head Windows CI 验证。

### 2. Windows host-pressure test isolation

```text
40e1ae4f0d0043a9a2205f8b4299855f427de847  test: isolate life semantics from host disk pressure
a7d8e91985da62831d6ea95994d22d9b1d914a95  test: isolate endogenous attention from host disk pressure
d44e454fd3aa559c4c8e4445ba10224cd70e130a  test: isolate cognition rpc from host disk pressure
7fe0444a6633536a3678074776c006f41b4dd7b2  test: isolate visual attention from host disk pressure
```

生产 low-disk Body 语义保留；测试隔离与 Body health 无关的宿主资源偶发状态，并保留 `<10% free → constrained → body resources` 回归。

### 3. Resident visual runtime packaging repair

```text
58aee1ea4331264fcc0abcf73843b91ca6dc0879  fix: package resident visual capture dependency
```

调查 browser/computer Body/Senses 时发现：`NativeVisualSense._capture_primary_screen()` 默认调用 `PIL.ImageGrab`，但正式 `runtime/python/pyproject.toml` 没声明 Pillow。测试可通过 injected `capture_fn`，正式 runtime 却可能因 `ImportError` 静默失去视觉。

修复：

- runtime 明确声明 `Pillow==12.3.0`；
- `test_runtime_ownership.py` 增加 installed-environment `PIL` 可导入回归；
- 未改变 visual ownership、采样语义或 raw-pixel persistence 边界。

真实 CI run `32831968178` 证明 fresh isolated Python 3.12 runtime 实际下载并安装 `pillow==12.3.0`，随后 installed-environment regression 通过。

## 真实调用链

### Verifier path

```text
provider_bridge.build_resident_runtime()
→ RepositoryVerifyingResidentRuntime
→ _repo_targeted_test_spec()
→ canonical mirrored identity OR tracked/clean manifest mapping
→ direct-import + discoverable unittest + current CI proof
→ typed python_unittest lifecycle
→ execution anti-replay
→ fresh post-action repository snapshot
→ completion only if evidence still matches
```

### Resident visual path

```text
ResidentSocketService
→ owns NativeVisualSense for the same resident
→ _visual_loop()
→ maybe_sample()
→ _capture_primary_screen()
→ Pillow ImageGrab local capture
→ compact frame hash / coarse regions / luminance
→ raw image discarded
→ resident.perceive_visual(...)
→ nervous traces / Situation / Thought / Will attention
```

Electron does not own the visual organ. Closing the UI does not define resident visual lifecycle.

## 真实测试 / CI

最新权威 implementation-head Windows evidence：

```text
run  32831968178
head 58aee1ea4331264fcc0abcf73843b91ca6dc0879

ZN Kernel / Python / Windows        success
  fresh isolated Python 3.12        success
  znagent install                   success
  pillow==12.3.0 install            success
  zero-model resident boot          success
  resident core compile             success
  full core unittest discovery      390 tests passed, 5 skipped
  PIL installed-environment test    success

ZN Source Boundary / Windows        success
Electron / TypeScript / Windows     success
Publish Windows CI statuses         success
```

CI verifies dependency packaging and injected-capture visual semantics. It does **not** yet prove that every installed Windows service/session has interactive desktop screen-capture permission; do not overstate this as real-session visual E2E.

当前环境没有私有仓库本地 checkout；没有把未执行的本地 suite 伪装成验证。以上结论来自真实 GitHub Actions。

## Diff / ownership 对账

- `main` 仍是 `8234a835dea604783cea0bd9d28a40de654ec03d`，未修改。
- `dev/zn-agent` 在本 HANDOFF 写入前相对 `main` ahead 67 / behind 0。
- PR #6 draft/open、mergeable、未合并。
- `58aee1...` 只修改 runtime dependency declaration 和 runtime ownership regression；没有引入外部 control plane。
- `terminal.py → test_terminal.py` 是 canonical mirror，不冗余加入 manifest。
- 当前没有继续为数量扩 verifier manifest。

## 风险 / 边界

- 不修改 `main`，除非用户明确要求且重新核验 promotion 条件。
- 禁止 force push / history rewrite。
- manifest 不是 command catalog；不得加入 shell/model/task-prose authority。
- computer interaction 必须是 ZN-owned typed Body action，不允许模型文字直接获得鼠标/键盘执行权。
- movement success 不是 task completion；computer action 必须有独立 current-world verification。
- 真实 Windows screen capture 仍可能受 session/desktop/permission 状态影响；dependency installed 不等于所有 session 都可 capture。
- Windows runner 曾有真实低磁盘状态；不通过削弱 Body sensing 隐藏现实。
- Actions 仍有 Node 20 action runtime deprecation warning；仅通过稳定、验证过的 action upgrade 处理。
- M8 updater/rollback/signing 仍是高风险 release boundary。

## Task Queue

### P0 — exact-head Windows CI
Status: **GREEN THROUGH `58aee1...` / RUN `32831968178`**

本 HANDOFF/status 同步产生的新 docs HEAD 仍需自动 Windows CI 再确认。

### P1 — bounded verifier manifest
Status: **VERIFIED NARROW SLICE / THREE REAL RELATIONS**

不为数量继续扩张。

### P2 — resident visual foundation
Status: **VERIFIED PACKAGING + SEMANTICS FOUNDATION**

正式 runtime 已拥有默认 Pillow capture dependency；real-session permission/E2E 仍未验证。

### P3 — bounded computer interaction Body
Status: **ACTIVE / INVESTIGATION**

目标是从现有 `NativeBody` + resident verification lifecycle 增加最小 typed computer action seam，并要求 fresh visual/current-world proof；先追真实 caller/state/lifecycle/tests，再修改。

### P4 — M8 Windows continuity / rollback / signing
Status: **PENDING / PARTIAL**

### P5 — SM1+ self-maintenance
Status: **PENDING**

## 下一真实目标

1. 确认包含本状态同步的最终 docs HEAD 自动 Windows x64 CI；
2. 同时只读追 computer interaction 的 entry → owner → state → lifecycle → dependency → tests → active caller；
3. 只实现最小 typed bounded action，不建立 browser agent/control plane，不让模型 prose 产生 action authority；
4. 为 side effect 增加 fresh visual/current-world verification 和 failure→Investigation 行为；
5. 保持 M8 partial；不触碰 `main`。
