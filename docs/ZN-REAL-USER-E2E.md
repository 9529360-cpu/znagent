# ZN Real User E2E Acceptance Matrix

This file answers one product question:

> What can an ordinary user currently hand to ZN as a normal task and have ZN carry through the real computer?

It is not a primitive-capability checklist and it is not a test-count ledger. Real code, live Git state and actual runtime/E2E evidence override this file.

Observed checkpoint for this reconciliation: `dev/zn-agent` at `af8754ae1ee0d0b3491cbad2134dd6e12edda5f9` on 2026-09-04.

## Maturity vocabulary

- **Exists** — implementation is present.
- **Connected** — the real product call path uses it.
- **Verified** — focused test, runtime or E2E evidence proves the bounded scenario.
- **Product-closed** — an ordinary normal-language task is reliably closed end to end, including relevant state changes, failure/replanning, independent result verification and continuity.
- **Partial** — useful verified slices exist, but the category is not product-closed.
- **Missing** — no current product path/evidence closes the user task.
- **Blocked** — a known current failure prevents a reliable claim.

A passing narrow E2E may justify `Verified` for that slice without making the whole row `Product-closed`.

## Current live evidence boundary

The current `dev/zn-agent` Windows Interactive run `33806840505` executed 33 tests and finished **failure**: 31 passed, one failed and one errored. The two current failures are:

- direct-CDP authorized-current-tab work fails closed when multiple visible pages make the current tab ambiguous;
- the legacy named-browser path can fail because the foreground browser window has no stable title.

The same run produced successful real interactive evidence for the explicitly authorized extension session, authenticated form work, semantic browser re-grounding, managed research return, browser-to-file work, file-to-desktop work and desktop semantic re-grounding.

The current Kernel/Python job in run `33806840435` is also **failure**: 1006 tests ran with one failure and five skips. The failing regression is `test_model_understood_goal_still_fails_closed_on_ambiguous_workspace_source`, where an ambiguous workspace-source scenario observed one edit call instead of the required zero.

Therefore no category below should be inferred product-closed merely from the presence of successful neighboring E2Es.

## Acceptance matrix

