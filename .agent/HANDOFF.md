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

L1/P0 的第一片 `VerifiedExperience` 已完成并经过真实主 CI。当前下一真实目标已经前移到：

```text
repeated compatible VerifiedExperience
→ bounded retrieval / aggregation
→ candidate procedural tendency
→ current-reality applicability
→ support / contradiction / maturity / inhibition
```

禁止 one-shot skill creation。stronger alternative-action recovery 保留为这条 learning path 的早期 consumer，而不是孤立 tactic generator。

纯 UI/desktop polish 继续暂停。M8/release 保留为 bounded parallel lane。

## 当前分支 / HEAD

- 分支：`dev/zn-agent`
- 最后一个真实 code/test SHA：`80292975264df35ff3a999ed32c7973cdd3514f5`
- 该 code/test SHA 的真实 CI：run `32639405457`，`ZN Kernel / Python = success`，`Electron / TypeScript = success`
- 本次状态文档同步父 HEAD：`564dbc0282186fb119ddba7db5362a12f9630990`
- 本 HANDOFF 提交本身为 docs-only `[skip ci]`；它会成为新的远程 HEAD，因此下一维护者必须先读取远程 `dev/zn-agent` 精确 HEAD，不得把上面的父 SHA 当成最终 HEAD。
- `main` 未修改。

## 本阶段已恢复并核对的真实现场

已重新读取/检查：

- `ZN.md`
- `AGENTS.md`
- `docs/ZN-IMPLEMENTATION-STATUS.md`
- `docs/ZN-SOURCE-EXTRACTION.md`
- `docs/ZN-SELF-MAINTENANCE.md`
- `.agent/HANDOFF.md`
- `dev/zn-agent` HEAD / recent commits / open PR / CI
- 当前 provider bridge → world-aware transfer resident → embodied verification 调用链
- packaged Python mapping：`runtime/python/pyproject.toml` 的 `zn_agent.core` 直接指向 `../../agent/kernel`

本轮开始时真实远程 HEAD：

```text
d9f51bd3aae4810af57f0fa9d134e82c2f89e03e
```

当时 open PR：无。

事实优先级继续保持：真实代码/Git → tests/CI → HANDOFF → 聊天。

## 本阶段完成：L1 first verified-experience slice

### 1. ZN-owned deterministic Body result semantics

新增：

```text
agent/kernel/result_semantics.py
```

关键提交：

```text
ee287a41873eb9340406aa95a56961b42127296c  feat: add deterministic body result semantics
20a3ffa9236e9de4279ef64e766d02f8cdce5988  fix: treat known swallowed failures as masked success
```

实现边界：

- 不 import Hermes `tools.*`；
- 只 source-adapt 窄的 deterministic failure/result semantics；
- 归一化输出只保留类别/计数/exit/timing/effect 等安全特征；
- failure classes 包括 timeout / not-executable / killed / nonzero-exit / command-not-found / module-not-found / permission-denied / merge conflict / rate limit 等；
- conservative masked-success detection 覆盖 `cmd | tail/head/...` 和 `cmd || echo/printf/true/:`；
- read-only pipeline 头部有保守豁免，避免明显误报；
- visible deterministic failure + shell-masked exit 0 不能 positive-verify。

Hermes 的 recovery prose/hint text、tool controller、agent loop 都没有进入 ZN active runtime。

### 2. First-class bounded `VerifiedExperience`

新增：

```text
agent/kernel/verified_experience.py
```

关键提交：

```text
1130148205471a14c964cc080ea481d6f72c3a93  feat: add bounded verified experience store
474f636cd8dedeeb23c5997ad45e07a7d224136f  fix: fingerprint capability domains in learned episodes
```

当前 record 连接：

```text
stable Situation / Investigation evidence fingerprint
+ goal / gap fingerprints
+ action kind / action signature hash
+ privacy-safe expected outcome features
+ normalized primary Body result features
+ independent verification features
+ verified / contradicted verdict
+ source/provenance class
+ grouping key / timestamp
```

硬边界：

