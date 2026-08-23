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

本阶段已把 bounded single-path Git staging 从 resident-owned tactic formation/recovery/L1-L2 learning 推进到第一条 reality-gated Git L3 reusable competence，并关闭 already-satisfied typed staging goal 的 native terminal-resolution gap。

当前 code/test truth：

```text
current typed git_path_staged goal
+ current structured Git/path facts
→ resident freshly forms:
   A = git add -- <current repo-relative path>
   B = git update-index --add -- <current repo-relative path>
→ learned evidence cannot supply path/workdir/command
→ Git-specific L3 may only reorder current A/B when current goal/root/target/variant reality is re-proven
→ Body executes selected current movement
→ fresh git_state must prove exclusively staged
→ only then complete / positive learning
```

如果 current structured reality 已经证明目标 exclusively staged，Investigation 直接 terminal-resolve，不 mutation、不 model fallback、不制造没有 causal action 的 positive VerifiedExperience。

## 当前分支 / HEAD / CI

- 固定开发分支：`dev/zn-agent`
- 本阶段恢复时 dev HEAD：`a03dd1ae912a294927eec3279cd8f0f73def6a19`
- 最终 code/test SHA：`f4d780d8af708c4136dd5b88c0f37eeb8b561a8e`
- 权威 code/test CI：run `32652858740`
  - `ZN Kernel / Python = success`
  - `Electron / TypeScript = success`
  - isolated `runtime/python` install = success
  - zero-model isolated runtime boot = success
  - kernel compile + full unittest discovery = success
  - Electron install/typecheck/bundle/ownership/runtime/update/handoff/release verifiers = success
  - `Container / Runtime Smoke = skipped`（normal push contract）
  - `Publish commit statuses = success`
- Python job：`97227036123`
- Electron job：`97227036021`
- implementation-status sync commit：`3155bca72e21d34b8b377050a48d79e6fa2a4796` (`[skip ci]`)
- 本 HANDOFF commit 也是 docs-only `[skip ci]`；提交后以重新读取的 `dev/zn-agent` branch ref 作为最终当前 HEAD。
- `main` 必须保持 `61dd880aa4bbbdb359ca544b752afc2c22845ce9`，M10 未满足。

本阶段真实中间失败必须保留：

- SHA `7191b94875ee7f733d014dc08ed8a06bbd4c56b0`
- run `32652606569`
- Electron success，Python failure
- 354 tests 中 1 个 failure：真实 resident 第 4 轮仍选 `git_add`，未应用成熟 `git_update_index` tendency
- 根因：L1 使用 event `required_capabilities` 记录 causal domains；active L3 使用 SelfModel hierarchical `readiness.domains` exact-match，`it/git` 的 parent `it` 造成 false mismatch
- `f4d780d8...` 改为该 Git family 用与 L1 相同的 typed current-event capability contract；没有放宽 root/target/current-reality gate
- final run `32652858740` 双绿，真实关闭该 failure

## 本阶段开始前恢复的真实现场

已重新读取/检查：

1. `ZN.md`
2. `AGENTS.md`
3. `docs/ZN-IMPLEMENTATION-STATUS.md`
4. `docs/ZN-SOURCE-EXTRACTION.md`
5. `docs/ZN-SELF-MAINTENANCE.md`
6. `.agent/HANDOFF.md`
7. `docs/ZN-MEMORY-LEARNING.md`
8. `docs/ZN-NEXT-PHASE.md`
9. `dev/zn-agent` HEAD / main relation / open PR / recent commits / CI
10. `Investigation → Action → Body → verification → VerifiedExperience → L2 → L3` active call chain

恢复时事实：

- dev HEAD = `a03dd1ae912a294927eec3279cd8f0f73def6a19`
- open PR = 0
- previous final code/test `7ec9725e...`, run `32650706582`, Python/Electron 双绿
- main = `61dd880aa4bbbdb359ca544b752afc2c22845ce9`
- M8 real AppImage N→N+1 run `32645354818` 的 installed updater smoke 仍 cancelled；不得报 verified

## 本阶段实现

### 1. Already-satisfied Git terminal resolution

`agent/kernel/investigation.py`

只有 current `git_semantics` 同时证明：

```text
staged=true
unstaged=false
untracked=false
conflicted=false
root/path identity valid
```

才 native terminal-resolve。staged+unstaged、conflict、missing Git/path facts 均 fail closed。

### 2. Current Git intent semantic proof

`agent/kernel/git_semantics.py`

