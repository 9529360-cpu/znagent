# ZN Implementation Status

This is a current architecture/status snapshot. Real code, Git state and contract/integration evidence are authoritative.

## Product control plane

ZN has one product control plane:

- one Resident lineage;
- one durable Work/Root completion truth;
- one action-authority system;
- one Body/effect boundary;
- one replay/recovery discipline;
- one completion decision owned by ZN.

External model or tool success is evidence only.

## Capability status

| Capability | Current state | Boundary |
| --- | --- | --- |
| Durable Work / Root completion | CONNECTED | Root status is ZN-owned; child/tool success cannot independently complete the Root |
| Side-effect journaling / no-blind-replay | CONNECTED | replay-sensitive effects preserve durable dispatch identity and fail closed when outcome is uncertain |
| Work recovery / continuation | CONNECTED + VERIFIED NARROW | durable plan/progress/recovery are reusable; broader long-horizon UX remains open |
| Browser semantic grounding | CONNECTED + VERIFIED NARROW | provider-neutral fresh semantic actions (checkbox/textbox/button/combobox targets) pin page URL, re-resolve stale targets only after explicit pre-dispatch proof, and never replay dispatched/uncertain effects |
| Windows application awareness | CONNECTED | installed-app/process/window identity and bounded activation use fresh machine evidence |
| Windows interactive actions | CONNECTED + VERIFIED NARROW | pointer/keyboard/UIA movements remain Body-owned and authority-gated |
| Atomic file overwrite | CONNECTED + VERIFIED | staged write, identity checks, durable attempt tracking and recovery contracts |
| Document/presentation primitives | CONNECTED + PARTIAL | generic document/presentation behaviors remain; scenario-owned document completion paths were retired |
| Spreadsheet primitives | CONNECTED + PARTIAL | generic workbook operations remain; no task-specific browser-to-sheet product route owns the architecture |
| Public research primitives | CONNECTED + PARTIAL | search/extract/evidence mechanisms remain; no dedicated representative-task completion path owns the product |
| Delegated Work / routing | CONNECTED + PARTIAL | generic routing, progress, health and authority remain; fixed story phase orchestration was retired |
| Memory / learned behavior | CONNECTED + VERIFIED NARROW | saved facts, explicit response preferences and same-Work conversation compose in bounded product cognition; automatic personal-memory writing, semantic search and arbitrary workflow learning remain open |
| Packaging / clean install | CONNECTED | packaged runtime and clean-install verification remain release boundaries |

## Saved memory in ordinary conversation

The active product path is Work route-policy binding -> anchored same-Work conversation -> `StructuredMemory.bind_cognition_context` -> existing CognitionRequest / Kernel / cognitive adapter. The existing `facts` table and `remember` / `forget` RPC remain the owners; no second memory database, identity migration or external agent runtime is introduced.

Saved keys and explicit aliases are matched conservatively, with Unicode normalization, most-specific-cue ranking and stable tie-breaking. Values are never searched for cues. A directly named topic takes precedence; otherwise the last two user messages from the existing bounded Work transcript may supply reference cues. Assistant claims, tools and other threads do not supply these cues. Records carry their saved key, update timestamp and match provenance; they are data, not execution authority or completion evidence.

Explicitly saved response language, style and verbosity are bounded default preferences. Examples of existing fact keys are `response language`, `response style`, `response verbosity`, and their supported Chinese reply-language/style equivalents. Values must be nonempty strings no longer than 200 characters. Other preferences require relevant cues; permission, credential and route-policy fields are not ambient preferences. Current user instructions take precedence over defaults. Saving/inference of preferences from arbitrary chat is not implemented by this projection.

The projection selects at most five facts, preserves whole values rather than generating lossy summaries, and caps the actual nested UTF-8 context at 8 KiB. Opt-out (`allow_memory` not exactly true when explicitly supplied) and explicit isolated cognition questions exclude both saved memory and conversation. New requests read current SQLite values without a projection cache; updates and deletions survive reconstruction. An already prepared durable cognition request remains its original snapshot across restart. Forgetting a fact does not erase earlier transcript disclosures or already prepared request snapshots.

Narrow executed evidence in `test_memory_conversation_product.py` exercises the real Product Resident, Work/RPC, Kernel, SQLite and cognitive adapter, including authenticated TCP disconnect/reconnect, two resident lifetimes, follow-up reference retrieval, update/forget, policy/isolation and pre-dispatch continuation without duplicated messages/calls. Provider responses are controlled test boundaries, not live-model quality evidence. Full installed daily-use acceptance and unified knowledge-graph/semantic retrieval remain open.

