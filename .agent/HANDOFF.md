# ZN Agent Handoff

更新时间：2026-08-23

## 当前目标

```text
durable ZN Self
+ mature Agent-level complex-task execution depth
+ reality-based verification
+ resident-owned learning / procedural competence
```

核心原则：

> **ZN uses models. Models do not own ZN.**

当前阶段已完成一个可复用、只读的 structured Git diff sense，并把它接入当前 Investigation。它是 broader engineering competence 的现实感觉基础，不是新的 mutation skill，也没有扩大 generic command authority。

下一真实方向是：先消除 Workbench 现有 diff presentation 与 resident structured diff sense 的双轨语义，然后基于共享 current-reality diff 建立一个 baseline-aware bounded mutation → diff/test/current-reality verification loop。不能为了演示再堆专用 if / planner / raw command replay。

## 当前分支 / HEAD / CI

- 固定开发分支：`dev/zn-agent`
- 本阶段开始时 dev HEAD：`1189ae3554c9066a5f8d5bb8520abe22f46ae434`
- 最终 code/test SHA：`c29cae2c9c10e94ec7dc75bccd16df40b7db7a17`
- 权威 code/test CI：run `32657175399`
  - `ZN Kernel / Python = success`
  - `Electron / TypeScript = success`
  - isolated `runtime/python` install = success
  - zero-model isolated runtime boot = success
  - kernel compile = success
  - full kernel unittest discovery = success
  - Electron locked install/typecheck/bundle/ownership/runtime/update/handoff/release verifiers = success
  - `Container / Runtime Smoke = skipped`（normal push contract）
  - `Publish commit statuses = success`
- Python job：`97237648830`
- Electron job：`97237648940`
- implementation-status sync：`c7611950a5936648d7bd897a8c81aadae5247283` (`[skip ci]`)
- 本 HANDOFF 也是 docs-only `[skip ci]`；提交后必须重新读取 `dev/zn-agent` exact HEAD。
- `main` 必须保持 inherited baseline `61dd880aa4bbbdb359ca544b752afc2c22845ce9`；M10 未满足。

## 本阶段开始前恢复的真实现场

已按接手规则重新读取/检查：

1. `ZN.md`
2. `AGENTS.md`
3. `docs/ZN-IMPLEMENTATION-STATUS.md`
4. `docs/ZN-SOURCE-EXTRACTION.md`
5. `docs/ZN-SELF-MAINTENANCE.md`
6. `.agent/HANDOFF.md`
7. `dev/zn-agent` exact HEAD
8. main relation / open PR / recent commits / CI
9. Body → Investigation → action/postcondition → work artifact 的真实调用链

恢复时事实：

- dev HEAD = `1189ae3554c9066a5f8d5bb8520abe22f46ae434`
- previous authoritative code/test SHA = `22e1abde5cd5e1bc228d19a7d09eff6d2f9c8cc8`
- previous run = `32654830857`, Python/Electron 双绿
- main = `61dd880aa4bbbdb359ca544b752afc2c22845ce9`
- dev ahead main = 588，behind = 0
- open PR = 0
- M8 real AppImage N→N+1 run `32645354818` installed updater smoke 仍 cancelled；不得报 verified

## 本阶段真实调用链发现

已有 `ResidentWorkLedger` 在 work 完成后会用 generic Body `command` 运行：

```text
git diff --no-ext-diff --no-color -- .
git diff --cached --no-ext-diff --no-color -- .
```

产生 UI diff artifact。

但此前 resident Investigation 只有 structured `git_state`，没有 structured diff current facts。因此：

```text
Workbench 能展示 diff
≠ resident 能把 diff 当作自己的 current reality
```

为避免过拟合，本阶段没有直接新增第三套专用 engineering skill / `repo_text_change` family，而是先建立所有未来 mutation verification / self-maintenance / workbench 都能复用的 read-only diff sense。

## 本阶段实现

### 1. NativeBody structured `git_diff` sense

文件：`agent/kernel/body.py`

commit：

```text
f7d730908e7fafcf7d58c00386a1f7dfd57559f3  feat: add structured git diff body sense
```

`NativeBody` 新增 exact `git_diff` action kind。它不是 caller-provided shell command；内部只运行固定 Git argv：

