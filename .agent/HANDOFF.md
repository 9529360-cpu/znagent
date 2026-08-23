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

> **Models may help ZN learn. Mature capability must belong to ZN.**

L1 `VerifiedExperience`、L2 transparent candidate aggregation、L3 current-reality applicability，以及第一片 **bounded low-risk L3 action influence** 已完成并经过真实主 CI。

当前下一真实目标不是 fast path，也不是把历史 action args replay 出来。下一步应让 ZN 自己的 Will / Investigation / deliberation 在当前事实下形成**有语义保证的 bounded structured choice set**，然后继续沿现有 reality-gated influence + independent verification 路径使用学习证据。

普通多子句 task text 不能被猜成 alternatives；外部模型文本也不能成为 choice owner。

纯 UI/desktop polish 继续暂停。M8/release 保持 bounded parallel lane。

## 当前分支 / HEAD / CI

- 固定开发分支：`dev/zn-agent`
- 本阶段最终真实 code/test SHA：`aec75ec2b2a2e37eae57a4a26011f324c1a823ff`
- real code CI：run `32643849526`
  - `ZN Kernel / Python = success`
  - `Electron / TypeScript = success`
  - isolated `runtime/python` install + zero-model boot step = success
  - kernel compile + full `tests/agent/kernel/test_*.py` = success
- implementation-status docs commit：`01508351e979549f66263171c53c34b479f63e1c` (`[skip ci]`)
- 本 HANDOFF 更新本身也是 docs-only `[skip ci]`，因此会成为新的远程 HEAD；下一维护者必须重新读取 remote HEAD，不能把上面的 code SHA 当分支 HEAD。
- 本阶段开始时 Open PR = 0。
- 本阶段开始时已补做并真实确认 `main` 与基线 `61dd880aa4bbbdb359ca544b752afc2c22845ce9` identical；结束前仍需再次核对。

当前执行环境没有 private-repo checkout，也没有 `gh` CLI。因此没有宣称 full local repo tests；代码验证以 GitHub Actions 为权威。

## 本阶段开始时恢复的真实现场

重新读取并核对：

1. `ZN.md`
2. `AGENTS.md`
3. `docs/ZN-IMPLEMENTATION-STATUS.md`
4. `docs/ZN-SOURCE-EXTRACTION.md`
5. `docs/ZN-SELF-MAINTENANCE.md`
6. `.agent/HANDOFF.md`
7. `docs/ZN-MEMORY-LEARNING.md` 当前 L3 契约
8. `dev/zn-agent` HEAD / recent commits / open PR / CI
9. `_deliberation_step` / `derive_native_action_intent()` / L2/L3 / world-aware active runtime caller chain

开始时 `dev/zn-agent` 精确 HEAD：

```text
849b90d9cf3e59d1eced179e59fbd7d7e56b40bc
```

compare identical；Open PR 0；上一阶段 code/test SHA `202b69e947db6c178d821c27e51fc1e61a90ce82` 的 run `32642408966` 仍 Python/Electron 双绿。

同时补做了上一阶段未完成的最终 `main` 对账：

```text
61dd880aa4bbbdb359ca544b752afc2c22845ce9 == main
```

没有 drift。

## 当前真实 learning / action call chain

### L1 causal evidence

```text
provider bridge
→ active resident
→ Investigation / current facts
→ NativeActionIntent
→ Body action
→ durable native_verification
→ independent Body observation
→ VerifiedExperience
→ VerifiedExperienceStore
```

正/负 learning label 仍来自 independent verification，不来自 model text、Body return success 或 naked shell exit 0。

### L2 candidate

```text
VerifiedExperienceStore.candidate_tendencies()
→ bounded retained causal episodes
→ privacy-safe compatible aggregation
→ CandidateProceduralTendency
```

Candidate 是 derived resident-owned view，不是第二个 mutable skill DB。

### L3 applicability

