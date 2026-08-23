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

当前 core engineering lane 已从第一条 tracked exact-replace baseline/delta proof 向前完成一层：同一 bounded mutation 现在可以消费一个 **typed Python unittest identity**，但 command authority 仍属于 ZN。当前事件只允许提供 test identity；ZN 自己证明 test/root/HEAD/target 关系、自己生成 canonical unittest command、自己执行、自己在测试后重新检查 target/test 当前现实。

这仍不是自动测试选择器、通用 mutation engine、任意 command verifier 或 model-owned planner。

## 当前分支 / HEAD / CI

- 固定开发分支：`dev/zn-agent`
- 本阶段恢复时 exact dev HEAD：`dd13b903a1e817f6e8aec584be261be9834d5e82`
- 本阶段权威 code/test SHA：`4a7e7311ecc1feaff97ea6b6bbe31ab94a9ab666`
- 权威 code/test CI：run `32662600128`
  - `ZN Kernel / Python = success`
  - `Electron / TypeScript = success`
  - `Container / Runtime Smoke = skipped`（normal push contract）
  - `Publish commit statuses = success`
- Python job：`97250982542`
  - isolated `runtime/python` install = success
  - zero-model isolated runtime boot = success
  - kernel compile = success
  - full `tests/agent/kernel` unittest discovery = success
- Electron job：`97250982660`
  - locked install = success
  - typecheck = success
  - desktop bundle = success
  - ownership/runtime/update/handoff/release verifier suites = success
- implementation-status sync：`1b38d2f814d394aac587b8c702b47c78f82e3dbb` (`[skip ci]`)
- 本 HANDOFF 为 docs-only `[skip ci]`；提交后最终维护者必须重新读取 `dev/zn-agent` exact HEAD，并以 Git 真实 HEAD 为准。
- `main` 必须保持 `61dd880aa4bbbdb359ca544b752afc2c22845ce9`；M10 未满足，禁止修改。
- 本阶段恢复时 dev ahead main = 606，behind = 0；结束前必须重新对账最终 ahead/behind。
- 恢复时 open PR = 0；结束前必须重新检查。

## 本阶段恢复的真实现场

开始任何修改前已重新读取/检查：

1. `ZN.md`
2. `AGENTS.md`
3. `docs/ZN-IMPLEMENTATION-STATUS.md`
4. `docs/ZN-SOURCE-EXTRACTION.md`
5. `docs/ZN-SELF-MAINTENANCE.md`
6. `.agent/HANDOFF.md`
7. exact `dev/zn-agent` HEAD
8. main relation / open PR / recent commits / prior CI
9. `Investigation → action formation → procedural runtime → native_action → independent verification → VerifiedExperience` 真实调用链
10. `NativeBody.command` / terminal result normalization / scoped `git_diff` / working-state restart semantics

恢复时事实：

- dev HEAD = `dd13b903a1e817f6e8aec584be261be9834d5e82`
- previous authoritative code/test = `e78432be526fe628791a6350a97b0a9d16bd8623`
- previous run = `32660483679`, Python/Electron 双绿
- main = `61dd880aa4bbbdb359ca544b752afc2c22845ce9`
- dev ahead main = 606，behind = 0
- open PR = 0
- M8 installed AppImage N→N+1 continuity remained unverified from run `32645354818`

## 本阶段设计收敛

目标不是“让 caller 给 ZN 一条测试 shell command”。真实调用链审查后采用更窄的 authority contract：

```text
current tracked exact-replace mutation
+ typed targeted_test identity
+ current structured Git/test evidence
→ ZN validates identity and scope
→ ZN derives command
→ ZN executes through its Body
→ ZN re-observes current reality
```

明确拒绝：

- task text 中的 raw test/shell command；
- procedural memory 中的 raw command/path replay；
- `targeted_test.command` 或其他额外 authority 字段；
- cross-target test identity；
- wrong workdir；
- dirty/staged/untracked test file；
- stale HEAD / stale test evidence；
- unbounded timeout；
- arbitrary command equivalence。

