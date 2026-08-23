# ZN Agent Handoff

更新时间：2026-08-23

## 当前目标

下一开发阶段把重心从桌面/UI/打包收回到 **ZN 核心能力完整性**。

当前原则：

```text
先诚实收尾当前 M8 AppImage gate
→ 不继续以 UI polish 为开发主线
→ 下一会话先做 repository-backed capability gap audit
→ 用真实代码/调用链/测试把能力标成 DONE / PARTIAL / MISSING / DO NOT COPY
→ 选择最高价值的一个 ZN 核心能力切片实现
```

详细下一阶段契约见：

- `docs/ZN-NEXT-PHASE.md`

桌面仍然是 ZN 的脸和工作台；release/M8 仍然是必要产品通道，但在核心能力仍有明显缺口时，不再作为开发重心。

## 当前分支 / HEAD

- 分支：`dev/zn-agent`
- 本轮开始时真实远程 HEAD：`7ac39b53f0bd990513d9f2ff5928ee5e53fe145c` (`test: bound AppImage smoke teardown`)
- 新增下一阶段文档提交：`c963562c6e811792ba5f9cb77ff7a5f42683be06` (`docs: refocus next phase on ZN core [skip ci]`)
- 本 HANDOFF 更新本身会产生新的文档提交；下一维护者必须重新读取 `dev/zn-agent` HEAD，不得把上面 SHA 当成最终 HEAD。
- 本轮通过 GitHub 远程接口工作，没有可声明的本地 working tree。
- `main` 未修改。

## 当前真实实现基线

已经具备的核心基础（不是“通用 Agent 已完成”的宣称）：

- ZN-native resident organism：持久 Self/life、Situation、Thought、Will、nervous memory、investigation、action、learning、sensing；
- zero-model operation 是硬契约；
- 外部 GPT/Claude/Gemini/OpenAI-compatible 等只通过 ZN-owned bounded cognition resource 使用；
- ZN-owned local process / terminal / PTY body；
- ZN-owned web search/extract sensing + URL/network safety；
- durable resident work/thread/workspace/WorkRun/progress；
- contextual file/diff/terminal artifacts；
- resident-owned provider/settings/credential references；
- resident-owned channel lifecycle，Telegram text/inbound media 已有；
- independent Electron main/preload/renderer/`zn://`；
- independent packaged `runtime/python` / `zn_agent` runtime；
- M7 Linux/Windows/macOS formal artifact shape/runtime evidence；
- M8 Linux deb fresh-install、systemd user autostart、source-level N→N+1 continuity evidence。

仍然不能宣称完成的通用能力：

- clean ZN-owned browser interaction；
- mature visual/screen sensing + mouse/keyboard computer use；
- 已验证的强 Git body / GitHub repository body/sense 闭环；
- mature long-horizon autonomous repo/task completion comparable to mature coding agents；
- broad tool/capability ecosystem；
- Telegram outbound attachment transport；
- SM1+ 自维护实现。

## 本轮新完成

- 重新读取并核对：`ZN.md`、`AGENTS.md`、`docs/ZN-IMPLEMENTATION-STATUS.md`、`docs/ZN-SOURCE-EXTRACTION.md`、`docs/ZN-SELF-MAINTENANCE.md`、旧 `.agent/HANDOFF.md`。
- 确认本轮开始时 `dev/zn-agent` 与 `7ac39b5...` identical。
- 确认无 open PR 指向当前工作。
- 新增 `docs/ZN-NEXT-PHASE.md`，正式记录下一阶段优先级：从 UI/release-heavy 工作回到 ZN core capability completeness。
- 下一阶段文档明确：不以“有接口/类”为能力完成证据，必须跟真实 active call chain、state、lifecycle、tests、运行证据。
- 明确 capability audit 使用 `DONE / PARTIAL / MISSING / DO NOT COPY` 四类，避免为了追赶主流 Agent 把 ZN 重新做成模型拥有的 planner/tools agent。

## 当前 CI / M8 事实

`7ac39b53f0bd990513d9f2ff5928ee5e53fe145c` 的真实普通 CI：

```text
ZN Kernel / Python       success
Electron / TypeScript   success
Actions run              32609677486
```

专用 `ZN Linux AppImage Update Smoke` 在本轮最后检查时 **仍没有在该 commit 的 combined status 中出现最终状态**。

因此：

- 不得把该 AppImage gate 写成 green/complete；
- 不得因此把整个 M8 写成 complete；
- 先前 diagnostics 已证明某次 AppImage smoke 的实际 N→N+1 continuity proof 在几分钟内成功，随后测试 teardown/open handles 长时间挂住；
- `7ac39b5` 只修改 smoke teardown：给 `systemctl` cleanup 加 timeout，并 bounded close update HTTPS server；production behavior 未改；
- 下一维护者若要继续这条 gate，先重新读取该 commit 的真实 status；如果出现 AppImage status，使用其 `target_url` 的真实 run id 读取 jobs/logs/artifact，不猜 run id。

## 下一阶段能力审计

