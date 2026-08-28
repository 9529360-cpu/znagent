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

## Current checkpoint - 2026-08-28

`main` remains unchanged at:

```text
8234a835dea604783cea0bd9d28a40de654ec03d  docs: close M10 handoff state
```

Ordinary development remains on `dev/zn-agent`.

Newest verified P5 proof head before this documentation synchronization:

```text
97803f8d0616c1f2b30a61af5acc686f1256cd11  fix: checkpoint overwrite pre-dispatch identity
```

Status: **BROADER WORK DURABILITY REMAINS PARTIAL. TWENTY-ONE CONCRETE CRASH/RESTART WINDOWS ARE NOW CLOSED AND VERIFIED. WINDOW #20 PREVENTS BLIND REPLAY AFTER AN OVERWRITE MAY ALREADY HAVE REACHED THE FILESYSTEM. WINDOW #21 PREVENTS A STALE PRE-DISPATCH OVERWRITE FROM SILENTLY CONTINUING AFTER RESTART WHEN THE TARGET CHANGED WHILE ZN WAS DOWN. GENERAL PER-TASK RESTORE/ROLLBACK REMAINS OPEN/PARTIAL.**

The resident-intelligence direction remains explicit: mature general computer-use/recovery mechanics should become ZN-owned built-in competence, while post-birth learning concentrates on user/environment/project-specific experience. This architecture direction is broader than current implementation and must not be reported as complete.

## 1. Durable foundations

Established durable boundaries include:

- terminal event + exact `EventOutcome` + idle `WorkingState` publish atomically;
- Life observation is secondary and repairable without replaying a completed action;
- event-identity-safe nervous outcome perception uses receipts;
- Windows canonical path identity is shared across Investigation, Body/Terminal, Git, Work, verification and procedural learning;
- Work cancellation is atomic and bypasses failure learning because cancellation is lifecycle/control truth;
- replay-sensitive Body and compiled-capability effects persist durable attempt ownership before dispatch;
- unresolved outside-world effects remain uncertainty rather than fabricated success/failure or replay permission;
- cumulative Body/accounting evidence is applied after the relevant semantic checkpoint is durable;
- external provider dispatch has durable attempt identity and unknown provider outcomes block replay;
- terminal-safe pruning cannot remove nonterminal recovery truth;
- accepted Work ingress has a short-lived pre-event checkpoint so accepted user work cannot disappear before resident-event persistence;
- active ordinary overwrite writes participate in the resident side-effect ownership/recovery lifecycle without broadening the reusable generic guard contract;
- fresh ordinary overwrite now owns a privacy-bounded pre-dispatch file-identity checkpoint before Body dispatch. If restart sees that checkpoint and no matching side-effect attempt, the resident re-observes current target identity before allowing the inherited fresh lifecycle to continue.

Generic nervous `perceive()` remains intentionally plastic and is not an exactly-once API.

## 2. Twenty-one proven broader Work crash/restart windows

The verified crash/restart windows are:

