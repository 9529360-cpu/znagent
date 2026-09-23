# ZNagent maintainer handoff

## Current objective

The highest-priority phase is the natural-chat / memory / restart continuity loop. PR #414 closes that loop on top of the existing Resident, Work, memory, provider and continuity owners; browser/Office/Windows automation expansion is deliberately deferred until this line is merged.

The product contract for this phase is:

```
natural user message
-> canonical Resident Work conversation
-> bounded prior conversation + structured memory
-> configured cognition resource
-> natural-language Resident outcome
-> durable Work/message outcome
-> narrow explicit long-term preference write-back
-> restart / reconnect
-> same Resident identity, Work conversation and saved preference
```

No second chat database, task engine, model router, identity owner, scheduler or execution authority was introduced.

## Natural chat / memory / restart closure — 2026-09-23

### What actually changed

- **One conversation owner:** Resident Work thread id is the canonical conversation identity. Telegram chat/topic addresses deterministically map to one opaque `work-channel-*` Work thread that Desktop/RPC can open and continue.
- **Channel ingress now enters Work:** the active `ResidentChannelSupervisor` uses the existing recovery-bounded Work ledger instead of enqueueing a parallel bare channel event.
- **Current conversation remains bounded:** `work_conversation_context.py` continues to project only prior user/ZN text with strict count/char/byte limits and a durable Work message cutoff. Activity, artifacts, other threads and future messages are excluded.
- **Short-term working state stays short-term:** Resident/Work working checkpoints remain execution state and are not promoted to long-term memory.
- **Long-term memory remains structured:** `StructuredMemory` keeps the existing facts table as the owner. Automatic write-back is restricted to explicit durable presentation preferences: reply language, reply style and reply verbosity.
- **Write-back is conservative:** only normalized allowlisted values are stored. Ordinary chat, credentials, health/personal data, permissions, route policy, inferred traits and model-generated claims are not auto-saved by this path. Ambiguous conflicts fail closed; explicit corrections replace the dimension; identical repeats are no-ops.
- **Remote preference authority is bounded:** Telegram private chat may update those presentation preferences; group/unknown remote senders may converse but cannot rewrite the Resident owner's global preferences.
- **Provider state is not identity:** the existing ProviderSettings service still exposes provider/model/readiness, hot-applies the configured cognition resource, and provider switching does not replace Resident identity, Work or memory.
- **Failure is explicit:** an unavailable/unconfigured model and a configured provider failure both produce a durable failed Work outcome. Telegram receives a static credential-safe explanation rather than a fabricated success or raw provider diagnostic.
- **Duplicate/loss protection:** one channel source update derives one stable Resident event/message identity. Replays do not duplicate memory, Work or replies. If Work ingress or route persistence fails after polling, the exact polled batch is retained and retried before the provider cursor is committed.
- **Restart path composes with #413:** the authenticated Resident endpoint becomes reconnectable after a real non-dispatching life pulse and before saved Work resumes, so existing conversations can be discovered before recovery execution continues.

### Files changed in PR #414

Runtime:
- `runtime/python/zn_agent/core/channel.py`
- `runtime/python/zn_agent/core/channel_delivery.py`
- `runtime/python/zn_agent/core/channel_runtime.py`
- `runtime/python/zn_agent/core/memory.py`
- `runtime/python/zn_agent/core/recovery_bounded_work.py`
- `runtime/python/zn_agent/core/work.py`

Acceptance/regression coverage:
- `tests/zn_agent/core/test_channel_runtime.py`
- `tests/zn_agent/core/test_explicit_preference_writeback.py`
- `tests/zn_agent/core/test_natural_chat_memory_recovery_contract.py`

This handoff file is the only documentation file changed for the phase.

### Real product scenarios validated

The contract test uses the actual Product Resident, SQLite, Resident Work ledger, Resident RPC, channel supervisor, ProviderSettings and continuity proof. The paid network-model edge is controlled in CI; the repository's existing `test_memory_conversation_product.py` separately drives the actual OpenAI-compatible cognitive-resource adapter with a bounded wire client.

Validated behavior includes:

1. Telegram private natural language asks ZN to remember a concise-answer preference.
2. The preference is normalized into structured memory rather than storing the raw utterance.
3. A duplicate Telegram update creates no second user message, model work, memory rewrite or external reply.
4. Desktop/RPC opens that exact canonical Work thread and sends the second turn.
5. The model boundary receives bounded prior conversation plus the saved response preference.
6. Resident/store are closed and reconstructed.
7. Provider configuration switches from an OpenAI route to an Anthropic route through the real ProviderSettings service.
8. Resident identity, Work and the preference survive restart and provider switch.
9. Telegram sends the third turn into the same Work thread; the restarted Resident still supplies the relevant history and preference to cognition.
10. Continuity comparison remains compatible; provider change is only a provider-reference warning.
11. No-model and configured-provider-failure paths are durable failures with clear user-visible guidance.
12. Telegram group chat cannot rewrite the Resident owner's global response preferences.
13. Channel Work-ingress and route-persistence failures retry the already-polled batch without message loss or duplicate Work.

### Exact verification evidence

Code-validation head: `0eca49256a0332de7763b0685997193d958c40ce`.

