# ZN product capability map

> This is a product-completeness ledger, not an agent-feature checklist.
>
> Architecture authority remains [`../ZN.md`](../ZN.md). Real code and real verification outrank this file.

Updated: 2026-08-26

## 1. Why this ledger exists

ZN must keep pace with useful capabilities demonstrated by current coding agents, computer-use agents and AI work systems without becoming an agent harness whose identity is a planner/model/tool loop.

The comparison rule is:

```text
market capability proves a user need exists
-> decide whether that need belongs to ZN
-> map it to a ZN-owned organ/resource/lifecycle
-> implement behind ZN-owned authority and state
-> verify effects from current-world evidence
-> keep providers/models replaceable
```

Passing one narrow E2E is evidence for one slice, not product completion.

Status vocabulary:

- `VERIFIED`: real implementation plus relevant real tests/CI/evidence exist.
- `PARTIAL`: useful implementation exists but product lifecycle/coverage is incomplete.
- `FOUNDATION`: owned contracts or early implementation exist, but the user-facing capability is not complete.
- `OPEN`: required product capability not yet implemented.
- `DEFERRED`: deliberately not current priority; not silently forgotten.

## 2. Subject / continuity

| Product need | ZN owner | Status | Current evidence / open work |
| --- | --- | --- | --- |
| Persistent identity independent of models | Self / resident life | VERIFIED | zero-model resident boot and persistent resident state are CI-guarded |
| Long-lived process independent of desktop window | resident / service | VERIFIED | desktop starts resident; identity is not renderer-owned |
| Situation / Thought / Will continuity | resident life | VERIFIED/PARTIAL | resident-owned lifecycle exists; broader real-world competence continues to grow |
| Provider replacement without identity loss | CognitiveResource boundary | VERIFIED | model routes are optional resources, not resident identity |
| Safe body/version handoff | update/release lifecycle | PARTIAL | architecture exists; Windows M8 install/upgrade/rollback/signing evidence remains open |

## 3. Memory / learning / competence

| Product need | ZN owner | Status | Current evidence / open work |
| --- | --- | --- | --- |
| Durable lived memory | nervous system / memory | VERIFIED/PARTIAL | persistent memory and reconsolidation mechanisms exist |
| Procedural learning gated by current reality | learning / Will | VERIFIED/PARTIAL | learned tendencies cannot replace fresh authority; breadth remains limited |
| Reusable deterministic skills/capabilities | resident competence | PARTIAL | `CapabilityRegistry` and promoted capabilities exist; installable/shareable skill lifecycle remains open |
| Forgetting/inhibition when evidence contradicts | nervous system | PARTIAL | architecture/tests exist; more real-world longitudinal evidence needed |
| User-visible memory controls and provenance | Self / memory UI | OPEN | needs inspect/edit/forget/provenance UX without exposing internal secrets |

## 4. Files / workspace / terminal / code

| Product need | ZN owner | Status | Current evidence / open work |
| --- | --- | --- | --- |
| Safe file read/write/move operations | Body | VERIFIED/PARTIAL | typed Body operations exist; broader desktop file workflows remain open |
| Terminal/process execution | Body | VERIFIED | bounded terminal/process mechanisms and tests exist |
| Git repository sensing and actions | Body/Senses | VERIFIED/PARTIAL | repository evidence and guarded actions exist; broader collaboration flows can expand |
| Code investigation/test/fix loop | Investigation / Action | VERIFIED/PARTIAL | repo-test semantics and evidence-based completion exist |
| Isolated parallel worktrees/tasks | Work / Investigation | OPEN | required for mainstream multi-task parity; must be ZN-owned work isolation, not multiple identities |
| Checkpoints / restore / rollback for work | Work / Body safety | OPEN | needed for long-running edits and destructive recovery |

## 5. Web and browser

Complete browser product capability requires both planes:

```text
Resident Managed Browser + User Browser Bridge
```