1. missing Work ingress linkage after durable resident event creation;
2. recovery decision committed before the next `WorkingState` save;
3. append dispatch durably `observed` before checkpoint save;
4. generic guarded side-effect dispatch durably `observed` before checkpoint save;
5. verified append recovery success before terminal `EventOutcome`;
6. common verified Body success resumes from `native_completion` without Body replay;
7. base resident investigation success resumes from `investigation_completion` without native reprobe;
8. verified semantic/focused/UI completion resumes from `native_completion` without resensing or input replay;
9. base resident MEMORY/CAPABILITY success resumes from `resident_completion` without re-recall/re-execution;
10. compiled capability execution persists durable `started`/`observed` ownership, blocks blind replay by default, and uses event-idempotent successful capability accounting;
11. durable observed compiled-capability failure resumes into native investigation without capability replay or duplicate failure evidence, while malformed observed truth fails closed;
12. zero-model terminal budget-blocked failure persists exact `terminal_failure` truth before task accounting and terminal publication;
13. deterministic outer `run_once()` exception publication uses the same terminal-failure ownership while refusing to overwrite durable success or outside-world uncertainty;
14. structured-memory success persists `resident_completion` before event-idempotent task/knowledge accounting;
15. native-investigation success persists `investigation_completion` before event-idempotent ability/knowledge/task accounting;
16. external cognition persists exact `external_completion` before resident metrics, success knowledge, Life/investigation integration and terminal `EventOutcome`, so restart does not replay the model;
17. external kernel attempts persist stable goal/attempt identity, full worker result, deterministic experience/proposal identity and exactly-once route-quality accounting;
18. crash after provider dispatch but before a returned result becomes explicit unknown-provider-outcome uncertainty: provider replay is blocked and no route learning or improvement proposal is invented from the unknown result;
19. an accepted Work user message can survive a hard crash before resident-event persistence: restart reconstructs the exact preallocated **pending** event and `work_runs` linkage without executing the event, duplicating the message, or granting replay authority. The adjacent event-persisted / WorkRun-missing window is also regression-locked;
20. an ordinary exact overwrite can reach the filesystem and then lose the process before Body result / resident checkpoint persistence. A durable `started` side-effect attempt survives. Restart detects the exact replay-sensitive signature, enters overwrite recovery instead of dispatching the write again, and performs only read-only current-world verification. Exact intended content resolves the attempt as `verified_effect` and completes without replay. Any mismatch, truncation or observation failure remains replay-blocked and does not mutate the target. A regression test also proves an external/user edit after the crash is preserved;
21. a fresh overwrite can durably save its resident pre-dispatch file identity and then lose the process **before** `OverwriteAwareBody` starts the durable side-effect attempt. On restart, absence of the exact side-effect attempt proves ZN did not cross its guarded Body dispatch boundary. The resident re-observes the target before continuing. If exact privacy-bounded identity still matches, the inherited fresh lifecycle may continue. If the target drifted while ZN was down, the stale overwrite is blocked, the resident returns to Investigation, no side-effect attempt is created and the external/user content is preserved.

The crash-window count is now twenty-one. Browser lifecycle proofs, synchronous caller control, shared-attempt pruning and Body-accounting invariants remain additional evidence, not artificial crash-window counts.

## 3. Active synchronous recovery boundary

The active caller chain remains:

```text
provider_bridge.build_resident_runtime()
-> RecoveryBoundedResidentRuntime
   -> OverwriteRecoveryResidentRuntime
   -> DurableBodyAccountingResidentRuntime
   -> CapabilityRecoveryResidentRuntime
   -> FocusedModernTextResidentRuntime
   -> embodied/focused/pointer completion owners

normal desktop Work:
ResidentRpcServer.work_start
-> ResidentWorkControl.start
-> RecoveryBoundedWorkLedger.start
-> background resident life loop
-> work_progress / work_cancel

legacy/direct synchronous callers:
resident.submit() / run_once()
-> RecoveryBoundedResidentRuntime synchronous recovery control
```

`ResidentRecoveryRequired` remains caller-control flow, not task failure. Exact read-only recovery may continue; unresolved replay-blocked uncertainty yields for explicit lifecycle decision without killing asynchronous resident life.

## 4. Shared side-effect-attempt owner

Replay-sensitive Body and compiled-capability execution converge on:

```text
runtime/python/zn_agent/core/side_effect_attempts.py
-> resident_side_effect_attempts
```

Body historical signature identity remains SHA-256 over exact JSON:

```text
{"kind": kind, "args": args}
```

Compiled capability identity intentionally remains separate. No persisted-row rewrite/migration was introduced.

`SideEffectAwareBody` deliberately keeps its historical reusable contract narrow: generic command/terminal/shell plus append-style text mutations. Ordinary overwrite behavior is added only in the active product layer through `OverwriteAwareBody`, so older/shared callers do not silently acquire new semantics.

## 5. P1-P4 verified stages

### P1 - shared side-effect-attempt persistence owner

Status: **COMPLETE / CI VERIFIED**

