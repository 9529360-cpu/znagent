# ZN implementation status

> Architecture contract: [`../ZN.md`](../ZN.md)
>
> Memory/learning architecture: [`ZN-MEMORY-LEARNING.md`](ZN-MEMORY-LEARNING.md)
>
> Next phase: [`ZN-NEXT-PHASE.md`](ZN-NEXT-PHASE.md)
>
> Source adoption boundary: [`ZN-SOURCE-EXTRACTION.md`](ZN-SOURCE-EXTRACTION.md)
>
> Self-maintenance contract: [`ZN-SELF-MAINTENANCE.md`](ZN-SELF-MAINTENANCE.md)
>
> Real code, Git state and CI outrank this ledger.

Development branch: `dev/zn-agent`. Canonical source/release branch: `main`.

## 1. Current checkpoint — 2026-08-25

The active repository remains physically ZN-only. M10 canonical source promotion is complete; `main` is canonical source/release and `dev/zn-agent` is the normal development branch.

Latest verified implementation head before this ledger sync:

```text
head  a32c0f0dfd34e47371530e0ded2368401d3a8efb
run   32854445588

ZN Kernel / Python / Windows        success
ZN Source Boundary / Windows        success
Electron / TypeScript / Windows     success
Publish Windows CI statuses         success
```

The Windows kernel job created a fresh isolated Python 3.12.13 environment, installed the formal `znagent` runtime from `runtime/python`, booted ZN without a model, compiled the resident core, and ran the complete working-tree suite: **402 tests passed with 5 platform-appropriate skips**.

This checkpoint adds the first verified typed pointer click lifecycle on top of the already-verified pointer movement and resident-owned target-local visual region sense. The click slice is intentionally narrow: one explicit left click can complete only the explicit `visual_region_changed` effect after a fresh pre-click baseline and a fresh post-click observation. Input delivery success alone is not completion proof, interrupted started clicks are not blindly replayed, and broader UI/business semantics are still not proven by local visual change.

## 2. Resident ownership — VERIFIED

The resident owns persistent Self/life state, Situation/Thought/Will, durable WorkingState, Investigation, native Body actions and senses, bounded cognition resources, provider settings, nervous memory/reconsolidation, verified experience/procedural tendencies, channel lifecycle and resident work/progress state.

Zero-model boot remains a hard CI contract and passed at exact head `a32c0f0dfd34e47371530e0ded2368401d3a8efb`.

The active resident builder constructs `VerifiedPointerClickResidentRuntime`, which extends the existing repository-verifying resident chain rather than replacing or bypassing it.

## 3. Engineering competence — VERIFIED NARROW SLICES

Current resident-owned engineering behavior includes structured Git state/diff evidence, bounded file/process/terminal/PTTY actions, exact text and command postcondition verification, tracked pre/post Git proof, evidence-bound anti-replay, current-reality-gated alternatives, bounded staging choices, targeted unittest verification and restart-safe side-effect verification.

The current Windows PowerShell kernel verifier contract is recognized strictly and fails closed on shell/runtime/PYTHONPATH/test-suite drift.

Repository-owned non-canonical verifier selection is bounded by `.agent/zn-engineering-verifiers.json`. The manifest may declare only literal `target` + `test` relations. It cannot declare command, shell, workdir, timeout or model/task-prose authority. Runtime selection still requires tracked/clean same-HEAD evidence, safe paths, a direct top-level import relation, a discoverable unittest case, the current CI suite contract, execution anti-replay and fresh post-action verification.

Current real manifest relations:

```text
runtime/python/zn_agent/core/repo_test_semantics.py
→ tests/zn_agent/core/test_repo_test_semantics_authority.py

runtime/python/zn_agent/core/git_semantics.py
→ tests/zn_agent/core/test_git_staging_semantics.py

runtime/python/zn_agent/core/result_semantics.py
→ tests/zn_agent/core/test_verified_experience.py
```

Run `32829830325` verified all three relations; later exact-head runs keep the contract green. Do not expand the manifest merely for count.

## 4. Memory and learning — VERIFIED FOUNDATION, MATURITY PARTIAL

Persistent traces, associations, schema formation, fading/pruning, prediction error, reconsolidation, independently verified episodic evidence and bounded procedural tendencies exist.

General procedural competence, mature computer use, broad local training and long-horizon growth benchmarks remain partial.

## 5. Body / Senses / computer interaction — VERIFIED FOUNDATION, MATURITY PARTIAL

Resident-owned background vision is a verified foundation: `ResidentSocketService` owns a persistent `NativeVisualSense`; default capture uses local Pillow `ImageGrab`; raw pixels are discarded inside capture; only compact frame/coarse-region/luminance structure enters the resident nervous system. The formal runtime declares and installs `Pillow==12.3.0`.

