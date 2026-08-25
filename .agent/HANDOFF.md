# ZN Agent Handoff

更新时间：2026-08-25

## 当前目标

当前主线仍是 **browser/computer Body/Senses**。本阶段已经把 narrow pointer click 的“局部效果证据 → 整个事件成功”漏洞收紧：只有明确 `effect_probe` 且 `completion_scope` 精确绑定 `verified_effect / visual_region_changed` 的事件，才允许局部视觉变化关闭整个事件；普通 `user_task` 或更宽语义在任何 pointer movement/input 前 fail closed。

下一真实目标不是扩大 input/browser authority，而是：**设计并验证更强的 typed semantic/current-world outcome contract，使高层 UI/application/world completion 只能由与该语义匹配的新鲜现实证据完成。**

核心原则：

> **ZN uses models. Models do not own ZN.**

## 当前分支 / HEAD

- 固定开发分支：`dev/zn-agent`
- canonical source/release branch：`main`
- 本 HANDOFF 写入前 implementation HEAD：`de61fef5e24eb8a2f2fb99a389bf77b21faddcef`
- canonical `main`：`8234a835dea604783cea0bd9d28a40de654ec03d`
- implementation HEAD 相对 `main`：ahead 77、behind 0；本状态同步 commit 会再前进一次
- PR #6：draft/open，base `main`，head `dev/zn-agent`，未合并
- `main` 未修改；没有 force push/history rewrite

## 已完成事项

### 1. Existing verifier / visual / pointer foundations

Repository verifier manifest 仍只有三条真实 literal target/test relation，不为数量扩张。`NativeVisualSense` 与 on-demand `NativeVisualRegionSense` 仍由 resident service 所有；正式 runtime owns `Pillow==12.3.0`。Pointer movement 仍要求 explicit normalized target + fresh `pointer_state` verification。

Historical exact evidence:

```text
pointer movement          run 32844167956   393 passed / 5 skipped
local visual region Sense run 32847172662   397 passed / 5 skipped
```

### 2. Narrow pointer click lifecycle

Key commits:

```text
44ecb72d4c58f2c75a8e5c5d65d1820e64ceeed4  feat: add verified pointer click lifecycle
e2ab7600cafd18ca0956932af43fe6ae83f82449  refactor: minimize pointer body diff
a32c0f0dfd34e47371530e0ded2368401d3a8efb  test: align click success assertion with terminal lifecycle
de61fef5e24eb8a2f2fb99a389bf77b21faddcef  fix: bind pointer click completion scope
```

Current active construction:

```text
provider_bridge.build_resident_runtime()
→ build_runtime() / KernelStore / ZN-owned cognitive resources
→ CognitiveBudgetManager
→ EffectScopedPointerClickResidentRuntime
→ VerifiedPointerClickResidentRuntime
→ existing repository-verifying / procedural / world-aware inheritance chain
```

Current click call chain:

```text
structured body_action/native_action
→ NativeActionIntent(kind="pointer_click")
→ require explicit expected_outcome.kind="visual_region_changed"
→ require event.kind="effect_probe"
→ require completion_scope.kind="verified_effect"
→ require completion_scope.effect_kind="visual_region_changed"
→ pointer_move(explicit normalized target)
→ fresh pointer_state confirms target
→ persist prepared state
→ fresh local visual baseline
→ persist execution-start marker before input
→ NativeBody.pointer_click
→ exactly one left click only if cursor still matches target
→ native_verification
→ fresh local region observation
→ matching local effect may close only this effect-scoped event
→ contradiction/unavailable evidence → Investigation
```

Body boundary remains:

- no implicit movement inside `pointer_click`;
- left button only;
- current cursor must still match explicit target within one pixel;
- Windows input delivery result is Body evidence only, never semantic completion proof;
- unresolved durable `started` marker prevents blind replay.

### 3. Event-level completion scope guard

The real bug traced before this change was:

```text
pointer local visual signature changed
→ _complete_successful_body_action()
→ ResidentRunResult(success=True)
→ Resident._complete_result()
→ whole AgentEvent terminal success
```

The generic completion helper also called `self_model.observe_native_outcome(event.task, ...)`, so broad task prose could receive native ability credit even when only a narrow local click effect had been verified.

`EffectScopedPointerClickResidentRuntime` now closes this hole for pointer click:

- ordinary `user_task` click is rejected before pointer movement;
- missing/invalid/broader `completion_scope` is rejected before pointer movement;
- unknown scope fields cannot create authority;
- only exact `effect_probe + verified_effect/visual_region_changed` may use local visual evidence as terminal event proof;
- effect-only pointer-click success does not credit arbitrary `event.task` prose as native self ability;
- defensive post-input scope drift refuses success and returns to Investigation without replaying pointer input.

This is a fail-closed guard, **not** a semantic verifier. “submitted form”, “message sent”, “purchase completed”, etc. remain unsupported completion claims unless a future typed verifier obtains matching fresh current-world evidence.

## 真实测试 / CI

