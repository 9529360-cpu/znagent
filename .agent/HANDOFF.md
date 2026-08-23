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

> **ZN uses models. Models do not own ZN.**

本阶段完成的是第一类 exact-text resident choice 的 ownership / safety 加固：ZN 在一个严格可证明的 append 场景中，不再要求 caller 预先提供最终 `text_equals.expected_text`，而是可以从当前完整文件观察 + 当前 append 内容推导 transient exact postcondition，并继续通过独立 Body read 验证结果。

同时修复了 procedural learning 中 append / replace 可能被同一 `write_text` 形状混合的安全缺口：L1/L2/L3 现在保留 privacy-safe `action_variant = append | replace` 边界，历史无 variant 的真实聚合候选在 L3 fail closed 为 `untested`。

这仍然不是第二个 genuinely different tactic class，也不是 general planner 或 general postcondition synthesizer。

## 当前分支 / HEAD / CI

- 固定开发分支：`dev/zn-agent`
- `main`：未修改；M10 未满足
- 本阶段恢复时 dev HEAD：`299380171b3dc419b269b07934cb37828d70f95f`
- 本阶段最终 code/test SHA：`04e95009a9b2277704d57bc3dd141748a91df772`
- code/test CI：run `32648983622`
  - `ZN Kernel / Python = success`
  - locked repository deps = success
  - isolated `runtime/python` install = success
  - zero-model isolated runtime boot = success
  - `agent/kernel` compile = success
  - full kernel unittest discovery = success
  - `Electron / TypeScript = success`
  - desktop typecheck/bundle/ownership/update/handoff tests = success
  - release-channel/runtime staging/packaged-artifact verifier tests = success
  - `Container / Runtime Smoke = skipped`（normal push workflow contract）
  - `Publish commit statuses = success`
- implementation-status docs commit：`edfabf0d0233c1f5275ff385213e1dc0bf5fd078` (`[skip ci]`)
- 本 HANDOFF commit 也是 docs-only `[skip ci]`；提交后它会成为新的 dev HEAD。下一维护者必须重新读取真实 branch ref，不能把上述 SHA 当未来 HEAD 的替代品。

中间 run `32648935424`（SHA `2e334322...`）因后续连续 push 被 workflow concurrency 取消，不是最终验证结果；最终 code/test run `32648983622` 已双绿。

## 本阶段恢复的真实现场

开始前重新读取并核对：

1. `ZN.md`
2. `AGENTS.md`
3. `docs/ZN-IMPLEMENTATION-STATUS.md`
4. `docs/ZN-SOURCE-EXTRACTION.md`
5. `docs/ZN-SELF-MAINTENANCE.md`
6. `.agent/HANDOFF.md`
7. `docs/ZN-MEMORY-LEARNING.md`
8. `docs/ZN-NEXT-PHASE.md`
9. `dev/zn-agent` HEAD / open PR / recent commits / CI / main relation
10. `Will → IntentionFormation → Investigation → Action → Body → verification → VerifiedExperience → L2/L3` 真实调用链

恢复时确认：

- dev HEAD = `299380171b3dc419b269b07934cb37828d70f95f`；
- open PR = 0；
- previous code/test SHA `920bd708...` 的 run `32647895984` Python/Electron 双绿；
- `main` 仍是 initial baseline `61dd880aa4bbbdb359ca544b752afc2c22845ce9`；
- M8 AppImage run `32645354818` 仍是 installed continuity smoke cancelled，不得写成 success。

## 本阶段真实调用链与实现

### 1. Resident derives one narrow exact postcondition

`agent/kernel/action.py`

`NativeActionIntent` 现在可以携带 `expected_outcome`。这是 current-event working cognition，不是 procedural memory。

`current_text_equals_postcondition(event, intent, facts)` 的当前语义：

```text
if explicit event expected_outcome exists:
    explicit contract remains authoritative
else if current intent == write_text append:
    require concrete non-empty append content
    require matching complete, untruncated file preview
    if path fact exists, require existing file target
    derive expected_text = observed_current_text + current_append_content
else:
    no derived exact postcondition
```