```text
git -C <workspace> rev-parse --show-toplevel
git -C <workspace> diff --no-ext-diff --no-color -- .
git -C <workspace> diff --cached --no-ext-diff --no-color -- .
git -C <workspace> diff --name-only -z ...
git -C <workspace> diff --cached --name-only -z ...
git -C <workspace> ls-files --others --exclude-standard -z
git -C <workspace> rev-parse --verify HEAD
```

返回 bounded structured evidence：

- root / HEAD identity；
- dirty / changed paths；
- worktree paths + bounded patch + patch hash；
- staged paths + bounded patch + patch hash；
- untracked paths；
- bounded observed diff-state fingerprint；
- truncation metadata。

边界：

- read-only；
- 不扩大 mutation authority；
- 不允许 caller 注入 arbitrary Git argv；
- untracked file content 不会自动进入 patch，只记录 path；
- 当前还未把它定义成 postcondition verifier。

### 2. Investigation 消费 structured diff

文件：`agent/kernel/embodied_investigation.py`

commits：

```text
f772da038c7fe3ed5d22f3aa6f41482745b52e9e  feat: let investigation observe structured git diffs
c29cae2c9c10e94ec7dc75bccd16df40b7db7a17  fix: keep git diff probing narrowly evidence driven
```

新增 `git_diff` observation probe，但没有新增 Runtime subclass。

当前 gate：

```text
current git probe already performed
+ current structured git reality says dirty
+ git_diff not already performed
+ current event explicitly carries diff/mutation semantics
→ observe git_diff
```

显式语义来自：

- task 的明确 diff/patch/change/modify/edit/write/create/replace/append/fix 等词；或
- structured `content` / `text` / `expected_outcome` payload。

Generic `debug` / `test` / `build` / `code` 不再单独触发 diff sensing。

`git_diff` probe 只写 Investigation current facts/evidence；不选择、不形成、不执行 mutation。

### 3. Tests

文件：`tests/agent/kernel/test_native_body.py`

commit：

```text
bbffd538d0e3499b35eedd46c03686050285c9af  test: cover structured git diff sensing
```

真实 temp Git repo coverage：

1. structured Body diff：
   - unstaged tracked edit；
   - staged new file；
   - untracked file；
   - root/HEAD/path sets/patches/hash/truncation；
   - untracked content 不被隐式读入；
   - Body event 只有 `git_diff`，没有 generic `command`。

2. zero-model active Investigation integration：
   - current dirty repo；
   - explicit diff task；
   - 先 `git_state` 后 `git_diff`；
   - Investigation durable facts 有 structured diff；
   - event 内没有 generic `command`；
   - 不因“看到了 diff”伪造 task completion。

## 本阶段真实 CI failure / 修复

### 中间 concurrency cancellation（不是代码 failure）

SHA `f772da038c7fe3ed5d22f3aa6f41482745b52e9e`，run `32656887879`：

- 后续 push 触发 workflow concurrency cancel；
- cancel 前 runtime install / zero-model boot / compile 已成功；
- kernel tests 和 Electron typecheck 在运行中被取消；
- 不能报 green，也不属于实现失败。

### 真实 Python failure

SHA：

```text
bbffd538d0e3499b35eedd46c03686050285c9af
```

run：

```text
32656924494
```

结果：

- Electron = success；
- Python = failure；
- 唯一失败：`test_one_live_cycle_advances_only_one_investigation_round`。

根因：初版 `_git_diff_relevant()` 把 broad `debug/test/build/code` 也当作应该观察 diff。CI checkout 的 ambient repo reality 是 dirty，因此原本 generic project investigation 被多加一轮 `git_diff`，破坏既有 multi-pulse probe invariant。

修复原则：

- 没改旧测试；
- 没降低旧 invariant；
- 没把额外 probe 合理化；
- 收窄新能力的 current-evidence trigger。

`c29cae2...` 删除 broad trigger 后，最终完整 CI 双绿。

这次 failure 是当前“避免过拟合”原则的真实工程证据：新 sense 必须只在当前语义需要时出现，不能因为“看起来是工程任务”就在所有工程问题上强行插入。

## 本阶段文档

已更新：

```text
docs/ZN-IMPLEMENTATION-STATUS.md
.agent/HANDOFF.md
```

没有修改：

