# ZNagent maintainer handoff

## Current objective

Finish removing scenario-owned product, test, CI, and documentation surfaces before adding any new mature Browser provider.

The product direction is substrate-first:

1. keep one ZN Resident / Work truth / authority / Body / completion truth;
2. validate reusable capability contracts in CI;
3. keep real integration evidence capability-owned rather than story-owned;
4. only after the cleanup is merged, add mature external Browser mechanics behind ZN's existing control plane.

## Current cleanup state

The active cleanup line has already removed several story-owned product paths:

- current-app text cleanup behavior/completion/goal and its dedicated Body extension;
- local-service recovery behavior and dedicated diagnosis surface;
- long-running terminal story behavior;
- local Office representative behavior;
- document-research-completion story behavior/safety layer;
- managed-reference browser research story runtime;
- browser-result-to-file story routing;
- fixed delegated-worker story orchestration.

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

## Browser work remains intentionally paused

Do not add the mature Browser provider until this cleanup is merged and the latest `main` is reread.

When Browser work resumes:

- start from a fresh branch off clean `main`;
- prefer mature external Browser mechanics instead of growing ZN-specific DOM automation;
- keep USER Browser ownership isolated from public/background research;
- route providers by declared capability, never by task story or prompt text;
- require fresh semantic observation before side effects and fresh verification after them;
- treat provider success only as evidence, never as Root completion;
- keep Playwright as a fallback where stricter file-transfer/session contracts still require it;
- package any external runtime at an exact version; never download `@latest` at user runtime.

## Non-negotiable architecture rules

Do not add:

- numbered scenario Resident classes;
- scenario-specific `*_behavior.py` modules whose only owner is one acceptance story;
- exact-prompt or exact-Chinese-sentence product routing;
- fixed worker pipelines for one representative task;
- hidden fallback after a provider has already begun a side-effecting task.

New functionality must compose through reusable capability contracts and remain subordinate to ZN Work, authority, Body, fresh verification, no-blind-replay and Root completion truth.
