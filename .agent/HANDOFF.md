# ZN Agent Handoff

Updated: 2026-08-26

## Current goal

Continue durable resident-owned Work from the verified restart/resume, atomic-terminal, and first generic side-effect anti-replay foundations. The next real target is first-class recovery from an uncertain side effect: observe a trustworthy postcondition before any retry when possible, otherwise keep replay blocked and expose explicit cancel/user-decision semantics.

Do not spend the current stage on the deferred Windows NetworkService DOS-8.3 path-identity defect unless it materially blocks current Work development.

Founding boundary remains:

> **ZN uses models. Models do not own ZN.**

## Branch / repository truth

- repository: `9529360-cpu/znagent`
- fixed development branch: `dev/zn-agent`
- canonical source/release branch: `main`
- side-effect recovery implementation head before documentation: `9502b96d94bc1a08d5f0b68a8c2359c51f11ea5a`
- atomic Work checkpoint: `f02582557a39f32273fb806929a6f64906fea547`
- prior Work restart checkpoint: `2bce63a23252b7166244d0afd9dcac63b6b4fc26`
- managed-browser checkpoint: `8c94f1ac9a3fdda2e704f45bdaf02efdc4d40271`
- canonical `main`: `8234a835dea604783cea0bd9d28a40de654ec03d`
- PR #6: draft/open/unmerged, base `main`, head `dev/zn-agent`
- `main` was not modified
- no force push or history rewrite was used

A HANDOFF commit cannot contain its own resulting SHA. Re-read `dev/zn-agent` after this file is committed and report the resulting exact head externally.

## Completed in current stage

### 1. Side-effect interruption call chain was traced

The relevant active path is:

```text
WorkingState(stage=native_action)
-> EmbodiedResidentRuntime / procedural action step
-> final resident Body.act(...)
-> NativeBody dispatch
-> outside-world mutation
-> BodyActionResult persistence
-> verification / investigation
```

`NativeBody.act()` performs dispatch before recording the returned result. Therefore an interruption after a generic side effect but before durable result observation could previously leave Work at the same native action and allow blind replay after restart.

Existing richer non-replayable paths were inspected and deliberately preserved:

- pointer click already persists an execution-start marker before input and refuses blind replay;
- focused keyboard text already persists an execution-start marker before SendInput and refuses blind replay;
- targeted test execution owns its own execution lifecycle.

The uncovered generic classes were command execution and append-style text/file writes.

### 2. Generic pre-dispatch side-effect guard implemented

Implementation sequence:

```text
be594b0e2a9e827fa4d5b7aa849126edbd2afa10
feat: refuse blind replay of generic side effects

5467951d4a71b21b594ed0d0b2b35c70a940bedf
test: close side-effect recovery database handle

9502b96d94bc1a08d5f0b68a8c2359c51f11ea5a
fix: preserve typed body ownership under side-effect guard
```

Relevant files:

```text
runtime/python/zn_agent/core/side_effect_body.py
runtime/python/zn_agent/core/focused_modern_text_resident.py
tests/zn_agent/core/test_work_side_effect_recovery.py
.github/workflows/zn-work-recovery-e2e.yml
```

`SideEffectAwareBody` now guards only:

```text
command / terminal / shell
write_text / write_file with append=true
```

Before dispatch, it writes a committed `started` attempt to `resident_side_effect_attempts` in the same resident SQLite DB. Stored fields are bounded execution metadata plus a SHA-256 signature. Raw commands, appended text, environment values and raw argument payloads are not copied into this recovery ledger.

If the same resident event/action signature is seen with an outstanding `started` attempt, the Body returns fail-closed uncertainty evidence:

```text
side_effect_uncertain = true
replay_blocked = true
```

and does not call the underlying dispatch again.

If dispatch returns a Body result, the attempt becomes `observed` and links to the returned Body action id. A returned failure is still an observed dispatch, not evidence that replay is safe. A normal exception after the pre-dispatch boundary remains uncertain because the outside-world effect may already have happened.

Exact replacement writes (`append=false`) are intentionally unchanged and outside this new guard.

### 3. Real interactive CI found a typed Body ownership regression and it was fixed correctly

The first implementation used composition around the final Body. Real Windows interactive E2E failed because the active Body stopped satisfying the existing `KeyboardTextBody` type contract. That failure was treated as real architecture evidence; the test was not weakened.

`9502b96d` changes `SideEffectAwareBody` into a real `KeyboardTextBody` subtype. The final resident Body therefore preserves keyboard ownership/type semantics while adding only the generic anti-replay boundary.

The test-only `5467951d` commit fixes a Windows temporary-directory cleanup error caused by an unclosed SQLite test connection. It does not change product behavior.

## Real test / CI truth

### Exact implementation focused Work recovery

```text
ZN Work Recovery E2E run 33006103725
head 9502b96d94bc1a08d5f0b68a8c2359c51f11ea5a
runner zn-ci-02 / Windows X64
conclusion success
Ran 12 tests in 7.449s
OK
```

The suite explicitly passed:

```text
test_active_product_resident_preserves_keyboard_body_type_and_side_effect_guard
test_nonreplayable_command_and_append_persist_started_before_dispatch_and_block_after_reopen
test_observed_nonreplayable_dispatch_closes_attempt_and_links_result
test_exact_text_replace_is_not_broadened_into_nonreplayable_guard
```

and all earlier Work restart + atomic terminal tests stayed green.

### Exact implementation interactive desktop regression

```text
ZN Windows Interactive Desktop E2E run 33006103742
head 9502b96d94bc1a08d5f0b68a8c2359c51f11ea5a
runner zn-interactive
conclusion success
Ran 4 tests in 15.213s
OK
```

Real interactive pointer click, Unicode focused text entry, UIA text capability, and installed Edge/Chrome User Browser Bridge state discovery all passed. This is the proof that the typed Body ownership fix restored real desktop behavior.

### Exact implementation managed-browser regression

```text
ZN Managed Browser E2E run 33006103702
head 9502b96d94bc1a08d5f0b68a8c2359c51f11ea5a
runner zn-ci-03 / Windows X64
conclusion success
browser contract tests 71 passed
real Chromium E2E      4 passed
```

The previously verified SELECT_OPTION real Chromium behavior remains intact.

### Ordinary ZN CI

`ZN CI` run `33006103746` was still in progress at the latest implementation-head inspection. Do not call ordinary CI green until all jobs, especially Kernel, actually finish. Later documentation commits create newer heads and may cancel/replace older branch-concurrency runs.

The known NetworkService long-path vs DOS-8.3 path-identity defect remains deferred. Partial work on it was reverted by `db647cb49c3de014aa82bc28ec87c1c4e5b02c15`; do not call it fixed or automatically reopen it.

## Windows runner topology

```text
headless CI:       [self-hosted, Windows, X64, zn-ci]
interactive proof: [self-hosted, Windows, X64, zn-interactive]
```

`zn-interactive` remains real and available: the exact implementation-head interactive run above completed successfully. Keep the visible foreground runner design; do not restore hidden launch, auto-logon, credentials, or Session-0 interactive claims.

## Current risks / blockers

- Work reconstruction is verified.
- Atomic event/outcome/idle terminalization is verified.
- Generic command/append blind replay after an uncertain start is now blocked.
- Pointer-click and keyboard-text dedicated anti-replay lifecycles remain intact.
- Work recovery is still PARTIAL: a blocked uncertain side effect is currently surfaced as Body failure evidence and then falls into normal investigation; it is not yet a first-class recovery state.
- There is not yet a resident-owned rule that proves an interrupted effect from fresh current reality before retry.
- Unverifiable uncertain effects do not yet have explicit cancel/user-decision RPC/UI semantics.
- Do not let uncertainty become ordinary failure learning merely because replay was blocked.
- Life self-observation after durable event completion remains a separate consistency concern.
- Ordinary Kernel CI may remain red on the deferred DOS-8.3 path issue.
- Browser PRESS/generic click/richer editing/multi-select/lifecycle remain open.
- User Browser Bridge control, M8 continuity and SM1+ remain incomplete.
- `main` remains untouched.

## Task queue

### P0 - first-class side-effect recovery / reverification

Status: **NEXT REAL TARGET**

Trace the current Body failure -> native investigation -> Work progress path for `side_effect_uncertain` evidence. Preserve the already-durable started attempt.

Implement a resident-owned distinction:

```text
trustworthy postcondition exists
-> observe current reality before any retry
-> effect proven present: continue without replay
-> effect proven absent and retry demonstrably safe: permit a new attempt

no trustworthy postcondition
-> keep replay blocked
-> explicit recovery/cancel/user decision required
```

Append-style text/file mutation is the best first reverify candidate because a bounded exact postcondition can sometimes be checked without repeating the append. Arbitrary commands will often remain unverifiable and must not be guessed complete or automatically retried.

### P1 - expose uncertainty in Work progress / control plane

Status: **OPEN**

`work_progress` should eventually expose a stable resident-owned recovery state instead of making the UI infer it from an ordinary error string. Cancellation/recovery decisions must belong to ZN, with the UI only as a face/control surface.

### P2 - life observation recovery

Status: **OPEN / SEPARATE FROM EVENT TERMINAL TRUTH**

A durable completed event remains completed even if later self-observation needs repair.

### P3 - browser follow-ons

Status: **OPEN / NOT CURRENT MAJOR TARGET**

PRESS, generic click semantics, richer text editing, multi-select and broader target/page lifecycle remain bounded candidates.

### P4 - deferred Windows DOS-8.3 path identity

Status: **KNOWN / DEFERRED BY USER DECISION**

Resume only if explicitly reprioritized or materially blocking current product work.

### P5 - M8 / SM1+

Status: **OPEN**

Preserve existing human-approval boundaries for high-risk identity, memory, credentials, updater/signing and destructive self-maintenance changes.

## Next real target

Make side-effect uncertainty first-class in Work recovery and add fresh effect reverification before any retry where ZN can prove a trustworthy postcondition. Keep unverifiable actions blocked pending explicit recovery/cancel/user decision. Keep `main` untouched.
