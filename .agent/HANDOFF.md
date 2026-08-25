# ZN Agent Handoff

Updated: 2026-08-25

## Current goal

The active lane remains browser/computer Body/Senses. The final foreground-aware pointer-click hardening is now verified on the real Windows x64 self-hosted CI runner. The next engineering target is the smallest useful read-only internal UI/application-state evidence beyond foreground-window identity, but only if it has a real typed active caller.

Core principle:

> **ZN uses models. Models do not own ZN.**

## Branch / HEAD

- fixed development branch: `dev/zn-agent`
- canonical source/release branch: `main`
- latest fully verified implementation head before this handoff sync: `1e325926149f4df00ac7f7f83ba3d82c6611b7e6`
- canonical `main`: `8234a835dea604783cea0bd9d28a40de654ec03d`
- PR #6 remains draft/open/unmerged, base `main`, head `dev/zn-agent`
- before docs sync, dev is ahead 86 / behind 0 relative to main
- main was not modified
- no force push or history rewrite was used

## Completed in current stage

### 1. Restored the real repository and CI state

The required architecture/status/handoff documents, current dev/main history, PR #6, main-to-dev compare, current pointer-click tests, resident completion lifecycle, and exact-head Windows CI were re-read from GitHub.

Repository truth before this docs sync:

```text
dev  1e325926149f4df00ac7f7f83ba3d82c6611b7e6
main 8234a835dea604783cea0bd9d28a40de654ec03d
PR #6 open / draft / mergeable / unmerged
```

### 2. Windows self-hosted runner recovered and executed real jobs

The previous infrastructure condition (`jobs=[]`) is no longer present. The runner accepted actual Windows jobs and completed the exact-head workflow.

The first recovered run at `abbacede34e...` was useful evidence rather than a false green:

```text
run 32875624835
ZN Source Boundary / Windows       success
Electron / TypeScript / Windows   success
ZN Kernel / Python / Windows       failure
Publish Windows CI statuses       success
```

Kernel executed the full suite and exposed exactly one test error. This proved the infrastructure was functioning and moved the blocker from runner availability to a real test failure.

### 3. Root-caused the single Kernel failure

The failing test was:

```text
test_pointer_click_semantic_completion.PointerClickSemanticCompletionTests.
test_ui_state_transition_needs_fresh_semantic_match_after_click
```

The semantic runtime behavior had succeeded. The failure was a `KeyError` because the test attempted to read:

```text
native_pointer_click_semantic_precondition
```

after successful completion. The real resident lifecycle intentionally runs `_complete_result()`, persists the outcome, observes the action, then replaces WorkingState with `WorkingState(stage="idle")`.

The subsequent Windows `kernel.db` file-lock error was secondary cleanup fallout after the assertion error prevented the test from reaching `resident.store.close()`.

### 4. Applied the smallest correct fix

Commit:

```text
1e325926149f4df00ac7f7f83ba3d82c6611b7e6
test: assert click admission before completion reset
```

The commit changes exactly one test file. It moves the semantic admission assertions to the preceding `native_verification` state, where that durable execution evidence is intentionally present, before the successful terminal result resets WorkingState to idle.

No runtime/product code changed in this correction.

### 5. Exact-head real Windows CI is fully green

Workflow:

```text
run 32882987054
head 1e325926149f4df00ac7f7f83ba3d82c6611b7e6
```

Results:

```text
ZN Source Boundary / Windows       success
ZN Kernel / Python / Windows       success
Electron / TypeScript / Windows   success
Publish Windows CI statuses       success
```

Kernel evidence:

```text
CPython 3.12.13
formal runtime installed from runtime/python
zero-model isolated resident boot success
resident core compile success
Ran 423 tests in 351.803s
OK (skipped=5)
```

The semantic click tests, including both final-boundary drift tests and the successful `reverified_phase="final_before_pointer_input"` case, all passed in that real Windows run.

Published commit contexts for the verified implementation head are success:

```text
ZN Source Boundary
ZN Kernel / Python
Electron / TypeScript
```

### 6. Final foreground-aware click lifecycle is now verified

Real active chain:

```text
provider_bridge.build_resident_runtime()
-> SemanticPointerClickResidentRuntime
-> EffectScopedPointerClickResidentRuntime
-> VerifiedPointerClickResidentRuntime
-> NativeBody pointer_click
-> Windows input boundary
```

Verified semantic lifecycle includes:

```text
initial source foreground proof
-> zero-input completion if destination already matches
-> exact source action_precondition for mutation
-> bounded pointer movement
-> fresh pointer-state verification
-> fresh target-local visual baseline
-> durable execution status="started"
-> FINAL fresh source foreground recheck after visual baseline
   -> mismatch/unavailable: status="aborted", input_sent=false, Investigation
-> one left click only when source authority still matches
-> fresh visual effect proof
-> post-input authority-drift checks
-> fresh exact destination foreground proof
-> ui_state_transition completion
```

The final hook remains a no-op in the generic base and is overridden only by the semantic layer; effect-only pointer clicks were not widened.

## Risks / boundaries

- Do not modify main through ordinary development.
- No force push/history rewrite.
- Do not weaken source-boundary scanning.
- Exact process/title foreground matching remains intentionally strict.
- Foreground identity is not internal application/business semantic proof.
- Real interactive-desktop E2E is still absent even though simulated resident behavior is CI verified.
- Broader input authority remains intentionally absent.
- M8 updater/rollback/signing remains partial and high risk.
- SM1+ remains open.
- GitHub Actions JavaScript runtime deprecation warnings are tooling debt, not a current functional failure.

## Task queue

### P0 - exact-head Windows CI
Status: **VERIFIED / GREEN**

Verified run `32882987054` at `1e325926...`; all four required Windows jobs succeeded and Kernel completed **423 passed / 5 skipped**.

### P1 - bounded verifier manifest
Status: **VERIFIED NARROW SLICE / THREE REAL RELATIONS**

### P2 - resident visual foundation
Status: **VERIFIED FOUNDATION**

Real interactive-desktop capture evidence remains open.

### P3 - bounded pointer movement
Status: **VERIFIED**

### P4 - narrow pointer click lifecycle
Status: **VERIFIED NARROW SLICE INCLUDING FINAL INPUT BOUNDARY**

### P5 - semantic/current-world UI verification
Status: **FOREGROUND SOURCE + DESTINATION SEMANTICS VERIFIED**

Source action precondition, final pre-input foreground recheck, visual effect proof, and exact destination foreground completion are now real-Windows-CI verified. Deeper internal UI/application-state semantics remain open.

### P6 - M8 Windows continuity / rollback / signing
Status: **PENDING / PARTIAL**

### P7 - SM1+ self-maintenance
Status: **PENDING**

## Next real target

1. inspect the smallest useful read-only internal UI/application-state Sense beyond foreground identity;
2. trace entry -> owner -> state -> lifecycle -> dependency -> tests -> active caller first;
3. add nothing if it would be unused telemetry;
4. prefer bounded resident-owned native evidence that can feed a real typed completion/precondition/investigation boundary;
5. keep interactive-desktop E2E, M8, and SM1+ explicitly open;
6. keep exact-head Windows CI green;
7. keep `main` untouched.
