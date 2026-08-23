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

核心产品原则：

> **Models may help ZN learn. Mature capability must belong to ZN.**

ZN 不是 `LLM -> planner -> tools -> agent`。外部模型可以作为 teacher/adviser，但不能长期拥有 ZN 的任务连续性、动作权、真值判断或已经学会的能力。

L1/P0 `VerifiedExperience` 与 L2 第一片 transparent candidate aggregation 已完成并经过真实主 CI。当前下一真实实现目标是：**L3 current-reality applicability evaluator**。

```text
CandidateProceduralTendency
+ current Situation / Investigation facts
→ supported / mismatch / untested applicability
→ Thought/Investigation evidence only
→ later reality-gated action influence
```

当前 candidate 即使状态为 `practiced` 也没有 Body 权限。不要跳过 L3 直接接 `_deliberation_step`、capability loader 或 nervous `activate()`。

stronger alternative-action recovery 不删除；它继续作为 learning architecture 的早期 consumer，而不是孤立 tactic generator。

纯 UI/desktop polish 继续暂停。M8/release 保留为 bounded parallel lane。

## 当前分支 / HEAD

- 分支：`dev/zn-agent`
- 最后一个真实 code/test SHA：`25ff0ada9efc8e8d830d085856edca7ea772a696`
- real code CI：run `32640409344`
  - `ZN Kernel / Python = success`
  - `Electron / TypeScript = success`
- implementation-status docs：`f3f1858267bf49b8b24dc8d46b04422776c0096e` (`[skip ci]`)
- 本 HANDOFF 提交本身为 docs-only `[skip ci]`；它会成为新的远程 HEAD，因此下一维护者必须重新读取远程 `dev/zn-agent` 精确 HEAD。
- `main` 未修改。

## 本阶段恢复并核对的真实现场

本阶段开始时重新读取/检查：

- `ZN.md`
- `AGENTS.md`
- `docs/ZN-IMPLEMENTATION-STATUS.md`
- `docs/ZN-SOURCE-EXTRACTION.md`
- `docs/ZN-SELF-MAINTENANCE.md`
- `.agent/HANDOFF.md`
- `dev/zn-agent` HEAD / recent commits / open PR / CI
- `VerifiedExperienceStore` / embodied verification / nervous reconsolidation / provider bridge / packaged Python mapping

本阶段开始时远程 `dev/zn-agent` 精确 HEAD：

```text
e24fef1574c46c211be63d5816a97559e797ee31
```

compare 当时为 identical；Open PR：无；最后 code SHA `80292975264df35ff3a999ed32c7973cdd3514f5` 的旧 CI 仍双绿。

当前执行环境无 private-repo checkout、无 `gh` CLI，因此不宣称 full local repo tests。真实代码验证以 GitHub CI 为权威。

## 当前真实 learning call chain

### L1 causal evidence owner

```text
provider bridge
→ WorldAwareTransferResidentRuntime
→ existing EmbodiedResidentRuntime
→ Investigation / NativeActionIntent
→ BodyActionResult
→ durable native_verification
→ independent Body observation
→ VerifiedExperience
→ VerifiedExperienceStore
```

可信正/负 learning label 来自 independent verification，而不是：

```text
model text
Body return success
naked shell exit 0
```

### L2 candidate owner

新增：

```text
agent/kernel/procedural_tendency.py
```

当前路径：

```text
VerifiedExperienceStore.candidate_tendencies()
→ scan retained bounded causal episodes
→ aggregate compatible privacy-safe groups
→ CandidateProceduralTendency
```

没有新 runtime shim。active product constructor 仍是原来的 `WorldAwareTransferResidentRuntime` chain。

Candidate 目前只是 derived resident-owned view，不是第二个 mutable skill database；restart 后从同一 L1 persistent evidence 重建相同 ID/state。

## 本阶段完成：L2 first transparent candidate slice

### 1. Candidate data model / aggregation

关键提交：

```text
3f00dbc884a899626fba7d32c6f2130a0f11ce0d  feat: derive candidate procedural tendencies
```

`CandidateProceduralTendency` 当前保存：

- deterministic tendency ID；
- privacy-safe compatibility/group key；
- action kind；
- domain fingerprints；
- expected-result kind / expected exit；
- effect/failure class；
- support count；
- contradiction count；
- distinct event count；
- native vs assisted support counts；
- transparent reliability ratio；
- candidate-level maturity state；
- inhibited flag；
- bounded privacy-safe applicability profile；
- bounded recent verdicts / supporting and contradicting experience IDs；
- first/last seen time。

Hard boundary：

- one verified event => no candidate；
- duplicate same-event records => cannot fake repetition；
- minimum two distinct independently verified events required；
- raw command/content/path/task/model text/caller capability label are not copied；
- no executable handler/args/callable is stored；
- candidate states are only transparent L2 states: `candidate`, `supported`, `practiced`, `contested`, `inhibited`；
- no state is called mature/procedural yet。

