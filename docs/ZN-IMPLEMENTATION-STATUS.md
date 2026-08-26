# ZN implementation status

> Architecture contract: [`../ZN.md`](../ZN.md)
>
> Product capability ledger: [`ZN-PRODUCT-CAPABILITY-MAP.md`](ZN-PRODUCT-CAPABILITY-MAP.md)
>
> Source adoption boundary: [`ZN-SOURCE-EXTRACTION.md`](ZN-SOURCE-EXTRACTION.md)
>
> Self-maintenance contract: [`ZN-SELF-MAINTENANCE.md`](ZN-SELF-MAINTENANCE.md)
>
> Real code, Git state and CI outrank this ledger.

Development branch: `dev/zn-agent`. Canonical source/release branch: `main`.

## Current checkpoint - 2026-08-26

M10 canonical source promotion remains complete. Ordinary development remains on `dev/zn-agent`; `main` remains unchanged at `8234a835dea604783cea0bd9d28a40de654ec03d`.

Latest implementation checkpoint before this documentation update:

```text
643e174bfc6dcdbe313df1a5434427319d5f068f
feat: expose sanitized Work recovery progress
```

Status: **DURABLE WORK RESTART/RESUME, ATOMIC TERMINALIZATION, GENERIC PRE-DISPATCH ANTI-REPLAY, APPEND SIDE-EFFECT REVERIFICATION, AND A SANITIZED WORK RECOVERY PROJECTION ARE VERIFIED. WORK DURABILITY REMAINS PARTIAL BECAUSE UNVERIFIABLE SIDE EFFECTS STILL NEED AN EXPLICIT RESIDENT-OWNED CANCEL/RECOVERY DECISION PATH.**

## 1. Durable Work and atomic terminal truth

The active ownership chain remains:

```text
ResidentRpcServer work_start / work_progress
-> ResidentWorkLedger
-> resident event lifecycle
-> KernelStore events + singleton WorkingState
-> resident life stages
-> EventOutcome
-> Work finalization
```

`WorkingState` remains the only resident-owned active checkpoint. Interrupted `PROCESSING` work returns to `PENDING` on reconstruction while the exact stage and next action survive for the same event.

Atomic terminalization publishes terminal event state, the exact durable `EventOutcome`, and idle `WorkingState` in one SQLite transaction. The corrected ownership invariant is:

```text
idle/unowned checkpoint  -> completion allowed
same-event checkpoint    -> completion allowed
foreign active checkpoint -> completion refused
```

Regression fix and proof:

```text
e74679fee481898c6d4e9260f4134e2ae563e272
fix: allow atomic completion from idle checkpoint
ZN Work Recovery E2E run 33008119594   success
14/14 tests passed
```

## 2. Generic side-effect anti-replay and recovery

The generic side-effect boundary remains deliberately narrow:

```text
command / terminal / shell
write_text / write_file with append=true
```

Before dispatch, `SideEffectAwareBody` commits a `started` attempt in the resident SQLite database. The ledger stores bounded metadata and a SHA-256 action signature, not raw commands, appended text, environment values, or raw action arguments.

An outstanding `started` attempt blocks duplicate dispatch for the same event/action signature. Pointer click and focused keyboard text retain their richer dedicated anti-replay lifecycles.

The resident now treats generic `side_effect_uncertain` evidence as recovery truth rather than ordinary failure evidence:

```text
stage      = side_effect_recovery
blocked_by = outside_world_effect_uncertain
```

Uncertainty does not automatically become `local_failure`, failed-action learning, negative self-model evidence, or ordinary native investigation.

Implementation checkpoint:

```text
1bcbf410a401755d6037423ea677cb3db1c6217a
feat: recover uncertain append effects from reality
```

For append actions with a trustworthy exact `text_equals` postcondition, recovery first performs read-only `read_text`:

```text
exact final text already present
-> attempt becomes verified_effect
-> complete without replay
-> no causal success learning from the uncertain dispatch

exact resident-derived pre-dispatch baseline still present
-> attempt becomes verified_absent
-> one fresh append is authorized
-> normal independent postcondition verification follows

unreadable / truncated / divergent current state
-> remain side_effect_recovery
-> replay remains blocked
-> explicit decision required
```

Generic command uncertainty remains deliberately blocked with `decision=user_decision_required`; no second command is run to infer whether the first ran.

Focused proof:

```text
ZN Work Recovery E2E run 33009460955
head   1bcbf410a401755d6037423ea677cb3db1c6217a
runner zn-ci-01 / Windows X64
result success
18/18 tests passed
```

## 3. Sanitized Work recovery projection

Implementation:

```text
643e174bfc6dcdbe313df1a5434427319d5f068f
feat: expose sanitized Work recovery progress
```

The real call chain was traced before modification:

```text
ResidentRpcServer.handle(work_progress)
-> ResidentWorkLedger.progress(thread_id, event_id)
-> daemon passes the progress object through unchanged
```

Therefore the projection owner is `ResidentWorkLedger.progress()`, not the daemon or UI.

`work_progress` now always contains a stable `recovery` key. It is non-null only when the requested event currently owns `WorkingState` and its stage is exactly `side_effect_recovery`.

The public recovery object is an allowlist only:

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

It does not export internal intent ids, action signatures, raw command text, appended content, environment values, internal verification paths/output, or arbitrary resident state. Queued, ordinary processing, and terminal work expose `recovery: null`.

Recovery projection survives resident reconstruction and the RPC layer passes the sanitized object through without rebuilding authority.

Exact focused Windows proof:

```text
ZN Work Recovery E2E run 33011631232
head   643e174bfc6dcdbe313df1a5434427319d5f068f
runner zn-ci-02 / Windows X64
result success
20/20 tests passed
```

New projection cases explicitly passed both in the focused suite and again inside the full Kernel suite:

```text
test_active_side_effect_recovery_is_sanitized_and_survives_reconstruction
test_work_progress_rpc_passes_through_sanitized_recovery
```

## 4. Exact ordinary Windows CI truth

Exact implementation-head ordinary CI:

```text
ZN CI run 33011631279
head 643e174bfc6dcdbe313df1a5434427319d5f068f
Electron / TypeScript / Windows    success
ZN Source Boundary / Windows       success
ZN Kernel / Python / Windows       failure
Kernel suite                        569 tests, 16 errors, 5 skipped
```

The new Work recovery projection tests passed inside that full suite. The 16 Kernel errors remain concentrated in the already known Windows NetworkService path-identity defect where the service shell/temporary environment exposes DOS-8.3 aliases such as:

```text
C:\WINDOWS\SERVIC~1\NETWOR~1\AppData\Local\Temp\...
```

while Python/repository expectations use the long identity:

```text
C:\Windows\ServiceProfiles\NetworkService\AppData\Local\Temp\...
```

Affected failures continue to cluster around repository targeted-test/text-delta verification and terminal/work artifact cwd identity. Cleanup `PermissionError` exceptions are secondary fallout after those assertions fail. No new Work recovery projection failure appeared.

This path-identity issue remains **KNOWN / DEFERRED BY CURRENT PRODUCT PRIORITY**. The earlier partial attempted fix was reverted normally in `db647cb49c3de014aa82bc28ec87c1c4e5b02c15`; no half-fix remains. Do not call ordinary CI green, and do not automatically reopen the path work unless it materially blocks the current Work objective or is explicitly reprioritized.

## 5. Windows runner and browser truth

Headless CI remains on `[self-hosted, Windows, X64, zn-ci]`. Interactive proof remains on `[self-hosted, Windows, X64, zn-interactive]`.

The visible foreground interactive runner design remains the accepted operations decision. Do not restore hidden launch, auto-logon, credential expansion, or Session-0 interactive claims.

Previously verified real regressions remain:

```text
ZN Windows Interactive Desktop E2E run 33006103742   success, 4/4
ZN Managed Browser E2E             run 33006103702   success, 71 contract + 4 real Chromium
```

Managed-browser native `SELECT_OPTION` remains verified. Browser PRESS, broader click/editing/multi-select/page lifecycle, authenticated User Browser Bridge control, M8 continuity, and SM1+ remain open.

## 6. Remaining Work recovery gap

The next gap is explicit control over unverifiable uncertainty. A user/control-plane decision to stop work is authority over the resident work lifecycle; it is **not evidence** that an outside-world effect did or did not occur.

Do not implement cancellation by merely changing a Work string or by marking an uncertain side-effect attempt as though its outside-world truth had been resolved. The current side-effect attempt ledger and event terminal transaction are separate durability boundaries, so cancellation semantics need an explicit invariant before coding.

Next order:

```text
1. define resident-owned cancellation/recovery truth for side_effect_recovery
2. preserve unresolved external-effect evidence without pretending effect presence/absence
3. make event terminalization and Work finalization crash-safe
4. add bounded RPC authority for explicit user decision
5. keep automatic replay forbidden for unverifiable commands
6. prove restart/decision behavior on focused Windows CI
```

Work durability remains **PARTIAL** until this explicit control path exists.

M8 Windows continuity remains PARTIAL. SM0 remains verified foundation; SM1+ remains open. High-risk identity, long-term memory, credential/permission, updater/signing, and destructive self-maintenance changes continue to require human approval.