只有上述证明成立时，原 first-slice exact-text choice 可以由当前 ZN 自己形成：

```text
A = append current delta
B = replace with derived exact final text
```

两者仍使用当前 event/path/content，不从 memory 取 raw args。

### 2. Verification ownership remains with current reality

`agent/kernel/procedural_resident.py`

当 caller 没有显式 `expected_outcome` 时，active runtime 可以读取当前 intent 携带的 resident-derived exact-text contract；它会先验证 contract target 与当前 write target 一致，再进入既有 `native_verification`。

真正完成仍是：

```text
Body movement
→ independent Body read_text
→ exact text comparison
→ only then complete / positive learning
```

Body success 不是 final proof。

显式 task-level `expected_outcome` 始终优先，不会被 resident-derived contract 覆盖。

### 3. Fail-closed boundary

不会推导 final state / 不会扩大 choice authority 的情况包括：

- missing preview；
- truncated preview；
- empty append content；
- incompatible/missing observed file target；
- explicit unsupported/malformed expected outcome；
- free-text tactic speculation；
- procedural memory/model output 试图提供 raw path/content/args。

### 4. Append / replace learning separation

`agent/kernel/verified_experience.py`

privacy-safe exact-text expected summary 新增：

```text
action_variant = append | replace
```

不会存 raw path/content。

L1 `group_key` 加入 variant。

`agent/kernel/procedural_tendency.py`

L2 compatibility 也加入 variant，并暴露 bounded applicability metadata：

```text
stable_action_variant
action_variant_variants
```

`agent/kernel/procedural_applicability.py`

freshly aggregated write candidate 必须与当前 intent variant 匹配：

- replace candidate + current append → `mismatch`；
- append candidate + current replace → `mismatch`；
- retained legacy L1 records without variant → new aggregation has marker but no stable variant → L3 `untested`；
- 旧手工 unit fixture 若完全没有新 metadata marker，保留原 fixture scope，不把它当真实新聚合 evidence。

当前 positive L3 influence gate 仍只允许 exact non-append replacement；本阶段没有扩大 append/command authority。

## 新增测试

### `tests/agent/kernel/test_resident_derived_postcondition.py`

覆盖：

1. no caller expected_outcome + full preview → resident derives exact final state and forms 2 `resident_choice`；
2. missing preview → one historical append intent, no invented postcondition；
3. truncated preview → one historical append intent, no invented postcondition；
4. active resident end-to-end：

```text
current file = prefix-
caller requests append suffix
caller does NOT provide expected_outcome
→ Investigation reads full file
→ resident derives prefix-suffix
→ Body append
→ independent read_text verifies prefix-suffix
→ ExecutionPath.BODY success
→ 0 model calls
→ one verified L1 episode marked action_variant=append
```

L1 safe expected summary 不含 raw target path。

### `tests/agent/kernel/test_procedural_action_variant.py`

覆盖：

- append / replace evidence 即使故意共享 legacy group_key 也会形成两个 L2 candidates；
- cross-variant applicability = mismatch；
- legacy no-variant write evidence = untested。

## 本阶段修改文件

Code:

```text
agent/kernel/action.py
agent/kernel/procedural_resident.py
agent/kernel/verified_experience.py
agent/kernel/procedural_tendency.py
agent/kernel/procedural_applicability.py
```

Tests:

```text
tests/agent/kernel/test_resident_derived_postcondition.py
tests/agent/kernel/test_procedural_action_variant.py
```

Docs:

```text
docs/ZN-IMPLEMENTATION-STATUS.md
.agent/HANDOFF.md
```

没有修改：

- `ZN.md`：架构方向未变化；
- `docs/ZN-SOURCE-EXTRACTION.md`：没有 Hermes extraction state 变化；
- `docs/ZN-SELF-MAINTENANCE.md`：没有 self-maintenance architecture 变化；
- `main`。

## 关键 commits

