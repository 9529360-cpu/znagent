# ZN Agent Handoff

Updated: 2026-08-25

## Current goal

The active lane remains browser/computer Body/Senses. The immediate goal is to get the current exact dev HEAD through real Windows x64 CI before expanding semantic UI state. The current implementation closes a stale-foreground timing gap at the final pointer-input boundary.

Core principle:

> **ZN uses models. Models do not own ZN.**

## Branch / HEAD

- fixed development branch: `dev/zn-agent`
- canonical source/release branch: `main`
- current implementation HEAD before this handoff sync: `a4a6d98e4139fd9a527474e007c378ccc52ba77f`
- canonical `main`: `8234a835dea604783cea0bd9d28a40de654ec03d`
- PR #6 remains draft/open/unmerged, base `main`, head `dev/zn-agent`
- main was not modified
- no force push or history rewrite was used

## Completed in current stage

### 1. Restored real repository state

The required architecture/status/handoff documents, dev/main refs, PR #6, recent commits, current CI, active builder, foreground Sense, pointer-click lifecycle, semantic layer, and semantic tests were re-read from the repository.

Before the current implementation commit, real dev was `70790cfc...`, main remained `8234a835...`, and dev was ahead 83 / behind 0.

### 2. CI remains infrastructure blocked

The prior exact-head run `32873438614` for `70790cfc...` still returned zero jobs. The new implementation run is:

```text
run  32875414203
head a4a6d98e4139fd9a527474e007c378ccc52ba77f
```

At latest inspection:

```text
workflow jobs returned: 0
```

Per `docs/ZN-SELF-HOSTED-CI.md`, no self-hosted Windows runner has accepted the workflow. This is **INFRASTRUCTURE BLOCKED / NOT EXECUTED**, not a passing or failing code-test result.

### 3. Closed the final pre-input stale-foreground interval

Previous implementation `9b11b30c...` added exact typed source-window authority:

```text
action_precondition.kind = foreground_window_matches
action_precondition.process_name = exact source process
action_precondition.title_equals = exact source title
```

That version proved the source foreground before movement and again after pointer preparation, but call-chain review showed the second check still happened before the lower lifecycle's fresh pointer-state check, visual baseline capture, durable started marker, and actual input delivery.

Current implementation commit:

```text
a4a6d98e4139fd9a527474e007c378ccc52ba77f  fix: verify foreground at click boundary
```

Real call chain:

```text
provider_bridge.build_resident_runtime()
-> SemanticPointerClickResidentRuntime
-> EffectScopedPointerClickResidentRuntime
-> VerifiedPointerClickResidentRuntime
-> NativeBody pointer_click
-> Windows SendInput
```

New final boundary:

```text
initial fresh foreground source proof
-> bounded pointer move/preparation
-> reject admitted authority drift
-> fresh pointer-state check
-> fresh target-local visual baseline
-> persist baseline + durable execution status="started"
-> _pointer_click_final_input_precondition()
   -> semantic layer probes foreground again
   -> exact action_precondition match required
   -> mismatch/unavailable/drift: status="aborted", input_sent=false, Investigation
-> only then body.act("pointer_click") / SendInput
```

The base lifecycle owns a default no-op final-input hook, so ordinary effect-only pointer clicks keep their previous semantics. The semantic runtime overrides the hook with the foreground source check.

The durable `started` marker remains before the final check. A crash in that narrow danger zone still produces conservative anti-replay behavior. A deliberate final-precondition rejection records that input was not sent.

No new mutation primitive, dependency, model authority, OCR, keyboard, drag, right-click, double-click, or generic browser control plane was added.

### 4. Regression coverage expanded

`tests/zn_agent/core/test_pointer_click_semantic_completion.py` now also covers:

- foreground drift after pointer movement rejected at the final input boundary;
- foreground drift specifically after visual baseline capture rejected before input;
- final rejection persists execution `status="aborted"` and `input_sent=false`;
- successful input records semantic re-verification phase `final_before_pointer_input`.