## Session log is the source of truth for model-visible context (DSH-1)

Every model request ZN sends is rebuildable from the append-only session event log alone (`session_log.py`, durable `session_events` table in `KernelStore`; inserts only, no update/delete path). Each resource logs the exact post-egress-redaction provider request body *before* sending (`model_request_sent`), then the response (`model_response`) or failure (`model_request_failed`, exception type only). The kernel worker additionally logs `model_request_planned` with correlation ids plus only lengths and hashes of the pre-redaction question/context. `rebuild_model_request(log, request_id)` returns the exact sent request plus its paired response/failure; it raises `KeyError` for an unlogged request instead of guessing from live state.

Never logged: pre-redaction text, credentials (API keys travel outside the logged body), image bytes (images are referenced by SHA-256 + MIME + size), and model thinking/reasoning blocks. Logging failures never break cognition. Covered send paths: OpenAI-compatible, Anthropic single-turn, Gemini text + image, Anthropic tool-loop turns, and direct `invoke` callers (e.g. specialist debug) via the same resource-level sink. Evidence: `test_session_log_source_of_truth.py` (14 tests), including a kernel end-to-end rebuild of the assembled kernel context.

## Team task state machine (DSH-2): revision CAS + tombstones + advisory writeScopes

Team tasks live in `team_task_state.py` (`TeamTaskStateStore` + immutable `TaskSnapshot`). It adds what the existing pieces lack: `WorkItem` has only a thread-level `plan_version` and overwrites unconditionally (last writer wins); AF-3 `ProgressLedger` tracks status transitions in memory but has no revision, no delete, no full-snapshot shape, and no write scopes; disband hard-deletes team records.

- Full snapshots: `TaskSnapshot.to_dict` / `from_dict` round-trip every field (status, assignee, dependencies, acceptance criteria, writeScopes, revision, history, tombstone fields). The caller owns durability (export/import); the store only enforces the state machine.
- Revision CAS: every successful write bumps `revision` by exactly 1. `update_task` requires `expected_revision`; a mismatch raises `RevisionConflictError` and changes nothing (re-read and retry). No-op writes consume no revision.
- Tombstones: `delete_task` never erases a row -- it sets `deleted=True` + `deleted_at` + `deleted_reason`, keeps the last status and full history, and bumps the revision. Tombstones are excluded from `list_tasks` by default, stay queryable via `get_task(..., include_deleted=True)` / `get_tombstone` / `list_tombstones`, and refuse further updates. There is deliberately no hard-delete API.
- Advisory writeScopes: per-task suggested relative path prefixes. `check_write_scope` only advises -- an out-of-scope path returns a warning advisory and is recorded in the advisory log; it never raises, never blocks, and never replaces the hard file isolation (`workspace_file_discipline`), which stays the only enforcement. Empty scopes mean unrestricted.
- Status vocabulary is shared with AF-3 (`todo` / `in_progress` / `done` / `failed`, same transition rules; `done` is terminal). `mirror_decision` mirrors coordinator dispatch/complete into task state via read-then-CAS as an observer that never raises. The module does not touch `CheckpointStorage`, LG-1 two-phase writes, the Work ledger, daemon, or approval gates.

Evidence: `test_team_task_state.py` (16 tests), including a two-reader lost-update rejection, tombstone retention + refusal, and advisory-not-blocking checks.

## Checkpoint fail-closed + unknown results (DSH-3)

Pulse-boundary checkpoints (`team_runner.py`, `team_work_owner.py`) fail closed. `TeamRunner.save_checkpoint` / `TeamWorkOwner.save_interrupt_checkpoint` raise `CheckpointSaveError` (a `RuntimeError`) when storage is wired and the write fails -- the pulse was not durably recorded, and the caller must not proceed as if it were; they still return `None` only when no storage is wired. `latest_checkpoint` / `pending_step_ids` raise `CheckpointLoadError` on a load failure instead of returning `None`: a failed load must never masquerade as "no checkpoint", which would mark every step pending and re-run completed work. The resident already fails an event closed on `RuntimeError` from `advance()`, so a checkpoint failure surfaces as an explicit terminal failure.

