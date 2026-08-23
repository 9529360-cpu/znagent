# ZN Agent Handoff

更新时间：2026-08-23

## 当前目标

开发主线已经从单纯“继续加深 execution tactics”进一步明确为：

```text
durable ZN Self
+ mature Agent-level complex-task execution depth
+ reality-based verification
+ resident-owned learning / procedural competence
```

核心产品原则：

> **Models may help ZN learn. Mature capability must belong to ZN.**

ZN 不是 `LLM -> planner -> tools -> agent`。同一个 resident Self 必须持续拥有目标、调查、动作、反证、恢复、完成判断和学习。

长期目标不是让 ZN 更熟练地调用 GPT/Claude/Gemini，而是让反复经过现实验证的经验逐步变成 ZN 自己的程序性能力；熟悉、低风险的行为可以逐步形成更快的 perception-action pathway，但预测结果与现实不一致时必须打断自动化，返回 Thought / Investigation 并重新学习。

当前下一真实实现目标：**L1/P0 verified experience record**。

先建立最小 resident-owned learning unit：

```text
current Situation / evidence
+ goal / current gap
+ concrete action
+ expected outcome
+ independently observed verification result
+ success / contradiction
```

它必须 bounded、restart-safe、privacy-safe，且不能把 model text、action return value 或一次成功直接当成成熟 skill。

此前的 **stronger alternative-action recovery** 不删除，但暂不作为孤立 tactic generator 继续实现。它将作为 learning architecture 的早期 consumer：A 失败、B 被现实独立验证成功后，这个 Situation/action/outcome 关系才成为可复用学习证据。

纯 UI/desktop polish 继续暂停。M8/release 保留为 bounded lane。

## 当前分支 / HEAD

- 分支：`dev/zn-agent`
- 最新真实 code/test SHA：`23ce3b42aad2d730afae4d60eb6af5d5b4bd1399`
- ZN architecture direction commit：`08f5bfba3ea7e4669170dd9008cefc6b3fe6573c`
- memory/learning architecture commit：`5977465d9c7560828c14a22a2bc4f5844c7ed8f3`
- next-phase alignment commit：`cfaa9fc738cd4cfbc65d02de336e256ce0647ee7`
- implementation-status update：`8650489035f04b775a6bf508ee7a8cf415840429`
- 本 HANDOFF 为 docs-only `[skip ci]`；下一维护者必须重新读取远程 `dev/zn-agent` 最终 HEAD。
- `main` 未修改。

## 本阶段恢复并核对的真实现场

已重新读取并核对：

- `ZN.md`
- `AGENTS.md`
- `docs/ZN-IMPLEMENTATION-STATUS.md`
- `docs/ZN-SOURCE-EXTRACTION.md`
- `docs/ZN-SELF-MAINTENANCE.md`
- `docs/ZN-NEXT-PHASE.md`
- `.agent/HANDOFF.md`
- `dev/zn-agent` HEAD / net diff / open PR / recent commits / CI
- 当前 memory/nervous-system 实现和测试
- 当前 Investigation → Action → Body → Verification execution spine

本阶段开始时远程 `dev/zn-agent` HEAD 为：

```text
79d1fee68c702f8bbc923944a75b520dffe4439f
```

开始时 compare 确认 branch 与该 HEAD identical；Open PR 无。

当前执行环境无可用本地 private-repo checkout，因此不宣称本地 test run；真实验证以 GitHub CI 为准。

## 本阶段架构方向更新

### `ZN.md`

Commit：

```text
08f5bfba3ea7e4669170dd9008cefc6b3fe6573c
```

新增硬架构契约 `Resident competence, procedural memory and reflex learning`，明确：

