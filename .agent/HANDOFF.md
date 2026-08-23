# ZN Agent Handoff

更新时间：2026-08-23

## 当前目标

开发主线已经明确切回 **ZN 核心能力完整性**。

当前约束：

```text
暂停纯 UI / desktop polish
→ desktop 只保留为 ZN 的脸、授权面和必要工作台
→ release/M8 保留为有边界的验证 lane，不再占据核心开发主线
→ 优先增强 resident 自己的 Body / Senses / Investigation / Action / Learning
```

本轮选择的第一项核心切片是 **Git repository sense**：先让同一个 resident 能可靠、结构化地观察真实仓库状态，为 durable repo work 和后续 SM2–SM4 打基础；本轮没有引入 Git 写操作、GitHub 写操作或新的模型控制面。

## 当前分支 / HEAD

- 分支：`dev/zn-agent`
- 本轮开始时远程 HEAD：`90e7119485f2fa80f4e27876dc5fe0aeb9f4eda1` (`test: fail fast on AppImage smoke leaks`)
- 核心实现提交：`168579604157467bb2384f385849c621ca66cefe` (`feat: strengthen native Git repository sense`)
- 回归测试提交：`90c3cde8619f698c8d1d67c63a6fa7b603a54ab2` (`test: cover native Git repository sense`)
- 本 HANDOFF 更新为 docs-only `[skip ci]` 提交；下一维护者必须重新读取远程 `dev/zn-agent` HEAD，不得把上面测试 SHA 当最终 HEAD。
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

并检查：

- `dev/zn-agent` 开始时与 `90e7119...` identical；
- 无 open PR；
- 开始时普通 `ZN Kernel / Python` 与 `Electron / TypeScript` CI 为 green；
- dedicated AppImage gate 仍不能记录为完成；
- 本轮通过 GitHub 远程接口工作，本地容器没有仓库 checkout，直接 clone 也因当前执行环境无法解析 github.com 而失败，因此本轮没有可声明的本地 test run / working-tree 状态。

## 真实 active call chain

正式 packaged resident 路径已追到：

```text
runtime/python/zn_agent/resident.py
→ agent/kernel/resident_server.py
→ ResidentRpcServer
→ provider_bridge.build_resident_runtime
→ WorldAwareTransferResidentRuntime
→ embodied resident/investigation
→ resident.body.act("git_state")
→ NativeBody._git_state
```

因此 Git 事实的正式 owner 是 ZN `NativeBody`。没有把旧兼容调查路径或 Hermes runtime 当正式 owner。

## 本轮完成的代码

`agent/kernel/body.py` 的只读 Git sense 从简单 branch/status 扩展为结构化仓库事实：

- repository root；
- current branch；
- full/short HEAD；
- detached HEAD；
- upstream；
- ahead / behind（存在 upstream 时）；
- dirty；
- unique `changed_paths`；
- staged paths；
- unstaged paths；
- untracked paths；
- conflicted paths；
- bounded porcelain `changes` 继续保留给现有调用者。

同时关闭一个 active-path 契约缺口：`NativeInvestigator._answer_from_native_facts()` 早已读取 `git.changed_paths` 回答“哪些文件改了”，但 embodied `NativeBody._git_state` 以前只返回 `changes`。这会导致真实 dirty repo 仍可能回答 `no changed files`。现在 Body 与 investigation contract 对齐。

## 测试

新增 `tests/agent/kernel/test_native_body.py` 回归覆盖：

1. 临时真实 Git repo 中同时制造 staged / unstaged / untracked 状态，断言 Body 返回结构化路径、HEAD、branch、dirty 与无 upstream 状态；
2. 通过正式 resident `submit()` 请求“which files changed”，断言结果来自 Git Body 的 `changed_paths` 且 `model_invocations == 0`。

## 当前 CI

代码+测试最新 SHA：

```text
90c3cde8619f698c8d1d67c63a6fa7b603a54ab2
```

本轮最后多次读取该 commit combined status 时，GitHub 尚未返回任何 status context（`statuses: []`）。因此：

- **不能宣称新 Git slice 已经过 CI**；
- 也不能把它写成 complete；
- 下一维护动作必须先读取该 SHA 或当前 HEAD 对应的真实 CI；
- 若失败，直接按 job/log 修复；若 green，再更新 `docs/ZN-IMPLEMENTATION-STATUS.md`，把 Git body 从“practical depth pending”改成已经验证的结构化 read-only repo sense，同时仍明确 Git mutation / GitHub repository loop 未完成。

## 当前核心能力判断

### 已有强基础

- durable Self/life；
- Situation / Thought / Will；
- nervous memory / reconsolidation；
- native investigation/action/learning；
- zero-model operation；
- bounded external cognition；
- local process / terminal / PTY body；
- web search/extract sensing + safety；
- durable work/thread/workspace/run/progress；
- resident-owned settings/credentials/channels；
- independent packaged `zn_agent` resident。

### 仍属 PARTIAL / MISSING

- durable long-horizon repo/task completion；
- Git write/action/verification closed loop；
- GitHub repository/PR/CI resident-owned sense/body；
- clean browser body/sense；
- mature visual screen + mouse/keyboard computer use；
- broad capability ecosystem；
- Telegram outbound attachment egress；
- SM1+ self-maintenance implementation。

## UI / Desktop 边界

默认不做：

- cosmetic polish；
- layout churn；
- dashboard expansion；
- 为了“看起来更完整”而增加桌面表面。

只有以下情况允许进入 desktop/UI：

- 核心能力必须获得用户授权；
- 必须展示真实 evidence / progress / risk；
- 核心任务被真实 usability bug 阻塞；
- browser/computer-use 或 MaintenanceCase 必须有最小操作面。

## M8 / Release lane

M8 不删除，但降为边界明确的 release lane。

- 已有 M7 package-shape、Linux deb clean-install、Linux systemd autostart、source-level N→N+1 continuity 证据继续保留；
- full installed Electron/AppImage updater handoff 仍不是 complete；
- Windows/macOS clean-install/login、signing/notarization 仍是 release debt；
- 不重复已完成 gate 来制造进度；
- 若 release gate 暴露真实 data-integrity / continuity / security bug，仍优先修复。

## 风险 / 阻塞

- 当前 Git slice 尚无最新 CI 结果，必须保持 PARTIAL；
- 不要把只读 Git sense 误写成完整 Git body，更不能写成 GitHub maintenance loop 已完成；
- repo mutation、PR/CI、自维护写路径必须继续有明确安全边界；
- identity/memory/credential/updater/rollback/self-maintenance permission 高风险修改仍需人工批准；
- 不得重新引入 Hermes runtime/control plane 或模型拥有的 planner/tools agent。

## 下一步

1. 重新读取当前 `dev/zn-agent` HEAD，并先检查 `90c3cde...`/最新 code SHA 的真实 CI；
2. 若 CI 失败，修 Git sense/test，直到 Kernel/Python（以及正常受影响 CI）green；
3. CI green 后更新 `docs/ZN-IMPLEMENTATION-STATUS.md` 和本 HANDOFF，明确“structured read-only Git repository sense verified”；
4. 继续核心 capability audit，下一优先候选是把 Git observation 接入 durable repo investigation/action/verification，而不是开始 UI；
5. 随后补 GitHub repository/PR/CI read-only sense，为 SM2 read-only self-repository investigation 铺路；
6. 在 mutation 前明确权限、工作区、分支、验证和 rollback 边界；
7. `main` 保持 untouched，直到 M10 条件满足且用户明确要求。