### 2. Bounded retrieval

关键提交：

```text
3c989a077152a5c28757ff1891fb393ebe0d10bb  feat: expose bounded procedural candidate retrieval
```

`VerifiedExperienceStore.candidate_tendencies()` scans the already-bounded retained L1 evidence rather than only the default recent 100 rows, so an older repeated pattern does not vanish merely because unrelated recent episodes exist.

This is retrieval/aggregation only. It does not modify Thought or action choice.

### 3. Retention repaired for L2 continuity

静态审查发现 L1 旧 retention 在容量压力下只保证 per-group singleton representative，可能把已经拥有两次独立 support 的 L2 candidate 削回单例。

修复提交：

```text
f0f5ba49d3d4b9a152a05e9d3e0f056667351162  fix: retain repeated support for procedural candidates
```

新 retention 顺序：

1. reserve bounded recent contradiction evidence；
2. when capacity permits, preserve two distinct verified events for already-repeated groups；
3. preserve one verified representative for other groups；
4. fill remaining capacity by recency。

Same-event duplicate does not satisfy the two-event retention pair。

### 4. Tests

新增：

```text
tests/agent/kernel/test_procedural_tendency.py
```

最终测试提交：

```text
25ff0ada9efc8e8d830d085856edca7ea772a696  test: preserve candidate support under retention
```

覆盖：

- one-shot verified success cannot create candidate；
- same-event duplicate cannot create candidate；
- two distinct verified events create one non-executable candidate；
- three supports progress to `supported` baseline；
- four supports progress to `practiced` baseline；
- contradiction produces `contested`；
- repeated/recent contradiction can produce `inhibited`；
- incompatible group/action does not merge；
- candidate evidence references/recent verdicts are bounded；
- bounded L1 retention preserves existing two-event candidate support + contradiction under pressure；
- real resident two separate write→independent-read events form one candidate；
- candidate serialization excludes private task/content/path/domain strings；
- restart reconstructs same candidate ID/support/state。

真实主 CI：

```text
25ff0ada9efc8e8d830d085856edca7ea772a696
ZN Kernel / Python      success
Electron / TypeScript  success
run                     32640409344
```

## L2/L3 ownership boundary — 不要回退

当前没有任何 candidate-to-action connection：

```text
CandidateProceduralTendency
-X-> EmbodiedResidentRuntime._deliberation_step
-X-> NativeBody
-X-> CapabilityRegistry / PromotedCapabilityLoader
-X-> PersistentNervousSystem.activate as action authority
```

这是故意的。

现有 `PersistentNervousSystem` / `SchemaReconsolidator` 已经有一般 associative pattern、support/refinement/contradiction、strength/confidence/reconsolidation semantics，但这些是 general lived prediction substrate，不等于 executable procedural skill。不要为了省代码把 neural familiarity 偷换成动作资格。

L3 必须显式问：

> 当前 Situation / Investigation facts 是否真的测试并支持这个 candidate 的 applicability？

如果当前证据没有测试它，结果应是 `untested`，不是默认匹配。

## 当前已有的 L1 / nervous / capability foundations

### L1 `VerifiedExperience`

关键旧提交：

```text
ee287a41873eb9340406aa95a56961b42127296c  deterministic result semantics
1130148205471a14c964cc080ea481d6f72c3a93  bounded verified experience store
b04a35356181abb86eb228cc7f963ebd01ca1653  record after independent verification
20a3ffa9236e9de4279ef64e766d02f8cdce5988  masked-success hardening
474f636cd8dedeeb23c5997ad45e07a7d224136f  capability-label privacy
80292975264df35ff3a999ed32c7973cdd3514f5  L1 final tests
```

L1 real CI：run `32639405457`, Python/Electron success。

### Nervous / reconsolidation

Current code already has：

- persistent neural traces；
- repeated-trace strengthening；
- associative links/spreading activation；
- consolidation/schema；
- fading/pruning；
- prediction/reality comparison；
- support/refinement/contradiction；
- prediction-error-driven reconsolidation。

继续把它当 general associative substrate，不要另装 LLM-memory product。

### Capability boundary

`CallableCapability` remains deterministic local capability shape。

`PromotedCapabilityLoader` remains the future stronger executable boundary：

```text
candidate/self-generated code
→ isolated tests/benchmarks
→ promotion decision
→ promoted capability
→ resident loading
```

L2 candidate 不得直接进入 loader。

### Existing `LearningCandidate`

`life.py` 旧 `LearningCandidate` 仍只是 resolved-impasse summary，external cognition success 也可以产生；它不是 `CandidateProceduralTendency`，不得混为一谈。

## Hermes / external research state retained

外部 learning research：

```text
docs/ZN-LEARNING-SOURCE-RESEARCH.md
6196e114f590475da8494aee994e737d19896c92
```

