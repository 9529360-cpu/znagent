# ZN Agent Handoff

更新时间：2026-08-24

## 当前目标

完成 active tree 的最终参考产品明文清理与防回流硬门槛，随后用 fresh CI 做 M10 晋升审查。用户已明确授权：参考源码保留在独立参考分支；active ZN 清理完成且 M10 条件满足后，将 `dev/zn-agent` 以非强制 fast-forward 晋升到 `main`。

核心原则：

> **ZN uses models. Models do not own ZN.**

## 当前分支 / HEAD

- 固定开发分支：`dev/zn-agent`
- 本次 HANDOFF 同步前 branch HEAD：`707fd84daa281408324b7ee2ab5bec0c4272caf4`
- bulk physical source evacuation：`6d5f78d22883857fcc99aff5cfd4ba1b9a2d3e6b`
- previous steady-state full CI authority：`732e03c413e9d222dc97c729051ba78f952f23c2` / run `32669724116`
- `main` 在本文件写入时仍是 `61dd880aa4bbbdb359ca544b752afc2c22845ce9`
- 独立 upstream reference branch 已核实与该旧 `main` commit 完全相同，旧源码已有单独参考落点。
- 接手者必须重新读取 GitHub exact HEAD；本文件不能自引用其自身最终 commit SHA。

## 已完成

### 1. 物理源撤离

用户已授权的大规模删除已经真实落盘，不是 shim/compatibility 隐藏层。

bulk commit：

```text
6d5f78d22883857fcc99aff5cfd4ba1b9a2d3e6b
```

one-shot verification run：

```text
32669071891
```

真实结果：

```text
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

active high-level tree 仅保留 ZN-owned `.agent/.github/apps/docs/runtime/tests` 与必要 root metadata；一次性迁移脚本和写入型 migration CI 已退役。

### 2. 参考源码独立保留

已通过 GitHub commit compare 核实：独立 upstream reference branch 与旧 `main` commit `61dd880aa4bbbdb359ca544b752afc2c22845ce9` 完全相同。

因此不需要在 active tree 再留一份源码，也不需要重写 Git 历史。参考分支仅用于未来阅读成熟机制，不是 runtime/build/release dependency。

### 3. 防回流 source-boundary guard

新增：

```text
.agent/verify_zn_source_boundary.py
```

CI 新增 `ZN Source Boundary` job，扫描全部 tracked path 和非二进制 tracked text，阻止退休产品标识、旧 namespace 和旧物理路径重新进入 active tree。

法律例外只有 `LICENSE` 文本内容：原版权归属必须按许可证要求原样保留；路径仍受扫描。

`zn-ci.yml` 现在同时在 `dev/zn-agent` 与 `main` push 上运行，以便晋升后 canonical branch 继续受到同一门槛保护。

### 4. 最后一轮明文清理

source-boundary run `32670680951` 精确暴露了最后一批残留；它们不是运行时依赖，而是历史说明或防回归测试字符串。

已清理/编码而不降低拒绝能力：

- desktop bundler 注释；
- packaged runtime/staging/verifier 中退休包拒绝 marker；
- desktop ownership/runtime tests 中退休产品 marker；
- cognition/web/result/url safety 注释和 docstring；
- resident autostart 与 runtime ownership tests 的旧 namespace/package marker；
- implementation status 的旧物理路径明文；
- 本 HANDOFF 的旧路径明文。

防回归检查改为 hex-decoded marker，只让测试在运行时构造退休标识，active tracked text 不再保存这些产品文字。

### 5. release/update ownership

当前 release workflow 完全由 ZN-owned build/package/runtime verifier/public channel 组成；formal tag 通过 immutable assets → GitHub Release → `stable.json` 最后推进。

Linux AppImage N→N+1 workflow 仍保留真实 installed update smoke；本轮删除了其中已经失效的旧路径触发项。

## 当前验证

此前完整 steady-state PR CI：

```text
run 32669724116
ZN Kernel / Python         success
Electron / TypeScript     success
Container / Runtime Smoke success
```

本轮 source-boundary 初次 fresh run：

```text
run 32670680951
ZN Source Boundary        failure
```

失败清单已全部按日志逐项修复；该 run 的其他 jobs 在修复提交出现后不再作为 final authority。必须对当前最终 HEAD 再跑一次完整 PR CI，确认 Source Boundary + Python + Electron + Container 全绿后，才能继续 M10 晋升。

## 当前未完成

- final source-boundary + full CI on the exact final cleanup HEAD；
- M10 风险审查与状态文档最终同步；
- `main` fast-forward promotion；
- promotion 后 `main` push CI 复验；
- Node packaging 的 2 个 high-severity audit finding 精确依赖链；
- M8 中除现有 Linux update smoke 外的 intended-platform continuity、real signing/notarization、real-version rollback；
- general browser/computer-use Body/Senses；
- broader resident engineering competence；
- SM1+ self-maintenance。

## 风险 / 边界

1. `LICENSE` 中原版权归属是法律 provenance，不得为文字清理而删除或改写。
2. 2 个 Node high advisory 尚未获得 exact audit dependency path；禁止盲目 `--force` 或 alpha/major upgrade。
3. M8 仍 PARTIAL。M10 允许的判断必须明确区分“把 ZN 设为 canonical main”与“宣称 formal release continuity 已全部完成”。若 unresolved release risk 对 branch promotion 可接受，必须在状态文档明确记录；不得把 M8 partial 写成 complete。
4. promotion 只能是 normal fast-forward，禁止 force push/history rewrite。
5. verification-only PR #5 不应被 merge；它只是 current-head PR CI 触发器，晋升应在 M10 通过后直接 fast-forward `main` ref。

## Task Queue

### P0 — active source evacuation

Status: **COMPLETE**

### P1 — text-clean source boundary + regression guard

Status: **IMPLEMENTED, FINAL CI PENDING**

下一步先跑 current-head PR CI；若 Source Boundary 仍失败，只按真实日志清理，不弱化 guard（法律 provenance 例外除外）。

### P2 — M10 branch-promotion review

Status: **PENDING P1 GREEN**

fresh review：resident/runtime、desktop、build/release、CI、license/provenance、source independence、M8 risk acceptance、用户授权。

### P3 — main promotion

Status: **AUTHORIZED BY USER, BLOCKED UNTIL P2 PASSES**

若 P2 通过：recheck `main...dev`, require fast-forward only, update `main` ref with force=false, then verify `main` push CI and close verification PR without merge.

### P4 — remaining engineering debt

Status: **PENDING**

Node audit exact path → M8 remaining continuity/signing/rollback → resident competence → SM1+。

## 下一真实目标

对当前 `dev/zn-agent` 最终清理 HEAD 跑 fresh full PR CI。只有 Source Boundary、Python、Electron、Container 全绿后，才执行 M10 final review 与非强制 `main` 晋升。