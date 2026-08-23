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

本阶段已经完成并由真实 CI 验证第一片 **resident-owned bounded structured-choice formation + learning consumer loop**。

ZN 现在不是只会消费 caller 提供的 `native_action_options`。在一个非常窄且可证明的 exact-text 场景中，当前 Investigation 观察到完整文件状态，并且 typed `text_equals` task postcondition 能证明“append 当前增量”和“直接 replace 到最终文本”达到同一目标时，resident 自己可以形成两个 bounded current choices。

这个 slice 仍然不是 general planner、自由文本 tactic inference、stored-action replay、mature skill 或 broad autonomous alternative generation。

下一真实目标：在不扩大未经证明 authority 的前提下，找到第二类由当前 Will/Investigation 能**语义证明为同一目标 alternatives** 的 resident-owned choice contract；优先考虑对长期 engineering competence 真有价值、且有独立 verification 的不同 tactic class。

## 当前分支 / HEAD / CI

- 固定开发分支：`dev/zn-agent`
- `main`：未修改；M10 仍未满足
- 本阶段开始恢复时 HEAD：`a54fc1f000cb7eb8e167b07d1262ab3133413611`
- 本阶段最终 code/test SHA：`920bd70814e44d9b62b6ba5159e264ab442470a3`
- code/test CI：run `32647895984`
  - `ZN Kernel / Python = success`
  - isolated `runtime/python` install = success
  - zero-model isolated runtime boot = success
  - `agent/kernel` compile = success
  - full kernel unittest discovery = success
  - `Electron / TypeScript = success`
  - desktop typecheck/bundle/ownership/update/handoff/release verifier tests = success
  - `Container / Runtime Smoke = skipped`（normal push workflow contract）
  - `Publish commit statuses = success`
- implementation-status latest docs commit：`50ebda8d51681a8e0503baddafc4aaddb34edd08` (`[skip ci]`)
- previous HANDOFF docs commit：`38f706fd4257ca879e04eefe09a4ab293f02eead` (`[skip ci]`)
- 本 HANDOFF 也是 docs-only `[skip ci]`；提交后它会成为新的 branch HEAD，下一维护者必须重新读取真实 branch ref，不能把 `920bd708...`、`50ebda8...` 或本段文字当作未来 HEAD 的替代品

### M8 / AppImage 真实终态

旧 run `32645354818` 已从之前的长期 in-progress 变为终态：

```text
Real AppImage N to N+1 job                            cancelled
Build real N AppImage                                 success
Build real N+1 AppImage                               success
Run real installed AppImage updater continuity smoke cancelled
Capture smoke diagnostics                             success
Upload smoke proof and diagnostics                    success
Publish AppImage update smoke status                  success
```

因此：

- 两个真实 AppImage build 有成功证据；
- installed N → N+1 updater continuity **没有成功证据**；
- 该 lane 仍是 M8 release debt，后续应读取 diagnostics 再判断取消/卡住根因；
- 不得把 `32645354818` 写成 continuity success。

## 本阶段恢复的真实现场

重新读取并核对：

1. `ZN.md`
2. `AGENTS.md`
3. `docs/ZN-IMPLEMENTATION-STATUS.md`
4. `docs/ZN-SOURCE-EXTRACTION.md`
5. `docs/ZN-SELF-MAINTENANCE.md`
6. `.agent/HANDOFF.md`
7. `docs/ZN-MEMORY-LEARNING.md`
8. `docs/ZN-NEXT-PHASE.md`
9. `dev/zn-agent` HEAD / main diff / open PR / recent commits / CI
10. action formation → Investigation → procedural applicability/influence → Body → verification → VerifiedExperience → candidate tendency 的真实调用链

恢复时确认：

- open PR = 0；
- `main` 保持 initial baseline，没有被本阶段修改；
- 前一 code/test run `32645416634` 仍 Python/Electron 双绿；
- 当时 AppImage run `32645354818` 仍卡住，结束前重新检查后已得到上述 cancelled 终态。

## 当前真实 action / learning call chain

### Action formation

```text
derive_native_action_intents(event, facts)
```

当前语义：

