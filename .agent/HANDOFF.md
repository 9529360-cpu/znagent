# ZN Agent Handoff

更新时间：2026-08-23

## 当前目标

开发主线是 **ZN 核心复杂任务执行能力**，最终目标已经明确写入 `docs/ZN-NEXT-PHASE.md`：

```text
durable ZN Self
+ mature Agent-level task execution depth
+ reality-based verification
```

目标不是把 ZN 重新做成 `LLM -> planner -> tools -> agent`，而是让同一个持续存在的 Self 能把复杂现实任务持续推进到经过证据验证的结果。

当前优先级：

1. durable complex-task execution spine；
2. action -> reality verification + failure recovery；
3. practical Git + GitHub/repository work；
4. browser body/sense；
5. visual/computer use；
6. real complex-task benchmarks；
7. 在更强执行脊柱上继续 SM1+ self-maintenance。

纯 UI/desktop polish 暂停。M8/release 保留为 bounded lane。

## 当前分支 / HEAD

- 分支：`dev/zn-agent`
- 本 HANDOFF 写入前 code/test HEAD：`47ccd5601462641c50c16ec76f2a05085a33f9f3` (`test: require reality verification after native writes`)
- 本 HANDOFF 本身是 docs-only `[skip ci]` 提交，因此下一维护者必须重新读取 `dev/zn-agent` 最终 HEAD。
- `main` 未修改。

## 本轮恢复的真实现场

已重新读取：

- `ZN.md`
- `AGENTS.md`
- `docs/ZN-IMPLEMENTATION-STATUS.md`
- `docs/ZN-SOURCE-EXTRACTION.md`
- `docs/ZN-SELF-MAINTENANCE.md`
- `docs/ZN-NEXT-PHASE.md`
- `.agent/HANDOFF.md`

已检查：

- 开始时 `dev/zn-agent == 6c5d068cff5e4f961b908fdedf5eee3b5b3c137a`；
- 无 open PR；
- 上一 Git sense code/test SHA `90c3cde8619f698c8d1d67c63a6fa7b603a54ab2` 的真实 CI 后来出现：`Electron / TypeScript = success`，`ZN Kernel / Python = failure`；
- 失败日志证明原因是测试隔离：测试把 resident SQLite 放进临时 Git repo，SQLite 产生 `kernel.db-wal` / `kernel.db-shm`，而断言错误地假设只有 `kernel.db`；不是 `NativeBody._git_state()` 的 Git 状态逻辑失败。

当前执行环境仍没有可用的本地 repo checkout，之前 clone 因环境 DNS 无法解析 github.com，因此不能声明本地测试结果；以 GitHub CI 为真实验证。

## 本轮方向文档更新

提交：

```text
2337c894e3810b64ed1cbfc653de2c2c035bb0d3
docs: define Self plus complex-task execution target
```

`docs/ZN-NEXT-PHASE.md` 已明确：

- Self 与成熟 Agent 级复杂任务执行能力必须同时成立；
- action success != task success；
- model response / zero exit / successful syscall 都只是 evidence；
- resident-owned loop 应持续 Goal -> Situation -> Investigation -> expected result -> Action -> observation -> verification -> revise/continue -> verified Outcome；
- 外部模型只提供 bounded CognitiveIncrement，不能拥有 task continuity / action authority / truth；
- 第一主线先做 durable execution + verification，再扩 Git/GitHub/browser/computer use。

这是 priority / execution-contract 强化，未改变 `ZN.md` 既有 organism-first 所有权架构，因此本轮没有修改 `ZN.md`。

## 真实 active execution call chain

本轮重新追到：

```text
resident event / WorkingState
-> ZNResidentRuntime.live_once / run_once
-> orient
-> native_investigation
-> native_deliberation
-> EmbodiedResidentRuntime native_action
-> NativeBody.act(...)
-> BodyActionResult
-> Situation / next Thought
```

并确认：

- `InvestigationState` 已持久化 hypotheses / probes / evidence / facts / unresolved / next_probe / rounds；
- `EmbodiedLifeCore` 会把 working stage / investigation / action result / cognition increment / Will / nervous state带进 Situation；
- failed body action 已会回到 investigation，并用 action signature 阻止完全相同的盲目重试；
- **关键缺口**：本轮开始时 `_native_action_step()` 对任何 `BodyActionResult.success == True` 都会直接把整个 event 标记 complete。这意味着“动作 API 成功”仍被当成“目标完成”。

## 本轮实现

### 1. 修复 Git sense CI 测试隔离

提交：

```text
59957637a6840a6ce54e10b67ee5dc7bc0623867
test: isolate Git sense from resident sqlite files
```

`tests/agent/kernel/test_native_body.py` 现在把真实临时 Git repo 和 resident SQLite store 放在不同目录，Git changed_paths 只验证测试自己制造的 staged / unstaged / untracked 文件，不再受 SQLite WAL/SHM 生命周期影响。

### 2. Action success 不再自动等于 task success（首个可验证切片）

提交：

```text
7a30baea6b4a2471479152e2843c50c0c7279997
feat: verify body postconditions before task completion
```

`agent/kernel/embodied_resident.py` 新增持久化 `native_verification` stage。

当前首个明确支持的 postcondition 是非 append `write_text`：

