# ZN Agent Handoff

更新时间：2026-08-23

## 当前目标

开发主线：

```text
durable ZN Self
+ mature Agent-level complex-task execution depth
+ reality-based verification
+ resident-owned learning / procedural competence
```

核心原则：

> **ZN uses models. Models do not own ZN.**

本阶段完成了第二个 genuinely different resident-owned semantic tactic family：**bounded single-path Git staging**。

ZN 现在可以在一个 typed `git_path_staged` 当前目标和当前 Investigation 的结构化 Git/path 证据共同成立时，自行形成两种不同 Git 机制：

```text
A = git add -- <current repo-relative path>
B = git update-index --add -- <current repo-relative path>
```

第一种 tactic 在当前现实下失败后，evidence-bound anti-replay 会继续阻止 A，resident 可以恢复到 B。最终成功不依赖 command return code；必须重新执行 fresh `git_state`，证明目标路径 staged 且不再 unstaged / untracked / conflicted。

这不是 general shell planner、general Git automation、learned raw-command replay，也没有扩大 Git/command 的 L3 positive authority。

## 当前分支 / HEAD / CI

- 固定开发分支：`dev/zn-agent`
- `main`：未修改；M10 未满足；baseline 仍为 `61dd880aa4bbbdb359ca544b752afc2c22845ce9`
- 本阶段恢复时 dev HEAD：`3bfd45f591e758d226b880c4d53a8b75e36f3800`
- 本阶段最终 code/test SHA：`7ec9725e9a2c9926adce36ec2d1ac8cfc9df926c`
- 权威 code/test CI：run `32650706582`
  - `ZN Kernel / Python = success`
  - locked repository deps = success
  - isolated `runtime/python` install = success
  - zero-model isolated runtime boot = success
  - `agent/kernel` compile = success
  - full kernel unittest discovery = success
  - `Electron / TypeScript = success`
  - dependency install / typecheck / bundle = success
  - desktop ownership / packaged runtime / update / handoff contracts = success
  - release-channel / runtime staging / packaged-artifact verifier tests = success
  - `Container / Runtime Smoke = skipped`（normal push workflow contract）
  - `Publish commit statuses = success`
- blueprint sync commit：`7d07af8eab9c1eb62b514acd54e4e074905e15f6` (`[skip ci]`)
- implementation-status sync commit：`ff76a80bbc1e610923b13e18a547e2cdbe4623fa` (`[skip ci]`)
- 本 HANDOFF commit 也是 docs-only `[skip ci]`；提交后必须重新读取 branch ref 作为当前 HEAD。

中间 run `32650543201`（SHA `109658346...`）被后续 push 的 workflow concurrency 取消。其 Python job 已完成 isolated runtime install、zero-model boot、compile，并在大量 kernel tests 连续通过后被取消；Electron 同样是 concurrency cancellation。它不是最终验证。最终 SHA `7ec9725e...` 的 run `32650706582` 已双绿。

## 本阶段恢复的真实现场

开始前重新读取并核对：

1. `ZN.md`
2. `AGENTS.md`
3. `docs/ZN-IMPLEMENTATION-STATUS.md`
4. `docs/ZN-SOURCE-EXTRACTION.md`
5. `docs/ZN-SELF-MAINTENANCE.md`
6. `.agent/HANDOFF.md`
7. `docs/ZN-MEMORY-LEARNING.md`
8. `docs/ZN-NEXT-PHASE.md`
9. `dev/zn-agent` HEAD / open PR / recent commits / CI / main relation
10. `Will → IntentionFormation → Investigation → Action → Body → verification → VerifiedExperience → L2/L3` 真实调用链

恢复时确认：

- dev HEAD = `3bfd45f591e758d226b880c4d53a8b75e36f3800`；
- open PR = 0；
- previous code/test SHA `04e95009...` 的 run `32648983622` Python/Electron 双绿；
- `main` 仍是 `61dd880aa4bbbdb359ca544b752afc2c22845ce9`；
- M8 AppImage run `32645354818` 的 installed updater continuity smoke 仍 cancelled，不得写成 verified。

## 本阶段真实调用链与实现

### 1. Typed Git goal and current-world authority

新增 `agent/kernel/git_semantics.py`。

当前唯一 mutation goal：

```text
expected_outcome.kind == git_path_staged
```