1. valid `body_action` / `native_action` → one exclusive `structured_event` action；
2. explicit bounded `native_action_options` → ordered `structured_choice` set；
3. otherwise 先形成历史 heuristic default；
4. 只有 exact-text proof contract 满足时，default append 可以扩成两个 `resident_choice`；
5. 其他情况保持历史 single-action behavior。

### Resident exact-text choice proof

必须同时满足：

```text
current default action == write_text append
expected_outcome.kind == text_equals
expected_outcome.path 与 current action target 一致
append content 非空
Investigation 有同一 target 的完整 file preview
preview.truncated == false
observed_current_text + append_content == expected_text
path fact（若存在）确认 target 是 existing file
```

满足后形成：

```text
A = current append movement
B = write_text(append=false, content=expected_text)
```

两者 `source == resident_choice`。

关键边界：

- B 的 path/content 来自**当前 task contract**，不是 learned memory；
- 无 preview、preview truncated、文本不匹配、target 不匹配或 path incompatible → 不形成第二 choice；
- free-text clauses、model text、procedural memory、failed-action args 都不能生成 choice；
- explicit single body/native action 保持 exclusive。

### Recovery / anti-replay

`ProcedurallyInfluencedResidentRuntime._recover_from_blocked_structured_choices()` 现在接受同源的：

```text
structured_choice
resident_choice
```

至少两个 choices 才可恢复。earlier choice 必须由当前 evidence-bound anti-replay 真实挡住，才选第一个 later unblocked choice。若第一项仍 admissible，历史 priority 不变；若全被挡住则 fail closed。

Recovery metadata 增加 `choice_source`，仍只保存 bounded index/count/action/evidence 信息。

### Verification

本 slice 的 typed task contract：

```text
expected_outcome = {
  kind: text_equals,
  path: ...,
  expected_text: ...
}
```

active runtime 将其转换为 existing text verification contract。Selected exact replacement 仍必须：

```text
Body write
→ native_verification
→ independent Body read_text
→ exact comparison
→ only then complete / create positive VerifiedExperience
```

Body success 本身不能证明任务完成。

### L1 / L2 / L3

```text
verified selected movement
→ VerifiedExperience (L1)
→ candidate_tendencies() (L2)
→ current-reality applicability (L3)
→ optional procedural bias among current choices
```

`procedural_applicability.current_expected_outcome()` 现在能把 explicit typed `text_equals` 规范化为当前 applicability contract。

Learned candidate 仍不能提供 raw path/content/command/args。

## 本阶段完成的端到端证明

新增 integration regression：

```text
tests/agent/kernel/test_resident_structured_choice_learning.py
```

场景：

1. 当前文件是 `prefix`；
2. resident 当前任务要求 append `suffix`，typed goal 是最终 `prefix + suffix`；
3. Investigation 完整观察当前文件，因此 resident 形成 `[append A, exact-replace B]`；
4. test environment 让 append route 抛出 Body failure；
5. same-evidence anti-replay 阻止 A；
6. native choice recovery 选择 resident-formed B；
7. B 使用 current task path/content 执行；
8. independent `read_text` 验证最终文本；
9. 产生一条 positive `VerifiedExperience`；
10. 三个 distinct events 后，形成 supported `write_text/text_equals` candidate；
11. later comparable reality 重新从 current file/task 形成 `[A, B]`；
12. L3 candidate 可以 bias 当前 B；
13. B 仍只使用 later event 当前 path/content，并再次独立 verify；
14. candidate serialization 不含 raw target path 或训练时文件内容。

这证明的是：

> resident 自己形成 bounded alternatives → 现实失败 → resident 自己恢复 → 独立验证 → 学习 → later current choice 被学习偏置

不是：

> memory 重放一个存储好的动作。

## 修改文件

Code:

```text
agent/kernel/action.py
agent/kernel/procedural_applicability.py
agent/kernel/procedural_resident.py
```

Tests:

```text
tests/agent/kernel/test_native_action_alternatives_contract.py
tests/agent/kernel/test_resident_structured_choice_learning.py
```

Docs:

```text
docs/ZN-IMPLEMENTATION-STATUS.md
.agent/HANDOFF.md
```

没有修改：

- `ZN.md`：架构方向没有改变；
- `docs/ZN-SOURCE-EXTRACTION.md`：本阶段没有 Hermes extraction state 变化；
- `docs/ZN-SELF-MAINTENANCE.md`：self-maintenance architecture 没变；
- `main`。

