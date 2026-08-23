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

本阶段把 bounded single-path Git staging 从“可形成/可恢复/可学习的 L1/L2 tactic family”推进到第一条 **reality-gated Git L3 reusable competence**，并关闭了 already-satisfied typed staging goal 的 native terminal-resolution gap。

ZN 现在可以在 typed `git_path_staged` 当前目标和当前 Investigation 的结构化 Git/path 事实共同成立时，自行重新形成：

```text
A = git add -- <current repo-relative path>
B = git update-index --add -- <current repo-relative path>
```

成熟 Git procedural evidence 不能恢复旧 command/path/workdir；它只能在当前 resident 已重新形成的 A/B 之间重排。适用性必须重新证明当前 typed goal、root、target、path identity、action variant 和当前 observed Git/path reality。Body action 后仍必须 fresh `git_state` 独立验证。

## 当前分支 / HEAD / CI

- 固定开发分支：`dev/zn-agent`
- 本阶段恢复时 dev HEAD：`a03dd1ae912a294927eec3279cd8f0f73def6a19`
- 最终 code/test SHA：`f4d780d8af708c4136dd5b88c0f37eeb8b561a8e`
- 权威 code/test CI：run `32652858740`
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
- Python job：`97227036123`
- Electron job：`97227036021`
- 本 HANDOFF commit 为 docs-only `[skip ci]`；提交后必须重新读取 branch ref 作为当前 HEAD。

本阶段有一个真实中间失败，不能抹掉：

- code/test SHA `7191b94875ee7f733d014dc08ed8a06bbd4c56b0`
- run `32652606569`
- Electron success，Python failure
- 354 个 Python tests 中 1 个失败：真实 resident 四轮学习集成测试中，第 4 轮仍选择 `git_add` 而不是已成熟的 `git_update_index`
- 根因不是 Git semantic gate，而是 L1 使用 event `required_capabilities` 记录因果域，L3 active path 却拿 SelfModel 展开的 `readiness.domains` 做 exact match；`it/git` 会额外产生父域 `it`，造成假 mismatch
- 修正后 Git L3 对该 resident-owned command family 使用与 L1 相同的 current event capability contract；没有放宽 cross-target/current-reality 检查
- final run `32652858740` 双绿，证明该 failure 已被真实 CI 关闭

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
10. `Will/Investigation → Action → Body → verification → VerifiedExperience → L2 → L3` 真实调用链

恢复时确认：

- dev HEAD = `a03dd1ae912a294927eec3279cd8f0f73def6a19`
- open PR = 0
- previous code/test SHA `7ec9725e9a2c9926adce36ec2d1ac8cfc9df926c` 的 run `32650706582` Python/Electron 双绿
- `main` 仍是 `61dd880aa4bbbdb359ca544b752afc2c22845ce9`
- M8 real AppImage N → N+1 run `32645354818` 的 installed updater smoke 仍 cancelled；不得写成 verified

## 本阶段真实实现

### 1. Already-satisfied Git goal can finish natively

`agent/kernel/investigation.py` 现在使用同一 `git_semantics` current-world contract 检查 typed `git_path_staged`。

只有 fresh/current structured evidence 同时证明：

```text
target staged == true
unstaged == false
untracked == false
conflicted == false
+ root/path identity still valid
```

Investigation 才直接 terminal-resolve “requested Git staging state is already satisfied”。

结果：

- 不形成 mutation choice；
- 不执行 command；
- 不调用 model；
- 不制造没有 causal action 的 positive VerifiedExperience。

staged+unstaged、conflict、missing Git、missing path 都不能走该终态。

### 2. Current resident Git intent must be re-proven from reality

`agent/kernel/git_semantics.py` 新增 `current_git_stage_intent_goal(...)`。

它不是 shell parser。它只接受当前 typed goal + current Investigation facts，并重新证明：

- current goal 仍 stageable 且尚未 satisfied；
- carried root/path/relative identity 重新解析后一致；
- source 必须是 `resident_choice`；
- kind 必须是 `command`；
- workdir 必须精确等于 current root；
- command 必须精确等于当前 variant + current relative path 的 canonical resident rendering。

