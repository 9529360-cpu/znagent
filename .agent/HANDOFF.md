# ZN Agent Handoff

Updated: 2026-08-28

## Current goal

P1-P4 are complete and CI-verified. P5 broader Work checkpoint/restore remains **PARTIAL / IN PROGRESS** with three bounded, verified slices:

1. accepted Work ingress checkpoint before resident-event creation (#19);
2. reality-gated ordinary overwrite effect-present recovery (#20);
3. privacy-bounded overwrite pre-dispatch identity/restart guard (#21).

Broader Work durability now has **TWENTY-ONE concrete crash/restart windows closed and verified**.

General per-task restore/rollback, arbitrary workspace snapshots, user-visible restore points, isolated parallel Work and post-dispatch automatic overwrite replay remain open.

Resident-intelligence product direction remains:

```text
resident-owned built-in competence
+ resident-owned learned competence
+ replaceable external cognition for genuine novelty
= ZN intelligence
```

Mature general computer/recovery mechanics should be engineered into ZN before first real use where concrete and verifiable. Post-birth learning should mainly adapt to user habits, environment, projects, recurring workflows and exceptions.

Founding boundary:

> **ZN uses models. Models do not own ZN.**

## Branch / repository truth

- repository: `9529360-cpu/znagent`
- development branch: `dev/zn-agent`
- canonical source/release branch: `main`
- canonical `main`: `8234a835dea604783cea0bd9d28a40de654ec03d`
- P5 ingress proof head: `2c20b8bded96ce07c6ec43263cc77b7bd10a7a82`
- P5 overwrite effect-present proof head: `c4276f8b151d2c45b69368cb414f012bf0644d01`
- P5 overwrite pre-dispatch proof head: `97803f8d0616c1f2b30a61af5acc686f1256cd11`
- implementation-status sync immediately before this HANDOFF: `d273ea803afcc75a5aba5341d5d6381c41ec8304`
- PR #6 remains draft development PR from `dev/zn-agent` to `main`
- `main` was not modified
- no force push or history rewrite was requested or performed

A HANDOFF commit cannot contain its own resulting SHA. Re-read `dev/zn-agent` after this commit and use the resulting exact HEAD externally.

## Completed stages

### P1 - shared side-effect-attempt persistence owner

Status: **COMPLETE / CI VERIFIED**

```text
ZN Work Recovery E2E 33117334326  success
ZN CI                33117334321  success
```

### P2 - bounded cumulative accounting/learning durability

Status: **COMPLETE / CI VERIFIED**

Proof head `f79d4f3c81b1d7c46dcfb55b6fc923acda77b39c`:

```text
ZN Work Recovery E2E 33119871079  success
ZN CI                33119871129  success
```

### P3 - managed-browser frontier reconciliation

Status: **COMPLETE / CI VERIFIED**

`SELECT_OPTION` and CHECK/UNCHECK are **VERIFIED NARROW**. `PRESS` remains OPEN.

```text
ZN Managed Browser E2E 33120809421  success
ZN CI                  33120848980  success
```

### P4 - resident-owned live-page registry

Status: **COMPLETE / CI VERIFIED NARROW**

Proof head `fffb0f4b84a76cef21a088167c9eb4faceb93afc`.

```text
ZN Managed Browser E2E 33122620361  success
ZN CI                  33122620398  success
```

Explicit tab/popup actions, frame identity, persistent browser-session recovery and PRESS remain open.

## P5 - durable Work checkpoint / restore foundation

Status: **PARTIAL / THREE BOUNDED SLICES CI VERIFIED**

### P5.1 - accepted Work ingress checkpoint (#19)

Proof head:

```text
2c20b8bded96ce07c6ec43263cc77b7bd10a7a82
```

Hard crash after accepted Work message but before resident event restores only the exact pending event/message/WorkRun linkage with zero attempts and no replay authority.

```text
ZN Work Recovery E2E 33124662199  success
ZN CI                33124662367  success
```

### P5.2 - ordinary overwrite effect-present recovery (#20)

Proof head:

```text
c4276f8b151d2c45b69368cb414f012bf0644d01
```

Active semantics:

```text
fresh overwrite
-> inherited most-specific lifecycle remains authoritative
-> OverwriteAwareBody durably starts side-effect attempt
-> actual mutation

hard crash after effect may have happened
-> exact durable attempt blocks replay
-> read-only current file observation
-> exact intended state => verified_effect / complete without replay
-> anything else => outside_world_effect_uncertain / preserve file / no replay
```

User/external edits after crash are preserved. Raw file contents are not copied into recovery control metadata.

```text
ZN Work Recovery E2E 33129111422  success
ZN CI                33129111419  success
```

### P5.3 - overwrite pre-dispatch identity guard (#21)

Status: **BOUNDED SLICE COMPLETE / CI VERIFIED**

Proof head:

```text
97803f8d0616c1f2b30a61af5acc686f1256cd11  fix: checkpoint overwrite pre-dispatch identity
```

New owner:

```text
runtime/python/zn_agent/core/file_identity.py
```

The file-identity sensor stores no raw file body. It records canonical path, existence/type, size, high-resolution timestamps, device/inode where available, and for stable regular files up to 8 MiB a complete SHA-256 observed with before/after stat agreement. Large files, symlinks, unsupported types or unstable/unobservable files fail closed for exact identity.

Active call chain remains:

```text
provider_bridge.build_resident_runtime()
-> RecoveryBoundedResidentRuntime
-> OverwriteRecoveryResidentRuntime
-> DurableBodyAccountingResidentRuntime
-> CapabilityRecoveryResidentRuntime
-> inherited specialized repo/Body completion owners
```

Fresh overwrite now owns this sequence:

```text
native_action intent durable
-> observe + durably save privacy-bounded pre-state identity
-> inherited fresh lifecycle
-> OverwriteAwareBody starts durable side-effect attempt
-> Body mutation
```

Distinct crash window #21:

```text
pre-state checkpoint durable
-> process dies before OverwriteAwareBody starts attempt
-> restart
```

Because `SideEffectAwareBody` starts the attempt before dispatch, **absence of the exact attempt proves ZN did not cross its guarded Body dispatch boundary**. Restart still re-observes current reality:

```text
exact same pre-state identity
-> original inherited fresh lifecycle may continue

target drifted / exact identity cannot be established
-> stale overwrite blocked
-> native_investigation
-> no side-effect attempt
-> no mutation
```

Important non-authority rule:

Once a durable side-effect attempt exists, the pre-state checkpoint can never authorize replay. Even if current file identity again equals the old pre-state, the original write may have happened and later been restored by the user/external process. Therefore post-dispatch `verified_absent` remains unavailable and replay stays blocked.

New hard-crash tests:

- drift after pre-dispatch crash -> stale overwrite blocked, external content preserved, zero attempts/writes;
- unchanged exact pre-state -> inherited fresh lifecycle resumes and normal independent verification completes;
- prior #20 effect-present and conflict tests remain regression-locked.

Real focused proof on exact head:

```text
ZN Work Recovery E2E run 33151244307                  success
  Prepare isolated runtime                            success
  Compile Work recovery path                          success
  Verify durable Work progress and restart recovery  success
```

Focused log: `Ran 95 tests ... OK`.

Real full-tree proof on exact same head:

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

Do not confuse this direction with already-complete general procedural competence.

## Current risks / incomplete work

- broader Work durability remains partial beyond twenty-one verified crash/restart windows;
- general per-task restore/rollback, arbitrary workspace checkpoints and user-visible restore points remain open;
- post-dispatch overwrite `verified_absent` remains intentionally unavailable;
- ordinary overwrite still ultimately uses direct `Path.write_text(...)`, leaving partial-target ambiguity on process/host failure during the write;
- a naive temp-file + replace change could alter Windows ACL/security descriptor, file attributes, metadata/identity behavior or leave orphan temp state, so atomic overwrite needs a real lifecycle design rather than a one-line substitution;
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
2. ordinary overwrite effect-present recovery/no-replay (#20);
3. overwrite pre-dispatch identity/drift guard (#21).

Next bounded P5 audit:

1. trace Windows overwrite semantics for existing regular files, missing files, reparse/symlink targets and readonly files;
2. inspect what current in-place `Path.write_text(...)` preserves versus same-directory staging/replacement: ACL/security descriptor, file attributes, timestamps, identity and sharing behavior;
3. design atomic/staged overwrite only if ZN can own temp naming, durable lifecycle, cleanup, replacement evidence and restart behavior without creating stale-replace authority;
4. preserve inherited repo baseline / Git delta / targeted-test / semantic verification owners;
5. keep pre-dispatch identity as Situation evidence, not post-dispatch mutation authority;
6. add #22 only for a genuinely new crash/restart window proven by real Windows CI.

## Next real target

Re-read final `dev/zn-agent` after this HANDOFF commit and inspect docs-only CI. Then continue P5 at the partial-write / Windows atomic-overwrite lifecycle audit. Keep `main` untouched.