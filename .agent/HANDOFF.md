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

当前 engineering lane 已完成 shared structured Git diff reality source：`NativeBody.git_diff` 同时服务 resident Investigation 和 Workbench diff artifact presentation。Workbench 不再自己运行第二套 `git diff` shell command，也不再自己解析 porcelain status path。

下一真实目标是基于同一 current-reality source 定义 baseline-aware bounded mutation → diff/test/current-reality verifier。不要增加 generic planner、raw command replay 或“一看到工程任务就跑额外步骤”的 broad lexical overfit。

## 当前分支 / HEAD / CI

- 固定开发分支：`dev/zn-agent`
- 本阶段开始时 exact dev HEAD：`1012ca2cb67439b84a9355591cf46c2e28fbadc1`
- 最终 code/test SHA：`a5b628bb72b2b683882ed7f35afbe0112320782e`
- 权威 code/test CI：run `32658783466`
  - `ZN Kernel / Python = success`
  - `Electron / TypeScript = success`
  - isolated `runtime/python` install = success
  - zero-model isolated runtime boot = success
  - kernel compile = success
  - full kernel unittest discovery = success
  - Electron locked install/typecheck/bundle/ownership/runtime/update/handoff/release verifiers = success
  - `Container / Runtime Smoke = skipped`（normal push contract）
  - `Publish commit statuses = success`
- Python job：`97241688503`
- Electron job：`97241688384`
- implementation-status sync：`93a5f6a2af508446fbadac1102a01fc7e2337472` (`[skip ci]`)
- 本 HANDOFF 也是 docs-only `[skip ci]`；提交后必须重新读取 `dev/zn-agent` exact HEAD。
- `main` 必须保持 `61dd880aa4bbbdb359ca544b752afc2c22845ce9`；M10 未满足，禁止修改。

## 本阶段恢复的真实现场

开始工作前已重新读取/检查：

1. `ZN.md`
2. `AGENTS.md`
3. `docs/ZN-IMPLEMENTATION-STATUS.md`
4. `docs/ZN-SOURCE-EXTRACTION.md`
5. `docs/ZN-SELF-MAINTENANCE.md`
6. `.agent/HANDOFF.md`
7. exact `dev/zn-agent` HEAD
8. main relation / open PR / recent commits / prior CI
9. `ResidentWorkLedger → Body → artifact → RPC → Workbench renderer` 的真实 diff 调用链

恢复时事实：

- dev HEAD = `1012ca2cb67439b84a9355591cf46c2e28fbadc1`
- previous authoritative code/test = `c29cae2c9c10e94ec7dc75bccd16df40b7db7a17`
- previous run = `32657175399`, Python/Electron 双绿
- main = `61dd880aa4bbbdb359ca544b752afc2c22845ce9`
- dev ahead main = 594，behind = 0
- open PR = 0
- M8 real AppImage N→N+1 run `32645354818` installed updater smoke 仍 cancelled；不得报 verified

## 本阶段真实调用链与问题

真实 Workbench diff path 原来是：

```text
ResidentWorkLedger._finalize_run
→ _collect_artifacts
→ _collect_workspace_git_context
→ Body git_state
→ local porcelain status parsing for changed files
→ Body command("git diff ...")
→ Body command("git diff --cached ...")
→ WorkArtifact(kind=diff)
→ work_get RPC
→ Workbench renderer displays artifact.content
```

Renderer 本身没有 Git semantics。重复语义实际在 `ResidentWorkLedger`：

- 已有 `git_state.changed_paths`，但 WorkLedger 仍解析 `git_state.changes` porcelain lines；
- 已有 structured `git_diff` sense，但 WorkLedger 仍运行两条 presentation-only generic shell commands。

这会形成 resident reality 与 UI presentation 两套 Git diff truth source。

## 本阶段实现

### 1. WorkLedger 复用 structured Git state/diff

文件：`agent/kernel/work.py`

当前实现：

```text
body.git_state(workspace)
→ consume git_state.changed_paths for changed-file artifacts
→ body.git_diff(workspace)
→ consume structured worktree/staged patches
→ persist same WorkArtifact(kind=diff)
```

删除：

- local `_path_from_porcelain(...)` parser；
- `git diff --no-ext-diff --no-color -- .` presentation command；
- `git diff --cached --no-ext-diff --no-color -- .` presentation command。

Diff artifact 保留既有 UI/RPC contract：

- `kind = diff`
- `name = Current workspace diff`
- `scope = current_workspace_after_event`
- bounded textual preview / truncation

同时新增 provenance：

- `source = git_diff`
- `source_action_id`
- `state_sha256`
- `head`

这只是 presentation truth-source 去重，不扩大任何 mutation authority，也没有新增 Runtime subclass。