```text
native investigation
-> derive write_text intent
-> Body write succeeds
-> persist expected text postcondition
-> native_verification
-> Body read_text current reality
-> exact compare

verified
-> task success

contradicted / observation failed
-> store verification evidence
-> native_investigation
-> block blind replay of identical action signature
-> continue failure recovery / truthful unresolved path
```

只有 postcondition 被当前 reality 重新观察并确认后，才 credit native outcome success 和 complete event。

未建立可靠 task-level verifier 的 action（例如 generic command、append）暂时保留旧 completion 行为；不能据此宣称通用 verification 已完成。

### 3. Verification 成为 resident Thought 阶段

提交：

```text
66f0fecc21b3cd7303c1f01b257095704f3454f4
feat: make post-action verification a resident thought stage
```

`agent/kernel/embodied_life.py` 现在把 `native_verification` 形成 `verify_action` Thought。

因此 verification 不是 `_native_action_step()` 内部偷偷做完的同步 if，而是一个可跨 pulse、可持久化、可跨 resident restart 的认知/身体阶段。

### 4. 回归测试

提交：

```text
47ccd5601462641c50c16ec76f2a05085a33f9f3
test: require reality verification after native writes
```

`tests/agent/kernel/test_native_action.py` 现在覆盖：

1. write 成功后 event 不完成，进入 `native_verification`；
2. 下一 Thought 是 `verify_action`，重新 `read_text` 后才完成；
3. 已经满足的目标仍可直接由 investigation evidence 完成，不产生多余 write；
4. action intent 在 action 前重启仍连续；
5. **action 已执行、verification 尚未执行时重启**，恢复同一 event 的 `native_verification`，验证后完成且不重复 write；
6. action 与 verification 之间现实被外部改写时，postcondition 被反证，回到 investigation，且 identical write 不盲目重放；
7. 原有 failed body action -> evidence -> no blind retry 行为继续保护。

## 当前 CI

上一 Git sense SHA 的真实失败已经定位并修复。

新的 code/test SHA：

```text
47ccd5601462641c50c16ec76f2a05085a33f9f3
```

本 HANDOFF 写入前多次查询该 SHA，GitHub combined status 仍为：

```text
statuses: []
```

因此当前状态仍是 **PARTIAL / NOT CI-VERIFIED**：

- 不得把 post-action verification slice 写成 CI complete；
- 不得更新 `docs/ZN-IMPLEMENTATION-STATUS.md` 为 verified，直到最新 code/test SHA 的真实 Kernel/Python CI green；
- 下一步首先读取当前 HEAD 和最新 code/test commit 的 CI；失败则读取 job/log 继续修。

## 当前能力边界

已经实际推进：

- persistent Self / resident continuity；
- durable event / WorkingState；
- multi-pulse Investigation；
- Body action intents；
- failed action evidence/recovery；
- **首个 durable action -> independent reality verification contract（non-append text state）**；
- structured read-only Git repository sense（代码已实现，最新修复仍待 CI）。

仍然 PARTIAL / MISSING：

- generic action postconditions；
- command/test/build success 的 task-level verification；
- multi-step goal completion semantics；
- long-horizon recovery beyond current bounded probes/actions；
- Git mutation + verification；
- GitHub repository/PR/CI resident-owned sense；
- browser body/sense；
- mature visual + mouse/keyboard computer use；
- real complex-task benchmark suite；
- SM1+ self-maintenance implementation。

## UI / Desktop / Release 边界

- 不做 cosmetic UI polish / layout churn / dashboard expansion；
- desktop 只在核心能力授权、evidence、browser/computer-use、maintenance approval 或真实 blocking usability defect 需要时进入；
- M8/release 仍保留，但不重新抢占核心主线；
- full installed updater handoff、Windows/macOS clean-install/login、signing/notarization 仍是明确 release debt。

## 风险 / 阻塞

- 最新核心实现尚无 CI status，不能宣称完成；
- 当前 verifier 只覆盖具有明确 exact text postcondition 的 replace/create write，不要泛化成“所有动作已验证”；
- generic shell exit 0 仍不等于复杂任务完成，是下一类 execution-depth 缺口；
- Git/GitHub mutation、自维护写路径必须保持权限/branch/diff/test/rollback 边界；
- identity/memory/credential/updater/rollback/self-maintenance permission 高风险修改仍需人工批准；
- `main` untouched。

## 下一步

1. 读取当前 `dev/zn-agent` HEAD 和 `47ccd560...` 对应真实 CI；
2. 若 Kernel/Python 失败，按 job/log 修到 green；
3. green 后更新 `docs/ZN-IMPLEMENTATION-STATUS.md` 和 HANDOFF，记录 verified Git sense + first post-action verification slice；
4. 下一 execution-spine 切片优先解决 command/test/build 类动作的“exit 0 != goal complete”：建立显式 expected outcome / verification evidence，而不是继续堆 tool；
5. 随后把 Git observation 扩成 practical repository investigation/action/verification，并补 GitHub PR/CI read-only sense；
6. 用真实“陌生 repo + failing CI -> diagnosis -> fix -> test -> diff -> evidence” benchmark 驱动后续能力缺口；
7. 保持 UI 暂停，`main` 不动。
