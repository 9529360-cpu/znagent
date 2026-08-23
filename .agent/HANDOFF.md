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

L1 `VerifiedExperience`、L2 transparent candidate aggregation、L3 current-reality applicability、第一片 bounded low-risk L3 action influence，以及 **bounded native structured-choice recovery** 已有真实 CI 证据。

下一真实目标仍是：让 ZN 自己的 Will / Investigation / deliberation 从当前事实形成**有语义保证的 bounded structured choice set**。本阶段只补齐了 choice consumer 的恢复能力：已有显式 choices 时，当前现实若否定 A，resident 可以在同一 evidence-bound anti-replay 契约下转到后续未被否定的 B。

这不是 autonomous choice formation，不是 fast path，不是 stored-action replay，也不是 model planner。

## 当前分支 / HEAD / CI

- 固定开发分支：`dev/zn-agent`
- 本阶段开始时精确 HEAD：`9f97ef5ecab3454000d3555d6c8ef41342f53433`
- 本阶段最终真实 code/test SHA：`2632bcb2a6738c79a250205374d45a0d34bbad36`
- real code CI：run `32645416634`
  - `ZN Kernel / Python = success`
  - `Electron / TypeScript = success`
  - isolated `runtime/python` install = success
  - zero-model isolated runtime boot = success
  - `agent/kernel` compile = success
  - full kernel unittest discovery = success
  - `Publish commit statuses = success`
  - `Container / Runtime Smoke = skipped`（normal push workflow contract）
- implementation-status docs commit：`76efbb298ebfedf030237854357a98635868fce9` (`[skip ci]`)
- 本 HANDOFF commit 也是 docs-only `[skip ci]`，因此会成为新的 remote HEAD；下一维护者必须重新读取 branch ref，而不能把 `2632bcb...` 或 `76efbb...` 当作当前分支 HEAD。
- 当前执行环境没有 private-repo local checkout，也没有 `gh`；没有宣称本地 full repo tests，GitHub Actions 是代码验证权威。

## 本阶段恢复的真实现场

重新读取并核对：

1. `ZN.md`
2. `AGENTS.md`
3. `docs/ZN-IMPLEMENTATION-STATUS.md`
4. `docs/ZN-SOURCE-EXTRACTION.md`
5. `docs/ZN-SELF-MAINTENANCE.md`
6. `.agent/HANDOFF.md`
7. `docs/ZN-MEMORY-LEARNING.md`
8. `dev/zn-agent` HEAD / recent diff / open PR / CI
9. Will / IntentionFormation / Action / active resident / Body / failed-action guard / verification caller chain

开始时：

```text
dev/zn-agent = 9f97ef5ecab3454000d3555d6c8ef41342f53433
main         = 61dd880aa4bbbdb359ca544b752afc2c22845ce9
Open PR      = 0
```

上一 code/test SHA `aec75ec2b2a2e37eae57a4a26011f324c1a823ff` 的 run `32643849526` 仍 Python/Electron 双绿。

## 并发分支变化

本阶段工作期间发现 `dev/zn-agent` 已被其他维护动作并发推进。对比 `9f97ef...` 到本阶段 code/test SHA 时，除本阶段文件外还出现了与本目标无关的：

```text
agent/kernel/channel.py
agent/kernel/channel_delivery.py
agent/kernel/channel_runtime.py
agent/kernel/telegram_channel.py
tests/agent/kernel/test_channel_runtime.py
tests/agent/kernel/test_telegram_channel.py
```

这些文件不是本阶段创建/修改的目标。本阶段没有回滚、覆盖或重写这些并发改动。最终 run `32645416634` 验证的是包含这些并发改动在内的组合 branch state。

不要仅凭本 HANDOFF 对这些 channel/Telegram 改动追加产品能力声明；后续需要按真实代码、对应测试和其维护记录单独对账。

## 当前真实 action / learning call chain

### Will / intention

