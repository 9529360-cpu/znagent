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
- Hermes learning/procedural source quarry：`fe40ecc0377d67871e4be4cfc579f3b8b73395aa`
- 本 HANDOFF 为 docs-only `[skip ci]`；下一维护者必须重新读取远程最终 HEAD。
- `main` 未修改。

## 本阶段恢复并核对的真实现场

已重新读取/检查：

- `ZN.md`
- `AGENTS.md`
- `docs/ZN-IMPLEMENTATION-STATUS.md`
- `docs/ZN-SOURCE-EXTRACTION.md`
- `docs/ZN-SELF-MAINTENANCE.md`
- `.agent/HANDOFF.md`
- `dev/zn-agent` HEAD / diff / open PR / CI
- 当前 Investigation → Action → Body → Verification call chain
- `main` inherited Hermes snapshot identity

本轮开始前远程 `dev/zn-agent` HEAD：

```text
bbf3f04d67fe8bbdb6c0f9d97e4f95479b43cd19
```

compare 确认 branch 与该 HEAD identical；Open PR：无。

`main` compare 确认仍 exactly：

```text
61dd880aa4bbbdb359ca544b752afc2c22845ce9
Initial commit: Hermes Agent source code
```

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

## 外部研究已经拖回仓库

```text
docs/ZN-LEARNING-SOURCE-RESEARCH.md
6196e114f590475da8494aee994e737d19896c92
```

并集成：

```text
docs/ZN-MEMORY-LEARNING.md
0f08f5de3d59cd426ba8dfb6744155f18635dcc6
```

选中的外部方向：fast/slow learning、bounded replay、DAgger teacher/student、River/ADWIN drift、Avalanche/Mammoth research baselines、later world-model research、BrowserGym/OSWorld benchmark。

No external framework has been added to the ZN runtime.

## 本阶段 Hermes learning/procedural source quarry

已更新：

```text
docs/ZN-SOURCE-EXTRACTION.md
fe40ecc0377d67871e4be4cfc579f3b8b73395aa
```

新增 extraction ledger：

```text
E11 mine inherited learning/procedural mechanisms
→ SOURCE AUDIT COMPLETE
→ bounded extraction candidates identified
```

### H-L1 — terminal failure/result semantics

Sources：

```text
tools/terminal_hints.py
agent/tool_result_classification.py
```

优先级：**NEAR-TERM / HIGH VALUE**。

可抽：

- bounded deterministic output-pattern failure classification；
- common Git/Python/environment recovery hints；
- exit 126/124/137 semantics；
- merge conflict / command-not-found / module-not-found / already-exists / rate-limit / permission-denied features；
- masked-success detection：`cmd | tail` / `cmd || echo` 虽 exit=0，但输出已证明真正命令失败；
- no-effect vs side-effecting operation classification；
- file mutation “result landed” checks。

重要事实：Hermes `terminal_hints.py` 注释说明这些模式来自约 250k terminal-result production window，其中约 14k failed calls 被覆盖，平均 retry chain 约多 1.4 tool turns。

这些可以成为 ZN 的 pre-existing engineering prior，减少模型老师成本；但 hint 仍只是 prior，当前现实验证才是事实。

### H-L2 — repeated/no-progress guardrails

Source：

```text
agent/tool_guardrails.py
```

优先级：**SELECTIVE EXTRACTION**。

可抽：canonical action signatures、exact failure counts、same-tool failure counts、no-progress detection、poller exemptions、runaway caps、identical-result stubs。

不要导入 inherited controller。ZN 已有更强的 evidence-bound blocked-action rule，只可把这些用作 evidence/features。

### H-L3 — skill telemetry + lifecycle

Sources：

```text
tools/skill_usage.py
agent/curator.py
```

优先级：**L2-L5 / VERY HIGH VALUE**。

成熟机制：

- authored procedure content 与 operational telemetry 分离；
- atomic/cross-process-safe usage sidecar；
- use/view/patch/post-patch-reuse telemetry；
- explicit management ownership/provenance；
- pin/protected/upstream-owned boundaries；
- deterministic active→stale→archived；
- stale reactivation；
- never-used grace period：absence of use != evidence of staleness；
- durable scheduled-work reference protection；
- autonomous archive recoverable，not hard delete；
- optional LLM consolidation OFF by default while deterministic lifecycle remains model-free。

ZN adaptation 必须用 verified support / contradiction / applicability / prediction reliability 驱动 skill maturity，而不是只按 use count/time。

### H-L4 — mutation ledger / rollback

Sources：

```text
tools/skill_ledger.py
agent/curator_backup.py
tools/skill_provenance.py
```

优先级：**VERY HIGH VALUE for promoted capabilities**。

可抽：

- actor/write-origin provenance；
- append-only JSONL mutation ledger；
- content-addressed SHA-256 before/after blobs，deduplicated；
- path containment validation；
- restore blobs pre-check；
- fail-closed pre-rollback safety capture；
- rollback itself reversible；
- whole-run snapshots；
- dependent scheduled references included in consistency rollback。

这应接到 ZN 已有 `PromotedCapabilityLoader` + self-maintenance approval，不允许 generated code 直接变 live skill。

### H-L5 — skill-manager safety mechanics

Source：

```text
tools/skill_manager_tool.py
```

可抽安全机制：path/symlink/junction delete defense、never delete root、pin/protected/upstream-owner boundaries、read-before-write、ownership-unverifiable fail closed。

明确拒绝：

```text
LLM writes SKILL.md
→ call this procedural learning
```

### H-L6 — learning observability

Sources：

```text
agent/learning_graph.py
agent/learning_mutations.py
agent/insights.py
```

