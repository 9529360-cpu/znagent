# ZN next phase — return to core capability mainline

> Date: 2026-08-23
>
> Active branch: `dev/zn-agent`
>
> Governing architecture: [`../ZN.md`](../ZN.md)
>
> Current implementation facts: [`ZN-IMPLEMENTATION-STATUS.md`](ZN-IMPLEMENTATION-STATUS.md)
>
> Self-maintenance contract: [`ZN-SELF-MAINTENANCE.md`](ZN-SELF-MAINTENANCE.md)

## 1. Why this phase exists

Recent work intentionally spent substantial effort on M7/M8 desktop packaging, clean installation, autostart and N → N+1 continuity because a resident subject that cannot survive installation/update boundaries is not a real product.

That work was necessary, but it must not become the permanent center of development.

The next main development phase returns to **ZN core capability completeness**.

The product goal is not “finish the UI” and it is not “copy every feature from another agent”. The goal is:

```text
one durable ZN subject
→ can perceive enough of the computer/world
→ can investigate an unfamiliar problem
→ can use its body to act
→ can observe the result
→ can continue the same work across pulses/time
→ can verify reality instead of trusting model output
→ can learn from the outcome
```

Desktop remains a face/work surface. Packaging/release remains an essential product lane. Neither should own the development agenda while core capability gaps are still material.

## 2. Priority reset

Until the core capability gap is substantially reduced:

- do not spend a development phase on cosmetic UI polish;
- do not add dashboard surfaces merely because information can be displayed;
- do not rebuild already-proven packaging gates only to recreate evidence;
- desktop work is justified when it is required to expose, operate, debug or safely authorize a real core capability;
- release/M8 work continues as a bounded validation lane, not as the definition of ZN's intelligence or agency;
- bugs, security problems, data-integrity problems and release blockers remain legitimate exceptions.

This is a priority reset, not an architecture reset. The organism-first contract in `ZN.md` remains authoritative.

## 3. Current core reality

The current repository already has a substantial ZN-native base:

- persistent resident life and identity;
- Situation / Thought / Will;
- nervous memory and reconsolidation machinery;
- native investigation / action / learning loop;
- bounded external cognition through ZN-owned resource adapters;
- meaningful zero-model operation;
- ZN-owned local process/terminal/PTTY body;
- ZN-owned web search/extract sensing and network safety;
- durable work/thread/workspace/active-run state;
- contextual file/diff/terminal artifacts;
- resident-owned provider/settings lifecycle;
- resident-owned communication lifecycle with Telegram text/inbound media;
- ZN-owned desktop main/preload/protocol/workbench;
- independently packaged `zn_agent` runtime and proven package artifacts.

These are real foundations. They are **not** evidence that ZN already has the complete practical capability breadth of a mature general-purpose agent.

## 4. Known capability gaps that must be audited in code

The next session must not mark these from documentation alone. It must trace active callers, ownership, state, lifecycle and tests before assigning status.

Initial categories to audit:

| Capability area | Current expectation before code audit |
| --- | --- |
| Persistent subject / zero-model life | strong existing foundation |
| Durable long-running work | existing foundation, practical autonomy depth still needs audit |
| Files/process/terminal body | active, breadth and task-level composition need audit |
| Git body | architecture requires it; practical owned operation depth must be verified |
| GitHub/repository interaction | not yet a resident-owned general maintenance body; SM2+ still planned |
| Web search/extract | active |
| Browser interaction | missing as a clean ZN-owned body/sense capability |
| Visual/screen sensing | architectural target; mature end-to-end capability not yet claimed |
| Mouse/keyboard/computer use | not yet claimed as a mature owned capability |
| Long-horizon autonomous investigation/action/verification | resident primitives exist; task success depth must be measured, not assumed |
| Tool/capability ecosystem | selective owned capabilities exist; breadth is incomplete |
| Communication | Telegram text/inbound media active; outbound attachment egress still partial |
| Self-health observation / maintenance cases | SM1 planned |
| Self-repository investigation | SM2 planned |
| Isolated self-repair + PR/CI | SM3/SM4 planned |

The audit result should use four labels:

```text
DONE
PARTIAL
MISSING
DO NOT COPY
```

