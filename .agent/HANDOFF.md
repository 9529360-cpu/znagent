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

L1/P0 的第一片 `VerifiedExperience` 已完成并经过真实主 CI。当前下一真实实现目标是：**repeated verified experience → candidate procedural tendency 的最小透明聚合层**。

```text
repeated compatible VerifiedExperience
→ bounded retrieval / aggregation
→ candidate procedural tendency
→ current-reality applicability
→ support / contradiction / maturity / inhibition
```

此前的 stronger alternative-action recovery 不删除；它将作为 learning architecture 的早期 consumer，而不是孤立 tactic generator。

纯 UI/desktop polish 继续暂停。M8/release 保留为 bounded lane。

## 当前分支 / HEAD

- 分支：`dev/zn-agent`
- 最新真实 code/test SHA：`80292975264df35ff3a999ed32c7973cdd3514f5`
- real code CI：run `32639405457`，`ZN Kernel / Python = success`，`Electron / TypeScript = success`
- H-L1 extraction/status docs：`5151f120f7ab621296bc3ae04a4bb15f839af639`
- implementation-status：`564dbc0282186fb119ddba7db5362a12f9630990`
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
- 当前 provider bridge → world-aware transfer resident → `EmbodiedResidentRuntime` → Body → Verification call chain
- packaged Python mapping：`runtime/python/pyproject.toml` 的 `zn_agent.core` 直接指向 `../../agent/kernel`

本轮开始前远程 `dev/zn-agent` HEAD：

```text
d9f51bd3aae4810af57f0fa9d134e82c2f89e03e
```

当时 Open PR：无。

当前执行环境无 private-repo checkout，因此不宣称 full local repo tests。真实 code CI 以 GitHub 为准；本轮 isolated pure-module smoke/`py_compile` 仅作为补充。

## 当前真实 learning attachment points

### Verification 已经成为可信 learning label

`EmbodiedResidentRuntime` 当前真实路径：

```text
Situation / Investigation
→ NativeActionIntent
→ BodyActionResult
→ expected postcondition when available
→ later independent Body observation
→ native_verification_result
→ VerifiedExperience
→ verified / contradicted
```

以下不能直接当 success learning label：

```text
model text
body return success
shell exit 0 without task-level postcondition
```

L1 现在把这个边界做成了实际持久化约束，而不再只是设计要求。

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

External cognition success 也能 stage 此 candidate。因此它可以作为 context，但不能直接当 mature skill，也不能替代新的 `VerifiedExperience` / future candidate tendency substrate。

## 本阶段已完成的 L1 first slice

### ZN-owned deterministic Body result semantics

新增：

```text
agent/kernel/result_semantics.py
```

关键提交：

```text
ee287a41873eb9340406aa95a56961b42127296c  feat: add deterministic body result semantics
20a3ffa9236e9de4279ef64e766d02f8cdce5988  fix: treat known swallowed failures as masked success
```

实现：

- bounded deterministic result/failure categories；
- timeout / exit 126 / exit 137 / nonzero exit 等语义；
- command-not-found / module-not-found / permission-denied / merge-conflict / rate-limit 等已知失败类别；
- observation-only vs potentially side-effecting feature；
- conservative masked-success detection for passthrough pipelines and `||` fallback swallowing；
- raw command/output 不进入 normalized learning features。

### Bounded restart-safe `VerifiedExperience`

新增：

```text
agent/kernel/verified_experience.py
```

关键提交：

```text
1130148205471a14c964cc080ea481d6f72c3a93  feat: add bounded verified experience store
474f636cd8dedeeb23c5997ad45e07a7d224136f  fix: fingerprint capability domains in learned episodes
```

当前 causal record 保存：

- experience/event/provenance ID；
- stable Situation/Investigation evidence fingerprint；
- goal/gap fingerprints；
- privacy-safe domain fingerprints；
- action kind + action signature hash；
- privacy-safe expected-outcome summary；
- normalized primary Body result features；
- independent verification features；
- `verified` / `contradicted` verdict；
- grouping key / timestamp。

禁止持久化：raw task/gap、raw command、verification command、path/workdir、Body output、expected output fragments、caller-supplied capability labels。

Store 与 kernel 共用同一 SQLite lifecycle，但有独立 `verified_experiences` 窄表；默认上限 2048；deterministic dedupe；restart-safe；retention 先保 contradiction，再保 representative groups，再补 recency。

`native_action_failure_records` 继续只是 execution anti-replay state，不允许偷偷变成长时 learning store。

### Shared embodied verification integration

修改：

```text
agent/kernel/embodied_resident.py
```

关键提交：

```text
b04a35356181abb86eb228cc7f963ebd01ca1653  feat: record independently verified resident experience
```

真实 ownership：

```text
provider bridge
→ WorldAwareTransferResidentRuntime
→ existing EmbodiedResidentRuntime
→ _native_action_step
→ durable native_verification
→ _native_verification_step
→ independent Body observation
→ VerifiedExperienceStore
```

没有新增 planner/manager/final-runtime shim。整文件 connector 更新后 compare 显示 `embodied_resident.py` 相对基线只有 `+70 / -0`。

Verification command 如果 shell exit 0 但输出存在 deterministic upstream failure，会被判 contradiction，不会 positive-learn。

### Tests

新增：

```text
tests/agent/kernel/test_verified_experience.py
```

最终测试 SHA：

```text
80292975264df35ff3a999ed32c7973cdd3514f5
```

覆盖：