- model 可以帮助 ZN 学习，但成熟能力必须属于 ZN；
- 断开全部 external models 不应让已经成熟的 resident skill 消失；
- memory 不能仅等价为给 LLM 的 context/retrieval；
- novel work 可以使用 Thought / Investigation / external cognition；
- repeated verified experience 应能形成 procedural competence；
- 一次成功不能直接创建永久 skill；
- reflex 是 prediction-backed fast path，不是 prompt cache / raw shell replay / absolute mouse-coordinate script；
- prediction error 必须 inhibit familiar path，并把控制权交回 Thought / Investigation；
- learning 需要 reinforcement、contradiction weakening、context narrowing、de-proceduralization、relearning；
- computer use 和 engineering ability 最终应能成为 resident-owned competence；
- growth 要通过模型依赖下降、熟悉任务步数/延迟下降、restart/provider/model-removal continuity、prediction-error interruption 等实际指标证明。

### `docs/ZN-MEMORY-LEARNING.md`

Commit：

```text
5977465d9c7560828c14a22a2bc4f5844c7ed8f3
```

新建专门 memory/learning contract，定义：

- working/current-event memory；
- episodic/lived experience memory；
- semantic/structured knowledge；
- associative nervous memory；
- procedural memory / learned competence；
- perception-action familiarity / reflex；
- skill maturity / inhibition / relearning；
- computer-use competence；
- engineering competence；
- external cognition 的 teacher/adviser boundary；
- real growth benchmarks。

定义实现阶段：

```text
L0 architecture contract                         DEFINED
L1 verified experience record                    NEXT
L2 candidate procedural tendency                 PLANNED
L3 reality-gated skill activation                PLANNED
L4 procedural fast path                          PLANNED
L5 inhibition / de-proceduralization / relearn   PLANNED
L6 computer-use + engineering learning benchmark PLANNED
```

L0 只是 architecture defined，不代表 runtime 已实现。

### `docs/ZN-NEXT-PHASE.md`

Commit：

```text
cfaa9fc738cd4cfbc65d02de336e256ce0647ee7
```

Phase target 更新为：

```text
durable ZN Self
+ mature task-execution depth
+ reality-based verification
+ resident-owned learning / procedural competence
```

新的实现顺序是：verified experience → candidate procedural tendency → alternative-action recovery as learning consumer → maturity/inhibition → engineering competence → computer-use competence → growth benchmarks。

### `docs/ZN-IMPLEMENTATION-STATUS.md`

Commit：

```text
8650489035f04b775a6bf508ee7a8cf415840429
```

明确区分“已验证基础”和“未来目标”，没有把 procedural memory 写成 complete。

## 当前真实 memory / learning 基础

当前代码已经有的真实 foundation：

### `StructuredMemory`

- durable structured facts；
- normalized key/alias recall；
- 不是 transcript store。

### `PersistentNervousSystem`

当前代码/测试已经证明：

- persistent `NeuralTrace`；
- repeated experience 强化同一个 trace，而不是不断新增重复 memory；
- co-active trace association；
- cue-driven activation + associative spreading；
- strength / salience / recency / repetition 对 activation 有作用；
- persistent affective state；
- local consolidation；
- recurring structure 形成 schema；
- weak isolated detail 可以 fade/prune；
- nervous state / traces 跨 restart；
- lived trace/schema 可进入 Situation/Thought；
- private lived/schema detail 不会因为调用 external cognition 就自动 dump 给模型；
- current reality 可以 gate transfer/reconsolidation。

代表测试：

```text
tests/agent/kernel/test_nervous_system.py
tests/agent/kernel/test_neural_cognition_boundary.py
```

## 当前没有实现、不得误报的 learning 能力

以下仍然 **PARTIAL / MISSING**：

- first-class causal episodic record：Situation → action → expected outcome → observed verification；
- repeated verified experience → reusable candidate procedure 的 learning bridge；
- explicit skill maturity/confidence/contradiction/inhibition state；
- resident-owned mature skills that execute locally without model interpretation；
- procedural fast path；
- prediction-error-driven de-proceduralization / relearning；
- learned computer-use competence；
- learned engineering competence；
- benchmarks proving familiar tasks become less model-dependent while verification quality remains intact。

