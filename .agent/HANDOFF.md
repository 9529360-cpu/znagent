# ZN Agent Handoff

更新时间：2026-08-24

## 当前目标

M10 canonical promotion 和 reference-source evacuation 已完成。当前阶段是 post-M10 steady-state cleanup：清除过期治理语义、关闭已知 npm high-severity debt、恢复只读 CI 权限，然后把验证后的 cleanup 晋升到 canonical `main`。之后回到 resident competence、M8 continuity 和 SM1+。

核心原则：

> **ZN uses models. Models do not own ZN.**

## 当前分支 / 关键基线

- 固定开发分支：`dev/zn-agent`
- canonical source/release branch：`main`
- bulk source evacuation：`6d5f78d22883857fcc99aff5cfd4ba1b9a2d3e6b`
- one-shot evacuation verification：run `32669071891`
- exact pre-M10 full CI：run `32671245421`
- final canonical M10 push CI：run `32671589664`
- dedicated reference branch 保留旧 baseline，仅作只读 quarry；active tree 不依赖它。
- 接手者必须重新读取 exact refs；本文件不能可靠自引用自身最终 SHA。

## 本轮已完成

### 1. post-M10 governance cleanup

已把长期规则从“M10 前 main 仍是未来目标”改为稳态分支模型：

```text
main          canonical source/release
dev/zn-agent  normal development
work/*        isolated work
```

已同步：

- `ZN.md`
- `AGENTS.md`
- `docs/ZN-MAINTAINER-PROMPT.md`
- `docs/ZN-SOURCE-EXTRACTION.md`
- `docs/ZN-SELF-MAINTENANCE.md`

普通开发仍不得直接在 `main` 试错；禁止 force push/history rewrite。

### 2. source boundary 保持干净

active source search 和 CI guard 没有发现重新进入的旧 runtime/namespace/path。`LICENSE` 原版权归属仍是唯一法律 provenance 文本例外，不得删除。

参考 branch 继续保留，但文档明确禁止 wholesale merge、submodule、packaging 或 runtime/build dependency。

### 3. npm high findings 精确归因

PR #6 的 audit-report run `32672071791` 给出真实 dependency evidence：

```text
electron 40.10.2
  → GHSA-9f4c-93c8-jc8g high
  → legacy extract-zip chain
extract-zip 2.0.1
  → GHSA-jmr9-qjv8-65gv high
```

production-only audit 原本为 0 high，但完整 development/tooling graph 有 2 high。

### 4. Electron 安全升级

第一次尝试 `40.10.6`：

- 移除了 legacy `extract-zip` high；
- 但 Electron 40 line 仍受 iframe popup advisory 影响；
- full audit 仍有 1 high，因此没有把它当完成。

进一步核实 patched stable range 从 `41.10.3` 开始，ZN 升级到 `electron 41.10.5`。

一次性验证 run `32672294469` 已证明：

```text
npm install with regenerated lock     success
npm audit --audit-level=high          success
desktop typecheck                     success
desktop bundle                        success
desktop 37 tests                      success
release/runtime Node 8 tests          success
ZN Source Boundary                    success
Container / Runtime Smoke             success
```

Python full tests 在该 run 结束时仍需从 GitHub 最终状态复核。

### 5. lockfile 已真实写回

为避免人工猜测 200KB lockfile integrity，临时给 desktop job `contents: write`，仅允许在 dev push、全部 audit/test 通过后提交 `package-lock.json`。

verified lock commit：

```text
22a0b56c4300441c7fddb63ab5ad6b82ecf909c3
deps: refresh Electron security lock [skip ci]
```

真实 lock 变化包括：

- Electron `41.10.5`；
- `@electron/get 5.1.0`；
- hardened `@electron-internal/extract-zip 1.0.5`；
- 旧 `extract-zip` / yauzl path 从 Electron chain 删除。

### 6. CI 写权限已再次收回

提交 `ad5679bcb264654feec3ae78a37f2af870ab4ca1` 已删除一次性 lock generation/commit path，并恢复 steady-state：

```text
contents: read
npm ci --ignore-scripts
npm audit --audit-level=high
```

现在任何 production 或 development/tooling high/critical npm finding 都会让 Electron CI 失败。

## 当前验证

- source evacuation authority: `32669071891` success
- pre-M10 exact full CI: `32671245421` success
- canonical M10 main CI: `32671589664` success
- npm exact-path investigation: `32672071791`
- Electron 41.10.5 regenerated-lock validation: `32672294469`
- steady-state exact-head PR CI after removing write access: **currently must be rechecked from GitHub**

不要把临时 regenerated-lock run 当成最终 steady-state authority；最终 authority 必须使用仓库已提交 lock + read-only CI 的 exact current HEAD。

## 当前未完成

1. exact current cleanup HEAD 的完整 Source Boundary + Python + Electron + Container PR CI；
2. 若全绿，将 post-M10 cleanup 非强制晋升到 `main`，再跑 canonical main CI；
3. 检查 GitHub Actions Node 20 deprecation warning，若官方稳定 actions 已迁移 Node 24，则做独立的小版本清理并验证；
4. M8 intended-platform continuity / secure signing / rollback；
5. browser/computer Body/Senses；
6. broader resident engineering competence；
7. SM1+ self-maintenance。

## 风险 / 边界

- `LICENSE` legal attribution 不能为了文字清理而修改。
- 不再使用 `npm audit fix --force`；当前 high debt 已用明确 stable patched Electron line 解决。
- steady-state CI 不保留 repository write permission。
- M8 仍 PARTIAL；canonical source cleanup 不代表 formal release complete。
- historical reference branch 仅供阅读，不能重新成为 active dependency/control plane。

## Task Queue

### P0 — source evacuation / source-boundary guard
Status: **COMPLETE**

### P1 — M10 canonical promotion
Status: **COMPLETE**

### P2 — post-M10 governance cleanup
Status: **IMPLEMENTED, FINAL CI PENDING**

### P3 — npm high-severity dependency cleanup
Status: **IMPLEMENTED, FINAL STEADY-STATE CI PENDING**

### P4 — Actions runtime deprecation cleanup
Status: **PENDING after P2/P3 green**

### P5 — resident competence / M8 / SM1+
Status: **PENDING**

## 下一真实目标

重新读取 current `dev/zn-agent` exact HEAD 和 PR #6 CI。只有 read-only steady-state Source Boundary、Python、Electron（含 full npm high gate）、Container 全绿后，才把 cleanup 晋升到 canonical `main`。
