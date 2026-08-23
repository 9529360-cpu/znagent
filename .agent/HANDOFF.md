# ZN Agent Handoff

更新时间：2026-08-24

## 当前目标

Post-M10 steady-state cleanup 已基本实现。当前收口目标是取得两类 exact evidence：

1. 当前 `dev/zn-agent` 的 fresh full PR CI；
2. Electron `41.10.5` 下真实 Linux AppImage N→N+1 resident continuity smoke。

两者均通过后，才把本轮 cleanup 以非强制 fast-forward 晋升到 canonical `main`，再验证 canonical push CI。

核心原则：

> **ZN uses models. Models do not own ZN.**

## 当前分支 / 基线

- 固定开发分支：`dev/zn-agent`
- canonical source/release branch：`main`
- 当前开发线在本文件更新前 HEAD：`a77da5435ee36ecf8ea0a19c044e6e04d2fe9490`
- 当前 canonical `main`：`8234a835dea604783cea0bd9d28a40de654ec03d`
- compare：`dev/zn-agent` ahead 21 / behind 0；merge base 为当前 `main`，因此仍是线性 fast-forward 候选。
- PR #6：draft/open，base `main`，head `dev/zn-agent`，未合并。
- dedicated historical reference branch 仅作只读 quarry；active tree 不依赖它。
- 接手者必须重新读取 exact refs；本文件不能可靠自引用自身最终 commit SHA。

## 本轮已完成

### 1. post-M10 governance cleanup

长期规则已从“M10 前 main 是未来目标”切换到稳态分支模型：

```text
main          canonical source/release
dev/zn-agent  normal development
work/*        isolated work
```

已同步 `ZN.md`、`AGENTS.md`、维护者 prompt、source extraction、自维护文档和 README。普通开发仍不得直接在 `main` 试错；禁止 force push/history rewrite。

README 入口已纠正：仓库拥有 ZN 实现、测试和自动化；resident 的 durable Self/state 由 resident-owned persistent storage 持有，不由 source tree 或某个维护模型拥有。

### 2. source boundary 保持 ZN-only

`.agent/verify_zn_source_boundary.py` 继续阻止退休产品标识、旧 namespace/path 和 control-plane 回流。

`LICENSE` 原法律 provenance 是唯一明确文本例外，不能为“清理干净”而删除或改写。

### 3. npm high-severity debt 已关闭

真实 audit 调查确认原 2 个 high：

```text
electron 40.10.2
  → GHSA-9f4c-93c8-jc8g
extract-zip 2.0.1
  → GHSA-jmr9-qjv8-65gv
```

`40.10.6` 只消掉 legacy `extract-zip` path，仍受 Electron advisory 影响，因此未作为完成版本。

ZN 最终升级到 patched stable `electron 41.10.5`。真实 lock commit：

```text
22a0b56c4300441c7fddb63ab5ad6b82ecf909c3
deps: refresh Electron security lock [skip ci]
```

当前 lock 使用 Electron `41.10.5`、`@electron/get 5.1.0`、`@electron-internal/extract-zip 1.0.5`，旧 `extract-zip` / yauzl Electron chain 已退出。

Steady-state Electron CI 现在强制：

```text
npm ci --ignore-scripts
npm audit --audit-level=high
```

已观察到真实 runner 输出 `found 0 vulnerabilities`。

### 4. 临时 CI 写权限已撤销

一次性 lock 生成/写回只用于避免人工猜测 200KB lock integrity。完成后已删除 generation/commit step 并恢复 `contents: read`。

steady-state CI 没有 repository write permission。

### 5. GitHub Actions runtime 清理

核心 workflows 已迁移到当前 Node 24 action runtime：

- `actions/checkout@v7`
- `actions/setup-node@v7`
- `actions/setup-python@v7`

旧 Node 20 runtime deprecation warning 已在真实 Electron job 日志中消失。

同时修正 release/AppImage uv cache authority：旧根 `uv.lock` 路径已改为 `runtime/python/pyproject.toml`。

### 6. Release / AppImage 安全门槛补强

