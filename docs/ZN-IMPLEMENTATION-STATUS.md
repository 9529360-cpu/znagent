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

Newest verified P5 overwrite-recovery proof head before this documentation synchronization:

```text
c4276f8b151d2c45b69368cb414f012bf0644d01  test: exercise nontruncated overwrite conflict
```

Status: **BROADER WORK DURABILITY REMAINS PARTIAL. TWENTY CONCRETE CRASH/RESTART WINDOWS ARE NOW CLOSED AND VERIFIED. THE TWENTIETH WINDOW COVERS AN ORDINARY OVERWRITE THAT REACHED THE FILESYSTEM BEFORE THE RESIDENT COULD SAVE ITS BODY RESULT/CHECKPOINT: RESTART WILL NOT BLINDLY REPLAY THE STALE OVERWRITE. IT RE-OBSERVES CURRENT FILE REALITY, COMPLETES ONLY WHEN THE EXACT INTENDED TEXT IS ALREADY PRESENT, AND OTHERWISE HOLDS UNCERTAINTY WITHOUT MUTATING THE FILE. GENERAL PER-TASK RESTORE/ROLLBACK REMAINS OPEN/PARTIAL.**

The resident-intelligence direction is also now explicit: mature general computer-use/recovery mechanics should become ZN-owned built-in competence, while post-birth learning concentrates on user/environment/project-specific experience. This architecture direction is broader than current implementation and must not be reported as complete.

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
- active ordinary overwrite writes now participate in the resident side-effect ownership/recovery lifecycle without broadening the reusable generic guard contract.

Generic nervous `perceive()` remains intentionally plastic and is not an exactly-once API.

## 2. Twenty proven broader Work crash/restart windows

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
20. an ordinary exact overwrite can reach the filesystem and then lose the process before Body result / resident checkpoint persistence. A durable `started` side-effect attempt survives. Restart detects the exact replay-sensitive signature, enters overwrite recovery instead of dispatching the write again, and performs only read-only current-world verification. Exact intended content resolves the attempt as `verified_effect` and completes without replay. Any mismatch, truncation or observation failure remains replay-blocked and does not mutate the target. A regression test also proves an external/user edit after the crash is preserved.

The crash-window count is now twenty. Browser lifecycle proofs, synchronous caller control, shared-attempt pruning and Body-accounting invariants remain additional evidence, not artificial crash-window counts.

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

Status: **PARTIAL / TWO BOUNDED SLICES CI VERIFIED**

P5 is not generic workspace rollback. It currently contains two bounded recovery improvements.

### 6.1 Accepted Work ingress checkpoint

Proof head:

```text
2c20b8bded96ce07c6ec43263cc77b7bd10a7a82  fix: recover accepted Work ingress before event creation
```

Active ingress chain:

```text
ResidentRpcServer.work_start
-> ResidentWorkControl.start
-> RecoveryBoundedWorkLedger.start
-> work_ingress_checkpoints
-> durable Work user message
-> resident AgentEvent
-> durable work_runs linkage
```

Restart verifies exact thread/message/event identities, reconstructs only a missing **pending** event with zero attempts, repairs WorkRun linkage and removes the short-lived checkpoint after agreement. It grants no execution/replay authority.

Proof:

```text
ZN Work Recovery E2E 33124662199  success
ZN CI                33124662367  success
```

### 6.2 Reality-gated overwrite recovery

Final proof head:

```text
c4276f8b151d2c45b69368cb414f012bf0644d01  test: exercise nontruncated overwrite conflict
```

Relevant implementation sequence includes:

```text
d6546ec1a3c5a9a8d3576cd06ecb182c0b312890  fix: recover interrupted overwrite from reality
0c8a553f9530b859c4a45ed8fadc1c50991cdca9  fix: activate overwrite recovery owner
21022c9f8460df789305e138152a4f04d6c96fd8  refactor: keep generic side-effect guard narrow
13f3c6708dfb0bcf4029fdda1146b9435fff8fa7  fix: scope overwrite guard to active resident
57aab99c16d506591e24d2334c379c7ba01a206c  ci: verify overwrite recovery
480bbca626eae1b02271f5eb95beeb8310f5d2e8  fix: keep overwrite recovery evidence content-free
a656b3952b1561657153f1b55da8c397d931a6e1  fix: preserve specialized overwrite lifecycle
c4276f8b151d2c45b69368cb414f012bf0644d01  test: exercise nontruncated overwrite conflict
```

