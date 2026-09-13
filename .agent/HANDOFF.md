# ZN Maintainer Handoff

> Updated: 2026-09-13
>
> Canonical branch: `main`
>
> This is a current-work-site summary, not a changelog. Real code, Git state, tests and CI remain authoritative.

## 接手先恢复现场

接手时必须重新查询 current `main`、open PR、live head、review threads 和 exact-head CI。不要把本文件里的 SHA/CI 当永久事实。

当前工作现场：

- canonical `main` 在 E2E-13 工作期间仍为 `5dbc663c7035dc523e34477501fee59914a8cff4`；如果接手时已变化，以远端为准；
- E2E-13 在 PR #252 / `work/e2e13-current-app-content`；
- PR #252 状态是 **VERIFIED NARROW / representative path closed**，保持 open / unmerged；
- final merge-readiness 只认 PR #252 的最后 live head；任何后续 code/docs commit 都会使旧 exact-head CI 失效；
- 合并前必须重新确认 E2E-13、E2E-15、完整 Windows product-route suite（含 E2E-07）、ZN CI 和所有其他 applicable PR workflows 都是该 final head 的 final success；
- 不要自动 Merge。

## E2E-13 当前真实 closure

代表性用户目标：

> 把我现在开的工作记录整理一下：去掉每行前后空格，删掉空行，重复内容只保留第一次，然后保存。

准确状态：**VERIFIED NARROW / representative path closed**。

现有 Product Resident 仍是唯一任务 owner，现有 Product Body 仍是唯一 mutation surface。没有新增 DesktopAgent、AppAgent、DialogAgent、第二 Resident、第二 Router/Store 或 RPA engine。

代表性链路：

```text
desktop_user_event
-> typed foreground-desktop cleanup goal
-> fresh foreground HWND/PID/process
-> unique exact multiline UIA Edit
-> bounded ValuePattern read
-> deterministic trim / drop blank / stable exact dedupe
-> fresh exact identity + source-content revalidation
-> guarded exact ValuePattern replacement
-> fresh post-replacement reread
-> fresh exact Save Button
-> existing durable pointer-click lifecycle
-> at most one Save dispatch
-> discard old HWND / RuntimeIds
-> fresh same-process replacement window
-> exact read-only 保存内容 ValuePattern read
-> chars/SHA-256 verification
-> independent Root Work acceptance
```

Raw source/result text is transient only. Durable WorkingState, Body history and audit retain bounded semantic/provenance metadata, counts and SHA-256; `replacement_text` is redacted from durable Body action JSON. Raw app content is not sent to a model.

## SetValue crash-window / restart repair

E2E-13 uses the existing `resident_side_effect_attempts` journal. `ValuePattern.SetValue` is not treated as idempotent.

The key repair is ordering: before normal source-content drift handling, E2E-13 queries durable `automation_value_replace` ownership by current event + action kind. Prior attempts in `started`, `observed`, or `verified_effect` remain authoritative across restart even if fresh current text would generate different action arguments/signature.

Recovery rules:

- fresh-bind the same bounded foreground process/window and exact named Edit;
- perform read-only fresh ValuePattern read;
- compare the previous expected result by bounded chars/SHA-256;
- exact expected result -> resolve/retain the old attempt as `verified_effect` and continue from fresh replacement verification;
- mismatch / lost authority / ambiguity -> fail closed;
- never generate a new replacement signature merely because current text changed after the earlier dispatch boundary;
- never blindly replay `SetValue`.

Persistent SQLite + real Resident rebuild regressions cover:

1. crash after durable `started`, while the outside-world value already equals expected result;
2. crash after Body observed success but before WorkingState checkpoint advances;
3. second crash after machine reconciliation recorded `verified_effect` but before WorkingState advances;
4. restart mismatch / user-edited content, which must fail closed with zero new replacement dispatch.

## Real Windows acceptance scope

The Windows Interactive workflow has explicit E2E-13 and E2E-15 steps before the broader product-route sweep.

E2E-13 real WinForms coverage includes:

- happy cleanup + exactly one Save + fresh replacement-window readback;
- stale Edit RuntimeId -> reject stale authority and fresh re-ground;
- pre-dispatch source drift -> reject stale transform and recompute;
- ambiguous same-name Edit -> zero mutation / zero Save;
- final-result mismatch -> no Root completion.

E2E-15 remains the previously closed bounded same-process `ShowDialog()` recovery path. E2E-13 does not replace or broaden it.

## E2E-07 regression found during PR #252

The Windows suite exposed a stable E2E-07 fixture regression. On the same head, a rerun reproduced the identical failure: `Page.windowOpen` existed, but no fresh root-opener child could be proven. Therefore this was not classified as a one-off runner timing flake.

Two attempted production browser-extension stabilizations were deliberately **reverted**:

- longer post-click observation window;
- fresh enumeration of candidate tabs.

Neither produced the missing opener proof. `apps/desktop/browser-extension/research-background.js` is restored to canonical `main` behavior. Do not reintroduce those changes merely to make E2E-13 green.

Root cause is in the E2E fixture contract: modern HTML treats `<form target="_blank">` as noopener unless opener semantics are explicitly requested, while E2E-07 intentionally requires exact opener-bound causal proof. The fixture now uses `rel="opener"` so it actually creates the representative relationship being verified.

Production safety remains unchanged:

- exact causal child/root proof;
- fresh opener reread;
- exact authorization generation binding;
- bounded task-scoped child authority;
- return to exact root and fresh root re-ground;
- a possibly executed causal click is never blindly replayed.

The existing test-only `_authorize_current_tab` helper may retry a real extension shortcut at most three times, and only while fresh evidence says authorization is absent. It is setup stabilization, not an authorization bypass.

## Canonical status language

Use exactly this level of claim for E2E-13:

**VERIFIED NARROW / representative path closed**

Do not promote it to:

- Desktop complete;
- arbitrary Windows application automation;
- general RPA;
- arbitrary rich-text/document editing;
- Office automation;
- universal UIA;
- clipboard/OCR authority;
- Save As support;
- arbitrary keyboard-shortcut automation.

## Existing important baselines not to duplicate

The repository already contains representative closures for Research & Information Work, Local DOCX/XLSX, evidence-driven DOCX completion, USER Browser authenticated work, E2E-07 causal child, E2E-08 user-presence OTP handoff, E2E-15 same-process modal recovery, E2E-24 Browser+File+Desktop, steering/continuation, supervision/restart, E2E-35 status-first continuation, E2E-36 uncertain-side-effect resolution, Memory/Learned Behavior and bounded dependency/readiness.

Read the canonical status docs before proposing new substrate. A new real failure in one of those areas is a coverage/boundary problem until repository evidence proves the substrate itself is missing.

## Core ownership boundaries to preserve

- one Resident owns Root Work;
- worker/model are replaceable cognition/execution resources, not ZN identity or completion truth;
- one durable Work/progress truth;
- one ModelRouter;
- current authority + fresh evidence before mutation;
- side-effect attempt ownership survives restart;
- worker/model/tool success is not Root completion;
- completed/uncertain outside-world effects are not blindly replayed;
- representative closure is not whole-class product closure.

## Next action after PR #252

Do not start a new E2E-13 implementation after PR #252 is verified. Choose future work from `docs/ZN-REAL-TASK-E2E-CATALOG.md` and `docs/ZN-NEXT-PHASE.md` based on the highest-value ordinary user task still blocked by current `main`.

PR #252 itself must remain unmerged until its **last** head has all applicable exact-head CI final success and GitHub has no remaining merge/review blocker. PR body is the place to record the final immutable head and final workflow run IDs after that final CI completes.
