# ZN Agent Handoff

更新时间：2026-08-25

## 当前目标

当前主线仍是 **browser/computer Body/Senses**，但施工点已经从“click 生命周期调查”前进到：**最小 typed pointer click 已通过 exact-head Windows x64 CI；下一步是把 local effect 与更高层 semantic/current-world outcome 严格分开，并在扩大任何 browser/input authority 之前增强验证。**

核心原则：

> **ZN uses models. Models do not own ZN.**

Windows x64 仍是 intended product / steady-state CI target；Linux/macOS 仅 optional/on-demand。M8 Windows clean install / N→N+1 / rollback / signing 仍是独立 partial milestone。

## 当前分支 / HEAD

- 固定开发分支：`dev/zn-agent`
- canonical source/release branch：`main`
- 本 HANDOFF 写入前开发 HEAD：`a32c0f0dfd34e47371530e0ded2368401d3a8efb`
- canonical `main`：`8234a835dea604783cea0bd9d28a40de654ec03d`
- `dev/zn-agent` 相对 `main`：ahead 75、behind 0；本状态同步 commit 会再前进一次
- PR #6：draft/open，base `main`，head `dev/zn-agent`，未合并
- `main` 未修改；没有 force push/history rewrite

## 已完成事项

### 1. Repository-owned verifier / Windows engineering slices

Verifier manifest 保持三条真实 relation，不为数量扩张：

```text
runtime/python/zn_agent/core/repo_test_semantics.py
→ tests/zn_agent/core/test_repo_test_semantics_authority.py

runtime/python/zn_agent/core/git_semantics.py
→ tests/zn_agent/core/test_git_staging_semantics.py

runtime/python/zn_agent/core/result_semantics.py
→ tests/zn_agent/core/test_verified_experience.py
```

Manifest 只能提供 literal target/test relation，不能创建 command/shell/model/task-prose authority。

### 2. Resident visual foundation

Formal runtime owns `Pillow==12.3.0`. `ResidentSocketService` owns persistent `NativeVisualSense` and on-demand read-only `NativeVisualRegionSense`。Region probe only returns compact local signature/luminance/bounds; raw pixels are discarded and the probe does not create mutation authority or another agent.

Exact run `32847172662` verified the target-local visual probe foundation with 397 passed / 5 skipped.

### 3. Verified bounded pointer movement

```text
83f45fd922ebc216933987d269b3c797d3875f2b  feat: add verified pointer movement
```

Typed `pointer_move` accepts only finite normalized coordinates; side-effect success is followed by fresh `pointer_state`; cursor drift contradicts completion. Exact run `32844167956` passed with 393 tests / 5 skipped.

### 4. Verified narrow pointer click lifecycle

Key commits:

```text
44ecb72d4c58f2c75a8e5c5d65d1820e64ceeed4  feat: add verified pointer click lifecycle
e2ab7600cafd18ca0956932af43fe6ae83f82449  refactor: minimize pointer body diff
a32c0f0dfd34e47371530e0ded2368401d3a8efb  test: align click success assertion with terminal lifecycle
```

Active builder/call chain:

```text
provider_bridge.build_resident_runtime()
→ VerifiedPointerClickResidentRuntime
→ RepositoryVerifyingResidentRuntime inheritance chain remains active
→ NativeActionIntent(kind="pointer_click")
→ require explicit expected_outcome.kind="visual_region_changed"
→ pointer_move(explicit normalized target)
→ fresh pointer_state confirms target
→ persist prepared click state
→ fresh target-local visual baseline
→ persist execution-start marker before input
→ NativeBody.act("pointer_click")
→ one left click only if cursor still matches target
→ native_verification
→ fresh target-local visual probe
→ changed signature: narrow visual_region_changed completion
→ unchanged/unavailable: contradiction → Investigation
```

Body primitive boundary:

- `pointer_click` never moves the cursor implicitly;
- only left button is accepted;
- current cursor must still match explicit target within one pixel;
- Windows `SendInput` delivery result is only Body evidence, never completion proof.

Resident lifecycle boundary:

- missing/invalid `visual_region_changed` expected outcome fails before input;
- missing resident-owned visual region Sense fails before input;
- pointer is freshly re-observed after positioning;
- local baseline is captured after hover/position effects and before click;
- execution `started` marker is durable before input;
- an interrupted `started` click is treated as unknowable delivery and is not replayed blindly;
- post-click fresh local visual observation is required;
- unchanged region returns to Investigation and negative evidence;
- changed region proves only the explicitly typed local visual effect, not a broader UI/business goal.

### 5. Exact-head CI for click slice

Authoritative implementation-head evidence:

```text
run  32854445588
head a32c0f0dfd34e47371530e0ded2368401d3a8efb

ZN Kernel / Python / Windows        success
ZN Source Boundary / Windows        success
Electron / TypeScript / Windows     success
Publish Windows CI statuses         success
```

Kernel evidence:

```text
fresh isolated Python 3.12.13       success
formal znagent runtime install       success
29 runtime packages installed        success
pillow==12.3.0                       installed
zero-model resident boot             success
resident core compile                success
full core unittest discovery         402 tests passed, 5 skipped
```

Five new click tests all passed:

```text
test_pointer_click_body_never_moves_implicitly
test_click_waits_for_position_baseline_and_fresh_effect_verification
test_interrupted_started_click_is_not_replayed
test_unchanged_local_region_contradicts_click_completion
test_click_without_narrow_visual_postcondition_fails_before_input
```

The immediately prior run `32853366923` had one test error only: after successful terminal completion the test tried to read `native_verification_result` from WorkingState that the existing lifecycle had already cleared. Other click tests and product behavior passed. The assertion was corrected in `a32c0f0...`; exact-head run `32854445588` then passed the whole suite.

## 当前真实调用链

### Active resident construction

```text
provider_bridge.build_resident_runtime()
→ build_runtime() / KernelStore / ZN-owned cognitive resources
→ CognitiveBudgetManager
→ VerifiedPointerClickResidentRuntime(kernel, budget)
```

This keeps the existing repository-verifying/procedural/world-aware inheritance chain active; click is an additional narrow lifecycle, not a replacement runtime.

### Pointer click

```text
structured body_action/native_action
→ NativeActionIntent(kind="pointer_click")
→ VerifiedPointerClickResidentRuntime._native_action_step()
→ explicit visual_region_changed contract
→ position + fresh pointer verification
→ fresh local baseline
→ durable non-replayable start marker
→ NativeBody.pointer_click
→ native_verification
→ fresh local region observation
→ local effect success OR contradiction
```

### Target-local visual Sense

```text
ResidentSocketService
→ NativeVisualRegionSense
→ explicit bounded probe
→ local derivative/signature
→ VisualRegionObservation
```

It remains synchronous/read-only relative to persistent retina/nervous memory.

## 真实测试 / CI

Latest authoritative implementation-head evidence is run `32854445588` at `a32c0f0...`: all four Windows jobs success; kernel full discovery ran 402 tests with 5 skips and no failures.

Current environment does not have a private-repository local checkout. No unexecuted local suite is presented as validation; authoritative evidence comes from GitHub Actions on the exact commit.

## Diff / PR / ownership 对账

- `main` remains `8234a835dea604783cea0bd9d28a40de654ec03d`, unchanged.
- `dev/zn-agent` is ahead 75 / behind 0 before this docs sync.
- PR #6 remains draft/open and unmerged; its head is `a32c0f0...` before this docs sync.
- Active tree is still ZN-only; exact-head Source Boundary passed.
- `provider_bridge` now constructs `VerifiedPointerClickResidentRuntime`; no historical product runtime/control plane was restored.
- Click implementation is isolated in `pointer_click_resident.py` plus the bounded Body primitive and tests.
- No keyboard/right-click/double-click/drag/browser mutation catalog was added.

## 风险 / 边界

- Do not modify `main` through ordinary development.
- No force push/history rewrite.
- `visual_region_changed` proves a local visual effect only. It must not silently become proof that a broader task such as “submitted form”, “purchase completed”, “message sent”, or other semantic/world outcome succeeded.
- Higher-level completion needs stronger current-world evidence bound to the requested semantics.
- Do not expand pointer/button/browser authority merely because one local click slice is green.
- Real Windows screen capture / interactive desktop availability remains an environment evidence gap; injected tests are not real-session E2E.
- An interrupted click with a persisted `started` marker remains intentionally non-replayable without additional evidence.
- Node-action runtime deprecation warnings are non-blocking maintenance debt; upgrade only through stable verified action versions.
- M8 updater/rollback/signing remains a high-risk release boundary.

## Task Queue

### P0 — exact-head Windows CI
Status: **GREEN THROUGH `a32c0f0...` / RUN `32854445588`**

This STATUS/HANDOFF sync creates a later docs HEAD. Let automatic CI verify it; do not create an infinite docs-only loop merely to record its own run ID.

### P1 — bounded verifier manifest
Status: **VERIFIED NARROW SLICE / THREE REAL RELATIONS**

Do not expand for count.

### P2 — resident visual foundation
Status: **VERIFIED PACKAGING + BACKGROUND RETINA + TARGET-LOCAL READ-ONLY PROBE**

Real-session capture permission/E2E remains open.

### P3 — bounded pointer movement
Status: **VERIFIED**

### P4 — narrow pointer click lifecycle
Status: **VERIFIED NARROW SLICE**

Only one explicit left click + explicit `visual_region_changed` effect is verified. No broader semantic claim.

### P5 — semantic/current-world UI verification
Status: **ACTIVE / NEXT INVESTIGATION**

Next work must trace how a higher-level requested outcome can be represented and independently observed without allowing task prose/model output to create side-effect authority. The key boundary is:

```text
explicit action authority
+ explicit semantic/effect contract
+ fresh current-world evidence appropriate to that contract
→ only matching scope may complete
```

If available evidence proves only local change, completion scope must remain local change.

### P6 — M8 Windows continuity / rollback / signing
Status: **PENDING / PARTIAL**

### P7 — SM1+ self-maintenance
Status: **PENDING**

## 下一真实目标

1. verify the STATUS/HANDOFF sync on automatic Windows x64 CI;
2. trace existing result/postcondition semantics and event completion scope before adding new input primitives;
3. design the smallest stronger semantic/current-world verifier that does not rely on model prose as fact/authority;
4. keep click authority unchanged until that verifier has a real typed contract and tests;
5. retain M8 as partial and leave `main` untouched.