- **ZN CI #2664 / run 35911086431: SUCCESS**
  - ZN Kernel / Python / Windows: **1703 tests passed, 5 skipped**, 1412.346 s.
  - The new natural chat/memory/restart contract cases all passed, including three-turn restart/provider-switch continuity, configured-provider failure, no-model failure and group-chat preference isolation.
  - Channel loss/dedup regression cases passed, including retained-batch retry after Work-ingress failure and stable replay after route-insert failure.
  - Electron / TypeScript / Windows / tests: SUCCESS.
  - ZN Source Boundary / Windows: SUCCESS.
  - Product Contracts gate: SUCCESS.
- **ZN Work Recovery Contract #54 / run 35911086398: SUCCESS**
  - **166 tests passed**, 189.039 s.
- **ZN Windows Clean Install #1571 / run 35911086427: SUCCESS**
  - packaged runtime and renderer/Electron build verified;
  - unsigned installer candidates built and release manifest verified;
  - real NSIS candidate installed into isolated Windows state;
  - installed Desktop started and Resident life was verified.

An earlier #414 head exposed deterministic failures in context nesting, one Chinese preference alias, channel checkpoint/stop compatibility and the retired `e2e` path namespace. Those were fixed; no unchanged failing run is being used as acceptance evidence.

### Remaining risks / deliberate limits

- Automatic natural-language memory write-back is intentionally **not** a general personal-fact extractor. It currently covers only explicit durable response language/style/verbosity preferences. Broader long-term facts need a separately reviewed privacy/conflict policy rather than transcript mining.
- The conversation projection is bounded by design; very old context must be recovered through structured memory or explicit Work inspection rather than dumping full transcripts into a model.
- CI does not send paid requests to a live external model and does not contact the real Telegram service. Provider configuration/routing, native cognitive-resource transport, channel ownership and restart behavior are verified with controlled boundaries.
- A model/provider failure remains a durable failed Work; automatic retry after configuration repair is not invented by this phase.
- Telegram transport addresses map deterministically to Resident Work threads, but there is no new UI for manually rebinding an arbitrary pre-existing Desktop-only thread to a different Telegram conversation.

### Next step

Merge #414 only after the HANDOFF-only final head also has fresh applicable green gates and main/head freshness is rechecked. After this phase is on canonical `main`, browser or other capability expansion can resume. Do not expand those surfaces before this continuity line is merged.

## Current cleanup state

The active cleanup line has already removed several story-owned product paths:

- current-app text cleanup behavior/completion/goal and its dedicated Body extension;
- local-service recovery behavior and dedicated diagnosis surface;
- long-running terminal story behavior;
- local Office representative behavior;
- document-research-completion story behavior/safety layer;
- managed-reference browser research story runtime;
- browser-result-to-file story routing;
- fixed delegated-worker story orchestration;
- File-to-Desktop composite goal / semantic grounding and task-specific modal sensing/recovery stack;
- payment-date-specific DOCX inspection and mutation path.

Generic mechanisms remain where they have reusable ownership:

- Work and Root completion truth;
- side-effect journal and replay discipline;
- USER Browser authorization and tab-generation ownership;
- managed Browser adapters and generic Browser contracts;
- Action Fabric / Body authority;
- Windows application/UIA/pointer/keyboard capability;
- generic document, presentation, spreadsheet, file, research, delegation and memory primitives.

The old test namespace has been retired. Reusable real-system tests live under `tests/zn_agent/integration`, and automatic workflows are contract-named.

## CI policy

Automatic merge/mainline validation is capability/contract based.

Required automatic contract surfaces include:

- Managed Browser Contract;
- Windows Interactive Desktop Contract;
- Work Recovery Contract;
- Atomic Overwrite Contract;
- ZN CI;
- Windows Clean Install.

Historical task stories are not architecture owners and do not get dedicated Resident modules, behaviors, routing rules, worker phase sequences, or merge gates.

## Browser capability line

Browser capability work is intentionally parked behind the natural-chat/memory/restart continuity phase. When it resumes:

- prefer mature external Browser mechanics instead of growing ZN-specific DOM automation;
- keep USER Browser ownership isolated from public/background research;
- route providers by declared capability, never by task story or prompt text;
- require fresh semantic observation before side effects and fresh verification after them;
- allow bounded semantic re-ground only when the provider proves the previous attempt never crossed dispatch;
- pin the pre-dispatch page context so a same-named control on a changed page cannot inherit authority;
- never replay dispatched or uncertain effects;
- treat provider success only as evidence, never as Root completion;
- keep Playwright as a fallback where stricter file-transfer/session contracts still require it;
- package external runtimes at exact versions; never download `@latest` at user runtime.

## Non-negotiable architecture rules

Do not add:

- numbered scenario Resident classes;
- scenario-specific `*_behavior.py` modules whose only owner is one acceptance story;
- exact-prompt or exact-Chinese-sentence product routing;
- fixed worker pipelines for one representative task;
- hidden fallback after a provider has already begun a side-effecting task.

New functionality must compose through reusable capability contracts and remain subordinate to ZN Work, authority, Body, fresh verification, no-blind-replay and Root completion truth.