任何不一致 fail closed。

### 3. Git-specific L3 applicability is current-reality gated

`agent/kernel/procedural_applicability.py` 只在上述 current intent proof 成立后，才暴露 Git staging applicability shape：

```text
kind = git_path_staged
current_goal_proven = true
action_variant = git_add | git_update_index
current target/workdir
```

随后 L2 candidate 还必须满足：

- expected kind 相同；
- stable action variant 相同；
- privacy-safe target fingerprint 相同；
- privacy-safe root/workdir fingerprint 相同；
- current path fact independently observes same target；
- current Git fact independently observes same root；
- candidate supported/practiced、未 inhibited、reliability >= 0.75；
- event-local candidate 未 revoked。

cross-target、missing reality、corrupted command、forged non-resident command 都得到 zero positive influence。

### 4. Positive Git influence only reorders current choices

`agent/kernel/procedural_influence.py` 仍禁止 generic command positive authority。

唯一新增 command eligibility 是：

```text
kind == command
source == resident_choice
expected kind == git_path_staged
current_goal_proven == true
variant in {git_add, git_update_index}
```

memory 不提供 path、workdir、command、args，也不增加新 choice。`select_procedurally_influenced_intent` 只能在当前 `derive_native_action_intents(event, facts)` 已形成的 tuple 中重排。

Git L3 的 domain applicability 使用与 L1 causal episode 相同的 typed current event `required_capabilities` contract；SelfModel 的 parent-domain expansion 仍用于 introspection，但不再制造假 causal-context mismatch。

### 5. Real active learning loop proven

新增真实 temp Git repository integration：

```text
3 个 distinct events
→ resident 每次形成 [A, B]
→ test 只让 first porcelain A 返回 synthetic Body failure，repo 不变
→ anti-replay blocks A
→ resident recovers to real B
→ fresh git_state verifies B
→ 3 个 verified privacy-safe B L1 episodes
→ one supported B L2 tendency

第 4 个 event
→ target 当前再次 changed
→ Investigation 重新观察 current path/Git reality
→ resident 重新形成 [A, B]
→ mature B evidence passes current Git-specific L3 gate
→ L3 only reorders current choices to B
→ exactly one real B command
→ fresh git_state verifies final state
→ 0 model invocations
```

这证明 learned Git evidence 已成为 resident-owned current choice bias，而不是 learned raw-command replay。

## 本阶段文件

Code:

```text
agent/kernel/git_semantics.py
agent/kernel/investigation.py
agent/kernel/procedural_applicability.py
agent/kernel/procedural_influence.py
```

Tests:

```text
tests/agent/kernel/test_resident_git_stage_resolution.py
tests/agent/kernel/test_git_procedural_influence.py
```

Docs:

```text
docs/ZN-IMPLEMENTATION-STATUS.md
.agent/HANDOFF.md
```

没有修改：

- `docs/ZN-SOURCE-EXTRACTION.md`：没有 Hermes extraction state 变化
- `docs/ZN-SELF-MAINTENANCE.md`：没有 self-maintenance architecture 变化
- `main`

`ZN.md` 的架构方向本阶段没有改变：本次实现的是上一 checkpoint 已明确规定的 next step，因此不把实现进度伪装成新的 architecture direction。

## 关键 commits

```text
c9907cd0f255a15a23e08d46984e3291292a5aab  feat: prove current git staging intent semantics
acbe5ca90dcec7d29f4ccd81d53eca2294379d7a  fix: resolve already satisfied git staging goals
8fd6bfd6b192b690edcaf81e90743f768790af46  feat: gate git procedural applicability by current reality
6288dd5325feba6a7610e86dd513a2f0632b9c61  feat: allow bounded git procedural choice bias
ff441db284891e245e492a24b643631a68de3694  test: prove already satisfied git staging resolution
740eea462c005a545e521711a687c3b226932f31  test: prove reality gated git procedural influence
7191b94875ee7f733d014dc08ed8a06bbd4c56b0  test: prove active learned git variant bias
f4d780d8af708c4136dd5b88c0f37eeb8b561a8e  fix: align git procedural domain contract
```