| Product need | ZN owner | Status | Current evidence / open work |
| --- | --- | --- | --- |
| HTTP web search/extract | Web Senses / external resources | VERIFIED/PARTIAL | Tavily/Exa/Firecrawl resources exist with resident-owned normalization/failover |
| ZN-owned browser session/action/evidence contracts | Browser Body/Senses | FOUNDATION | session, permission, query, target, observation, action, authority and effect contracts are ZN-owned and hardened |
| Local managed Chromium, headless | Browser Body | FOUNDATION | Playwright adapter + dedicated real Windows Chromium navigation/target/focus/toggle-click/type-text/check E2E exist; lifecycle cleanup is resident-owned |
| Local managed Chromium, headed | Browser Body | OPEN | same ZN contracts, separate real UX/evidence |
| DOM/accessibility target sensing | Browser Senses | PARTIAL / VERIFIED NARROW | exact `DOM_ID` for one unique visible main-frame element is real-Chromium verified; iframe, generic accessibility, multi-target/disambiguation and visual fusion remain open |
| Managed-browser focus | Browser Body | VERIFIED NARROW | exact current target authority, execution-time exact-node revalidation, `FOCUS`, and fresh `document.activeElement` evidence are real-Chromium verified |
| Managed-browser aria-pressed toggle click | Browser Body | VERIFIED NARROW | explicit boolean expected state, exact-node continuity, fresh pre/post `aria-pressed`, and replacement rejection are real-Chromium verified |
| Managed-browser empty-textbox TYPE_TEXT | Browser Body | VERIFIED NARROW | `allow_page_interaction + allow_text_entry`, empty writable non-password text input/textarea, <=512 UTF-16 units, same-node continuity, and fresh length+SHA-256 completion evidence are real-Chromium verified |
| Managed-browser native CHECK | Browser Body | VERIFIED NARROW | enabled unchecked native `input[type=checkbox]`, `allow_page_interaction`, execution-time exact-node revalidation, provider `check()`, and fresh same-node `checked=true` evidence are real-Chromium verified |
| Managed-browser UNCHECK | Browser Body | OPEN | next action-specific lifecycle; must start from a current checked native checkbox and independently verify fresh same-node `checked=false` |
| Generic click / text replacement / ARIA checkbox / SELECT_OPTION / PRESS | Browser Body | OPEN | no generic provider success surface; each action requires a bounded independent postcondition |
| Multi-tab/popup/frame lifecycle | Browser Body/Senses | OPEN | needs stable page/frame identities and stale-target handling |
| Downloads/uploads | Browser Body + File authority | OPEN | adapter refuses these until explicit file authority exists |
| Screenshots/visual browser sensing | Browser Senses | OPEN | integrate with visual evidence rather than making pixels completion authority by themselves |
| Persistent ZN-managed browser profile | Browser state | OPEN | explicitly separate from user profiles/credentials |
| Optional cloud browser backend | Browser resource adapter | OPEN | provider may be replaceable; local browsing must not depend on it |
| Operate user's existing Edge/Chrome login session | User Browser Bridge | FOUNDATION | real Windows interactive proof shows isolated-profile Edge exposes a focused HTML input through default UIA without forced renderer accessibility; authenticated existing-session attachment/permission/mutation remain open |
| Companion extension/native messaging bridge | User Browser Bridge | OPEN | add only if real provider evidence shows it is needed and permission is explicit |
| MFA/sensitive-field handling | Permission / Body | OPEN | never silently replay/extract secrets; explicit high-risk boundaries required |

Managed mutation evidence remains deliberately narrow. Provider handles are disposable execution resources and never ZN identity. `FOCUS` requires exact-node continuity plus fresh focus evidence. `CLICK` is limited to explicit boolean `aria-pressed` transitions. `TYPE_TEXT` is limited to an empty writable non-password textbox with bounded Unicode input and privacy-safe length/digest evidence. `CHECK` is limited to an enabled unchecked native checkbox and succeeds only from fresh same-node `checked=true`. Generic click, text replacement, password entry, contenteditable, ARIA checkbox control, `UNCHECK`, select/press, and arbitrary provider methods remain unavailable until independently verified.

The User Browser Bridge provider proof remains sensing-only: it uses a temporary isolated profile and bounded focused-element/current-text evidence, not authenticated browser control.

## 6. Desktop computer use