不要把现在的 NeuralTrace/schema 直接称为完整 procedural memory。

## 现有执行 spine 的真实 CI 基线

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

GitHub job 结论此前已核对：Kernel tests、isolated model-free boot、compile、Electron typecheck/bundle/tests 全部 success；push workflow 的 container job 按设计 skipped。

本阶段没有修改 runtime/test code，只有 `[skip ci]` 文档变更，因此不生成/宣称新的 code CI。

## 已真实 CI 验证的 execution foundations

### Git sense + first post-action verification

```text
code/test SHA            47ccd5601462641c50c16ec76f2a05085a33f9f3
ZN Kernel / Python       success
Electron / TypeScript   success
run                      32612456040
```

### Explicit command postconditions

```text
code/test SHA            f280c8f68af69dfc2ac10b94d8d83726c10aa14e
ZN Kernel / Python       success
Electron / TypeScript   success
run                      32621596489
```

### Compact task execution context

```text
code/test SHA            aaa6fa55c5c4e1968006f618a37260cb4f41675a
ZN Kernel / Python       success
Electron / TypeScript   success
run                      32621878503
```

### Evidence-bound failed-action history

```text
code/test SHA            23ce3b42aad2d730afae4d60eb6af5d5b4bd1399
ZN Kernel / Python       success
Electron / TypeScript   success
run                      32635668910
```

Verified includes bounded failure records, A → B → A suppression under unchanged Investigation facts, changed-facts retry eligibility, restart continuity, and prevention of false completion after accepted cognition still proposes a currently blocked movement.

## 当前下一真实实现目标：L1/P0 verified experience record

开始实现前仍必须 fresh-restore repository state and active call chain。

第一 slice 要把已经存在的 execution evidence 变成一个明确的 learning unit，而不是引入 planner/skills database：

```text
Situation / stable evidence
→ goal / current gap
→ concrete NativeActionIntent identity
→ expected outcome
→ Body action result
→ independent verification observation
→ verified / contradicted
→ bounded resident-owned experience record
```

必须证明：

- success learning evidence 来自 independent reality verification；
- model text alone 不能生成“成功经验”；
- shell exit 0 alone 不等于成功经验；
- record 跨 resident restart；
- record bounded；
- 不把 full command/content/private secret 随意复制到 broad long-term memory；
- contradiction 也被保留，不只存 success；
- 现有 Situation/Investigation evidence identity 可以与经验关联；
- 当前 architecture 不新增 planner/task manager。

然后才进入 L2 candidate procedural tendency；再让 alternative-action recovery 成为它的一个真实消费者。

## 风险与边界

- 不做 one-shot skill creation；
- 不把模型生成 procedure 直接当 resident competence；
- 不把 prompt cache / embedding retrieval 伪装成 procedural learning；
- 不把 absolute mouse coordinate replay 当 reflex；
- 熟练化仍必须保持 expected outcome + observation + verification；
- prediction error 必须能打断 automatic path；
- high-risk identity/memory/credential/updater/rollback/signing/self-maintenance permission 修改不因“熟练”而绕过人工审批；
- 不泄露 secrets 到 memory/skill records；
- 不修改 `main`。

## 文档状态

本阶段架构方向改变，因此已按规则先更新 `ZN.md`。

已更新：

- `ZN.md`
- `docs/ZN-MEMORY-LEARNING.md`（new）
- `docs/ZN-NEXT-PHASE.md`
- `docs/ZN-IMPLEMENTATION-STATUS.md`
- `.agent/HANDOFF.md`

未修改：

- `docs/ZN-SOURCE-EXTRACTION.md`：Hermes extraction state 未变化；
- `docs/ZN-SELF-MAINTENANCE.md`：本阶段不是 self-maintenance architecture change；
- `AGENTS.md`：维护规则未变化；
- `main`：untouched。
