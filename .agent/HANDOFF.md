# ZNagent maintainer handoff

## Current objective

Expand reusable capabilities from the cleaned substrate without restoring scenario-owned product paths.

The Browser line is active again: pinned Chrome DevTools MCP is integrated behind ZN's provider/capability routing, Playwright remains a bounded fallback, and USER Browser authority stays isolated behind explicit current-tab authorization.

The product direction remains substrate-first:

1. keep one ZN Resident / Work truth / authority / Body / completion truth;
2. validate reusable capability contracts in CI;
3. keep real integration evidence capability-owned rather than story-owned;
4. broaden mature external Browser mechanics only behind ZN-owned permission, fresh evidence, no-replay and completion semantics.

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

The old test namespace has been retired. Reusable real-system tests now live under `tests/zn_agent/integration`, and automatic workflows are contract-named.

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

The cleanup prerequisite is complete and Browser work now proceeds from current clean `main`.

Current rules:

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
