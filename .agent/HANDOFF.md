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

并行完成的 communication slice 也已有独立证据：resident channel event 可显式持久化 outbound artifact nomination，Telegram 在任何网络请求前通过 ZN-owned path policy 授权并发送 document。当前 cognition 尚不会自主决定何时提名工件，因此这不是 autonomous media judgment。

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
- outbound-media code/test SHA：`018af2ec18abbac2a74e33f471101cb6a4308f36`
- outbound-media normal CI：run `32645243684`，Python / Electron / status publisher 全部 success
- media push 的 AppImage run `32645243759` 被后续并行 code push 按 workflow concurrency 自动取消；累计包含 media code 的 successor run `32645354818` 仍停留在 real installed N → N+1 continuity step。该 step 已超过 workflow 声明的外层 `15m` timeout，但 runner 尚未返回最终 conclusion；不得写 success，也不要归因于 media diff
- 本 HANDOFF commit 也是 docs-only `[skip ci]`，因此会成为新的 remote HEAD；下一维护者必须重新读取 branch ref，而不能把 `2632bcb...` 或 `76efbb...` 当作当前分支 HEAD。
- 当前执行环境有 private-repo checkout 与 `gh`。outbound-media 定向本地验证已执行；完整集成权威仍是 GitHub Actions。

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

这些 channel/Telegram 改动现已按真实调用链、代码、定向测试和独立 CI 完成对账，具体边界记录在下方 outbound-media section；没有回滚或覆盖本阶段 native-choice recovery。

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

## 并行完成：resident-owned outbound media seam

真实调用链：

```text
resident channel_message event
→ durable pending ChannelRoute
→ explicit nominate_outbound_media(event_id, local_path, ...)
→ SQLite channel_media_nominations
→ resident outcome becomes ready
→ ChannelMessage.attachments
→ Telegram OutboundMediaPathPolicy authorization
→ multipart sendDocument
```

完成边界：

- `ChannelOutboundMedia` 与 inbound `ChannelAttachment` 分离；
- nomination 只接受 existing pending resident route，最多 8 个，metadata 必须 bounded JSON-safe；
- nomination 持久化并经过 supervisor restart 继续投递；
- response text 即使包含本机路径也不会被解释为 attachment；
- Telegram 在任何网络请求前预授权全部路径，默认只允许 ZN home 下 `artifacts/` 与 `channels/outbound/`；
- relative path、traversal、逃逸 symlink、root 外文件和超限文件 fail closed；
- 支持 text + documents 与 attachment-only delivery，并保留 thread/reply routing；
- filename sanitation 与 token-safe errors 保持有效。

未完成边界：

- Thought/Will/Investigation 尚不会自主判断应提名哪个 artifact；
- 第一 slice 统一使用 Telegram `sendDocument`，未实现 photo/audio/video-specific method selection；
- nomination 是结构化 transport seam，不是 model 文本中的路径，也不是任意本地文件读取权限。

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

Outbound-media 定向本地验证：

```text
test_channel_runtime.py + test_telegram_channel.py   19 passed
channel/telegram/outbound_media related suite       41 passed, 1 skipped
ruff changed files                                  all checks passed
```

一次包含 `test_resident_channel_service.py` 的 Windows 扩展运行在 `TemporaryDirectory` 清理时遇到 `kernel.db` 文件锁；同一 failure 已在未修改的原始 worktree 连续复现，因此不是 media diff 引入。Linux full kernel CI `32645243684` 与累计 branch CI `32645416634` 均 success。

AppImage successor run `32645354818` 的 N 与 N+1 real AppImage builds 已 success，但 installed continuity step 超过其声明的 15 分钟外层 timeout 后仍未结束。它属于 M8/updater lane 的待查运行状态，不是 outbound-media capability 的完成证据。

## 文档状态

本阶段：

- `docs/ZN-IMPLEMENTATION-STATUS.md` 已更新；
- `docs/ZN-SOURCE-EXTRACTION.md` 已更新 outbound-media extraction state；
- `.agent/HANDOFF.md` 已更新；
- `ZN.md` 未改：架构方向没有改变；
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
- autonomous outbound artifact nomination from current Thought/Will/Investigation；
- Telegram photo/audio/video-specific outbound transports；
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
- outbound-media successor AppImage smoke `32645354818` 的最终结论；
- code / tests / docs / HANDOFF 是否一致。
