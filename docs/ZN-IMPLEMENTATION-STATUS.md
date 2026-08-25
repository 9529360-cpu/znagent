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
3ccc7db03e6b55a6f407c13f49974ff04acdb7c8
test: guard process sensing against signals
```

Implementation lineage for the Windows process-sensing closure:

```text
07b76476847bc810e4cc14d3fb39e9a601426b4c
fix: make process sensing signal-free

3ccc7db03e6b55a6f407c13f49974ff04acdb7c8
test: guard process sensing against signals
```

Status: **VERIFIED ON REAL WINDOWS X64 CI**.

Exact-head workflow evidence for `3ccc7db...`:

```text
run 32907209081

ZN Source Boundary / Windows       success
ZN Kernel / Python / Windows       success
Electron / TypeScript / Windows   success
Publish Windows CI statuses       success
```

The Kernel job checked out exact SHA `3ccc7db03e6b55a6f407c13f49974ff04acdb7c8`, used CPython 3.12.13, installed the formal `znagent` runtime from `runtime/python` including `psutil==7.2.2`, booted an isolated zero-model resident, compiled the resident core, and ran full discovery:

```text
Ran 449 tests in 584.556s
OK (skipped=5)
```

The new regression itself ran on the real Windows runner:

```text
test_process_observation_is_signal_free ... ok
```

## 2. Resident ownership

The resident continues to own persistent Self/life state, Situation/Thought/Will, durable WorkingState, Investigation, native Body actions and Senses, bounded cognition resources, memory/reconsolidation, verified experience/procedural tendencies, channels, and resident work/progress state.

External models do not own identity, execution authority, current-world truth, or completion.

The active process-sensing call chain is real resident code:

```text
EmbodiedInvestigator processes probe
-> resident.body.act("process_state")
-> NativeBody.act()
-> NativeBody._dispatch()
-> NativeBody._process_state()
-> NativeBody._record()
```

`process_state` now performs a genuinely read-only liveness check with `psutil.pid_exists(pid)`. It no longer uses `os.kill(pid, 0)`, which is not signal-free on Windows. Optional process metadata remains best-effort through `psutil.Process(pid)` and cannot turn metadata-access denial into process mutation.

The regression test explicitly patches `zn_agent.core.body.os.kill` and asserts it is never called. It also forces `psutil.Process` to raise `PermissionError` and verifies that the liveness result remains successful and read-only.

## 3. Body / Senses / computer interaction

### 3.1 Existing verified click and UI Automation boundary

The previously verified bounded pointer-click lifecycle, foreground-window Sense, focused native-control Sense, and read-only UI Automation Sense remain intact.

`NativeAutomationElementSense` remains deliberately read-only: no tree walking, event subscriptions, control patterns, or UIA mutation authority were added in this slice. Opaque UIA `RuntimeId` remains action-cycle scoped rather than durable semantic identity.

### 3.2 Real interactive Windows E2E now exists

The previous ledger said real interactive-desktop E2E was absent. That is no longer true.

Implementation commit `07b76476847bc810e4cc14d3fb39e9a601426b4c` triggered repository workflow `ZN Windows Interactive Desktop E2E`:

```text
run 32906767247
job Windows interactive pointer/UIA E2E
conclusion success
```

The self-hosted Windows x64 runner checked out exact SHA `07b76476847bc810e4cc14d3fb39e9a601426b4c`, installed the formal runtime, and ran:

```text
test_real_resident_click_proves_visual_foreground_and_uia_focus ... ok
Ran 1 test in 3.172s
OK
```

This is narrow but real evidence for the existing screen -> pointer -> foreground -> UIA-focus chain on the repository-defined interactive runner/session. It does **not** prove arbitrary DOM state, arbitrary application semantics, business transaction completion, message delivery, network success, or broad cross-machine compatibility.

The later regression-only commit `3ccc7db...` changes only `tests/zn_agent/core/test_native_body.py`, so the path-filtered interactive workflow does not rerun for that docs/test-only change; the implementation commit that changed `body.py` is the exact SHA that passed interactive E2E.

## 4. Repository source boundary

The active tree remains ZN-only by contract and exact-head CI evidence.

Run `32907209081` completed `ZN Source Boundary / Windows` successfully at `3ccc7db...`. No ownership rule or scanner exemption was weakened.

## 5. Desktop / runtime / release

Run `32907209081` completed `Electron / TypeScript / Windows` successfully at `3ccc7db...`, including locked dependency installation, high-severity advisory rejection, typecheck, bundle, desktop ownership/runtime/update/handoff contract tests, and release-channel/runtime-staging/artifact-verifier tests.

M8 remains **PARTIAL**. Still open for Windows x64:

1. clean Windows install/login evidence;
2. installed Windows N->N+1 continuity evidence;
3. rollback validation across a real Windows version transition;
4. applicable secure Windows signing evidence.

## 6. Self-maintenance

SM0 remains complete. SM1+ remains open. No self-maintenance architecture changed in this slice.

## 7. Current known debts / blockers

There is no current Windows CI infrastructure blocker.

Still open:

- broader semantic verification for application state beyond the narrow verified focus scopes;
- any future UIA property/tree use must have a real typed active caller and remain read-only unless a separate authority design is approved;
- broader input primitives until matching typed authority and independent verification exist;
- broader interactive E2E coverage beyond the one repository-defined screen/pointer/foreground/UIA-focus proof;
- M8 Windows install/upgrade/rollback/signing evidence;
- mature procedural competence/growth benchmarks;
- SM1+;
- non-blocking GitHub Actions JavaScript runtime deprecation warnings.

## 8. Next real targets

```text
1. keep exact-head Windows x64 CI green
2. investigate the next useful read-only application-state evidence only from a concrete typed caller
3. do not turn UI Automation into a generic mutation/control plane
4. keep RuntimeId short-lived and action-cycle scoped
5. preserve the real interactive E2E lane and widen it only when a concrete failure mode justifies it
6. keep M8 and SM1+ explicitly partial/open
7. leave main untouched through ordinary development
```
