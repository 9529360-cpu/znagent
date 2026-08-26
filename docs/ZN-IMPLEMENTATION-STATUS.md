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
9502b96d94bc1a08d5f0b68a8c2359c51f11ea5a
fix: preserve typed body ownership under side-effect guard
```

Status: **DURABLE WORK RESTART/RESUME, ATOMIC TERMINALIZATION, AND A FIRST FAIL-CLOSED GENERIC SIDE-EFFECT ANTI-REPLAY BOUNDARY ARE VERIFIED. WORK DURABILITY IS STILL PARTIAL: UNCERTAIN EFFECTS CAN NOW BLOCK BLIND REPLAY, BUT FRESH EFFECT REVERIFICATION AND EXPLICIT CANCEL/USER-DECISION SEMANTICS ARE NOT YET COMPLETE.**

## 1. Durable Work foundations already verified

The real Work call chain remains:

```text
ResidentRpcServer work_start / work_progress
-> ResidentWorkLedger
-> ZNResidentRuntime event lifecycle
-> KernelStore events + singleton working_state
-> resident life stages
-> EventOutcome
-> ResidentWorkLedger finalization
```

ZN's SQLite `WorkingState` is the resident-owned checkpoint. Interrupted `PROCESSING` work returns to `PENDING` on resident reconstruction while the exact stage and next action survive for the same event. No duplicate checkpoint subsystem exists.

Verified restart checkpoint:

```text
2bce63a23252b7166244d0afd9dcac63b6b4fc26
ZN Work Recovery E2E run 33002232752   success
runner                                   zn-ci-03 / Windows X64
6/6 Work progress + restart tests        passed
```

Atomic terminal completion remains verified at:

```text
f02582557a39f32273fb806929a6f64906fea547
ZN Work Recovery E2E run 33004561095   success
runner                                   zn-ci-02 / Windows X64
8/8 Work progress/recovery tests         passed
```

`KernelStore.complete_event()` publishes terminal event status, the exact durable `EventOutcome`, and `WorkingState(stage="idle")` in one SQLite transaction. A forced `event_outcomes` INSERT abort test proves all three records roll back together.

## 2. Generic non-replayable side-effect boundary

The side-effect call chain was traced through the real Body owner:

```text
WorkingState(stage=native_action)
-> EmbodiedResidentRuntime / procedural action path
-> final resident Body.act(...)
-> NativeBody dispatch
-> outside-world mutation
-> BodyActionResult persistence
-> verification / investigation
```

The generic failure window was real: `NativeBody.act()` dispatches first and records its result afterward. If ZN stopped after a generic command or append-style write reached the outside world but before its result was durably observed, restart could previously return to `native_action` and issue the same mutation again.

Existing richer input paths were already safer and were deliberately left alone:

- pointer click has its own persisted execution-start marker and refuses blind replay;
- focused keyboard text has its own persisted execution-start marker and refuses blind replay;
- targeted test execution has its own dedicated execution record.

The new `SideEffectAwareBody` adds the same fail-closed principle only to the previously uncovered generic classes:

```text
command / terminal / shell
write_text or write_file with append=true
```

Before dispatch it commits a `started` side-effect attempt in the same resident SQLite database. The recovery ledger stores only bounded metadata:

```text
attempt id
event id
action kind
SHA-256 action signature
started / observed status
timestamps
returned Body action id / success bit
```

Raw command text, appended text, environment values and raw action arguments are not copied into the recovery ledger.

If the resident later sees the same event/action signature with an outstanding `started` attempt, it returns explicit uncertainty evidence and refuses to dispatch again:

```text
side_effect_uncertain = true
replay_blocked = true
```

A normal Body exception after the pre-dispatch boundary also remains uncertain; ZN does not infer that no side effect occurred merely because dispatch raised.

A returned Body result closes the attempt as `observed`. This means `success=false` is still an observed dispatch result, not proof that the action was safe to replay.

Exact replacement-style text writes (`append=false`) are intentionally outside this new guard because they already have convergent/exact-effect verification semantics. This slice does not broaden behavior.

## 3. Typed Body ownership regression found and fixed by real interactive CI

Initial implementation:

```text
be594b0e2a9e827fa4d5b7aa849126edbd2afa10
feat: refuse blind replay of generic side effects
```

The first design wrapped the final Body by composition. Real interactive Windows E2E correctly rejected that because the active resident Body was no longer a `KeyboardTextBody`, breaking the typed owner contract. The test was not weakened.

The fix:

```text
9502b96d94bc1a08d5f0b68a8c2359c51f11ea5a
fix: preserve typed body ownership under side-effect guard
```

`SideEffectAwareBody` is now a real `KeyboardTextBody` subtype. The active resident therefore preserves the existing keyboard Body type and dispatch semantics while adding only the generic pre-dispatch uncertainty guard.

A separate test-only resource cleanup fix remains:

```text
5467951d4a71b21b594ed0d0b2b35c70a940bedf
test: close side-effect recovery database handle
```

It fixed a Windows temporary-directory cleanup error caused by an unclosed SQLite test handle; it did not change product behavior.

## 4. Exact implementation verification

For implementation head `9502b96d94bc1a08d5f0b68a8c2359c51f11ea5a`:

```text
ZN Work Recovery E2E             run 33006103725   success
runner                                               zn-ci-02 / Windows X64
Work progress/recovery suite                         12 passed

