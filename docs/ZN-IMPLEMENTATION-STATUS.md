# ZN Implementation Status

This is the current product/evidence ledger for ZN. It is not a commit log, roadmap or capability-count scorecard.

Real code and live Git state override this file. Actual tests/builds/CI override documentation claims. User-level maturity is recorded with:

- **Exists** — implementation is present;
- **Connected** — the real product call path uses it;
- **Verified** — focused test/runtime/E2E evidence proves the bounded slice;
- **Product-closed** — an ordinary user task is reliably closed end to end, including relevant recovery/replanning, independent verification and continuity;
- **Partial / Experimental / Blocked** — useful but incomplete or currently failing.

A module, PR or green focused test must not be upgraded to `Product-closed` without real user-task evidence.

Observed reconciliation checkpoint: `dev/zn-agent` at `af8754ae1ee0d0b3491cbad2134dd6e12edda5f9` on 2026-09-04.

## Repository / verification truth

- `main`: `0dbec575fc128bd1cc1837e7485b5a37e0ac8393`;
- `dev/zn-agent`: `af8754ae1ee0d0b3491cbad2134dd6e12edda5f9`;
- observed comparison: dev is 223 commits ahead and 1 behind main. This is repository/release hygiene, not product progress;
- open PR #166 (`work/natural-work-continuation`) is not merged current truth and is 5 commits behind current dev;
- current clean-install run `33806840503`: success;
- current `ZN CI` run `33806840435`: Source Boundary and Electron succeed; Kernel/Python fails one ambiguity fail-closed regression;
- current Windows Interactive run `33806840505`: failure, 33 tests total, 31 passing, one failure and one error.

Current interactive failures:

1. direct-CDP current-tab identity becomes ambiguous with multiple visible pages;
2. legacy named-browser probing can fail when the foreground browser window has no stable title.

Current Kernel/Python failure:

- ambiguous model-understood workspace source produced one edit call instead of the required zero side effects.

Do not describe current dev as CI-green or runtime-healthy.

## Resident Core

**Maturity: Connected + Verified / Product-closed: No broad claim**

Current facts:

- ZN owns Resident Self, Body/Senses, Situation, Thought, Will, Investigation/Action and persistent state;
- external models are bounded cognition resources and do not own identity, world truth, authority or completion;
- zero-model/native behavior remains supported for bounded resident-owned paths;
- Resident service/socket lifecycle and persistent home/state are exercised by core tests.

Current limitation:

- the existence of a persistent Resident does not by itself prove broad ordinary-language task autonomy or long-term user continuity across arbitrary tasks.

Next product gap:

- use the existing core to close more real tasks rather than adding another resident abstraction.

## Work / Continuity

**Maturity: Connected + Verified / Natural continuation: Missing on current dev**

Current facts:

- durable Work threads/events/outcomes exist;
- selected action lifecycles preserve non-replay/recovery state across restart;
- same-home Resident restart tests preserve Self fields and Work-thread data across different runtime IDs;
- desktop Work surfaces can poll resident-owned thread/event state.

Not current dev truth:

- natural references such as `刚才那个继续` / `昨天那个继续` are implemented only in open PR #166, not in current dev;
- PR #166 reconnects active Work or creates a fresh follow-up event after completed Work, but explicitly refuses new instructions while the referenced Work is already active.

Current limitation:

- active-task steering is not closed;
- no current real-user Windows E2E proves restart + natural prior-Work reference + fresh re-sense + safe continuation.

Next product gap:

- reconcile PR #166 with current dev and prove natural continuation, then separately implement safe active-task steering.

## User Browser Bridge

**Maturity: Connected + Verified for bounded existing-session tasks / Product-closed: No**

Current facts:

- a ZN browser extension can explicitly authorize one current HTTP(S) tab through a user action;
- authorization is tied to the exact tab and is revocable;
- Resident uses a loopback-only relay and bounded command set;
- the verified existing authenticated session is established before Resident starts;
- ZN does not copy the session cookie, password database or browser profile into its managed browser/runtime;
- extension commands can observe/type one exact safe native textbox, observe/click one exact native button, probe current tab state and collect bounded semantic candidates;
- password, OTP and payment-class fields are refused;
- uncertain delivered commands are not blindly replayed;
- semantic browser work can reject stale node/name bindings and re-ground after page-label/node drift;
- an identical foreground decoy tab does not receive authority in the verified semantic extension E2E;
- revocation after grounding stops with zero side effects/replay/substitution.

Important evidence:

- `test_windows_interactive_user_browser_extension.py`;
- `test_windows_interactive_user_browser_extension_form_submit.py`;
- `test_windows_interactive_user_browser_semantic_grounding.py`;
- successful rows inside Windows Interactive run `33806840505`.

Current limitation:

- verification still uses a controlled temporary test user profile, even though the session is real and authenticated before Resident;
- direct-CDP and legacy foreground-title browser paths still expose current context-identity failures;
- permission management is one-tab explicit action/revoke, not a complete user-facing site/account permission center;
- arbitrary forms, uploads/downloads, complex dialogs/frames and sensitive-input workflows are not product-closed.

Next product gap:

- stabilize all ordinary existing-session routing around explicit fresh authorized-tab identity under realistic multi-tab/multi-window drift.

## Managed Browser

**Maturity: Connected + Verified for bounded research/interaction / Product-closed: No**

Current facts:

- managed Chromium is isolated from the user's ordinary browser profile/session;
- bounded navigation and semantic interaction paths exist;
- managed research can inspect multiple reference pages, read page text/links, follow a detail page when the first source is insufficient and establish two-source agreement;
- the verified managed-research-return task preserves the user browser and freshly re-senses it before continuing;
- verified evidence shows managed Chromium did not receive the user's session cookie.

Current limitation:

- current research is still routed by bounded task-specific rules;
- generic source discovery, arbitrary research goals, broad multi-tab/popup/frame handling, download/upload authority and headed product UX are not closed.

Next product gap:

- generalize investigation/replanning only as required by a real user task, not by adding a generic browser abstraction first.

## Desktop / Computer Use

**Maturity: Connected + Verified for bounded semantic tasks / Product-closed: No**

Current facts:

- Windows foreground/UIA and pointer/keyboard foundations are connected;
- ordinary-language desktop goals can use bounded cognition to propose semantics while Resident freshly senses current safe Edit/Button candidates;
- exact UIA identity is bound after semantic selection and revalidated before movement;
- stale RuntimeIds/old exact bindings are rejected;
- duplicate equally named safe candidates can fail closed before input;
- current desktop semantic re-ground logic preserves the semantic goal across label/runtime drift, senses fresh candidates and binds current names again before action;
- real Windows E2Es independently verify final application title/state.

Current limitation:

- the verified task shape remains narrow: safe Edit/Button interaction in the current foreground non-browser app;
- broad menus, dialogs, tree/list controls, complex application navigation and arbitrary recovery are not product-closed.

Next product gap:

- one broader real desktop E2E that forces investigation after app/window state change, instead of another primitive milestone.

## File Operations

**Maturity: Connected + Verified for bounded workspace text tasks / Currently Blocked by one ambiguity regression**

Current facts:

- bounded workspace candidate discovery, comparison, exact file identity, fresh read, overwrite and reread verification exist;
- browser-result-to-file E2E selects one exact plausible file, leaves another plausible candidate unchanged, writes once and rereads the saved content;
- file-to-desktop E2E detects source drift before keyboard input, rejects stale source evidence and recovers before continuing.

Current failure:

- current Kernel/Python CI shows the model-understood ambiguous-workspace-source regression: one edit call occurred where ambiguity requires zero side effects.

Current limitation:

- file task language/edit shapes are still narrow;
- broad document formats, organization/move flows and arbitrary file transformations are not product-closed.

Next product gap:

- restore the zero-side-effect ambiguity boundary before expanding file breadth.

## Cross-surface Tasks

**Maturity: Verified for selected two-surface tasks / Missing for three-surface closure**

Verified bounded slices:

- managed research -> return to authorized user browser;
- browser -> file;
- file -> desktop.

Not verified as one user Work:

- browser -> desktop;
- browser + file + desktop.

Current limitation:

- composite handlers are still task-family-specific; there is no evidence that ZN can generally choose and traverse all required surfaces from an arbitrary reasonable goal.

Next product gap:

- one normal-language browser + file + desktop E2E with a deliberate state change and independent final verification.

## Replanning / Investigation

**Maturity: Connected + Verified in bounded flows / Product-closed: No**

Current facts:

- browser semantic drift can trigger fresh candidate sensing and bounded semantic re-ground;
- desktop label/runtime drift can trigger fresh semantic re-ground;
- managed research can follow a detail page after the first source lacks the required fact;
- file-to-desktop work can reject stale source evidence and re-sense;
- models may propose bounded semantics but cannot mint world identity, authority or completion.

Current limitation:

- these are selected vertical implementations, not a general investigation engine proven across arbitrary user tasks;
- task-specific cue/regex routing remains significant in several paths.

Next product gap:

- drive generalization from a failing real E2E where the route cannot be predicted in advance.

## Completion Verification

**Maturity: Connected + Verified in several task families / Product-closed: No global claim**

Current verified evidence patterns include:

- HTTP server observations independent of the browser adapter;
- fresh final URL checks;
- Windows foreground/UIA state;
- filesystem reread after mutation;
- exact-side-effect counts;
- stale-source/target rejection before further movement.

Current limitation:

- not every product task family has an independent verifier;
- click, keypress, HTTP status, command exit or model response remain insufficient completion evidence.

Next product gap:

- require one explicit independent result condition for every new real-user E2E.

## Safety / Authority

**Maturity: Connected + Verified / Coverage incomplete as surfaces broaden**

