# ZN Agent Handoff

更新时间：2026-08-23

## 当前目标

```text
durable ZN Self
+ mature Agent-level complex-task execution depth
+ reality-based verification
+ resident-owned learning / procedural competence
```

核心原则：

> **ZN uses models. Models do not own ZN.**

桌面 UI 当前由独立协作者推进；本维护 lane 只推进 ZN core，不把 UI 变化混进 core authority / verification 工作。

当前 core engineering lane 已完成第一条 **resident-owned targeted-test identity formation**：对 ZN 自己的 top-level `agent/kernel/<module>.py` tracked exact replacement，resident 可以只依赖当前仓库证据形成唯一 mirrored Python unittest identity，而不是要求 caller/model/memory 提供 test path 或 shell command。

这仍不是通用测试发现器、任意 command verifier、通用 mutation engine 或 model-owned planner。

## 当前分支 / HEAD / CI

- 固定开发分支：`dev/zn-agent`
- 本阶段恢复时 exact dev HEAD：`ccd1b05f021f32bc479ad22b81fb5a5eca25b185`
- 本阶段权威 code/test SHA：`20e7431e74f2c87f631564d7d8f1119057474dfc`
- 权威 code/test CI：run `32663996928`
  - `ZN Kernel / Python = success`
  - `Electron / TypeScript = success`
  - `Container / Runtime Smoke = skipped`（normal push contract）
  - `Publish commit statuses = success`
- Python job：`97254463582`
  - locked repository deps = success
  - isolated `runtime/python` install = success
  - zero-model isolated runtime boot = success
  - kernel compile = success
  - full kernel unittest discovery = success
- Electron job：`97254463704`
  - locked install = success
  - typecheck = success
  - bundle = success
  - ownership/runtime/update/handoff/release verifier suites = success
- 本阶段 first failing code/test run：SHA `f13707c70fe0f1e5f8792985d457293a476e2a61`, run `32663836403`
  - Electron success
  - Python failure：3 failures + 1 error，全部来自新 recovery/authority test fixtures 使用 `- run:` inline YAML，而 production proof deliberately 只承认当前真实 `zn-ci.yml` 的独立 `run:` executable step；实现正例、旧 explicit targeted-test suite、repo-delta suite、isolated runtime boot/compile 均已通过。
  - 修复方式是把 fixtures 对齐当前真实 CI shape，没有放宽 runtime authority parser。
- `main` 必须保持 `61dd880aa4bbbdb359ca544b752afc2c22845ce9`；M10 未满足，禁止修改。
- 本 HANDOFF 为 docs-only `[skip ci]`；最终维护者必须重新读取 exact `dev/zn-agent` HEAD 并以 Git 为准。

## 本阶段恢复的真实现场

开始修改前重新读取/检查：

1. `ZN.md`
2. `AGENTS.md`
3. `docs/ZN-IMPLEMENTATION-STATUS.md`
4. `docs/ZN-SOURCE-EXTRACTION.md`
5. `docs/ZN-SELF-MAINTENANCE.md`
6. `.agent/HANDOFF.md`
7. exact `dev/zn-agent` HEAD
8. main relation / open PR / previous CI / recent commits
9. `Investigation -> resident action formation -> procedural resident -> native_action -> independent verification -> VerifiedExperience` 调用链
10. `NativeBody.git_diff` / `read_text` / command execution / restart semantics / packaged runtime mapping

恢复时事实：

- dev HEAD = `ccd1b05f021f32bc479ad22b81fb5a5eca25b185`
- previous authoritative code/test = `4a7e7311ecc1feaff97ea6b6bbe31ab94a9ab666`
- previous run = `32662600128`, Python/Electron 双绿
- main = `61dd880aa4bbbdb359ca544b752afc2c22845ce9`
- dev ahead main = 612，behind = 0
- open PR = 0
- M8 installed AppImage N -> N+1 continuity remained unverified from cancelled run `32645354818`

## 本阶段核心设计

### Resident-owned test identity authority

自动 identity 只在下面这个窄合同尝试形成：

