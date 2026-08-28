# ZN Agent Handoff

Updated: 2026-08-28

## Current goal

P1 shared side-effect-attempt persistence, P2 bounded cumulative accounting/learning durability, P3 managed-browser frontier reconciliation, and bounded P4 resident-owned live-page registry are complete and CI-verified.

P5 broader Work checkpoint/restore remains **PARTIAL / IN PROGRESS**. Two bounded P5 slices are now real and CI-verified:

1. accepted Work ingress checkpoint before resident-event creation;
2. reality-gated crash/restart recovery for ordinary overwrite `write_text` / `write_file`.

Broader Work durability now has **TWENTY concrete crash/restart windows closed and verified**. Window #20 covers an overwrite that reached the filesystem but lost the process before Body result / resident checkpoint persistence. Restart will not blindly replay the stale overwrite. It re-observes current file reality; exact intended content completes without replay, while mismatch/truncation/observation failure remains uncertainty and preserves the current file.

General per-task restore/rollback, arbitrary workspace snapshots and user-visible restore points remain open.

Resident-intelligence product direction remains:

```text
resident-owned built-in competence
+ resident-owned learned competence
+ replaceable external cognition for genuine novelty
= ZN intelligence
```

Mature general computer/recovery mechanics should be engineered into ZN before first real use where concrete and verifiable. Post-birth learning should primarily adapt to the user's habits, environment, projects, recurring workflows and exceptions. This architecture is broader than current implementation and must not be reported as complete.

Founding boundary:

> **ZN uses models. Models do not own ZN.**

## Branch / repository truth

- repository: `9529360-cpu/znagent`
- development branch: `dev/zn-agent`
- canonical source/release branch: `main`
- canonical `main`: `8234a835dea604783cea0bd9d28a40de654ec03d`
- branch HEAD immediately before this HANDOFF synchronization commit: `38298b136f80eb42b5c3b8d13c84bddb63205927`
- P5 ingress proof head: `2c20b8bded96ce07c6ec43263cc77b7bd10a7a82`
- P5 overwrite final proof head: `c4276f8b151d2c45b69368cb414f012bf0644d01`
- implementation-status sync head before this HANDOFF: `38298b136f80eb42b5c3b8d13c84bddb63205927`
- PR #6 remains draft development PR from `dev/zn-agent` to `main`
- `main` was not modified
- no force push or history rewrite was requested or performed

A HANDOFF commit cannot contain its own resulting SHA. Re-read `dev/zn-agent` after this commit and use the resulting exact HEAD externally.

## Completed stages

### P1 - shared side-effect-attempt persistence owner

Status: **COMPLETE / CI VERIFIED**

```text
ZN Work Recovery E2E run 33117334326  success
ZN CI run 33117334321                 success
```

### P2 - bounded cumulative accounting/learning durability

Status: **COMPLETE / CI VERIFIED**

Proof head `f79d4f3c81b1d7c46dcfb55b6fc923acda77b39c`:

```text
ZN Work Recovery E2E run 33119871079  success
ZN CI run 33119871129                 success
```

### P3 - managed-browser frontier reconciliation

Status: **COMPLETE / CI VERIFIED**

`SELECT_OPTION` and CHECK/UNCHECK are **VERIFIED NARROW**. `PRESS` remains genuinely OPEN.

```text
ZN Managed Browser E2E run 33120809421  success
ZN CI run 33120848980                   success
```

### P4 - resident-owned live-page registry

Status: **COMPLETE / CI VERIFIED NARROW**

Commit `fffb0f4b84a76cef21a088167c9eb4faceb93afc` owns monotonic `page-N` identities, provider-page discovery, closed-page eviction, stale target/observation cleanup and deterministic default-page promotion.

```text
ZN Managed Browser E2E run 33122620361  success
ZN CI run 33122620398                   success
```

Explicit tab/popup actions, frame identity, persistent browser-session recovery and PRESS remain open.

## P5 - durable Work checkpoint / restore foundation

Status: **PARTIAL / TWO BOUNDED SLICES CI VERIFIED**

### P5.1 - accepted Work ingress checkpoint

Proof head:

```text
2c20b8bded96ce07c6ec43263cc77b7bd10a7a82  fix: recover accepted Work ingress before event creation
```

Verified semantics:

- exact message/event identities are preallocated and durable before message/event boundary;
- hard crash after accepted Work message but before event persistence restores only exact pending event, zero attempts, no execution;
- hard crash after event persistence but before `work_runs` linkage repairs linkage without duplicate event;
- identities must agree or recovery fails closed;
- ingress checkpoint disappears after ordinary linkage becomes durable;
- it grants no replay permission after resident execution/outside-world effects may have begun.

Proof:

```text
ZN Work Recovery E2E run 33124662199  success
ZN CI run 33124662367                   success
```

This established crash/restart window #19.

### P5.2 - reality-gated ordinary overwrite recovery

Status: **BOUNDED SLICE COMPLETE / CI VERIFIED**

Final proof head:

```text
c4276f8b151d2c45b69368cb414f012bf0644d01  test: exercise nontruncated overwrite conflict
```

Relevant implementation commits:

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

Active call chain:

```text
provider_bridge.build_resident_runtime()
-> RecoveryBoundedResidentRuntime
-> OverwriteRecoveryResidentRuntime
-> DurableBodyAccountingResidentRuntime
-> CapabilityRecoveryResidentRuntime
-> focused / embodied / specialized completion owners
```

Active semantics:

```text
fresh overwrite
-> inherited most-specific resident lifecycle remains authoritative
   (repo baseline / Git delta / targeted tests / semantic verification where applicable)
-> active OverwriteAwareBody commits durable side-effect attempt before mutation
-> NativeBody currently executes ordinary overwrite via Path.write_text(...)

hard crash after write reached filesystem but before Body result / WorkingState save
-> resident_side_effect_attempts keeps exact attempt in started state
-> restart still sees native_action
-> exact event/signature is replay-blocking
-> Body refuses second overwrite dispatch
-> side_effect_recovery
-> read-only current file observation

current file == exact intended text
-> resolve attempt as verified_effect
-> complete without replay

anything else
-> user_decision_required / outside_world_effect_uncertain
-> preserve current file
-> no replay
```

Safety properties:

- raw file contents are not copied into recovery control metadata;
- current user/external edit after crash is preserved;
- mismatch is not treated as proof that original write did not happen;
- stale intent never becomes unconditional overwrite/restore authority;
- shared `SideEffectAwareBody` keeps its old command + append contract; overwrite guard is active-product-specific;
- fresh overwrite continues through inherited specialized lifecycle rather than bypassing existing repo-aware/targeted-test ownership.

A first implementation exposed a real regression: replacing the active Body too broadly caused existing repo-aware baseline/Git-delta/targeted-test behavior to disappear. That regression was fixed instead of hidden. Only the final proof head is authoritative.

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

This establishes crash/restart window #20.

No local repository test run is claimed. Repository self-hosted Windows CI is verification authority.

## Product / architecture - resident intelligence

Status: **ARCHITECTURE DEFINED / BROADER IMPLEMENTATION PARTIAL**

`ZN.md` and `docs/ZN-RESIDENT-INTELLIGENCE.md` define the engineering-distillation rule:

```text
mature maintainable general knowledge
-> explicit ZN-owned sensing/state/procedure/verification/recovery
-> tests + actual evidence
-> ship as built-in resident competence
```

The user should not have to raise a naive agent into basic computer literacy. Post-birth learning should focus primarily on personal/environment/project-specific adaptation while broad general competence continues to improve through verified software evolution and lived evidence.

Do not confuse this direction with already-complete general procedural competence.

## Current risks / incomplete work

- broader Work durability remains partial beyond twenty verified crash/restart windows;
- general per-task restore/rollback, arbitrary workspace checkpoints and user-visible restore points remain open;
- overwrite recovery can currently prove effect-present but intentionally cannot prove effect-absent;
- no privacy-safe overwrite pre-dispatch file identity is yet durably available for safe automatic retry;
- NativeBody ordinary overwrite is still direct `Path.write_text(...)`, so partial-write ambiguity remains possible;
- any future retry/restore must reject user/external drift and must not turn a stale checkpoint into mutation authority;
- general procedural competence, repetition/drift/provider-replacement benchmarks and mature anomaly handling remain incomplete;
- isolated parallel Work remains open;
- browser `PRESS`, broader click/text replacement/ARIA checkbox mutation, explicit tab/popup/frame ownership, headed managed browser and authenticated User Browser Bridge remain incomplete;
- Windows M8 continuity and SM1+ remain incomplete;
- identity, long-term memory, credentials/permissions, updater/signing, rollback and destructive self-maintenance remain human-approval boundaries.

## Task queue

### P1

Status: **COMPLETE / CI VERIFIED**

### P2

Status: **COMPLETE / CI VERIFIED**

### P3

Status: **COMPLETE / CI VERIFIED**

### P4

Status: **COMPLETE / CI VERIFIED NARROW**

### P5

Status: **PARTIAL / IN PROGRESS**

Completed bounded slices:

1. accepted Work ingress checkpoint (#19);
2. ordinary overwrite effect-present recovery/no-replay (#20).

Next bounded P5 audit:

1. reuse existing side-effect `verified_absent` semantics instead of creating another recovery plane;
2. inspect current file/repo-aware intent lifecycle for any existing pre-write identity evidence that can be reused;
3. design a privacy-safe pre-dispatch identity for overwrite: canonical path + existence/type + bounded metadata + digest/equivalent content identity, without storing raw user file body in recovery control state;
4. ensure pre-state evidence is causally bound closely enough to durable dispatch ownership to avoid authorizing retry from stale evidence;
5. on restart distinguish:
   - exact intended post-state -> `verified_effect` / complete without replay;
   - exact proven pre-dispatch state -> only then `verified_absent` / retry may become eligible;
   - anything else -> remain uncertainty / no mutation;
6. evaluate same-directory temporary-file + atomic replace semantics as a way to avoid partial-target writes, but do not introduce cleanup/replay hazards or bypass specialized repo-aware lifecycle;
7. add crash/restart window #21 only if a genuinely new interruption is closed and real Windows CI proves it.

## Next real target

Re-read final `dev/zn-agent` after this HANDOFF commit and inspect docs-only CI. Then continue P5 at the overwrite pre-write-identity / `verified_absent` boundary. Keep `main` untouched.