- 必须有真实独立 Body observation；
- verification observation `action_id` 不能等于 primary Body action；
- Body `success=True` 本身不能创建经验；
- generic shell exit `0` 无 task-level postcondition 时不能创建经验；
- model/report text 无独立 observation 时不能创建经验；
- unsupported verification 不创建经验；
- contradiction 会持久化为 negative experience，不会被丢掉；
- masked-success verifier 即使旧逻辑声称 `verified=True`，builder 也会 defense-in-depth 改成 `contradicted`。

隐私边界：

- 不持久化 raw task/gap text；
- 不持久化 raw primary/verification command；
- 不持久化 raw path/workdir；
- 不持久化 raw Body output / required output fragment；
- 不持久化 caller-supplied capability label；
- 对这些只保存稳定 fingerprint、count、category 等必要学习特征。

Store：

- 与 resident kernel 共用同一 SQLite 文件，但使用独立窄表 `verified_experiences`；
- 默认硬上限 2048；
- deterministic experience ID / dedupe；
- restart-safe；
- retention 先保留 recent contradictions，再保留 representative group，再用 recency 填充；
- `native_action_failure_records` 继续只是 execution anti-replay state，不能与 learning store 混用。

### 3. 接入真实 shared embodied verification owner

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

没有新增 planner/final-runtime shim。

整文件 connector 更新后已做 compare：`embodied_resident.py` 相对基线只有 `+70 / -0`，没有误删原行为。

Command verification 现在会把 shell-masked visible failure 当 contradiction，而不是只看 exit code。

WorkingState 只留下安全的最新经验摘要：

```text
experience_id
verdict
group_key
source
```

### 4. Tests

新增：

```text
tests/agent/kernel/test_verified_experience.py
```

最终测试提交：

```text
80292975264df35ff3a999ed32c7973cdd3514f5  test: cover private capability labels in learning
```

覆盖：

- real write → independent read verification → one `verified` experience；
- restart 后同一 experience 可读取；
- contradicted postcondition → `contradicted` experience；
- Body success / naked exit 0 without postcondition → zero experience；
- model/report-only success without independent observation → no experience；
- masked pipeline/fallback/command-not-found swallowed status；
- read-only pipeline 非误报；
- privacy：SQLite serialized record 不含 task/content/path/root/private capability label；
- hard bounded retention + contradiction preservation。

本地执行环境没有 private-repo checkout，因此没有伪造 full local repo test 结果。仅做了 isolated pure-module smoke/`py_compile` 作为补充；权威结果是 GitHub CI。

## 真实 CI

Final code/test SHA：

```text
80292975264df35ff3a999ed32c7973cdd3514f5
```

Real GitHub Actions：

```text
ZN Kernel / Python      success
Electron / TypeScript  success
run                     32639405457
```

Push workflow 不运行 `Container / Runtime Smoke`，因此本阶段不宣称该 job。

后续文档提交使用 `[skip ci]`，不能把 docs-only HEAD 冒充为重新跑过代码 CI。

## 本阶段文档对账

已更新：

```text
docs/ZN-SOURCE-EXTRACTION.md
5151f120f7ab621296bc3ae04a4bb15f839af639
```

H-L1 从 source quarry / near-term 改成：**FIRST SLICE EXTRACTED INTO ZN / CI VERIFIED**，并明确未引入 Hermes control plane。

已更新：

```text
docs/ZN-IMPLEMENTATION-STATUS.md
564dbc0282186fb119ddba7db5362a12f9630990
```

Implementation Status 现在明确：

- L1 first causal `VerifiedExperience` slice 已真实 CI 验证；
- learning 不再是纯文档方向；
- 仍未实现 repeated aggregation / candidate tendency / mature skill / procedural fast path；
- Immediate sequence 已前移到 L2-style transparent aggregation/candidate tendency。

`docs/ZN-SELF-MAINTENANCE.md` 本轮没有架构变化，因此没有为了形式而改。

`ZN.md` 的核心 learning direction 没有改变；后部最新 learning section 与本轮实现一致。较早章节中仍存在历史性的 M8 “current priority”措辞，下轮如触碰 architecture status 可清理，但不得因此把主线倒退回 M8。

## 当前真实 capability boundary

已验证：

