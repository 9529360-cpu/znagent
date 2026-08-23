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

当前下一真实目标：**stronger alternative-action recovery**。当当前现实证据已经否定一个 movement 时，ZN 应该形成/选择 genuinely different concrete tactic，而不是重放失败动作、反复借脑或假完成。

纯 UI/desktop polish 暂停。M8/release 保留为 bounded lane。

## 当前分支 / HEAD

- 分支：`dev/zn-agent`
- 最新真实 code/test SHA：`23ce3b42aad2d730afae4d60eb6af5d5b4bd1399`
- implementation-status docs commit：`e5ef764a485b3a234293f794d23e9b63de2b87d1` (`[skip ci]`)
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
- `dev/zn-agent` HEAD / net diff / open PR / recent commits / CI
- active packaged resident call chain
- Investigation → Action → Body → Verification → Situation/Thought anti-replay path

Open PR：无。

当前执行环境无可用本地 private-repo checkout，因此不宣称本地 test run；真实验证以 GitHub CI 为准。

## 本阶段已真实 CI 验证：evidence-bound failed-action history

Final code/test SHA：

```text
23ce3b42aad2d730afae4d60eb6af5d5b4bd1399
```

Real CI：

```text
ZN Kernel / Python      success
Electron / TypeScript  success
run                     32635668910
```

GitHub job 结论也已核对：Kernel test step、isolated model-free boot、compile、Electron typecheck/bundle/tests 全部 success；push workflow 的 container job 按设计 skipped。

最终实现位于现有 `EmbodiedResidentRuntime`，正式构造仍是现有 `WorldAwareTransferResidentRuntime` 链，没有保留额外 final-runtime shim/planner/manager。

主要 verified semantics：

```text
failed movement
→ record action signature hash + current Investigation facts fingerprint
→ bounded durable failure ledger
→ same action + same reality evidence remains blocked
→ B later failing does not erase A failure
→ new Investigation facts create a new evidence version
→ prior action can then be reconsidered
```

具体已验证：

- `native_action_failure_records` 最多 16 条；
- same action/same evidence failure 去重；
- full command/content 不进入 compact ledger，只保留 action signature hash；
- evidence fingerprint 来自 stable `Investigation.facts`，不来自 `rounds`；
- timestamp-only observation noise 不解锁旧失败动作；
- A → B → A 在现实证据不变时仍被阻止；
- changed facts 可重新使旧 movement eligible；
- failure records 跨 resident restart；
- 旧 persisted `native_action_failure_signature` 只做一次迁移读取，新逻辑不再依赖它；
- `execution_context.failed_actions` 暴露 bounded current execution evidence；
- external cognition resolution 不改 Investigation facts，因此模型文本本身不算新现实证据；
- accepted cognition 如果仍导出同一个被当前现实否定的 movement，现在返回 truthful failure，不再 fall through 到 false complete。

### 本阶段 CI 调试事实

快速连续 push 触发 workflow `cancel-in-progress`，因此中间 run 的 `error` 是 concurrency cancellation，不等同代码失败。

中间 run `32635484728`（SHA `8bd88ac...`）被后续 push 取消；取消前 isolated model-free boot 和 compile 已 success，Kernel 测试日志暴露两个旧测试仍断言已废弃的 `native_action_failure_signature`。

随后测试契约改为断言新 evidence ledger：

```text
2010ff8ab6d056cee11e6596dfc9e263cc2455b9  text contradiction test
23ce3b42aad2d730afae4d60eb6af5d5b4bd1399  command contradiction test
```

最终 run `32635668910` 全绿。

## 之前已真实 CI 验证的核心 slices

### Git sense + first post-action verification

```text
code/test SHA            47ccd5601462641c50c16ec76f2a05085a33f9f3
ZN Kernel / Python       success
Electron / TypeScript   success
run                      32612456040
```

Verified：structured read-only Git sense；non-append write success 不直接 complete；durable `native_verification`；`verify_action` Thought；Body re-read 后 exact match 才完成；verification 跨 restart；contradiction 返回 Investigation。

### Explicit command postconditions

```text
code/test SHA            f280c8f68af69dfc2ac10b94d8d83726c10aa14e
ZN Kernel / Python       success
Electron / TypeScript   success
run                      32621596489
```

Primary command success 只算 action evidence；独立 Body command 后置验证比较 exit/output 后才能完成。

### Compact task execution context

```text
code/test SHA            aaa6fa55c5c4e1968006f618a37260cb4f41675a
ZN Kernel / Python       success
Electron / TypeScript   success
run                      32621878503
```

`execution_context` 保留 goal/stage/current_gap/expected_outcome/current_action/latest_verification/bounded verification_history，并跨 pulse/restart。

## 当前真实能力边界

### Verified foundation

- persistent Self / zero-model life；
- durable event / WorkingState；
- Situation / Thought / Will continuity；
- Investigation 跨 pulse/restart；
- NativeActionIntent / BodyActionResult；
- structured read-only Git repository sense；
- exact text + explicit command postcondition verification；
- compact current-event execution context；
- evidence-bound bounded failed-action ledger；
- A → B → A same-evidence replay suppression；
- changed-facts retry eligibility；
- blocked post-cognition action不能假完成；
- bounded external cognition remains resource, not owner。

### 仍 PARTIAL / MISSING

- high-level goal → reliable resident-owned postcondition derivation；
- stronger alternative-action recovery / multi-step tactic changes；
- first-class completed-task `VerificationReport`/audit object；
- safe Git mutation + diff/test/reality verification；
- GitHub repo/PR/CI resident-owned read sense；
- clean browser Body/Senses；
- mature visual + mouse/keyboard computer use；
- real complex-task benchmark suite；
- SM1+ self-maintenance。

## 当前下一真实目标

先实现 bounded alternative-action recovery：

```text
current evidence blocks action A
→ keep A blocked
→ use current Situation / Investigation facts / failure evidence
→ derive or select genuinely different action B
→ execute B through normal Body path
→ verify B's expected outcome
→ if contradicted, record B against same evidence version
→ do not turn this into planner/task tree
```

需要特别保持：

- model output 不直接成为 tool/shell instruction；
- external cognition 不能凭文本“刷新 evidence version”；
- alternative 必须是具体不同的 resident-owned movement；
- recovery 必须 bounded，避免 A/B/C 无限枚举；
- 无可靠 alternative 时 truthful failure 优于假完成。

随后：

1. practical Git mutation + diff/test/reality verification；
2. GitHub PR/CI read-only sense；
3. unfamiliar repo + failing CI benchmark；
4. browser/computer-use breadth按真实任务缺口进入。

## UI / release / safety boundary

- 不做 cosmetic UI polish/layout churn/dashboard expansion；
- desktop 只在核心授权/evidence/browser/computer-use/maintenance approval 或 blocking usability defect 需要时进入；
- M8 release debt 不删除，但不抢核心主线；
- force push/history rewrite/危险迁移/关闭 CI 或保护/扩大 secret 权限等仍必须人工确认；
- identity/memory/credential/updater/rollback/self-maintenance permission 高风险改动仍默认人工批准；
- `main` untouched。