形成 mutation choice 前必须同时证明：

- current Investigation 有 available Git fact + repo root；
- current path fact 确认一个 existing regular file；
- target physically/lexically inside current Git root；
- symlink/path alias ambiguity rejected；
- target currently unstaged or untracked；
- target not conflicted；
- already-satisfied state does not form a mutation choice。

缺失 Git/path 事实、越界路径、directory、conflict、identity mismatch 都 fail closed。

### 2. Resident forms two genuinely different staging tactics

`agent/kernel/action.py`

显式 `body_action/native_action` 仍保持 exclusive，caller `native_action_options` contract 不变。只有在上述 Git semantics 成立时，resident 自己形成：

```text
source = resident_choice
kind   = command
A      = git add -- <current relative path>
B      = git update-index --add -- <current relative path>
```

每个 intent 携带 transient current-event `expected_outcome`：root/path/relative_path/action_variant。它不是 procedural memory。

### 3. Verification is fresh structured Git reality

`agent/kernel/procedural_resident.py`

verification 会重新检查：

- intent source 必须是 `resident_choice`；
- action kind 必须是 `command`；
- workdir 必须等于 current goal root；
- actual command 必须精确等于 resident-owned canonical rendering；
- persisted root/path/relative identity 必须重新解析后一致。

真正完成条件：

```text
Body command
→ fresh Body git_state(root)
→ target staged == true
→ target unstaged == false
→ target untracked == false
→ target conflicted == false
→ complete / positive learning
```

command success 本身不是 proof。

### 4. Recovery remains evidence-bound

failed-action signature 仍是 stable `{kind,args}`，不含随机 intent id。因此重新 deliberation 形成同一个 A 后，在同一 evidence fingerprint 下仍会被正确 block；B 因 command args 不同保持独立 admissible。

新增 recovery integration test 人为让 first `git add` Body result 失败但不改变真实 repo，随后真实 B=`git update-index --add` 执行，fresh `git_state` 验证成功。

### 5. Privacy-safe L1/L2 learning, no Git L3 authority yet

`agent/kernel/verified_experience.py`

Git staging learned expected summary 只保留：

```text
target_fingerprint
workdir_fingerprint
action_variant = git_add | git_update_index
```

verification summary 只保留 bounded staged/unstaged/untracked/conflicted booleans 和 fingerprint，不保存 raw path/command。

现有 L2 grouping/compatibility 包含 `action_variant`，所以两个 staging mechanisms 不会混合。

**本阶段没有扩大 L3 command/Git influence。** 当前 Git L1/L2 candidate 仍缺 Git-specific target/root reality applicability；现有 positive influence whitelist 也不接受 command。procedural memory 不能重放 learned command/path/args。

## 新增 / 修改文件

Code:

```text
agent/kernel/action.py
agent/kernel/git_semantics.py
agent/kernel/procedural_resident.py
agent/kernel/verified_experience.py
```

Tests:

```text
tests/agent/kernel/test_resident_git_stage_choice.py
tests/agent/kernel/test_resident_git_stage_recovery.py
tests/agent/kernel/test_git_staging_semantics.py
```

Docs:

```text
ZN.md
docs/ZN-IMPLEMENTATION-STATUS.md
.agent/HANDOFF.md
```

没有修改：

- `docs/ZN-SOURCE-EXTRACTION.md`：没有 Hermes extraction state 变化；
- `docs/ZN-SELF-MAINTENANCE.md`：没有 self-maintenance architecture 变化；
- `main`。

`ZN.md` 本阶段只同步已被真实代码证明滞后的 current-state / immediate-priority 文字：M8 remains bounded release debt；当前 core priority 是 resident competence。也同步了已存在的 outbound `sendDocument` seam。核心架构原则没有改变。

## 关键 commits