`NativeWill` 仍故意只保留一个当前 incubating candidate step，不是 plan list。`NativeIntentionFormation` 从当前 Situation/Body/schema expectation 形成一个 situated next-step candidate，`NativeWill.promote_candidate()` 再把它提升为 `next_task` / `next_payload`。

因此当前 Will 还没有 resident-owned multi-action choice-set owner。

### Current action formation

```text
derive_native_action_intents(event, facts)
```

语义保持：

- valid `body_action` / `native_action` → one exclusive `structured_event` action；
- explicit bounded `native_action_options` → ordered `structured_choice` set；
- otherwise → historical single heuristic action；
- free-text multi-clause task 不会被猜成 alternatives；
- memory / model text 不参与 action args 形成。

### L1 / L2 / L3

```text
Body movement
→ independent verification
→ VerifiedExperience (L1)
→ candidate_tendencies() (L2)
→ current-reality applicability (L3)
→ optional bounded procedural bias over already-formed choices
```

Candidate 不能提供 raw command/args/path/content；`mismatch` / `untested` 没有正向 action authority。

### Active runtime

```text
provider_bridge.build_resident_runtime()
→ ProcedurallyInfluencedResidentRuntime
→ WorldAwareTransferResidentRuntime
→ existing embodied/world/transfer chain
```

Body、verification、failed-action ledger、Investigation owners 没有被替换。

## 本阶段完成：bounded native structured-choice recovery

### 1. Consumer prerequisite

真实缺口是：虽然 `native_action_options` 已经能表达 ordered choices，但在没有 qualifying procedural candidate 时，如果 A 已在当前 evidence fingerprint 下失败，普通 deliberation 仍会回到 default A，而不会消费后续 B。

这意味着即使未来 Will/Investigation 能正确形成 choices，consumer 也还不能可靠恢复。因此本阶段先补这个更低层 prerequisite。

### 2. 代码

修改：

```text
agent/kernel/procedural_resident.py
```

新增：

```text
_NATIVE_CHOICE_RECOVERY_KEY = "native_choice_recovery"
_recover_from_blocked_structured_choices(...)
```

核心规则：

- 至少两个 current intents；
- 所有 intents 都必须是 `source == "structured_choice"`；
- 按原 declared order 扫描；
- earlier choice 必须真实被 `_action_blocked_by_current_evidence(...)` 在当前 evidence fingerprint 下挡住；
- 选择第一个 later unblocked choice；
- 若第一项仍 admissible，则返回 False，历史 default priority 不变；
- 若 single explicit action，则不进入 recovery；
- 若全部 choices 被挡住，则 fail closed，交还原 deliberation/impasse path；
- 不从 task text、memory、model output 或 failed-action args 构造新的 option；
- 不修改 current option args；
- 继续调用 existing `_begin_native_action_cycle(...)`，因此 Body/verification owners 不变。

WorkingState 仅保存 bounded recovery metadata：

```text
selected_index
choice_count
blocked_prior_choices
action_kind
evidence_version  # truncated fingerprint
```

Thought 可以观察到 native recovery；下一 deliberation 开始前旧 recovery marker 会清理。

### 3. Procedural interaction

如果一个 procedurally influenced choice 本身已被 current anti-replay 挡住：

1. 当前 candidate 先 event-local revoke；
2. active procedural influence marker 清掉；
3. 再尝试 native structured-choice recovery；
4. 后续 B 若被选中，归因是 native recovery，不是假装由旧 candidate 选择。

Evidence-bound anti-replay 继续高于 familiarity。

## 测试 / CI

新增：

```text
tests/agent/kernel/test_native_choice_recovery.py
```

覆盖：

- active runtime 仍包含 `WorldAwareTransferResidentRuntime`；
- A 在当前 evidence 下被记录失败后，明确的 `[A, B]` 可恢复到 B；
- recovery 不需要 procedural learning；
- A 未被挡住时不抢走 historical default；
- single / non-choice explicit action 不进入 recovery；
- selected args 完全来自 current B option，不从 failure history 恢复或发明 args。

最终 code/test commits：

