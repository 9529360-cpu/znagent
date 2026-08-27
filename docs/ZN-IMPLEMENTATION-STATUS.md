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

## Current checkpoint - 2026-08-27

`main` remains unchanged at `8234a835dea604783cea0bd9d28a40de654ec03d`. Ordinary development remains on `dev/zn-agent`.

Relevant checkpoints:

```text
5c679ea742a2c83578c85c215cf582ce8c22a8cf  recovery-only Work cancellation UI
86895eda3397cf71d7f24b2d7d84d0c73c5e7220  preserve durable outcome across Life observation failure
83ca2179bf1f836469687dac61310b016f482ca8  sanitized completion-observation health primitive
a2428564b30556f3a33ea1556b47c0829f1c99e3  richer resident completion-observation ownership
43142de23196b4e5fb3912bc177a8f25b95189e3  focused richer-resident observation coverage
ae5996eb005d16262a4a44e93a79236d8d0f5703  atomic nervous EventOutcome perception substrate
10ad29e32555f17493e58bea108cfdd54c86bc04  activation cutoff for safe nervous repair
4e616d8a323e99adec11a0815b6a602ac5dbcd25  Intentional resident outcome reconciliation
c72f9348f0a0485483f5cc35554b0bc2c3060f00  bind outcome transaction to active nervous substrate
75c7c303a4ed2fa8fbec8e5dfee2066d03baf949  bind product outcome plasticity to final nervous owner
90a24a4bff07735a95d7a73783518f2cdd4c4044  final-owner crash/restart regression
ba06e08561cc73bcd8afc61b444b860c45bfb376  focused nervous outcome proof checkpoint
c54bb8c37385d98fc9688b6e89839d7a5cba6df6  single-owner completion journal cleanup and regression
0c011a2473c581e6517a882343208d6efe47cac1  canonical Windows path identity at action/Git/terminal/Work owners
e3fc20b7b4271e46868f408c258cab58ba014abb  carry canonical identity through evidence and procedural learning
9207d3de534080ea62a9847a848cde3b0ba5b6b5  retain receipted nervous outcome traces across pruning
```

Status: **RECOVERY-ONLY CANCELLATION REMAINS REACHABLE END TO END. `EventOutcome` REMAINS TERMINAL TRUTH. LIFE OBSERVATION REPAIR REMAINS SECONDARY AND NON-REPLAYING. DURABLE EVENT-OUTCOME NERVOUS PLASTICITY NOW HAS AN EVENT-IDENTITY-SAFE ATOMIC BOUNDARY FOR TRACE, LINKS, AFFECT, AND RECEIPT, INCLUDING CRASH/RESTART REPAIR WITHOUT DUPLICATE REINFORCEMENT. GENERIC NERVOUS `perceive()` REMAINS INTENTIONALLY PLASTIC AND IS NOT AN EXACTLY-ONCE API. BROADER WORK DURABILITY REMAINS PARTIAL.**

## 1. Durable cancellation and terminal truth

The established uncertain-effect cancellation authority remains `KernelStore.cancel_uncertain_event()` for the narrow replay-blocked recovery state. Cancellation is a lifecycle/control result, not failure learning and not evidence about whether the outside-world effect happened.

The post-completion authority remains:

```text
action result
-> KernelStore.complete_event(...)
-> durable terminal event + EventOutcome
-> secondary resident observation
```

`EventOutcome` is terminal truth. `CompletionObservationJournal` receipts Life observation after that boundary. A failed Life observation remains pending and can be repaired from the durable outcome after restart without rerunning the completed event/action.

Life observation remains an at-least-once repair path; no global exactly-once claim is made.

## 2. Completion-observation ownership and status

There are two legitimate resident birth paths:

```text
ZNResidentRuntime
-> ZNLifeCore.wake()
-> CompletionObservationJournal

EmbodiedResidentRuntime and descendants
-> EmbodiedLifeCore.wake()
-> CompletionObservationJournal
```

The richer path intentionally does not call `ZNResidentRuntime.__init__`, because temporarily constructing the legacy LifeCore would be wrong for persisted richer state. `EmbodiedResidentRuntime` owns completion observation after the richer Life wake. Provider bridge remains assembly-only.

`CompletionObservationJournal.health()` exposes only:

```text
healthy
pending_count
waiting_count
running_count
stages
```

`FocusedModernTextResidentRuntime.status()` projects that sanitized object as `completion_observations`; the existing RPC status path passes it through without raw repair errors, event IDs, paths, or `last_error`.

