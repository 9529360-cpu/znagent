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

## 1. Current checkpoint - 2026-08-26

M10 canonical source promotion remains complete. `main` is canonical source/release; ordinary development remains on `dev/zn-agent`.

Latest fully verified implementation head:

```text
9b8cc99798d98165c7801b4d4b9ff9bc34b7b662
test: prove typed UI automation scope on Windows
```

Implementation lineage for the current application-state slice:

```text
4b0860b5ee43ceece40233513893d02be1bed555
feat: sense bounded UI automation ids

5772af65d68eb73285a59fd6bbac435f0d23c3e1
test: guard bounded UI automation ids

2b3a577947d49a03ff0b2e326de3251b90e02028
feat: narrow UI automation targets by type

b81a0c33576d10ebdc9cd34070597888f2932966
test: guard typed UI automation target scope

9b8cc99798d98165c7801b4d4b9ff9bc34b7b662
test: prove typed UI automation scope on Windows
```

Status: **VERIFIED ON REAL WINDOWS X64 CI AND REAL INTERACTIVE WINDOWS E2E**.

Exact-head normal workflow evidence:

```text
run 32910542532
head 9b8cc99798d98165c7801b4d4b9ff9bc34b7b662

ZN Source Boundary / Windows       success
ZN Kernel / Python / Windows       success
Electron / TypeScript / Windows   success
Publish Windows CI statuses       success
```

The Kernel job checked out exact SHA `9b8cc997...`, used CPython 3.12.13, installed the formal `znagent` runtime from `runtime/python`, booted an isolated zero-model resident, compiled the resident core and ran full discovery:

```text
Ran 454 tests in 569.006s
OK (skipped=5)
```

The new boundary regressions ran on the real Windows runner, including:

```text
test_observation_exposes_bounded_automation_id_without_dynamic_name ... ok
test_probe_rejects_injected_oversized_automation_id ... ok
test_snapshot_reads_bounded_ids_through_standard_cached_property_api ... ok
test_snapshot_truncates_automation_id_before_observation ... ok
test_automation_id_cannot_be_completion_authority ... ok
test_typed_control_scope_is_reverified_after_click ... ok
test_typed_control_scope_mismatch_aborts_before_input ... ok
```

Exact-head interactive evidence:

```text
run 32910542482
head 9b8cc99798d98165c7801b4d4b9ff9bc34b7b662
job Windows interactive pointer/UIA E2E
conclusion success

test_real_resident_click_proves_visual_foreground_and_uia_focus ... ok
Ran 1 test in 2.846s
OK
```

The interactive test used the repository-defined self-hosted Windows x64 input desktop and formal runtime. Its typed target constraints came from a fresh UI Automation observation before the action; the real resident then moved/clicked through the existing Body path, the owned Win32 checkbox actually toggled, and fresh post-action UIA/native-control evidence proved focus on the exact target.

## 2. Resident ownership

The resident continues to own persistent Self/life state, Situation/Thought/Will, durable WorkingState, Investigation, native Body actions and Senses, bounded cognition resources, memory/reconsolidation, verified experience/procedural tendencies, channels, and resident work/progress state.

External models do not own identity, execution authority, current-world truth, or completion.

Existing resident-owned foundations include local file/path movement and sensing, process sensing, Git state/diff, terminal and interactive PTY, web resources/channels, screen/visual sensing, pointer state/movement/click, foreground-window sensing, native focused-control sensing and read-only UI Automation sensing. Capability breadth is not considered mature merely because an API exists: a useful competence still requires typed authority, fresh current-world evidence, effect observation and independent completion proof.

The earlier signal-free `process_state` contract remains covered by the full exact-head Kernel run, including `test_process_observation_is_signal_free ... ok`.

## 3. Body / Senses / computer interaction

### 3.1 Read-only UI Automation Sense is richer but remains bounded

`NativeAutomationElementSense` still uses a lazy MTA worker and cached-property-only UI Automation reads with `AutomationElementMode_None`.

The Sense now exposes a bounded `automation_id` observation:

- read through the standard cached-property API;
- stripped and capped at 256 characters;
- treated as short-lived application-provided evidence/diagnostics;
- not durable identity;
- not execution or completion authority.