首个 test family 只接受：

```text
kind = python_unittest
path = tests/**/test_*.py
for_path = exact current mutation repository-relative path
workdir = optional, but if present must resolve exactly to current Git root
timeout = optional bounded numeric value
```

## 本阶段实现

### 1. Typed targeted unittest verification

文件：`agent/kernel/procedural_resident.py`

提交：

```text
4b74f3c6a1038563b3a1403db7e7c1c160ff4a9a  feat: gate repo text replacement on targeted unittest [skip ci]
f3c22eeaa5db359a2b77e9869314be101aaef229  fix: prevent targeted unittest replay after interruption
```

关键合同：

1. 只在现有 tracked exact-replacement stronger proof 上启用；其他 mutation shape 请求 targeted test 会在 movement 前 fail closed。
2. test identity 必须是一个 literal repository-relative `tests/**/test_*.py` regular file，并且和 mutation target 的 `for_path` 精确绑定。
3. test file 必须和 target 同一 Git root、同一 HEAD、tracked、clean、非 truncated；baseline fingerprint 与 target baseline 一起持久化。
4. resume `native_action` 时 target/test baseline 都必须重新观察并精确匹配。
5. 写入后先证明 exact text + scoped repository delta，再重新证明 test evidence 没漂移。
6. command 由 ZN 固定生成：当前 Python executable + `-m unittest discover -s <test-dir> -p <test-file>`；caller 没有 command string authority。
7. terminal result 继续经过现有 deterministic normalization；timeout、non-zero exit、masked-success/failure evidence 都不能变成 success。
8. test 通过后再读取 target、scoped Git delta 和 test snapshot；test 自己改变 target/HEAD/test file 会使 verification 失败。
9. `VerifiedExperience` 的主 independent observation 仍是最终 current text observation；raw target/test path/command 不进入 learned procedural authority。

### 2. Targeted-test execution anti-replay

测试进程可能有副作用，不能假设 crash 后安全重跑。

在真正执行 test 前，WorkingState 会先 durable 写入：

```text
native_targeted_test_execution = {
  intent_id,
  kind=python_unittest,
  state_sha256=<test baseline fingerprint>,
  status=started,
  action_id=null
}
```

test 返回后，再 durable 写入 `status=completed` + Body action id + verifier verdict，然后才做 post-test reality checks。

如果 resident 在 `started` 之后中断，恢复 pulse 看到同一 intent 的 marker 会：

```text
refuse replay
→ verification contradiction
→ native_investigation
→ no second test execution
```

这是 fail-closed interruption semantics，不假装知道 crash 前 test 是否真正开始/完成。

### 3. Regression coverage

文件：`tests/agent/kernel/test_repo_targeted_test_verification.py`

提交：

```text
ad4650c133c2de52ecbbcd6fbd509680f1709e47  test: cover repo targeted unittest verification
4a7e7311ecc1feaff97ea6b6bbe31ab94a9ab666  test: refuse targeted unittest replay after restart
```

覆盖：

- tracked exact replace + passing targeted unittest → 只有全部 current-world proof 通过才 complete；
- zero model invocation；
- resident-generated unittest command；
- test file baseline / pre-exec / post-exec scoped Git observations；
- test failure → Investigation + contradicted experience；
- timeout → Investigation + contradicted experience；
- dirty test file → write 前 block；
- cross-target `for_path` → write 前 block；
- caller extra `command` authority → write 前 block；
- wrong workdir → write 前 block；
- persisted in-flight execution marker + runtime restart → refuse replay，无第二次 command；
- learned record 不保留 raw test path / target path。

## 真实 CI

最终 code/test SHA：

```text
4a7e7311ecc1feaff97ea6b6bbe31ab94a9ab666
```

run：

```text
32662600128
```

结果：