| Product need | ZN owner | Status | Current evidence / open work |
| --- | --- | --- | --- |
| Visual region sensing | Senses | VERIFIED/PARTIAL | visual-region sensing and attention rhythm exist |
| Foreground/focused control sensing | Senses | VERIFIED | native foreground/focus evidence exists |
| Pointer movement/click with verification | Body + Senses | VERIFIED NARROW | real Windows interactive E2E exists |
| Native Win32 text entry | Body + Senses | VERIFIED NARROW | real Unicode Edit E2E, empty focused native Edit only |
| Modern UI text current-state evidence | Senses | VERIFIED NARROW | WPF read-only digest proof and real Edge focused HTML-input provider proof exist; raw text is not exported |
| Modern app/browser mutation | Body | PARTIAL | managed browser has narrow focus, toggle click, empty-textbox type and native check; authenticated user-browser/general modern-app mutation remains open |
| Generic keyboard shortcuts/navigation | Body | OPEN | requires typed authority and effect verification |
| Robust window/app lifecycle | Body/Senses | OPEN/PARTIAL | process/window foundations exist; product-grade cross-app lifecycle incomplete |

## 7. Connectors / protocols / external systems

| Product need | ZN owner | Status | Current evidence / open work |
| --- | --- | --- | --- |
| Typed external resource protocol | Resource/Channel boundary | PARTIAL | provider-specific resources exist; generic protocol surface is not complete |
| MCP client interoperability | Body/Channel adapter | OPEN | expose bounded resources/actions behind ZN permission/evidence semantics |
| Plugin/connector discovery | Resource registry | OPEN | provider metadata cannot create execution authority |
| Credential-reference management | credential boundary | VERIFIED/PARTIAL | secrets live outside normal config/memory; more connector UX remains |
| Connector permission scopes/revocation | permission system | OPEN | needed before broad third-party integration |

## 8. Communication and personal work systems

| Product need | ZN owner | Status | Current evidence / open work |
| --- | --- | --- | --- |
| User conversation channels | Communication organs | PARTIAL | channel mechanisms exist; product breadth incomplete |
| Email read/draft/send | Communication/Body | OPEN | account connector + explicit send authority required |
| Calendar read/schedule/respond | Communication/Body | OPEN | current-time/conflict evidence required |
| Contacts/people resolution | Senses / connector | OPEN | side-effect ambiguity must fail closed |
| Team chat/work systems | Communication/Body | OPEN | replaceable connectors, not product identity |
| Notifications/follow-up | Will / automation | OPEN/PARTIAL | resident work/progress exists; general user automation remains open |

## 9. Long-running work / automation / recovery

| Product need | ZN owner | Status | Current evidence / open work |
| --- | --- | --- | --- |
| Persist work across restarts | Work / resident state | PARTIAL | resident work/progress state exists |
| Scheduled tasks | Will / resident scheduler | OPEN | persist independently of chat/model provider |
| Event-triggered tasks | Senses / Will | OPEN | external events become observations, not direct execution authority |
| Conditional monitoring | Investigation / Will | OPEN | evidence-based notification lifecycle required |
| Background task visibility/cancel | Work UI | OPEN | user must inspect/cancel active work |
| Retry/backoff/idempotency | Action lifecycle | PARTIAL | selected paths exist; unified semantics remain open |
| Crash recovery/resume | resident / Work | PARTIAL | resident continuity exists; per-task recovery needs broader coverage |

## 10. Parallelism / delegation / cognition

| Product need | ZN owner | Status | Current evidence / open work |
| --- | --- | --- | --- |
| Multiple model providers | CognitiveResource | VERIFIED | providers/routes are replaceable cognition resources |
| Use specialist models for bounded gaps | Investigation / Thought | PARTIAL | architecture supports bounded cognition; broader orchestration can improve |
| Parallel independent investigations | Investigation / Work | OPEN | resident-owned concurrent work, not multiple product identities |
| Merge competing hypotheses by evidence | Thought / Investigation | PARTIAL | contradiction/evidence principles exist; explicit merge lifecycle open |
| Human/model maintainer collaboration | engineering workflow | PARTIAL | Git/PR/HANDOFF make maintainers replaceable; work must not depend on any single model/provider |

## 11. Security / permission / trust

