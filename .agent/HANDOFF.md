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

L1 `VerifiedExperience`、L2 transparent candidate aggregation，以及第一片 **L3 read-only current-reality applicability** 已完成并经过真实主 CI。

下一真实目标不是 fast path，也不是 raw replay。下一步是：

```text
supported CandidateProceduralTendency
+ current independently observed reality
→ bounded low-risk influence on existing ZN-owned structured action formation
→ independent post-action verification remains mandatory
```

`mismatch` / `untested` candidate 必须保持零正向动作权。即使 candidate 为 `supported` / `practiced`，当前实现仍不直接控制 Body。

stronger alternative-action recovery 保留为 learning architecture 的早期 consumer，而不是孤立 tactic generator。

纯 UI/desktop polish 继续暂停。M8/release 保持 bounded parallel lane。

## 当前分支 / HEAD / CI

- 分支：`dev/zn-agent`
- 本阶段最终真实 code/test SHA：`202b69e947db6c178d821c27e51fc1e61a90ce82`
- real code CI：run `32642408966`
  - `ZN Kernel / Python = success`
  - `Electron / TypeScript = success`
- implementation-status docs：`5af75e475960dfddd2cf3267bb6069d480b89fc6` (`[skip ci]`)
- 本 HANDOFF 更新本身为 docs-only `[skip ci]`，会成为新的远程 HEAD；下一维护者必须从 Git 重新读取 `dev/zn-agent` 精确 HEAD，不能把上面的 code SHA 当作分支 HEAD。
- Open PR 在本阶段开始时为 0；结束前必须再次核对。
- `main` 本阶段未修改；结束前必须再次对比原基线 `61dd880aa4bbbdb359ca544b752afc2c22845ce9`。

当前执行环境没有 private-repo checkout，也没有 `gh` CLI。因此本阶段没有宣称 full local repo tests；真实代码验证以 GitHub Actions 为权威。

## 本阶段开始时重新恢复的真实现场

开始工作前重新读取并核对：

1. `ZN.md`
2. `AGENTS.md`
3. `docs/ZN-IMPLEMENTATION-STATUS.md`
4. `docs/ZN-SOURCE-EXTRACTION.md`
5. `docs/ZN-SELF-MAINTENANCE.md`
6. `.agent/HANDOFF.md`
7. `dev/zn-agent` HEAD / recent commits / open PR / CI
8. 当前 L1/L2/Investigation/Situation/Action active call chain

开始时 `dev/zn-agent` 精确 HEAD：

```text
d739a03e599bf5881ef721fa40883cc5d55a5db5
```

开始时 compare identical；Open PR 0；旧 code/test SHA `25ff0ada9efc8e8d830d085856edca7ea772a696` 的 run `32640409344` 仍 Python/Electron 双绿。

同时重新读取 `docs/ZN-MEMORY-LEARNING.md` 的 L3 约束。

## 当前真实 learning call chain

### L1 causal evidence owner

```text
provider bridge
→ WorldAwareTransferResidentRuntime
→ EmbodiedResidentRuntime
→ Investigation / NativeActionIntent
→ BodyActionResult
→ durable native_verification
→ independent Body observation
→ VerifiedExperience
→ VerifiedExperienceStore
```

正/负 learning label 仍来自 independent verification，不来自：

```text
model text
Body return success
naked shell exit 0
```

### L2 candidate owner

```text
VerifiedExperienceStore.candidate_tendencies()
→ retained bounded causal episodes
→ privacy-safe compatible aggregation
→ CandidateProceduralTendency
```

Candidate 是 derived resident-owned view，不是第二个 mutable skill DB；restart 后由 L1 evidence 重建。

### L3 read-only applicability owner

新增：

```text
agent/kernel/procedural_applicability.py
```

当前路径：

```text
CandidateProceduralTendency
+ current NativeActionIntent shape
+ current expected-outcome contract
+ current persisted Investigation facts
→ evaluate_candidate_applicability()
→ supported / mismatch / untested
→ bounded observational evidence
→ CognitiveSituation.procedural_applicability
→ Thought.known
```

Active packaged product constructor 仍是：

```text
provider_bridge.build_resident_runtime()
→ WorldAwareTransferResidentRuntime
→ WorldAwareEmbodiedInvestigator
```

这条 active-caller 事实在本阶段 CI 中实际抓到并修复，见下文。

## 本阶段完成：L3 first read-only applicability slice

### 1. Pure evaluator

关键提交：

```text
cf2c270f3619e566cd0c07f81e6a2c5f59697cad  feat: add reality-gated procedural applicability
f36db4de98c75f200459f9a0a62d05509bd12e29  fix: fail closed on untested applicability fields
```

`ProceduralApplicabilityEvaluation` 只保留：

- evaluation ID；
- tendency ID；
- `supported | mismatch | untested`；
- action kind；
- candidate maturity/reliability/inhibited state；
- matched / mismatched / untested field names；
- independently reality-matched field names；
- privacy-safe current-context fingerprint。

