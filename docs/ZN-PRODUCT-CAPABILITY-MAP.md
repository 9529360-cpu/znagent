# ZN Product Capability Map

> This is a current product-completeness map, not an agent-feature checklist and not a commit log.
>
> Architecture authority: [`../ZN.md`](../ZN.md). Implementation/evidence detail: [`ZN-IMPLEMENTATION-STATUS.md`](ZN-IMPLEMENTATION-STATUS.md). Real-user acceptance: [`ZN-REAL-USER-E2E.md`](ZN-REAL-USER-E2E.md).
>
> Real code/Git and actual runtime/tests/CI override this file when they disagree.

Updated: 2026-09-04

## Maturity vocabulary

Use the same maturity language across current product documents:

- **Exists** — implementation is present;
- **Connected** — the real product path uses it;
- **Verified** — bounded runtime/test/E2E evidence proves the slice;
- **Product-closed** — an ordinary user task is reliably closed from normal-language entrance through recovery/replanning, independent result verification and relevant continuity;
- **Partial / Experimental / Blocked** — useful but incomplete or currently failing.

Do not convert `Verified` into `Product-closed` merely because the underlying primitive is reliable.

## Current product picture

ZN already has a substantial connected substrate: persistent Resident state, Work, browser planes, desktop/UIA, file Body actions, bounded cognition, fresh-evidence action contracts, non-replay recovery and completion verification mechanisms.

The current development branch also has several real Windows vertical slices that go beyond primitive demos:

- explicitly authorized existing authenticated browser work;
- authenticated textbox -> button -> result-page work;
- managed research that preserves and returns to the authorized user browser;
- browser semantic re-ground after page label/node drift;
- browser -> file work;
- file -> desktop work;
- desktop semantic re-ground after UI drift.

However, current dev is not CI-green and the broad product remains incomplete. The acceptance matrix intentionally claims zero broad categories as Product-closed at the 2026-09-04 checkpoint.

## Subject / Resident continuity

| Product need | Current maturity | Current truth / limitation |
| --- | --- | --- |
| Persistent Resident identity independent of models | Connected + Verified | Self/resident state is repository-owned and model-independent. This does not by itself prove arbitrary long-term user-task continuity. |
| Resident process independent of desktop renderer | Connected + Verified | Socket/service lifecycle and reconnect behavior are covered by core tests. |
| Durable Work/thread/event state | Connected + Verified / Partial UX | Work survives normal persistence/restart paths, but natural `昨天那个继续` is not merged on current dev. |
| Same-home runtime restart continuity | Verified foundation | Core test preserves selected Self fields and Work thread data across `runtime-n` -> `runtime-n-plus-1`. This is not an installed N -> N+1 upgrade. |
| Natural prior-Work continuation | Missing on current dev | Open PR #166 implements a bounded resolver/follow-up lane but is not current dev truth and is behind live dev. |
| Active-task steering | Missing | PR #166 explicitly leaves new instructions during active referenced Work as a separate product problem. |
| Installed N -> N+1 identity/data/Work continuity | Partial / Not product-verified | Clean install and same-home restart foundations exist; real installed replacement, migration, uncertain-work continuity, rollback and signing/trust are unproven. |

## User Browser Bridge

| Product need | Current maturity | Current truth / limitation |
| --- | --- | --- |
| Use an existing authenticated Edge/Chrome session | Connected + Verified / Partial | Real Windows extension E2E establishes authentication before Resident starts, explicitly authorizes the current tab, uses the existing session and proves no login replay is needed. Evidence still uses a controlled test profile and broader context routing remains incomplete. |
| Explicit current-tab authorization | Connected + Verified | User extension action authorizes one exact HTTP(S) tab; another tab cannot silently inherit authority. |
| Authorization revoke | Connected + Verified / Partial UX | User can revoke; a test proves revoke after grounding produces zero action/replay/substitution and leaves browser alive. No full permission-center UX yet. |
| Existing-session multi-step form | Connected + Verified / Partial | Exact safe textbox -> fresh Sense -> exact button -> final authenticated result is verified. Arbitrary form shapes, uploads, complex dialogs/frames and sensitive entry are not closed. |
| Ordinary semantic browser lookup | Connected + Verified / Partial | Bounded cognition proposes business semantics only; Resident grounds current safe candidates, binds exact identity and verifies fresh result. Task family remains bounded. |
| Page label/node drift re-ground | Connected + Verified / Partial | Old binding is rejected and current candidates are re-grounded in the verified semantic task. Not yet a general browser replanner. |
| Multiple lookalike tabs/windows and context drift | Blocked / Partial | Extension semantic path protects exact authorized tab/decoy case, but current Windows suite still exposes direct-CDP multi-visible-page ambiguity and a legacy foreground-title failure. |
| Sensitive browser-field protection | Connected + Verified narrow | Password, OTP and payment autocomplete classes are refused; semantic sensitive-target test produces zero actions. Broader future surfaces must preserve equivalent protection. |
| Cookie/password/profile copying into managed browser | Intentionally not a capability | Existing-session access is through bounded authorization/bridge, not raw credential extraction. |