- persistent zero-model resident Self；
- durable event/WorkingState/Situation/Thought/Will；
- nervous traces/association/schema/reconsolidation；
- multi-pulse native Investigation；
- native Body/action；
- structured read-only Git sense；
- exact text + explicit command postcondition verification；
- compact durable execution context；
- evidence-bound failed-action anti-replay；
- first bounded/restart-safe/privacy-safe independently verified causal experience record；
- deterministic masked-success/failure semantics；
- bounded external cognition as resource；
- ZN-owned terminal/PTTY/web/work/provider/channel paths；
- independent ZN desktop/runtime/package identity foundations。

仍未完成：

- repeated `VerifiedExperience` retrieval/aggregation；
- candidate procedural tendency object/state；
- maturity/reliability/applicability/inhibition/de-proceduralization；
- learned mature skill activation / procedural fast path；
- stronger multi-action alternative recovery using learned evidence；
- safe Git mutation + diff/test/reality verification；
- GitHub repo/PR/CI resident read sense；
- clean browser Body/Senses seam；
- learned computer-use / engineering competence；
- growth benchmarks proving familiar tasks reduce model dependence without reducing verification quality；
- SM1+ self-maintenance implementation；
- remaining bounded M8 installed updater/multi-OS/signing gates。

## 风险 / 约束

1. `VerifiedExperience` 是 causal episode substrate，不是 skill。不要把一个成功 episode 直接 promote 成 capability。
2. `native_action_failure_records` 与 `verified_experiences` 必须保持不同职责：前者 execution anti-replay，后者 bounded learning evidence。
3. 当前只对已有独立 postcondition contract 的动作形成经验；generic action 没有 contract 时不应为了“多学数据”而降低真值标准。
4. domain/task/path/command/output 等隐私信息不能为了 future retrieval 重新原样塞回 learning store；如需语义检索，应设计明确、可审计的 privacy boundary。
5. masked-success pattern 是 deterministic evidence，不是绝对世界真理；必须保持保守并由实际 verification/context 约束。
6. 不要把 Hermes Curator/MemoryManager/SkillManager/tool loop 重新接成 active runtime。
7. candidate maturity 后续必须由 verified support/contradiction/applicability/prediction reliability 驱动，不可只按 use count/time。
8. 高风险 self-maintenance、identity、long-term memory、key permissions、updater/signing 仍按 `docs/ZN-SELF-MAINTENANCE.md` 保留人工批准边界。

## 阻塞

当前无代码/CI blocker。

当前执行环境没有 private-repo checkout，但 GitHub connector 可读写仓库且真实 GitHub Actions 已完成权威验证。不要把这一环境限制误写成项目能力限制。

## 下一真实目标

Fresh restore 后，先重新读取 6 个强制文档、HEAD/diff/PR/CI，再沿当前代码决定精确实现点。

优先目标：**repeated verified experience → candidate procedural tendency 的最小透明聚合层**。

建议第一片：

1. 读取 `VerifiedExperienceStore` 现有 grouping/retention，确认不会依赖 raw private payload；
2. 定义 bounded aggregation/retrieval contract，例如基于 stable `group_key` / action kind / expected-outcome class / current evidence compatibility 的 support + contradiction counts；
3. 只有重复兼容的 `verified` episodes 才能形成 candidate；单次成功不能；
4. candidate 必须保留 contradiction、last-verified、support count、maturity/applicability/inhibited 等明确状态；
5. current reality/evidence 不匹配时不能 fast-path；
6. contradiction 必须能降低/抑制 candidate，而不是被 recency 覆盖；
7. restart/bound/privacy tests；
8. tests 明确证明 model text/one-shot success 不能创建 candidate；
9. CI green 后再考虑把 A fail → genuinely different B verified success 接成 alternative-action learning consumer；
10. 不要直接生成 SKILL.md，不要引入 LLM planner/curator，不要把 candidate 直接放进 `PromotedCapabilityLoader`。

后续再进入：

```text
candidate tendency
→ repeated verified practice
→ maturity / prediction reliability
→ local activation under current evidence
→ contradiction / inhibition / relearning
→ promotion only after isolated test/benchmark/rollback gates
```

M8 remaining updater/multi-OS/signing work继续保持 bounded release debt，不覆盖 learning mainline。
