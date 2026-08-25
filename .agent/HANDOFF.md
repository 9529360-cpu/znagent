# ZN Agent Handoff

Updated: 2026-08-26

## Current goal

The Windows process-sensing footgun is closed at root cause and covered by a real Windows regression. The existing interactive screen -> pointer -> foreground -> UIA-focus chain also now has a narrow real repository-defined E2E proof. The next engineering target is the next useful read-only application-state evidence only when a concrete typed caller justifies it; do not widen UI Automation or input authority speculatively.

Core principle:

> **ZN uses models. Models do not own ZN.**

## Branch / HEAD

- fixed development branch: `dev/zn-agent`
- canonical source/release branch: `main`
- latest fully verified implementation head: `3ccc7db03e6b55a6f407c13f49974ff04acdb7c8`
- status-ledger sync immediately before this handoff sync: `4dab01625b0b84f67ce5e60ef8d6cc14fbe18eed`
- canonical `main`: `8234a835dea604783cea0bd9d28a40de654ec03d`
- PR #6 remains draft/open/unmerged, base `main`, head `dev/zn-agent`
- `main` was not modified
- no force push or history rewrite was used

Because a Git commit cannot truthfully contain its own SHA, the branch HEAD recorded above is the exact parent immediately before this HANDOFF commit. The final report must re-read `dev/zn-agent` after this documentation sync and verify the resulting exact-head CI.

## Completed in current stage

### 1. Restored repository truth before changing anything

The required six documents were re-read together with dev/main refs, PR #6, main-to-dev compare, recent commits, exact-head Actions state, the `process_state` implementation, its formal dependency, its tests, and its active caller chain.

The old STATUS/HANDOFF were stale at `f5bca980...`; real branch state had already advanced to:

```text
07b76476847bc810e4cc14d3fb39e9a601426b4c
fix: make process sensing signal-free
```

Real code and CI were used as authority rather than the stale ledger.

### 2. Process sensing is now genuinely signal-free

Root fix:

```text
07b76476847bc810e4cc14d3fb39e9a601426b4c
fix: make process sensing signal-free
```

`runtime/python/zn_agent/core/body.py` now uses the project-formal runtime dependency:

```text
psutil.pid_exists(pid)
```

for read-only PID liveness. The old Windows-unsafe liveness probe:

```text
os.kill(pid, 0)
```

is no longer used by `process_state`.

`psutil==7.2.2` was already a formal `runtime/python` dependency; no compatibility shim or extra product dependency was introduced.

The active caller chain is real resident behavior:

```text
EmbodiedInvestigator processes probe
-> body.act("process_state")
-> NativeBody.act
-> _dispatch
-> _process_state
-> _record
```

Optional metadata from `psutil.Process(pid)` remains best-effort. Failure to read metadata does not mutate the target process or erase the read-only liveness result.

### 3. Final Windows footgun regression was added

Commit:

```text
3ccc7db03e6b55a6f407c13f49974ff04acdb7c8
test: guard process sensing against signals
```

`tests/zn_agent/core/test_native_body.py` now has `test_process_observation_is_signal_free`.

The test deliberately:

- patches `zn_agent.core.body.os.kill` and requires `assert_not_called()`;
- makes `psutil.pid_exists(424242)` return `True`;
- makes `psutil.Process(424242)` raise `PermissionError("metadata denied")`;
- verifies `process_state` still returns successful, alive, read-only evidence.

This is specifically aimed at the Windows footgun rather than merely repeating the existing positive PID-liveness test.

### 4. Exact implementation-head Windows CI is green

Workflow:

```text
run  32907209081
head 3ccc7db03e6b55a6f407c13f49974ff04acdb7c8
```

Results:

```text
ZN Source Boundary / Windows       success
ZN Kernel / Python / Windows       success
Electron / TypeScript / Windows   success
Publish Windows CI statuses       success
```

Kernel evidence from the completed job log:

```text
checkout exact 3ccc7db03e6b55a6f407c13f49974ff04acdb7c8
CPython 3.12.13
formal znagent runtime installed from runtime/python
psutil 7.2.2 installed
zero-model isolated resident boot success
resident core compile success
test_process_observation_is_signal_free ... ok
Ran 449 tests in 584.556s
OK (skipped=5)
```

Desktop evidence in the same run includes locked dependency installation, high-severity npm audit, typecheck, bundle, desktop ownership/runtime/update/handoff tests, and release/runtime/artifact verifiers, all successful.

Source Boundary also completed successfully without weakening scanner rules.

### 5. Real interactive Windows E2E is no longer absent

The implementation commit `07b76476847bc810e4cc14d3fb39e9a601426b4c` changed `body.py`, so it triggered `.github/workflows/zn-windows-interactive-e2e.yml`.

Workflow evidence:

```text
run 32906767247
head 07b76476847bc810e4cc14d3fb39e9a601426b4c
Windows interactive pointer/UIA E2E  success
```

The job used the self-hosted Windows x64 interactive runner/session, installed the formal runtime, and ran:

```text
test_real_resident_click_proves_visual_foreground_and_uia_focus ... ok
Ran 1 test in 3.172s
OK
```

This is a narrow real proof for the repository-defined screen -> pointer -> foreground -> UIA-focus chain. It must not be generalized into arbitrary DOM/business-state verification or broad cross-environment support.

The regression-only commit `3ccc7db...` changes a core test file, not an interactive-workflow path, so the interactive workflow correctly did not rerun for that commit. The actual `body.py` implementation SHA itself is the SHA that passed interactive E2E.

## Risks / boundaries

- Do not modify `main` through ordinary development.
- No force push/history rewrite.
- Do not weaken source-boundary scanning.
- `process_state` must remain observation, not process-control authority.
- UI Automation remains a read-only Sense, not a generic mutation/control plane.
- RuntimeId remains opaque and action-cycle scoped, not durable identity or memory.
- One real interactive runner/session proof is valuable but narrow; do not call it broad application compatibility.
- No keyboard/right-click/double-click/drag authority has been added.
- M8 updater/rollback/signing remains partial and high risk.
- SM1+ remains open.
- GitHub Actions JavaScript runtime deprecation warnings remain non-blocking tooling debt.

## Task queue

### P0 - exact-head Windows CI
Status: **VERIFIED / GREEN FOR IMPLEMENTATION HEAD**

Run `32907209081` at `3ccc7db...`; all four Windows jobs succeeded and Kernel completed **449 tests / 5 skipped / OK**. The final documentation-sync HEAD must still be independently re-read and its exact-head CI checked before the final report.

### P1 - bounded verifier manifest
Status: **VERIFIED NARROW SLICE / THREE REAL RELATIONS**

### P2 - resident visual foundation
Status: **VERIFIED FOUNDATION + ONE REAL INTERACTIVE E2E**

The existing screen/pointer/foreground/UIA-focus chain has one real self-hosted Windows interactive proof. Broader environment/application coverage remains open.

### P3 - bounded pointer movement
Status: **VERIFIED**

### P4 - narrow pointer click lifecycle
Status: **VERIFIED NARROW SLICE INCLUDING FINAL INPUT BOUNDARY**

### P5 - semantic/current-world UI verification
Status: **FOREGROUND + NATIVE FOCUSED-CONTROL + UIA FOCUSED-TARGET SLICES VERIFIED**

### P6 - M8 Windows continuity / rollback / signing
Status: **PENDING / PARTIAL**

### P7 - SM1+ self-maintenance
Status: **PENDING**

## Next real target

1. re-read final `dev/zn-agent` HEAD after this HANDOFF commit and require exact-head Windows CI to remain green;
2. preserve the signal-free `process_state` contract and regression;
3. investigate the next useful read-only application-state evidence only from a concrete typed caller;
4. do not widen UIA into generic tree search or control-pattern mutation without a separate authority design;
5. preserve the real interactive E2E lane and expand it only in response to concrete product failure modes;
6. keep RuntimeId short-lived and action-cycle scoped;
7. keep M8 and SM1+ explicitly open;
8. keep `main` untouched.
