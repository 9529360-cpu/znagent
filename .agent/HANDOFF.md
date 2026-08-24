# ZN Agent Handoff

更新时间：2026-08-24

## 当前目标

Post-M10 steady-state cleanup 的 Windows CI 修复已收敛。当前目标是保持 `dev/zn-agent` exact HEAD 的 Windows Source Boundary / Python / Electron CI 为绿，并补齐仍未完成的 Linux manual evidence：Container runtime smoke 与真实 AppImage N→N+1 resident continuity smoke。

核心原则：

> **ZN uses models. Models do not own ZN.**

不要因为 Windows CI 已绿就把 Linux AppImage continuity 写成完成；旧 run 在最关键的 installed updater continuity 步骤被取消。

## 当前分支 / HEAD

- 固定开发分支：`dev/zn-agent`
- canonical source/release branch：`main`
- 本文件更新前开发 HEAD：`8d8be1f819f047d0436ca997c573616e3e61d7b9`
- 当前 canonical `main`：`8234a835dea604783cea0bd9d28a40de654ec03d`
- PR #6：draft/open，base `main`，head `dev/zn-agent`，未合并
- 本文件自身提交会再次推进 `dev/zn-agent`；接手者必须读取真实 branch HEAD，不得把上面的 pre-HANDOFF SHA 当最终 HEAD

## 本轮已完成

### 1. 恢复真实 CI 现场并区分 cancellation 与代码失败

`zn-ci.yml` 使用：

```text
concurrency:
  group: zn-ci-${{ github.ref }}
  cancel-in-progress: true
```

因此连续 push 会取消上一轮 run。此前若干红色 status 来自 cancelled run，并不是四套代码同时失败。

最后一个真实执行到 Python suite 的失败基线是 `0ec4acf84468833e037c475146be3535588cd2a7`：

```text
ZN Source Boundary / Windows   success
Electron / TypeScript / Windows success
ZN Kernel / Python / Windows   failure
```

Python 真实结果：383 tests，13 errors，5 skipped。13 个错误分成：

- 2 个 Windows/Git-Bash command verification 功能失败；
- 11 个 Windows `WinError 32` / `kernel.db` cleanup lock。

### 2. 修复真实 SQLite connection ownership bug

根因位于：

```text
runtime/python/zn_agent/core/schema_structure.py
```

`SchemaStructurePlasticity._rewire_links()` 原来使用：

```python
with self.nervous._connect() as conn:
```

Python `sqlite3.Connection` 的 context manager 只处理 transaction commit/rollback，不保证关闭连接。该短连接独立于 `KernelStore._conn`，所以即使调用 `store.close()`，Windows 仍会锁住 `kernel.db`。

修复提交：

```text
f9837e55f5d8aa67ceaa7852e9730cdbf5ad69a8
fix: close schema merge sqlite connection
```

现在使用 `contextlib.closing(...)` 明确关闭 schema merge 短连接。

### 3. 修复 Windows Git-Bash command verification test path

根因位于：

```text
tests/zn_agent/core/test_command_verification.py
```

产品 terminal 在 Windows 明确使用 Git Bash；不应为了测试改成 `cmd.exe`。两个失败 case 把 Windows backslash path 直接嵌入经 `bash -c` 传递的 Python `-c` 源码。纯 `print(...)` 命令在同一 terminal/helper 下能正常执行，证明问题不是整体 shell contract。

修复提交：

```text
8d8be1f819f047d0436ca997c573616e3e61d7b9
test: make command verification paths bash-portable on Windows
```

仅把嵌入 Python 源码的 target path 改为 `Path.as_posix()`；Windows `pathlib.Path` 可正常接受 forward slash，不改变 ZN terminal 产品语义。

## 真实测试 / CI 结果

### Windows exact-head evidence

Run：

```text
32700998620
```

Checkout 日志明确验证：

```text
HEAD = 8d8be1f819f047d0436ca997c573616e3e61d7b9
```

结果：

```text
ZN Source Boundary / Windows       success
Electron / TypeScript / Windows    success
ZN Kernel / Python / Windows       success
Publish Windows CI statuses        success
```

