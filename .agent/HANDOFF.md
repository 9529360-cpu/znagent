# ZN Agent Handoff

更新时间：2026-08-23

## 当前目标

当前阶段已经完成 active repository 的物理 source evacuation。主目标从“继续迁移旧树”切回：

```text
保持 ZN-only ownership
→ 恢复 resident-owned engineering competence 主线
→ 关闭 M8 N→N+1 / intended-platform release continuity
→ 逐步推进 SM1+ self-maintenance
→ 只有在 fresh M10 review 通过且用户明确授权后才晋升 main
```

核心原则：

> **ZN uses models. Models do not own ZN.**

## 当前分支 / 权威基线

- 固定开发分支：`dev/zn-agent`
- 大规模删除前最后迁移修复：`624c3843dfc956e3753a3883c9cdc5208e6a46ea`
- verified bulk evacuation commit：`6d5f78d22883857fcc99aff5cfd4ba1b9a2d3e6b`
- one-shot verification run：`32669071891`
- steady-state CI cleanup：`5e032e8b2241abf58aba9c03f0041eb4a13c6be9`
- 当前文档/架构对账基线（写入本 HANDOFF 前）：`8589fdb8a9718b7c77d750ad7063b42b90c9286a`
- 本 HANDOFF 提交后 branch HEAD 会再前进一个提交；接手者必须以 `git rev-parse origin/dev/zn-agent` / GitHub branch HEAD 为当前 exact HEAD，不要把上面的 authored-against SHA 当成自引用 HEAD。
- `main` 仍未修改；M10 尚未完成 fresh promotion review。

## 本阶段已完成

### 1. 真实恢复与调用链审计

开始清理前重新读取并核对：

1. `ZN.md`
2. `AGENTS.md`
3. `docs/ZN-IMPLEMENTATION-STATUS.md`
4. `docs/ZN-SOURCE-EXTRACTION.md`
5. `docs/ZN-SELF-MAINTENANCE.md`
6. `.agent/HANDOFF.md`
7. `dev/zn-agent` exact HEAD / main relation / PR / CI / recent commits
8. Python runtime、desktop builder、test、Docker 和 release 的真实 active call chain

事实显示已有 `.agent/purge_hermes_source.py` 和 draft PR #5 one-shot verifier，但旧 HANDOFF/状态文档落后于真实代码。

### 2. 修复 one-shot 删除验证器

首轮 one-shot 在物理删树后已经证明 Python 382 tests 通过，但桌面测试仍要求已经应被删除的 duplicated `package.json.build` 和旧 packaging hook chain。

修复提交：

```text
dec9ee08f552ce48eb98d7bb3db17915c9e08a50
fix: verify ZN-only desktop after Hermes purge
```

处理原则：不恢复旧包装链，而是让删后测试验证唯一 `electron-builder.zn.yml`，并让 desktop `builder` 显式使用该配置。

### 3. 保持 final commit guard 严格

第二轮删后树已经全部功能绿，但提交守卫错误地禁止合法 workflow 删除。

修复：

```text
c09fc406c8d57fc8e956632fd3237d5c69d054e0
fix: allow verified purge deletions to commit
```

守卫只允许 workflow 删除，仍拒绝新增/修改 workflow 和生成物进入 purge commit；同时清掉临时 `.npmrc`。

第三轮发现验证安装生成 `runtime/python/build/**`，守卫正确拒绝。没有放宽守卫，而是删除 Python build/egg-info 验证副产物：

```text
624c3843dfc956e3753a3883c9cdc5208e6a46ea
fix: clean Python build artifacts before purge commit
```

### 4. 大规模删除真正落盘

用户已明确授权大规模删除。

最终 one-shot run：

```text
32669071891
```

`One-shot final Hermes source evacuation = success`，包含：

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

生成的正式删除提交：

```text
6d5f78d22883857fcc99aff5cfd4ba1b9a2d3e6b
refactor: evacuate inherited Hermes source from ZN
```

GitHub PR diff 显示该提交阶段将 changed-files 扩展到约 10k paths、删除约 2.99M lines；这是实际物理删树，不是 import shim。

### 5. 删后真实树审计

删后根目录只剩 ZN 所需高层结构：

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

旧 CLI / gateway / providers / plugins / tools / web / TUI / shared web workspace / root old Python distribution 等不再存在于 active dev tree。

物理 core/test 路径现在是：

```text
runtime/python/zn_agent/core/
tests/zn_agent/core/
```

迁移脚本已在 verified commit 中自行删除。

### 6. 退役 one-shot CI 写权限

成功删树后，临时 PR-only one-shot job 不应留在 steady-state CI，否则会继续依赖已删除脚本。

提交：

```text
5e032e8b2241abf58aba9c03f0041eb4a13c6be9
ci: retire completed source evacuation job
```

同时将 `zn-ci.yml` 的 `contents` 权限从 `write` 收回为 `read`；正常 steady-state CI 不再拥有仓库内容写权限。