```text
CandidateProceduralTendency
+ current action shape
+ current expected-outcome contract
+ current persisted Investigation facts
→ evaluate_candidate_applicability()
→ supported / mismatch / untested
```

`Investigation.facts` 不保存 derived L3 judgement，因此不会污染 L1 reality fingerprint。

### L3 bounded action influence

Active constructor 现在是：

```text
provider_bridge.build_resident_runtime()
→ ProcedurallyInfluencedResidentRuntime
→ WorldAwareTransferResidentRuntime
→ full existing embodied/world/transfer chain
```

影响路径：

```text
current explicit structured choice set
+ current Investigation facts
+ L2 candidate tendencies
+ L3 applicability
→ select_procedurally_influenced_intent()
→ existing _begin_native_action_cycle()
→ existing Body
→ existing independent verification
```

学习证据只允许重排当前已存在的 choice；不提供 raw command/args/path/content。

## 本阶段完成：第一片 bounded L3 action influence

### 1. 新增 procedural influence evaluator / selector

文件：

```text
agent/kernel/procedural_influence.py
```

核心对象：`ProceduralActionInfluence`。

只保留 privacy-safe proof：candidate/evaluation ID、action kind、maturity、reliability、support counts、context fingerprint、reality-matched field labels。

第一 slice 正向 influence gate：

- candidate maturity 只能是 `supported` / `practiced`；
- candidate 必须 non-inhibited；
- reliability >= `0.75`；
- 当前 `evaluate_candidate_applicability(...)` 必须正好是 `supported`；
- event-local revoked candidate 不能再次产生正向 influence；
- 第一 slice 只允许 exact non-append `write_text`；
- 必须存在 resident-owned automatic `text_equals` independent postcondition；
- command / append write / direct explicit `structured_event` action 均零 positive influence。

`mismatch` / `untested` 永远零正向动作权。

### 2. `action.py` 增加 structured choice seam，但保留旧行为

新增：

```text
derive_native_action_intents(...)
```

兼容 API：

```text
derive_native_action_intent(...)
```

仍返回第一/default choice。

关键语义：

- 普通 heuristic action formation 仍是历史 single-choice 行为；
- 只有当前 event 明确携带 bounded `native_action_options` 时才形成 multi-choice set；
- valid `body_action` / `native_action` 仍 exclusive，优先于 options；
- invalid explicit shape 仍保留历史 heuristic fallback；
- `native_action_options` 最多读取 8 个；
- each option 的 args 来自当前 structured event option，不来自 procedural memory；
- 普通 task 里同时出现 “command + write” 不会被解释成 alternatives，因为两者可能是 sequential obligations。

这个修正很重要：阶段中曾短暂实现过“从 task 中同时形成多个 heuristic intents”，静态审查发现会扩大产品语义后已移除，最终 green SHA 不含该行为。

### 3. Active resident influence owner

新增：

```text
agent/kernel/procedural_resident.py
```

`ProcedurallyInfluencedResidentRuntime` 继承完整 `WorldAwareTransferResidentRuntime`，没有另起 planner/brain/main loop。

`_deliberation_step(...)`：

- 无 qualifying influence 时 100% delegate 到原 superclass 行为；
- 有 qualifying influence 时，只从 current `derive_native_action_intents(...)` 结果中选一个；
- candidate 不改变 args；
- existing `_action_blocked_by_current_evidence(...)` 比 familiarity 更强；
- admitted action 继续走 existing `_begin_native_action_cycle(...)`。

`_native_action_step(...)`：

- Body failure 后 event-local revoke active candidate，回 Investigation。

`_fail_postcondition_verification(...)`：

- verification contradiction 在 existing negative-evidence path 上 event-local revoke active candidate，回 Investigation。

WorkingState keys：

```text
procedural_action_influence
procedural_revoked_tendencies   # bounded 8 IDs; event-local
```

active influence metadata 不存 raw action args。

### 4. Anti-replay / attribution 边界

如果 influenced intent 已被当前 evidence-bound anti-replay 挡住：

