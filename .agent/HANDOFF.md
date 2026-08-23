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

当前 engineering lane 已完成第一条 baseline-aware bounded mutation proof：对现有、已授权、幂等的 tracked exact text replacement，在写入前持久化并重验 target-scoped Git baseline，写入后必须由 fresh exact text + target-scoped Git delta 共同证明才允许完成和 positive learning。

这不是通用 mutation engine。append、untracked/staged/conflicted target、rename/binary、generic command 和 arbitrary shell equivalence 都没有被纳入；targeted test 自动选择/执行也尚未接入。

## 当前分支 / HEAD / CI

- 固定开发分支：`dev/zn-agent`
- 本阶段开始时 exact dev HEAD：`e02ad64eb7e9f4665d0ef3673143b2798c2095c2`
- 最终 code/test SHA：`e78432be526fe628791a6350a97b0a9d16bd8623`
- 权威 code/test CI：run `32660483679`
  - `ZN Kernel / Python = success`
  - `Electron / TypeScript = success`
  - isolated `runtime/python` install = success
  - zero-model isolated runtime boot = success
  - kernel compile = success
  - full kernel unittest discovery = success
  - Electron locked install/typecheck/bundle/ownership/runtime/update/handoff/release verifiers = success
  - `Container / Runtime Smoke = skipped`（normal push contract）
  - `Publish commit statuses = success`
- Python job：`97245785652`
- Electron job：`97245785745`
- implementation-status sync：`bfb9fce33f1e88d0d758f2d88e3ad5932deabf50` (`[skip ci]`)
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
9. `Investigation → action formation → procedural influence/recovery → native_action → independent verification → VerifiedExperience` 的真实调用链

恢复时事实：

- dev HEAD = `e02ad64eb7e9f4665d0ef3673143b2798c2095c2`
- previous authoritative code/test = `a5b628bb72b2b683882ed7f35afbe0112320782e`
- previous run = `32658783466`, Python/Electron 双绿
- main = `61dd880aa4bbbdb359ca544b752afc2c22845ce9`
- dev ahead main = 599，behind = 0
- open PR = 0
- M8 installed AppImage N→N+1 continuity remained unverified from run `32645354818` unless newer real workflow evidence proves otherwise

## 本阶段真实设计收敛

最初目标是 baseline-aware mutation → diff/test/current-reality verifier。实际调用链审查后收窄为第一条可以可靠证明的 mutation：tracked exact replacement。

没有选择 append 作为第一条，因为 append 是非幂等 movement；若文本已经写入而 repo-delta verification 暂时失败，重试会有重复追加风险。exact replacement 已有明确写入 authority、幂等性和 `text_equals` verifier，更适合作为第一条 current-reality engineering mutation proof。

也没有用 whole-repo `git_diff.state_sha256` 直接当 baseline，因为 unrelated dirty files 会污染因果边界。先给现有 read-only `git_diff` 增加一个安全的 literal repository-relative target scope，再用它建立 pre/post evidence。

## 本阶段实现

### 1. Target-scoped structured `git_diff`

文件：`agent/kernel/body.py`

commit：

```text
e2717b5cc56c9bcfc090b887c6396f2485af6a3d  feat: scope structured git diff evidence
```

新增可选 `relative_path` scope：

- 只接受 repository-relative literal path；
- absolute path / `..` escape / empty/root scope fail closed；
- Git patch 使用固定 argv + `:(literal)<path>`；
- patch 禁用 external diff 与 textconv；
- worktree/staged/name-only/untracked evidence 同一 scope；
- scoped result 增加 `scope_relative_path` / `scope_tracked`；
- scoped state fingerprint 包含 scope identity；
- 仍是 read-only Body sense，不接受 caller shell command。

### 2. Tracked exact-replace baseline / delta verifier

文件：`agent/kernel/procedural_resident.py`

commit：

```text
735a39ece7a41a298f7f069c54ccd3c8df1efc01  feat: verify tracked text replacements against repo delta
```

没有新增 Runtime subclass。

仅当 current intent 同时满足以下条件时进入 stronger repo proof：

```text
write_text
+ append == false
+ source in {native_deliberation, resident_choice}
+ current verification == text_equals / replace
+ current Investigation has Git root + HEAD
+ target is current compatible regular file
+ physical/lexical identity unambiguous and inside repo
+ target not staged
+ target not untracked
+ target not conflicted
```

写入前：

```text
target-scoped git_diff
→ prove same root / HEAD / literal target / tracked / not truncated
→ persist only bounded fingerprints + identity in current WorkingState
→ if native_action resumes after restart, fresh scoped observation must match baseline
→ mismatch blocks before mutation and returns to Investigation
```

写入后：

```text
fresh read_text == exact expected text
+ fresh target-scoped git_diff
+ same root / same HEAD / same scope / still tracked
+ no truncation
+ staged patch unchanged
+ worktree patch fingerprint changed
+ scoped state fingerprint changed
+ target did not become untracked
→ complete + positive VerifiedExperience
```

HEAD drift after mutation is contradiction even if text happens to match. Unrelated dirty files are excluded by target scope.

### 3. Tests

文件：`tests/agent/kernel/test_repo_text_delta_verification.py`

commits：