没有 raw command、args、path、content、task text。

核心 fail-closed 规则：

- task/request shape 可以 disqualify / compare，但不能单独证明 applicability；
- `supported` 要求至少一个 stable candidate reality anchor 被当前独立 Investigation observation 命中；
- 所有当前参与比较的 contract field 必须已测试；
- current target/workdir/verification signature mismatch => `mismatch`；
- missing/incomplete current evidence => `untested`；
- generalized candidate 没有 stable target/workdir anchor => `untested`；
- inhibited candidate => cannot qualify；
- matching repo root 但缺 current command verification contract => `untested`，不能因为“同目录”就支持。

Current expected-outcome comparison 是 transient；raw current values 不写入 procedural memory。

### 2. Investigation/Situation/Thought integration

关键提交：

```text
87d5d9a6a46b0b9f94061502bbcb24752e9643f7  feat: surface procedural applicability from investigation
2404825f971b2deb252db16ac5ae3ecded17a5db  feat: expose procedural applicability to thought
4300d0bc7cdca615d75ed362156dd5bf8dda787e  fix: derive applicability from durable reality evidence
```

最终 ownership：

- Investigation 可保留 bounded textual observational note；
- `CognitiveSituation` 每次从 persisted event + persisted Investigation facts + current L2 candidate 重新 derive structured evaluation；
- restart 不需要第二个 applicability DB/cache；
- Thought 可以知道 candidate 当前是 supported/mismatch/untested；
- stage-derived `chosen_action` / `action_kind` 不因该评价改变。

### 3. 两个生命周期陷阱已避免

#### A. 不把 L3 evaluation 塞进 `Investigation.facts`

`EmbodiedResidentRuntime._evidence_fingerprint()` 会把 `Investigation.facts` 作为 L1 reality identity / failed-action retry evidence。

如果把 derived L3 judgement 写进 facts：

```text
L3 judgement
→ changes L1 evidence fingerprint
→ could falsely appear as new reality evidence
→ could incorrectly unlock a previously failed movement
```

因此当前实现明确不这么做。

#### B. 不依赖 Investigator 单独写 WorkingState cache

上层 `_investigation_step()` 持有自己的 `WorkingState` 并在 investigator 返回后保存。若 investigator 内部单独写同一个 WorkingState，很可能随后被上层旧 state 覆盖。

因此 structured applicability 不放在这种脆弱 cache；Situation 从 durable Investigation + L1/L2 现场重建。

### 4. Active caller 修复

真实主 runtime 的 `WorldAwareEmbodiedInvestigator.investigate()` 为避免 world schema feedback 重复，原本直接调用：

```text
NativeInvestigator.investigate(self, ...)
```

这会绕过 `EmbodiedInvestigator.investigate()` 的 L3 hook。

最终修复：

```text
202b69e947db6c178d821c27e51fc1e61a90ce82  fix: preserve applicability in active world investigator
```

只在 active world-aware caller 的 native probe 返回后显式调用同一个 read-only hook。

该提交 diff 已核对为：

```text
agent/kernel/world_closed_loop.py  +1 / -0
```

没有误写整文件。

## 测试 / CI 真实结果

新增：

```text
tests/agent/kernel/test_procedural_applicability.py
tests/agent/kernel/test_procedural_applicability_contract.py
```

覆盖：

- matching task context without current observation => `untested`；
- observed matching stable target => `supported`；
- other observed target => `mismatch`；
- generalized candidate without stable reality anchor => `untested`；
- inhibited candidate cannot qualify；
- command candidate requires observed repo root；
- matching repo root without complete current verification contract => `untested`；
- serialized evaluation excludes raw workdir/path/command/action command；
- real resident first creates one L2 candidate from two independently verified writes；
- third comparable event reaches path reality observation before any Body mutation and exposes supported applicability；
- supported applicability does not create `native_action_result` and Thought remains on existing `investigate` stage/action；
- `Investigation.facts` does not contain derived applicability；
- Situation applicability serialization excludes private temp path/content/task；
- restart reconstructs same supported applicability from durable evidence without moving Body。

### CI failure history — 不要抹掉

第一轮 final-candidate SHA `ad415dc897c7f3d5bbbaab6d8201a4ce660e4a1a`：

```text
run 32641858655
Electron / TypeScript  success
ZN Kernel / Python      failure
```

唯一失败来自 integration test 错误假设“固定两次 `live_once()` 后一定已经完成 path probe”。产品 evaluator unit boundaries 都通过。

改为等待真实 path observation 后，SHA `8d26a458a05ad17f0f4df003f732164d9cd21c11`：

```text
run 32642032803
Electron / TypeScript  success
ZN Kernel / Python      failure
```

这次 path facts 已真实存在，但 Investigation note 仍缺失，证明不是 timing 问题。

诊断 SHA `f876eb5641c82f3cab79c5ba2b7f0e5deb55dbc6` 在同一真实时刻直接将 candidate + readiness + intent + facts 喂 evaluator，证明 evaluator 返回 `supported`；因此问题收敛到 active caller hook。

