# ZN Agent Handoff

更新时间：2026-08-25

## 当前目标

当前主线是 **browser/computer Body/Senses**。第一块 typed pointer movement 与第一块 target-local visual region sense 都已通过 exact-head Windows x64 CI。下一步不是把 input API 返回值包装成“会点击”，而是把最小 click 生命周期设计成：显式结构化 authority → side-effect 前 fresh 局部视觉 baseline → bounded click → fresh 局部视觉观察 → contradiction / narrow effect verification；若局部变化不足以证明请求的语义结果，则必须继续增强 Senses/verification，而不能宣称任务完成。

核心原则：

> **ZN uses models. Models do not own ZN.**

Windows x64 仍是 intended product / steady-state CI target；Linux/macOS 仅 optional/on-demand。M8 Windows clean install / N→N+1 / rollback / signing 仍是独立 partial milestone。

## 当前分支 / HEAD

- 固定开发分支：`dev/zn-agent`
- canonical source/release branch：`main`
- 本 HANDOFF 写入前开发 HEAD：`f437ab85be63972005d8d7fb6a78f3f204d57dc4`
- canonical `main`：`8234a835dea604783cea0bd9d28a40de654ec03d`
- 本 HANDOFF 写入前 `dev/zn-agent` 相对 `main`：ahead 71、behind 0；本状态同步 commit 会再前进一次
- PR #6：draft/open，base `main`，head `dev/zn-agent`，未合并
- `main` 未修改；没有 force push/history rewrite

## 已完成事项

### 1. Bounded repo-owned verifier manifest — three real relations

```text
runtime/python/zn_agent/core/repo_test_semantics.py
→ tests/zn_agent/core/test_repo_test_semantics_authority.py

runtime/python/zn_agent/core/git_semantics.py
→ tests/zn_agent/core/test_git_staging_semantics.py

runtime/python/zn_agent/core/result_semantics.py
→ tests/zn_agent/core/test_verified_experience.py
```

manifest 只能声明 literal `target` + `test`，不能携带 command/shell/workdir/timeout，也不能把模型建议或 task prose 变成执行 authority。Run `32829830325` 验证三条 relation；后续 exact-head runs 持续保持 green。不为数量继续扩张。

### 2. Windows host-pressure test isolation

关键提交：

```text
40e1ae4f0d0043a9a2205f8b4299855f427de847  test: isolate life semantics from host disk pressure
a7d8e91985da62831d6ea95994d22d9b1d914a95  test: isolate endogenous attention from host disk pressure
d44e454fd3aa559c4c8e4445ba10224cd70e130a  test: isolate cognition rpc from host disk pressure
7fe0444a6633536a3678074776c006f41b4dd7b2  test: isolate visual attention from host disk pressure
```

生产 low-disk Body 语义保留；测试不再让与 Body health 无关的宿主资源状态污染 cognition assertions，并保留 `<10% free → constrained → body resources` 回归。

### 3. Resident visual runtime packaging repair

```text
58aee1ea4331264fcc0abcf73843b91ca6dc0879  fix: package resident visual capture dependency
```

正式 runtime 明确声明 `Pillow==12.3.0`，不再依赖宿主机器碰巧已有 Pillow。Exact run `32831968178` 证明 fresh isolated runtime 安装、zero-model boot 和完整 suite 成功。

### 4. Verified bounded pointer movement

```text
83f45fd922ebc216933987d269b3c797d3875f2b  feat: add verified pointer movement
```

实现边界：

- `NativeBody` 拥有 Windows primary-screen `pointer_move` / `pointer_state`；
- `pointer_move` 只接受 finite normalized `[0,1]` 坐标；
- structured `body_action` / `native_action` 是 authority；模型 prose、普通 task text、procedural memory 不产生坐标 authority；
- side-effect 成功后进入 durable `native_verification`，不会直接完成任务；
- fresh `pointer_state` 独立读取 cursor；
- drift/contradiction 进入 Investigation 并形成 negative evidence；
- active procedural inheritance 只同步 verification result passthrough，没有扩大 procedural authority。

Exact run `32844167956`：四个 Windows jobs success，**393 tests passed / 5 skipped**。三条 pointer tests 全绿。

### 5. Verified resident-owned local visual region sense