- `ZN.md`：产品/架构方向没有变化；本阶段实现的是已批准的 Body/Senses + reality verification 方向；
- `docs/ZN-SOURCE-EXTRACTION.md`：无 Hermes extraction state 变化；
- `docs/ZN-SELF-MAINTENANCE.md`：无 self-maintenance architecture 变化；
- `main`。

## 本阶段关键 commits

```text
f7d730908e7fafcf7d58c00386a1f7dfd57559f3  feat: add structured git diff body sense
f772da038c7fe3ed5d22f3aa6f41482745b52e9e  feat: let investigation observe structured git diffs
bbffd538d0e3499b35eedd46c03686050285c9af  test: cover structured git diff sensing
c29cae2c9c10e94ec7dc75bccd16df40b7db7a17  fix: keep git diff probing narrowly evidence driven
c7611950a5936648d7bd897a8c81aadae5247283  docs: record structured git diff sensing [skip ci]
```

## 当前仍未完成 / 不得误报

- Workbench diff artifact 仍使用既有 generic Body `command` presentation path，尚未迁到 shared `git_diff` sense；
- baseline-aware pre/post diff verifier 尚未实现；
- bounded mutation → diff → test → current-reality verification loop 尚未完成；
- broader resident-owned tactic formation beyond exact-text + single-path Git staging；
- arbitrary command equivalence / arbitrary side-effect tactic synthesis 仍应禁止；
- general reliable high-level postcondition derivation；
- multi-step long-horizon execution with genuinely different tactics without a model-owned planner；
- Git commit/push/reset/checkout/branch mutation authority；
- GitHub repo/PR/CI resident-owned sense；
- mature resident-owned engineering competence / general procedural fast path；
- browser Body/Senses + learned computer-use competence；
- growth benchmarks；
- autonomous outbound artifact nomination；
- Telegram photo/audio/video-specific transports；
- installed AppImage N→N+1 updater continuity；
- Windows/macOS intended clean-install/login continuity；
- signing/notarization；
- SM1+ self-maintenance。

## 风险 / 阻塞

Core lane 当前没有已知 CI blocker。

主要风险：

1. broad lexical trigger 会把一个有用 sense 变成对“工程任务”过拟合的额外流程；当前 narrow trigger 必须保持，未来优先用 typed/current facts 替代继续扩词表；
2. `git_diff` 当前是 read-only sense，不是 task verifier；不能因为 patch 看起来合理就叫任务完成；
3. 在把 diff 用作 verifier 前，需要定义 baseline identity、target scope、pre-existing unrelated changes、truncation、untracked-content、rename/binary/textconv 等明确语义；
4. 当前 `state_sha256` 是 observed diff-state fingerprint，untracked file content 不参与，只包含 untracked path；不能把它误解成完整 workspace content hash；
5. Workbench 仍有旧 diff presentation command 路径，下一步应合并事实源而不是长期保留两套 diff semantics；
6. generic command positive procedural authority继续禁止。

M8 debt 未变化：run `32645354818` real installed AppImage updater continuity smoke cancelled；N/N+1 build success 不等于 updater continuity verified。

## 下一真实目标

Fresh restore 后：

1. 重新读取必读文档和真实 dev HEAD/CI/diff/PR；
2. 先检查 `ResidentWorkLedger` diff artifact consumer，尽量迁移到 `NativeBody.git_diff`，让 resident cognition 和 UI presentation 共用一个 Git diff reality source；
3. 迁移时保持现有 artifact 行为和 bounded presentation，不让 renderer/work ledger 成为第二套 Git semantics；
4. 在 shared sense 稳定后设计 baseline-aware bounded engineering mutation verifier：必须区分 mutation 前已有变化与本次动作引入的变化；
5. 再把一个已有低风险、明确 authority 的 mutation 接到 diff/test/current-reality loop，而不是增加 arbitrary shell planner；
6. authority 扩大前先补 stale/missing baseline、unrelated dirty changes、cross-target、truncation、identity ambiguity、unsafe side effect、contradiction negatives；
7. generic command positive authority继续禁止，除非新的 semantic family 自己证明 current authority + independent verifier；
8. M8 updater continuity 保持独立 release debt。

判断标准：

> **少加一个专用抽象，多让同一个 ZN Self 用共享现实证据完成一个真正可验证的工作闭环。**
