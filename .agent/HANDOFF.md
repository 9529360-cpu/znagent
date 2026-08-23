# ZN Agent Handoff

更新时间：2026-08-23

## 当前目标

开发主线是 **ZN 核心复杂任务执行能力**：

```text
durable ZN Self
+ mature Agent-level task execution depth
+ reality-based verification
```

目标不是 `LLM -> planner -> tools -> agent`，而是让同一个持续存在的 Self 把复杂现实任务持续推进到经过证据验证的结果。

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
- 当前 code/test HEAD：`5ebb233a97969a9e93c6399615beb48ff6ae9f41` (`test: cover explicit command postconditions`)
- 本 HANDOFF 是 docs-only `[skip ci]` 提交；下一维护者必须重新读取远程 `dev/zn-agent` 最终 HEAD。
- `main` 未修改。

## 本轮恢复的真实现场

已重新读取并核对：

- `ZN.md`
- `AGENTS.md`
- `docs/ZN-IMPLEMENTATION-STATUS.md`
- `docs/ZN-SOURCE-EXTRACTION.md`
- `docs/ZN-SELF-MAINTENANCE.md`
- `docs/ZN-NEXT-PHASE.md`
- `.agent/HANDOFF.md`

已检查：

- 开始时 `dev/zn-agent == 61129e09876723232fb3f73891cd9e03969b74ce`；
- 无 open PR；
- `main` untouched；
- 当前执行环境仍没有可用本地 repo checkout，因此验证以 GitHub CI 为准。

## 已真实 CI 验证的上一核心切片

code/test source：

```text
47ccd5601462641c50c16ec76f2a05085a33f9f3
test: require reality verification after native writes
```

真实 CI：

```text
ZN Kernel / Python      success
Electron / TypeScript  success
Actions run             32612456040
```

因此以下现在可以正式视为 verified，而不再是 pending：

1. structured read-only Git repository sense，包括 root/branch/HEAD/upstream/ahead-behind/changed/staged/unstaged/untracked/conflicted paths；
2. active embodied investigation 使用 `NativeBody.git_state` 的 `changed_paths` 回答真实 changed files；
3. non-append `write_text` 的 durable post-action verification：Body write success 不直接完成 event；
4. `native_verification` 是持久化 resident stage，并形成 `verify_action` Thought；
5. verification 会重新 `read_text` 当前现实，只有 exact postcondition 成立才 complete；
6. action 后、verification 前重启仍恢复同一 event 且不重复 write；
7. postcondition 被现实反证时回到 investigation，并阻止 identical action blind replay。

## 当前新增切片：explicit command postconditions

实现提交：

```text
5cc0b1bccca976a8c635fbf3ddd7f95912a4cdc6
feat: verify explicit command postconditions
```

测试提交：

```text
5ebb233a97969a9e93c6399615beb48ff6ae9f41
test: cover explicit command postconditions
```

真实 active call chain 仍是：

```text
resident event / WorkingState
-> Situation / Thought
-> native investigation
-> native deliberation
-> NativeActionIntent
-> NativeBody.act(command)
-> BodyActionResult
-> native_verification
-> verify_action Thought
-> NativeBody.act(command verification probe)
-> verification evidence
-> complete OR investigation/failure recovery
```

事件现在可以显式声明：

```text
expected_outcome:
  kind: command
  command: <independent verification command>
  exit_code: <expected code, default 0>
  output_contains: <optional string/list>
  workdir: <optional, defaults to action workdir>
```

语义：

```text
primary command exit 0
!= task success

primary action success
-> persist expected_outcome
-> later resident pulse performs independent verification command
-> compare observed exit code/output with expected state
-> verified only then complete
```

验证失败时：

- 保存 `native_verification_result`；
- 将明确失败证据写回 `local_failure`；
- 回到 native investigation；
- 将原 primary action signature 标记为已失败，避免盲目重放同一 primary command；
- `model_policy=never` 时最终必须 truthful unresolved/failure，而不是假装成功。

新增 `tests/agent/kernel/test_command_verification.py` 覆盖：

1. primary command 成功后仍进入 `native_verification`；
2. verification command exit/output 满足 expected outcome 后才完成；
3. command verification stage 跨 resident restart 持久存在，primary command 不重复；
4. verification exit/output 不满足时回 investigation，primary command 不盲目重放。

## 当前 CI

上一切片 `47ccd560...` 已真实 green，见上。

当前最新 code/test SHA：

```text
5ebb233a97969a9e93c6399615beb48ff6ae9f41
```

本 HANDOFF 写入前查询 combined status 仍为：

```text
statuses: []
```

所以 **explicit command postconditions 仍是 PARTIAL / NOT CI-VERIFIED**。

下一维护动作必须先读取 `5ebb233...` 的真实 CI：

- 若 Kernel/Python 失败，读取 job/log 并修到 green；
- 若 green，再更新 `docs/ZN-IMPLEMENTATION-STATUS.md`，记录 first command-level independent verification contract；
- 不得把 generic command verification 写成“复杂任务完成语义已经全部解决”。

## 当前能力边界

已 verified：

- persistent Self / resident continuity；
- durable event / WorkingState；
- multi-pulse Investigation；
- Body action intents；
- failed action evidence/recovery；
- non-append text action -> independent reality verification；
- structured read-only Git repository sense。

本轮 pending：

- explicit command -> independent command postcondition verification。

仍 PARTIAL / MISSING：

- 自动从高层用户目标推导可靠 task-level postconditions；
- multi-step goal/subgoal completion semantics；
- long-horizon recovery beyond current bounded probes/actions；
- safe Git mutation + verification；
- GitHub repository/PR/CI resident-owned sense；
- browser body/sense；
- mature visual + mouse/keyboard computer use；
- real complex-task benchmark suite；
- SM1+ self-maintenance implementation。

## UI / Desktop / Release 边界

- 不做 cosmetic UI polish / layout churn / dashboard expansion；
- desktop 只在核心能力授权、evidence、browser/computer-use、maintenance approval 或真实 blocking usability defect 需要时进入；
- M8/release 仍保留，但不抢占核心主线；
- full installed updater handoff、Windows/macOS clean-install/login、signing/notarization 仍是明确 release debt。

## 风险 / 阻塞

- 当前 command verifier 尚未有真实 CI 结果；
- `expected_outcome.command` 当前是显式结构化 task contract，不是让模型文本直接变 shell；
- generic shell exit 0 仍然只有在存在可靠 expected outcome 时才能区别 action success 与 goal success；
- Git/GitHub mutation、自维护写路径必须保持权限/branch/diff/test/rollback 边界；
- identity/memory/credential/updater/rollback/self-maintenance permission 高风险修改仍需人工批准；
- `main` untouched。

## 下一步

1. 读取 `5ebb233...` 真实 CI；
2. CI fail -> 读取 job/log -> 修复 -> 再 CI；
3. CI green -> 更新 `docs/ZN-IMPLEMENTATION-STATUS.md` 和 HANDOFF；
4. 下一 execution-spine 重点不是增加更多 command 类型，而是让 resident 能从真实 task/evidence 中维护明确的“当前目标 / next gap / expected outcome / verification result”；
5. 随后进入 practical Git repository action + verification，再补 GitHub PR/CI read-only sense；
6. 用真实“陌生 repo + failing CI -> diagnosis -> fix -> test -> diff -> evidence” benchmark 驱动后续能力；
7. UI 暂停，`main` 不动。