memory/learning integration：

```text
docs/ZN-MEMORY-LEARNING.md
0f08f5de3d59cd426ba8dfb6744155f18635dcc6
```

选中方向仍是 fast/slow learning、bounded replay、DAgger teacher/student、River/ADWIN drift、Avalanche/Mammoth research baselines、later world-model research、BrowserGym/OSWorld benchmark。

No external learning framework has been added to runtime。

Hermes source quarry 仍在 `docs/ZN-SOURCE-EXTRACTION.md`：

- H-L1 deterministic terminal/result semantics: first slice already source-adapted into ZN；
- H-L2 repeated/no-progress guardrails: selective future extraction；
- H-L3 skill telemetry/lifecycle: useful later for maturity/stale/inhibition/retirement mechanics, but do not import Curator owner；
- H-L4 ledger/rollback: future promoted-capability safety；
- H-L5 skill-manager safety only, reject `LLM writes SKILL.md -> procedural learning`；
- H-L6 observability later；
- H-L7 conventional memory only support-memory quarry；
- H-L8 browser substrate later behind ZN Body/Sense seam。

本阶段没有新增 Hermes extraction，因此 `docs/ZN-SOURCE-EXTRACTION.md` 没有形式性修改。

## 当前没有实现、不得误报

仍 PARTIAL / MISSING：

- L3 current-Situation applicability evaluator；
- candidate influence on resident Thought/deliberation；
- mature/procedural resident-owned skill state；
- procedural fast path；
- prediction-error interrupt of an actually activated procedural route；
- stronger alternative-action recovery as a learned consumer；
- DAgger student training loop；
- River/ADWIN prototype；
- learned computer-use competence；
- learned engineering competence；
- retention/forgetting/model-removal growth benchmarks；
- practical Git mutation + diff/test verification；
- GitHub repo/PR/CI resident-owned sense；
- browser Body/Sense seam；
- SM1+ self-maintenance implementation。

Do not describe L2 `practiced` as mature skill. It is still observational evidence aggregation with zero action authority。

## 下一真实目标

Fresh restore 后先实现 L3 的**只读 applicability evaluator**，不要一上来执行动作：

```text
CandidateProceduralTendency
+ current Investigation facts / Situation
→ compare privacy-safe applicability expectations
→ supported / mismatch / untested
→ bounded applicability evidence
→ Thought / Investigation visibility
```

第一 slice 建议顺序：

1. 重新追 `CognitiveSituation` / `EmbodiedInvestigator.facts` / `NativeActionIntent` 的当前真实结构；
2. 明确哪些 current evidence 可以与 candidate applicability 的 fingerprints/counts 做可靠 comparison；
3. evaluator 必须 fail closed：没有可测试证据 => `untested`；
4. mismatch/contradiction 必须降低或 inhibit candidate route，而不是“相似就算匹配”；
5. 先只把 evaluation 放进 Situation/Thought evidence，不改变动作；
6. restart/privacy/bound tests；
7. prove stale/other-target/current-context mismatch cannot qualify；
8. CI green 后才考虑让低风险 supported candidate **bias** existing ZN action formation；
9. 即使以后 influence action，也只能选择 ZN-owned structured action shape，不能 replay raw command/model text；
10. high-risk identity/memory/credentials/updater/rollback/signing/self-maintenance 权限永远不因 maturity 绕过批准。

之后再把 A fail → genuinely different B independently verified success 做成第一个 concrete learning consumer。

## 风险 / 安全 / release boundary

- 不做 one-shot skill creation；
- 不把 teacher/model 当 truth owner；
- 不把 embedding retrieval 伪装成 procedural competence；
- candidate 不是 action authority；
- nervous familiarity 不是 action authority；
- `native_action_failure_records` / `verified_experiences` / candidate derived view 保持 execution-vs-causal-learning-vs-procedural-aggregation 分工；
- 不为了 applicability 把 task/path/command/output/private domain 原样放回 broad memory；
- current reality must remain authoritative；
- high-risk operations do not become automatic through maturity；
- 不引入重型 ML runtime dependency，除非 benchmark 证明价值并验证多平台 packaging；
- 不把 Hermes source quarry 变成 active control plane；
- `main` untouched；
- M8/release debt 保留为 bounded parallel lane。

## 文档状态

本阶段更新：

- `docs/ZN-IMPLEMENTATION-STATUS.md`：L2 transparent aggregation/retrieval CI verified，下一目标前移到 L3 applicability；
- `.agent/HANDOFF.md`：当前 code SHA/CI/L2边界/下一目标已同步。

本阶段未改变 source extraction/self-maintenance/architecture direction，因此没有为了形式修改：

- `docs/ZN-SOURCE-EXTRACTION.md`；
- `docs/ZN-SELF-MAINTENANCE.md`；
- `ZN.md`；
- `AGENTS.md`；
- `main`。
