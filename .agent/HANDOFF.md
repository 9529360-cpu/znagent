# ZN Agent Handoff

Updated: 2026-08-26

## Current goal

ZN is now deliberately prioritizing resident-owned capability maturity before formal install/upgrade closure. The goal is not to create a larger model-called tool catalog. ZN should be born with mainstream computer/engineering capability breadth as owned Body/Senses and complete competence loops, then use lived verified experience to become faster and more reliable.

The current stage completed one narrow application-state improvement: read-only UI Automation can observe bounded AutomationId diagnostics, and the existing real pointer/UIA caller can optionally narrow its target by exact control type/class while continuing to require fresh pre-input and post-input verification.

Core principle:

> **ZN uses models. Models do not own ZN.**

## Branch / HEAD

- fixed development branch: `dev/zn-agent`
- canonical source/release branch: `main`
- latest fully verified implementation head: `9b8cc99798d98165c7801b4d4b9ff9bc34b7b662`
- status-ledger sync immediately before this handoff sync: `3b80a2ba8df6373e06d2f5fc605f43a8a7f7a897`
- canonical `main` at the start of this stage: `8234a835dea604783cea0bd9d28a40de654ec03d`
- PR #6 was draft/open/unmerged at the start of this stage, base `main`, head `dev/zn-agent`
- `main` was not modified in this stage
- no force push or history rewrite was used

Because a Git commit cannot truthfully contain its own SHA, the branch HEAD recorded above is the verified implementation head/status parent before this HANDOFF commit. Final reporting must re-read `dev/zn-agent`, `main`, PR #6 and exact-head CI after documentation sync.

## Completed in current stage

### 1. Restored repository truth and capability direction

Before modifying code, the required architecture/status/self-maintenance/source/HANDOFF documents, dev/main refs, PR #6, CI, recent commits and the active UI Automation click call chain were re-read.

Real starting dev HEAD was:

```text
86c658e735631d1a7154a529d7cfa1506271edc0
docs: hand off signal-free process sensing slice
```

Its exact-head Windows CI was fully green. `main` remained `8234a835...` and was not touched.

The repository already owns meaningful built-in foundations: file/path movement and sensing, process sensing, Git state/diff, terminal/PTTY, web resources/channels, visual sensing, pointer state/movement/click, foreground-window sensing, native focused-control sensing and read-only UI Automation sensing. The current gap is less “number of APIs” and more complete resident competence: identify current reality, form typed authority, act, independently verify, recover and learn.

### 2. Bounded AutomationId became read-only application evidence

Commit:

```text
4b0860b5ee43ceece40233513893d02be1bed555
feat: sense bounded UI automation ids
```

`NativeAutomationElementSense` now includes UIA AutomationId in its existing cached-property-only request and observation.

Boundaries:

- maximum 256 characters;
- cached-property API only;
- `AutomationElementMode_None` retained;
- no tree walking;
- no events;
- no control patterns;
- no mutation methods;
- dynamic UIA Name/text remains excluded;
- AutomationId is diagnostic/current application evidence only, not durable identity and not execution/completion authority.

Commit:

```text
5772af65d68eb73285a59fd6bbac435f0d23c3e1
test: guard bounded UI automation ids
```

Regression coverage proves bounded/truncated AutomationId, cached-property-only reads, injected oversize rejection and continued absence of dynamic `name`.

### 3. Existing UIA click target can be narrowed by typed application evidence

Commit:

```text
2b3a577947d49a03ff0b2e326de3251b90e02028
feat: narrow UI automation targets by type
```

The existing `focused_automation_element_at_pointer` completion scope now optionally accepts exact:

```text
control_type
class_name_equals
```

These are narrowing constraints on the existing real caller, not a generic selector/control plane.

The final pre-input target probe must match the typed scope or input is refused. Post-click focused UIA evidence must match the same pre-click RuntimeId plus any supplied type/class constraints before completion.

`name_equals` remains unsupported authority. `automation_id_equals` remains unsupported authority. Unknown fields fail closed.

Commit:

```text
b81a0c33576d10ebdc9cd34070597888f2932966
test: guard typed UI automation target scope
```

The regressions prove matching typed scope succeeds, mismatching control type aborts before input, and AutomationId cannot silently become authority.

### 4. Real interactive Windows typed-target proof is green

Commit:

```text
9b8cc99798d98165c7801b4d4b9ff9bc34b7b662
test: prove typed UI automation scope on Windows
```

The repository-defined real Windows fixture now obtains `control_type` and `class_name` from a fresh UIA observation of the target, passes those exact values into the typed completion scope, executes the existing ZN-owned pointer Body path with `model_policy=never`, then proves the actual Win32 checkbox toggled and fresh UIA/native focused-control state matches the target.

Exact-head workflow:

```text
run 32910542482
head 9b8cc99798d98165c7801b4d4b9ff9bc34b7b662
Windows interactive pointer/UIA E2E  success
```