Start-of-stage `a03dd1ae...` → final code/test `f4d780d8...` is 8 commits, ahead-only.

## 真实测试 / CI

权威最终 CI：run `32652858740`, code/test SHA `f4d780d8af708c4136dd5b88c0f37eeb8b561a8e`。

```text
ZN Kernel / Python          success
Electron / TypeScript      success
Container / Runtime Smoke  skipped
Publish commit statuses    success
```

Python job `97227036123`：checkout、ZN home、Python/uv、locked deps、isolated runtime install、zero-model boot、compile、full kernel unittest discovery 全部 success。

Electron job `97227036021`：install、typecheck、bundle、desktop ownership/packaged runtime/update/handoff contracts、release-channel/runtime-staging/packaged-artifact verifiers 全部 success。

真实失败 run `32652606569` 也保留在事实记录中；它暴露了 domain-contract mismatch，后续 `f4d780d8...` 修复并由 final CI 关闭。

## 当前仍未完成 / 不得误报

- broader resident-owned tactic formation beyond exact-text + single-path Git staging；
- arbitrary command equivalence / arbitrary side-effect tactic synthesis（仍应禁止无语义证明的泛化）；
- general reliable high-level postcondition derivation；
- practical broader Git mutation → diff/test/current-reality verification loop；
- Git commit/push/reset/checkout/branch mutation authority；
- GitHub repo/PR/CI resident-owned sense；
- mature resident-owned engineering competence；
- general mature procedural fast path；
- clean browser Body/Senses seam and learned computer-use competence；
- growth benchmarks；
- autonomous outbound artifact nomination；
- Telegram photo/audio/video-specific transports；
- successful installed AppImage N → N+1 updater continuity；
- Windows/macOS intended clean-install/login continuity；
- signing/notarization；
- SM1+ self-maintenance。

一个小型 implementation cleanup 仍可后续处理：`agent/kernel/action.py` 的 Git choice formation 仍直接拼接与 `git_stage_command()` 等价的 canonical strings；语义 verification 已以 central renderer 为权威，但 formation 侧可进一步去掉重复 rendering。它不是当前 correctness blocker。

`EmbodiedInvestigator` 的 read-only procedural-candidate evidence surface 仍沿用较早的 generic call shape；active L3 decision path 已使用 current facts 并由 CI 证明正确。后续在扩大工程 tactic 前应把 observational surface 和 active Git applicability 的 current-facts/domain contract 完全对齐，避免诊断文本与真实 selection gate 表述不一致。

## 风险 / 阻塞

Core lane 当前无已知 CI blocker。

主要风险仍是把 narrow Git semantic contract 泛化成 arbitrary command planner。任何下一步 command-side competence 都必须先有明确 effect semantics、current-world authority、independent verifier 和 negative tests；memory/model 不得成为 raw side-effect argument authority。

M8 updater debt 未变化：run `32645354818` real installed AppImage updater continuity smoke cancelled；N/N+1 build 成功不等于 installed updater continuity verified。

## 下一真实目标

Fresh restore 后：

1. 重新读取所有必读文档和真实 dev HEAD/CI/diff/PR；
2. 先做小型一致性清理：让 Action 使用 central Git stage renderer，并让 read-only procedural applicability surface 与 active Git gate 使用同一 current-facts/domain semantics；
3. 然后扩展第一个 practical engineering loop：选择一个 effect/verifier 都可结构化证明的 bounded Git mutation → diff/test/current-reality task，不做 arbitrary shell equivalence；
4. 保持 current resident choice formation、fresh postcondition verification、anti-replay、event-local revocation、privacy-safe L1/L2/L3；
5. authority 扩大前补 stale/missing evidence、cross-target、identity mismatch、unsafe side effect、contradiction negatives；
6. 再增加 GitHub repo/PR/CI resident-owned sense，前提是它有明确 current-world consumer，而不是新 cognitive agent；
7. 继续保留 M8 installed updater continuity 为独立 release debt。

判断标准仍然是：

> **这样是否让持续存在的 ZN Self 更能基于当前现实形成、验证并内化自己的能力。**
