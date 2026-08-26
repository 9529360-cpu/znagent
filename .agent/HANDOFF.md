# ZN Agent Handoff

Updated: 2026-08-26

## Current goal

Continue durable resident-owned Work from the verified restart/resume, atomic-terminal, generic anti-replay, and first append reverification foundations.

The next real target is the Work control plane: expose a stable sanitized recovery object through `work_progress`, then add explicit user/cancel/recovery decisions for unverifiable side effects. Do not make the UI, model, provider, or error strings the owner of recovery truth.

Do not spend the current stage on the deferred Windows NetworkService DOS-8.3 path-identity defect unless it materially blocks current Work development.

Founding boundary remains:

> **ZN uses models. Models do not own ZN.**

## Branch / repository truth

- repository: `9529360-cpu/znagent`
- fixed development branch: `dev/zn-agent`
- canonical source/release branch: `main`
- current recovery implementation head before documentation: `1bcbf410a401755d6037423ea677cb3db1c6217a`
- atomic ownership regression fix: `e74679fee481898c6d4e9260f4134e2ae563e272`
- atomic Work checkpoint: `f02582557a39f32273fb806929a6f64906fea547`
- prior Work restart checkpoint: `2bce63a23252b7166244d0afd9dcac63b6b4fc26`
- managed-browser checkpoint: `8c94f1ac9a3fdda2e704f45bdaf02efdc4d40271`
- canonical `main`: `8234a835dea604783cea0bd9d28a40de654ec03d`
- PR #6: draft/open/unmerged, base `main`, head `dev/zn-agent`
- `main` was not modified
- no force push or history rewrite was used

A HANDOFF commit cannot contain its own resulting SHA. Re-read `dev/zn-agent` after this file is committed and report the resulting exact head externally.

## Completed in current stage

### 1. Atomic terminal ownership invariant corrected

Ordinary CI exposed a real regression from the first atomic terminalization slice: a claimed event could legitimately finish while singleton `WorkingState` remained idle/unowned, but `KernelStore.complete_event()` originally required that event to already own the checkpoint.

Correct invariant now is:

```text
idle/unowned checkpoint -> completion allowed
same-event checkpoint    -> completion allowed
foreign active checkpoint -> completion refused
```

Fix:

```text
e74679fee481898c6d4e9260f4134e2ae563e272
fix: allow atomic completion from idle checkpoint
```

Focused Windows proof:

```text
ZN Work Recovery E2E run 33008119594
head e74679fee481898c6d4e9260f4134e2ae563e272
conclusion success
14/14 tests passed
```

New tests explicitly cover claimed-event completion from idle and fail-closed refusal to erase a foreign active checkpoint. Existing atomic SQL rollback proof remains green.

Ordinary run `33008119464` no longer contained the checkpoint-ownership RuntimeError. Its remaining Kernel errors were the known NetworkService long-path versus DOS-8.3 path family, which remains deferred.

### 2. Side-effect uncertainty is now a resident recovery state

Implementation:

```text
1bcbf410a401755d6037423ea677cb3db1c6217a
feat: recover uncertain append effects from reality
```

Relevant files:

```text
runtime/python/zn_agent/core/side_effect_body.py
runtime/python/zn_agent/core/focused_modern_text_resident.py
tests/zn_agent/core/test_work_side_effect_recovery.py
```

The existing durable pre-dispatch guard remains narrow:

```text
command / terminal / shell
write_text / write_file with append=true
```

`SideEffectAwareBody` still commits a `started` attempt before dispatch and refuses duplicate dispatch while that exact event/action signature remains unresolved.

The attempt ledger stores bounded metadata and a SHA-256 signature only. It does not duplicate raw commands, appended text, environment values, or raw action arguments.

The final resident now intercepts `side_effect_uncertain` before ordinary failure handling and persists:

```text
stage      = side_effect_recovery
blocked_by = outside_world_effect_uncertain
```

Uncertainty does not automatically become `local_failure`, failed-action evidence, negative self-model learning, or ordinary native investigation.

### 3. Interrupted append can now be resolved from current reality

The resident uses only the existing trusted append postcondition path. A recoverable append requires an exact same-target `text_equals` contract. For safe retry, the baseline is accepted only when the goal was resident-derived from a full untruncated preview and the expected final text ends with the exact append suffix.

Recovery first performs read-only `read_text`.

If the exact final text is already present:

```text
attempt -> verified_effect
complete without replay
no causal success learning from the uncertain dispatch
```

If the exact resident-derived pre-dispatch baseline is still present:

```text
attempt -> verified_absent
retry authorized
one fresh append dispatch
normal independent postcondition verification
```

If current state is unreadable, truncated, or divergent:

```text
stage remains side_effect_recovery
decision = user_decision_required
replay remains blocked
```

### 4. Generic command uncertainty remains deliberately blocked

Arbitrary commands usually have no trustworthy read-only verifier. Current behavior is therefore:

```text
decision = user_decision_required
replay_blocked = true
started attempt remains unresolved
```

No second command is run to infer whether the first command ran.

## Real test / CI truth

### Current focused Work recovery

```text
ZN Work Recovery E2E run 33009460955
head 1bcbf410a401755d6037423ea677cb3db1c6217a
runner zn-ci-01 / Windows X64
conclusion success
Ran 18 tests in 8.963s
OK
```

