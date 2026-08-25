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
a4a6d98e4139fd9a527474e007c378ccc52ba77f
fix: verify foreground at click boundary
```

Status: **CODE PRESENT / LOCAL STATIC COMPILE PASSED / EXACT-HEAD WINDOWS CI NOT EXECUTED**.

Automatic exact-head run:

```text
run 32875414203
```

At latest inspection the run existed but `fetch_workflow_run_jobs` returned zero jobs. The self-hosted Windows runner had not accepted the workflow. Per `docs/ZN-SELF-HOSTED-CI.md`, this is infrastructure availability evidence, not a passing or failing code-test result.

The latest fully verified implementation head remains:

```text
head  6f25b30c46d2f1bcafdd8f62e0968c2a4d05623e
run   32866088556

ZN Kernel / Python / Windows        success
ZN Source Boundary / Windows       success
Electron / TypeScript / Windows    success
Publish Windows CI statuses        success
```

That verified Windows kernel run used fresh CPython 3.12.13, installed the formal runtime, booted with zero external models, compiled the resident core, and completed full discovery with **416 tests passed and 5 platform-appropriate skips**.

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

External models do not own identity, execution authority, current-world truth, or completion.

## 3. Body / Senses / computer interaction

### Verified foundation through `6f25b30c...`

The verified narrow UI chain includes structured `pointer_click` authority, `visual_region_changed` local effect verification, durable click-start anti-replay, exact typed `ui_state_transition` completion, read-only `NativeForegroundWindowSense`, exact `foreground_window_matches(process_name, title_equals)` completion scope, target-already-satisfied zero-input completion, and fresh post-click foreground proof.

Foreground process/title proves only application/window identity. It does not prove internal application state, transaction completion, message delivery, network success, or arbitrary task prose.

### Current unverified source-context hardening

Commit `9b11b30cbd943e7b1cf4a0c24bff023d4d76098b` introduced an explicit typed mutation source precondition:

```text
action_precondition.kind = foreground_window_matches
action_precondition.process_name = exact source process
action_precondition.title_equals = exact source title
```

It required a fresh source foreground match before pointer movement and persisted the admitted event kind, intent, completion scope, and source precondition.

Further call-chain review found that its second foreground check still happened too early. The lower click lifecycle subsequently performed a fresh cursor check, captured the target-local visual baseline, persisted the non-replayable `started` marker, and only then delivered input. Foreground ownership could therefore drift during that remaining pre-input interval.

Commit `a4a6d98e4139fd9a527474e007c378ccc52ba77f` closes that timing gap without widening mutation authority.

Current intended lifecycle in code:

```text
fresh foreground observation
-> if completion target already matches: complete with zero input
-> otherwise require exact action_precondition
-> source foreground must match before pointer movement
-> persist admitted event kind + intent + completion scope + action precondition
-> existing bounded pointer movement/preparation
-> reject admitted authority drift
-> fresh pointer-state check
-> capture fresh target-local visual baseline
-> persist baseline + durable execution status="started"
-> FINAL fresh source-foreground check immediately before pointer input
   -> exact match: continue
   -> mismatch/unavailable/drift: mark execution status="aborted", input_sent=false; Investigation
-> exactly one left click
-> fresh local visual effect verification
-> verify admitted event/scope/precondition still match
-> fresh target foreground must match completion scope
-> only then close typed ui_state_transition
```

The base `VerifiedPointerClickResidentRuntime` now owns a default no-op `_pointer_click_final_input_precondition()` hook at the final input boundary. `SemanticPointerClickResidentRuntime` overrides it with resident-owned foreground evidence. Ordinary effect-only clicks retain their existing behavior.

The final hook runs after the durable `started` marker is saved. If the process crashes in that narrow interval, restart still sees an uncertain started click and refuses blind replay. When the hook explicitly rejects input, the resident records `status="aborted"` and `input_sent=false` before entering Investigation.

No keyboard, right-click, double-click, drag, generic browser automation catalog, OCR, model-derived fact, new dependency, or new mutation primitive was added.

Files changed by `a4a6d98e...`:

```text
runtime/python/zn_agent/core/pointer_click_resident.py
runtime/python/zn_agent/core/pointer_click_semantic_resident.py
tests/zn_agent/core/test_pointer_click_semantic_completion.py
```

Parent `70790cfc...` -> `a4a6d98e...` was reviewed and contains exactly those three files: 44 additions in the base lifecycle, 53 additions / 29 deletions in semantic timing, and 48 additions / 3 deletions in semantic tests.

Generated candidate versions of all three Python files passed `python -m py_compile`. No authoritative local private checkout exists, so no unit test is counted as passed for this head until repository CI actually executes.

Expanded regression coverage now includes:

- mutation requires explicit action precondition before movement;
- unsupported source-precondition authority fields fail closed;
- initial source foreground mismatch fails before movement;
- admitted authority drift fails before input;
- foreground drift after pointer movement is rejected at the final input boundary;
- foreground drift after visual baseline capture is rejected before input;
- an explicit final-boundary rejection persists `aborted` and `input_sent=false`;
- successful semantic transition records re-verification phase `final_before_pointer_input`;
- post-input precondition/scope drift still returns to Investigation without replay;
- target-already-satisfied zero-input completion remains allowed.

These tests are **present but not yet CI-executed**.

## 4. Repository source boundary

The active tree remains intended to be ZN-only and the scanner remains unchanged. The last fully executed Source Boundary success remains run `32866088556` at `6f25b30c...`. Current later heads require a real self-hosted Windows execution before their boundary status is called verified.

No source-boundary rule or exemption was weakened by the current safety hardening.

## 5. Desktop / runtime / release

Desktop ownership and runtime packaging are unchanged by this slice. The last fully verified desktop/runtime evidence remains run `32866088556`.

M8 remains **PARTIAL**. Still open for Windows x64:

1. clean Windows install/login evidence;
2. installed Windows N->N+1 continuity evidence;
3. rollback validation across a real Windows version transition;
4. applicable secure Windows signing evidence.

## 6. Self-maintenance

SM0 remains complete. SM1+ remains open. No self-maintenance architecture changed in this slice.

## 7. Current known debts / blockers

- self-hosted Windows x64 runner has not accepted the current exact-head workflow;
- `a4a6d98e...` requires real Kernel, Source Boundary, Electron and publisher execution before verification;
- real interactive-desktop foreground-window/screen-capture/click E2E evidence remains absent;
- semantic verification deeper than application/window identity remains open;
- structured read-only internal UI/application-state evidence remains open;
- broader input primitives remain intentionally absent until matching typed authority and verification exist;
- M8 Windows install/upgrade/rollback/signing evidence remains open;
- mature procedural competence/growth benchmarks remain partial;
- SM1+ remains open;
- non-blocking GitHub Actions runtime deprecation warnings remain tooling debt.

## 8. Next real targets

```text
1. restore/observe a replaceable Windows x64 self-hosted runner accepting the latest exact dev HEAD
2. inspect real Kernel / Source Boundary / Electron / publisher results
3. fix any executed failure; queued/no-job state is not a passing test
4. only after green CI mark the source-context/final-input hardening VERIFIED
5. then resume P5 read-only internal UI/application-state evidence beyond foreground identity
6. keep interactive-desktop E2E, M8, and SM1+ explicitly open
7. leave main untouched through ordinary development
```