### Verified pointer movement

```text
structured event authority
→ NativeActionIntent(kind="pointer_move")
→ resident-owned NativeBody
→ Windows primary-screen pointer movement
→ persist movement result
→ separate native_verification stage
→ fresh pointer_state observation
→ complete only if current cursor position matches the expected bounded position
→ contradiction returns to Investigation and records negative evidence
```

Properties:

- typed `pointer_move` only;
- finite normalized primary-screen coordinates in `[0, 1]`;
- no coordinate inference from model prose, ordinary task text or procedural memory;
- movement API success is not completion proof;
- fresh cursor position is independently observed after the action;
- drift or contradictory observation fails verification and returns to Investigation.

Run `32844167956` verified this lifecycle with 393 passing core tests.

### Verified local visual region sense

`NativeVisualRegionSense` is owned by `ResidentSocketService` alongside the persistent retina. It is deliberately on-demand and read-only:

```text
ResidentSocketService
→ NativeVisualRegionSense
→ explicit bounded normalized region
→ lazy Pillow ImageGrab capture
→ crop target-local region
→ local grayscale / quantized derivative
→ compact signature + luminance + pixel bounds
→ raw pixels closed and discarded
→ VisualRegionObservation
```

Properties:

- service construction does not capture the screen; `ImageGrab` is lazy and runs only on `probe()`;
- center coordinates must be finite normalized `[0, 1]` values;
- probe width/height are bounded to `0.01..0.50` of the primary screen;
- returned evidence is a compact local signature, mean luminance, pixel bounds and capture metadata;
- raw frame persistence is explicitly rejected;
- probing does not write persistent retina state, create nervous traces, change background visual sampling rhythm, or call a model;
- the probe is a Sense, not action authority and not another agent.

Run `32847172662` verified this foundation with **397 tests passed / 5 skipped**. Tests use injected region probes; they do not claim real interactive-desktop screenshot E2E on the CI host.

### Verified narrow pointer click lifecycle

The active call chain is:

```text
provider_bridge.build_resident_runtime()
→ VerifiedPointerClickResidentRuntime
→ explicit NativeActionIntent(kind="pointer_click")
→ require explicit expected_outcome.kind="visual_region_changed"
→ move pointer to explicit normalized target
→ fresh pointer_state verifies target
→ persist prepared click state
→ fresh target-local visual baseline
→ persist execution-start marker BEFORE input
→ NativeBody.act("pointer_click")
→ exactly one left click only if pointer is still at target
→ native_verification
→ fresh target-local visual probe
→ changed signature: complete only the narrow visual_region_changed effect
→ unchanged/unavailable: contradiction → Investigation
```

Properties:

- only one explicit left click is supported; no right click, double click, drag, keyboard or generic browser agent;
- `NativeBody.pointer_click` never moves the pointer implicitly;
- the resident re-checks cursor position after preparation and before baseline/input;
- a durable `started` marker is written before click delivery; restart with an unresolved started marker refuses blind replay because delivery is unknowable;
- click input API success does not complete the event;
- a fresh local baseline is persisted before input and a fresh local observation is captured after input;
- an unchanged local region contradicts completion and returns to Investigation;
- missing resident-owned visual region Sense or missing/invalid `visual_region_changed` postcondition fails before input;
- local visual change proves only the explicitly typed local effect. It does **not** prove a broader application/business/world semantic result.

Key implementation commits:

```text
44ecb72d4c58f2c75a8e5c5d65d1820e64ceeed4  feat: add verified pointer click lifecycle
e2ab7600cafd18ca0956932af43fe6ae83f82449  refactor: minimize pointer body diff
a32c0f0dfd34e47371530e0ded2368401d3a8efb  test: align click success assertion with terminal lifecycle
```

Exact-head run `32854445588` verified the implementation with **402 tests passed / 5 skipped**, including:

```text
test_pointer_click_body_never_moves_implicitly
test_click_waits_for_position_baseline_and_fresh_effect_verification
test_interrupted_started_click_is_not_replayed
test_unchanged_local_region_contradicts_click_completion
test_click_without_narrow_visual_postcondition_fails_before_input
```

The prior implementation-head run `32853366923` correctly failed one new test because that test attempted to read cleared WorkingState after terminal completion. Product click behavior and the other four new click tests passed in that run. The test lifecycle assertion was corrected at `a32c0f0...`, then the complete exact-head suite passed.

## 6. External cognition, web/world and channels — VERIFIED FOUNDATION

Supported model providers are bounded ZN-owned cognitive resources. Provider replacement does not replace resident identity, store or life state.

ZN owns URL/network safety and web resource boundaries. Channel lifecycle is resident-owned.

