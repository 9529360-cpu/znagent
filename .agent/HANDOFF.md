# ZN Maintainer Handoff

This is the current maintainer checkpoint for ZN product work. It is a fact index, not a chat transcript, roadmap oracle or live Git mirror.

Real code and live Git state override this file. Actual tests/builds/CI override documentation claims. A merged PR, passing focused test or existing module is never enough by itself to claim a user task is product-closed.

## Current truth

Observed on 2026-09-04:

- repository: `9529360-cpu/znagent`;
- canonical/release branch `main`: `0dbec575fc128bd1cc1837e7485b5a37e0ac8393` (`Promote verified user-browser focused text entry`, PR #126 era);
- primary development branch `dev/zn-agent`: `af8754ae1ee0d0b3491cbad2134dd6e12edda5f9` (`Re-ground desktop semantic goals after runtime UI drift`, PR #173);
- `main...dev/zn-agent` is **diverged**: dev is 223 commits ahead and 1 commit behind main at the observed comparison. This is repository/release hygiene, not a product milestone;
- documentation-only reconciliation branch for this checkpoint: `work/docs-product-truth-20260904`; it must not be mistaken for a product implementation lane;
- open product PR #166, `Continue durable Work from natural references and fresh follow-ups`, head `work/natural-work-continuation` at `0c6d26b9efd4857670a1eb51bd6825e0445d049f`, base `dev/zn-agent`;
- open documentation-only PR #174, `Sync product docs to current real-task evidence`, head `work/docs-product-truth-20260904`, base `dev/zn-agent`; it changes documentation only and is not product capability evidence;
- PR #166 is currently diverged from live dev: 12 commits ahead and 5 commits behind. No PR-trigger workflow run was visible for its current head when checked. Its code is therefore an **open product lane**, not current dev capability;
- recent merged product work includes #173 desktop semantic re-grounding, #172 managed research from the authorized user page, #171 ordinary browser semantic grounding in the authorized existing session, #170 desktop semantic grounding and #164/#163 browser-result-to-file closure.

### Current CI truth

For current dev head `af8754ae...`:

- `ZN Windows Clean Install` run `33806840503`: **success**;
- Source Boundary in `ZN CI` run `33806840435`: **success**;
- Electron/TypeScript in `ZN CI` run `33806840435`: **success**;
- Kernel/Python in `ZN CI` run `33806840435`: **failure** — 1006 tests ran, 1 failed, 5 skipped. The failure is `test_model_understood_goal_still_fails_closed_on_ambiguous_workspace_source`; the test observed one edit call where ambiguous workspace evidence requires zero;
- `ZN Windows Interactive Desktop E2E` run `33806840505`: **failure** — 33 tests ran, 31 passed, one failed and one errored.

The two current Windows Interactive failures are:

1. direct-CDP authorized-current-tab flow: `authorized user-browser current tab is ambiguous: multiple visible pages`;
2. legacy named-browser flow: `foreground browser window has no stable title`.

Do not summarize the current dev as CI-green or runtime-healthy.

## Active product lane

The product mainline is **real-task autonomous closure**, not maintenance/reporting, installer, release or primitive capability expansion.

The active product question is:

> Can an ordinary user state a normal goal, let ZN inspect the real current computer, and have the same Resident carry the work across the required surfaces, re-sense/replan when reality changes, verify the real result and continue later without replaying unsafe side effects?

Open PR #166 is relevant because natural Work continuation is a real product gap. It is not merged truth and it does not close active-task steering.

## What ZN can actually do now

The following are **verified bounded user-level slices on current dev**, not broad product-completion claims.

### Existing authenticated browser session

A real Windows Interactive extension path can:

- start with a browser session authenticated before Resident exists;
- require an explicit extension action on one current HTTP(S) tab;
- keep authorization tied to that exact tab;
- use the user's existing session without copying the session cookie, password database or profile into ZN;
- revoke the tab authorization while leaving the browser running;
- reject password/OTP/payment-class text targets;
- stop without replay/substitution if authorization is revoked before a movement.

Evidence: current production `user_browser_extension_relay.py`, `user_browser_extension_resident.py`, extension `background.js`, and passing tests inside Windows run `33806840505`.

### Authenticated form task

The existing-session path can complete a bounded multi-step task:

```text
existing authenticated tab
-> explicit authorization
-> exact safe textbox entry
-> fresh Sense
-> exact button click
-> page transition
-> fresh final URL/result verification
```

The E2E independently verifies the authenticated result through the HTTP server and Windows foreground state. This is verified for the bounded form shape; it is not generic arbitrary-form automation.

### Managed research -> return to user browser

ZN can preserve the explicitly authorized user tab, use isolated managed Chromium to inspect multiple reference pages, follow a detail page when the initial source is insufficient, establish two-source agreement, then return to and freshly re-sense the authorized tab before one guarded mutation. Managed Chromium does not receive the user-session cookie in the verified E2E.

### Ordinary browser semantic goal + drift re-ground

For a bounded normal-language lookup, cognition may propose only business semantics. Resident senses safe candidates from the exact authorized tab, binds exact current node identity, revalidates before action, freshly senses again between text and submit, and verifies a fresh anchored result. If labels/nodes drift, the old binding is rejected and the semantic goal can be re-grounded to current candidates. An identical foreground decoy tab does not receive authority in the verified extension path.

### Browser -> file

A normal-language Windows task can use the existing authenticated user page as context, research two managed sources, replan to a source detail page, select one exact workspace text file, change it exactly once, leave another plausible candidate unchanged, reread the file and finalize the same Work. Browser research provides evidence; it does not itself grant file mutation authority.

### File -> desktop

A bounded ordinary-language Windows task can find a workspace value, ground the current desktop application's safe Edit/Button controls, detect that the source file changed before keyboard input, reject stale source evidence, re-sense, continue and verify the final application state. The current E2E records one keyboard movement and one submit path after recovery.

### Desktop semantic re-ground

ZN can preserve a semantic desktop goal when current UI labels/runtime identities drift, re-sense safe current UIA candidates, reject the old exact binding, re-ground bounded semantics and verify the final application state. Duplicate equally named candidates fail closed before input in the passing interactive scenario.

## Current failures and product gaps

### 1. Existing-session browser context identity is not stable across all real paths

User scenario: several browser windows/tabs are visible while the user authorizes one tab and gives an ordinary task.

What works: the extension semantic path binds exact authorized tab identity, survives a foreground decoy and supports explicit revoke.

What still fails: the current Windows suite still contains a direct-CDP path that cannot choose among multiple visible pages and a legacy named-browser path that can lose a stable foreground title.

Closure needed: ordinary existing-session work should use one explicit, fresh, revocable browser identity contract instead of falling through to fragile foreground/current-tab guesses.

Acceptance E2E: authorize one real logged-in tab, create multiple visible lookalike tabs/windows and title/focus drift, give one normal-language task, prove only the authorized tab changes and the final result is independently verified.

### 2. Ambiguous workspace evidence currently has a fail-closed regression

User scenario: a normal-language workspace/desktop task has more than one plausible source file.

Current failure: Kernel/Python CI shows `test_model_understood_goal_still_fails_closed_on_ambiguous_workspace_source` observed one edit call where the contract requires zero mutation under ambiguity.

Existing foundation: exact file identity, candidate comparison, stale-source rejection and verified file/desktop flows already exist.

Closure needed: ambiguity must remain an information problem; it must never leak into a side effect before one exact source is freshly established.

Acceptance E2E: two equally plausible real workspace files + ordinary desktop goal -> zero file/desktop mutation and explicit unresolved state; after a real disambiguating observation/instruction, re-sense and complete exactly once.

### 3. Work continuity is not yet a complete user experience

User scenario: `刚才那个继续`, `昨天那个继续`, or a fresh follow-up to earlier Work.

Current dev: durable Work/restart mechanisms exist, but the natural-reference resolver is not merged.

Open lane: PR #166 implements natural references and completed-Work follow-up on a separate branch, but it is 5 commits behind current dev and lacks current-head CI evidence.

Still missing even in that PR: active-task steering. A new instruction while the referenced event is active is explicitly refused instead of incorporated.

Acceptance E2E: restart Resident, say `昨天那个继续`, reconnect to the one correct durable Work, freshly re-sense the current computer and continue without replaying prior side effects; then steer an active task with a new user instruction while preserving the same Work identity.

### 4. Investigation/replanning and cross-surface routing are still narrow

User scenario: a reasonable goal does not match one of the currently encoded task families, or the path changes after a popup/page/app/file-state change.

Existing foundation: semantic browser grounding, desktop semantic grounding/re-ground, managed-source detail replanning, exact file re-sensing and bounded model goal proposals.

Current limitation: important flows still have task-specific regex/cue routing and dedicated composite handlers. There is no evidence that arbitrary reasonable browser -> desktop or browser + file + desktop goals can be investigated and closed as one Work.

Acceptance E2E: one normal-language three-surface task where ZN must discover the route, move browser -> file -> desktop, encounter one deliberate state change, replan and independently verify the final result.

### 5. Installed upgrade/data continuity is not product-verified

User scenario: a long-lived installed Resident moves from N to N+1 without becoming a new subject or losing/replaying Work.

Existing foundation: current clean-install workflow is green; a core test restarts different runtime IDs on the same home and preserves Self `born_at`/name/pulse plus Work-thread data.

Not proven: real installed N -> N+1 replacement, schema migration, active/uncertain Work continuity, rollback and signing/trust.

Acceptance E2E: installed N with real durable Self/Work state -> installed N+1 -> same continuity evidence, no duplicate uncertain side effect, verified migration/result; rollback/trust remain separate high-risk stages.

## Next product priorities

Order these by real-user impact, not by existing implementation momentum:

1. restore the ambiguous-workspace zero-side-effect safety boundary and prove it with a real-user-style acceptance path;
2. stabilize existing-session browser context identity/routing under multiple visible tabs/windows and foreground/title drift;
3. reconcile and verify natural durable Work continuation, then separately close active-task steering;
4. build one browser + file + desktop vertical task and use its failures to drive only the replanning/routing work actually required;
5. keep installed N -> N+1 continuity as a long-term critical lane, but do not let updater/release work displace the real-task gaps above unless continuity work is directly blocking them.

## Supporting / deferred work

The following remain legitimate engineering capabilities but are **not the current product mainline** unless they directly block a real user E2E, user data, Resident continuity or a safety boundary:

- installer optimization;
- release candidate/promotion choreography;
- signing and release trust;
- extra CI orchestration;
- BUG-report transport/intake and maintainer deployment;
- maintenance handoff/transport mechanics;
- governance abstractions;
- new provider abstractions;
- new Agent/organ/state-machine abstractions.

Do not delete historical implementation in these areas merely because it is not the current priority.

## Real User E2E status

See `docs/ZN-REAL-USER-E2E.md` for the 20-row acceptance matrix.

At this checkpoint the matrix intentionally claims **0 broad categories as Product-closed**. Several narrow vertical slices are verified and useful, but the current CI failures, routing breadth, missing cross-surface combinations, incomplete natural continuity and unverified installed upgrade prevent a broader maturity claim.

## Do not mistake for completion

- merged PR != product closed;
- focused test passed != user task closed;
- CI green != runtime healthy;
- current CI is not green anyway;
- code/interface exists != mature capability;
- browser extension installed != permission/product UX closed;
- clean install succeeded != long-term safe upgrade proven;
- durable Work tables/restart tests != `昨天那个继续` product experience;
- model produced a plan/answer != fact, authority, identity or completion;
- click/keypress/HTTP success/command exit != requested user outcome.

## Handoff discipline

On takeover, re-query live refs, open PRs and CI before acting. The SHAs/run IDs above are observed checkpoints only.

Do not make document synchronization itself the next product milestone. Use these documents to choose one real user E2E, inspect the real caller/evidence chain, close only the missing pieces required for that E2E, then update the facts again.