Job evidence:

```text
formal runtime installed on self-hosted Windows x64 interactive session
CPython 3.12.13
test_real_resident_click_proves_visual_foreground_and_uia_focus ... ok
Ran 1 test in 2.846s
OK
```

This is narrow real evidence. It is not proof of arbitrary application semantics, browser DOM state or cross-machine compatibility.

### 5. Exact implementation-head normal Windows CI is green

Workflow:

```text
run 32910542532
head 9b8cc99798d98165c7801b4d4b9ff9bc34b7b662
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
checkout exact 9b8cc99798d98165c7801b4d4b9ff9bc34b7b662
CPython 3.12.13
formal znagent runtime installed from runtime/python
zero-model isolated resident boot success
resident core compile success
Ran 454 tests in 569.006s
OK (skipped=5)
```

The real Kernel log explicitly contains all new AutomationId/type/class authority tests as `ok`, including the negative no-input and non-authority cases.

Desktop evidence includes locked install, high-severity npm audit, typecheck, bundle, ownership/runtime/update/handoff contracts and release/runtime/artifact verifiers, all successful.

Source Boundary completed successfully without weakening ZN-only rules.

### 6. Status ledger synchronized

Commit immediately before this HANDOFF sync:

```text
3b80a2ba8df6373e06d2f5fc605f43a8a7f7a897
docs: record typed UI automation evidence
```

`docs/ZN-IMPLEMENTATION-STATUS.md` now reflects the exact implementation CI/E2E and the revised capability-development priority.

`ZN.md` was not changed because the existing architecture already prioritizes resident-owned competence and browser/computer Body/Senses before M8. `ZN-SOURCE-EXTRACTION.md` and `ZN-SELF-MAINTENANCE.md` were not changed because source-adoption and self-maintenance architecture did not change.

## Risks / boundaries

- Do not modify `main` through ordinary development.
- No force push/history rewrite.
- Do not weaken source-boundary scanning.
- External models must not own Body/Sense selection, execution authority, truth or completion.
- UI Automation remains a read-only Sense, not a generic mutation/control plane.
- Dynamic UIA Name/text remains excluded from the narrow current Sense.
- AutomationId is bounded evidence/diagnostics only and cannot be completion authority.
- RuntimeId remains opaque and action-cycle scoped, not durable identity or memory.
- No keyboard/right-click/double-click/drag authority has been added yet.
- New mutation primitives should not be added until matching typed authority and independent postcondition evidence exist.
- M8 install/upgrade/rollback/signing remains partial; it is not the immediate competence-development lane.
- SM1+ remains open.
- GitHub Actions JavaScript runtime deprecation warnings remain non-blocking tooling debt.
- The real interactive test also surfaces a non-blocking Pillow `Image.getdata` deprecation warning for future cleanup.

## Task queue

### P0 - exact-head Windows CI
Status: **VERIFIED / GREEN FOR IMPLEMENTATION HEAD**

Run `32910542532` at `9b8cc997...`: all four normal Windows jobs succeeded, Kernel **454 tests / 5 skipped / OK**.

### P1 - resident application-state semantics
Status: **VERIFIED NARROW TYPED UIA SLICE**

Bounded AutomationId diagnostic evidence plus optional exact control type/class target narrowing are real and tested. UIA remains read-only.

### P2 - real interactive computer-use proof
Status: **VERIFIED NARROW TYPED TARGET E2E**

Run `32910542482` proves the typed target path on the real Windows interactive fixture with `model_policy=never`.

### P3 - broader built-in computer-use competence
Status: **IN PROGRESS / NEXT LANE**

Mainstream capability breadth should be filled as complete ZN-owned loops rather than raw model-callable tools. The next candidate should be chosen from the real call chain, likely a safe typed keyboard/text-entry lifecycle or stronger browser/application-state sensing.

### P4 - mature procedural familiarity
Status: **PARTIAL**

Existing verified experience/procedural tendencies are real, but broader repeated real-task competence and growth benchmarks remain open.

### P5 - M8 Windows continuity / rollback / signing
Status: **PENDING / PARTIAL / NOT IMMEDIATE**

### P6 - SM1+ self-maintenance
Status: **PENDING**

## Next real target

1. re-read final `dev/zn-agent` HEAD after this HANDOFF commit and require its exact-head Windows CI to remain green;
2. preserve the current typed UIA evidence/authority boundaries and real interactive lane;
3. inspect the real existing call chain before selecting the next mainstream capability gap;
4. prefer one complete resident loop over many raw primitives: fresh Sense -> typed authority -> Body action -> independent postcondition -> contradiction/recovery;
5. strong next candidates are safe typed keyboard/text entry or stronger browser/application-state sensing, but do not implement either speculatively without its active caller and verification design;
6. keep learning as familiarity/reliability improvement, not as an excuse for missing basic built-in competence;
7. keep M8 and SM1+ explicitly open;
8. keep `main` untouched.
