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

Latest side-effect recovery implementation head before this status-document update:

```text
1bcbf410a401755d6037423ea677cb3db1c6217a
feat: recover uncertain append effects from reality
```

Status: **DURABLE WORK RESTART/RESUME, ATOMIC TERMINALIZATION, GENERIC PRE-DISPATCH ANTI-REPLAY, AND A FIRST RESIDENT-OWNED SIDE-EFFECT REVERIFICATION PATH ARE VERIFIED. WORK DURABILITY REMAINS PARTIAL BECAUSE UNVERIFIABLE SIDE EFFECTS STILL NEED AN EXPLICIT USER/CANCEL/RECOVERY CONTROL PATH.**

## 1. Durable Work foundation

The Work ownership chain remains:

```text
ResidentRpcServer work_start / work_progress
-> ResidentWorkLedger
-> resident event lifecycle
-> KernelStore events + singleton WorkingState
-> resident life stages
-> EventOutcome
-> Work finalization
```

`WorkingState` remains the only resident-owned active checkpoint. Interrupted `PROCESSING` work returns to `PENDING` on reconstruction while the exact stage/next action survives for the same event.

Verified restart checkpoint:

```text
2bce63a23252b7166244d0afd9dcac63b6b4fc26
ZN Work Recovery E2E run 33002232752   success
6/6 tests passed
```

Atomic terminalization remains store-owned: terminal event state, exact durable `EventOutcome`, and idle `WorkingState` are published in one SQLite transaction.

### Atomic checkpoint ownership regression and fix

Ordinary CI later exposed that the first invariant was too strict: a legitimately claimed resident event could complete while the singleton checkpoint was still idle/unowned. Requiring the completing event to already own that checkpoint rejected valid internal completion paths.

The corrected invariant is:

```text
completion may proceed when WorkingState is idle/unowned
completion may proceed when WorkingState belongs to the same event
completion must refuse to clear another event's active checkpoint
```

Fix:

```text
e74679fee481898c6d4e9260f4134e2ae563e272
fix: allow atomic completion from idle checkpoint
```

Exact focused Windows proof:

```text
ZN Work Recovery E2E run 33008119594   success
head e74679fee481898c6d4e9260f4134e2ae563e272
14/14 tests passed
```

New cases explicitly prove idle/unowned completion succeeds and a foreign active checkpoint is refused without changing event/outcome/checkpoint truth. Existing forced-SQL rollback proof remains green.

Ordinary CI run `33008119464` also proves the atomic ownership regression disappeared from the full core suite. Its remaining Kernel failures were the previously known NetworkService long-path versus DOS-8.3 path-identity family; that separate issue remains deferred by current product priority.

## 2. Generic anti-replay boundary

The generic side-effect chain was traced through the real final Body:

```text
WorkingState(stage=native_action)
-> resident action step
-> SideEffectAwareBody.act(...)
-> committed started attempt
-> outside-world dispatch
-> durable BodyActionResult or uncertainty
-> verification / recovery
```

The guarded generic classes remain deliberately narrow:

```text
command / terminal / shell
write_text / write_file with append=true
```

Before dispatch, `SideEffectAwareBody` commits a `started` attempt in the resident SQLite database. The ledger stores bounded metadata only: attempt/event ids, action kind, SHA-256 action signature, status/timestamps, and returned Body action id/success bit. Raw commands, appended text, environment values, and raw argument payloads are not copied into this ledger.

If the same event/action signature is encountered with an outstanding `started` attempt, replay is refused with explicit uncertainty evidence. A normal exception after the durable boundary also remains uncertain rather than being treated as proof that no side effect occurred.

Pointer click and focused keyboard text keep their richer dedicated anti-replay lifecycles and were not replaced. Exact replacement text writes (`append=false`) remain outside this guard.

The active Body still satisfies the `KeyboardTextBody` type contract; real interactive CI previously caught and forced correction of an initial composition wrapper design.

## 3. First-class side-effect recovery from current reality

Implementation:

```text
1bcbf410a401755d6037423ea677cb3db1c6217a
feat: recover uncertain append effects from reality
```

The final active resident now treats generic `side_effect_uncertain` evidence as a durable recovery state rather than ordinary failure evidence:

```text
stage      = side_effect_recovery
blocked_by = outside_world_effect_uncertain
```

Uncertainty no longer automatically creates:

- negative native-outcome learning;
- `local_failure`;
- failed-action learning;
- a transition to ordinary `native_investigation`.

This matters because an interrupted action whose external effect is unknown is not evidence that the attempted action failed.

### Append with a trustworthy exact postcondition

