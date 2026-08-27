# ZN Agent Handoff

Updated: 2026-08-27

## Current goal

Pause after closing and verifying the sixth broader Work durability crash
window. The common verified Body success path now survives a crash before
terminal `EventOutcome` publication without Body replay. Five earlier windows
remain closed and verified.

Broader Work durability remains **PARTIAL**. Do not infer completion from these six slices.

Founding boundary remains:

> **ZN uses models. Models do not own ZN.**

## Branch / repository truth

- repository: `9529360-cpu/znagent`
- development branch: `dev/zn-agent`
- canonical source/release branch: `main`
- canonical `main`: `8234a835dea604783cea0bd9d28a40de654ec03d`
- verified implementation/test head: `dc3b72ad1dfdc5bb8ac2a6c3898fe5038b85197d`
- common Body completion checkpoint: `dc3b72ad1dfdc5bb8ac2a6c3898fe5038b85197d`
- append terminal-boundary runtime checkpoint: `2ffb79c4bf11903d46f53dd9a7b8d1fcbd922642`
- companion test-contract checkpoint: `f7d6cb64121e914e0250736c0089d58c4b7fea2b`
- implementation-status documentation checkpoint before this HANDOFF sync: `c3b7e4b7a0c6dcfc0a053c4143666de46a2f3184`
- PR #6: draft/open/unmerged, base `main`, head `dev/zn-agent`
- `main` was not modified
- no force push or history rewrite was requested or performed

A HANDOFF commit cannot contain its own resulting SHA. Re-read `dev/zn-agent` after this file is committed and use that exact head externally.

## Completed in this stage

### Sixth crash window: common verified Body success before EventOutcome

The active common chain was:

```text
native verification succeeds
-> _complete_successful_body_action()
-> durable WorkingState.stage = complete
-> crash before outer _complete_result()
-> restart discards complete checkpoint and returns to orient
```

`EmbodiedResidentRuntime` now persists a resumable `native_completion`
checkpoint with the established Body result. Restart reconstructs that result
and reaches `KernelStore.complete_event()` without calling Body or repeating
runtime task accounting. Malformed completion data fails closed instead of
reopening action. Specialized pointer/semantic UI completion overrides were
not changed and remain separate proof targets.

Product regression:

```text
test_restart_publishes_verified_body_completion_without_body_replay
```

It proves restart, zero Body replay, stable runtime task count, terminal
`EventOutcome`, idle checkpoint and finalized Work progress.

### Fifth crash window: verified append recovery success before EventOutcome

The active append recovery path can durably split here:

```text
side_effect_recovery checkpoint (`reverify_effect`)
-> exact read-only text verification succeeds
-> side-effect attempt durably `verified_effect`
-> recovery returns successful BODY result
-> crash before outer `_complete_result()` publishes EventOutcome
```

Before `2ffb79c4...`, the success path persisted `WorkingState.stage = complete` before terminal publication. On restart, `_state_for_event()` intentionally does not resume a `complete` checkpoint, so the still-nonterminal event could lose the durable recovery position and re-enter from `orient`.

The effect-present append recovery path now keeps the last durable replay-safe `side_effect_recovery` checkpoint on disk until `KernelStore.complete_event()` atomically publishes terminal event state, exact `EventOutcome` and idle `WorkingState`. It may still return a success result in memory, but no intermediate terminal-looking checkpoint is persisted.

If the process dies after the recovery result but before `_complete_result()`, restart restores the same recovery checkpoint, re-runs only the exact read-only verification, idempotently acknowledges the already committed `verified_effect`, and does not replay `write_text`.

Regression `test_restart_after_verified_effect_before_checkpoint_save_completes_without_replay` now simulates both crash boundaries and reconstructs twice before final terminalization. The older `test_interrupted_append_completes_from_verified_effect_without_replay_or_failure_learning` was corrected to assert the same durable contract: pre-terminal state remains `side_effect_recovery`; only `_complete_result()` publishes `EventOutcome` + idle state.

This closes only this concrete append-recovery terminalization window. It does not prove the broader family of resident success/failure completion paths.

## Real test / CI truth

Exact-head sixth-window proof:

```text
head dc3b72ad1dfdc5bb8ac2a6c3898fe5038b85197d
ZN Work Recovery E2E run 33076704204  success / 51 tests / OK
ZN CI run 33076704179
Electron / TypeScript / Windows      success
ZN Source Boundary / Windows         success
ZN Kernel / Python / Windows         success / 601 tests / 5 skipped / OK
Publish Windows CI statuses          success
```

Local exact-code proof before push: 51 focused Work tests, 40 adjacent common
Body caller tests, and 601 core discovery tests with 5 skips; all OK.

Focused Work proof:

```text
ZN Work Recovery E2E run 33071963811
head f7d6cb64121e914e0250736c0089d58c4b7fea2b
Windows resident Work restart recovery  success
Ran 50 tests                            OK
```

Ordinary CI proof:

```text
ZN CI run 33071963819
head f7d6cb64121e914e0250736c0089d58c4b7fea2b
Electron / TypeScript / Windows   success
ZN Source Boundary / Windows      success
ZN Kernel / Python / Windows      success
Kernel                            600 tests / 5 skipped / OK
Publish Windows CI statuses       success
```

No local test run is claimed for this web-maintainer slice; repository self-hosted Windows CI is the verification authority.

## Housekeeping note

Earlier in this workstream, accidental one-byte placeholder `docs/.tmp-should-not-use` was created in `aafa7e6ae0c3784c63e931f5daf5fd0aec244c6a` and removed normally in `4f9d0aa3c94da88fc07203f18284cbc6cd26295d`. No force push, history rewrite or `main` change occurred.

## Current risks / incomplete work

- broader Work durability remains partial beyond the six verified crash windows;
- semantic UI completion and base resident investigation completion have analogous pre-`EventOutcome` paths that remain unproven;
- failure-side terminal-looking checkpoint paths remain unproven;
- no deliberate outcome-trace rewrite/compactor exists; destructive long-term-memory migration still requires separate review and explicit approval;
- explanatory-comment cleanup in `intentional_resident.py` remains non-behavioral debt;
- Windows M8 continuity remains incomplete;
- browser PRESS, broader click/editing/multi-select/page lifecycle remain incomplete;
- authenticated User Browser Bridge control remains incomplete;
- SM1+ self-maintenance remains incomplete;
- identity, long-term memory, credentials/permissions, updater/signing, rollback and destructive self-maintenance remain high-risk approval boundaries.

## Task queue

### P1 - broader Work durability

Status: **OPEN / SIX CRASH WINDOWS VERIFIED / PAUSED BY USER**

Closed without blind replay:

1. resident event committed before missing `work_runs` linkage;
2. recovery decision committed before the next `WorkingState` checkpoint;
3. append dispatch durably `observed` before the next `WorkingState` checkpoint;
4. generic command dispatch durably `observed` before the next `WorkingState` checkpoint, with cancellation coherently accepting that recovery-owned state;
5. append recovery already durably `verified_effect`, then returns success before terminal `EventOutcome`; restart preserves replay-safe recovery, re-verifies exact text and completes without append replay.

6. common verified Body success now resumes from `native_completion` and
   publishes terminal truth without Body replay.

### P2 - browser follow-ons

Status: **OPEN**

PRESS, broader click semantics, richer text editing, multi-select, broader page/target lifecycle and authenticated User Browser Bridge control.

### P3 - M8 / SM1+

Status: **OPEN**

Preserve human approval for high-risk identity, memory, credentials, updater/signing, rollback and destructive self-maintenance changes.

## Related files

```text
runtime/python/zn_agent/core/focused_modern_text_resident.py
runtime/python/zn_agent/core/embodied_resident.py
runtime/python/zn_agent/core/resident.py
runtime/python/zn_agent/core/store.py
runtime/python/zn_agent/core/work.py
tests/zn_agent/core/test_work_side_effect_recovery.py
tests/zn_agent/core/test_work_side_effect_resolution_recovery.py
tests/zn_agent/core/test_work_body_success_recovery.py
docs/ZN-IMPLEMENTATION-STATUS.md
.agent/HANDOFF.md
```

## Next real target

Paused at the user's request after the sixth verified checkpoint. When work is
resumed, re-read current repository and CI truth before selecting a seventh
window. Semantic UI completion, base resident investigation completion and
failure-side terminal-looking checkpoints remain candidates, not conclusions.
Keep `main` untouched during ordinary development.