```text
fb05074cf4299fab05a523fb02242c1c68698e22  test: cover baseline aware repo text verification
974a81bcc71b26ef426896aeb1666738be55e272  test: locate post action verification read
e78432be526fe628791a6350a97b0a9d16bd8623  test: assert durable repo delta evidence
```

覆盖：

- scoped Git diff 排除 unrelated dirty path；
- scope traversal / absolute path fail closed；
- target 已有 pre-existing dirty change + unrelated dirty change 时，exact replace 仍只证明 target delta；
- baseline → write → fresh read → post scoped diff 的真实 Body action 顺序；
- staged fingerprint 不变、worktree/scoped-state fingerprint 改变；
- HEAD 在 write 后、verification 前变化 → contradiction；
- target baseline patch 截断 → 写入前 block，无 write movement；
- untracked target 不冒充 tracked repo-delta verifier，继续使用既有 text verification；
- positive/negative `VerifiedExperience` 保持 privacy-safe，不持久化 raw path/content/patch。

## 本阶段真实 CI failure / 修复

### 中间 concurrency cancellation

SHA `735a39ece7a41a298f7f069c54ccd3c8df1efc01`，run `32660190937`：

- 后续 test push 触发 workflow concurrency cancellation；
- cancel 前 isolated runtime install、zero-model boot、compile 已成功；
- kernel tests / Electron typecheck 被取消；
- 不是实现 failure，也不能报 green。

### 真实 Python failure

SHA：`fb05074cf4299fab05a523fb02242c1c68698e22`

run：`32660232657`

结果：

- Electron = success；
- Python = failure；
- full kernel suite 共 361 tests；
- 只有新增测试 1 fail + 1 error；
- 新实现 negatives（HEAD drift contradiction、scoped path isolation/escape、truncated baseline precondition）在同一 run 已通过。

根因不是 verifier 语义，而是测试在 event terminal completion 后读取 transient current `WorkingState` slots。终态 lifecycle 已经换出/重置当前工作槽，因此该取证面不可靠。

修复：

- 不改实现合同；
- 不削弱 negative assertions；
- tracked success 改为断言 durable Body action history、final `ResidentRunResult.reason`、scoped fingerprints 和 `VerifiedExperience`；
- untracked fallback 改为证明没有 target-scoped `git_diff`、final result 不声明 repo delta，并保留 verified experience。

最终 `e78432be...` / run `32660483679` 完整双绿。

## 当前仍未完成 / 不得误报

- 自动 targeted-test 选择/执行尚未接到 mutation verification；
- 因此完整 `mutation → diff → targeted test → current-reality` engineering loop 仍是 partial；
- append 的 baseline/retry semantics 尚未定义；
- untracked/staged/conflicted target 的 stronger repo-delta proof 尚未定义；
- rename/binary 等 diff semantics 尚未定义；
- broader resident-owned tactic formation beyond exact-text + single-path Git staging；
- arbitrary command equivalence / arbitrary side-effect tactic synthesis 继续禁止；
- Git commit/push/reset/checkout/branch mutation authority；
- GitHub repo/PR/CI resident-owned sense；
- mature resident-owned engineering competence / general procedural fast path；
- browser Body/Senses + learned computer-use competence；
- growth benchmarks；
- installed AppImage N→N+1 updater continuity，除非新的 real workflow 已证明；
- Windows/macOS intended clean-install/login continuity；
- signing/notarization；
- SM1+ self-maintenance。

## 风险 / 阻塞

Core lane 当前无已知 CI blocker。

主要风险：

1. 不要把这一条 tracked exact-replace verifier 提前抽象成 generic mutation engine；等第二个真实 mutation family 出现后再提炼重复合同；
2. target-scoped `state_sha256` 是 observed diff-state fingerprint，不是完整文件/workspace content hash；
3. append 非幂等，不能直接复用 exact-replace restart/retry 语义；
4. targeted test 只能在 test/effect semantics 可独立证明时接入，不能从 free text 推断 arbitrary shell command；
5. generic command positive procedural authority继续禁止；
6. model output、patch appearance、Body success 都不能替代 current verification。

M8 release debt 与 core lane 分开处理。旧 run `32645354818` 的 installed AppImage updater continuity smoke cancelled；除非更新的 real AppImage run 给出终态成功，否则不得报 verified。

## 下一真实目标

Fresh restore 后：

1. 重新读取必读文档和 exact dev HEAD/CI/diff/PR；
2. 保持当前 tracked exact-replace baseline/delta contract 不扩 scope；
3. 调查仓库内现有测试/构建 verification contract，寻找一个“test command 本身有明确来源和 bounded semantics”的 current-world consumer；
4. 只在 test identity、workdir、target/effect scope 都能由当前代码/配置/typed contract 独立证明时，把 targeted test 接到这条 mutation 后；
5. test failure 必须阻止 completion/positive learning，并返回 Investigation；
6. stale/missing test evidence、wrong workdir、cross-target、masked success、timeout/contradiction 先补 negatives；
7. 不从 task text 或 procedural memory重放 raw test/shell command；
8. 不为了复用提前做 arbitrary command equivalence engine；
9. M8 updater continuity 保持独立 release lane。

判断标准：

> **少加一个专用抽象，多让同一个 ZN Self 用共享现实证据完成一个真正可验证的工作闭环。**