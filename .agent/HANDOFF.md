# ZN Agent Handoff

更新时间：2026-08-24

## 当前目标

完成 M10 canonical-branch promotion：对 exact final decision/status HEAD 跑完整 CI，通过后将 `main` 以非强制 fast-forward 指向同一 commit，再验证 canonical push CI。用户已明确授权该晋升。

核心原则：

> **ZN uses models. Models do not own ZN.**

## 当前分支 / 基线

- 固定开发分支：`dev/zn-agent`
- bulk source evacuation：`6d5f78d22883857fcc99aff5cfd4ba1b9a2d3e6b`
- bulk one-shot verification：run `32669071891`
- source-boundary cleanup full green：`b8eb1727711810f83f26035355370fafdb09ed83` / run `32670967428`
- production npm high gate added：`5466f51f4f9c3952483a824e718bb8a4c36cce68`
- M10 architecture decision：`c06e25c3fb85df3c3fe42049df7ab5f527135bf3`
- implementation-status synchronization：`bf091650031b096353d405f0a70820ed0d3d0685`
- 本文件提交前 `main` 仍为历史 baseline `61dd880aa4bbbdb359ca544b752afc2c22845ce9`；接手时必须重新读取 exact refs。
- dedicated reference branch 已核实保留完整历史 baseline，active tree 不依赖它。

## 已完成

### 1. active source evacuation

物理参考源撤离已完成。active high-level tree 仅保留 ZN-owned `.agent/.github/apps/docs/runtime/tests` 与必要 root metadata。迁移脚本和 migration-only write CI 均已退役。

真实 one-shot evidence：

```text
run 32669071891
fresh ZN-only Node lock/install          success
isolated ZN Python install               success
zero-model resident boot                 success
Python core tests                        382 passed
desktop typecheck/bundle                 success
desktop vitest                           37 passed
Node release/runtime tests               8 passed
ZN-only Docker build + boot              success
verified deletion commit/push            success
```

### 2. reference source isolated

独立 reference branch 与旧 `main` baseline commit 完全一致，因此旧源码已有单独参考落点，不需要在 active tree 复制，也不需要重写历史。

### 3. source-boundary hard gate

`.agent/verify_zn_source_boundary.py` 扫描 tracked path 和 tracked non-binary text，禁止退休产品标识、旧 package namespace 和旧物理路径回流。

`LICENSE` 文本是唯一法律 provenance 例外；原版权归属必须保留。路径本身仍受扫描。

`ZN CI` 同时覆盖 `dev/zn-agent` 和 `main` push。

### 4. final retired-text cleanup

初次 boundary run `32670680951` 给出精确残留清单。所有 active comments/docstrings/tests/runtime verifier 中的明文历史标识已清除或改为运行时 hex marker，拒绝能力未降低。

cleanup authority：

```text
run 32670967428
ZN Source Boundary        success
ZN Kernel / Python        success
Electron / TypeScript     success
Container / Runtime Smoke success
```

### 5. production npm security boundary

普通完整 Node install 仍报告 2 个 high findings。CI 已新增：

```text
npm audit --omit=dev --audit-level=high
```

run `32671061837` 的该 production gate 已 success，因此当前两项 finding 属于 development/tooling dependency debt，不是被接受的 production/runtime dependency。

不要做 blind `npm audit fix --force`；后续获取 exact dependency path 再安全修复。

### 6. M10 review

`ZN.md` 已记录 2026-08-24 M10 decision：

- resident/runtime ownership verified；
- desktop ownership verified；
- build/package/release ownership verified；
- source boundary CI-enforced；
- provenance/license retained；
- historical source isolated；
- production npm high gate active；
- M8 仍 **PARTIAL**，remaining platform continuity/signing/rollback debt 只被接受用于 canonical branch promotion，不代表 formal release complete；
- 用户已明确授权；
- 只允许 non-forced fast-forward。

## 当前未完成

1. exact final docs/decision HEAD 的完整 PR CI；
2. recheck `main...dev/zn-agent` fast-forward relation；
3. non-forced `main` update；
4. `main` push CI 复验；
5. verification-only draft PR #5 关闭且不得 merge；
6. 2 个 development/tooling npm high finding 的 exact dependency path；
7. remaining M8 intended-platform continuity / secure signing / rollback；
8. browser/computer Body/Senses、broader resident competence、SM1+。

## 风险 / 边界

- 禁止 force push/history rewrite。
- `LICENSE` legal attribution 不得为了文字清理而修改。
- M8 不得写成 complete。
- canonical `main` promotion 不等于正式 release。
- PR #5 只是 full PR CI trigger，不是 promotion mechanism。

## Task Queue

### P0 — source evacuation

Status: **COMPLETE**

### P1 — source boundary / regression guard

Status: **COMPLETE**

### P2 — M10 review

Status: **APPROVED FOR CANONICAL PROMOTION, EXACT-HEAD CI REQUIRED**

### P3 — main promotion

Status: **AUTHORIZED, PENDING EXACT-HEAD GREEN**

执行顺序：fresh full PR CI → compare refs → force=false fast-forward → main push CI → close PR #5 without merge。

### P4 — remaining debt

Status: **PENDING**

Development/tooling audit exact path → M8 continuity/signing/rollback → resident competence → SM1+。

## 下一真实目标

读取本提交后的 exact `dev/zn-agent` HEAD，等待/核实该 exact HEAD 的 Source Boundary、Python、Electron、Container 全绿；随后立即重新 compare `main...dev/zn-agent` 并执行 non-forced fast-forward promotion。