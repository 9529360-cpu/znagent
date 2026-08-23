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

当前下一真实实现目标仍是：**L1/P0 verified experience record**。

```text
current Situation / stable evidence
+ goal / current gap
+ concrete action
+ expected outcome
+ independently observed verification result
+ verified / contradicted verdict
→ bounded resident-owned learning unit
```

此前的 stronger alternative-action recovery 不删除；它将作为 learning architecture 的早期 consumer，而不是孤立 tactic generator。

纯 UI/desktop polish 继续暂停。M8/release 保留为 bounded lane。

## 当前分支 / HEAD

- 分支：`dev/zn-agent`
- 最新真实 code/test SHA：`23ce3b42aad2d730afae4d60eb6af5d5b4bd1399`
- architecture direction：`08f5bfba3ea7e4669170dd9008cefc6b3fe6573c`
- memory/learning architecture：`5977465d9c7560828c14a22a2bc4f5844c7ed8f3`
- next-phase alignment：`cfaa9fc738cd4cfbc65d02de336e256ce0647ee7`
- implementation-status：`8650489035f04b775a6bf508ee7a8cf415840429`
- external learning/source research：`6196e114f590475da8494aee994e737d19896c92`
- memory/learning research integration：`0f08f5de3d59cd426ba8dfb6744155f18635dcc6`
- 本 HANDOFF 为 docs-only `[skip ci]`；下一维护者必须重新读取远程最终 HEAD。
- `main` 未修改。

## 本阶段恢复并核对的真实现场

已重新读取/检查：

- `ZN.md`
- `AGENTS.md`
- `docs/ZN-IMPLEMENTATION-STATUS.md`
- `docs/ZN-SOURCE-EXTRACTION.md`
- `docs/ZN-SELF-MAINTENANCE.md`
- `docs/ZN-MEMORY-LEARNING.md`
- `.agent/HANDOFF.md`
- `dev/zn-agent` HEAD / diff / open PR / CI
- `agent/kernel/memory.py`
- `agent/kernel/nervous_system.py`
- `agent/kernel/reconsolidation.py`
- `agent/kernel/capabilities.py`
- `agent/kernel/capability_loader.py`
- `agent/kernel/evolution.py`
- `agent/kernel/models.py`
- `agent/kernel/life.py`
- `agent/kernel/resident.py`
- `agent/kernel/embodied_resident.py`
- current Investigation → Action → Body → Verification → completion/failure call chain

本轮研究开始前远程 HEAD：

```text
71766731b2432d570d399dad1d1b3a05892f6df7
```

开始时 compare 确认 branch 与该 HEAD identical。Open PR：无。

当前执行环境无 private-repo checkout，因此不宣称本地 tests。真实 code CI 以 GitHub 为准。

## 当前真实 learning attachment points

### Verification 已经提供可信 learning label

`EmbodiedResidentRuntime` 当前真实路径：

```text
Situation / Investigation
→ NativeActionIntent
→ BodyActionResult
→ expected postcondition when available
→ later independent Body observation
→ native_verification_result
→ verified / contradicted
```

这应成为 L1 positive/negative learning evidence 的事实来源。

禁止把以下直接当 success learning label：

```text
model text
body return success
shell exit 0 without task-level postcondition
```

### Nervous system 已经有 association + reconsolidation foundation

当前代码已经有：

- persistent traces；
- repeated-trace strengthening；
- associative links/spreading activation；
- consolidation/schema；
- fading/pruning；
- prediction/reality comparison；
- support/refinement/contradiction；
- prediction-error-driven reconsolidation。

因此不要再引入一个 LLM-memory product 来拥有这部分。

### Capability boundary 已经可承接未来 procedural competence

`CallableCapability` 是 deterministic zero-token local capability，而且源码注释已明确 future learned procedures can be compiled into capabilities。

`PromotedCapabilityLoader` 已经规定：candidate/self-generated code 不能直接进入 live promoted capabilities；必须先 tests / benchmarks / promotion / rollback。

未来 procedural learning 应尽量复用这个 boundary，而不是再造第二套 executable-skill runtime。

### 当前 `LearningCandidate` 不等于 verified procedural evidence

`life.py` 的 `LearningCandidate` 目前只是 resolved impasse summary：task + resolution source/summary + required capabilities。

External cognition success 也能 stage 此 candidate。因此它可以作为 context，但不能直接当 mature skill 或 L1 verified experience。

## 本阶段外部研究：已拖回仓库

新建：

```text
docs/ZN-LEARNING-SOURCE-RESEARCH.md
6196e114f590475da8494aee994e737d19896c92
```

并把结论集成进：

```text
docs/ZN-MEMORY-LEARNING.md
0f08f5de3d59cd426ba8dfb6744155f18635dcc6
```

### 选中的成熟思想 / 组件方向

```text
Complementary Learning Systems / fast-slow learning
→ ADOPT DESIGN PRINCIPLE
→ fast verified episodes + slower consolidation/competence

Experience Replay
→ ADOPT MECHANISM
→ bounded representative verified replay; resident-native first

DAgger / imitation learning
→ PROTOTYPE
→ model/human as teacher, ZN as student; reality verification is final label

River / ADWIN
→ PROTOTYPE
→ lightweight online adaptation + stale-skill/drift detection

Avalanche / Mammoth
→ RESEARCH HARNESS
→ continual-learning baselines/forgetting metrics; not production runtime

EWC / DER / SI / GEM / Progress & Compress
→ LATER ALGORITHM OPTIONS
→ only when actual local neural skill models and forgetting exist

Voyager
→ SOURCE QUARRY
→ borrow reusable-skill/environment-feedback ideas; reject GPT-owned control loop

DreamerV3 / world-model RL
→ LATER RESEARCH
→ prediction-backed bounded skill domains; do not replace Situation/Thought/Will

Nested Learning
→ RESEARCH LENS
→ multiple update time-scales

BrowserGym
→ FUTURE DEV BENCHMARK
→ reproducible browser learning/training/evaluation

OSWorld V2
→ FUTURE DEV BENCHMARK
→ long-horizon desktop/computer-use evaluation
```