Dynamic UIA `Name` remains intentionally outside this narrow Sense. No dynamic control text was added.

No UIA tree walk, event subscription, control pattern, or mutation method was added.

Opaque UIA `RuntimeId` remains the exact short-lived target identity inside the current action cycle. It must not become durable semantic identity or long-term memory identity.

### 3.2 Typed target scope now narrows an existing real caller

The existing `focused_automation_element_at_pointer` completion scope may now optionally require:

```text
control_type: <positive UIA control type integer>
class_name_equals: <exact bounded class name>
```

These fields narrow the existing typed caller; they do not create a generic UIA selector language.

Before real pointer input, fresh target evidence must still match process, exact foreground source, RuntimeId eligibility and any supplied type/class constraints. A type/class mismatch aborts before input. After the click, fresh focused UIA evidence must match the exact pre-click RuntimeId and the same typed constraints before completion is accepted.

`name_equals` remains unsupported authority. `automation_id_equals` is explicitly regression-tested as unsupported authority. Unknown completion-scope fields continue to fail closed.

### 3.3 Mutation authority did not widen in this slice

No keyboard, right-click, double-click, drag, UIA control-pattern mutation or generic application automation authority was added.

The actual click still flows through the existing ZN-owned Body path. The UIA layer only senses and independently verifies current application state.

The useful pattern established by this slice is:

```text
fresh Sense evidence
-> explicit typed target scope
-> existing Body movement
-> fresh effect/state observation
-> independent completion proof
```

That pattern should be reused when broadening ZN's built-in computer-use competence rather than giving an external model a catalog of raw mutation tools.

## 4. Repository source boundary

The active tree remains ZN-only by contract and exact-head CI evidence.

Run `32910542532` completed `ZN Source Boundary / Windows` successfully at `9b8cc997...`. No ownership rule or scanner exemption was weakened. No reference product runtime/control plane was restored.

## 5. Desktop / runtime / release

Run `32910542532` completed `Electron / TypeScript / Windows` successfully at `9b8cc997...`, including locked dependency installation, high-severity advisory rejection, typecheck, bundle, desktop ownership/runtime/update/handoff contract tests, and release-channel/runtime-staging/artifact-verifier tests.

M8 remains **PARTIAL** and is not the immediate capability-development priority. Still open for Windows x64:

1. clean Windows install/login evidence;
2. installed Windows N->N+1 continuity evidence;
3. rollback validation across a real Windows version transition;
4. applicable secure Windows signing evidence.

These become hard release/update gates when ZN is ready for formal installed-body distribution; they are not a substitute for resident competence.

## 6. Self-maintenance

SM0 remains complete. SM1+ remains open. No self-maintenance architecture changed in this slice.

## 7. Current known debts / boundaries

There is no current Windows CI infrastructure blocker.

Still open:

- broader resident-owned computer-use competence beyond pointer/focus slices;
- a safe typed keyboard/text-entry lifecycle with independent postcondition proof before generic keyboard injection is allowed;
- broader browser/application-state sensing and verification from concrete ZN-owned callers;
- any future UIA property/tree/control-pattern use must have a concrete product need and preserve read/authority boundaries;
- broader interactive E2E coverage beyond the repository-defined Windows fixture;
- mature procedural competence/growth benchmarks across repeated real tasks;
- M8 Windows install/upgrade/rollback/signing evidence;
- SM1+;
- non-blocking GitHub Actions JavaScript runtime deprecation warnings;
- a non-blocking Pillow `Image.getdata` deprecation warning surfaced by the interactive visual test.

## 8. Next real targets

```text
1. keep exact-head Windows x64 CI and the real interactive lane green
2. continue filling mainstream computer-use capability gaps as ZN-owned Body/Senses/competence, not model-owned tools
3. prefer the next complete loop over a broad raw-tool catalog: sense target -> typed authority -> act -> independently verify
4. investigate a safe typed keyboard/text-entry slice or a stronger browser/application-state Sense from the real current call chain before implementation
5. keep UI Automation read-only unless a separate, evidence-backed mutation authority design is explicitly justified
6. keep RuntimeId short-lived and AutomationId non-authoritative
7. keep M8 and SM1+ explicitly partial/open while resident competence is still growing
8. leave main untouched through ordinary development
```