`FocusedModernTextResidentRuntime` no longer reconstructs or re-repairs the journal. The Embodied birth root is the single richer-resident lifecycle owner, while the final product layer retains the sanitized `status()["completion_observations"]` projection. A product-level regression proves construction invokes `repair_life()` once and preserves status visibility.

## 3. Event-identity-safe nervous outcome perception

`NativeWill` already reconciles durable outcomes during resident birth through `will.reconcile_outcomes()` and remains the Will authority.

Generic `PersistentNervousSystem.perceive()` remains intentionally plastic. Repeating a matching perception is new lived evidence and legitimately changes repetitions, trace strength, links, and affect. It is therefore not used as a blind restart-repair primitive.

Durable terminal `EventOutcome` perception now uses a dedicated resident-owned transaction. For one event identity, a single SQLite transaction atomically covers:

```text
event_id dedupe / receipt
trace insert or reinforcement
co-active neural-link reinforcement
affect / nervous_state update
```

The active nervous object's in-memory affect is updated only after the transaction commits. A fault before commit rolls back trace, links, affect, and receipt together.

The dedupe key is `event_id`, not trace fingerprint. Therefore:

- retrying the same durable event is a complete plasticity no-op after its receipt commits;
- two distinct events with the same semantic outcome still count as two lived outcomes and may reinforce the same trace;
- a nervous failure after terminal event completion cannot reclassify the completed event or trigger action replay;
- restart reconciliation retries only missing secondary perception.

The durable support tables are:

```text
neural_event_outcomes(event_id PRIMARY KEY, trace_id, perceived_at)
neural_event_outcome_state(id=1, repair_from)
```

`repair_from` records feature activation. Restart repair only considers terminal outcomes created after that cutoff, because historical pre-feature outcomes may already have influenced the old nervous path without receipts. ZN does not guess and double-reinforce unknowable legacy history.

The final product later replaces the lower nervous implementation with `IntegratedTransferNervousSystem`. The outcome operation therefore accepts the active `PersistentNervousSystem` instance and mutates that actual final owner instead of adding a provider/product compatibility shim or a second neural authority.

This is an event-identity-safe guarantee for the durable terminal EventOutcome path only. It is not a claim that all generic nervous perceptions are exactly once.

The lifecycle trace found that pruning was already active, not merely future: resident heartbeat calls `PersistentNervousSystem.consolidate()`, which can call `_delete_trace()` for weak isolated non-schema traces. Before `9207d3de...`, that deletion could remove an `outcome` trace while leaving its `neural_event_outcomes` receipt behind. Restart repair then saw the event receipt and permanently skipped repair, while a direct retry dereferenced a missing trace.

`ensure_event_outcome_schema()` now installs a database-level retention guard on receipted traces. It applies to the real final `IntegratedTransferNervousSystem`, not only the lower event-outcome nervous class. `_delete_trace()` reports the actual SQLite row result, preserves links when deletion is refused, and consolidation only counts a real deletion as pruning. Ordinary weak unreferenced traces remain prunable.

The durable policy is now explicit:

- an event receipt is the event-ID idempotence authority;
- its referenced trace must remain dereferenceable while the receipt points to it;
- automatic pruning fails closed rather than creating a dangling receipt;
- a future deliberate outcome-trace compactor may replace a representation only by atomically retargeting every affected receipt to an existing canonical trace before deleting the old trace;
- no such outcome-trace rewrite or destructive migration was introduced in this stage.

## 4. Focused Windows proof

Current focused proof:

```text
ZN Work Recovery E2E run 33049868415
head 9207d3de534080ea62a9847a848cde3b0ba5b6b5
Windows resident Work restart recovery             success
Compile Work recovery path                         success
Verify durable Work progress and restart recovery  success
46 tests                                             OK
```

The focused suite includes the established Work progress/restart/side-effect/cancellation and completion-observation modules plus:

```text
test_event_outcome_nervous
test_event_outcome_nervous_recovery
```

The new proof covers:

- same event ID does not reinforce trace/link/affect twice;
- distinct same-result events still reinforce as separate lived evidence;
- forced failure before nervous commit rolls back the entire plasticity unit;
- receipt survives restart and suppresses duplicate reinforcement;
- the real final product nervous owner receives the immediate completion receipt;
- forced nervous failure after terminal completion leaves the durable EventOutcome intact;
- restart repairs only perception and a second restart remains a no-op.
- consolidation cannot prune a receipted outcome trace or falsely count it as pruned;
- the final product nervous owner retains the trace, and restart retry remains a no-op.