### 7. MD/架构清理

已按删后事实清理：

- `ZN.md`：从 migration/evacuation contract 改为 steady-state ZN-only product contract；
- `AGENTS.md`：不再把旧产品树描述成长期开发/reference branch 架构；
- `docs/ZN-SOURCE-EXTRACTION.md`：从 in-tree extraction plan 改为 closed source-adoption boundary ledger；
- `docs/ZN-IMPLEMENTATION-STATUS.md`：移除过时 `agent/kernel` 等事实，记录物理 `zn_agent/core` 和真实删树 CI；
- `docs/ZN-MAINTAINER-PROMPT.md`：改成 ZN-only 接手规则；
- `docs/ZN-NEXT-PHASE.md`：明确 repository-boundary work 已结束，主线回到 competence/M8/SM；
- `docs/ZN-SELF-MAINTENANCE.md`：按当前 ZN-only repository boundary 重写；
- 删除纯 migration-history 文档 `docs/ZN-BLUEPRINT-BASELINE-2026-08-23.md`；Git history 已保留其历史内容。

保留：

- `docs/ZN-MEMORY-LEARNING.md`
- `docs/ZN-LEARNING-SOURCE-RESEARCH.md`

原因：这两份描述 ZN 的长期学习架构/外部研究，不是 active-tree 旧产品依赖说明。

## 当前 CI / 验证事实

大规模删除本身的权威验证：run `32669071891`，one-shot 全绿并完成 commit/push。

该 run 中普通 job 已观察到：

```text
ZN Kernel / Python     success
Electron / TypeScript success
```

外层 `Container / Runtime Smoke` 在 one-shot 已完成时仍可能处于独立运行中；删树正确性不依赖它，因为 one-shot 内部已经在删后树完成同等 Docker build + zero-model boot。

文档/steady-state CI cleanup 后必须读取最新 branch push CI；不要把本 HANDOFF 之前的 run 当成后续文档提交的最终 CI。

## 当前未完成

不要误报以下事项为 complete：

- M8 installed N → N+1 application/runtime/resident continuity；
- intended Windows/macOS clean-install/login continuity（若仍是正式 release target）；
- real signing/notarization；
- real-version rollback proof；
- general browser/computer-use Body/Senses；
- general resident-owned engineering verifier selection；
- mature broad procedural fast path / growth benchmarks；
- SM1+ autonomous self-maintenance；
- M10 promotion review / main promotion。

## 已知风险

1. one-shot `npm install` 报告过 2 个 high-severity advisories；必须调查真实 dependency tree，不能直接 `npm audit fix --force`。
2. `main` 仍是 M10 前旧 branch state；不要为了“看起来干净”提前修改。
3. package/runtime ownership tests 中可以保留用于防回归的 forbidden-content 字符串；不要把“仓库文本完全没有某个历史词”误当成比实际 dependency/path isolation 更重要的安全目标。
4. resident engineering verifier authority 仍然窄；不要因为现在物理路径已迁移，就扩大到任意 test/command guess。

## 相关文件

```text
ZN.md
AGENTS.md
Dockerfile
package.json
package-lock.json
runtime/python/pyproject.toml
runtime/python/zn_agent/core/
tests/zn_agent/core/
apps/desktop/
.github/workflows/zn-ci.yml
.github/workflows/zn-release.yml
.github/workflows/zn-linux-appimage-update-smoke.yml
docs/ZN-IMPLEMENTATION-STATUS.md
docs/ZN-SOURCE-EXTRACTION.md
docs/ZN-SELF-MAINTENANCE.md
docs/ZN-NEXT-PHASE.md
.agent/HANDOFF.md
```

## Task Queue

### P0 — finish post-evacuation audit

Status: **IN PROGRESS**

- verify latest steady-state push CI after docs/CI cleanup;
- close/retire temporary draft PR #5 without merging;
- re-scan retained docs/tree for stale physical paths/reference-control-plane requirements;
- reconcile any remaining stale doc facts.

### P1 — investigate Node advisories

Status: **PENDING**

Trace the two high-severity advisories to direct/transitive packages and decide whether safe dependency updates can remove them without breaking Electron packaging. Do not force-upgrade blindly.

### P2 — resume resident-owned engineering competence

Status: **PENDING after P0**

Start from physical `runtime/python/zn_agent/core` and `tests/zn_agent/core`. Preserve all existing current-reality authority/verification/restart gates.

### P3 — M8 continuity

Status: **PENDING**

Complete installed N→N+1, intended-platform release continuity, rollback and signing/notarization evidence.

### P4 — M10

Status: **BLOCKED on fresh evidence review**

Only after current runtime/desktop/release/CI/provenance/M8 risk review and explicit user authorization may `dev/zn-agent` be deliberately promoted to `main`.

## 下一真实目标

Finish P0 first: read latest branch HEAD + CI, retire PR #5 without merge, and confirm the retained active tree/docs no longer depend on historical product paths. Then investigate the npm advisories before returning to resident competence.