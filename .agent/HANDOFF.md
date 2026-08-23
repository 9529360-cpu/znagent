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

当前核心已从“证明第一条 Git L3”进入下一阶段：保持 Git staging semantic / formation / applicability / diagnostic 一致，然后扩展到一个 effect/verifier 都能结构化证明的 bounded engineering mutation → diff/test/current-reality loop。

当前已经成立的 Git competence truth：

```text
current typed git_path_staged goal
+ current structured Git/path facts
→ resident freshly forms current A/B only:
   A = git add -- <current repo-relative path>
   B = git update-index --add -- <current repo-relative path>
→ one canonical git_stage_command renderer owns command formation semantics
→ current Git semantic proof re-proves goal/root/target/relative path/source/workdir/variant
→ learned evidence may only reorder freshly formed current A/B
→ read-only Investigation diagnostic evaluates the same current facts/domain contract and full current choice set
→ Body executes current movement
→ fresh git_state must independently prove exclusively staged
→ only then complete / positive learning
```

如果 current structured reality 已经证明目标 exclusively staged，Investigation 直接 terminal-resolve，不 mutation、不 model fallback、不制造没有 causal action 的 positive VerifiedExperience。

## 当前分支 / HEAD / CI

- 固定开发分支：`dev/zn-agent`
- 本阶段恢复时 dev HEAD：`63a42c139599a01791dc7d8bca7e019a2397c9cc`
- 最终 code/test SHA：`22e1abde5cd5e1bc228d19a7d09eff6d2f9c8cc8`
- 权威 code/test CI：run `32654830857`
  - `ZN Kernel / Python = success`
  - `Electron / TypeScript = success`
  - isolated `runtime/python` install = success
  - zero-model isolated runtime boot = success
  - kernel compile = success
  - full kernel unittest discovery = success
  - Electron locked install/typecheck/bundle/ownership/runtime/update/handoff/release verifiers = success
  - `Container / Runtime Smoke = skipped`（normal push contract）
  - `Publish commit statuses = success`
- Python job：`97231890643`
- Electron job：`97231890487`
- `ZN.md` current-state sync：`00147f99f8aed878fa1955891edd91f2b2b18cc1` (`[skip ci]`)
- implementation-status sync：`3c9d1194c869bd4fb28b0c92401823fc338752b8` (`[skip ci]`)
- 本 HANDOFF commit 也是 docs-only `[skip ci]`；提交后必须重新读取 `dev/zn-agent` branch ref 作为最终当前 HEAD。
- `main` 基线必须保持 `61dd880aa4bbbdb359ca544b752afc2c22845ce9`；M10 未满足。
- open PR 在本阶段恢复时为 0；结束前再次检查。

上一阶段保留的真实 Git-L3 中间失败仍是历史证据，不应删除或改写：

- SHA `7191b94875ee7f733d014dc08ed8a06bbd4c56b0`
- run `32652606569`
- Electron success，Python failure
- 根因是 L1 event capability contract 与 SelfModel hierarchical domain representation false mismatch
- `f4d780d8af708c4136dd5b88c0f37eeb8b561a8e` / run `32652858740` 已真实关闭该 failure

## 本阶段开始前恢复的真实现场

已重新读取/检查：

1. `ZN.md`
2. `AGENTS.md`
3. `docs/ZN-IMPLEMENTATION-STATUS.md`
4. `docs/ZN-SOURCE-EXTRACTION.md`
5. `docs/ZN-SELF-MAINTENANCE.md`
6. `.agent/HANDOFF.md`
7. `dev/zn-agent` HEAD / main relation / open PR / recent commits / CI
8. Git staging formation → semantic proof → applicability → active selection → Investigation diagnostic 的真实调用链

恢复事实：

- dev HEAD = `63a42c139599a01791dc7d8bca7e019a2397c9cc`
- previous final code/test = `f4d780d8af708c4136dd5b88c0f37eeb8b561a8e`
- previous run = `32652858740`, Python/Electron 双绿
- main = `61dd880aa4bbbdb359ca544b752afc2c22845ce9`
- open PR = 0
- M8 real AppImage N→N+1 run `32645354818` 的 installed updater smoke 仍 cancelled；不得报 verified

恢复时发现 `ZN.md` 25.8/next-target wording仍把 Git positive L3 写成 future work，但真实代码、status、HANDOFF 和 run `32652858740` 已证明第一条 bounded Git L3 active。已按真实仓库纠正文档，没有改变产品方向。

## 本阶段实现

### 1. Git staging action formation 统一使用 canonical renderer

`agent/kernel/action.py`

原来 formation 侧自行 `shlex.quote` 后拼：

```text
git add -- ...
git update-index --add -- ...
```

现在直接调用 `git_semantics.git_stage_command(variant, relative_path)`。

结果：

- formation 和 current semantic proof 使用同一 renderer；
- 不再保留两套等价但可能漂移的 command construction；
- renderer 返回异常/未知 variant 时 fail closed；
- regression 使用带空格 repo-relative path，验证两个 current variants 的实际 command 都等于 canonical renderer 输出。

### 2. Active Git L3 与 read-only diagnostic 共用 current domain contract

`agent/kernel/procedural_applicability.py`

新增共享 `current_procedural_applicability_domains(...)`。

规则：

- generic/write families 继续使用 caller/SelfModel current domains；
- 只有 exact current `resident_choice` + `git_path_staged` + `current_goal_proven` 才使用与 L1 causal evidence 相同的 event `required_capabilities` contract；
- parent domain expansion（例如 `it` + `it/git`）不再制造 false Git mismatch；
- helper 本身不提供 action authority。