| # | Real user task | Current maturity | Evidence | Known failure / limitation | Next blocker |
| --- | --- | --- | --- | --- | --- |
| 1 | Real web information retrieval | Verified / Partial | Managed Chromium can inspect bounded reference pages, follow a detail page when the landing page lacks the fact, and establish two-source agreement before continuing. | The verified investigation is a narrow release-code/reference flow, not general-purpose web research from arbitrary goals. | General investigation goals, source selection and synthesis without task-specific cue parsers. |
| 2 | Existing authenticated browser session | Verified / Partial | Real Windows extension E2E starts the browser session before Resident, authorizes one current tab by explicit extension action, uses the existing authenticated session and does not transfer cookies/credentials to ZN. | Evidence uses a controlled temporary test user profile; other user-browser paths still have current context-identity failures with multiple visible pages or unstable foreground title. | Stable product routing around explicit authorized-tab identity in ordinary multi-tab/multi-window user sessions. |
| 3 | Multi-step authenticated web form | Verified / Partial | Existing-session E2E types one exact safe textbox, freshly senses, clicks one exact button, crosses a page transition and verifies the authenticated result through server + Windows foreground evidence. | Bounded native textbox/button form shape; not broad arbitrary forms, validation flows, popups, uploads or sensitive fields. | Broader semantic form interaction while preserving fresh authority and postconditions. |
| 4 | Managed research while preserving user browser context | Verified / Partial | Managed research opens isolated Chromium, reads multiple sources without the user's session cookie, then returns to and freshly re-senses the exact authorized user tab before one guarded mutation. | Current routing is task-specific and bounded to reference/release-code research. | General investigation/replanning policy that can decide when to leave and return to the user browser. |
| 5 | Desktop application task | Verified / Partial | Real Windows semantic desktop E2Es understand an ordinary goal, ground safe UIA Edit/Button candidates, reject stale RuntimeIds, re-ground after label drift and verify the final application title/state. | Narrow safe Edit/Button flows in the current foreground non-browser app; no broad menus/dialogs/complex app navigation claim. | Broader desktop semantic investigation and recovery across real application state changes. |
| 6 | File find / read / edit / verify | Verified / Partial | Natural workspace file logic discovers candidates, compares contents, binds exact file identity, performs one overwrite and verifies by fresh reread; browser-to-file E2E proves exact file selection and leaves another plausible candidate unchanged. | Workspace language and edit shapes remain narrow; current Kernel/Python CI exposes an ambiguity fail-closed regression in a model-understood workspace-source path. | Restore zero-side-effect ambiguity handling, then expand file tasks without bypassing exact identity. |
| 7 | Browser -> file | Verified / Partial | Windows E2E researches two managed sources from an explicitly authorized existing session, selects one exact workspace file, writes exactly once, rereads it and finalizes the same Work. | One bounded reference-code -> text-file edit scenario. | General cross-surface data transfer and file intent grounding. |
| 8 | Browser -> desktop application | Missing / Not verified | Browser and desktop capabilities exist independently. | No dedicated current real-user Windows Interactive E2E proves a browser result carried into a non-browser desktop application as one Work. | One normal-language browser-to-desktop vertical task with independent final app verification. |
| 9 | File -> desktop application | Verified / Partial | Windows E2E reads a workspace value, detects source drift before input, rejects stale source evidence, re-senses and completes the desktop task with exactly one keyboard action and one submit. | Narrow current app/control shape; still depends on bounded semantic routing. | Broader desktop task shapes and interruption/continuation coverage. |
| 10 | Browser + file + desktop in one Work | Missing | The component two-surface paths exist. | No current E2E closes all three surfaces in one user task. | One three-surface real task that carries evidence without turning prior results into authority. |
| 11 | Page/state change -> replan | Verified / Partial | Browser semantic E2E changes labels/nodes after grounding and ZN rejects the old binding, freshly re-grounds and completes; managed research follows a source-B detail page when the landing page lacks the fact. | Replanning is implemented in selected bounded flows, not as a general investigation loop across all surfaces. | Generalize fresh Sense/Situation/Thought/replan beyond hard-coded task families. |
| 12 | Window / tab drift | Partial / Blocked | Extension semantic E2E proves an identical foreground decoy tab never receives authority and the authorized tab stays bound. | Current Windows run still fails direct-CDP current-tab selection with multiple visible pages and errors when a legacy named-browser probe lacks a stable foreground title. | Unify browser context identity/routing around explicit authorization and fresh evidence. |
| 13 | Work interruption / restart recovery | Verified / Partial | Durable Work/state and selected non-replay recovery lifecycles exist; same-home Resident process restart continuity is covered by core tests. | There is no current real-user Windows E2E showing an interrupted ordinary task resumed through a natural user continuation phrase. | User-visible continuity entry that reconnects to durable Work and re-senses before action. |
| 14 | "昨天那个继续" / natural prior-Work reference | Missing on current dev | Open PR #166 implements this on `work/natural-work-continuation`, but it is not merged into current `dev/zn-agent`. | PR #166 is 5 commits behind current dev, has no visible PR-trigger workflow run at its current head, and is not current product truth. | Reconcile the lane with current dev, verify restart/ambiguity/non-replay behavior, then merge only if evidence is green. |
| 15 | Active task steering | Missing | Open PR #166 explicitly treats active-task steering as a separate product problem. | New instructions while referenced Work is active are not product-closed steering. | Safe in-flight user steering that preserves event identity, authority and non-replay. |
| 16 | Sensitive field protection | Verified / Partial | Extension implementation excludes password, OTP and payment autocomplete classes; Windows semantic E2E proves a sensitive semantic target cannot be selected and produces zero actions. | Coverage is strongest for current browser textbox semantics, not every future surface/connector. | Keep equivalent redaction/refusal guarantees as surfaces broaden. |
| 17 | Authorization revoke | Verified / Partial | User can revoke the extension-authorized tab; semantic E2E proves revoke after grounding stops with zero action/replay/substitution, and form E2E proves the browser process remains alive. | No complete user-facing permission center or durable per-site grant management. | Product permission UX, scope visibility and revocation across sessions/capabilities. |
| 18 | Side-effect non-replay | Verified / Partial | Relay distinguishes uncertain delivered commands from pre-dispatch failure; action lifecycles re-sense rather than blindly replay. Selected browser/file/desktop tests prove exactly-once or zero-action behavior. | Semantics are not unified/product-proven for every external side effect. | Expand only alongside concrete user E2Es and explicit postconditions. |
| 19 | Independent result verification | Verified / Partial | Current E2Es use independent HTTP server observations, filesystem reread, Windows foreground/UIA evidence and exact final-state checks rather than trusting action return values. | Not every task family has an independent verifier yet. | Make result verification a required closure condition for each new vertical task. |
| 20 | N -> N+1 Resident continuity | Partial / Not product-verified | Core test restarts two runtime identities on the same home and proves Self `born_at`/name/pulse continuity plus Work-thread continuity. Current clean-install workflow succeeds. | This is not a real installed N -> N+1 replacement. Schema migration, active/uncertain Work continuity, rollback and signing/trust are not proven. | A bounded installed upgrade experiment that preserves identity/data/Work and handles uncertain side effects without replay. |

## Product-closed count

At this checkpoint, this matrix intentionally claims **0 / 20 categories as Product-closed**.

That does not mean ZN has no useful capability. Several meaningful vertical slices are real and repeatedly verified. It means the evidence still shows narrow task shapes, current CI failures, missing cross-surface combinations, incomplete natural Work continuation and incomplete installed upgrade continuity. Calling those broad categories product-closed would overstate the current user experience.

## How to use this matrix

Choose the next product task by asking which row can move from `Missing/Blocked/Partial` toward `Verified` or `Product-closed` through one coherent normal-language E2E. Do not choose a primitive, provider abstraction, installer improvement, CI expansion or governance layer unless it directly blocks that E2E.
