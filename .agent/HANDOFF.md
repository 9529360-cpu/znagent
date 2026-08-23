# ZN Agent Handoff

更新时间：2026-08-24

## 当前目标

M10 canonical source promotion 已完成。当前维护主线回到 development/tooling dependency audit、resident competence、M8 continuity 和 SM1+。每次接手先重新读取 exact Git refs、CI 和本文件，事实仍以真实代码/Git/CI 为准。

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
- exact reviewed pre-promotion HEAD：`c158517225ff7b8cf0a952a0ae1dd6ebcf9c2c5d`
- exact reviewed full PR CI：run `32671245421`
- canonical promotion-record `main` push CI：run `32671435423`
- dedicated reference branch 保留完整历史 baseline；active tree 不依赖它。
- 本文件不能自引用自身最终 commit SHA。接手者必须重新读取 exact `main` 和 `dev/zn-agent` refs。

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

独立 reference branch 与晋升前旧 canonical baseline 完全一致。历史源码已有单独参考落点，不需要复制进 active tree，也不需要重写 Git 历史。

### 3. source-boundary hard gate

`.agent/verify_zn_source_boundary.py` 扫描 tracked path 与 tracked non-binary text，阻止退休产品标识、旧 package namespace 和旧物理路径回流。

`LICENSE` 文本是唯一法律 provenance 例外；原版权归属必须保留。

`ZN CI` 覆盖 `dev/zn-agent` 与 `main` push。

### 4. final source/text cleanup

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

完整开发安装仍报告 2 个 high findings。CI 强制：

```text
npm audit --omit=dev --audit-level=high
```

production gate 已通过，因此当前两项 high finding 属于 development/tooling dependency debt，不是接受进 production/runtime 的依赖。

禁止 blind forced audit upgrade；后续先取得 exact dependency path。

### 6. M10 review and canonical promotion

`ZN.md` 已记录 M10 review：resident/runtime、desktop、build/package/release、CI、provenance、source independence、M8 risk acceptance 和用户授权均已审查。

M8 仍 **PARTIAL**。canonical source promotion 不代表 formal release complete。

真实 promotion sequence：

```text
reviewed HEAD c158517225ff7b8cf0a952a0ae1dd6ebcf9c2c5d
→ full PR CI run 32671245421 success
→ recheck fast-forward relation
→ main update force=false
→ main/dev compare identical
→ canonical main push CI run 32671435423 success
```

没有 merge commit、force push 或历史重写。

canonical run `32671435423`：

```text
ZN Source Boundary        success
ZN Kernel / Python        success
Electron / TypeScript     success
Container / Runtime Smoke skipped by push-event design
Publish commit statuses   success
```

Container 在 exact reviewed PR run `32671245421` 已成功。

### 7. M10 documentation closeout

`docs/ZN-IMPLEMENTATION-STATUS.md` 已改为稳定状态：M10 对 canonical source promotion 为 COMPLETE；M8 继续 PARTIAL。未来 docs-only commit 的实时 CI 仍以 GitHub 当前结果为准，不以文档声称代替验证。

## 当前未完成

1. 2 个 development/tooling npm high finding 的 exact dependency path 与安全修复判断；
2. remaining M8 intended-platform continuity / secure signing / rollback；
3. browser/computer Body/Senses；
4. broader resident engineering competence；
5. SM1+ self-maintenance。

## 风险 / 边界

- 禁止 force push/history rewrite。
- `LICENSE` legal attribution 不得删除或改写。
- M8 不得写成 complete。
- canonical `main` promotion 不等于正式 release。
- historical reference branch 仅供阅读成熟机制，不得重新成为 active runtime/build/release/control-plane dependency。

## Task Queue

### P0 — source evacuation

Status: **COMPLETE**

### P1 — source boundary / regression guard

Status: **COMPLETE**

### P2 — M10 review and canonical source promotion

Status: **COMPLETE**

### P3 — development/tooling dependency audit

Status: **NEXT**

获取 2 个 high findings 的 exact dependency tree，判断是否存在 stable safe upgrade；禁止 blind `--force`。

### P4 — resident competence / M8 / SM1+

Status: **PENDING**

dependency audit → resident-owned engineering competence → remaining M8 continuity/signing/rollback → SM1+。

## 下一真实目标

重新确认 final docs HEAD 的 CI 与 `main`/`dev/zn-agent` exact refs 一致，然后进入 development/tooling npm advisory exact-path investigation。