ZN Windows Interactive Desktop E2E run 33006103742   success
runner                                               zn-interactive
real interactive tests                              4 passed

ZN Managed Browser E2E             run 33006103702   success
runner                                               zn-ci-03 / Windows X64
browser contract tests                              71 passed
real Chromium E2E                                   4 passed
```

The focused Work suite directly proves:

```text
active product resident remains a KeyboardTextBody subtype
generic command + append persist started before dispatch
resident/store reopen sees the outstanding attempt
same event/action is not dispatched a second time
observed dispatch closes the attempt
exact text replacement is not broadened into this guard
restart/reconstruction + atomic terminal tests remain green
```

The real interactive suite passed pointer click, Unicode focused text entry, UIA text capability, and the real installed Edge/Chrome User Browser Bridge discovery/read-state test. This specifically confirms the typed Body regression was repaired without weakening real desktop behavior.

The managed-browser regression remained green with 71 contract tests and 4 real Chromium E2Es, including the verified native `SELECT_OPTION` cases.

## 5. Windows runner and ordinary CI truth

Headless CI remains on `[self-hosted, Windows, X64, zn-ci]`. Interactive proof remains on `[self-hosted, Windows, X64, zn-interactive]`.

The interactive runner continues to execute visibly in the real user session; the latest exact implementation run above was accepted by `zn-interactive` and completed successfully.

Ordinary `ZN CI` for head `9502b96d...` is run `33006103746`. At the latest inspection its jobs were still in progress. Do not report ordinary CI green until all jobs, especially Kernel, actually complete successfully.

A separate real NetworkService long-path vs DOS-8.3 path-identity defect remains deferred by current product priority. Its partial attempted fix was reverted normally in `db647cb49c3de014aa82bc28ec87c1c4e5b02c15`; no half-fix remains. Do not automatically reopen it.

## 6. Remaining Work recovery gap

The current guard answers only one question safely: **should an uncertain generic side effect be blindly replayed?** The answer is now no.

It does not yet decide what should happen next. The next product slice must make uncertainty first-class in resident Work recovery:

```text
safe independent postcondition available
-> observe current reality first
-> if effect is already proven, continue without replay
-> if effect is proven absent and retry is safe, allow a fresh attempt

no trustworthy postcondition / non-idempotent unknown effect
-> keep replay blocked
-> expose explicit recovery/cancel/user-decision state
-> do not learn an ordinary action failure from uncertainty alone
```

Likely first concrete target is append-style file/text action because ZN can sometimes verify a bounded exact postcondition without repeating the append. Generic arbitrary commands will often remain unverifiable and therefore require an explicit decision rather than automatic replay.

Broader open foundations remain isolated parallel Work/Investigation, ZN-owned connector/MCP permission/evidence substrate, scheduled/event-driven work, unified permission/audit controls, M8 install/update/rollback/signing continuity, authenticated User Browser Bridge control, and SM1+ self-maintenance.

M8 Windows continuity remains PARTIAL. SM0 remains verified foundation; SM1+ remains open. High-risk identity, long-term memory, credential/permission, updater/signing and destructive self-maintenance changes continue to require human approval.

## 7. Next implementation order

```text
1. preserve restart recovery + atomic terminalization + generic anti-replay guard
2. make side-effect uncertainty explicit in Work progress/state
3. add fresh effect reverification before any retry when a trustworthy postcondition exists
4. add explicit cancel/user-decision handling for unverifiable uncertainty
5. prove reconstruction/reverification on focused Windows CI
6. keep browser PRESS and broader lifecycle as bounded follow-on work
```
