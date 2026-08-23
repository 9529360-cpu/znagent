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

纯 UI/desktop polish 暂停。M8/release 保留为 bounded lane。

## 当前分支 / HEAD

- 分支：`dev/zn-agent`
- 最新真实 code/test SHA：`aaa6fa55c5c4e1968006f618a37260cb4f41675a`
- 当前 implementation-status docs commit：`4bf052b5cc4e206a0da23cb1e61e937de466b4ee` (`[skip ci]`)
- 本 HANDOFF 为 docs-only `[skip ci]`；下一维护者必须重新读取远程 `dev/zn-agent` 最终 HEAD。
- `main` 未修改。

## 本阶段恢复的真实现场

已重新读取并核对：

- `ZN.md`
- `AGENTS.md`
- `docs/ZN-IMPLEMENTATION-STATUS.md`
- `docs/ZN-SOURCE-EXTRACTION.md`
- `docs/ZN-SELF-MAINTENANCE.md`
- `docs/ZN-NEXT-PHASE.md`
- `.agent/HANDOFF.md`
- `dev/zn-agent` HEAD / diff / open PR / normal CI
- active resident Investigation → Action → Body → Verification → Situation/Thought call chain

Open PR：无。

当前执行环境无可用本地 private-repo checkout，因此不宣称本地 test run；真实验证以 GitHub CI 为准。

## 已真实 CI 验证：Git sense + first post-action verification

Final source/test SHA：

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

- structured read-only `NativeBody.git_state`；
- active embodied Investigation 使用真实 `changed_paths`；
- non-append `write_text` success 不直接 complete；
- durable `native_verification` + `verify_action` Thought；
- Body re-read reality 后 exact match 才 complete；
- verification 跨 restart；
- contradiction 返回 Investigation；
- identical failed action 不 blind replay。

## 已真实 CI 验证：explicit command postconditions

主要 source/test：

```text
5cc0b1bccca976a8c635fbf3ddd7f95912a4cdc6  feat: verify explicit command postconditions
8a661a376bd0d24dc2eea5dbe4187a159a8f4df1  feat: surface verification evidence in resident thought
f280c8f68af69dfc2ac10b94d8d83726c10aa14e  test: fix command verification shell contract
```

CI：

```text
ZN Kernel / Python      success
Electron / TypeScript  success
run                     32621596489
```

Semantics：

```text
primary command success
!= task success

primary Body command
→ durable expected_outcome
→ later verify_action Thought
→ independent Body verification command
→ compare observed exit/output
→ complete OR Investigation/failure recovery
```

Failed verification 直接进入下一次 `CognitiveSituation` / Thought，并阻止原 primary command immediate blind replay。

## 已真实 CI 验证：compact task execution context

Source/test：

```text
470a8549901fd4201556188ea8276f83ebdb6033  feat: persist compact task execution context
969e07125db396f3f949aaa4d846fb5f8a0fd6bf  feat: bring execution context into situation
aaa6fa55c5c4e1968006f618a37260cb4f41675a  test: cover compact execution context
```

CI：

```text
ZN Kernel / Python      success
Electron / TypeScript  success
run                     32621878503
```

Active `WorkingState.data.execution_context` 现在保留一个有界的当前任务视图：

```text
goal
stage
current_gap
expected_outcome summary
current_action summary
latest_verification summary
verification_history (max 8)
updated_at
```

这不是 plan tree/task DB。

Verified：

- execution context 跨 pulse/restart；
- goal/current gap/expected outcome 进入 Situation/Thought；
- verification failure 成为当前 gap；
- 新的不同 action 开始时，旧 active verification verdict 被清空；
- 旧 verdict 进入最多 8 条的 bounded history，不再冒充当前现实。

## 当前真实能力边界

### Verified foundation

- persistent Self / zero-model life；
- durable event / WorkingState；
- Situation / Thought / Will continuity；
- Investigation 跨 pulse/restart；
- NativeActionIntent / BodyActionResult；
- failed Body action feedback；
- structured read-only Git repository sense；
- exact text postcondition independent verification；
- explicit command postcondition independent verification；
- verification contradiction immediate Situation/Thought feedback；
- compact current-event goal/gap/expected/current-action/verification context；
- bounded external cognition remains resource, not owner。

### 仍 PARTIAL / MISSING

- high-level goal → reliable resident-owned postcondition derivation；
- multi-step tactic changes over many actions；
- current anti-replay only has one last failed action signature: A → B → A can still bypass it；
- first-class completed-task VerificationReport/audit object；
- broader alternative-action recovery；
- safe Git mutation + diff/test/reality verification；
- GitHub repo/PR/CI resident-owned read sense；
- clean browser Body/Senses；
- mature visual + mouse/keyboard computer use；
- real complex-task benchmark suite；
- SM1+ self-maintenance。

## 当前下一真实目标

先修 long-horizon failure loop：

```text
single last-failed-action signature
→ bounded failed-action records tied to evidence state
→ A -> B -> A cannot loop without new evidence
→ genuinely new Investigation evidence can make a prior action eligible again
```

实现必须继续是当前 resident execution state 的有界证据机制，不引入 planner/task manager。

随后：

1. stronger alternative-action recovery；
2. practical Git mutation + diff/test/reality verification；
3. GitHub PR/CI read-only sense；
4. unfamiliar repo + failing CI benchmark；
5. browser/computer-use breadth按真实任务缺口进入。

## UI / release / safety boundary

- 不做 cosmetic UI polish/layout churn/dashboard expansion；
- desktop 只在核心授权/evidence/browser/computer-use/maintenance approval 或 blocking usability defect 需要时进入；
- M8 release debt 不删除，但不抢核心主线；
- force push/history rewrite/危险迁移/关闭 CI 或保护/扩大 secret 权限等仍必须人工确认；
- identity/memory/credential/updater/rollback/self-maintenance permission 高风险改动仍默认人工批准；
- `main` untouched。