- candidate 先加入 event-local revoked IDs；
- active influence marker 随即清掉；
- 然后才 delegate 到普通 superclass fallback。

这样后续 fallback 动作若失败，不会被错误归因到并没有选择它的 procedural candidate。

### 5. Thought visibility

在真实 `live_once()` action pulse 的 working-stage enrich 后，Thought 可以知道：

- 某个 candidate 当前正在 bias 一个 already-formed action kind；
- candidate 没有提供 action args；
- verification 仍然必要。

这不是新的 Thought action authority；stage/body owners 不变。

## 测试 / CI 真实结果

新增：

```text
tests/agent/kernel/test_procedural_influence.py
tests/agent/kernel/test_native_action_alternatives_contract.py
```

覆盖：

- explicit `native_action_options` declared order；
- default compatibility 仍选第一项；
- valid explicit body action remains exclusive；
- invalid explicit shape 保留 historical native fallback；
- ordinary multi-clause task 不被重解释为 alternatives；
- incompatible directory target 不会变成 write alternative；
- supported candidate 只能重排 current safe intents；
- selected write 的 path/content 来自 current option；
- serialized influence 不包含 raw path/content/task/command；
- immature / mismatched / revoked / command / append route 均 zero positive influence；
- real active runtime 仍是 world-aware runtime subclass；
- 3 个 distinct independently verified writes 形成 `supported` candidate；
- current explicit choice `[command, write_text]` 的 historical default 仍是 command；
- reality-supported candidate 实际 bias 到 already-specified write；
- Body 真实执行 write_text；
- independent Body read_text 验证后才 success；
- command marker 没有执行；
- real action pulse Thought 看得到 current influence；
- 第二次 influenced write 后人为改变 reality，verification contradiction 真实回 `native_investigation` 并 event-local revoke candidate。

最终 code/test SHA：

```text
aec75ec2b2a2e37eae57a4a26011f324c1a823ff
```

GitHub Actions run：

```text
32643849526
ZN Kernel / Python      success
Electron / TypeScript  success
Publish statuses        success
Container smoke         skipped  # normal push workflow contract
```

Python job 中实际经过：

```text
locked repository dependencies
isolated runtime/python install
zero-model isolated runtime boot
compile agent/kernel
full unittest discover tests/agent/kernel/test_*.py
```

全部 success。

## 本阶段关键 commits

```text
7e0ce2478e9f3f2a0682ec7c59b0fd1287787134  feat: gate procedural action influence
0f7f69c1acf6827aad18e17db7e2dfd54ad770dc  feat: expose structured native action alternatives
e17c45b2559b3c8981e19b5d3c9a12738cf89b4d  feat: rank procedural influence within native choices
9eb973a1832a2d016f9d8e0af5148392abe9958b  feat: let supported procedures bias native deliberation
6a3c05e5c6c50702d34709c317945883319b51ff  fix: preserve world-aware active runtime under procedural influence
a09899c0c90e04786f4f410f9256488b96e9e91c  feat: activate bounded procedural resident influence
d5fb73c088945ccc0a05c8b628704654e52ff88f  test: cover bounded procedural action influence
12b81cf000ccd5cde0d77daf364369d43f268d42  fix: preserve native fallback for invalid explicit actions
96be642275bb381ea0195a8c91fc1a398f02ecde  fix: isolate blocked procedural fallback attribution
d18beed9602146ab695ad104eb9f0e46b78696b6  test: preserve native action alternative compatibility
665d49b7397100513495615d3e656891246ae186  fix: require explicit structured action choice sets
211a94c4dbf92c5d2d83547656dcc038c6468359  test: use explicit native action choice sets
aec75ec2b2a2e37eae57a4a26011f324c1a823ff  test: observe procedural thought on real action pulse
01508351e979549f66263171c53c34b479f63e1c  docs: record bounded L3 action influence [skip ci]
```

## 当前没有实现、不得误报