下一会话第一项工作不是继续 UI，也不是立刻凭感觉写 browser。

先做 repository-backed capability gap audit：

```text
恢复真实仓库状态
→ 枚举成熟 Agent 的能力类别
→ 对每一类追真实 ZN active caller
→ owner
→ state
→ lifecycle
→ dependency
→ tests
→ active use
→ 必要时跑 focused validation
→ DONE / PARTIAL / MISSING / DO NOT COPY
→ 按产品杠杆和 ZN 架构适配度排序
```

重点审计：

1. durable long-task investigation/action/verification；
2. filesystem/process/terminal 实际任务组合能力；
3. Git body；
4. GitHub/repository sense/body；
5. browser interaction；
6. visual/screen sense；
7. mouse/keyboard computer use；
8. tool/capability registration and breadth；
9. communication egress；
10. SM1 health observation / MaintenanceCase；
11. long-horizon coding/repo work 的真实成功链路。

## 下一阶段实现候选

最终顺序必须以 capability audit 的代码证据决定。目前高价值候选是：

- 强化 durable long-task execution，使一个真实任务能跨 pulses 持续调查→动作→验证，而不是认知重启；
- 建立 clean ZN-owned browser body/sense seam，再接实际浏览器能力；
- 建立 visual/computer-use body/senses；
- 补强 Git + GitHub/repository 能力，为日常工作和 SM2–SM4 同时打基础；
- 按 `docs/ZN-SELF-MAINTENANCE.md` 推进 SM1 health observation / MaintenanceCase，然后 SM2 read-only repo investigation。

不要靠 feature fashion 决定；优先能显著提高 ZN 完成真实复杂任务能力、同时不破坏 resident ownership 的切片。

## UI / Desktop 边界

下一阶段默认不做纯 UI polish。

UI 改动只在以下情况合理：

- 新核心能力必须有操作/授权界面；
- 必须向用户展示任务现实证据/进度；
- browser/computer-use 必须有观察或权限面；
- SM1 必须展示 MaintenanceCase；
- 真实 usability bug 阻塞任务完成。

不要做纯布局 churn、dashboard 扩张或视觉精修来替代核心能力工作。

## M8 / Release lane

M8 不放弃，但降为有边界的 release/continuity lane。

原则：

- 真实 continuity/data-integrity bug 必须修；
- 测试 harness / CI teardown 问题应修成可靠 gate，但不要无限消耗核心开发阶段；
- 已经验证过的 M7、Linux clean-install、Linux autostart 不重复跑来制造“进度”；
- Windows/macOS clean-install/login/signing/notarization保持明确 release debt；
- `main` 在 M10 前继续 untouched。

## 自维护顺序

`docs/ZN-SELF-MAINTENANCE.md` 现有契约仍有效：

```text
关键 M8 continuity evidence
→ SM1 health observation / MaintenanceCase
→ SM2 read-only self-repository investigation
→ SM3 isolated repair
→ SM4 PR/CI loop
→ SM5 risk/approval
→ SM6 self-maintenance release
→ SM7 user-confirmed update/rollback
```

下一阶段 capability audit 可以决定是否先做一个更基础的 Git/browser/long-task body slice；如果要改变这条架构顺序，先更新 `ZN.md` / self-maintenance contract，不能静默跑偏。

## 相关文件

- `ZN.md`
- `AGENTS.md`
- `docs/ZN-NEXT-PHASE.md`
- `docs/ZN-IMPLEMENTATION-STATUS.md`
- `docs/ZN-SOURCE-EXTRACTION.md`
- `docs/ZN-SELF-MAINTENANCE.md`
- `.agent/HANDOFF.md`
- `agent/kernel/**`
- `runtime/python/**`
- `apps/desktop/electron/**`
- `apps/desktop/scripts/zn-appimage-update-smoke.mjs`
- `.github/workflows/zn-ci.yml`
- `.github/workflows/zn-linux-appimage-update-smoke.yml`

## 风险 / 阻塞

- 不要把“organism architecture 已成形”误写成“通用 Agent 能力已完整”。
- 不要为了快速获得 browser/coding-agent 功能重新接回 inherited browser/session/gateway/full-agent control plane。
- 不要把模型输出直接当事实/动作；必须通过代码、日志、测试、运行/世界证据验证。
- AppImage gate final status 在本轮尚未取得，仍是未完成证据。
- 高风险 identity/memory/credential/updater/rollback/self-maintenance permissions 修改仍需要人工批准。

## 下一步

下一会话：

1. 重新读取所有必读 MD 和最新 `dev/zn-agent` HEAD/CI；
2. 先检查 AppImage gate 是否已经落最终 status，并诚实记录；
3. 读取 `docs/ZN-NEXT-PHASE.md`；
4. 开始 repository-backed **ZN capability gap audit**；
5. 形成 DONE/PARTIAL/MISSING/DO NOT COPY 清单；
6. 选出一个最高价值核心能力切片，追完整调用链后开始实现；
7. 不继续以 UI polish 为主线。