```text
ZN Work Recovery E2E 33117334326  success
ZN CI                33117334321  success
```

### P2 - bounded cumulative accounting/learning durability

Status: **COMPLETE / CI VERIFIED**

Proof head:

```text
f79d4f3c81b1d7c46dcfb55b6fc923acda77b39c
```

```text
ZN Work Recovery E2E 33119871079  success
ZN CI                33119871129  success
```

### P3 - managed-browser frontier reconciliation

Status: **COMPLETE / CI VERIFIED**

`SELECT_OPTION`, CHECK and UNCHECK are **VERIFIED NARROW**. `PRESS` remains OPEN.

```text
ZN Managed Browser E2E 33120809421  success
ZN CI                  33120848980  success
```

### P4 - resident-owned live-page registry

Status: **COMPLETE / CI VERIFIED NARROW**

Proof head:

```text
fffb0f4b84a76cef21a088167c9eb4faceb93afc
```

Implemented resident-owned monotonic `page-N` identities, provider-page discovery, closed-page eviction, stale target/observation cleanup and deterministic default-page promotion. Explicit tab/popup actions, frame identity and persistent browser-session recovery remain open.

```text
ZN Managed Browser E2E 33122620361  success
ZN CI                  33122620398  success
```

## 6. P5 - durable Work checkpoint / restore foundation

Status: **PARTIAL / THREE BOUNDED SLICES CI VERIFIED**

P5 is not generic workspace rollback. It currently contains three bounded recovery improvements.

### 6.1 Accepted Work ingress checkpoint

Proof head:

```text
2c20b8bded96ce07c6ec43263cc77b7bd10a7a82  fix: recover accepted Work ingress before event creation
```

Restart verifies exact thread/message/event identities, reconstructs only a missing **pending** event with zero attempts, repairs WorkRun linkage and removes the short-lived checkpoint after agreement. It grants no execution/replay authority.

Proof:

```text
ZN Work Recovery E2E 33124662199  success
ZN CI                33124662367  success
```

### 6.2 Reality-gated overwrite effect-present recovery

Final proof head:

```text
c4276f8b151d2c45b69368cb414f012bf0644d01  test: exercise nontruncated overwrite conflict
```

Fresh overwrite preserves the inherited mature lifecycle. `OverwriteAwareBody` commits durable side-effect ownership before mutation. After a hard crash with a replay-blocking attempt, restart performs only read-only current-text observation: exact intended state completes without replay; mismatch/truncation/read failure holds uncertainty and preserves the target.

Proof:

```text
ZN Work Recovery E2E 33129111422  success
ZN CI                33129111419  success
```

### 6.3 Privacy-bounded overwrite pre-dispatch identity

Proof head:

```text
97803f8d0616c1f2b30a61af5acc686f1256cd11  fix: checkpoint overwrite pre-dispatch identity
```

New resident-owned module:

```text
runtime/python/zn_agent/core/file_identity.py
```

The identity sensor stores no raw file body. It records canonical path, existence/type and bounded filesystem metadata. Stable regular files up to 8 MiB also receive a complete SHA-256 observed with before/after stat agreement. Large files, symlinks, unsupported types or unstable/unobservable files fail closed for exact identity.

Fresh overwrite semantics are now:

```text
native_action intent durable
-> observe + durably checkpoint overwrite pre-state identity
-> inherited fresh lifecycle remains authoritative
-> OverwriteAwareBody durable side-effect attempt starts
-> actual Body mutation
```

If process death happens after the pre-state checkpoint but before Body dispatch, restart has the following evidence:

```text
pre-state checkpoint exists
+ exact side-effect attempt does not exist
= ZN did not cross its guarded overwrite Body dispatch boundary
```

Restart still does **not** blindly resume. It re-observes current target identity:

```text
exact same pre-state identity
-> inherited fresh lifecycle may continue

target identity drifted / cannot be proved exact
-> stale overwrite blocked
-> native_investigation
-> no Body attempt
-> no mutation
```

