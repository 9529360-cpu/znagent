# ZN Agent Handoff

更新时间：2026-08-23

## 当前目标

开发主线：

```text
durable ZN Self
+ mature Agent-level complex-task execution depth
+ reality-based verification
```

不是 `LLM -> planner -> tools -> agent`。同一个 resident Self 必须持续拥有目标、调查、动作、反证、恢复和最终完成判断。

当前优先级：

1. durable complex-task execution spine；
2. action -> reality verification + failure recovery；
3. practical Git + GitHub/repository work；
4. browser body/sense；
5. visual/computer use；
6. real complex-task benchmark；
7. 更强执行脊柱上的 SM1+ self-maintenance。

纯 UI/desktop polish 暂停。M8/release 是 bounded lane。

## 当前分支 / HEAD

- 分支：`dev/zn-agent`
- 最新真实 code/test SHA：`f280c8f68af69dfc2ac10b94d8d83726c10aa14e`
- implementation-status docs commit：`5b5798e2e451c2d55da35b00f29f33685d53b15f` (`[skip ci]`)
- 本 HANDOFF 也是 docs-only `[skip ci]`；下一维护者必须重新读取远程 `dev/zn-agent` 最终 HEAD。
- `main` 未修改。

## 已恢复并核对的真实现场

本阶段重新读取：

- `ZN.md`
- `AGENTS.md`
- `docs/ZN-IMPLEMENTATION-STATUS.md`
- `docs/ZN-SOURCE-EXTRACTION.md`
- `docs/ZN-SELF-MAINTENANCE.md`
- `docs/ZN-NEXT-PHASE.md`
- `.agent/HANDOFF.md`

并检查：

- `dev/zn-agent` HEAD；
- open PR：无；
- 相关 diff；
- normal CI；
- active resident call chain；
- `main` untouched。

当前执行环境仍无可用本地 private-repo checkout，所以不宣称本地 test run；真实验证来自 GitHub CI。

## 已真实 CI 验证：Git sense + first post-action verification

source：

```text
47ccd5601462641c50c16ec76f2a05085a33f9f3
```

CI：

```text
ZN Kernel / Python      success
Electron / TypeScript  success
run                     32612456040
```

Verified：

- `NativeBody.git_state` structured read-only repository evidence：root / branch / HEAD / detached / upstream / ahead-behind / dirty / changed / staged / unstaged / untracked / conflicted；
- embodied investigation 通过正式 Body contract 使用 `changed_paths`；
- non-append `write_text` 成功后不直接 complete；
- durable `native_verification` stage + `verify_action` Thought；
- later Body `read_text` re-observation 后 exact match 才 complete；
- verification stage 跨 resident restart；
- reality contradiction 返回 investigation；
- identical failed action 不 blind replay。

## 已真实 CI 验证：explicit command postconditions

主要实现：

```text
5cc0b1bccca976a8c635fbf3ddd7f95912a4cdc6  feat: verify explicit command postconditions
8a661a376bd0d24dc2eea5dbe4187a159a8f4df1  feat: surface verification evidence in resident thought
f280c8f68af69dfc2ac10b94d8d83726c10aa14e  test: fix command verification shell contract
```

真实 CI：

```text
ZN Kernel / Python      success
Electron / TypeScript  success
run                     32621596489
```

Active chain：

```text
resident event / WorkingState
-> Situation / Thought
-> native investigation
-> native deliberation
-> NativeActionIntent(command)
-> NativeBody.act(command)
-> primary BodyActionResult
-> native_verification
-> verify_action Thought
-> NativeBody.act(independent verification command)
-> observed exit/output evidence
-> complete OR investigation/failure recovery
```

事件可显式声明：

```text
expected_outcome:
  kind: command
  command: <independent verification command>
  exit_code: <expected code, default 0>
  output_contains: <optional string/list>
  workdir: <optional>
```

Verified semantics：

```text
primary command success
!= task success

primary command success
-> persist postcondition
-> later Thought independently verifies current reality
-> verified only then complete
```

失败时：

