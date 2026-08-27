# ZN Agent Handoff

Updated: 2026-08-27

## Current goal

Continue the bounded broader-Work durability audit after verifying eighteen concrete crash/restart windows, the direct synchronous `side_effect_recovery` caller lifecycle, and the shared low-level `resident_side_effect_attempts` persistence/pruning invariant.

The newest completed slice removes duplicated Body/compiled-capability low-level attempt persistence ownership while preserving their intentionally different historical signature encodings. Capacity pruning is now terminal-truth-gated: an active event's `observed`, `verified_effect` or `verified_absent` recovery evidence cannot be deleted merely because its attempt status is no longer `started`.

Broader Work durability remains **PARTIAL**. The next real target is the bounded backward audit of cumulative resident/kernel accounting and learning writes against their durable semantic completion/failure facts.

Founding boundary remains:

> **ZN uses models. Models do not own ZN.**

## Branch / repository truth

- repository: `9529360-cpu/znagent`
- development branch: `dev/zn-agent`
- canonical source/release branch: `main`
- canonical `main`: `8234a835dea604783cea0bd9d28a40de654ec03d`
- exact implementation/test/CI proof head: `a70d15600c7bd8b361a0120e303b881b82461f3f`
- branch HEAD immediately before this HANDOFF/status synchronization commit: `a70d15600c7bd8b361a0120e303b881b82461f3f`
- PR #6 remains the development PR from `dev/zn-agent` to `main`
- `main` was not modified
- no force push or history rewrite was requested or performed

A HANDOFF commit cannot contain its own resulting SHA. Re-read `dev/zn-agent` after this file is committed and use that exact head externally.

## Completed in this stage

### Shared low-level attempt persistence owner

The audited active callers are:

```text
SideEffectAwareBody
-> side_effect_attempts
-> resident_side_effect_attempts

compiled capability execution
-> ResidentSideEffectJournal
-> side_effect_attempts
-> resident_side_effect_attempts

KernelStore.cancel_uncertain_event
-> same resident_side_effect_attempts transaction
-> shared schema delete guard
-> event + EventOutcome + idle WorkingState atomically
```

`runtime/python/zn_agent/core/side_effect_attempts.py` now owns the shared table/index schema, SQLite connection policy, plain attempt start/read/observe/resolve queries, replay-blocking/event-attempt lookup and terminal-safe capacity pruning.

`SideEffectAwareBody` delegates those low-level operations to the shared owner while keeping its existing Body contract: strict attempt lifecycle, result action/success metadata, started-or-observed recovery resolution and optional observed replay blocking.

`ResidentSideEffectJournal` delegates to the same owner while preserving compiled capability semantics: idempotent `start_with_checkpoint` / `observe_with_checkpoint`, atomic attempt + WorkingState persistence, and started-only default replay blocking.

### Historical signature identity preserved

The two durable identities intentionally remain different and are regression-locked:

```text
Body:
sha256(json({"kind": kind, "args": args}))

compiled capability:
sha256(json({"kind": normalized_kind, "identity": identity}))
```

No hash normalization, persisted-row rewrite or upgrade migration was introduced.

### Terminal-truth-gated pruning

The audit found a real durability gap in the old common cleanup pattern:

```text
DELETE ... WHERE status!='started' ... OFFSET 4096
```

That condition can select `observed`, `verified_effect` or `verified_absent` rows that still belong to a nonterminal event and are therefore active recovery truth.

The enforced invariant is now:

> Capacity pruning may delete an attempt only when the owning event is terminal (`completed` or `failed`) **and** the event already has a durable `event_outcomes` row. Any attempt for a nonterminal event is retained regardless of status.

The shared prune query enforces the rule. The shared schema also installs a delete guard so an older/direct generic DELETE fails safe for nonterminal attempts.

`KernelStore.cancel_uncertain_event()` intentionally remains inside its existing single SQLite transaction rather than opening a helper connection. Cancellation must atomically transition the attempt to `work_abandoned`, publish cancelled event + `EventOutcome`, and clear WorkingState. The shared schema guard prevents its legacy generic cleanup SQL from deleting unrelated active recovery facts before terminal truth exists; after terminal truth is durable in the same transaction, bounded historical cleanup is permitted.

### Compatibility and recovery proof

`tests/zn_agent/core/test_side_effect_attempt_persistence.py` proves:

- exact historical Body and capability hash constants remain stable and distinct;
- Body-started attempts are readable through the compiled-capability journal owner, and Body resolution is visible there;
- terminal historical attempts can be pruned;
- active Body `verified_effect` and compiled-capability `observed` rows survive zero-capacity pruning pressure;
- a raw generic DELETE cannot remove those active rows;
- the active event still has no EventOutcome, proving retention depends on terminal truth rather than attempt status.