## Managed Browser

| Product need | Current maturity | Current truth / limitation |
| --- | --- | --- |
| Isolated managed Chromium | Connected + Verified / Partial | Managed Chromium is used without the user's browser-session cookie in verified cross-browser research. |
| Bounded navigation/semantic interactions | Connected + Verified | Narrow exact-target interactions and postconditions exist. Do not infer arbitrary browsing UI coverage. |
| Multi-source research | Connected + Verified / Partial | Current managed research can inspect multiple references, follow a detail page and require two-source agreement for the bounded task. General autonomous research goals are not product-closed. |
| Preserve user browser while researching elsewhere | Connected + Verified / Partial | Verified task keeps the authorized user tab, researches in managed Chromium, then freshly re-senses the exact user tab before continuing. |
| Broad tabs/popups/frames/downloads/uploads/headed UX | Partial / Missing | Some low-level page lifecycle exists, but broad real-user product closure is absent. |

## Desktop / Computer Use

| Product need | Current maturity | Current truth / limitation |
| --- | --- | --- |
| Foreground/window/UIA sensing | Connected + Verified foundation | Used by real desktop task paths. |
| Ordinary-language semantic desktop goal | Connected + Verified / Partial | Cognition may propose semantics; Resident senses safe current candidates and retains exact UIA identity/authority. |
| Safe Edit/Button task | Connected + Verified / Partial | Real Windows paths perform bounded input/click and verify final app state. Broad application control is not closed. |
| UI label/runtime identity drift re-ground | Connected + Verified / Partial | Current dev re-senses current safe candidates and re-binds semantics after stale labels/RuntimeIds. |
| Broad menus/dialogs/tree/list/app lifecycle | Partial / Missing | No broad real-user closure claim. |

## Files / Workspace

| Product need | Current maturity | Current truth / limitation |
| --- | --- | --- |
| Find/compare/read exact workspace text file | Connected + Verified / Partial | Candidate discovery/comparison and exact identity are used by current natural file tasks. |
| Verified text edit + reread | Connected + Verified / Partial | Browser -> file E2E writes exactly one target and verifies fresh reread while leaving another plausible candidate unchanged. |
| Stale source rejection before downstream desktop input | Connected + Verified / Partial | File -> desktop E2E changes the source before keyboard input, rejects stale evidence, re-senses and completes. |
| Ambiguous workspace source fail-closed | Blocked | Current Kernel/Python CI reports one edit call in a case that requires zero side effects under ambiguity. |
| Broad document/file transformation and organization | Partial / Missing | Current verified tasks are narrow workspace text flows. |

## Cross-surface tasks

| Product need | Current maturity | Current truth / limitation |
| --- | --- | --- |
| Managed research -> authorized user browser | Verified / Partial | Real Windows vertical slice exists. |
| Browser -> file | Verified / Partial | Real Windows vertical slice exists with independent server + filesystem evidence. |
| File -> desktop | Verified / Partial | Real Windows vertical slice exists with stale-source recovery and final app verification. |
| Browser -> desktop | Missing / Not verified | Browser and desktop capabilities exist independently; no dedicated current real-user E2E closes this path as one Work. |
| Browser + file + desktop | Missing | No current three-surface real-user closure. |

## Investigation / Replanning

| Product need | Current maturity | Current truth / limitation |
| --- | --- | --- |
| Fresh re-sense after browser semantic drift | Connected + Verified narrow | Verified in selected semantic lookup path. |
| Fresh re-sense after desktop semantic drift | Connected + Verified narrow | Verified in selected desktop path. |
| Investigate alternate/detail source when first page is insufficient | Connected + Verified narrow | Managed research follows a detail page in the current reference task. |
| Reject stale file evidence and investigate again | Connected + Verified narrow | Verified in file -> desktop path. |
| General investigation/replanning across arbitrary reasonable goals | Partial / Missing | Current routing still relies significantly on task-family-specific bounded handlers/cues. |