新增 `current_git_stage_intent_goal(...)`，重新证明：

- current typed goal 仍 stageable 且未 satisfied；
- current root/path/relative identity 一致；
- source=`resident_choice`；
- kind=`command`；
- workdir=current root；
- command=该 current variant/current relative path 的 canonical resident rendering。

它不是 arbitrary shell parser；任何不一致 fail closed。

### 3. Git-specific L3 applicability

`agent/kernel/procedural_applicability.py`

只有 exact current resident intent semantic proof 成立后才暴露 `git_path_staged` applicability。L2 candidate 继续要求 current：

- expected kind；
- action variant；
- target fingerprint + independently observed path；
- root/workdir fingerprint + independently observed Git root；
- candidate maturity/reliability/non-inhibited；
- event-local non-revoked。

cross-target、missing reality、identity mismatch、corrupted command、forged non-resident command 都 zero positive influence。

### 4. Positive Git influence only reorders current choices

`agent/kernel/procedural_influence.py`

Generic command 仍没有 positive procedural authority。唯一 command exception：

```text
kind=command
source=resident_choice
kind=git_path_staged
current_goal_proven=true
variant=git_add | git_update_index
```

memory 不提供 command/path/workdir/args，不形成新 choice。

### 5. Active learned-loop proof

真实 temp Git repo integration：

```text
3 distinct events
→ each freshly forms [A,B]
→ synthetic first-A Body failure leaves repo unchanged
→ anti-replay blocks A
→ resident recovers to real B
→ fresh git_state verifies B
→ 3 verified privacy-safe B L1
→ supported B L2

4th current event
→ fresh current path/Git observation
→ freshly forms [A,B]
→ Git L3 supports B only from current reality + mature evidence
→ reorders current choices to B
→ exactly one real B command
→ fresh git_state verification
→ zero model invocations
```

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

- `ZN.md`：架构方向未改变，本阶段执行的是上一个 checkpoint 已定义的目标
- `docs/ZN-SOURCE-EXTRACTION.md`：无 Hermes extraction state 变化
- `docs/ZN-SELF-MAINTENANCE.md`：无 self-maintenance architecture 变化
- `main`

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
3155bca72e21d34b8b377050a48d79e6fa2a4796  docs: record reality gated git procedural competence [skip ci]
```

Start code range `a03dd1ae... → f4d780d8...` = 8 ahead-only code/test commits。

## 当前仍未完成 / 不得误报

- broader resident-owned tactic formation beyond exact-text + single-path Git staging；
- arbitrary command equivalence / arbitrary side-effect tactic synthesis；
- general reliable high-level postcondition derivation；
- practical broader Git mutation → diff/test/current-reality verification loop；
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

小型一致性 cleanup 仍未完成：

1. `agent/kernel/action.py` Git choice formation 仍直接拼与 `git_stage_command()` 等价的 canonical strings；verification 已以 central renderer 为权威，formation 侧后续应去重复。
2. `EmbodiedInvestigator` 的 read-only procedural-candidate evidence surface 仍是较早 generic call shape；active Git L3 selection 已正确使用 current facts 并通过 CI，但 observational diagnostic surface 应与 active current-facts/domain semantics 对齐。

## 风险 / 阻塞

Core lane 当前无已知 CI blocker。

主要风险仍是把 narrow Git semantics 泛化成 arbitrary command planner。任何下一 command-side competence 都必须先有明确 effect semantics、current-world authority、independent verifier 和 negative tests。

M8 debt 未变化：run `32645354818` 的 real installed AppImage updater continuity smoke cancelled；N/N+1 build success 不等于 updater continuity verified。

## 下一真实目标

Fresh restore 后：

1. 重新读取必读文档和真实 dev HEAD/CI/diff/PR；
2. 先做上述两项小型一致性 cleanup；
3. 选择一个 effect/verifier 都能结构化证明的 bounded engineering task，开始 Git mutation → diff/test/current-reality loop；
4. 继续要求 current resident choice formation、fresh verification、anti-replay、event-local revocation、privacy-safe L1/L2/L3；
5. authority 扩大前补 stale/missing evidence、cross-target、identity mismatch、unsafe side effect、contradiction negatives；
6. 再增加 GitHub repo/PR/CI resident-owned sense，前提是有明确 current-world consumer；
7. M8 installed updater continuity 继续作为独立 release debt。

判断标准：

> **这样是否让持续存在的 ZN Self 更能基于当前现实形成、验证并内化自己的能力。**