## 关键 commits

```text
1cb9d6f3d716fadb9f4c1379c955d2284d901b0f  feat: form resident exact-text action choices
2da38f014f73f9f51224f5784fbc1e8853587a24  feat: align procedural applicability with exact-text goals
0d566d04f55dff7d9e967c49bf901c0d90dfce60  feat: recover resident-formed exact-text choices
5f10a4f5d60fb9c801ce53d400cba13ca1addee8  test: cover resident exact-text choice formation
920bd70814e44d9b62b6ba5159e264ab442470a3  test: prove resident choice learning loop
1fe89bde2fa16b39d0feb574399600fa288ef9ac  docs: record resident-owned choice learning slice [skip ci]
38f706fd4257ca879e04eefe09a4ab293f02eead  docs: hand off resident choice learning state [skip ci]
50ebda8d51681a8e0503baddafc4aaddb34edd08  docs: record cancelled AppImage continuity result [skip ci]
```

## 测试 / CI

本地可执行环境没有完整 private-repo checkout，因此没有把本地 synthetic check 冒充 repository integration test。

实际执行过一个最小 isolated pure action-formation check，验证：

- exact matching full preview → 两个 `resident_choice`；
- missing preview → single historical action；
- truncated preview → single historical action；
- mismatched preview → single historical action。

结果：PASS。

权威集成验证是 GitHub Actions run `32647895984`：

```text
ZN Kernel / Python          success
Electron / TypeScript      success
Container / Runtime Smoke  skipped
Publish commit statuses    success
```

Python job 中完整 kernel unittest discovery 已包含新增 resident learning integration test。

## 当前没有实现、不得误报

仍 PARTIAL / MISSING：

- broad resident-owned generation of structured action alternatives from Will/Investigation；
- commands / Git / browser / arbitrary side-effect tactic formation；
- learned multi-step tactic trees；
- model-free general planner；
- broad candidate influence over command / arbitrary side effects；
- raw action replay from procedural memory；
- mature resident-owned procedural skills；
- procedural fast path；
- broader prediction-error de-proceduralization；
- resident-owned reliable high-level postcondition derivation；
- learned engineering competence；
- learned computer-use competence；
- growth benchmarks proving lower model dependence without lower verification quality；
- practical Git mutation + diff/test/reality verification；
- GitHub repo/PR/CI resident-owned sense；
- browser Body/Sense seam；
- autonomous outbound artifact nomination from current Thought/Will/Investigation；
- Telegram photo/audio/video-specific outbound transports；
- successful real installed AppImage N → N+1 updater continuity；
- SM1+ self-maintenance implementation。

## 风险 / 阻塞

### Core learning lane

当前无已知 CI blocker。

主要设计风险是过早泛化 choice formation：不能因为 task 中有多个动词、memory 中有熟悉 tactic、或 model 建议了多个动作，就宣称这些动作是同一 goal 的 alternatives。下一 slice 必须继续使用可验证 semantic contract。

### M8 updater lane

Run `32645354818` 的 installed updater continuity smoke 已 cancelled。两版 AppImage build success，诊断有上传。下一次切回 M8 时，应先读取 diagnostics artifact / step logs，确定为何 continuity step 被 cancelled/卡住，而不是盲目重复 run 或降低 integrity gates。

## 下一步

Fresh restore 后：

1. 重新读取本 HANDOFF 与真实 branch HEAD；
2. 确认 docs-only HEAD 与 code/test SHA `920bd708...` 的关系；
3. 重新确认最新 CI / concurrent commits；
4. 从 `NativeWill` / `NativeIntentionFormation` / Investigation facts 追一个**第二类有语义证明的 choice formation contract**；
5. 优先寻找 genuinely different tactics，而不是同一种 file write 的形式变化；
6. 在扩大 authority 前先写 negative/fail-closed tests；
7. 保持 current args ownership、anti-replay、L3 gates、independent verification 和 privacy-safe learning；
8. 完成 code → tests → CI → docs → HANDOFF 后再推进下一 slice。

不要为了“更像 agent”添加 planner tree。判断标准仍然是：

> **这样是否让持续存在的 ZN Self 更能基于现实形成、验证并内化自己的能力。**