No external framework has been added to the ZN runtime.

## Proposed learning ownership stack

```text
Body/Senses current reality
→ Situation / Investigation
→ action + expected outcome
→ independent verification
→ VerifiedExperience                    fast
→ bounded replay
→ PersistentNervousSystem / schema
→ CandidateProcedure                    slower
→ reality-gated repeated practice
→ maturity / reliability / drift
→ resident-owned procedural capability
→ familiar fast path
→ prediction + reality check
→ reinforce OR inhibit/relearn
```

External cognition remains outside as teacher/adviser:

```text
novel/uncertain gap
→ model/human suggestion
→ ZN evaluates/acts
→ reality verification
→ only verified experience changes competence
```

## L1 implementation decision after research

Do **not** install Avalanche/Mammoth/PyTorch/River/etc. merely to start learning.

First implementation remains resident-native `VerifiedExperience` with bounded storage and deterministic retention.

Initial record should include, privacy-safe where possible:

- experience ID；
- event/provenance ID；
- source/teacher involvement (`native`, `external-cognition-assisted`, `human-assisted` etc.)；
- Situation / Investigation evidence fingerprint；
- domains / task-gap class；
- action signature + kind；
- expected-outcome summary；
- verification summary；
- verdict (`verified` / `contradicted`; uncertainty later when supported)；
- timestamps/provenance；
- safe grouping features。

Do not store unnecessary model transcript, credentials, private content, full command/content payloads.

`native_action_failure_records` remains execution anti-replay state. L1 may distill evidence from it but must not silently repurpose it as long-term memory.

### First bounded replay/retention policy

Start inspectable:

```text
per context/skill family:
  keep recent contradictions
  keep representative verified successes
  keep limited rare/novel cases

global hard bound
+ deterministic pruning
+ provenance preserved
```

Later compare on the same real stream:

1. resident-native transparent reliability aggregation；
2. River/ADWIN online adaptation/drift；
3. DAgger-style local student in a bounded benchmark environment；
4. only if measurable neural forgetting exists: replay/EWC/DER/etc. research baselines。

## 当前没有实现、不得误报

仍 PARTIAL / MISSING：

- first-class causal `VerifiedExperience`；
- replay store/retention implementation；
- repeated verified experience → `CandidateProcedure`；
- maturity/reliability/inhibition state；
- resident-owned mature skill activation；
- procedural fast path；
- drift-triggered de-proceduralization/relearning；
- DAgger student training loop；
- River/ADWIN prototype；
- computer-use learned skill；
- engineering learned skill；
- retention/forgetting/model-removal benchmarks。

Do not call current `NeuralTrace`, schema, or old `LearningCandidate` complete procedural memory.

## 真实 CI 基线

Final code/test SHA：

```text
23ce3b42aad2d730afae4d60eb6af5d5b4bd1399
```

Real CI：

```text
ZN Kernel / Python      success
Electron / TypeScript  success
run                     32635668910
```

本轮新增只有 `[skip ci]` research/docs，没有 runtime/test code 变更，因此没有新增 code CI，也不宣称有。

## 下一真实目标

Fresh-restore 后实现 L1：

```text
verified/contradicted native action outcome
→ privacy-safe VerifiedExperience
→ durable bounded store
→ restart-safe retrieval
→ provenance / evidence fingerprint
→ deterministic retention
```

必须测试：

- independent verification success 才能产生 positive learning evidence；
- model text alone 不能产生 positive experience；
- body/shell success alone 不能冒充 verified task outcome；
- contradiction 也进入 learning evidence；
- restart survives；
- bounded retention；
- secret/private payload 不被宽泛复制；
- no planner/task manager；
- no direct candidate-code promotion。

L1 有真实数据后，再进入 L2 transparent resident-native aggregation，并与 River/ADWIN prototype 做测量比较。

## 风险 / 安全 / release boundary

- 不做 one-shot skill creation；
- 不把 teacher/model 当 truth owner；
- 不把 embedding retrieval 伪装成 procedural competence；
- 不把 absolute mouse-coordinate replay 当 reflex；
- high-risk identity/memory/credentials/updater/rollback/signing/self-maintenance permissions 不因熟练化而绕过人工批准；
- 不引入重型 ML runtime dependency，除非实际 benchmark 证明价值并验证多平台 packaging；
- `main` untouched；
- M8/release debt 保留为 bounded lane。

## 文档状态

本阶段新增/更新：

- `docs/ZN-LEARNING-SOURCE-RESEARCH.md`（new）；
- `docs/ZN-MEMORY-LEARNING.md`；
- `.agent/HANDOFF.md`。

本阶段未改变：

- `ZN.md` architecture direction（上一阶段已经先定义）；
- `docs/ZN-IMPLEMENTATION-STATUS.md`：没有 runtime implementation 状态变化；
- `docs/ZN-SOURCE-EXTRACTION.md`：Hermes extraction 状态未变化；
- `docs/ZN-SELF-MAINTENANCE.md`：self-maintenance 架构未变化；
- `AGENTS.md`；
- `main`。
