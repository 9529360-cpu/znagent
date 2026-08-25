# ZN Agent Handoff

Updated: 2026-08-25

## Current goal

The active lane remains browser/computer Body/Senses. The current implementation hardens semantic pointer-click input against stale foreground-window context before attempting deeper UI/application semantics.

Core principle:

> **ZN uses models. Models do not own ZN.**

## Branch / HEAD

- fixed development branch: `dev/zn-agent`
- canonical source/release branch: `main`
- current implementation HEAD before this handoff sync: `9b11b30cbd943e7b1cf4a0c24bff023d4d76098b`
- canonical `main`: `8234a835dea604783cea0bd9d28a40de654ec03d`
- current dev was ahead 82 / behind 0 relative to main at last comparison
- PR #6 remains draft/open/unmerged, base `main`, head `dev/zn-agent`
- main was not modified
- no force push or history rewrite was used

## Completed in current stage

### 1. Restored real repository state

All required architecture/status/handoff documents, dev/main refs, PR #6, recent commits, CI, and the active pointer-click call chain were re-read from the repository.

### 2. Distinguished CI infrastructure blockage from code failure

Previous exact-head workflow `32869032969` for `40186a21...` remained queued with no published commit-status contexts. Repository documentation defines that state as no self-hosted runner having accepted the job yet.

The new implementation run is:

```text
32873121911
head 9b11b30cbd943e7b1cf4a0c24bff023d4d76098b
```

At latest inspection:

```text
workflow jobs returned: 0
commit status contexts: 0
```

Therefore current CI state is **INFRASTRUCTURE BLOCKED / NOT EXECUTED**, not success and not a code-test failure.

### 3. Fixed stale foreground context before semantic click input

Implementation commit:

```text
9b11b30cbd943e7b1cf4a0c24bff023d4d76098b  fix: bind click input to foreground context
```

Real call chain:

```text
provider_bridge.build_resident_runtime()
-> SemanticPointerClickResidentRuntime
-> EffectScopedPointerClickResidentRuntime
-> VerifiedPointerClickResidentRuntime
```

Problem found: when the semantic completion target was not already satisfied, the initial foreground mismatch only caused the resident to proceed. After pointer movement, the lower lifecycle verified cursor position and local visual baseline but did not prove that the intended source window still owned foreground immediately before click delivery.

Current code adds a typed source-window precondition only when mutation is actually needed:

```text
action_precondition.kind = foreground_window_matches
action_precondition.process_name = exact source process
action_precondition.title_equals = exact source title
```

Behavior:

```text
fresh foreground probe
-> target completion scope already matches
   -> complete with zero input; action_precondition not required
-> target not satisfied
   -> require exact action_precondition
   -> fresh source foreground match required before pointer movement
   -> persist event kind + intent + completion scope + action precondition admission
   -> existing bounded pointer preparation
   -> reject admission drift
   -> fresh source foreground match required again before click
   -> mismatch/unavailable/drift => Investigation, zero clicks
   -> existing visual baseline + durable started marker + one left click
   -> existing fresh local visual effect verification
   -> admitted scope/precondition still must match
   -> fresh target foreground must match completion scope
   -> only then typed ui_state_transition may complete
```

No mutation capability was widened. No new dependency was added.

### 4. Tests added/expanded

`tests/zn_agent/core/test_pointer_click_semantic_completion.py` now covers:

- missing action precondition before a mutating transition;
- unsupported action-precondition authority fields;
- fresh source foreground mismatch before movement;
- foreground drift after pointer move, with no click and no visual baseline capture;
- pre-input semantic admission drift;
- post-input action-precondition drift without replay;
- existing semantic mismatch/scope-drift behavior;
- target-already-satisfied no-input path.

Candidate runtime and test files passed local `python -m py_compile` before commit. There is no authoritative local private checkout, so these tests have not yet been executed locally or by CI.

### 5. Diff reviewed

Parent `40186a21...` -> `9b11b30c...` contains exactly:

```text
runtime/python/zn_agent/core/pointer_click_semantic_resident.py
tests/zn_agent/core/test_pointer_click_semantic_completion.py
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

Do not extend that verification claim to `9b11b30c...` until a self-hosted Windows runner actually executes the current exact-head jobs.

## Risks / boundaries

- Do not modify main through ordinary development.
- No force push/history rewrite.
- Do not weaken source-boundary scanning to make docs or code pass.
- Exact process/title matching remains intentionally strict.
- Foreground identity is not internal application/business semantic proof.
- Current safety hardening is committed but not yet CI verified because no self-hosted runner accepted the workflow.
- Real interactive-desktop E2E remains absent.
- Broader input authority remains intentionally absent.
- M8 updater/rollback/signing remains partial and high risk.

## Task queue

### P0 - exact-head Windows CI
Status: **BLOCKED BY SELF-HOSTED RUNNER AVAILABILITY**

Current run: `32873121911` for `9b11b30c...`. No jobs/status contexts have been accepted/published yet.

### P1 - bounded verifier manifest
Status: **VERIFIED NARROW SLICE / THREE REAL RELATIONS**

### P2 - resident visual foundation
Status: **VERIFIED FOUNDATION**

Real interactive-desktop capture evidence remains open.

### P3 - bounded pointer movement
Status: **VERIFIED**

### P4 - narrow pointer click lifecycle
Status: **VERIFIED NARROW SLICE**

### P5 - semantic/current-world UI verification
Status: **FOREGROUND COMPLETION VERIFIED THROUGH 6f25b30c / PRE-INPUT SOURCE-CONTEXT HARDENING PRESENT BUT CI UNVERIFIED**

Current unverified hardening prevents a semantic click from using stale foreground context after pointer preparation.

Deeper internal UI/application-state semantics remain open and should resume only after current exact-head CI executes successfully.

### P6 - M8 Windows continuity / rollback / signing
Status: **PENDING / PARTIAL**

### P7 - SM1+ self-maintenance
Status: **PENDING**

## Next real target

1. get a replaceable Windows x64 self-hosted runner online/available so the repository workflow accepts the current head;
2. inspect real Kernel / Source Boundary / Electron / publisher results for the latest exact dev HEAD;
3. fix any executed failure rather than assuming success;
4. once green, synchronize this hardening as verified without creating an infinite docs-only run loop;
5. then continue the smallest read-only internal UI/application-state Sense beyond foreground identity;
6. keep main untouched.
