# ZN Agent Handoff

更新时间：2026-08-25

## 当前目标

当前主线是 **browser/computer Body/Senses**。第一块 typed pointer movement 已经通过 exact-head Windows CI；下一步不是盲目增加 click，而是先证明 click 之后存在足够独立、fresh、ZN-owned 的 current-world postcondition。Windows x64 是 intended product / steady-state CI target；Linux/macOS 仅 optional/on-demand。M8 Windows clean install / N→N+1 / rollback / signing 仍是独立 partial milestone。

核心原则：

> **ZN uses models. Models do not own ZN.**

## 当前分支 / HEAD

- 固定开发分支：`dev/zn-agent`
- canonical source/release branch：`main`
- 本 HANDOFF 写入前开发 HEAD：`83f45fd922ebc216933987d269b3c797d3875f2b`
- canonical `main`：`8234a835dea604783cea0bd9d28a40de654ec03d`
- `dev/zn-agent` 相对 `main`：ahead 69、behind 0；本状态同步 commit 会再前进一次
- PR #6：draft/open，base `main`，head `dev/zn-agent`，mergeable，未合并
- `main` 未修改；没有 force push/history rewrite

## 已完成事项

### 1. Bounded repo-owned verifier manifest — three real relations

当前三条真实 relation：

```text
runtime/python/zn_agent/core/repo_test_semantics.py
→ tests/zn_agent/core/test_repo_test_semantics_authority.py

runtime/python/zn_agent/core/git_semantics.py
→ tests/zn_agent/core/test_git_staging_semantics.py

runtime/python/zn_agent/core/result_semantics.py
→ tests/zn_agent/core/test_verified_experience.py
```

manifest 只能声明 literal `target` + `test`，不能携带 command/shell/workdir/timeout，也不能把模型建议或 task prose 变成执行 authority。第三 relation 已由 run `32829830325` exact-head Windows CI 验证。不为数量继续扩张。

### 2. Windows host-pressure test isolation

关键提交：

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

`NativeVisualSense._capture_primary_screen()` 默认依赖 Pillow `ImageGrab`，正式 runtime 现明确声明 `Pillow==12.3.0`。Run `32831968178` 证明 fresh isolated Python 3.12 runtime 安装和 390-test suite 通过。

### 4. Verified bounded pointer movement

```text
83f45fd922ebc216933987d269b3c797d3875f2b  feat: add verified pointer movement
```

实现范围刻意保持最小：

- `NativeBody` 增加 Windows primary-screen `pointer_move` / `pointer_state`；
- `pointer_move` 只接受 finite normalized `[0,1]` 坐标；
- structured `body_action` / `native_action` 是当前 authority，模型 prose / task text / procedural memory 不产生坐标 authority；
- side-effect 成功后进入现有 durable `native_verification`，不会直接完成任务；
- fresh `pointer_state` 重新读取 cursor position；
- observed position 与目标不符时记录 contradiction/negative evidence，并回到 Investigation；
- `ProcedurallyInfluencedResidentRuntime._verification_contract` 同步透传 action `result`，保持真实 product inheritance chain 兼容；没有扩大 procedural authority。

新增测试：

```text
test_pointer_move_is_bounded_normalized_body_movement
test_structured_pointer_move_waits_for_fresh_position_verification
test_pointer_drift_contradicts_success_and_returns_to_investigation
```

真实 exact-head Windows CI run `32844167956`：Source Boundary、Electron、Kernel、status publisher 全部 success；Kernel fresh isolated runtime / zero-model boot / compile / full suite 全绿，**393 tests passed, 5 skipped**。

这些测试使用 injected/fake pointer body；没有在 CI host 上真实移动鼠标，也没有把 runner 的交互桌面状态当成产品 E2E 证据。

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
→ persistent NativeVisualSense
→ _visual_loop()
→ maybe_sample()
→ _capture_primary_screen()
→ Pillow ImageGrab local capture
→ compact frame hash / coarse regions / luminance
→ raw image discarded
→ resident.perceive_visual(...)
→ nervous traces / Situation / Thought / Will attention
```

### Pointer movement path

```text
structured event body_action/native_action
→ action.derive_native_action_intents()
→ NativeActionIntent(kind="pointer_move")
→ active resident deliberation / durable native action cycle
→ NativeBody.act("pointer_move")
→ Windows pointer movement
→ persist native_action_result
→ native_verification
→ verification contract binds expected normalized position to actual action result
→ NativeBody.act("pointer_state")
→ fresh current cursor position
→ match: complete + verified experience
→ mismatch/unavailable: contradiction → Investigation, no positive completion claim
```

## 真实测试 / CI

最新权威 implementation-head Windows evidence：

```text
run  32844167956
head 83f45fd922ebc216933987d269b3c797d3875f2b