`DO NOT COPY` matters: a mainstream-agent feature that would reintroduce `LLM → planner → tools → agent` ownership, inherited control planes, or a model-owned identity should not be adopted merely for parity.

## 5. How new capabilities must fit ZN

New capability work must strengthen the existing subject rather than create parallel agent brains.

Preferred mapping:

```text
Self
Body
Senses
Memory
Situation
Thought
Will
Investigation
Action
Learning
```

Examples:

```text
browser navigation
≠ browser agent
= ZN body/sense capability

Git / repository mutation
≠ coding-agent personality
= ZN body capability with evidence and safety boundaries

GitHub / PR / CI reading
≠ external maintainer brain
= repository/world sense for the same resident

long task execution
≠ one giant LLM plan
= durable work + repeated Situation → Investigation/Action → Evidence pulses
```

External models may propose hypotheses or candidate code. Their output still must be checked against current code, logs, tests, runtime evidence and world state.

## 6. First task of the next session

Do a **repository-backed ZN capability gap audit** before choosing the next implementation slice.

Required method:

```text
restore repository state
→ read architecture/status/HANDOFF
→ inspect current HEAD/CI
→ enumerate capability categories
→ trace each real active call chain
→ inspect ownership/state/lifecycle/tests
→ run focused validation where status is ambiguous
→ classify DONE / PARTIAL / MISSING / DO NOT COPY
→ rank gaps by product leverage and architectural fit
→ choose one coherent core slice
→ update ZN.md first only if architecture direction must change
→ implement/test/CI normally
```

The audit should compare capability categories with mature contemporary agents, but the comparison is a coverage tool, not the product definition.

Do not assume ZN is strong merely because an interface/class exists. A capability counts when the active resident can actually use it and the behavior is protected by real tests/evidence.

## 7. Likely high-value implementation lanes after the audit

The audit decides exact order. The current strongest candidates are:

1. durable long-task execution quality: keep investigation/action/verification moving across pulses without cognitive restart or a model owning the plan;
2. clean ZN-owned browser body/sense boundary and lifecycle;
3. visual/computer-use body and senses where local platform permissions allow it;
4. practical Git + GitHub/repository body/sense capability, designed so it can later support SM2–SM4 safely;
5. SM1 health observation / `MaintenanceCase`, then the self-maintenance sequence already defined in `ZN-SELF-MAINTENANCE.md`;
6. broaden tool/resource coverage only where a real ZN task needs it.

Do not decide among these by feature fashion. Prefer the slice that most increases ZN's ability to complete real work while preserving resident ownership.

## 8. M8/release lane boundary

M8 is not abandoned.

At the implementation baseline before this document, `7ac39b53f0bd990513d9f2ff5928ee5e53fe145c` has normal CI success for:

```text
ZN Kernel / Python
Electron / TypeScript
Actions run 32609677486
```

The dedicated `ZN Linux AppImage Update Smoke` final commit status was not present when this phase document was written. Therefore the full AppImage application updater gate must **not** be recorded as green or complete yet.

The correct relationship is:

```text
finish/record the current AppImage gate honestly
→ keep remaining M8 multi-OS/signing/release breadth as explicit release work
→ do not let release breadth consume the next core-development phase
```

If the dedicated AppImage gate exposes a real continuity/data-integrity defect, fix it. If it exposes only test-harness/release-validation debt, record and bound that debt instead of turning the project back into a packaging project.

## 9. UI boundary for this phase

UI work is allowed when it is the minimum necessary surface for a core capability, for example:

- permission/approval for a body action;
- displaying evidence needed to understand an ongoing resident task;
- browser/computer-use observation/control required by the capability;
- maintenance-case visibility required by SM1;
- fixing a real usability defect that blocks task completion.

Pure visual polish, layout churn and extra dashboarding are not next-phase priorities.

## 10. Phase success signal

This phase is moving correctly when repository evidence increasingly supports statements such as:

```text
ZN can take a durable real-world/computer task
→ investigate using owned senses
→ manipulate the computer using owned body capabilities
→ use models only when useful
→ verify outputs/results
→ continue after a pulse/window/model interruption
→ preserve the same Self/work/memory
→ surface failure instead of pretending success
```

The objective is **a more capable ZN**, not a more decorated desktop and not a larger collection of model-owned tools.