```text
3df9fd78b7c41e38a36502e0ed429793e02f6b26  feat: define bounded git staging semantics
60e34a73890b13819e3777e9b4977a6b39a6ef1a  refactor: centralize bounded git stage commands
4cc04da8d8228991551e40366e8e3693b3824dab  feat: verify resident git staging choices
4e24fa7eac5e8e69a3a89ce676b8d24a23bb2963  feat: learn verified git staging variants
3a28a6aaa1310c53bb525df1ed0456e57cf474d4  test: prove resident git staging choices
da912358b98530c61d951e2098a64262bdf083b1  test: prove git staging tactic recovery
294f67100cd9d6a042873c8e0f854e7ec0c13110  fix: revalidate persisted git staging identity
7ec9725e9a2c9926adce36ec2d1ac8cfc9df926c  test: cover git staging identity contract
7d07af8eab9c1eb62b514acd54e4e074905e15f6  docs: sync current resident competence priority [skip ci]
ff76a80bbc1e610923b13e18a547e2cdbe4623fa  docs: record bounded resident git staging tactics [skip ci]
```

本阶段共有 11 个 code/test commits；上表列出关键 commits。以 `compare_commits(3bfd45f... → 7ec9725e...)` 的真实 11-commit range 和最终 CI 为权威。

## 真实测试 / CI

权威最终 CI：run `32650706582`, code/test SHA `7ec9725e9a2c9926adce36ec2d1ac8cfc9df926c`。

```text
ZN Kernel / Python          success
Electron / TypeScript      success
Container / Runtime Smoke  skipped
Publish commit statuses    success
```

Python job `97221754667`：checkout、ZN home、Python/uv、locked deps、isolated runtime install、zero-model boot、compile、full kernel unittest discovery 全部 success。

Electron job `97221754543`：install、typecheck、bundle、desktop ownership/packaged runtime/update/handoff contracts、release-channel/runtime-staging/packaged-artifact verifiers 全部 success。

本环境没有完整 authenticated private-repo checkout，因此没有把 isolated container Git semantic experiments 冒充 repository integration。真实集成以上述 GitHub Actions 为准。

## 当前仍未完成 / 不得误报

- already-satisfied typed `git_path_staged` 的 native terminal resolution；
- Git-specific L3 current-reality applicability；
- learned Git candidate 对 current resident-formed staging choices 的安全 bias；
- broader resident-owned tactic formation beyond exact-text + single-path Git staging；
- arbitrary command equivalence / arbitrary side-effect tactic synthesis；
- general reliable high-level postcondition derivation；
- mature procedural skills / fast path；
- practical broader Git mutation + diff/test/reality verification；
- GitHub repo/PR/CI resident-owned sense；
- learned engineering competence beyond this staging proof；
- browser Body/Senses seam and learned computer-use competence；
- growth benchmarks；
- autonomous outbound artifact nomination；
- Telegram photo/audio/video-specific transports；
- successful installed AppImage N → N+1 continuity；
- Windows/macOS intended clean-install/login continuity；
- signing/notarization；
- SM1+ self-maintenance。

## 风险 / 阻塞

Core lane 当前无已知 CI blocker。

主要风险是把这个成功的 narrow Git contract 泛化成 arbitrary command planner。当前允许的 staging variants 必须继续由 resident-owned semantic module 从 current goal/current evidence 重建；memory/model 不得提供 raw path/command authority。

一个已知 correctness gap：`git_path_staged` 已经满足时，action formation 正确不产生 mutation，但 Investigation 还没有 dedicated terminal-resolution contract；在扩大 Git L3 authority 前应先补这个闭环。

M8 updater debt 未变化：run `32645354818` real installed AppImage updater continuity smoke cancelled；N/N+1 build 成功不等于 continuity verified。

## 下一真实目标

Fresh restore 后：

1. 重新读取所有必读文档和真实 dev HEAD/CI/diff/PR；
2. 先补 already-satisfied `git_path_staged` native resolution，保证当前现实已经满足目标时不 mutation、不 model fallback；
3. 再设计 Git-specific L3 applicability：必须由 current structured Git/path evidence 证明同一 root/target/goal；
4. positive influence 若开放，只能 reorder 当前刚刚由 resident 形成的 `git_add` / `git_update_index` choices，不能 replay learned command/path；
5. 保持 fresh `git_state` postcondition verification、anti-replay、event-local revocation、privacy-safe L1/L2；
6. authority 扩大前补 stale/missing evidence、cross-target、identity mismatch、unsafe side effect、contradiction negatives；
7. 然后推进 bounded Git mutation → diff/test/current-reality engineering loop，而不是 planner tree。

判断标准仍然是：

> **这样是否让持续存在的 ZN Self 更能基于当前现实形成、验证并内化自己的能力。**