Interrupted tool calls resume as unknown, never retried. The detector is durable, not heuristic: the runner records the termination pulse count at pulse START and the checkpoint at pulse END, so a latest checkpoint older than the termination pulses (or no checkpoint while a pulse already started) proves the previous pulse died mid-flight. On the recovery pulse, `TeamRunner.step()` reconciles first -- before the pulse counter moves -- and every pending step with a live, unclaimed `WorkerRun` gets `outcome_uncertain=True` stamped into the run's metrics and its step id recorded in the checkpoint's `uncertain_step_ids` (carried forward until the step completes; completion implies the CP-3 verdict verified the outcome). The steps are not re-dispatched: the coordinator already waits on a live run, and the recovery result carries `uncertain_step_ids` through `TeamStepResult` / `TeamOwnerStep`. No new retry path exists; the kernel's `_checkpoint_uncertain_dispatch` and the LG-1 native-completion rebuild keep their own unknown-result handling untouched.

Evidence: `test_dsh3_checkpoint_failclosed.py` (12 tests), including save/load failure raising, step() propagating a save failure, interrupted-pulse marking with no second dispatch, first-pulse crash, and uncertainty clearing on completion.

## Tiered repeat reminders (DSH-4): advisory nudges, never a gate

When a specialist repeats the *same tool call* -- same tool, same parameters -- the resident injects a graded reminder into the next cognition question: a short reminder at 3 consecutive repeats, a detailed reminder naming the tool and its parameters at 5 and at 8. The reminder is advice, not enforcement: it never blocks, rejects, escalates, or changes execution, and the run continues exactly as it would without it.

Complement to #493 (hard rewrite-loop escalation), not a second copy. #493 counts *verified evidence* -- identical (objective, path, content) twice or the same (objective, path) four times -- and escalates. DSH-4 (`repeat_reminder.py`) counts *dispatched tool calls* -- (tool, params) with no objective in the identity -- so it also catches repeats #493 cannot see (the same call re-proposed under a different objective, or a run_python call with identical args), and it nudges *before* the hard escalation fires instead of replacing it. The observation point is `_begin_team_step` (one dispatched step = one tool call; a rejected proposal was never called and is not counted). Identity is exact matching over a canonical form: parameters are normalized with deep-sorted keys and serialized deterministically before hashing, so key order never changes the identity and any value difference is a different call. A new user message (`work_message_id` change) or a new run clears the count.

Known boundary (pre-existing, verified on clean main, not introduced here): the full loop cannot drive many identical repeats through the Body -- an identical run_python re-dispatch blocks in side-effect recovery, and a 5th identical write_file dispatch crashes the restore-point layer on intent_id. Those generic-layer guards cap how far identical repeats can go in practice; DSH-4 does not touch them.

Evidence: `test_repeat_reminder.py` (10 tests: key-order invariance, reminders exactly at 3/5/8 with the detailed form naming tool + params, consecutive-reset, new-message / new-run reset) + `test_team_feedback_loop.py` (loop wiring: the 3rd identical dispatch injects the short reminder into the next question and the loop keeps asking; resident-wiring: 5/8 detailed reminders through the real observe hook + reset).

## Continuable sub-agent delegations (DSH-7): delegate / append / interrupt / resume

A delegation is the supervisor's continuable handle on one specialist working one plan item (`supervisor -> one specialist -> one plan item -> one live run`). It is not a second control plane: the runner still dispatches, the resident still executes steps, and completion is still decided only by the claim / verification path. Four transitions, all supervisor-only owner APIs with deliberately NO tool spec -- a sub-agent cannot append to, pause, or resume any delegation (including its own):