Future only：可以给用户展示 “ZN 学会了什么”、skill-memory relations、usage/state、archive/restore、model/tool/skill cost metrics；不是 L1 critical path。

### H-L7 — conventional memory machinery

Sources：

```text
agent/memory_manager.py
agent/memory_provider.py
plugins/memory/query_rewrite.py
plugins/memory/*
```

只当 support-memory quarry。可借 lifecycle/failure isolation/async sync/prefetch/session hooks/trivial-query gates/strict rewrite validation/stream scrubber。

不能让：

```text
retrieve text → inject LLM → model owns memory/action
```

替代 ZN nervous/procedural memory。

### H-L8 — browser substrate

Sources：

```text
tools/browser_supervisor.py
selected tools/browser_tool.py mechanisms
```

Later：persistent CDP supervision、frame/OOPIF/dialog/console state、accessibility-tree/ref interaction、bounded snapshots、credential-scrubbed subprocess env、platform launch robustness。

必须 behind future ZN-owned browser Body/Sense seam；不得恢复 Hermes browser orchestration。

## 本阶段检查的 inherited test evidence

不是只看注释，已检查：

```text
tests/tools/test_skill_usage.py
tests/agent/test_curator.py
tests/tools/test_skill_ledger.py
tests/agent/test_tool_result_classification.py
```

重要边界测试包括：

- concurrent telemetry update 不丢计数；
- lifecycle event 只在真实 transition 后发出；
- post-patch reuse；
- corrupted telemetry recovery；
- bundled/hub/external ownership separation；
- pinned/protected capability survival；
- cron/durable-reference protection；
- unrelated stale capability still ages out；
- ledger content dedupe；
- rollback path escape rejection；
- missing blob abort before mutation；
- pre-rollback safety capture fail closed；
- delete/write-file exact recovery。

这些 edge cases 可以直接变成未来 ZN tests 的来源。

## L1 implementation decision after both surveys

Do **not** install Avalanche/Mammoth/PyTorch/River/etc. merely to start learning。

Do **not** import Hermes Curator/MemoryManager/SkillManager as control plane。

第一 implementation 仍是 resident-native `VerifiedExperience`。

但是 L1 现在应该优先 source-extract/adapt **非常窄的 deterministic Hermes outcome/failure semantics**：

```text
Body result
→ normalized result/effect features
→ masked-success / known-failure evidence where applicable
→ independent postcondition observation
→ VerifiedExperience
```

初始 record：

- experience ID；
- event/provenance ID；
- source/teacher involvement (`native`, `external-cognition-assisted`, `human-assisted` etc.)；
- Situation / Investigation evidence fingerprint；
- domains / task-gap class；
- action signature + kind；
- expected-outcome summary；
- normalized result/failure features；
- independent verification summary；
- verdict (`verified` / `contradicted`)；
- timestamps/provenance；
- privacy-safe grouping features。

禁止持久化 unnecessary model transcript、credentials、private content、full command/content payloads。

`native_action_failure_records` 仍是 execution anti-replay state，不能偷偷变成长期 learning store。

## 当前没有实现、不得误报

仍 PARTIAL / MISSING：

- first-class causal `VerifiedExperience`；
- extracted ZN-owned Hermes failure/result feature helper；
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

Documenting the Hermes quarry is not extraction and is not runtime completion。

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

本轮只有 `[skip ci]` docs/source-audit updates，没有 runtime/test code 变更，因此没有新增 code CI，也不宣称有。

## 下一真实目标

Fresh-restore 后实现 L1：

```text
current ZN Body/verification
+ narrow extracted/adapted deterministic Hermes result semantics
→ privacy-safe VerifiedExperience
→ durable bounded store
→ restart-safe retrieval
→ provenance / evidence fingerprint
→ deterministic retention
```

第一 code slice 的优先顺序：

1. 追 `BodyActionResult` / command verification 的当前真实数据结构；
2. 设计 ZN-owned normalized action-result feature helper，不 import inherited `tools.*`；
3. 只抽需要的 masked-success / known-failure semantics；
4. 建 `VerifiedExperience` schema/store；
5. 接 verified success + contradicted postcondition 两条路径；
6. tests：model text/body return/exit0 alone 都不能冒充 positive learning；
7. restart + bound + privacy tests；
8. CI green 后再更新 implementation status / HANDOFF。

L1 有真实数据后，进入 L2 transparent aggregation，并从 Hermes skill lifecycle 中吸收 maturity/stale/inhibit/retire 边界；再与 River/ADWIN prototype 做测量比较。

## 风险 / 安全 / release boundary

- 不做 one-shot skill creation；
- 不把 teacher/model 当 truth owner；
- 不把 embedding retrieval 伪装成 procedural competence；
- 不把 absolute mouse-coordinate replay 当 reflex；
- high-risk identity/memory/credentials/updater/rollback/signing/self-maintenance permissions 不因熟练化而绕过人工批准；
- 不引入重型 ML runtime dependency，除非 benchmark 证明价值并验证多平台 packaging；
- 不把 Hermes source quarry 变成 active control plane；
- `main` untouched；
- M8/release debt 保留为 bounded lane。

## 文档状态

本阶段更新：

- `docs/ZN-SOURCE-EXTRACTION.md`；
- `.agent/HANDOFF.md`。

本阶段未改变 runtime implementation，因此没有更新：

- `docs/ZN-IMPLEMENTATION-STATUS.md`；
- `ZN.md` architecture direction；
- `docs/ZN-SELF-MAINTENANCE.md`；
- `AGENTS.md`；
- `main`。