`agent/kernel/procedural_influence.py`

删除本地 `_git_event_domain_contract` duplicate，active influence 改为调用共享 helper。Generic commands 的 positive authority 边界没有扩大。

### 3. Investigation procedural diagnostic 与 active current semantics 对齐

`agent/kernel/embodied_investigation.py`

原问题：

```text
derive_native_action_intent() 只看 default A
current_expected_outcome() 未传 current facts
readiness.domains 与 active Git causal-domain representation 不一致
```

因此成熟 B candidate 可能在只读 evidence surface 被错误拿去和 A 比较，或因缺 current facts/domain mismatch 被误报。

现在：

- 用 `derive_native_action_intents(...)` 取得完整 current resident choice set；
- 每个 candidate 只读地对当前同 kind choices 逐一评价；
- `current_expected_outcome(..., facts=current facts)`；
- 使用共享 current applicability-domain helper；
- `supported` current choice 可胜过同一 candidate 对另一 current variant 的 mismatch/untested；
- 仍然只写 Investigation evidence，不选择、不执行、不制造 action。

### 4. Regression / diff review

`tests/agent/kernel/test_git_procedural_influence.py`

新增/强化：

- path with spaces → formation command exactly equals canonical `git_stage_command`；
- active influence 收到包含 SelfModel parent `it` 的 current domains，仍通过 typed event causal contract 正确支持 current Git B；
- active four-event zero-model learning integration 在第 4 轮进入 native action 前，Investigation evidence 必须已经把成熟 B candidate 识别为 `supported by current independent evidence`；
- existing cross-target / missing reality / corrupted choice / forged generic command negatives 继续保留。

修改 `embodied_investigation.py` 时 diff review 发现一次无关回归：vision fact 的 `"luminance"` 字段被意外带掉。已在 final code/test SHA 前恢复；最终 cumulative diff 不改变既有 vision contract。

## 本阶段文件

Code:

```text
agent/kernel/action.py
agent/kernel/procedural_applicability.py
agent/kernel/procedural_influence.py
agent/kernel/embodied_investigation.py
```

Tests:

```text
tests/agent/kernel/test_git_procedural_influence.py
```

Docs:

```text
ZN.md
docs/ZN-IMPLEMENTATION-STATUS.md
.agent/HANDOFF.md
```

没有修改：

- `docs/ZN-SOURCE-EXTRACTION.md`：无 Hermes extraction state 变化
- `docs/ZN-SELF-MAINTENANCE.md`：无 self-maintenance architecture 变化
- `main`

## 本阶段关键 commits

```text
45625637c1b69201a0ff9241753ef6c8223da831  refactor: centralize git staging command formation
37284d441a1eabf6d20a358354501510a82fa2e1  refactor: share current procedural applicability context
88e89b0b0df31150eeeae58e64490c1c48cef709  refactor: reuse procedural applicability domains
094f21327a15c32dbbb4312993106ee39f663a15  fix: align procedural diagnostic with current choices
65972d38675481161e1212f2a4c675ddc4cce558  test: align git applicability diagnostics with active semantics
22e1abde5cd5e1bc228d19a7d09eff6d2f9c8cc8  fix: preserve vision luminance diagnostic
00147f99f8aed878fa1955891edd91f2b2b18cc1  docs: sync verified git l3 architecture state [skip ci]
3c9d1194c869bd4fb28b0c92401823fc338752b8  docs: record git applicability consistency verification [skip ci]
```

Code/test range `63a42c139599... → 22e1abde5cd5...` = 6 ahead-only code/test commits。

## 当前仍未完成 / 不得误报

- practical broader engineering mutation → diff/test/current-reality verification loop；
- broader resident-owned tactic formation beyond exact-text + single-path Git staging；
- arbitrary command equivalence / arbitrary side-effect tactic synthesis（仍应禁止，除非未来有独立 semantic family）；
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

主要风险仍是把一个已证明的 narrow semantic family 错误泛化成 arbitrary command planner。下一条 engineering competence 必须先定义 current-world authority、effect semantics、independent verifier 和 negative cases，再允许 resident choice/learning；不能先让模型或 procedure memory 产生 raw side-effect arguments。

只读 Investigation diagnostic 现在与 active Git L3 对齐，但它仍只是 observational evidence，绝不能变成第二个 selection/control plane。

M8 debt 未变化：run `32645354818` 的 real installed AppImage updater continuity smoke cancelled；N/N+1 build success 不等于 updater continuity verified。

## 下一真实目标

Fresh restore 后：

1. 重新读取必读文档和真实 dev HEAD/CI/diff/PR；
2. 追当前 Body/file/Git/diff/test/postcondition 的真实调用链；
3. 选择一个 effect/verifier 都能结构化证明的 bounded engineering mutation，不做 arbitrary shell planner；
4. 目标应形成明确的 mutation → diff/test/current-reality verification loop，并保持 current resident choice formation、fresh verification、anti-replay、event-local revocation、privacy-safe L1/L2/L3；
5. authority 扩大前先补 stale/missing evidence、cross-target、identity/equivalence ambiguity、unsafe side effect、contradiction negatives；
6. generic command positive authority继续禁止，除非新的 semantic family 自己证明 current authority + verifier；
7. GitHub repo/PR/CI sense 只在出现明确 current-world consumer 后增加；
8. M8 installed updater continuity 继续作为独立 release debt。

判断标准：

> **这样是否让持续存在的 ZN Self 更能基于当前现实形成、验证并内化自己的能力。**