This is deliberately different from post-dispatch recovery. Once a durable side-effect attempt exists, matching the old pre-state again does **not** prove `verified_absent`; the write may have happened and later been restored externally. Automatic post-dispatch replay therefore remains forbidden.

Real focused proof on exact head `97803f8d0616c1f2b30a61af5acc686f1256cd11`:

```text
ZN Work Recovery E2E run 33151244307                  success
  Prepare isolated runtime                            success
  Compile Work recovery path                          success
  Verify durable Work progress and restart recovery  success
```

Focused logs include both new hard-crash cases and the prior overwrite-recovery regressions; the suite completed `Ran 95 tests ... OK`.

Real full-tree proof on the same exact head:

```text
ZN CI run 33151244298                                  success
ZN Kernel / Python / Windows                           success
  Boot isolated ZN distribution without a model       success
  Compile resident core                               success
  Run ZN core tests against working tree              success
ZN Source Boundary / Windows                           success
Electron / TypeScript / Windows                        success
Publish Windows CI statuses                            success
```

No local repository test run is claimed for these web-maintainer slices. Repository self-hosted Windows CI is the verification authority.

## 7. Resident intelligence architecture direction

`ZN.md` and `docs/ZN-RESIDENT-INTELLIGENCE.md` distinguish:

```text
built-in resident competence
+ learned resident competence
+ replaceable external cognition
```

The intended product split is:

- before first real use, mature general computer/recovery competence should be engineered into ZN where concrete and verifiable;
- after first real use, learning should concentrate primarily on the user's habits, local environment, recurring workflows, projects, exceptions and personal ways of working;
- provider/model replacement must not erase resident-owned mature competence;
- familiarity may reduce redundant deliberation, never current-state sensing or postcondition verification.

This is an architecture/product contract, not a claim that broad mature computer competence or procedural learning is already complete.

## 8. What remains partial / open

Open work includes:

- broader Work durability beyond the twenty-one proven crash/restart windows;
- general per-task restore/rollback, arbitrary workspace checkpoints and user-visible restore points;
- post-dispatch overwrite `verified_absent` remains intentionally unavailable because old-state equality is not causal proof that the effect never happened;
- direct `Path.write_text(...)` overwrite still permits partial-target ambiguity if the process or host fails during the write;
- any atomic/staged replacement design must account for Windows permissions/ACLs, file attributes, metadata semantics, temp-file cleanup and crash recovery instead of merely swapping in `os.replace()`;
- isolated parallel Work;
- long-horizon repetition/drift/provider-replacement benchmarks for resident intelligence;
- browser `PRESS`, broader click/text replacement/ARIA checkbox mutation, explicit tab/popup/frame ownership, headed managed-browser UX and authenticated User Browser Bridge;
- Windows M8 install / N->N+1 / rollback / signing evidence;
- SM1+ self-maintenance;
- high-risk identity, long-term-memory, credential/permission, updater/signing, rollback and destructive self-maintenance changes remain human-approval boundaries.

## 9. Next real target

Continue P5 at the partial-write / atomic-overwrite boundary, but do not implement a naive temp-file replacement merely because it is usually called atomic.

Next investigation should:

1. trace exact overwrite behavior on Windows for existing regular files, missing files, symlinks/reparse points, readonly files and repository files;
2. determine which security descriptor/ACL, attributes, timestamps and file identity semantics the current in-place write preserves that temp-file replacement could change;
3. design same-directory staging only if ZN can define and verify temp lifecycle, cleanup, target replacement and restart semantics without introducing an orphan-temp or stale-replace authority path;
4. preserve inherited repo baseline / Git delta / targeted-test / semantic verification ownership;
5. retain the new pre-dispatch identity as Situation evidence, not as unconditional mutation permission;
6. keep post-dispatch old-state equality insufficient for `verified_absent` unless stronger causal evidence is added;
7. add crash/restart window #22 only if a genuinely distinct interruption is closed and real Windows CI proves it.

Keep `main` untouched during ordinary development. Preserve outside-world uncertainty as uncertainty, not replay permission.