| Product need | ZN owner | Status | Current evidence / open work |
| --- | --- | --- | --- |
| Secret storage outside source/log/memory | credential boundary | VERIFIED | keyring/project secret boundaries exist |
| URL/private-network safety | network Body policy | VERIFIED/PARTIAL | strong URL checks exist; DNS-rebinding/network-sandbox hardening remains open |
| Action-specific authority | Body/Action | VERIFIED/PARTIAL | strong typed authority exists in several lifecycles; expansion remains action-specific |
| Independent post-action evidence | Senses / Action | VERIFIED/PARTIAL | verified lifecycles include managed navigation, focus, toggle click, empty-textbox type and native check |
| Global permission center | Self/user boundary | OPEN | inspectable grants/revocation by capability/site/account |
| Sensitive action escalation | Will / permission | OPEN/PARTIAL | release/self-maintenance rules exist; general product policy remains open |
| Sandboxed untrusted code/content | Body | OPEN/PARTIAL | some boundaries exist; browser/code/plugin sandboxing needs unified policy |
| Audit trail without secret leakage | Memory/observability | OPEN/PARTIAL | evidence records exist; product-level audit UX incomplete |

## 12. Product UI / observability

| Product need | ZN owner | Status | Current evidence / open work |
| --- | --- | --- | --- |
| Native desktop work surface | ZN desktop | VERIFIED/PARTIAL | independent Electron main/preload/renderer exists |
| Show current work/status/evidence | desktop / Work | PARTIAL | resident work/progress surfaces exist; richer task inspection needed |
| Browser/session visibility | desktop / Browser | OPEN | headed session and inspect/cancel UX needed |
| Permission management UX | desktop / Self boundary | OPEN | site/account/capability grants and revocation |
| Memory inspection/control UX | desktop / Memory | OPEN | provenance, correction and forgetting controls |
| Failure/recovery explanation | desktop / Situation | OPEN/PARTIAL | errors exist; coherent recovery surface incomplete |

## 13. Self-maintenance / release

| Product need | ZN owner | Status | Current evidence / open work |
| --- | --- | --- | --- |
| Detect/investigate own failures | self-maintenance | SM0 VERIFIED / SM1+ OPEN | architecture and maintenance evidence pipeline exist |
| Isolated self-repair branch/test/PR | self-maintenance | OPEN | SM1+ |
| CI-gated promotion | repository automation | VERIFIED | normal development/PR/CI flow established |
| Immutable packaged releases | release automation | PARTIAL | release machinery exists; Windows M8 evidence incomplete |
| User-approved update/restart | updater | PARTIAL | architecture/desktop updater exists; full continuity evidence open |
| Rollback after bad release | updater | OPEN/PARTIAL | required M8 proof remains |

## 14. Near-term product order

```text
A. keep resident continuity + CI trustworthy
B. preserve Managed Browser navigation/target/focus/toggle-click/type-text/check real Chromium evidence
C. add UNCHECK with exact-node authority + fresh boolean checked=false evidence
D. add SELECT_OPTION / PRESS / broader click semantics one lifecycle at a time
E. expand target sensing to frames/accessibility/multiple targets behind bounded evidence
F. design authenticated User Browser Bridge lifecycle from real provider evidence
G. build unified permission/audit semantics across browser/connectors/computer use
H. add isolated parallel Work/Investigation + checkpoints
I. add connector protocol/MCP interoperability behind ZN ownership
J. add scheduled/event-driven resident work
K. expand communication/personal-work connectors
L. close Windows install/update/rollback/signing continuity
M. advance SM1+ self-maintenance
```

No development or release capability may depend on one current model, chat session, or machine.

## 15. Completion rule

No row is `VERIFIED` because a model says it is, a provider advertises support, or one API call returned successfully.

For user-affecting capability, completion normally requires:

```text
ZN-owned contract/state/lifecycle
+ explicit permission/authority where side effects exist
+ real provider/runtime behavior
+ failure/privacy/security boundaries
+ independent effect observation
+ tests
+ exact relevant CI/E2E
+ packaging/update consideration where the capability ships to users
```

The goal is not “feature parity with agents.” The goal is a capable ZN whose useful abilities remain organs of one persistent subject.