修复 `WorldAwareEmbodiedInvestigator` 后最终 code/test SHA：

```text
202b69e947db6c178d821c27e51fc1e61a90ce82
ZN Kernel / Python      success
Electron / TypeScript  success
run                     32642408966
```

这是当前代码验证权威。

## L3 ownership boundary — 不要回退

当前仍然没有 candidate-to-action authority：

```text
ProceduralApplicabilityEvaluation
-X-> raw command replay
-X-> direct NativeBody action
-X-> CapabilityRegistry / PromotedCapabilityLoader promotion
-X-> PersistentNervousSystem.activate as action authority
-X-> direct override of _deliberation_step chosen action
```

`CognitiveSituation` / Thought 知道 `supported` 并不等于“执行它”。

现有 `PersistentNervousSystem` / `SchemaReconsolidator` 是 general associative prediction/reconsolidation substrate，不等于 executable skill。不要把 neural familiarity 偷换成 action eligibility。

## 当前没有实现、不得误报

仍 PARTIAL / MISSING：

- L3 candidate influence on resident native action selection/deliberation；
- mature/procedural resident-owned skill state；
- procedural fast path；
- prediction-error interrupt/deproceduralization of an actually activated procedural route；
- stronger alternative-action recovery as a learned consumer；
- learned engineering competence；
- learned computer-use competence；
- growth benchmarks proving familiar work reduces external cognition while preserving verification quality；
- practical Git mutation + diff/test/reality verification；
- GitHub repo/PR/CI resident-owned sense；
- browser Body/Sense seam；
- SM1+ self-maintenance implementation。

Do not describe read-only L3 `supported` as a mature skill or as an activated procedure。

## 下一真实目标

Fresh restore 后做最小 **bounded low-risk L3 action-influence slice**。

推荐边界：

1. 重新读取六份必读文档、remote HEAD、PR、CI、最近提交；
2. 重新追 `_deliberation_step` / `derive_native_action_intent()` / current Situation applicability active call chain；
3. 只允许 `supported` 且 non-inhibited candidate 产生正向 bias；
4. `mismatch` / `untested` 必须产生零 positive influence；
5. candidate 不得提供 raw command/args/path/content/model text；
6. influence 只能作用于**已经由 ZN 当前结构化 action formation 合法生成的候选动作形状**；
7. 第一 slice 不做 raw replay、不做 SKILL.md generation、不做 automatic capability promotion；
8. independent post-action verification 永远保留；熟练度不能降低真值要求；
9. candidate contradiction / prediction error 必须能够立即撤销 influence 并回 Investigation；
10. high-risk identity/long-term-memory/credentials/updater/rollback/signing/self-maintenance permissions 仍保留人工批准，不因 maturity 绕过。

第一个 concrete learning consumer 仍建议：

```text
A fails
→ genuinely different B succeeds
→ B independently verified
→ later comparable current reality supports B-pattern
→ supported candidate may bias existing structured choice toward B
→ still independently verify outcome
```

不要把它实现成 hardcoded A/B tactic rule。

## 风险

- current domain comparison 是保守 exact-match；后续泛化需要真实 benchmark，不要先放宽；
- generalized target/workdir candidate 当前 fail closed；这是刻意的，不是 bug；
- candidate retrieval / applicability 每个 Situation pulse 都是 bounded derivation，第一 slice 可接受；若以后性能成为事实问题再 profile，不要先建第二个 mutable cache；
- active caller hierarchy 中存在 world-aware overrides，后续改 owner 方法必须继续追最终 runtime 的真实 override；
- `Investigation.facts` 是 L1 reality evidence substrate，不要塞 derived learning judgement；
- 不把外部模型、Hermes Curator、skill-manager 重新变成 procedural owner；
- no one-shot skill creation；
- no embedding similarity as action authority；
- `main` 不动；
- M8 updater/signing/multi-OS release debt 仍存在，但当前不是 core-learning 主线。

## 阻塞

当前无已知代码阻塞。

环境限制：没有本地 private checkout / `gh`，因此依赖 GitHub connector + Actions 做真实 repo/CI 验证。

## 文档状态

本阶段更新：

- `docs/ZN-IMPLEMENTATION-STATUS.md`
- `.agent/HANDOFF.md`

本阶段未更新：

- `ZN.md`：架构方向没有变化；实现了既定 L3 read-only slice；
- `AGENTS.md`：无规则变化；
- `docs/ZN-SOURCE-EXTRACTION.md`：没有新 Hermes extraction；
- `docs/ZN-SELF-MAINTENANCE.md`：没有 self-maintenance architecture 变化。

## 下一维护者开始前

不要根据本文件直接假设现场未变化。必须重新：

1. 读六份必读文档；
2. 查 `dev/zn-agent` 精确 HEAD；
3. 查 diff / PR / CI / recent commits；
4. 查最终 runtime active caller；
5. 以代码 + Git + CI 为准对账本 HANDOFF。