```text
current tracked exact replacement target = agent/kernel/<module>.py
+ canonical mirror = tests/agent/kernel/test_<module>.py
+ current test file is a regular non-symlink tracked clean file on same root/HEAD
+ test source has a module-level direct AST import edge to agent.kernel.<module>
+ test source exposes >=1 top-level unittest.TestCase with test_* method
+ current .github/workflows/zn-ci.yml is a regular non-symlink tracked clean file on same root/HEAD
+ current CI text contains the exact kernel unittest suite in an executable one-line run: step
-> resident may form python_unittest identity
```

关键边界：

- 只承认 `agent/kernel/<module>.py` -> `tests/agent/kernel/test_<module>.py` 这一条 current ZN kernel mirror convention；
- nested/function/class/branch/try/dead-code import 不形成 target relation；
- 注释/字符串里的 module 名不形成 relation；
- 仅有 import 但没有 discoverable unittest case 不形成 execution authority，避免 `0 tests / exit 0` 假证明；
- CI 中仅有说明文字长得像 command 不形成 authority；必须是当前真实 executable `run:` field；
- initial evidence 缺失/不干净/不匹配时，不猜另一个测试、不调用模型、不执行 command，只保留原有 tracked repo-delta verifier；
- explicit typed `targeted_test` contract 继续优先走旧的严格验证路径，不被自动 discovery 改写。

### Durable/restart semantics

一旦 resident-formed identity 在 movement 前进入 `native_repo_text_baseline.targeted_test`，它就变成该 intent 的 required verifier：

- restart 后不能因为 event 原本没有 `targeted_test` 字段而静默降级回 repo-delta-only；
- verification 前重新证明 test + CI root/HEAD/path/tracked/clean/source semantics；
- test/CI evidence 在 movement 后漂移会 block execution 并返回 Investigation；
- test command 仍由已有 targeted-test verifier canonical render；caller/model/memory 没有 raw command authority；
- 已有 durable `native_targeted_test_execution=status=started` anti-replay 规则继续生效：interruption 后拒绝盲目再次执行可能有副作用的 test。

## 本阶段实现文件

```text
agent/kernel/repo_test_semantics.py
agent/kernel/repo_test_resident.py
agent/kernel/provider_bridge.py
tests/agent/kernel/test_repo_auto_targeted_test_verification.py
tests/agent/kernel/test_repo_auto_targeted_test_recovery.py
tests/agent/kernel/test_repo_auto_targeted_test_discovery.py
tests/agent/kernel/test_repo_test_semantics_authority.py
```

核心行为：

- `repo_test_semantics.py` 只做纯语义证明，不读文件、不执行命令；
- `RepositoryVerifyingResidentRuntime` 在现有 `ProcedurallyInfluencedResidentRuntime` 之上只增加 bounded repository verifier identity formation；
- `provider_bridge.build_resident_runtime()` 构造该 core resident，仍保留完整 world-aware resident inheritance chain；
- packaged `runtime/python` 仍通过既有 package mapping 使用 `agent/kernel`，CI 已证明 isolated zero-model boot/compile/test 无回归。

## Regression coverage

已覆盖：

- canonical top-level kernel target -> mirrored test identity；
- passing resident-formed test -> test command actually executes, current-world rechecks complete, zero model calls；
- failing resident-formed test -> Investigation + contradicted learning；
- missing mirrored test -> no guessed command，repo-delta verifier仍可完成；
- indirect/wrong target relation -> no execution authority；
- dead/nested import -> no relation；
- direct import but zero discoverable unittest cases -> no execution authority；
- changed CI contract -> no initial authority；
- misleading CI prose containing command text -> no authority；
- dirty test / dirty CI -> no initial authority；
- persisted resident-formed identity survives restart and remains required；
- test/CI evidence changed after movement -> no test execution + Investigation；
- existing explicit typed targeted-test verification suite remains green；
- existing exact-replace scoped repo-delta suite remains green。

## 真实 CI

最终 code/test SHA：

```text
20e7431e74f2c87f631564d7d8f1119057474dfc
```

run：

```text
32663996928
```

结果：

```text
ZN Kernel / Python     success
Electron / TypeScript success
Container smoke       skipped on normal push
Publish statuses      success
```

这是真实 push CI。当前环境没有 authenticated local checkout，因此本阶段不把本地测试写成通过；权威验证来自实际 GitHub Actions。

