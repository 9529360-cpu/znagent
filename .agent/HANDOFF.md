# ZN Agent Handoff

更新时间：2026-08-23

## 当前目标

active repository 的物理参考源撤离与删后审计已经完成。当前主线：

```text
保持 ZN-only ownership
→ 调查 Node packaging advisory debt
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
- bulk one-shot verification run：`32669071891`
- steady-state CI cleanup：`5e032e8b2241abf58aba9c03f0041eb4a13c6be9`
- steady-state audited code/docs HEAD：`732e03c413e9d222dc97c729051ba78f952f23c2`
- steady-state full PR CI：`32669724116`
- 本 HANDOFF 是验证完成后的 docs-only `[skip ci]` 同步；接手者必须重新读取 GitHub exact `dev/zn-agent` HEAD。
- `main` 未修改；M10 尚未完成 fresh promotion review。

## 已完成

### 1. 真实恢复与调用链审计

开始清理前重新读取/核对必读文档、exact dev HEAD、main relation、PR/CI、最近提交，以及 Python runtime、desktop builder、tests、Docker、release 的真实 active call chain。

### 2. 修复 one-shot 删树验证

首轮物理删树后 Python 382 tests 已通过；桌面仍有两个测试要求已经应该删除的 duplicated package build metadata / retired packaging hook chain。

修复提交：

```text
dec9ee08f552ce48eb98d7bb3db17915c9e08a50
```

没有恢复旧包装链；删后测试改为验证唯一 `electron-builder.zn.yml`，desktop builder 显式使用该配置。

### 3. 保持最终提交 guard 严格

删树功能验证全绿后，提交守卫又正确暴露：

- 合法删除旧 workflow 被旧规则一并禁止；
- Python 安装验证产生 `runtime/python/build/**` 副产物。

修复提交：

```text
c09fc406c8d57fc8e956632fd3237d5c69d054e0
624c3843dfc956e3753a3883c9cdc5208e6a46ea
```

没有放宽 generated-artifact guard；只允许 workflow 删除，并在 commit 前清掉 `.npmrc`、Python build/egg-info 等验证副产物。

### 4. 大规模删除真正落盘

用户已明确授权大规模删除。

最终 one-shot run：

```text
32669071891
```

删后临时树验证：

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

提交：

```text
5e032e8b2241abf58aba9c03f0041eb4a13c6be9
```

PR-only migration job 已删除；`zn-ci.yml` 的 `contents` 权限从 `write` 收回为 `read`。steady-state CI 不再拥有仓库内容写权限。

### 7. 文档清理

已按删后事实对账：

- `ZN.md` → steady-state ZN-only product contract；
- `AGENTS.md` → ZN-only 接手/施工规则；
- `docs/ZN-SOURCE-EXTRACTION.md` → closed source-adoption boundary ledger；
- `docs/ZN-IMPLEMENTATION-STATUS.md` → 当前物理 `zn_agent/core` 与真实删树 CI；
- `docs/ZN-MAINTAINER-PROMPT.md` → 当前 ZN-only bootstrap；
- `docs/ZN-NEXT-PHASE.md` → repository-boundary work 结束，恢复 competence/M8/SM 主线；
- `docs/ZN-SELF-MAINTENANCE.md` → 当前仓库 ownership 自维护规则；
- 删除纯 migration-history `docs/ZN-BLUEPRINT-BASELINE-2026-08-23.md`。

保留：

- `docs/ZN-MEMORY-LEARNING.md`
- `docs/ZN-LEARNING-SOURCE-RESEARCH.md`

两份保留文档经删后复查，没有旧物理 `agent/kernel` 路径，内容属于 ZN 长期学习架构/外部研究。

当前 `docs/` 只保留 7 份 ZN 文档。

### 8. active manifests / ownership 复查

当前 root `package.json` 只声明 `apps/desktop` workspace。

当前 desktop manifest：

```text
name = zn-desktop
builder = node scripts/run-electron-builder.mjs --config electron-builder.zn.yml
```

当前 Python distribution：

```text
project = znagent
script = zn-resident -> zn_agent.resident:main
packages = zn_agent, zn_agent.*
```

### 9. steady-state CI 真正复验

为避免把“应该有 push CI”当证据，临时重新打开既有 draft PR #5，仅触发当前 steady-state PR CI，不 merge。

当前 HEAD `732e03c413e9d222dc97c729051ba78f952f23c2` 的真实 run：

```text
32669724116
```

结果：

```text
ZN Kernel / Python         success
Electron / TypeScript     success
Container / Runtime Smoke success
```

这次 run 不含任何一次性 migration job。

验证完成后 PR #5 已再次关闭，`merged = false`，`main` 未修改。

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

1. one-shot fresh Node install 报告 2 个 high-severity advisories。当前 lock 中多个 `brace-expansion` 节点已经处于 2026 已知高危公告的 patched versions，因此不能把这两个 finding 简单归因于它；下一步要获得真实 npm audit dependency path，再决定安全升级，不做 `--force` 或盲目 override。
2. `main` 仍是 M10 前 branch state；不要为“看起来干净”提前修改。
3. code/tests 中允许存在用于防回归的 forbidden-content test strings；判断 ownership 看真实 dependency/path/caller，不把“文本里完全没有历史词”当成产品安全证明。
4. resident engineering verifier authority 仍然窄；不要扩大到任意 test/command guess。

## Task Queue

### P0 — post-evacuation audit

Status: **COMPLETE**

已完成：删后物理树、MD、manifests、CI、临时 PR、一次性写权限全部对账，并用 `32669724116` 对当前 steady-state HEAD 做 Python/Electron/Container 实际复验。

### P1 — investigate Node advisories

Status: **NEXT**

获取真实 npm audit dependency path，区分 production/runtime 与 dev-only packaging dependency；只做可验证、安全、不破坏 Electron packaging 的升级。

### P2 — resume resident-owned engineering competence

Status: **PENDING after P1**

从物理 `runtime/python/zn_agent/core` 和 `tests/zn_agent/core` 继续，保留全部 current-reality authority/verification/restart gates。

### P3 — M8 continuity

Status: **PENDING**

完成 installed N→N+1、intended-platform release continuity、rollback 和 signing/notarization evidence。

### P4 — M10

Status: **BLOCKED on fresh evidence review**

source independence 已满足，但 M8/release continuity 风险仍未闭合。只有 current runtime/desktop/release/CI/provenance/M8 risk review 达到 `ZN.md` M10 条件且用户明确授权时，才允许把 `dev/zn-agent` 晋升到 `main`。

## 下一真实目标

P1：先把 Node 的 2 个 high-severity audit finding 精确追到依赖链；如果属于可安全修复的 packaging dependency，就修复并跑完整 CI。之后恢复 resident competence 主线，同时继续推进 M8。