```text
f437ab85be63972005d8d7fb6a78f3f204d57dc4  feat: add resident visual region sense
```

新增 `NativeVisualRegionSense`，由 `ResidentSocketService` 与 persistent retina 一起拥有，但用途刻意不同：background retina 继续形成 lived visual structure；region sense 只提供明确请求时的 fresh、read-only、target-local evidence。

真实调用链：

```text
ResidentSocketService
→ NativeVisualRegionSense
→ probe(explicit bounded normalized region)
→ lazy Pillow ImageGrab
→ bounded primary-screen crop
→ grayscale + 16x16 quantized local derivative
→ compact SHA-256 signature + luminance + pixel bounds + capture metadata
→ all Pillow image objects closed
→ raw pixels discarded
→ VisualRegionObservation
```

边界：

- service 构造不会触发 screenshot；只有 `probe()` 才 lazy `ImageGrab`；
- center 必须是 finite normalized `[0,1]`；
- width/height fraction 限制为 `0.01..0.50`；
- raw-frame persistence 声明为 true 会被拒绝；
- probe 不写 visual SQLite state；
- probe 不创建 nervous trace；
- probe 不推进 background retina sample_count/hash/rhythm；
- probe 不调用任何模型；
- region sense 是 Sense，不是 Body action authority，不是另一个 agent；
- 它当前没有被开放成 generic RPC/desktop control surface。

Exact Windows x64 CI：

```text
run  32847172662
head f437ab85be63972005d8d7fb6a78f3f204d57dc4

ZN Kernel / Python / Windows        success
ZN Source Boundary / Windows        success
Electron / TypeScript / Windows     success
Publish Windows CI statuses         success
```

Kernel 真实证据：

```text
fresh isolated Python 3.12.13       success
znagent formal runtime install       success
29 runtime packages resolved         success
pillow==12.3.0                       installed
zero-model resident boot             success
resident core compile                success
full core unittest discovery         397 tests passed, 5 skipped
```

新增四条 visual-region tests 全绿：

```text
test_invalid_region_never_reaches_capture_authority
test_probe_is_bounded_fresh_read_only_local_evidence
test_probe_rejects_raw_pixel_persistence_claim
test_resident_service_owns_region_sense_without_writing_retina_or_memory
```

测试通过 injected region probe 验证语义/ownership，没有在 CI runner 上把真实 interactive-desktop screenshot 当成 E2E 证明。因此 real-session capture/desktop availability 仍是环境证据缺口。

## 当前真实调用链

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

### Persistent resident visual path

```text
ResidentSocketService
→ persistent NativeVisualSense
→ _visual_loop()
→ maybe_sample()
→ _capture_primary_screen()
→ Pillow ImageGrab local capture
→ compact frame hash / coarse 4x3 regions / luminance
→ raw image discarded
→ resident.perceive_visual(...)
→ nervous traces / Situation / Thought / Will attention
```

### Target-local visual path

```text
ResidentSocketService
→ NativeVisualRegionSense
→ explicit bounded probe
→ local derivative/signature
→ VisualRegionObservation
```

This path is synchronous and read-only relative to resident memory/lived retina state.

### Pointer movement path

```text
structured body_action/native_action
→ NativeActionIntent(kind="pointer_move")
→ durable native action cycle
→ NativeBody.act("pointer_move")
→ persist result
→ native_verification
→ NativeBody.act("pointer_state")
→ fresh current cursor position
→ match: verified completion
→ mismatch/unavailable: contradiction → Investigation
```

## 真实测试 / CI

Latest authoritative implementation-head evidence:

```text
run  32847172662
head f437ab85be63972005d8d7fb6a78f3f204d57dc4

ZN Kernel / Python / Windows        success
  fresh isolated runtime            success
  zero-model boot                   success
  compile                           success
  full core suite                   397 passed, 5 skipped
  visual-region bounded probe       success
  invalid-region fail-closed        success
  raw-pixel persistence rejection   success
  service ownership/no-memory-write success

ZN Source Boundary / Windows        success
Electron / TypeScript / Windows     success
Publish Windows CI statuses         success
```

Previous docs-head `93eae04fc436c0df15de3173629927bab238c78e` also had all four Windows jobs green in run `32846248288`.

当前环境没有私有仓库本地 checkout；没有把未执行的本地 suite 伪装成验证。以上结论来自真实 GitHub Actions。