Kernel exact evidence：

```text
Python 3.12.13 isolated runtime boot   success
compileall resident core               success
383 core tests                         OK
skipped                                5
runtime                                388.541s
```

此前失败的两个 command verification case 已在真实 Windows CI 中变为 `ok`；此前触发 DB lock 的 schema/integrated/situated/neural tests 也已通过。

Electron exact evidence：

```text
locked npm install                     success
npm audit --audit-level=high           success
typecheck                              success
bundle                                 success
desktop ownership/runtime/update tests success
release/runtime verifier tests         success
```

Source Boundary exact evidence：success。

### Linux Container

`.github/workflows/zn-linux-container-smoke.yml` 当前是 `workflow_dispatch` only，不会由普通 dev push 自动运行。

历史 run 有成功证据，但本轮 Windows-fix exact HEAD 尚未取得新的 manual Container smoke。不要把它写成当前 exact-head 已验证。

### Linux AppImage N→N+1 continuity

`.github/workflows/zn-linux-appimage-update-smoke.yml` 当前也是 `workflow_dispatch` only。

旧 run：

```text
32672795722
```

最终 conclusion：`cancelled`。

已真实完成：

```text
pending status publication             success
checkout / Node / uv                    success
locked npm install                      success
npm high audit                          success
headless dependencies                   success
isolated user systemd manager           success
real N AppImage build                   success
real N+1 AppImage build                 success
```

取消点：

```text
Run real installed AppImage updater continuity smoke   cancelled
```

因此 Linux installed updater resident continuity 仍是未完成证据，不得标 success。

## 相关文件

```text
.github/workflows/zn-ci.yml
.github/workflows/zn-linux-container-smoke.yml
.github/workflows/zn-linux-appimage-update-smoke.yml
runtime/python/zn_agent/core/schema_structure.py
tests/zn_agent/core/test_command_verification.py
tests/zn_agent/core/test_resident_sqlite_lifecycle.py
docs/ZN-IMPLEMENTATION-STATUS.md
.agent/HANDOFF.md
```

## 风险 / 边界

- 不修改 `main`，除非用户明确要求并且相关晋升条件真实满足。
- 禁止 force push / history rewrite。
- 不把 cancelled CI 当作代码 failure，也不把 cancelled AppImage smoke 当作 success。
- `sqlite3.Connection` 不能仅靠普通 `with conn:` 推断连接已经关闭；Windows 会暴露残留句柄。
- Windows terminal 的 Git Bash contract 是产品设计，不应为单个测试失败切换 shell。
- AppImage updater / rollback / signing 属于高风险发布边界，不能降低验证标准。
- GitHub Actions 当前日志有第三方 action Node runtime deprecation warning；本轮 run 未因此失败，后续按稳定上游 action 版本处理，不做盲目升级。

## 当前未完成 / Task Queue

### P0 — Windows CI blocker
Status: **COMPLETE / EXACT CI VERIFIED**

### P1 — fresh exact-head Container runtime smoke
Status: **PENDING MANUAL WORKFLOW EVIDENCE**

### P2 — real Linux AppImage N→N+1 installed resident continuity
Status: **PENDING; OLD RUN 32672795722 CANCELLED DURING CORE CONTINUITY STEP**

### P3 — PR #6 cleanup promotion decision
Status: **BLOCKED ON REQUIRED FINAL EVIDENCE / USER AUTHORIZATION FOR MAIN**

### P4 — remaining M8 intended-platform continuity / signing / rollback
Status: **PENDING / PARTIAL**

### P5 — browser/computer Body/Senses, broader resident engineering competence, SM1+
Status: **PENDING**

## 下一真实目标

1. 读取本 HANDOFF commit 后的真实 `dev/zn-agent` HEAD，并确认它触发的 Windows CI；
2. 取得当前开发线的 manual Linux Container runtime smoke；
3. 重新运行真实 Linux AppImage N→N+1 installed resident continuity smoke，并读取 terminal diagnostics；
4. 只有所需 evidence 真实通过后，才评估 PR #6 / canonical `main` 的正常非强制晋升；不得把 partial 写成 complete。