仍 PARTIAL / MISSING：

- resident-owned generation of useful structured choices from Will/Investigation；
- general candidate influence over command/arbitrary side effects；
- raw action replay from procedural memory；
- mature/procedural resident-owned skill state；
- procedural fast path；
- broad prediction-error de-proceduralization beyond candidate inhibition + event-local active-route revocation；
- stronger alternative-action recovery as a learned consumer；
- learned engineering competence；
- learned computer-use competence；
- growth benchmarks proving familiar work reduces external cognition while verification quality remains intact；
- practical Git mutation + diff/test/reality verification；
- GitHub repo/PR/CI resident-owned sense；
- browser Body/Sense seam；
- SM1+ self-maintenance implementation。

Do not describe the current `supported` candidate or influenced structured write as a mature skill / autonomous procedure / fast path。

## 下一真实目标

Fresh restore 后，优先实现 **resident-owned bounded structured choice formation**，不是扩大 procedural replay。

必须先重新追：

```text
Will / current Thought
→ current Investigation facts
→ derive_native_action_intent(s)
→ _deliberation_step
→ active ProcedurallyInfluencedResidentRuntime
→ Body
→ verification
```

建议边界：

1. choice set 必须由当前 ZN state / facts 有语义地证明是 alternatives，而不能从 free-text 多子句猜；
2. external model output 不能直接变成 choice owner；
3. candidate memory 不提供 raw command/args/path/content；
4. `mismatch` / `untested` 继续 zero positive influence；
5. exact write first-slice gates 保留，除非有新的 real evidence 支持扩大；
6. independent verification 永远保留；
7. anti-replay 比 familiarity 更强；
8. prediction error / contradiction 继续立即回 Investigation；
9. high-risk identity/long-term-memory/credentials/updater/rollback/signing/self-maintenance permissions 仍保留人工批准。

第一个 concrete learning consumer 仍建议沿：

```text
A fails
→ genuinely different B succeeds
→ B independently verified
→ later comparable current reality supports B-pattern
→ current resident-owned choice set legitimately contains B
→ supported candidate may bias toward B
→ independent verification still required
```

不要把它实现成 hardcoded A/B tactic rule。

## 风险

- 当前 `native_action_options` 是明确 structured event seam，不代表 ZN 已会自主形成 alternatives；不要把 seam 当能力完成；
- domain applicability 仍是保守 exact-match，泛化需要 benchmark 证据；
- generalized target/workdir candidate fail closed 是刻意设计；
- L3 Situation/applicability 每 pulse 是 bounded derivation；没有性能事实前不要加第二个 mutable cache；
- active caller hierarchy 有 world-aware / transfer-aware overrides，后续不能只改 parent owner 而不查 final runtime MRO；
- cognition-integration path 仍使用 historical single `derive_native_action_intent()`，本阶段没有把 procedural influence 扩到 external-cognition integration；不要误报；
- 正式 release / updater / signing / rollback 与本阶段无关，不要顺手扩大权限或触碰 secrets。

## 阻塞

无产品架构 blocker。

当前环境限制：没有 private-repo local checkout / `gh`，所以没有 full local repo test claim；GitHub Actions 是本阶段真实验证权威。

## 文档状态

本阶段已更新：

```text
docs/ZN-IMPLEMENTATION-STATUS.md
.agent/HANDOFF.md
```

未更新且原因明确：

```text
ZN.md                         # architecture direction 未改变
docs/ZN-SOURCE-EXTRACTION.md # 无新 Hermes extraction
docs/ZN-SELF-MAINTENANCE.md  # 无 self-maintenance architecture 变化
```

## 下次开始前

不要依赖本 HANDOFF 猜状态。必须重新：

1. 读六份必读文档；
2. 查 `dev/zn-agent` 精确 HEAD；
3. 查 `main` / diff / PR / CI / recent commits；
4. 查 active runtime MRO / caller；
5. 以真实代码 + Git + CI 为准对账 HANDOFF。