```text
ZN Kernel / Python     success
Electron / TypeScript success
Container smoke       skipped on normal push
Publish statuses      success
```

这是真实完整 push CI，不是局部测试推断。

## 当前仍未完成 / 不得误报

- resident **自动发现/形成 targeted-test identity** 尚未实现；当前 typed identity 来自 current event，然后由 ZN 独立验证；
- 非 Python unittest framework 尚未进入 verifier contract；
- build/typecheck/lint 等 broader engineering verifier 尚未进入 resident-owned bounded semantics；
- append baseline/retry semantics 尚未定义；
- untracked/staged/conflicted target stronger repo-delta/test proof 尚未定义；
- rename/binary 等 mutation/diff semantics 尚未定义；
- general `mutation → diff → targeted test → current-reality` engineering loop 仍 partial；
- broader resident-owned tactic formation beyond exact-text + single-path Git staging；
- arbitrary command equivalence / arbitrary side-effect tactic synthesis 继续禁止；
- Git commit/push/reset/checkout/branch mutation authority；
- GitHub repo/PR/CI resident-owned sense；
- mature engineering procedural fast path；
- browser Body/Senses + learned computer-use competence；
- growth benchmarks；
- installed AppImage N→N+1 updater continuity；
- Windows/macOS intended clean-install/login continuity；
- signing/notarization；
- SM1+ self-maintenance。

## 风险 / 阻塞

Core lane 当前无已知 CI blocker。

主要风险：

1. typed test identity 仍来自 current event；下一步不能简单把 task/model 文本里的文件名当 authority；
2. 一个 tracked clean test file 仍可能包含任意代码，因此执行 authority 必须继续由 typed bounded contract + current repository evidence约束，不能退化成“看到 test 就跑”；
3. test 可能有副作用；当前 restart contract 是 durable in-flight marker 后拒绝 replay，不是声称 test idempotent；
4. 不要把首个 `python_unittest` slice 抽象成 arbitrary command verifier；
5. append 非幂等，不能直接复用 exact-replace retry semantics；
6. model output、patch appearance、Body success、exit `0` 单独都不能替代 current verification；
7. M8 release debt 与 core lane 分开处理。

## 相关文件

```text
agent/kernel/procedural_resident.py
tests/agent/kernel/test_repo_targeted_test_verification.py
agent/kernel/body.py
agent/kernel/terminal.py
agent/kernel/result_semantics.py
agent/kernel/verified_experience.py
agent/kernel/action.py
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

原因：本阶段实现的是 ZN.md 已定义 core direction 的下一层 bounded verification，没有改变产品/主体架构；没有 Hermes extraction 状态变化，也没有改变 self-maintenance architecture。

## 下一真实目标

Fresh restore 后：

1. 重新读取必读文档、exact dev HEAD、diff/PR/CI；
2. 保持 tracked exact-replace + typed Python unittest 的现有 hard gates 不扩 scope；
3. 追真实 Investigation/project evidence，寻找一个 resident 可以**自己形成 test identity** 的最窄合同；
4. 优先利用当前仓库现实（tracked files、target relation、明确配置/映射、现有 structured evidence），不要从 free text 或 model output 推导 authority；
5. resident-formed identity 必须能独立证明 target relation、workdir、test family 和 bounded execution semantics；
6. ambiguity / multiple candidate / stale config / cross-target / symlink / dirty candidate / changed HEAD / restart 等 negatives 先于 positive authority；
7. 如果真实代码没有足够证据形成 test identity，就不要硬接自动选择；改做下一条能被当前现实严格证明的 engineering verifier consumer；
8. 不做 arbitrary command equivalence engine；
9. M8 updater continuity 保持独立 release lane。

判断标准：

> **不是“模型会不会猜哪个测试”，而是“ZN 当前自己的 Senses / Investigation 是否有足够现实证据形成一个可证明、可执行、可验证的 test identity”。**