Active semantics:

```text
fresh overwrite
-> inherited mature resident lifecycle remains authoritative
   (repo baseline / Git delta / targeted-test / semantic verification where applicable)
-> OverwriteAwareBody commits durable side-effect attempt before actual mutation
-> NativeBody overwrite currently performs Path.write_text(...)

hard crash after durable attempt + real write
-> WorkingState may still say native_action
-> restart sees exact replay-blocking attempt
-> Body refuses a second overwrite dispatch
-> side_effect_recovery
-> read current text only

current text == exact intended complete text
-> resolve attempt as verified_effect
-> complete without replay

anything else
-> user_decision_required / outside_world_effect_uncertain
-> preserve current file
-> no stale overwrite replay
```

Important safety properties:

- no raw file body is copied into overwrite recovery control metadata;
- recovery observation stores only bounded metadata such as action id, success, truncation and character count;
- a user/external edit after the crash is preserved;
- a mismatch is not treated as proof that the original write failed;
- a stale intent never becomes unconditional authority to restore/overwrite;
- the first implementation exposed a real regression by replacing higher-level Body ownership and thereby bypassing existing repo-aware/targeted-test behavior. That regression was fixed; final active code delegates all fresh overwrites to the inherited most-specific lifecycle and intercepts only already-durable replay-blocked attempts.

Final real Windows proof on exact head `c4276f8b151d2c45b69368cb414f012bf0644d01`:

```text
ZN Work Recovery E2E run 33129111422                  success
  Prepare isolated runtime                            success
  Compile Work recovery path                          success
  Verify durable Work progress and restart recovery  success

ZN CI run 33129111419                                  success
ZN Kernel / Python / Windows                           success
  Boot isolated ZN distribution without a model       success
  Compile resident core                               success
  Run ZN core tests against working tree              success
ZN Source Boundary / Windows                           success
Electron / TypeScript / Windows                        success
Publish Windows CI statuses                            success
```

No local repository test run is claimed for this web-maintainer slice. Repository self-hosted Windows CI is the verification authority.

## 7. Resident intelligence architecture direction

`ZN.md` and `docs/ZN-RESIDENT-INTELLIGENCE.md` now explicitly distinguish:

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

- broader Work durability beyond the twenty proven crash/restart windows;
- general per-task restore/rollback, arbitrary workspace checkpoints and user-visible restore points;
- automatic overwrite retry when the resident can prove the target still has the exact pre-dispatch state;
- privacy-safe pre-write identity for overwrite recovery;
- partial-write avoidance / atomic overwrite staging where appropriate;
- isolated parallel Work;
- long-horizon repetition/drift/provider-replacement benchmarks for resident intelligence;
- browser `PRESS`, broader click/text replacement/ARIA checkbox mutation, explicit tab/popup/frame ownership, headed managed-browser UX and authenticated User Browser Bridge;
- Windows M8 install / N->N+1 / rollback / signing evidence;
- SM1+ self-maintenance;
- high-risk identity, long-term-memory, credential/permission, updater/signing, rollback and destructive self-maintenance changes remain human-approval boundaries.

## 9. Next real target

Continue P5 at the narrower remaining overwrite boundary.

The current mechanism can prove **effect present** but intentionally cannot prove **effect absent** for an overwrite. A mismatch may mean old pre-state, partial write or a user/external change.

Next investigation/implementation should therefore:

1. reuse the existing `verified_absent` side-effect resolution path rather than add a competing recovery plane;
2. design a bounded, privacy-safe pre-write identity owned by the resident before overwrite dispatch, preferably metadata/digest evidence rather than stored raw file contents;
3. on restart, distinguish at least:
   - exact intended post-state -> complete without replay;
   - exact proven pre-dispatch state -> only then consider `verified_absent` and retry authorization;
   - anything else -> preserve uncertainty and do not mutate;
4. include file existence/type, canonical path identity and enough current-file identity evidence to reject external/user drift; do not treat content digest alone as unconditional authority if stronger host evidence is available;
5. evaluate whether atomic temp-file + replace semantics reduce partial-write ambiguity without creating a new cleanup/replay hazard;
6. preserve the inherited repo-aware / Git-delta / targeted-test lifecycle for fresh overwrites;
7. add a twenty-first crash/restart count only if a genuinely new distinct interruption is closed and real Windows CI proves it.

Keep `main` untouched during ordinary development. Preserve outside-world uncertainty as uncertainty, not replay permission.