```text
3d1d7ebdce9c02224d4e836ef6c4c4d6df2758f7  feat: recover across bounded native choices
2632bcb2a6738c79a250205374d45a0d34bbad36  test: cover bounded native choice recovery
```

真实 GitHub Actions：

```text
run 32645416634
ZN Kernel / Python          success
Electron / TypeScript      success
Publish commit statuses    success
Container / Runtime Smoke  skipped
```

Python job 的 locked deps、isolated runtime install、zero-model boot、compile、full kernel tests 全部 success。Electron job 的 install、typecheck、bundle、desktop ownership/update/handoff tests、release/runtime staging/package verifier tests 全部 success。

## 文档状态

本阶段：

- `docs/ZN-IMPLEMENTATION-STATUS.md` 已更新；
- `.agent/HANDOFF.md` 已更新；
- `ZN.md` 未改：架构方向没有改变；
- `docs/ZN-SOURCE-EXTRACTION.md` 未改：没有新的 Hermes extraction；
- `docs/ZN-SELF-MAINTENANCE.md` 未改：self-maintenance architecture 没变。

## 当前没有实现、不得误报

仍 PARTIAL / MISSING：

- resident-owned generation of useful structured action alternatives from Will/Investigation；
- learned formation of genuinely different tactics，而不是消费 caller-provided options；
- broad candidate influence over command / arbitrary side effects；
- raw action replay from procedural memory；
- mature/procedural resident-owned skills；
- procedural fast path；
- broader prediction-error de-proceduralization；
- learned engineering competence；
- learned computer-use competence；
- growth benchmarks proving reduced external cognition without lower verification quality；
- practical Git mutation + diff/test/reality verification；
- GitHub repo/PR/CI resident-owned sense；
- browser Body/Sense seam；
- SM1+ self-maintenance implementation。

`native_action_options` 仍只是 explicit structured event seam。不要把本阶段写成 “ZN 已经会自己生成 alternatives”。

## 下一真实目标

Fresh restore 后，继续做第一片 **resident-owned bounded structured-choice formation**。

必须重新追真实链：

```text
Will / current Thought
→ NativeIntentionFormation
→ current Investigation facts
→ event next_payload / action contract
→ derive_native_action_intents()
→ ProcedurallyInfluencedResidentRuntime._deliberation_step()
→ Body
→ independent verification
```

边界：

1. choice set 必须由当前 ZN state/facts 有语义地证明是同一目标的 alternatives；
2. 不能因为自由文本里出现多个 action-shaped clause 就推断 alternatives；
3. external model output 不能直接拥有 choice set；
4. candidate memory 不能提供 raw command/args/path/content；
5. `mismatch` / `untested` 继续 zero positive influence；
6. 现有 exact-write influence gates 保留，除非新的 real benchmark 支持扩大；
7. independent verification 始终保留；
8. evidence-bound anti-replay 高于 familiarity；
9. prediction error / contradiction 立即回 Investigation；
10. cognition-integration path 目前仍使用历史 single `derive_native_action_intent()`，不要在未重新追 caller 前静默扩大；
11. high-risk identity / long-term memory / credentials / updater / rollback / signing / self-maintenance permission 仍人工批准；
12. 不要建立第二个 mutable choice/procedure cache，除非有 profiling evidence。

推荐真实 consumer benchmark：

```text
A fails
→ genuinely different B succeeds
→ B independently verified
→ later comparable current reality supports B-pattern
→ current resident-owned choice formation legitimately contains B
→ supported candidate may bias toward B
→ independent verification still required
```

不要 hardcode A/B tactic rule。

## 结束前必须再次核对

每次继续前/结束前必须重新检查：

- exact `dev/zn-agent` HEAD；
- `main` 是否仍为 `61dd880aa4bbbdb359ca544b752afc2c22845ce9`；
- Open PR；
- current code SHA CI；
- 本阶段并发 channel changes 是否又被继续推进；
- code / tests / docs / HANDOFF 是否一致。