Current facts:

- explicit authority and fresh-evidence discipline exist in browser/file/desktop action lifecycles;
- browser extension authorization is user-triggered and revocable;
- sensitive browser fields are filtered/refused;
- model output cannot create browser/UIA identity or action authority;
- uncertain side effects are not automatically replayed;
- credential/profile copying from the user's browser into managed browser is not the existing-session strategy.

Current limitation:

- there is no single complete product permission center;
- every new surface/connector/action still needs the same non-replay, sensitive-data and postcondition discipline.

Next product gap:

- preserve these boundaries while closing user tasks; do not create a new governance framework unless a real E2E exposes a concrete missing safety primitive.

## Deployment / Upgrade Continuity

**Maturity: Partial / Not product-verified**

Current facts:

- Windows clean-install workflow currently succeeds;
- packaging/updater/update-observation foundations exist;
- core same-home restart test proves selected Self and Work data survive a runtime-id change.

Not proven:

- actual installed N -> N+1 replacement;
- schema/data migration under version change;
- identity continuity through real installed upgrade;
- active/uncertain Work continuity through upgrade;
- rollback behavior;
- signing/release trust.

Do not infer long-term safe user upgrades from installer packaging, clean-install CI or updater classes.

Next product gap:

- keep as a critical long-term continuity lane, but do not let release/update engineering outrank current real-task closure unless it directly blocks user continuity/data safety.

## Current five largest product gaps

### 1. Browser context identity under realistic existing-session drift

User scenario: the user has several visible browser pages/windows and authorizes one real logged-in tab.

Failure today: some current paths still become ambiguous or depend on unstable foreground-title evidence.

Existing foundation: exact extension tab identity, explicit authorize/revoke, semantic grounding, decoy-tab protection.

Missing closure: all ordinary existing-session tasks need one coherent explicit browser-context identity path.

Acceptance E2E: multiple lookalike tabs/windows + focus/title drift -> only the explicitly authorized tab changes; independently verified result.

### 2. Ambiguous workspace source must remain zero-side-effect

User scenario: two plausible files match an ordinary task.

Failure today: current Kernel/Python CI shows one edit call under ambiguity.

Existing foundation: candidate comparison, exact identity, stale-source rejection, file reread verification.

Missing closure: ambiguity must stay in Investigation until exactly one source is freshly established.

Acceptance E2E: two equally plausible sources -> zero file/desktop side effects; after disambiguation, exactly one safe completion.

### 3. Natural Work continuation + active steering

User scenario: `昨天那个继续`, then a new instruction while the work is still active.

Failure today: natural reference implementation is open PR #166, not merged current dev; active steering remains explicitly unimplemented.

Existing foundation: durable Work, outcomes, restart persistence, same-thread/event identity rules.

Missing closure: user-visible prior-Work resolution, fresh re-sense, and safe in-flight instruction steering without event replay.

Acceptance E2E: restart -> `昨天那个继续` -> same durable Work -> fresh sensing -> active steering -> verified result, no prior side-effect replay.

### 4. General investigation/replanning across surfaces

User scenario: a normal goal needs browser + file + desktop and one step changes unexpectedly.

Failure today: verified replanning exists only in selected handlers; no three-surface closure.

Existing foundation: browser/desktop semantic re-ground, managed research, file drift rejection, bounded cognition.

Missing closure: routing/investigation must adapt to the current world instead of requiring a pre-shaped task family.

Acceptance E2E: browser -> file -> desktop with one induced state drift and independently verified final state.

### 5. Installed N -> N+1 identity/data/Work continuity

User scenario: the long-lived Resident upgrades without losing identity, Work or uncertain-effect safety.

Failure today: only clean install and same-home runtime-restart foundations are proven.

Existing foundation: persistent home/Self/Work, update observation/artifact verification, packaging.

Missing closure: real installed version transition, migration, active/uncertain Work preservation, rollback/trust evidence.

Acceptance E2E: installed N with durable state -> installed N+1 -> same subject/work continuity + no duplicate uncertain effect.

## Supporting / deferred work

The following are not the current product mainline unless they directly block one of the gaps/E2Es above:

- installer optimization;
- release-candidate choreography;
- signing/release automation;
- CI expansion;
- BUG-report transport/intake/deployment;
- maintainer transport/handoff formatting;
- governance abstractions;
- provider abstractions;
- new organ/Agent/state-machine abstractions.

Keep existing implementations and historical evidence; do not let them automatically become the next product priority.

## Real User E2E Acceptance Matrix

See [`ZN-REAL-USER-E2E.md`](ZN-REAL-USER-E2E.md).

At the observed checkpoint the matrix intentionally claims **0 / 20 broad categories as Product-closed**. Multiple narrow vertical slices are real and verified, but current CI failures, limited routing breadth, missing cross-surface combinations, incomplete natural Work continuation and unverified installed upgrade continuity prevent a broader maturity claim.
