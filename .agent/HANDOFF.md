# ZN Agent Handoff

Updated: 2026-08-26

## Current goal

Continue durable resident-owned Work from the verified restart/resume, atomic terminal, generic anti-replay, append reverification, and sanitized Work recovery projection foundations.

The next real target is explicit resident-owned cancellation/recovery semantics for unverifiable `side_effect_recovery`. A user decision may stop Work, but it must not be misrepresented as proof that an outside-world effect happened or did not happen.

Do not spend the current stage on the deferred Windows NetworkService DOS-8.3 path-identity defect unless it materially blocks current Work development or is explicitly reprioritized.

Founding boundary remains:

> **ZN uses models. Models do not own ZN.**

## Branch / repository truth

- repository: `9529360-cpu/znagent`
- fixed development branch: `dev/zn-agent`
- canonical source/release branch: `main`
- latest implementation head before this HANDOFF update: `643e174bfc6dcdbe313df1a5434427319d5f068f`
- append side-effect reverification checkpoint: `1bcbf410a401755d6037423ea677cb3db1c6217a`
- atomic ownership regression fix: `e74679fee481898c6d4e9260f4134e2ae563e272`
- prior atomic Work checkpoint: `f02582557a39f32273fb806929a6f64906fea547`
- prior Work restart checkpoint: `2bce63a23252b7166244d0afd9dcac63b6b4fc26`
- canonical `main`: `8234a835dea604783cea0bd9d28a40de654ec03d`
- PR #6: draft/open/unmerged, base `main`, head `dev/zn-agent`
- `main` was not modified
- no force push or history rewrite was used

Two normal commits `4ef74c320165e7a0908afc8a29b21489cbae6c90` and `f80407a377a70d6b346110fc77407eb1ede08558` created and then removed an accidental one-line temporary test file. The file is gone; history was not rewritten.

A HANDOFF commit cannot contain its own resulting SHA. Re-read `dev/zn-agent` after this file is committed and report the resulting exact head externally.

## Completed in current stage

### 1. Side-effect uncertainty remains resident-owned recovery truth

Generic non-replayable classes remain deliberately narrow:

```text
command / terminal / shell
write_text / write_file with append=true
```

`SideEffectAwareBody` commits a durable `started` attempt before dispatch. An unresolved same event/action signature blocks duplicate dispatch. The ledger stores bounded metadata/signature only, not raw commands, appended text, environment values, or raw action arguments.

The final resident intercepts generic `side_effect_uncertain` before ordinary failure handling and persists:

```text
stage      = side_effect_recovery
blocked_by = outside_world_effect_uncertain
```

Uncertainty does not automatically become ordinary failure learning.

### 2. Append recovery from current reality is verified

Implementation:

```text
1bcbf410a401755d6037423ea677cb3db1c6217a
feat: recover uncertain append effects from reality
```

For a trustworthy same-target exact append postcondition, recovery first performs read-only `read_text`:

```text
exact final state present
-> verified_effect
-> complete without replay or causal success learning

exact resident-derived pre-dispatch baseline present
-> verified_absent
-> authorize one fresh append
-> normal independent verification follows

unreadable / truncated / divergent
-> remain blocked
-> user_decision_required
```

Generic command uncertainty remains blocked and is never automatically replayed.

Focused proof:

```text
ZN Work Recovery E2E run 33009460955
head 1bcbf410a401755d6037423ea677cb3db1c6217a
runner zn-ci-01 / Windows X64
18/18 passed
```

### 3. `work_progress.recovery` is now a stable sanitized projection

Implementation:

```text
643e174bfc6dcdbe313df1a5434427319d5f068f
feat: expose sanitized Work recovery progress
```

Real call chain:

```text
ResidentRpcServer.handle(work_progress)
-> ResidentWorkLedger.progress(thread_id, event_id)
-> daemon pass-through
```

The projection therefore belongs to `ResidentWorkLedger.progress()`. No new control-plane owner was introduced.

`work_progress` always includes `recovery`. It is non-null only for the requested event's active `side_effect_recovery` stage.

Public allowlist:

```text
status
kind
attempt_id
replay_blocked
verification_kind
decision
reason
verification.action_id
verification.success
verification.truncated
verification.observed_chars
```

Explicitly not exported:

```text
intent_id
signature
raw command
raw appended text
environment values
internal verification path/output
arbitrary WorkingState data
```

Queued, ordinary-processing, and terminal events return `recovery: null`. The projection survives resident reconstruction, and RPC passes it through unchanged.

## Real test / CI truth

### Exact focused Work recovery

```text
ZN Work Recovery E2E run 33011631232
head 643e174bfc6dcdbe313df1a5434427319d5f068f
runner zn-ci-02 / Windows X64
conclusion success
20/20 passed
```

New cases that actually ran and passed:

```text
test_active_side_effect_recovery_is_sanitized_and_survives_reconstruction
test_work_progress_rpc_passes_through_sanitized_recovery
```

