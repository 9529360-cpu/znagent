# ZN Agent Handoff

更新时间：2026-08-23

## 当前目标

active repository 的物理参考源撤离已经完成。当前主线：

```text
保持 ZN-only ownership
→ 恢复 resident-owned engineering competence
→ 关闭 M8 N→N+1 / intended-platform release continuity
→ 逐步推进 SM1+ self-maintenance
→ fresh M10 review 通过且用户明确授权后才晋升 main
```

核心原则：

> **ZN uses models. Models do not own ZN.**

## 当前分支 / 权威基线

- 固定开发分支：`dev/zn-agent`
- 大规模删除前最后迁移修复：`624c3843dfc956e3753a3883c9cdc5208e6a46ea`
- verified bulk evacuation commit：`6d5f78d22883857fcc99aff5cfd4ba1b9a2d3e6b`
- one-shot verification run：`32669071891`
- steady-state CI cleanup：`5e032e8b2241abf58aba9c03f0041eb4a13c6be9`
- 文档/架构对账基线：`8589fdb8a9718b7c77d750ad7063b42b90c9286a`
- 本 HANDOFF 更新前 remote HEAD：`c8a942df5e230e1d5a0f2ca3c8481ff1114f0b76`
- 接手者必须以 GitHub / `git rev-parse origin/dev/zn-agent` 为 exact current HEAD；HANDOFF 文件无法自引用其自身最终 commit SHA。
- `main` 未修改；M10 尚未完成 fresh promotion review。

## 已完成

### 1. 真实恢复与调用链审计

开始清理前重新读取/核对必读文档、exact dev HEAD、main relation、PR/CI、最近提交，以及 Python runtime、desktop builder、tests、Docker、release 的真实 active call chain。

现场显示已有一次性 allowlist purge 机制，但旧 HANDOFF/状态文档明显落后于真实代码。

### 2. 修复 one-shot 删树验证

首轮物理删树后的 Python 382 tests 已通过；桌面仍有两个测试要求已经应该删除的 duplicated package build metadata / retired packaging hook chain。

修复提交：

```text
dec9ee08f552ce48eb98d7bb3db17915c9e08a50
```

处理原则：不恢复旧包装链；删后测试验证唯一 `electron-builder.zn.yml`，desktop builder 显式使用该配置。

### 3. 保持最终提交 guard 严格

后续删树树形/功能已全绿，但提交守卫先后正确暴露两类 migration-only 问题：

- 合法删除旧 workflow 被旧规则一并禁止；
- Python 安装验证产生 `runtime/python/build/**` 副产物。

修复提交：

```text
c09fc406c8d57fc8e956632fd3237d5c69d054e0
624c3843dfc956e3753a3883c9cdc5208e6a46ea
```

没有通过放宽 generated-artifact guard 解决，而是只允许 workflow 删除并在 commit 前清掉 `.npmrc`、Python build/egg-info 等验证副产物。

### 4. 大规模删除真正落盘

用户已明确授权大规模删除。

最终 one-shot run：

```text
32669071891
```

删后树验证：

```text
apply ZN-only allowlist                 success
fresh Node lock/install                 success
isolated ZN Python install              success
zero-model resident boot                success
full tests/zn_agent/core                382 passed
desktop typecheck/bundle                success
desktop vitest                          37 passed
retained release/runtime Node tests     8 passed
ZN-only Docker build                    success
Docker zero-model resident boot         success
final cleaned-tree commit/push          success
```

正式删除提交：

```text
6d5f78d22883857fcc99aff5cfd4ba1b9a2d3e6b
```

这是实际物理删树，不是 import shim 或 compatibility wrapper。

### 5. 删后真实树

当前高层结构：

```text
.agent/
.github/
apps/
docs/
runtime/
tests/
AGENTS.md
Dockerfile
LICENSE
README.md
ZN.md
package.json
package-lock.json
.gitignore
```

旧 CLI / gateway / providers / plugins / tools / web / TUI / shared workspace / root old Python distribution 等不再存在于 active dev tree。

物理 core/test：

```text
runtime/python/zn_agent/core/
tests/zn_agent/core/
```

一次性迁移脚本已在 verified commit 中自行删除。

### 6. 退役一次性 CI 写权限