- **Delegate** names the current holder of a plan item. It never reassigns (reassignment is AF-4 handoff's job) and never completes (only claim / verification completes).
- **Append** queues an adjacent message (supplement / course-correct) for a running delegation. The owner delivers it into the sub-agent's NEXT cognition question exactly once, then marks it delivered in team shared memory.
- **Interrupt** pauses a delegation: the coordinator answers "wait" for its item (never dispatch / verify / complete / escalate while paused) and the resident sends it no cognition. The live run is kept with its evidence; the item is not failed. A Body action dispatched before the pause may still land once -- pause stops new work, it does not drop an in-flight completion.
- **Resume** unpauses it: the SAME live run continues with its existing evidence, never a fresh dispatch from scratch. An optional resume value rides along as one more cognition input, delivered once.

Permission boundary (structural, not prompt-only): appended messages are delivered as quoted supervisor *context* under a non-authority guard -- they never change tools, permissions, or approval state, never approve anything, and any destructive step still needs its normal approval. The delegation record holds messages + pause state only; no approval / authority fields exist for a message to flip. The delegation is per-item: after an AF-4 handoff the record follows the new holder, and pending messages belong to the item's work.

Persistence: delegation records live in team shared memory (the same durable store as the AF-4 handoff log and the LG-2 interrupt record); no new persistence mechanism. Pause / resume are journaled (kind `delegation`); appends are not journaled (their durable record is the audit trail).

Evidence: `test_subagent_delegation.py` (16 tests: pure state machine incl. cap / double-pause / resume-without-pause / completed-wins-over-paused; owner validation incl. delegate-must-name-current-holder; advance-level exactly-once delivery of messages and resume values; pause-before-dispatch suppresses dispatch; pause freezes the live run and resume continues the same run id; coordinator pause gate incl. deferred verification of a landed claim; full resident loop: Q2 carries the appended message with the guard, paused pulses make zero cognition calls and keep the same run, Q3 carries the resume value without repeating the message, and the resumed run executes to disk).

Known boundary: delivery marking happens in the same owner step that attaches input to the live context (the same commit-point semantics as the LG-2 resume-value pop). A crash before that owner step leaves everything pending for the next pulse; nothing is marked delivered without being attached.

## Spec-first workflow (W-3): no approved spec, no implementation work

Every feature starts with a spec directory `specs/<slug>/` holding `PRODUCT.md` + `TECH.md` (`spec_first.py`; templates via `render_spec_templates`). Two label gates control the two kinds of "starting work":

- **Gate 1 `ready-to-spec`** -- starting to *write* the spec (`can_start_spec` against the labels on the feature request / assignment). A `ready-to-implement` label alone does not authorize spec-writing.
- **Gate 2 `ready-to-implement`** -- starting *implementation* (`check_implementation_gate`): both spec files present, every required section filled (PRODUCT: 背景/目标/范围/非目标/验收；TECH: 方案/改动点/验收/风险；a section whose body is only the `【待填写】` placeholder or shorter than 20 chars is incomplete), and the `ready-to-implement` label in TECH.md's `<!-- SPEC LABELS: ... -->` marker. The label lives in the spec file itself, so fixing the spec unblocks the team on the next pulse with no resume ceremony.

Wiring (built on existing interfaces, no parallel flow): the resident checks the spec gate in the dispatch path after the Plan Mode gate and before `owner.advance` -- a spec precedes even the plan, and with Plan Mode also on, a missing spec blocks before any plan proposal is made. A blocked gate produces a gap-shaped dict (`missing` / `needed` / `impact`, same shape as P2b `gap_report`) mirrored in working state under `team_spec_gate` and surfaced in the blocked `next_action`. It is deliberately NOT recorded as an LG-2 interrupt: an interrupt needs an explicit resume value to clear, but a spec gate must self-heal the moment the spec files on disk are fixed. When the gate passes, a compact spec summary (goal + approach) rides into the specialist's question next to Plan Mode's `plan_text`, with "do not modify the spec files" and "report a gap instead of inventing scope".

Boundary: the natural-language "assemble a team" path never invents a `spec_slug` -- the assigner binds the work to a spec via `team_request["spec_slug"]`. No slug means the gate is not consulted (legacy flows unchanged).

Evidence: `test_spec_first.py` (24 tests: templates, both gates, gap shape, disk loader incl. hostile slugs, and four resident-loop tests -- missing spec blocks with zero specialist calls and nothing written; approved spec unblocks with the spec summary in the specialist's question; fixing the spec on disk unblocks without resume; spec gate runs before Plan Mode; legacy no-slug flow unaffected).

## Recently retired scenario-owned surfaces

The cleanup removes product code whose primary owner was a narrow representative task rather than a reusable capability contract, including:

- current-app cleanup story modules;
- local-service repair story modules;
- long-running terminal story behavior;
- local Office representative behavior;
- document-research-completion story behavior;
- managed-reference browser research story runtime;
- browser-result-to-file story route;
- fixed delegated-worker story orchestration;
- File-to-Desktop composite goal / semantic grounding route;
- task-specific desktop modal sensing/recovery stack;
- payment-date-specific DOCX inspection and mutation path.

Their removal does not revoke the generic Work, Body, authority, browser, file, research, Office, delegation or recovery mechanisms they previously composed.

## CI shape

Automatic gates are contract-first and use contract-named workflows. Real-system capability checks live under `tests/zn_agent/integration`; ordinary deterministic/unit contracts remain under `tests/zn_agent/core`.

The repository policy test prevents retired scenario namespaces and numbered story identifiers from becoming active architecture again.

## Current major gaps

2. Generic semantic fresh-re-ground currently covers exact named text/button/combobox action paths; arbitrary web interaction remains open.

Browser expansion now proceeds from the cleaned capability-owned substrate rather than from retired representative-task stories.