## 7. Desktop ownership — VERIFIED

Active desktop path:

```text
ZN Electron main
→ ZN preload / IPC
→ long-lived resident RPC
→ ZN renderer
```

Ownership tests protect window/protocol lifecycle, preload surface, `zn://` deep links, resident-backed work/provider/progress surfaces, packaged runtime identity, update/application gates and the single formal builder configuration.

Electron development/runtime tooling remains pinned to `41.10.5`. Run `32854445588` passed locked install, high-severity npm audit, typecheck, bundle, desktop ownership/runtime/update tests and release/runtime artifact verifier tests.

## 8. Runtime and artifact ownership — VERIFIED FOR EXERCISED TARGETS

Runtime identity:

```text
Python distribution: znagent
Python package:      zn_agent
entrypoint:          zn-resident
```

The runtime project explicitly owns `Pillow==12.3.0` for resident visual capture. Run `32854445588` resolved and installed 29 runtime packages in a fresh isolated Windows Python 3.12.13 environment before zero-model boot and the full suite.

Historical artifact evidence includes Linux packages, Windows installers, macOS artifacts, fresh Ubuntu installation and installed Linux resident lifecycle evidence. Current steady-state development verification is Windows x64.

## 9. Release/update state — M8 PARTIAL

ZN owns release/update automation. Verified foundations include versioned runtime staging, immutable runtime identity metadata, package verification, channel preparation, `stable.json` last-write ordering and resident update gates.

Still open for the current Windows x64 M8 target:

1. clean Windows install/login evidence;
2. installed Windows N→N+1 continuity evidence;
3. rollback validation across a real Windows version transition;
4. applicable secure Windows signing evidence.

M8 must not be reported complete until those items are exercised. M10 canonical source promotion does not change this status.

## 10. Repository source boundary — COMPLETE AND CI-ENFORCED

Status: **COMPLETE**.

`.agent/verify_zn_source_boundary.py` scans tracked paths and tracked non-binary text to reject retired product identifiers, package namespaces and old physical paths from the active tree. `LICENSE` text is the only explicit scan exception because original legal attribution must remain verbatim.

The historical source quarry remains outside the active tree in the dedicated reference branch/Git history and is not an active runtime/build/test/package/release dependency. Run `32854445588` passed the current Windows source-boundary job.

## 11. Dependency security state — HIGH-SEVERITY DEBT CLOSED

Electron is on the patched `41.10.5` line. The old `extract-zip` chain is absent from the active Electron dependency path and steady-state CI uses locked install plus `npm audit --audit-level=high`.

The Windows workflow still reports Node-action runtime deprecation warnings for actions that target Node 20 while GitHub forces Node 24. This is non-blocking tooling maintenance debt and should be changed only through stable, verified action upgrades.

## 12. Self-maintenance — SM0 COMPLETE, SM1+ OPEN

Architecture is defined in `ZN-SELF-MAINTENANCE.md`. ZN does not yet autonomously own the full detect → investigate → isolated fix → PR → CI → merge → release workflow.

High-risk identity/memory/credential/updater/rollback/signing/self-approval changes remain human-approved by default.

## 13. M10 status — COMPLETE

The 2026-08-24 M10 review passed and canonical source promotion was executed by non-forced fast-forward with no history rewrite.

`main` is canonical source/release; `dev/zn-agent` remains the normal development branch. Canonical promotion did not declare M8 complete.

## 14. Current known debts

- a stronger semantic/current-world verifier that can prove a requested UI/application/world outcome when mere local visual change is insufficient;
- an explicit binding between higher-level task semantics and the narrow effect contract, so `visual_region_changed` cannot be mistaken for proof of a broader goal;
- real-session screen-capture and interactive-desktop availability evidence;
- broader computer-use primitives remain intentionally absent until their authority and verification contracts are proven;
- M8 Windows clean-install/login, installed N→N+1, rollback and signing evidence;
- mature procedural competence/growth benchmarks;
- SM1+ autonomous self-maintenance;
- Node-action/deprecation warnings and other non-security third-party tooling warnings.

## 15. Next real targets

```text
1. keep automatic Windows x64 self-hosted CI green on each exact dev HEAD
2. synchronize STATUS/HANDOFF after the verified click slice without changing main
3. strengthen semantic/current-world verification before expanding click/browser authority
4. bind any higher-level task completion claim to evidence stronger than local visual change
5. add real interactive-desktop/screen availability evidence when an appropriate environment is available
6. close Windows M8 clean-install / N→N+1 / rollback / signing evidence
7. advance SM1+ behind existing approval and verification boundaries
```

Do not modify `main` through ordinary development. Any later status change must be reflected here only after real code/Git/CI evidence exists.