## Diff / ownership 对账

- `main` 仍是 `8234a835dea604783cea0bd9d28a40de654ec03d`，未修改。
- `dev/zn-agent` 在本 HANDOFF 写入前相对 `main` ahead 71 / behind 0。
- PR #6 draft/open、未合并。
- region-sense commit 仅新增 `visual_region_sense.py`、新增对应测试、并在 `resident_server.py` 接入 ownership；没有新增 external control plane。
- `resident_server.py` 没有移除 service lifecycle 逻辑；diff 中 deletion 仅是注释文字/空格调整。
- region probe 不是 `body_action`，不创造新的 mutation authority。
- 当前没有继续扩 verifier manifest。

## 风险 / 边界

- 不修改 `main`，除非用户明确要求且重新核验 promotion 条件。
- 禁止 force push / history rewrite。
- manifest 不是 command catalog；不得加入 shell/model/task-prose authority。
- computer interaction 必须是 ZN-owned typed Body action；模型文字不能直接获得鼠标/键盘执行权。
- `pointer_move` 的 cursor-position postcondition足以验证“指针到了哪里”，但不足以验证应用/UI 语义。
- local visual signature change 最多证明“目标局部视觉结构发生变化”；它本身仍不等于“点击完成了业务目标”。
- 未来 click 必须在 side effect 前持久化 fresh baseline/intent evidence，并在 side effect 后重新观察；不能用 input API success 直接完成。
- click 发生后如果 resident 中断，必须有 anti-replay 策略；不能在不知道 click 是否已发生时盲目重放。
- 真实 Windows screen capture / interactive desktop 可能受 session/desktop/permission 状态影响；CI 当前不宣称 real-screen E2E。
- Windows runner 曾有真实低磁盘状态；不通过削弱 Body sensing 隐藏现实。
- Actions 仍有 Node 20 action runtime deprecation warning；仅通过稳定、验证过的 action upgrade 处理。
- M8 updater/rollback/signing 仍是高风险 release boundary。

## Task Queue

### P0 — exact-head Windows CI
Status: **GREEN THROUGH `f437ab85...` / RUN `32847172662`**

本 HANDOFF/status 同步会产生新的 docs HEAD；允许其自动 CI 跑完，但不要为了记录那个 run ID 再产生无限 docs commit。

### P1 — bounded verifier manifest
Status: **VERIFIED NARROW SLICE / THREE REAL RELATIONS**

不为数量继续扩张。

### P2 — resident visual foundation
Status: **VERIFIED PACKAGING + BACKGROUND RETINA + TARGET-LOCAL READ-ONLY PROBE**

formal runtime owns Pillow；real-session capture permission/E2E 仍未验证。

### P3 — bounded computer interaction Body
Status: **VERIFIED FIRST SLICE / POINTER MOVE**

`pointer_move` + fresh `pointer_state` verification 已通过 exact-head Windows CI。Click/keyboard/browser mutation 未实现。

### P4 — click/browser current-world verification
Status: **ACTIVE / INVESTIGATION**

已有 local pre/post visual evidence primitive，但尚未实现 click。下一步必须追完整 entry → owner → state → lifecycle → dependency → tests → active caller，并定义：

```text
explicit structured click authority
→ fresh local visual baseline
→ durable execution-start marker / anti-replay
→ bounded click
→ fresh local visual re-observation
→ narrow effect evidence
→ stronger semantic evidence where required
→ only then completion
```

若当前 evidence 只能证明 local change，就只能宣称 local effect，不可宣称更高层 task success。

### P5 — M8 Windows continuity / rollback / signing
Status: **PENDING / PARTIAL**

### P6 — SM1+ self-maintenance
Status: **PENDING**

## 下一真实目标

1. 确认本 STATUS/HANDOFF 同步 commit 的 automatic Windows x64 CI；
2. 只读追 click 的真实 active runtime inheritance/call chain；
3. 定义 click 的 pre-action baseline、execution anti-replay 和 post-action fresh observation contract；
4. 仅在 typed authority + verifiable postcondition 都成立时增加最小 click Body primitive；
5. local visual change 不足时先加强 semantic/current-world evidence，而不是扩大 action authority；
6. 保持 M8 partial；不触碰 `main`。
