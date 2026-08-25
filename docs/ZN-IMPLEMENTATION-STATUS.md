# ZN implementation status

> Architecture contract: [`../ZN.md`](../ZN.md)
>
> Memory/learning architecture: [`ZN-MEMORY-LEARNING.md`](ZN-MEMORY-LEARNING.md)
>
> Source adoption boundary: [`ZN-SOURCE-EXTRACTION.md`](ZN-SOURCE-EXTRACTION.md)
>
> Self-maintenance contract: [`ZN-SELF-MAINTENANCE.md`](ZN-SELF-MAINTENANCE.md)
>
> Real code, Git state and CI outrank this ledger.

Development branch: `dev/zn-agent`. Canonical source/release branch: `main`.

## 1. Current checkpoint - 2026-08-25

M10 canonical source promotion remains complete. `main` is canonical source/release; ordinary development remains on `dev/zn-agent`.

Current development implementation head before this status sync:

```text
9b11b30cbd943e7b1cf4a0c24bff023d4d76098b
fix: bind click input to foreground context
```

Status of that implementation: **CODE PRESENT / LOCAL STATIC COMPILE PASSED / EXACT-HEAD WINDOWS CI NOT YET EXECUTED**.

The automatic run for that head is:

```text
run 32873121911
```

At the latest inspection, the workflow had no jobs returned and the commit had zero published commit-status contexts. Per `ZN-SELF-HOSTED-CI.md`, this means no self-hosted runner had accepted the workflow yet. This is infrastructure availability evidence, not a code-test result. Do not report `9b11b30c...` as CI verified until real Windows jobs execute.

The latest fully verified implementation head remains:

```text
head  6f25b30c46d2f1bcafdd8f62e0968c2a4d05623e
run   32866088556

ZN Kernel / Python / Windows        success
ZN Source Boundary / Windows       success
Electron / TypeScript / Windows    success
Publish Windows CI statuses        success
```

That verified Windows kernel run used fresh CPython 3.12.13, installed the formal runtime, booted the resident with zero external models, compiled the resident core, and completed full discovery with **416 tests passed and 5 platform-appropriate skips**.

## 2. Resident ownership

The resident continues to own persistent Self/life state, Situation/Thought/Will, durable WorkingState, Investigation, native Body actions and Senses, bounded cognition resources, memory/reconsolidation, verified experience/procedural tendencies, channels, and resident work/progress state.

Active construction remains:

```text
provider_bridge.build_resident_runtime()
-> SemanticPointerClickResidentRuntime
-> EffectScopedPointerClickResidentRuntime
-> VerifiedPointerClickResidentRuntime
-> resident-owned lower runtime chain
```

No external model owns resident identity, execution authority, truth, or completion.

## 3. Body / Senses / computer interaction

### Verified foundation through `6f25b30c...`

The verified narrow UI chain still includes:

- structured `pointer_click` authority;
- `visual_region_changed` local effect verification;
- durable click-start marker and no blind replay;
- exact typed `ui_state_transition` completion;
- read-only `NativeForegroundWindowSense`;
- exact `foreground_window_matches(process_name, title_equals)` completion scope;
- target-already-satisfied no-input completion;
- fresh post-click foreground-window proof;
- no generic task-prose ability credit.

Foreground-window identity proves only application/window identity. It does not prove internal application state, transaction completion, message delivery, network success, or arbitrary natural-language task semantics.

### Current unverified safety hardening at `9b11b30c...`

Investigation found a pre-input stale-context gap: after the initial foreground probe, the lower click lifecycle rechecked pointer position and captured a fresh local visual baseline, but did not independently prove that the same intended source application/window still owned the foreground immediately before click delivery.

The current implementation adds a separate typed mutation precondition without widening input authority:

```text
completion target:
completion_scope.kind = foreground_window_matches
completion_scope.process_name = exact target process
completion_scope.title_equals = exact target title

action source context when input is required:
action_precondition.kind = foreground_window_matches
action_precondition.process_name = exact source process
action_precondition.title_equals = exact source title
```

Lifecycle now intended by the code:

```text
fresh foreground observation
-> if completion target already matches: complete with zero input
-> otherwise require exact action_precondition
-> source foreground must match before pointer movement
-> persist admitted event kind + intent id + completion scope + action precondition
-> prepare/move pointer through existing bounded lifecycle
-> validate admission has not drifted
-> fresh source foreground must still match after pointer preparation
-> mismatch/unavailable/drift: Investigation, no click
-> existing pointer + local visual baseline checks
-> durable started marker
-> exactly one left click
-> existing fresh local visual effect verification
-> verify admitted event/scope/precondition still match
-> fresh target foreground must match completion scope
-> only then close typed ui_state_transition
```

The target-already-satisfied path intentionally does not require an action precondition because it sends no input.

No keyboard, right-click, double-click, drag, browser automation catalog, OCR, model-derived fact, or new mutation primitive was added.

Files changed by `9b11b30c...`:

```text
runtime/python/zn_agent/core/pointer_click_semantic_resident.py
tests/zn_agent/core/test_pointer_click_semantic_completion.py
```

Parent-to-implementation diff was reviewed and contains exactly those two files. Generated candidate versions of both files passed `python -m py_compile`. No authoritative local private checkout exists, so unit execution still depends on repository CI.

New/expanded test coverage in that commit includes:

- mutation requires explicit action precondition before movement;
- unsupported precondition authority fields fail closed;
- source foreground mismatch fails before movement;
- foreground drift after pointer movement fails before click and before visual baseline capture;
- pre-input admitted precondition drift fails before click;
- post-input precondition drift fails without replay;
- target-already-satisfied zero-input behavior remains allowed;
- existing semantic mismatch and completion-scope drift behavior remains covered.

These tests are **not yet counted as passed** until exact-head CI executes.

## 4. Repository source boundary

The active tree remains intended to be ZN-only and the scanner remains unchanged. A prior docs-sync run exposed a forbidden retired marker in HANDOFF prose; that wording was corrected in `40186a21c64e5dc1116dd79bc0ae2a1111040948` without weakening the verifier or adding an exemption.

Because the self-hosted runner did not accept the follow-up run, the correction and the later safety hardening do not yet have fresh exact-head Source Boundary execution evidence. The last fully verified Source Boundary result remains run `32866088556` at `6f25b30c...`.

## 5. Desktop / runtime / release

Desktop ownership and runtime packaging remain unchanged by the current safety hardening. The last fully verified desktop/runtime evidence remains run `32866088556`.

M8 remains **PARTIAL**. Still open for the Windows x64 product target:

1. clean Windows install/login evidence;
2. installed Windows N->N+1 continuity evidence;
3. rollback validation across a real Windows version transition;
4. applicable secure Windows signing evidence.

## 6. Self-maintenance

SM0 remains complete. SM1+ remains open. No self-maintenance architecture changed in the current slice.

## 7. Current known debts / blockers

- self-hosted Windows x64 runner currently has not accepted the latest development workflow;
- `9b11b30c...` requires real exact-head Kernel, Source Boundary, Electron and status-publisher execution before verification;
- real interactive-desktop foreground-window/screen-capture/click E2E evidence remains absent;
- semantic verification deeper than application/window identity remains open;
- structured read-only internal UI/application state evidence remains open;
- broader input primitives remain intentionally absent until matching typed authority and verification exist;
- M8 Windows install/upgrade/rollback/signing evidence remains open;
- mature procedural competence/growth benchmarks remain partial;
- SM1+ remains open;
- non-blocking GitHub Actions runtime deprecation warnings remain tooling debt.

## 8. Next real targets

```text
1. restore/observe a replaceable Windows x64 self-hosted runner accepting the current workflow
2. require exact-head run 32873121911 or its latest-head successor to execute real jobs
3. fix any real failure; do not treat queued/no-status state as a passing test
4. only after green CI, mark the foreground action-precondition hardening VERIFIED
5. then resume P5: smallest useful read-only internal UI/application-state evidence beyond foreground identity
6. keep real interactive-desktop E2E, M8, and SM1+ explicitly open
7. leave main untouched through ordinary development
```
