from __future__ import annotations

from pathlib import Path

MARKER = "<!-- memory-learned-behavior-1.0-closure -->"

SECTIONS = {
    "docs/ZN-REAL-TASK-E2E-CATALOG.md": r'''

<!-- memory-learned-behavior-1.0-closure -->
## 2026-09-10 — E2E-37 / E2E-38 / E2E-39 — Memory & Learned Behavior 1.0

Status: **CLOSED representative path / VERIFIED NARROW**.

The closed representative task family is deterministic single-path Git staging through the normal active Resident. This is not a synthetic learning action and it does not claim arbitrary workflow learning.

- **E2E-37 — Reuse a preferred way of working:** two different repositories build the same mature Git procedure independently. A new natural-language request equivalent to “use the way I used before on this project” performs fresh current path/Git sensing, retrieves only a bounded currently-applicable prior context, preserves bounded verified-experience/event provenance, excludes the other project, and then executes through the ordinary Body + postcondition lifecycle. With two real historical projects but no current project/target identity, history is not allowed to invent a target or mutation arguments and the request fails closed.
- **E2E-38 — Learn from repeated verified workflow:** four distinct independently verified events mature the existing candidate tendency to `practiced`. On a new event, new file and new current target state, the active Resident uses current Investigation to re-form legal action intents, then a practiced/currently-applicable competence skips one redundant `native_deliberation` pulse. Fresh `inspect_path`, pre-action `git_state`, Body mutation, post-action `git_state` and independent `VerifiedExperience` verification remain. After Resident restart with external models unavailable, the bounded learned mechanical competence still works.
- **E2E-39 — Learned path invalidated by reality:** a missing current target blocks learned command dispatch before action. For post-action drift, the real Git mutation occurs and the index is changed before the independent verification pulse; the Resident records contradiction/prediction error, revokes the event-local learned route and returns to Investigation. Two recent contradictions persistently inhibit the competence across restart. One later success is insufficient to restore `practiced`; repeated new independently verified evidence can gradually relearn it.

Measured learning assertion for the representative family:

```text
cold/unfamiliar: >= 1 resident deliberate pulse
practiced/familiar: fewer deliberate pulses

both paths:
current inspect_path retained
current git_state retained
Body mutation retained
fresh postcondition git_state retained
independent verification retained
```

The dedicated CI gate is `.github/workflows/memory-learned-behavior-e2e.yml`; canonical `ZN CI` continues to gate the full core suite and existing source/desktop boundaries.

Explicit non-claims: this does not close general memory, arbitrary multi-step workflow learning, cross-device memory, automatic executable skill generation, or universal provider-free operation.
''',
    "docs/ZN-PRODUCT-CAPABILITY-MAP.md": r'''

<!-- memory-learned-behavior-1.0-closure -->
## Memory & Learned Behavior 1.0 — representative capability closure (2026-09-10)

Status: **VERIFIED NARROW / representative path closed**.

The active product Resident now has one bounded resident-owned procedural fast path on top of the existing `VerifiedExperience -> CandidateProceduralTendency -> reality-gated influence` chain. The representative family is single-path Git staging because the repository already provides deterministic current Sense, replay-sensitive Body execution and independent Git postcondition verification for it.

What is product-real now:

- project/workspace-local procedural candidates use the existing privacy-safe workdir fingerprint in their compatibility identity, so equally-shaped history from another repository cannot mature or select the current project's competence;
- natural prior-style requests can surface bounded currently-applicable verified context with event/experience provenance rather than dumping memory/transcripts;
- only `practiced` competence (four or more distinct verified events and reliability at least 0.80 under the existing deterministic maturity rules) may remove one redundant native deliberation pulse;
- current event authority and fresh Investigation still supply the real target, workdir and action arguments; history supplies no credentials, private contents, raw command payloads or stale target identity;
- SideEffect/anti-replay, Body execution and fresh independent postcondition verification are unchanged;
- current mismatch blocks the fast path; prediction error records contradiction, returns to Investigation and repeated recent contradictions can persistently inhibit the competence;
- durable verified evidence survives Resident restart, and the already-learned bounded mechanical path remains usable with external models unavailable.

This closes E2E-37/38/39 only as a representative product slice. It is not a claim that arbitrary workflows are learnable or that Memory as a whole is complete.
''',
    "docs/ZN-IMPLEMENTATION-STATUS.md": r'''

<!-- memory-learned-behavior-1.0-closure -->
## 2026-09-10 — Memory & Learned Behavior 1.0

Status: **VERIFIED NARROW / representative path closed** for E2E-37, E2E-38 and E2E-39.

Implementation facts:

- active construction in `runtime/python/zn_agent/core/provider_bridge.py` now composes `MemoryLearnedBehaviorResidentRuntime` over the existing current Resident inheritance chain;
- `runtime/python/zn_agent/core/learned_behavior_resident.py` adds bounded provenance-bearing prior working context and one L4 fast-path policy; it does not add a second planner, memory database, action registry, capability registry or skill executor;
- `runtime/python/zn_agent/core/procedural_tendency.py` now includes the already-privacy-safe `workdir_fingerprint` in compatibility identity when present, separating same-procedure competence between projects while still allowing different targets inside one project to reinforce each other;
- the maturity threshold remains deterministic and existing: one success cannot create a candidate, two distinct supports form `candidate`, three can become `supported`, and four distinct supports with reliability >= 0.80 can become `practiced`; model-only text and unverified actions still have no positive learning authority;
- the representative L4 path may skip one `native_deliberation` pulse only after current Investigation has already formed current safe intents and existing applicability checks select a `practiced` tendency;
- existing current Sense, user/event authority, Body arguments, side-effect attempt ownership, anti-replay and independent postcondition verification remain authoritative;
- existing durable contradicted `VerifiedExperience` aggregation supplies L5 downgrade/inhibition/relearning: repeated contradiction can inhibit, restart preserves it, and later verified events must rebuild reliability rather than one success immediately restoring maturity.

Acceptance coverage:

- `tests/zn_agent/core/test_learned_behavior_resident.py`
- `tests/zn_agent/core/test_project_scoped_procedural_learning.py`
- `tests/zn_agent/e2e/test_e2e37_preferred_working_style.py`
- `tests/zn_agent/e2e/test_e2e38_learned_verified_workflow.py`
- `tests/zn_agent/e2e/test_e2e39_learned_path_drift.py`
- `.github/workflows/memory-learned-behavior-e2e.yml`

No destructive `StructuredMemory` or identity migration was required. Provenance for this trust-bearing slice comes from the existing durable verified-experience store; `StructuredMemory` is not upgraded into an action-authority source.

Explicit remaining boundary: no general multi-step procedure engine, general personal memory UI, cross-device memory, arbitrary skill code generation, or universal provider-independent open-ended reasoning is claimed.
''',
    "docs/ZN-MEMORY-LEARNING.md": r'''

<!-- memory-learned-behavior-1.0-closure -->
## 16. Implementation closure note — Memory & Learned Behavior 1.0 (2026-09-10)

Earlier sections intentionally describe L4/L5 and procedural memory prospectively. The current implementation now closes one representative product slice and should be read with this narrower status update:

**Status: VERIFIED NARROW / representative path closed.**

The path is deliberately built by extending, not replacing, the existing layers:

```text
fresh current event + Investigation
→ privacy-safe current project/workdir fingerprint
→ bounded VerifiedExperience retrieval
→ CandidateProceduralTendency maturity
→ existing current applicability gate
→ practiced resident-owned procedure preference
→ skip one redundant native deliberation pulse
→ ordinary Body / authority / anti-replay lifecycle
→ fresh independent postcondition observation
→ verified or contradicted experience
→ maturity strengthens, degrades, inhibits or relearns
```

For the representative Git staging family, repeated distinct verified events can therefore make ZN measurably less deliberative without making it less grounded. The learned record answers “which familiar current-safe procedure is preferred”; it never answers “what target currently exists”, never supplies current sensitive values and never grants mutation authority.

Project specificity is part of the learning identity: when a verified episode has a workdir fingerprint, procedural aggregation includes that privacy-safe fingerprint in its compatibility key. This prevents same-shaped verified work from another repository from becoming evidence for the current repository while still allowing multiple target files in the same repository to reinforce one competence.

The L4 threshold reuses the transparent existing `practiced` state rather than introducing a new model-decided maturity label. Four distinct independently verified supporting events and reliability >= 0.80 are required for the representative fast path. One success is never sufficient.

L5 is also product-active on this path. Current precondition mismatch prevents the learned mutation from dispatching. Post-action prediction error is recorded as contradicted verified experience and returns control to Investigation. Repeated recent contradiction can inhibit the competence; because the evidence is durable, restart does not erase that downgrade. Later compatible verified events can restore reliability gradually, but one new success cannot immediately restore `practiced` after repeated contradiction.

The representative E2E measurement is deliberately behavioral, not an enum assertion: cold Git staging requires at least one native `deliberate` pulse; after practice, a new target/event uses fewer deliberation pulses while both cold and practiced paths retain current `inspect_path`, current Git sensing, Body mutation and independent Git postcondition verification.

No River/ADWIN runtime dependency was added. Its drift-detection principle remains a research reference; the deterministic verified-event/recent-contradiction baseline is sufficient for this narrow closure and is easier to audit. No Voyager-style GPT control plane or DAgger teacher-as-truth path was introduced: external cognition remains a fallible suggestion source and only independent reality verification creates positive learning evidence.

This status does **not** mean “Memory is complete”, “human-like long-term memory is complete” or “any workflow can now be learned”. General multi-step procedure representation, broader task families and higher-level consolidation remain future work and must earn their own real E2E evidence.
''',
    "docs/ZN-RESIDENT-INTELLIGENCE.md": r'''

<!-- memory-learned-behavior-1.0-closure -->
## 2026-09-10 — Resident-owned learned behavior representative path

Status: **VERIFIED NARROW**.

The normal product builder now returns `MemoryLearnedBehaviorResidentRuntime`, composed above the prior active Resident chain. This is a resident behavior layer, not a second agent/runtime: Self, Work, Situation, Investigation, Thought, Body, authority, side-effect recovery and verification continue to be owned by the same Resident lifecycle.

For a mature bounded Git staging procedure, fresh Investigation first establishes the current path/repository/Git facts and derives the current legal action intents. Existing procedural applicability then decides whether a `practiced` resident-owned tendency matches those current facts. Only then may the Resident skip one redundant native deliberation pulse and enter the ordinary action cycle with the **current** intent. History never reconstructs Body arguments.

A prediction mismatch immediately gives current reality priority. Pre-action mismatch blocks dispatch; post-action verification mismatch records contradiction, revokes the learned route for the event and returns to Investigation. Repeated contradiction can durably inhibit the tendency across Resident restart, after which new verified experience must rebuild support/reliability gradually.

This gives Resident intelligence one concrete “experience changed future cognition cost” closure while preserving the core rule that less unnecessary cognition must never mean less sensing, authority or verification.
''',
    ".agent/HANDOFF.md": r'''

<!-- memory-learned-behavior-1.0-closure -->
## 2026-09-10 handoff — Memory & Learned Behavior 1.0 / PR #245

Base used for the work: `17f22fefcda32db9eb20d3a9a6f080157a4e0c5d` (`E2E-36: explicit uncertain side-effect resolution (#244)`). Development branch: `work/memory-learned-behavior-v1`. PR: `#245`.

Representative closure status: **E2E-37 CLOSED, E2E-38 CLOSED, E2E-39 CLOSED; Memory & Learned Behavior VERIFIED NARROW / representative path closed**, subject to the canonical merge checks on the final PR head.

What changed:

- active Resident composition adds `MemoryLearnedBehaviorResidentRuntime`;
- procedural compatibility becomes project/workspace-local when a privacy-safe workdir fingerprint exists;
- bounded verified prior context can support “use my previous way on this project” without transcript dumping or historical Body args;
- `practiced` current-applicable competence can remove one redundant native deliberation pulse on the real single-path Git staging family;
- current Sense, authority, SideEffect/anti-replay and independent verification remain mandatory;
- pre-action mismatch blocks dispatch; post-action prediction error records contradiction and returns to Investigation;
- two recent contradictions can durably inhibit; restart preserves downgrade; later verified evidence relearns gradually rather than one-shot restoring maturity;
- restart with external models unavailable preserves the bounded learned mechanical competence.

Research before implementation: HumanCompatibleAI/imitation DAgger (aggregate learner-visited experience, but teacher is not truth), MineDojo/Voyager (reusable skills + environment feedback/self-verification, but no GPT-owned control plane), and River/ADWIN (drift principle only; no production dependency without benchmark justification).

Acceptance files: `tests/zn_agent/core/test_learned_behavior_resident.py`, `tests/zn_agent/core/test_project_scoped_procedural_learning.py`, `tests/zn_agent/e2e/test_e2e37_preferred_working_style.py`, `tests/zn_agent/e2e/test_e2e38_learned_verified_workflow.py`, `tests/zn_agent/e2e/test_e2e39_learned_path_drift.py`, plus `.github/workflows/memory-learned-behavior-e2e.yml`.

Do not broaden this handoff into a claim that arbitrary workflows, human-like memory, code-generating learned skills or cross-device memory are closed.
''',
}


def main() -> None:
    changed = []
    for name, section in SECTIONS.items():
        path = Path(name)
        text = path.read_text(encoding="utf-8")
        if MARKER in text:
            continue
        path.write_text(text.rstrip() + section + "\n", encoding="utf-8")
        changed.append(name)
    print("updated:" if changed else "already synchronized:", *changed)


if __name__ == "__main__":
    main()