- real write → independent read → verified experience；
- restart retrieval；
- contradicted postcondition → negative experience；
- Body success / naked exit 0 without postcondition → no experience；
- model/report-only success without independent observation → no experience；
- masked pipeline / fallback / command-not-found swallowed failure；
- read-only pipeline conservative non-match；
- privacy boundary including private capability labels；
- bounded retention + contradiction preservation。

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
5151f120f7ab621296bc3ae04a4bb15f839af639
```

Extraction ledger：

```text
E11 mine inherited learning/procedural mechanisms
→ SOURCE AUDIT COMPLETE
→ H-L1 first extraction active in ZN
```

### H-L1 — terminal failure/result semantics

Sources：

```text
tools/terminal_hints.py
agent/tool_result_classification.py
```

状态：**FIRST SLICE EXTRACTED INTO ZN / CI VERIFIED**。

已 source-adapt：

- bounded deterministic output-pattern failure classification；
- exit 126/124/137 semantics；
- merge conflict / command-not-found / module-not-found / rate-limit / permission-denied features；
- masked-success detection：`cmd | tail` / `cmd || echo` 虽 exit=0，但输出已证明真正命令失败；
- no-effect/observation-only vs potentially side-effecting result classification。

没有抽入 Hermes recovery prose/hint authority、tool controller、agent loop、MemoryManager 或 SKILL.md ownership。

重要来源事实仍保留：Hermes `terminal_hints.py` 注释说明这些模式来自约 250k terminal-result production window，其中约 14k failed calls 被覆盖，平均 retry chain 约多 1.4 tool turns。

这些只是 pre-existing engineering prior；当前现实验证才是事实。

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

Future only：可以给用户展示 “ZN 学会了什么”、skill-memory relations、usage/state、archive/restore、model/tool/skill cost metrics；不是当前 critical path。

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

## 当前没有实现、不得误报

仍 PARTIAL / MISSING：

- repeated verified experience → candidate procedural tendency aggregation；
- replay/retrieval scoring beyond the current bounded episode store；
- candidate maturity/reliability/applicability/inhibition state；
- resident-owned mature skill activation；
- procedural fast path；
- drift-triggered de-proceduralization/relearning；
- DAgger student training loop；
- River/ADWIN prototype；
- computer-use learned skill；
- engineering learned skill；
- retention/forgetting/model-removal benchmarks。

L1 first causal `VerifiedExperience` and the narrow H-L1 result helper are implemented; do not regress docs back to “source quarry only”。

## 真实 CI 基线

Final code/test SHA：

```text
80292975264df35ff3a999ed32c7973cdd3514f5
```

Real CI：

```text
ZN Kernel / Python      success
Electron / TypeScript  success
run                     32639405457
```

后续只有 `[skip ci]` docs/status updates，没有 runtime/test code 变更，因此这些 docs-only HEAD 不宣称有新 code CI。

## 下一真实目标

Fresh-restore 后实现 repeated verified experience 的最小透明聚合层：

```text
VerifiedExperienceStore
→ bounded compatible-group retrieval
→ support + contradiction evidence
→ candidate procedural tendency
→ current-reality applicability
→ maturity / inhibition state
```

第一 code slice 优先顺序：

1. 追 `VerifiedExperienceStore` / `group_key` / current Situation evidence 的真实调用链；
2. 设计 ZN-owned bounded aggregation/retrieval contract，不恢复 raw private payload；
3. repeated compatible verified episodes 才能形成 candidate；one-shot success 不能；
4. candidate 保存 support count、contradiction count、last verified、maturity/applicability/inhibited 等透明状态；
5. current reality/evidence 不兼容时不能 fast-path；
6. contradiction 必须降低/抑制 candidate，而不是被 recency 覆盖；
7. restart + bound + privacy tests；
8. model text / one-shot success cannot create candidate；
9. CI green 后再把 A fail → genuinely different B verified success 接成 alternative-action learning consumer；
10. 不要直接生成 SKILL.md，不要引入 LLM planner/curator，不要把 candidate 直接放进 `PromotedCapabilityLoader`。

之后再进入 maturity/prediction reliability、local activation、inhibition/relearning 和 promotion gates。

## 风险 / 安全 / release boundary

- 不做 one-shot skill creation；
- 不把 teacher/model 当 truth owner；
- 不把 embedding retrieval 伪装成 procedural competence；
- `native_action_failure_records` 与 `verified_experiences` 保持 execution-vs-learning 分工；
- 不为了 future retrieval 把 task/path/command/output/private domain 原样塞回 learning store；
- masked-success patterns 只是保守 deterministic evidence，不能脱离当前现实变成绝对真理；
- 不把 absolute mouse-coordinate replay 当 reflex；
- high-risk identity/memory/credentials/updater/rollback/signing/self-maintenance permissions 不因熟练化而绕过人工批准；
- 不引入重型 ML runtime dependency，除非 benchmark 证明价值并验证多平台 packaging；
- 不把 Hermes source quarry 变成 active control plane；
- `main` untouched；
- M8/release debt 保留为 bounded lane。

## 文档状态

本阶段更新：

- `docs/ZN-SOURCE-EXTRACTION.md`：H-L1 first slice extracted / CI verified；
- `docs/ZN-IMPLEMENTATION-STATUS.md`：L1 first causal episode implemented，下一步前移到 repeated aggregation/candidate tendency；
- `.agent/HANDOFF.md`：当前目标、CI、风险、下一步已同步。

本阶段没有 architecture direction change，因此没有为了形式修改：

- `ZN.md`；
- `docs/ZN-SELF-MAINTENANCE.md`；
- `AGENTS.md`；
- `main`。

注意：`ZN.md` 较早章节仍有历史性的 M8 “current priority”措辞，但后部最新 learning section、Implementation Status 和本 HANDOFF 已明确当前 learning mainline。下次触碰 architecture status 时可清理该陈旧措辞；不得据此把主线倒退回 M8。