New cases that actually ran and passed:

```text
test_recovery_resolution_closes_only_matching_started_attempt
test_interrupted_append_completes_from_verified_effect_without_replay_or_failure_learning
test_interrupted_derived_append_retries_only_after_exact_baseline_is_reobserved
test_interrupted_generic_command_enters_blocked_recovery_without_replay
```

This proves zero replay when the effect is already present, read-before-retry when the exact baseline is proven, exactly one fresh append after safe retry authorization, and zero command dispatch for unverifiable command uncertainty.

All prior Work restart, atomic terminalization, rollback, anti-replay, and typed Body tests stayed green in the same focused run.

### Ordinary ZN CI on current implementation head

```text
run 33009460950
head 1bcbf410a401755d6037423ea677cb3db1c6217a
Electron / TypeScript / Windows    success
ZN Source Boundary / Windows       success
ZN Kernel / Python / Windows       in progress at latest inspection
```

Do not call ordinary CI green until Kernel actually finishes. If it fails only on the known NetworkService long-path/DOS-8.3 identity defect, keep that separate issue deferred unless it materially blocks current work.

### Prior full-core evidence for atomic fix

`ZN CI` run `33008119464` on `e74679f` showed the new atomic ownership regression was gone. Remaining Kernel errors were the already known path-identity family. This is important: do not confuse that deferred environmental/path identity defect with Work terminalization or side-effect recovery.

## Windows runner topology

```text
headless CI:       [self-hosted, Windows, X64, zn-ci]
interactive proof: [self-hosted, Windows, X64, zn-interactive]
```

Keep the visible foreground `zn-interactive` design. Do not restore hidden launch, auto-logon, credential expansion, or Session-0 interactive claims.

Previously verified real regressions remain:

```text
ZN Windows Interactive Desktop E2E run 33006103742   success, 4/4
ZN Managed Browser E2E             run 33006103702   success, 71 contract + 4 Chromium
```

## Current risks / blockers

- Work reconstruction is verified.
- Atomic event/outcome/idle terminalization is verified with corrected checkpoint ownership.
- Generic command/append blind replay after an uncertain start is blocked.
- Append effect-present and exact-baseline recovery are verified from fresh current reality.
- Uncertainty is no longer treated as ordinary action failure learning.
- Work durability remains **PARTIAL** because generic/unverifiable uncertainty has no explicit user/cancel/recovery command yet.
- `work_progress` exposes `stage`/`next_action` but not a dedicated sanitized `recovery` object yet.
- Life self-observation after durable completion remains a separate consistency concern.
- The Windows NetworkService DOS-8.3 path-identity issue remains known/deferred; partial work was reverted by `db647cb49c3de014aa82bc28ec87c1c4e5b02c15`.
- Browser PRESS/generic click/richer editing/multi-select/lifecycle remain open.
- User Browser Bridge control, M8 continuity, and SM1+ remain incomplete.
- `main` remains untouched.

## Task queue

### P0 - Work recovery projection

Status: **NEXT REAL TARGET**

Expose a stable resident-owned `recovery` object through `ResidentWorkLedger.progress()` / `work_progress`.

Whitelist only bounded fields such as:

```text
status
kind
attempt_id
replay_blocked
verification_kind
decision
reason
bounded verification metadata
```

Never export raw command text, appended text, environment values, or the full action signature.

The UI/control plane should render this truth, not infer it from error strings.

### P1 - explicit recovery / cancellation decision

Status: **OPEN**

Add a resident-owned control path for unverifiable uncertainty. It must be explicit and fail closed. Do not silently turn a blocked command into retryable work, and do not claim an effect happened without evidence.

Cancellation/recovery decisions should be durable and auditable. High-risk/destructive actions remain subject to existing human-approval boundaries.

### P2 - life observation recovery

Status: **OPEN / SEPARATE FROM EVENT TERMINAL TRUTH**

A durable completed event remains completed even if later self-observation requires repair.

### P3 - browser follow-ons

Status: **OPEN / NOT CURRENT MAJOR TARGET**

PRESS, generic click semantics, richer text editing, multi-select, and broader page/target lifecycle remain bounded candidates.

### P4 - deferred Windows DOS-8.3 path identity

Status: **KNOWN / DEFERRED**

Resume only if explicitly reprioritized or materially blocking current product work.

### P5 - M8 / SM1+

Status: **OPEN**

Preserve existing human-approval boundaries for high-risk identity, memory, credentials, updater/signing, and destructive self-maintenance changes.

## Related files

```text
runtime/python/zn_agent/core/store.py
runtime/python/zn_agent/core/work.py
runtime/python/zn_agent/core/side_effect_body.py
runtime/python/zn_agent/core/focused_modern_text_resident.py
runtime/python/zn_agent/core/embodied_resident.py
runtime/python/zn_agent/core/procedural_resident.py
tests/zn_agent/core/test_work_progress.py
tests/zn_agent/core/test_work_recovery.py
tests/zn_agent/core/test_work_side_effect_recovery.py
.github/workflows/zn-work-recovery-e2e.yml
```

## Next real target

Expose sanitized side-effect recovery state through Work progress, then implement explicit resident-owned recovery/cancel decisions for unverifiable effects. Keep `main` untouched.