- `native_verification_result` 保存反证；
- `local_failure` 保存明确原因；
- stage 返回 `native_investigation`；
- primary action signature 阻止 identical blind replay；
- 下一 pulse 的 `CognitiveSituation` 直接看到 `last_verification_*`；
- 下一 Thought 立即把 verification failure 视为 unknown/evidence，而不是继续把 primary action success 当目标成功。

## 本轮 CI 失败与修复记录

早期 command test SHA `5ebb233...`：

```text
Electron / TypeScript  success
ZN Kernel / Python      failure
run                     32621385427
```

真实日志显示两个测试问题：

1. POSIX 上使用 `subprocess.list2cmdline` 构造无空格 `python -c` 代码，shell quoting 错；
2. 成功完成后 `_complete_result()` 正常把 WorkingState 归 idle，测试错误地从 completed WorkingState 读取 verification result。

修复：

- Windows 用 `subprocess.list2cmdline`，POSIX 用 `shlex.join`；
- 成功路径通过 durable Body action history + event outcome 判断实际完成，不假设 completed WorkingState 保留活动态数据；
- 同时新增 verification contradiction 直接进入 next Situation/Thought 的回归。

最终 `f280c8f...` 已 green。

## 当前真实执行脊柱判断

### Verified foundation

- persistent Self / zero-model life；
- durable event / WorkingState；
- Investigation 跨 pulse/restart；
- NativeActionIntent / BodyActionResult；
- failed body action evidence；
- exact text postcondition independent verification；
- explicit command postcondition independent verification；
- verification contradiction immediate Situation/Thought feedback；
- structured read-only Git repository sense；
- bounded external cognition remains a resource, not owner。

### 仍 PARTIAL / MISSING

- high-level goal -> reliable postcondition derivation；
- durable explicit `current goal / current gap / expected outcome / verification result` as a compact task-level contract；
- multi-step task/subgoal execution and tactic changes over many actions；
- successful completed-task verification evidence as a first-class event audit object（当前可以由 event outcome + durable Body action history重建，但尚未有独立 verification report object）；
- verification failure 后形成 genuinely different recovery action，而不只是避免 blind replay / truthful failure；
- safe Git mutation + diff/test/reality verification；
- GitHub repo/PR/CI resident-owned read sense；
- browser；
- mature visual/mouse/keyboard computer use；
- complex-task benchmark suite；
- SM1+ self-maintenance。

## UI / Desktop / Release 边界

- 不做 cosmetic UI polish / layout churn / dashboard expansion；
- desktop 只在核心能力授权、evidence、browser/computer-use、maintenance approval 或 blocking usability defect 需要时进入；
- M8/release 保留 explicit debt，不抢核心主线；
- full installed updater handoff、Windows/macOS clean-install/login、signing/notarization 仍未 complete。

## 风险 / 阻塞

- generic shell exit `0` 仍不等于任意高层目标成功；只有存在可靠 postcondition 时才有任务级验证语义；
- 当前 explicit command expected_outcome 是结构化 event contract，不是模型文本直接进入 shell；
- stale verification-result 生命周期需要在未来多动作循环中继续注意，不能让旧反证污染已形成的新动作；
- Git/GitHub mutation、自维护写路径必须有权限/branch/diff/test/rollback 边界；
- identity/memory/credential/updater/rollback/self-maintenance permission 高风险修改仍需人工批准；
- `main` untouched。

## 下一真实目标

1. 继续 execution spine，而不是增加 UI；
2. 让一个 durable event 以紧凑结构明确保存：原始 goal、当前 gap、当前 expected outcome、最近 verification evidence；
3. 这些字段必须参与 Situation/Thought，并跨 pulse/restart，不做 ever-growing planner/task DB；
4. 处理多动作生命周期，确保新的不同 action 开始后旧 verification verdict 不错误污染当前 Situation，同时历史失败证据仍能由 Investigation/Nervous state使用；
5. 在此基础上做 practical Git mutation + diff/test/reality verification；
6. 再加入 GitHub PR/CI read-only sense；
7. 用真实 benchmark：陌生 repo + failing CI -> 调查 -> 修复 -> test -> diff/state -> evidence；
8. `main` 不动。