ZN Kernel / Python / Windows        success
  fresh isolated Python 3.12        success
  znagent install                   success
  Pillow runtime dependency         success
  zero-model resident boot          success
  resident core compile             success
  full core unittest discovery      393 tests passed, 5 skipped
  pointer bounded-movement test      success
  pointer fresh-verification test    success
  pointer drift contradiction test   success

ZN Source Boundary / Windows        success
Electron / TypeScript / Windows     success
Publish Windows CI statuses         success
```

当前环境没有私有仓库本地 checkout；没有把未执行的本地 suite 伪装成验证。以上结论来自真实 GitHub Actions。

## Diff / ownership 对账

- `main` 仍是 `8234a835dea604783cea0bd9d28a40de654ec03d`，未修改。
- `dev/zn-agent` 在本 HANDOFF 写入前相对 `main` ahead 69 / behind 0。
- PR #6 draft/open、mergeable、未合并。
- pointer commit 只修改 `body.py`、`embodied_resident.py`、`procedural_resident.py` 和新增 `test_pointer_body.py`；没有引入外部 control plane。
- `procedural_resident.py` 的改动只是 verification signature/result passthrough 兼容。
- 当前没有继续扩 verifier manifest。

## 风险 / 边界

- 不修改 `main`，除非用户明确要求且重新核验 promotion 条件。
- 禁止 force push / history rewrite。
- manifest 不是 command catalog；不得加入 shell/model/task-prose authority。
- computer interaction 必须是 ZN-owned typed Body action；模型文字不能直接获得鼠标/键盘执行权。
- movement/input delivery success 不是 task completion；必须独立 current-world verification。
- 目前 cursor position 是 pointer movement 的合理独立 postcondition，但它不足以证明 click 对应用/UI 产生了目标效果。
- 在新增 click 前，必须找到可 fresh 观察且与点击目标相关的视觉/UI/world state；否则先加强 Senses，不加 side effect。
- 真实 Windows screen capture / interactive desktop 仍可能受 session/desktop/permission 状态影响。
- Windows runner 曾有真实低磁盘状态；不通过削弱 Body sensing 隐藏现实。
- Actions 仍有 Node 20 action runtime deprecation warning；仅通过稳定、验证过的 action upgrade 处理。
- M8 updater/rollback/signing 仍是高风险 release boundary。

## Task Queue

### P0 — exact-head Windows CI
Status: **GREEN THROUGH `83f45fd...` / RUN `32844167956`**

本 HANDOFF/status 同步产生的新 docs HEAD 仍需自动 Windows CI 再确认；不要仅为记录自身 run ID 再产生无限 docs commit。

### P1 — bounded verifier manifest
Status: **VERIFIED NARROW SLICE / THREE REAL RELATIONS**

不为数量继续扩张。

### P2 — resident visual foundation
Status: **VERIFIED PACKAGING + SEMANTICS FOUNDATION**

formal runtime owns Pillow；real-session capture permission/E2E 仍未验证。

### P3 — bounded computer interaction Body
Status: **VERIFIED FIRST SLICE / POINTER MOVE**

`pointer_move` + fresh `pointer_state` verification 已通过 exact-head Windows CI。Click/keyboard/browser mutation 未实现。

### P4 — click/browser current-world verification
Status: **ACTIVE / INVESTIGATION**

先找独立 postcondition，再决定最小 typed action。若现有 visual sense 只能证明粗粒度 frame change，而无法证明目标 effect，则优先加强可验证视觉/UI sensing，不允许用 input API success 冒充完成。

### P5 — M8 Windows continuity / rollback / signing
Status: **PENDING / PARTIAL**

### P6 — SM1+ self-maintenance
Status: **PENDING**

## 下一真实目标

1. 确认包含本状态同步的 docs HEAD 自动 Windows x64 CI；
2. 同时只读追 click/browser 的 entry → owner → state → lifecycle → dependency → tests → active caller；
3. 明确 click 的 fresh independent verifier；没有 verifier 就不加 click；
4. 如果现有 compact visual sense 不足以验证目标 UI effect，先增强 ZN-owned sensing/current-world evidence；
5. 保持 M8 partial；不触碰 `main`。
