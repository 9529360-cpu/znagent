# ZN Next Product Phase

This file records the current recommended product sequence after restoring live repository/code/test/CI truth. It is a priority document, not capability evidence. `ZN.md`, real production code, real Git and real runtime/E2E evidence remain authoritative.

Observed checkpoint: `dev/zn-agent` at `af8754ae1ee0d0b3491cbad2134dd6e12edda5f9` on 2026-09-04.

## Current phase: real-task autonomous closure

The current product phase is not installer/release expansion, self-maintenance transport, primitive verification or new agent/provider abstractions.

The product question is:

> When an ordinary user gives ZN a normal human task, can the same long-lived Resident understand it, inspect the current computer, choose the necessary browser/desktop/file resources, perform multiple steps, re-sense and replan when reality changes, verify the real result and preserve continuity for later work?

The strongest current evidence is no longer isolated movement primitives. Current dev has bounded real Windows slices for:

- explicitly authorized existing authenticated browser work;
- authenticated textbox -> button -> result-page work;
- managed research that preserves and returns to the user's authorized browser tab;
- browser semantic re-ground after label/node drift;
- browser -> file work with two-source research and verified file reread;
- file -> desktop work with stale-source rejection and recovery;
- desktop semantic re-ground after runtime UI label/identity drift.

These are meaningful vertical slices, but they are still `Verified / Partial`, not broad Product-closed categories. See `ZN-REAL-USER-E2E.md`.

## Current blocking evidence

Current dev is not CI-green:

- Kernel/Python has one fail-closed regression where an ambiguous workspace-source scenario observed one edit call instead of zero;
- Windows Interactive has one direct-CDP multi-visible-page ambiguity failure and one legacy foreground-browser-title error.

These failures are product evidence. They must not be hidden behind the large number of passing neighboring tests.

## Recommended next five product work items

Each item below is valuable only because it closes a concrete user E2E. The order should be re-checked against live evidence at takeover.

### 1. Restore zero-side-effect behavior for ambiguous workspace sources

Real user scenario:

> The user asks ZN to take data from a workspace file and use it in the current app, but two files are equally plausible.

Current failure:

- current Kernel/Python CI proves one edit call can occur where ambiguity should keep the task in Investigation with zero mutation.

Existing foundation:

- candidate comparison;
- exact file identity;
- stale-source rejection;
- verified file reread;
- file -> desktop vertical path.

Acceptance E2E:

```text
two equally plausible workspace sources
-> ordinary-language desktop goal
-> ZN cannot prove one source
-> zero file / keyboard / pointer mutation
-> explicit unresolved state
-> after real disambiguating evidence, fresh re-sense
-> exactly one verified completion
```

This is the highest immediate priority because it is a current safety/correctness regression on a real product path.

### 2. Stabilize existing-session browser identity under realistic tab/window drift

Real user scenario:

> The user has multiple browser windows/tabs open, explicitly authorizes one logged-in tab, then asks ZN to complete a normal task there.

Current failure:

- a direct-CDP path becomes ambiguous with multiple visible pages;
- a legacy named-browser path can fail when foreground title identity is unstable.

Existing foundation:

- explicit extension authorization of one exact tab;
- authenticated session established before Resident;
- no cookie/profile transfer;
- revoke;
- decoy-tab protection;
- semantic re-ground and result verification.

Acceptance E2E:

```text
one explicitly authorized logged-in tab
+ multiple visible lookalike tabs/windows
+ focus/title drift
-> normal-language task
-> only authorized tab receives authority
-> stale context is rejected/re-sensed
-> final authenticated result independently verified
```

Do not solve this by copying browser credentials or by adding another parallel browser identity system.

### 3. Close natural Work continuation, then active-task steering

Real user scenario:

> `昨天那个继续。` / `刚才那个继续。` / a new instruction while that Work is still active.

Current truth:

- durable Work and restart persistence exist;
- open PR #166 implements natural prior-Work references and completed-Work follow-up on a branch, not current dev;
- PR #166 is currently behind live dev and has no visible current-head PR workflow run;
- PR #166 explicitly leaves active-task steering as a separate problem.

Acceptance E2E:

```text
Resident restart
-> user says "昨天那个继续"
-> exactly one durable prior Work is resolved
-> current computer is freshly re-sensed
-> previous side effects are not replayed
-> user gives a new instruction while Work is active
-> same Work identity is steered safely
-> final real result independently verified
```

Natural continuation should reconnect to reality, not replay event history.

### 4. Close one browser + file + desktop task with runtime replanning

Real user scenario:

> ZN must look something up in the browser, use/update a local file, then carry the result into a desktop application; one page/file/window state changes mid-task.

Current foundation:

- browser -> file is verified narrowly;
- file -> desktop is verified narrowly;
- browser/desktop semantic re-ground exists;
- managed-source detail replanning exists.

Current gap:

- no current real-user E2E closes all three surfaces as one Work;
- routing remains substantially task-family-specific.

Acceptance E2E:

```text
ordinary-language goal
-> sense current browser/workspace/app
-> investigate web evidence
-> exact file operation
-> desktop operation
-> induced page/file/window drift
-> fresh Sense / Situation / Thought / replan
-> independently verified final application/file state
```

Use this E2E to justify only the routing/replanning changes it actually exposes. Do not pre-build a generic orchestration framework.

### 5. Preserve installed N -> N+1 Resident/data continuity as a critical supporting lane

Real user scenario:

> A long-lived installed ZN upgrades without becoming a new subject, losing Work or replaying an uncertain side effect.

Current foundation:

- clean-install workflow currently succeeds;
- same-home core test preserves selected Self and Work data across a runtime-id change;
- update/artifact verification foundations exist.

Not proven:

- real installed N -> N+1 replacement;
- schema migration;
- active/uncertain Work continuity;
- rollback;
- signing/release trust.

Acceptance E2E:

```text
installed N with durable Self + Work + one replay-sensitive state
-> installed N+1 transition
-> same subject/data references verified
-> no duplicate uncertain side effect
-> migrated Work still inspectable/continuable
```

This is a critical long-term continuity requirement, but installer/release/signing work must not automatically outrank the current real-task gaps above unless it is directly blocking user data or Resident continuity.

## Supporting / deferred work

The following work remains legitimate but is not the current product mainline by default:

- installer optimization;
- release-candidate choreography;
- signing/release trust;
- extra CI orchestration;
- BUG-report transport/intake/deployment;
- maintainer transport/handoff formatting;
- new governance abstractions;
- new provider abstractions;
- new Agent/organ/state-machine abstractions.

Existing implementation and historical evidence in these areas should be preserved. Their priority changes only when a concrete real-user E2E, data-safety boundary or Resident-continuity issue is directly blocked by them.

## Product-phase completion rule

Do not advance the phase because a class exists, a primitive E2E passes, a PR merges, CI is green or an installer is produced.

Advance it when one more ordinary user task can reliably move through:

```text
normal-language goal
-> fresh Sense
-> Situation / Thought
-> bounded plan or hypothesis
-> action
-> fresh observation
-> compare outcome
-> continue / investigate / replan
-> independent completion evidence
-> durable Work continuity
```

The current acceptance ledger is `ZN-REAL-USER-E2E.md`.