## 5. Ordinary CI truth

The last completed ordinary code checkpoint before this nervous slice remains:

```text
ZN CI run 33020344789
head 43142de23196b4e5fb3912bc177a8f25b95189e3
Electron / TypeScript / Windows    success
ZN Source Boundary / Windows       success
ZN Kernel / Python / Windows       failure
Kernel                             585 tests / 16 errors / 5 skipped
```

Those remaining 16 errors were the known Windows NetworkService DOS-8.3 versus long-path identity family around repository targeted-test/text-delta verification and terminal/Work artifact cwd identity, with cleanup `PermissionError` fallout. The prior partial path fix remains normally reverted in `db647cb49c3de014aa82bc28ec87c1c4e5b02c15`.

An ordinary run at old documentation head `4559fb71...` also encountered a runner-local uv CPython standard-library corruption before Kernel tests began; that was not classified as a repository regression.

The first full-boundary implementation checkpoint exposed one remaining split:

```text
ZN CI run 33046424920
head 0c011a2473c581e6517a882343208d6efe47cac1
Electron / TypeScript / Windows    success
ZN Source Boundary / Windows       success
ZN Kernel / Python / Windows       failure
Kernel                             594 tests / 4 failures / 6 errors / 5 skipped
```

The original 16 repository/terminal/Work errors were gone and the new short-path targeted-test regression passed. The remaining failures showed that Investigation facts and procedural fingerprints still retained the incoming DOS spelling while actions and verification carried the canonical long spelling. That evidence/action identity split was fixed at its owners rather than hidden in assertions.

The Windows path code-checkpoint ordinary evidence was genuinely green:

```text
ZN CI run 33047823223
head e3fc20b7b4271e46868f408c258cab58ba014abb
Electron / TypeScript / Windows    success
ZN Source Boundary / Windows       success
ZN Kernel / Python / Windows       success
Kernel                             594 tests / 5 skipped / OK
```

Exact-head `ZN Windows Interactive Desktop E2E` run `33047823208` also succeeded. `ZN Work Recovery E2E` run `33046424926` succeeded at the first path code checkpoint; the second evidence-only commit did not match that workflow's path trigger.

Current exact-head ordinary evidence is also genuinely green:

```text
ZN CI run 33049868413
head 9207d3de534080ea62a9847a848cde3b0ba5b6b5
Electron / TypeScript / Windows    success
ZN Source Boundary / Windows       success
ZN Kernel / Python / Windows       success
Kernel                             596 tests / 5 skipped / OK
```

Exact-head `ZN Work Recovery E2E` run `33049868415` succeeded with 46 tests. The only ordinary-run annotation is the existing Node 20 action-runtime deprecation notice; it did not fail a job.

The final Windows identity chain is:

```text
event payload / context path
-> NativeInvestigator canonical path facts and previews
-> native action path/workdir matching
-> NativeBody and Terminal host path identity
-> Git root senses and ResidentWorkLedger workspace identity
-> verification and privacy-safe procedural fingerprints
-> active resident callers and tests
```

DOS 8.3 expansion is lexical: it expands the longest existing Windows prefix and reattaches a missing suffix without following symlinks or reparse points. Security containment still performs strict real-path resolution and rejects candidates outside the resolved root.

## 6. What remains partial

Open work includes:

- no deliberate outcome-trace rewrite/compactor exists; any future implementation must atomically retarget receipts and requires separate review before a destructive long-term-memory migration;
- restore several explanatory comments accidentally lost during the whole-file Intentional owner edit; no behavioral deletion was found in diff review;
- broader Work durability outside the proven cancellation/Life-observation/nervous-outcome slices;
- Windows continuity M8;
- browser PRESS, broader click/editing/multi-select/page lifecycle;
- authenticated User Browser Bridge control;
- SM1+ self-maintenance.

High-risk identity, long-term memory, credential/permission, updater/signing, rollback, and destructive self-maintenance changes still require human approval.

## 7. Next real target

Next: **trace the first still-unproven broader Work durability crash window.**

Follow the active product chain from Work RPC ingress through event claim, stage/checkpoint ownership, outside-world side-effect admission, terminal `EventOutcome`, restart reconstruction, progress projection, and active callers. Select the first real ambiguity not already covered by cancellation, Life observation, nervous outcome perception, or the existing non-replayable action guard, then close it without replaying uncertain effects.

Do not weaken cancellation semantics, replay completed actions, or move development to `main`.
