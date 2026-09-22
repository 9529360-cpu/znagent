# ZN Next Phase

This document records the next engineering order, not a catalog of representative stories.

## 1. Finish the cleanup first

Before adding another Browser runtime, the repository must have a clean capability-owned surface:

- no numbered scenario modules in production;
- no story-specific Resident or behavior routes;
- no fixed worker sequence owned by one acceptance task;
- no scenario-named test directory or workflow;
- no architecture documentation that treats a representative task as the owner of a product route.

Reusable real-system verification belongs under integration/contract semantics.

## 2. Keep the control plane singular

ZN remains the sole owner of:

- Resident identity and lifecycle;
- Root Work and plan truth;
- action authority;
- Body dispatch;
- side-effect attempt identity;
- fresh sensing and postcondition evidence;
- replay/recovery policy;
- completion truth.

External tools can provide mechanics and observations. They do not become another agent brain, scheduler, Work ledger, completion system, or authority source.

## 3. Verify the cleaned substrate

Before Browser expansion, the cleaned line must pass the applicable generic gates:

- ZN CI;
- Managed Browser Contract;
- Windows Interactive Desktop Contract;
- Work Recovery Contract;
- Atomic Overwrite Contract;
- Windows Clean Install when packaging/runtime boundaries change.

Failures in these gates should be repaired at the reusable contract owner. Do not recreate retired story routes to make a test pass.

## 4. Add mature Browser mechanics from clean main

After cleanup is merged:

1. reread the latest `main`;
2. create one fresh Browser-provider integration branch;
3. research mature upstream implementations and licenses first;
4. add the smallest provider substrate;
5. route by capability requirements before session creation;
6. keep USER Browser ownership separate;
7. add generic provider contracts;
8. package exact-version sidecars only after the adapter contract is stable.

The first preferred provider remains Chrome DevTools MCP, with Playwright retained as a fallback for capabilities that require stricter causal file-transfer or session behavior.

## 5. Provider requirements

Any managed Browser provider must expose or declare enough capability information for ZN to decide before opening a session whether it can satisfy the requested operation.

Provider observations must be treated as generation-bound evidence:

- semantic identifiers belong to one fresh observation;
- stale identifiers are not replayable authority;
- a side effect requires final fresh target validation;
- completion requires a fresh postcondition observation;
- provider-reported success never closes Root Work by itself.

## 6. Subsequent capability expansion

Once the provider substrate is stable, add reusable mechanics only when they improve general capability contracts, for example:

- tabs/pages;
- dialogs;
- downloads/uploads;
- file chooser;
- console/errors;
- network observation;
- profile/session ownership;
- recovery after browser drift or restart.

Do not add a new Resident or route for one task story.