Existing Work side-effect recovery/resolution/observed/cancellation and compiled-capability recovery tests stayed in the focused suite and passed unchanged on the same code head.

This persistence/pruning proof is an additional invariant; the concrete crash/restart-window count remains eighteen.

## Key commits

```text
836acf3b778cf0bbb7b5ae6eeb247f6771ae424e  refactor: centralize side effect attempt persistence
5c42cdd7a403b1a14ee915934d9e3d4967e34a8b  refactor: route body side effects through shared persistence
a093a35226d05bff866063b2f483a01f869bb84f  refactor: share compiled side effect persistence
a681bfbf08efe720251ef037f0bd45d5f1b797aa  test: protect active side effect recovery facts
a70d15600c7bd8b361a0120e303b881b82461f3f  ci: cover shared side effect attempt owner
```

Related implementation files:

```text
runtime/python/zn_agent/core/side_effect_attempts.py
runtime/python/zn_agent/core/side_effect_body.py
runtime/python/zn_agent/core/side_effect_journal.py
runtime/python/zn_agent/core/store.py
tests/zn_agent/core/test_side_effect_attempt_persistence.py
.github/workflows/zn-work-recovery-e2e.yml
```

`store.py` was audited but not changed in this slice; its cancellation transaction remains the active caller described above and is protected by the shared database invariant.

## Real test / CI truth

Exact implementation/test/CI proof for `a70d15600c7bd8b361a0120e303b881b82461f3f`:

```text
ZN Work Recovery E2E run 33117334326                 success
Windows resident Work restart recovery                success
Compile Work recovery path                            success
Verify durable Work progress and restart recovery     success
  shared attempt-owner/pruning regressions             success

ZN CI run 33117334321                                 success
ZN Kernel / Python / Windows                          success
  Boot isolated ZN distribution without a model       success
  Compile resident core                               success
  Run ZN core tests against working tree              success
ZN Source Boundary / Windows                          success
Electron / TypeScript / Windows                       success
Publish Windows CI statuses                           success
```

No local repository test run is claimed for this stage. Repository self-hosted Windows CI is the verification authority.

## Current risks / incomplete work

- broader Work durability remains partial beyond eighteen verified crash/restart windows plus the verified synchronous caller and shared-attempt persistence boundaries;
- the database delete guard is intentionally conservative: attempts without terminal event + EventOutcome truth cannot be capacity-deleted, even if an older caller issues generic cleanup SQL;
- Body and compiled capability historical signature identities are intentionally different and must remain so unless a separately reviewed migration proves upgrade compatibility;
- continue the bounded backward audit for cumulative accounting/learning writes that may precede durable semantic facts;
- no deliberate outcome-trace rewrite/compactor exists; destructive long-term-memory migration remains a separate approval boundary;
- explanatory-comment cleanup in `intentional_resident.py` remains non-behavioral debt;
- Windows M8 continuity, browser PRESS/broader interaction lifecycle, authenticated User Browser Bridge control, and SM1+ remain incomplete;
- identity, long-term memory, credentials/permissions, updater/signing, rollback and destructive self-maintenance remain high-risk approval boundaries.

## Task queue

### P1 - shared side-effect-attempt persistence owner

Status: **COMPLETE / CI VERIFIED**

Completed contract:

1. traced Body, compiled capability and cancellation interaction with `resident_side_effect_attempts`;
2. separated genuinely shared low-level persistence from intentionally different signature/atomic-checkpoint semantics;
3. consolidated Body and compiled-capability persistence plumbing behind one owner;
4. made capacity deletion terminal-truth-gated at helper + schema level;
5. added compatibility/pruning proof and passed focused recovery + full ZN CI.

### P2 - continued bounded backward durability audit

Status: **OPEN / NEXT**

Enumerate active cumulative resident/kernel accounting and learning mutations, trace each backward to its durable semantic completion/failure fact, and close any path where cumulative state can commit before restart-safe semantic truth.

### P3 - browser / M8 / SM1+

Status: **OPEN**

PRESS, broader interaction lifecycle, authenticated User Browser Bridge control, Windows M8 continuity and SM1+ remain incomplete. Preserve human approval for high-risk identity, memory, credentials, updater/signing, rollback and destructive self-maintenance changes.

## Next real target

Re-read the current branch/PR/CI and then continue P2 from active accounting/learning callers. Keep broader Work durability marked PARTIAL and keep `main` untouched during ordinary development.