```text
1ca91c1c9937aad42e323b4dbcfbf8ee5d903922  feat: let resident carry derived action postconditions
dbb14b8291a7caab49f38069427e5a00c30e9099  feat: verify resident-derived text goals
275eebcc92f027d73572f09142d8393b381945ef  fix: separate text action variants in learning
32a147a4237540cb290cfa2a350f38add0236940  fix: preserve action variant in procedural tendency
a609f200f6e1380f2777febd4a271a03a1b33ec7  fix: gate procedural influence by write variant
2e33432204c39fe5486856381decc21f52a78e90  test: prove resident-derived append postconditions
91d94c1a6969b157e5749628eae7d63c2996c889  test: preserve legacy candidate fixtures while old records fail closed
04e95009a9b2277704d57bc3dd141748a91df772  test: enforce procedural write variants
edfabf0d0233c1f5275ff385213e1dc0bf5fd078  docs: record resident-derived postcondition slice [skip ci]
```

## 真实测试 / CI

权威最终 CI：run `32648983622`, code/test SHA `04e95009a9b2277704d57bc3dd141748a91df772`。

```text
ZN Kernel / Python          success
Electron / TypeScript      success
Container / Runtime Smoke  skipped
Publish commit statuses    success
```

Python job `97217531258`：isolated runtime install、zero-model boot、compile、full kernel unittest discovery 全部 success。

Electron job `97217531266`：dependency install、typecheck、bundle、ownership/update/handoff/release verifier tests 全部 success。

本环境没有完整 private-repo checkout，因此没有把 synthetic local checks 冒充 repository integration。真实集成结果以上述 GitHub Actions 为准。

## 当前仍未完成 / 不得误报

- 第二个 genuinely different resident-owned semantic choice contract；
- broader Will/Investigation-driven alternative formation beyond exact-text file writing；
- commands / Git / browser / arbitrary side-effect tactic formation；
- general reliable high-level postcondition derivation；
- learned multi-step tactic trees；
- model-free general planner；
- broad candidate influence over commands/arbitrary side effects；
- raw action replay from procedural memory；
- mature procedural skills / fast path；
- practical Git mutation + diff/test/reality verification；
- GitHub repo/PR/CI resident-owned sense；
- learned engineering competence；
- browser Body/Senses seam and learned computer-use competence；
- growth benchmarks proving lower model dependence without lower verification quality；
- autonomous outbound artifact nomination；
- Telegram media-specific outbound transports；
- successful installed AppImage N → N+1 continuity；
- SM1+ self-maintenance。

## 风险 / 阻塞

Core lane 当前无已知 CI blocker。

主要设计风险仍是过早泛化 semantic choice formation：不能把 task 中两个动词、model 的建议、memory 中熟悉 route 或 command 字符串解析，当成“两个动作一定实现同一个目标”的证明。

本阶段额外封住一个风险：append 与 replace 虽然都叫 `write_text`，但因副作用语义不同，procedural evidence 不能再默认互通。

M8 updater debt 未变化：run `32645354818` 的 real installed AppImage updater continuity smoke cancelled；两版 AppImage build success，但 continuity 没有 success 证据。后续切回 M8 时先读 diagnostics/logs，不要降低 integrity gates。

## 下一真实目标

Fresh restore 后：

1. 重新读取所有必读文档和真实 dev HEAD/CI/diff；
2. 继续从 `NativeWill` / `NativeIntentionFormation` / Investigation facts 找**第二个 genuinely different tactic class**；
3. 优先选择有独立 current-world verifier、且能证明两个 tactics 目标等价的工程能力契约；
4. command/Git 是有价值方向，但不能靠解析 shell 文本猜 mutation/result；
5. authority 扩大前先补 negative tests：missing/stale evidence、ambiguous equivalence、unsafe side effect、contradiction 必须 fail closed；
6. 保持 current args ownership、action-variant boundary、anti-replay、L3 gates、independent verification、privacy-safe learning；
7. 完成 code → tests → real CI → docs → HANDOFF 后，再称该 slice 完成。

不要为了看起来更“agentic”添加 planner tree。判断标准仍然是：

> **这样是否让持续存在的 ZN Self 更能基于当前现实形成、验证并内化自己的能力。**