## 当前仍未完成 / 不得误报

- 自动 identity 只完成 ZN top-level kernel mirrored `unittest` 第一条约定，不是 general test discovery；
- 没有证明一个 mirrored test 对 target 的完整语义覆盖；当前只证明 direct module-level import + discoverable TestCase + current CI suite ownership；
- 非 Python unittest framework 尚无 resident-owned verifier identity contract；
- build/typecheck/lint verifier identity 尚未形成；
- append/untracked/staged/conflicted/rename/binary mutation stronger baseline/delta/test proof 尚未定义；
- general `mutation -> diff -> targeted test -> current reality` engineering loop 仍 partial；
- arbitrary command equivalence / arbitrary side-effect tactic synthesis 继续禁止；
- Git commit/push/reset/checkout/branch mutation authority；
- GitHub repo/PR/CI resident-owned sense；
- broader resident-owned tactic formation与成熟 engineering procedural fast path；
- browser Body/Senses、learned computer-use、growth benchmarks；
- M8 installed AppImage N -> N+1 updater continuity；
- Windows/macOS clean-install/login continuity；
- signing/notarization；
- SM1+ self-maintenance。

## 风险 / 阻塞

Core lane 当前无已知 CI blocker。

主要风险：

1. mirrored file naming 是当前 ZN repo convention，不应未经新的 current-reality proof 扩展到任意仓库；
2. `direct import + discoverable unittest` 仍不是 semantic coverage proof；下一阶段如果扩大 authority，必须有更强 repo-owned mapping/config/evidence，而不是猜；
3. test 可能有副作用，restart 继续使用 fail-closed no-replay，不宣称 idempotent；
4. 不能把 CI command recognition 扩成任意 YAML/shell parser 来方便自动执行；
5. model output、procedural memory、task prose、Body success、exit 0 单独都不是 authority/proof；
6. UI lane 与 core lane 分离，避免把 UI 协作者的改动当成 core competence evidence；
7. M8 release debt 继续独立。

## 相关文件

```text
agent/kernel/repo_test_semantics.py
agent/kernel/repo_test_resident.py
agent/kernel/procedural_resident.py
agent/kernel/provider_bridge.py
agent/kernel/body.py
agent/kernel/verified_experience.py
.github/workflows/zn-ci.yml
tests/agent/kernel/test_repo_auto_targeted_test_verification.py
tests/agent/kernel/test_repo_auto_targeted_test_recovery.py
tests/agent/kernel/test_repo_auto_targeted_test_discovery.py
tests/agent/kernel/test_repo_test_semantics_authority.py
tests/agent/kernel/test_repo_targeted_test_verification.py
docs/ZN-IMPLEMENTATION-STATUS.md
.agent/HANDOFF.md
```

本阶段没有修改：

```text
ZN.md
docs/ZN-SOURCE-EXTRACTION.md
docs/ZN-SELF-MAINTENANCE.md
main
```

原因：没有改变 ZN 产品/主体架构、Hermes extraction 状态或 self-maintenance architecture；只是实现既定 core direction 的下一条 bounded current-world verifier formation。

## 下一真实目标

Fresh restore 后：

1. 重新读取必读文档、exact dev HEAD、diff/PR/CI；
2. 保持当前 tracked exact-replace + explicit/auto Python unittest 的所有 gates 不变；
3. 调查下一条 **repo-owned structured verifier mapping**：优先寻找当前仓库明确配置/manifest/CI ownership 能证明的 verifier relation，而不是继续靠命名 convention 扩张；
4. 如果存在唯一且当前可证明的 mapping，先做 ambiguity/stale config/cross-target/symlink/dirty evidence/restart negatives，再给 execution authority；
5. 如果当前仓库没有足够结构证据，就转向另一条能被 current reality 严格证明的 engineering verifier consumer，不强造自动选择；
6. 不做 arbitrary command equivalence engine；
7. UI 与 M8 release lane 保持独立。

判断标准：

> **ZN 当前自己的 Senses / Investigation 必须先证明“为什么这个 verifier 属于这个变化”，然后才允许执行；模型会猜、文件名像、命令返回 0 都不够。**