All prior Work restart, atomic terminal, rollback, anti-replay, append reverification, and typed Body tests stayed green.

### Exact ordinary ZN CI

```text
ZN CI run 33011631279
head 643e174bfc6dcdbe313df1a5434427319d5f068f
Electron / TypeScript / Windows    success
ZN Source Boundary / Windows       success
ZN Kernel / Python / Windows       failure
Kernel                             569 tests / 16 errors / 5 skipped
```

The new Work recovery projection tests passed inside the full Kernel suite. The 16 errors remain in the known Windows NetworkService DOS-8.3 versus long-path identity family. Representative affected areas are repo targeted-test/text-delta verification and Work terminal artifact cwd identity. Cleanup `PermissionError` traces are secondary fallout after assertions fail.

Do not call ordinary CI green. Do not confuse this deferred path-identity defect with Work recovery projection failures.

The prior partial path fix was reverted normally in `db647cb49c3de014aa82bc28ec87c1c4e5b02c15`; no half-fix remains.

## Windows runner topology

```text
headless CI:       [self-hosted, Windows, X64, zn-ci]
interactive proof: [self-hosted, Windows, X64, zn-interactive]
```

Keep the visible foreground `zn-interactive` design. Do not restore hidden launch, auto-logon, credential expansion, or Session-0 interactive claims.

Previously verified real regressions remain:

```text
ZN Windows Interactive Desktop E2E run 33006103742   success, 4/4
ZN Managed Browser E2E             run 33006103702   success, 71 contract + 4 Chromium
```

## Current risks / blockers

- Work reconstruction is verified.
- Atomic event/outcome/idle terminalization is verified with corrected checkpoint ownership.
- Generic command/append blind replay after an uncertain start is blocked.
- Append effect-present and exact-baseline recovery are verified from fresh reality.
- Uncertainty is not ordinary failure learning.
- Sanitized recovery truth is visible through Work/RPC and survives reconstruction.
- Work durability remains **PARTIAL** because unverifiable uncertainty has no explicit resident-owned cancel/recovery command yet.
- A user cancellation decision is not evidence about whether the outside-world effect occurred.
- Side-effect attempt resolution and event terminalization currently use separate durability boundaries; do not fake atomicity by changing both independently without a crash-recovery invariant.
- Life self-observation after durable completion remains a separate consistency concern.
- Windows NetworkService DOS-8.3 path identity remains known/deferred.
- Browser PRESS/broader click/editing/multi-select/lifecycle, User Browser Bridge control, M8 continuity, and SM1+ remain incomplete.
- `main` remains untouched.

## Task queue

### P0 - explicit resident-owned recovery / cancellation decision

Status: **NEXT REAL TARGET**

Trace and define the truthful invariant before coding.

Requirements:

```text
user decides to stop Work
-> event/work lifecycle may become terminal
-> do NOT claim uncertain external effect was absent or present
-> preserve unresolved effect evidence durably
-> restart must not resurrect cancelled Work into replay
-> no automatic generic-command retry
```

Determine whether unresolved side-effect attempts should remain historical unresolved records or move to a distinct non-epistemic work-cancelled state. If a new ledger status is added, its meaning must not imply effect truth. Keep retention bounded.

Then add one bounded RPC authority owned by ZN, not UI/model/provider text, and prove restart/crash behavior on focused Windows CI.

### P1 - life observation recovery

Status: **OPEN / SEPARATE FROM EVENT TERMINAL TRUTH**

A durable completed event remains completed even if later self-observation needs repair.

### P2 - browser follow-ons

Status: **OPEN / NOT CURRENT MAJOR TARGET**

PRESS, broader click semantics, richer text editing, multi-select, and broader page/target lifecycle remain bounded candidates.

### P3 - deferred Windows DOS-8.3 path identity

Status: **KNOWN / DEFERRED**

Resume only if explicitly reprioritized or materially blocking current product work.

### P4 - M8 / SM1+

Status: **OPEN**

Preserve human approval for high-risk identity, memory, credentials, updater/signing, and destructive self-maintenance changes.

## Related files

```text
runtime/python/zn_agent/core/store.py
runtime/python/zn_agent/core/work.py
runtime/python/zn_agent/core/side_effect_body.py
runtime/python/zn_agent/core/focused_modern_text_resident.py
runtime/python/zn_agent/core/resident.py
runtime/python/zn_agent/core/daemon.py
tests/zn_agent/core/test_work_progress.py
tests/zn_agent/core/test_work_recovery.py
tests/zn_agent/core/test_work_side_effect_recovery.py
.github/workflows/zn-work-recovery-e2e.yml
```

## Next real target

Define and implement truthful explicit cancellation/recovery semantics for unverifiable side effects. Preserve uncertain external-effect evidence, keep replay blocked, make restart behavior deterministic, and keep `main` untouched.