### 2. Regression

文件：`tests/agent/kernel/test_work_ledger.py`

真实 temp Git repo 同时制造：

```text
HEAD:       notes.txt = before
index:      notes.txt = staged
worktree:   notes.txt = after
```

测试证明：

- file artifact 仍显示 current `after`；
- diff artifact 同时包含 staged 和 worktree patch；
- artifact 的 `state_sha256` 与 source `git_diff` Body action 完全一致；
- source action kind 是 `git_diff`；
- event action history 中不存在旧两条 presentation generic command；
- RPC / persistent artifact 行为保持。

## Diff hygiene

首个原子 code+test commit：

```text
2fdd471d6b819160a7fdd8af31881af8a8600d8a  refactor: reuse structured git diff in work artifacts
```

commit review 发现手工 blob 组装带入一处无关 `EventStatus` formatting drift；随后 cleanup：

```text
584cb810597e1197cbd36f9ed7ea4fb702ef2d08  chore: keep work ledger diff focused
```

第二次 review 又发现 `WorkArtifact` constructor 的 `path/content` 顺序被无关调换；再次恢复：

```text
a5b628bb72b2b683882ed7f35afbe0112320782e  chore: restore work artifact field order
```

最终 cumulative diff 相对阶段起点只包含两个目标文件：

```text
agent/kernel/work.py                         23 additions / 31 deletions
tests/agent/kernel/test_work_ledger.py      38 additions / 0 deletions
```

两个 cleanup push 造成前一候选 workflow concurrency cancellation；例如 `584cb810...` 对应 run `32658723920` 的 Python/Electron job 在后续 push 后被 cancelled。cancel 前 runtime install、zero-model boot、compile 等已成功。这不是最终代码 failure；最终权威 SHA/run 为 `a5b628bb...` / `32658783466`，完整双绿。

## 本阶段文档

已更新：

```text
docs/ZN-IMPLEMENTATION-STATUS.md
.agent/HANDOFF.md
```

没有修改：

- `ZN.md`：架构方向没有改变；
- `docs/ZN-SOURCE-EXTRACTION.md`：无 Hermes extraction state 变化；
- `docs/ZN-SELF-MAINTENANCE.md`：无 self-maintenance architecture 变化；
- `main`。

## 当前仍未完成 / 不得误报

- baseline-aware pre-mutation / post-mutation diff verifier；
- bounded mutation → diff → targeted test → current-reality verification loop；
- 区分 pre-existing unrelated dirty changes 与本次 mutation 引入变化的通用 contract；
- diff truncation / rename / binary / untracked-content 等 verifier semantics；
- broader resident-owned tactic formation beyond exact-text + single-path Git staging；
- arbitrary command equivalence / arbitrary side-effect tactic synthesis（继续禁止）；
- general reliable high-level postcondition derivation；
- multi-step long-horizon execution without model-owned planner；
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

1. `git_diff.state_sha256` 是 observed diff-state fingerprint，不是整个 workspace 内容 hash；untracked content 不在 hash 中，不能误作完整 workspace baseline；
2. Workbench 现在只是共享事实消费者，不能变成 verifier 或 control plane；
3. 下一步如果只按“diff 变了”判成功，会把用户原有 dirty changes 和本次 mutation 混在一起；必须先建立 baseline identity/scope；
4. broad lexical engineering triggers 会过拟合；优先 typed current-event contracts + current facts；
5. generic command positive procedural authority继续禁止。

M8 debt 未变化：run `32645354818` real installed AppImage updater continuity smoke cancelled；N/N+1 build success 不等于 updater continuity verified。

## 下一真实目标

Fresh restore 后：

1. 重新读取必读文档和 exact dev HEAD/CI/diff/PR；
2. 追 `write_text` / `git_diff` / postcondition / command-test verification 的真实 active chain；
3. 定义一个 bounded baseline contract：repo root + HEAD + scoped changed paths + diff fingerprint/patch identity，明确 pre-existing dirty state；
4. 定义 mutation 后的 scoped delta proof，不能把 unrelated dirty changes算成本次成功；
5. 在现有低风险、明确 authority 的 mutation 上接一个 targeted test/current-reality verifier，不扩大 arbitrary shell authority；
6. negative cases 至少覆盖 stale/missing baseline、unrelated dirty changes、cross-target、truncation、identity ambiguity、contradiction；
7. 只有 independent verifier 完整成立后才允许 positive `VerifiedExperience` / learning；
8. M8 updater continuity 保持独立 release debt。

判断标准：

> **少加一个专用抽象，多让同一个 ZN Self 用共享现实证据完成一个真正可验证的工作闭环。**
