# ZN Agent Handoff

更新时间：2026-08-24

## 当前目标

M10 canonical source promotion 已执行。当前只剩验证本次 `main` 文档记录 commit 的真实 canonical push CI，然后把 `dev/zn-agent` 以普通 fast-forward 同步到相同最终 SHA，并关闭 verification-only PR #5（不得 merge）。

核心原则：

> **ZN uses models. Models do not own ZN.**

## 当前分支 / 关键基线

- 固定开发分支：`dev/zn-agent`
- canonical source branch：`main`
- bulk source evacuation：`6d5f78d22883857fcc99aff5cfd4ba1b9a2d3e6b`
- bulk one-shot verification：run `32669071891`
- clean-tree full CI：`b8eb1727711810f83f26035355370fafdb09ed83` / run `32670967428`
- production npm high gate：`5466f51f4f9c3952483a824e718bb8a4c36cce68`
- M10 architecture decision：`c06e25c3fb85df3c3fe42049df7ab5f527135bf3`
- exact pre-promotion reviewed HEAD：`c158517225ff7b8cf0a952a0ae1dd6ebcf9c2c5d`
- exact pre-promotion full PR CI：run `32671245421`，四项全部 success
- `main` 已从历史 baseline 以 `force=false` fast-forward 到 reviewed ZN HEAD；没有 merge commit、force push 或历史重写。
- dedicated reference branch 继续保留完整历史 baseline，active tree 不依赖它。
- 接手时重新读取 exact `main` / `dev/zn-agent` refs；本文件不能自引用自身最终 commit SHA。

## 已完成

### 1. active source evacuation

物理参考源撤离完成。active tree 仅保留 ZN-owned product/runtime/desktop/docs/automation structure 与必要 root metadata。迁移脚本和 migration-only write CI 已退役。

one-shot real evidence：

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

### 2. reference source isolation

独立 reference branch 与晋升前旧 `main` baseline 完全一致。历史源码已有单独参考落点，不需要复制进 active tree，也不需要重写 Git 历史。

### 3. source-boundary hard gate

`.agent/verify_zn_source_boundary.py` 扫描 tracked path 与 tracked non-binary text，阻止退休产品标识、旧 package namespace 和旧物理路径回流。

`LICENSE` 文本是唯一法律 provenance 例外；原版权归属必须保留。

`ZN CI` 覆盖 `dev/zn-agent` 与 `main` push。

### 4. final text cleanup

所有 active comments/docstrings/tests/runtime verifier 中的历史产品明文均已清理或改为运行时 hex marker，拒绝能力保持。

exact reviewed evidence：

```text
run 32671245421
ZN Source Boundary        success
ZN Kernel / Python        success
Electron / TypeScript     success
Container / Runtime Smoke success
```

### 5. production npm security boundary

完整开发安装仍报告 2 个 high findings。CI 已强制：

```text
npm audit --omit=dev --audit-level=high
```

production gate 已通过，因此当前两项 high finding 属于 development/tooling dependency debt，不是接受进 production/runtime 的依赖。

禁止 blind forced audit upgrade；后续先取得 exact dependency path。

### 6. M10 canonical source promotion

M10 review 已按 `ZN.md` 完成：resident/runtime、desktop、build/package/release、CI、provenance、source independence、M8 risk acceptance 和用户授权均已审查。

M8 仍 **PARTIAL**。canonical source promotion 不代表 formal release complete。

真实 ref 操作：

```text
main: historical baseline
  -> c158517225ff7b8cf0a952a0ae1dd6ebcf9c2c5d
force=false
```

随后 `main...dev/zn-agent` compare 为 identical。

### 7. canonical promotion record

因为 ref move 本身没有产生新的可识别 `main` push Actions run，已在 `main` 写入纯文档 promotion record，以真实触发 canonical push CI。实现代码没有在这一步改变。

## 当前未完成

1. 验证最终 `main` promotion-record commit 的 canonical push CI；
2. 将 `dev/zn-agent` force=false fast-forward 到同一最终 docs SHA；
3. 确认 `main...dev/zn-agent` identical；
4. close draft PR #5 without merge；
5. development/tooling 2 个 high finding 的 exact dependency path；
6. remaining M8 intended-platform continuity / secure signing / rollback；
7. browser/computer Body/Senses、broader resident competence、SM1+。

## 风险 / 边界

- 禁止 force push/history rewrite。
- `LICENSE` legal attribution 不得删除或改写。
- M8 不得写成 complete。
- canonical `main` promotion 不等于正式 release。
- PR #5 只能关闭，不能 merge。

## Task Queue

### P0 — source evacuation

Status: **COMPLETE**

### P1 — source boundary / regression guard

Status: **COMPLETE**

### P2 — M10 review and source promotion

Status: **COMPLETE; CANONICAL PUSH CI FINALIZATION PENDING**

### P3 — branch synchronization / verification PR retirement

Status: **PENDING CANONICAL GREEN**

### P4 — remaining engineering debt

Status: **PENDING**

Development/tooling audit exact path → M8 continuity/signing/rollback → resident competence → SM1+。

## 下一真实目标

读取本提交产生的 exact `main` HEAD 和其 `ZN CI` push run；确认 Source Boundary、Python、Electron 全绿后，将 `dev/zn-agent` 非强制 fast-forward 到相同 SHA，确认两支 identical，并关闭 PR #5 without merge。