ZN already derives an append `text_equals` goal only when it has a full, untruncated current file preview. The active procedural verification contract binds that goal to the same target and marks the action variant as `append`.

Recovery therefore performs a read-only `read_text` before any retry.

If current reality already equals the exact requested final text:

```text
started attempt -> verified_effect
complete without replay
no causal success learning from the uncertain dispatch
```

If current reality exactly equals the resident-derived pre-dispatch baseline:

```text
started attempt -> verified_absent
retry authorization is restored
one fresh append may dispatch
normal independent postcondition verification follows
```

The safe-baseline rule is intentionally narrow: the intent must be `resident_choice`, the verification contract must be the exact same `text_equals` append goal, and the expected final text must end with the exact appended suffix.

If the read fails, is truncated, or observes divergent text, ZN keeps replay blocked and moves to a decision-required recovery state instead of guessing.

### Generic command uncertainty

Generic commands normally lack a trustworthy read-only postcondition. They therefore remain blocked:

```text
decision = user_decision_required
replay_blocked = true
```

The outstanding `started` attempt remains unresolved. ZN does not run another command merely to ask whether the first command ran.

## 4. Exact focused Windows verification

Current implementation evidence:

```text
ZN Work Recovery E2E run 33009460955
head   1bcbf410a401755d6037423ea677cb3db1c6217a
runner zn-ci-01 / Windows X64
result success
Ran 18 tests in 8.963s
OK
```

The suite explicitly passed:

```text
test_recovery_resolution_closes_only_matching_started_attempt
test_interrupted_append_completes_from_verified_effect_without_replay_or_failure_learning
test_interrupted_derived_append_retries_only_after_exact_baseline_is_reobserved
test_interrupted_generic_command_enters_blocked_recovery_without_replay
```

This proves:

- effect already present -> zero append replay and completion from fresh observation;
- exact old baseline present -> read first, then exactly one fresh append, then normal verification;
- generic command uncertainty -> zero command dispatch and durable blocked recovery;
- uncertainty is not converted into ordinary failure learning;
- all earlier Work reconstruction, atomic terminal, and anti-replay tests remain green.

## 5. Ordinary CI truth

Current implementation-head ordinary CI is:

```text
ZN CI run 33009460950
head 1bcbf410a401755d6037423ea677cb3db1c6217a
Electron / TypeScript / Windows    success
ZN Source Boundary / Windows       success
ZN Kernel / Python / Windows       in progress at latest inspection
```

Do not report ordinary CI green until Kernel actually finishes successfully. If Kernel again fails only on the known NetworkService long-path/DOS-8.3 identity defect, record that exact fact and keep the issue deferred unless it materially blocks current product work.

The earlier partial path-identity attempt was reverted normally in `db647cb49c3de014aa82bc28ec87c1c4e5b02c15`; no half-fix remains.

## 6. Windows runner truth

Headless CI remains on `[self-hosted, Windows, X64, zn-ci]`. Interactive proof remains on `[self-hosted, Windows, X64, zn-interactive]`.

The visible foreground interactive runner design remains the accepted product/operations decision. Do not restore hidden launch, auto-logon, credential expansion, or Session-0 interactive claims.

Previously verified exact runtime regressions remain:

```text
ZN Windows Interactive Desktop E2E run 33006103742   success, 4/4
ZN Managed Browser E2E             run 33006103702   success, 71 contract + 4 real Chromium
```

Managed-browser native `SELECT_OPTION` remains verified. Broader browser PRESS, generic click, richer editing, multi-select, page lifecycle, User Browser Bridge control, M8 continuity, and SM1+ remain open.

## 7. Remaining Work recovery gap

The next control-plane gap is not replay safety itself; it is durable, explicit recovery control for unverifiable uncertainty.

Current `work_progress` exposes generic `stage` and `next_action`, but no dedicated sanitized recovery object. Clients should not infer resident recovery truth from an error string.

Next order:

```text
1. expose a bounded resident-owned recovery object through Work progress/RPC
2. include only safe fields such as status/kind/attempt id/replay flag/verification kind/decision/reason
3. never expose raw command text, appended text, environment values, or full action signatures
4. add explicit cancel/recovery decision semantics for unverifiable side effects
5. preserve no-learning-from-uncertainty
6. prove reconstruction/control behavior on focused Windows CI
```

Work durability remains **PARTIAL** until that explicit control path exists.

M8 Windows continuity remains PARTIAL. SM0 remains verified foundation; SM1+ remains open. High-risk identity, long-term memory, credential/permission, updater/signing, and destructive self-maintenance changes continue to require human approval.