Existing coverage for missing/mismatched source preconditions, unsupported authority fields, admission drift, post-input scope/precondition drift, semantic mismatch, and zero-input already-satisfied completion remains present.

Generated candidate versions of these files passed local static compile:

```text
runtime/python/zn_agent/core/pointer_click_resident.py
runtime/python/zn_agent/core/pointer_click_semantic_resident.py
tests/zn_agent/core/test_pointer_click_semantic_completion.py
```

All three passed `python -m py_compile`. There is no authoritative local private checkout, so no unit tests are counted as passed for this head until GitHub Actions executes.

### 5. Diff reviewed

Parent `70790cfc...` -> `a4a6d98e...` contains exactly three files:

```text
runtime/python/zn_agent/core/pointer_click_resident.py               +44 / -0
runtime/python/zn_agent/core/pointer_click_semantic_resident.py      +53 / -29
tests/zn_agent/core/test_pointer_click_semantic_completion.py        +48 / -3
```

The branch was advanced by non-forced fast-forward.

## Last fully verified CI

The latest fully verified implementation remains:

```text
head 6f25b30c46d2f1bcafdd8f62e0968c2a4d05623e
run  32866088556

ZN Kernel / Python / Windows        success
ZN Source Boundary / Windows       success
Electron / TypeScript / Windows    success
Publish Windows CI statuses        success
full core discovery                 416 passed, 5 skipped
```

Do not extend that verification claim to `a4a6d98e...` until a self-hosted Windows runner actually executes the latest exact-head jobs.

## Risks / boundaries

- Do not modify main through ordinary development.
- No force push/history rewrite.
- Do not weaken source-boundary scanning.
- Exact process/title matching remains intentionally strict.
- Foreground identity is not internal application/business semantic proof.
- Current hardening is committed but not CI verified because no self-hosted runner accepted the workflow.
- Real interactive-desktop E2E remains absent.
- Broader input authority remains intentionally absent.
- M8 updater/rollback/signing remains partial and high risk.

## Task queue

### P0 - exact-head Windows CI
Status: **BLOCKED BY SELF-HOSTED RUNNER AVAILABILITY**

Current implementation run: `32875414203` for `a4a6d98e...`. No jobs have been accepted yet.

### P1 - bounded verifier manifest
Status: **VERIFIED NARROW SLICE / THREE REAL RELATIONS**

### P2 - resident visual foundation
Status: **VERIFIED FOUNDATION**

Real interactive-desktop capture evidence remains open.

### P3 - bounded pointer movement
Status: **VERIFIED**

### P4 - narrow pointer click lifecycle
Status: **VERIFIED NARROW SLICE / FINAL-INPUT HOOK PRESENT BUT CURRENT HEAD CI UNVERIFIED**

### P5 - semantic/current-world UI verification
Status: **FOREGROUND COMPLETION VERIFIED THROUGH `6f25b30c...` / SOURCE-CONTEXT AND FINAL-INPUT HARDENING PRESENT BUT CI UNVERIFIED**

Deeper internal UI/application-state semantics remain open. Do not resume mutation expansion while the current exact head lacks real Windows execution.

### P6 - M8 Windows continuity / rollback / signing
Status: **PENDING / PARTIAL**

### P7 - SM1+ self-maintenance
Status: **PENDING**

## Next real target

1. get a replaceable Windows x64 self-hosted runner online/available so the latest exact-head workflow is accepted;
2. inspect real Kernel / Source Boundary / Electron / publisher results;
3. fix any executed failure rather than assuming success;
4. once green, synchronize the final-input hardening as verified without creating an infinite docs-only loop;
5. then resume the smallest useful read-only internal UI/application-state Sense beyond foreground identity;
6. keep real interactive-desktop E2E, M8, and SM1+ explicitly open;
7. keep `main` untouched.