Authoritative implementation-head evidence:

```text
run  32861070432
head de61fef5e24eb8a2f2fb99a389bf77b21faddcef

ZN Kernel / Python / Windows        success
ZN Source Boundary / Windows        success
Electron / TypeScript / Windows     success
Publish Windows CI statuses         success
```

Kernel evidence:

```text
fresh isolated Python 3.12.13       success
formal runtime install              success
29 runtime packages                 installed
Pillow 12.3.0                       installed
zero-model resident boot            success
resident core compile               success
full unittest discovery             405 tests passed, 5 skipped
```

All eight pointer-click lifecycle tests passed:

```text
test_pointer_click_body_never_moves_implicitly
test_click_waits_for_position_baseline_and_fresh_effect_verification
test_interrupted_started_click_is_not_replayed
test_unchanged_local_region_contradicts_click_completion
test_click_without_narrow_visual_postcondition_fails_before_input
test_user_task_click_is_rejected_before_pointer_movement
test_effect_probe_without_exact_completion_scope_fails_before_input
test_effect_probe_completion_does_not_credit_task_prose_as_native_ability
```

Electron evidence in the same run: locked install, high-severity audit, typecheck, bundle, desktop ownership/runtime/update/handoff tests and release/runtime artifact verifiers all passed.

Current environment still has no private-repository local checkout. Local validation for generated changes was limited to static Python compilation before commit; GitHub Actions on the exact commit is the authoritative executed suite.

## Diff / PR / ownership 对账

Implementation commit `de61fef5...` was created atomically from three files and reviewed before branch movement:

```text
runtime/python/zn_agent/core/pointer_click_completion_resident.py  new
runtime/python/zn_agent/core/provider_bridge.py                    2-line active builder switch
tests/zn_agent/core/test_pointer_click_lifecycle.py                lifecycle + 3 regressions
```

Before fast-forwarding dev, parent→commit diff showed exactly those three files. `dev/zn-agent` was advanced with `force=false`.

Current ownership facts before this docs sync:

- `main` remains `8234a835dea604783cea0bd9d28a40de654ec03d`;
- `dev/zn-agent` implementation head is ahead 77 / behind 0;
- PR #6 remains draft/open/unmerged;
- Source Boundary exact-head job is green;
- active resident/control plane remains ZN-only;
- no keyboard/right-click/double-click/drag/generic browser mutation catalog was added.

## 风险 / 边界

- Do not modify `main` through ordinary development.
- No force push/history rewrite.
- `visual_region_changed` is local effect evidence only.
- The new `effect_probe` guard must not be relaxed just to make broad UI tasks executable.
- Higher-level completion requires a typed outcome contract plus fresh evidence appropriate to that exact contract.
- Task prose, model output, Body API success, or “something changed visually” cannot independently prove semantic/world success.
- Real Windows interactive-desktop/screenshot evidence is still absent; injected probes are not real-session E2E.
- Broader input authority remains intentionally absent.
- Node action runtime deprecation warnings remain non-blocking maintenance debt.
- M8 updater/rollback/signing remains a high-risk partial milestone.

## Task Queue

### P0 — exact-head Windows CI
Status: **GREEN THROUGH `de61fef5...` / RUN `32861070432`**

This STATUS/HANDOFF sync creates a later docs HEAD. Let automatic CI verify it; do not create an infinite docs-only loop merely to record its own run ID.

### P1 — bounded verifier manifest
Status: **VERIFIED NARROW SLICE / THREE REAL RELATIONS**

### P2 — resident visual foundation
Status: **VERIFIED FOUNDATION**

Real interactive-desktop capture evidence remains open.

### P3 — bounded pointer movement
Status: **VERIFIED**

### P4 — narrow pointer click lifecycle
Status: **VERIFIED NARROW SLICE**

### P5 — semantic/current-world UI verification
Status: **PARTIAL GUARD VERIFIED / SEMANTIC VERIFIER NEXT**

Completed in this stage:

```text
explicit pointer-click action authority
+ explicit local visual effect contract
+ exact event-level effect completion scope
+ fresh local visual evidence
→ only the matching local effect_probe may terminal-complete
```

Still open:

```text
explicit higher-level semantic outcome contract
+ fresh current-world evidence appropriate to that semantic contract
→ only matching higher-level outcome may complete
```

The next implementation must not infer completion authority from natural-language task text or model claims.

### P6 — M8 Windows continuity / rollback / signing
Status: **PENDING / PARTIAL**

### P7 — SM1+ self-maintenance
Status: **PENDING**

## 下一真实目标

1. verify this docs-sync HEAD on automatic Windows x64 CI;
2. trace which existing Senses/evidence types could support a **typed semantic UI outcome** without creating new mutation authority;
3. define the smallest higher-level completion contract and verifier boundary before adding any new input primitive;
4. if current Senses cannot prove such an outcome, add the smallest read-only Sense first rather than weakening proof requirements;
5. keep M8 partial and leave `main` untouched.