## Completion Verification

| Product need | Current maturity | Current truth / limitation |
| --- | --- | --- |
| Browser final-result verification | Connected + Verified / Partial | Fresh URL/anchored page evidence plus independent HTTP-server/foreground evidence are used in current E2Es. |
| File result verification | Connected + Verified / Partial | Fresh filesystem reread is used after current file mutation. |
| Desktop result verification | Connected + Verified / Partial | Final application title/UI state is independently checked in current Windows tasks. |
| Global completion judgment across all task families | Partial | Every new task family still needs an explicit independent result condition. Movement/API/model success is not completion. |

## Safety / Authority / Non-replay

| Product need | Current maturity | Current truth / limitation |
| --- | --- | --- |
| Model does not own fact/identity/authority/completion | Connected + Verified architecture | Current browser/desktop semantic proposals are bounded to semantics/candidate selection; exact world identity remains Resident evidence. |
| Fresh authority before side effects | Connected + Verified / Partial coverage | Used in current browser/file/desktop lifecycles. |
| Unknown external effect not blindly replayed | Connected + Verified / Partial coverage | Browser extension relay/action paths distinguish uncertain delivery/effect from safe pre-dispatch failure. |
| Sensitive field/credential protection | Connected + Verified narrow | Browser fields are conservatively filtered; raw user browser credentials/session stores are not copied into managed browser. |
| Product-wide permission center | Missing | Explicit one-tab authorization exists, but general site/account/capability permission management is not closed. |

## Product UI / observability

| Product need | Current maturity | Current truth / limitation |
| --- | --- | --- |
| Native desktop surface / Work visibility | Connected + Partial | Desktop Work surface exists and can follow resident-returned thread/event state. |
| User-visible browser authorization state | Connected + Partial | Extension badge/action gives explicit authorize/revoke control for one tab. Broader permission/history UX is absent. |
| User-visible continuation/steering UX | Missing / Partial | Durable Work exists, but natural prior-Work continuation is not merged and active steering is missing. |
| Failure/recovery explanation | Partial | Internal state/evidence exists; ordinary-user recovery UX remains incomplete. |

## Deployment / Upgrade / Release

| Product need | Current maturity | Current truth / limitation |
| --- | --- | --- |
| Clean Windows install | Verified current workflow | Current clean-install run succeeds. This is a test/deployment fact, not proof of mature resident behavior. |
| Update observation/artifact verification | Connected / Partial | Foundations exist. |
| Installed N -> N+1 continuity | Partial / Not product-verified | No real installed transition proves identity/data/Work/uncertain-effect continuity. |
| Rollback | Not verified for long-term product continuity | Do not infer from updater/install code presence. |
| Signing/release trust | Incomplete / approval-gated | Supporting release lane, not current real-task priority. |

## Self-maintenance / reporting

Existing self-maintenance, BUG-report, repair/intake and repository-maintenance mechanisms are historical/engineering capabilities. They are **supporting work**, not the current product mainline.

They should be revisited only when a concrete real-user task, Resident continuity issue, user-data risk or safety boundary is directly blocked by them. Do not treat their code/test/CI maturity as evidence that ZN can complete more ordinary user tasks.

## Current five product gaps

The detailed evidence and acceptance E2Es are in `ZN-IMPLEMENTATION-STATUS.md` and `ZN-REAL-USER-E2E.md`. The current five are:

1. existing-session browser context identity under realistic multi-tab/window drift;
2. ambiguous workspace source must remain zero-side-effect;
3. natural Work continuation and active-task steering;
4. general investigation/replanning across browser + file + desktop;
5. installed N -> N+1 Resident/data/Work continuity.

## Product-completeness rule

The next milestone is not another primitive, provider, CI workflow, installer stage or governance layer.

A product milestone should be expressible as:

```text
an ordinary user says one normal goal
-> ZN senses the real current environment
-> ZN chooses and executes the needed surfaces/steps
-> reality changes
-> ZN re-senses and replans instead of blindly failing/replaying
-> ZN independently verifies the requested outcome
-> the Work remains durable for future continuation
```

If a proposed mainline change cannot name the real-user E2E that moves from failure/partial toward verified/product-closed, reassess whether it belongs on the current product line.