成功删树后，临时 PR-only migration job 已退役：

```text
5e032e8b2241abf58aba9c03f0041eb4a13c6be9
```

`zn-ci.yml` 的 `contents` 权限从 `write` 收回为 `read`。steady-state CI 不再拥有仓库内容写权限。

### 7. 文档清理

已按删后事实对账：

- `ZN.md` → steady-state ZN-only product contract；
- `AGENTS.md` → ZN-only 接手/施工规则；
- `docs/ZN-SOURCE-EXTRACTION.md` → closed source-adoption boundary ledger；
- `docs/ZN-IMPLEMENTATION-STATUS.md` → 当前物理 `zn_agent/core` 与真实删树 CI；
- `docs/ZN-MAINTAINER-PROMPT.md` → 当前 ZN-only bootstrap；
- `docs/ZN-NEXT-PHASE.md` → repository-boundary work 结束，恢复 competence/M8/SM 主线；
- `docs/ZN-SELF-MAINTENANCE.md` → 当前仓库 ownership 自维护规则；
- 删除纯 migration-history 文档 `docs/ZN-BLUEPRINT-BASELINE-2026-08-23.md`。

保留：

- `docs/ZN-MEMORY-LEARNING.md`
- `docs/ZN-LEARNING-SOURCE-RESEARCH.md`

这两份描述 ZN 长期学习架构/外部研究，不是旧产品 active dependency 说明。

### 8. 临时 PR 已关闭

用于触发 one-shot verifier 的 draft PR #5 已关闭，未 merge；`main` 未修改。

## 当前 CI / 验证事实

大规模删除权威验证：run `32669071891`，one-shot 全绿并完成 commit/push。

该 run 的普通 jobs 已有：

```text
ZN Kernel / Python     success
Electron / TypeScript success
```

one-shot 内部已经额外完成删后 Docker build + zero-model boot。

文档/steady-state CI cleanup 后必须读取最新 branch push CI；不要把 migration run 当成所有后续 docs/CI commits 的最终验证。

## 当前未完成

- M8 installed N → N+1 application/runtime/resident continuity；
- intended Windows/macOS clean-install/login continuity（若仍为正式 release target）；
- real signing/notarization；
- real-version rollback proof；
- general browser/computer-use Body/Senses；
- general resident-owned engineering verifier selection；
- mature broad procedural fast path / growth benchmarks；
- SM1+ autonomous self-maintenance；
- M10 promotion review / main promotion。

## 已知风险

1. one-shot `npm install` 报告 2 个 high-severity advisories；必须追真实 dependency tree，不能直接 `npm audit fix --force`。
2. `main` 仍是 M10 前 branch state；不要为“看起来干净”提前修改。
3. code/tests 中允许存在用于防回归的 forbidden-content test strings；判断 ownership 看真实 dependency/path/caller，不把“文本里完全没有历史词”当作产品安全证明。
4. resident engineering verifier authority 仍然窄；不要扩大到任意 test/command guess。

## Task Queue

### P0 — finish post-evacuation audit

Status: **IN PROGRESS**

- verify latest steady-state push CI after docs/CI cleanup；
- re-scan retained MD/tree for stale physical paths/reference-control-plane requirements；
- reconcile any remaining stale facts。

### P1 — investigate Node advisories

Status: **PENDING**

Trace the two high-severity advisories to direct/transitive packages and decide whether safe dependency updates can remove them without breaking Electron packaging. Do not force-upgrade blindly.

### P2 — resume resident-owned engineering competence

Status: **PENDING after P0**

Start from physical `runtime/python/zn_agent/core` and `tests/zn_agent/core`. Preserve all current-reality authority/verification/restart gates.

### P3 — M8 continuity

Status: **PENDING**

Complete installed N→N+1, intended-platform release continuity, rollback and signing/notarization evidence.

### P4 — M10

Status: **BLOCKED on fresh evidence review**

Only after current runtime/desktop/release/CI/provenance/M8 risk review and explicit user authorization may `dev/zn-agent` be deliberately promoted to `main`.

## 下一真实目标

Finish P0: read latest branch HEAD + CI, confirm retained MD/tree no longer depends on historical product paths, then investigate the npm advisories before returning to resident competence.