- Release packaging 在 locked install 后执行 full `npm audit --audit-level=high`。
- AppImage N→N+1 smoke 也执行同一 full audit。
- AppImage smoke path filter 现在包含根 `package-lock.json`，避免纯 lock 安全变化漏测。
- AppImage smoke 启动即发布 `ZN Linux AppImage Update Smoke = pending`，结束时再发布 success/failure，解决长跑期间无法区分“未触发”和“仍执行”的可观测性缺口。

## 当前真实验证

历史权威：

```text
32669071891   source evacuation one-shot success
32671245421   exact pre-M10 full PR CI success
32671589664   canonical M10 main push CI success
32672071791   npm exact dependency-path investigation
32672294469   Electron 41.10.5 regenerated-lock validation success
32672797496   fa134632... full PR CI success
```

`32672797496` 已在 Actions v7 + read-only steady-state CI 上真实通过：

```text
ZN Source Boundary        success
ZN Kernel / Python        success
Electron / TypeScript     success
Container / Runtime Smoke success
```

其 Electron job 真实输出：

```text
npm ci                    found 0 vulnerabilities
npm audit --audit-level=high  found 0 vulnerabilities
typecheck                 success
bundle                    success
desktop tests             37 passed
release/runtime tests     8 passed
```

### 当前 AppImage continuity run

Run `32672795722`，head `fa134632077251c009c35c56b0c61d15ec9a63f0`。

已真实通过：

```text
pending status publication             success
checkout / Node / uv                    success
locked npm install                      success
full npm high audit                     success
headless dependencies                   success
isolated user systemd manager           success
real N AppImage build                   success
real N+1 AppImage build                 success
```

当前仍在：

```text
Run real installed AppImage updater continuity smoke   in_progress
```

不得把它写成 success，直到 GitHub 给出 terminal conclusion。

### 当前 exact-head CI anomaly

README-only commit `a77da543...` 触发 PR run `32673206922`。该 run 四个主 job 在约 3 秒内全部 failure，且 GitHub 返回 `steps: null`，重跑失败 jobs 后仍同样零步骤 failure。

这与前一 commit `fa134632...` 的完整真实 green run 相冲突，形态更像 GitHub Actions runner/check-suite 层异常，而不是 Source Boundary、Python、Electron、Container 四套代码同时回归。

因此不要把 `32673206922` 作为代码失败结论；必须由新的 commit 触发 fresh exact-head run，并以真实 step execution 为准。

## 当前未完成

1. AppImage run `32672795722` 的 terminal result；
2. 本 HANDOFF commit 之后的 fresh exact-head full PR CI；
3. 两者均绿后，非强制 fast-forward `main`；
4. canonical `main` push CI；
5. M8 remaining intended-platform continuity / signing / rollback；
6. browser/computer Body/Senses；
7. broader resident engineering competence；
8. SM1+ self-maintenance。

## 风险 / 边界

- `LICENSE` legal attribution 不得删除或改写。
- 不使用 `npm audit fix --force`。
- steady-state CI 不保留 repository write permission。
- M8 仍 PARTIAL；本轮 cleanup 或 canonical source promotion 不代表 formal release complete。
- historical reference branch 不能重新成为 active dependency/control plane。
- AppImage updater/rollback 属于高风险边界；测试失败必须修真实原因，不能绕过或降低验证。

## Task Queue

### P0 — source evacuation / source boundary
Status: **COMPLETE**

### P1 — M10 canonical promotion
Status: **COMPLETE**

### P2 — post-M10 governance cleanup
Status: **IMPLEMENTED / FINAL EVIDENCE IN PROGRESS**

### P3 — npm high-severity dependency cleanup
Status: **IMPLEMENTED / 0 VULNERABILITIES VERIFIED / FINAL PROMOTION PENDING**

### P4 — Actions runtime / release CI cleanup
Status: **IMPLEMENTED / VERIFIED ON fa134632...**

### P5 — Linux AppImage N→N+1 continuity
Status: **IN PROGRESS — run 32672795722**

### P6 — resident competence / remaining M8 / SM1+
Status: **PENDING**

## 下一真实目标

先读取 run `32672795722` 的 terminal result 与 diagnostics（若失败），并读取本次 HANDOFF 更新触发的 fresh PR CI。只有两条证据都真实通过，才允许把本轮 cleanup 非强制 fast-forward 到 `main`。