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
| Isolated parallel worktrees/tasks | Work / Investigation | OPEN | required for mainstream multi-task parity; must be ZN-owned work isolation, not multiple agent identities |
| Checkpoints / restore / rollback for work | Work / Body safety | OPEN | needed for long-running edits and destructive recovery |

## 5. Web and browser

Complete browser product capability requires both planes:

```text
Resident Managed Browser + User Browser Bridge
```

| Product need | ZN owner | Status | Current evidence / open work |
| --- | --- | --- | --- |
| HTTP web search/extract | Web Senses / external resources | VERIFIED/PARTIAL | Tavily/Exa/Firecrawl provider resources exist with resident-owned normalization/failover |
| ZN-owned browser session/action/evidence contracts | Browser Body/Senses | FOUNDATION | `BrowserSessionIdentity`, query/target/observation/action/authority/effect contracts are implemented and hardened |
| Local managed Chromium, headless | Browser Body | FOUNDATION | Playwright adapter + dedicated real Windows Chromium navigation/target E2E exist; lifecycle cleanup is resident-owned |
| Local managed Chromium, headed | Browser Body | OPEN | same ZN contracts, separate real UX/evidence |
| DOM/accessibility target sensing | Browser Senses | PARTIAL / VERIFIED NARROW | exact `DOM_ID` query for one unique visible main-frame element is real-CI/real-Chromium verified with bounded role/name/hint and freshness; iframe, generic accessibility queries, multi-target/disambiguation and visual fusion remain open |
| Managed-browser focus/click/type/select | Browser Body | OPEN | target sensing now exists, but mutation still requires exact-node continuity at dispatch plus independent post-action evidence; `NAVIGATE` remains the only implemented mutation |
| Multi-tab/popup/frame lifecycle | Browser Body/Senses | OPEN | needs stable page/frame identities and stale-target handling |
| Downloads/uploads | Browser Body + File authority | OPEN | adapter refuses these until explicit file authority exists |
| Screenshots/visual browser sensing | Browser Senses | OPEN | must integrate with visual evidence rather than become completion authority by itself |
| Persistent ZN-managed browser profile | Browser state | OPEN | must be explicitly separated from user browser profiles and credentials |
| Optional cloud browser backend | Browser resource adapter | OPEN | provider may be replaceable; local browsing must not depend on it |
| Operate user's existing Edge/Chrome login session | User Browser Bridge | FOUNDATION | real Windows interactive proof shows isolated-profile Edge exposes a focused HTML input through the default UIA provider without forced renderer accessibility; actual authenticated existing-session attachment, lifecycle, permission and mutation remain open |
| Companion extension/native messaging bridge | User Browser Bridge | OPEN | candidate path for richer authenticated browser state; add only if provider evidence shows it is needed and user permission is explicit |
| MFA/sensitive-field handling | Permission / Body | OPEN | never silently replay or extract secrets; explicit high-risk boundaries required |

The managed-browser target proof is deliberately narrow: it validates an exact main-frame DOM-id target, not arbitrary DOM querying or generic accessibility-tree control. The provider does not export raw input values, HTML or uncontrolled page content, and password targets fail closed without explicit sensitive-field permission.

The User Browser Bridge provider proof is also deliberately narrow: it validates real browser UIA sensing, not authenticated user-browser control. The fixture uses a temporary isolated profile and exports only bounded focused-element/current-text evidence, including text length and digest rather than raw text.

## 6. Desktop computer use

| Product need | ZN owner | Status | Current evidence / open work |
| --- | --- | --- | --- |
| Visual region sensing | Senses | VERIFIED/PARTIAL | visual-region sensing and attention rhythm exist |
| Foreground/focused control sensing | Senses | VERIFIED | native foreground/focus evidence exists |
| Pointer movement/click with verification | Body + Senses | VERIFIED NARROW | real Windows interactive E2E exists |
| Native Win32 text entry | Body + Senses | VERIFIED NARROW | real Unicode Edit E2E, empty focused native Edit only |
| Modern UI text current-state evidence | Senses | VERIFIED NARROW | WPF read-only digest proof and real Edge focused HTML-input provider proof exist; raw text is not exported |
| Modern app/browser text mutation | Body | OPEN | do not infer mutation authority from WPF/Edge read evidence or managed target sensing |
| Generic keyboard shortcuts/navigation | Body | OPEN | requires typed authority and effect verification |
| Robust window/app lifecycle | Body/Senses | OPEN/PARTIAL | process/window foundations exist; product-grade cross-app lifecycle incomplete |

## 7. Connectors / protocols / external systems

Mainstream systems increasingly expose MCP/plugins/connectors. ZN should support the useful interoperability without making an external registry its brain.

| Product need | ZN owner | Status | Current evidence / open work |
| --- | --- | --- | --- |
| Typed external resource protocol | Resource/Channel boundary | PARTIAL | provider-specific resources exist; generic protocol surface is not complete |
| MCP client interoperability | Body/Channel adapter | OPEN | should expose bounded resources/actions behind ZN permission and evidence semantics |
| Plugin/connector discovery | Resource registry | OPEN | provider metadata cannot create execution authority |
| Credential-reference management | credential boundary | VERIFIED/PARTIAL | secrets live outside normal config/memory; more connector UX remains |
| Connector permission scopes/revocation | permission system | OPEN | needed before broad third-party integration |

## 8. Communication and personal work systems

| Product need | ZN owner | Status | Current evidence / open work |
| --- | --- | --- | --- |
| User conversation channels | Communication organs | PARTIAL | channel mechanisms exist; product breadth incomplete |
| Email read/draft/send | Communication/Body | OPEN | should use account connector + explicit send authority |
| Calendar read/schedule/respond | Communication/Body | OPEN | current-time/conflict evidence required |
| Contacts/people resolution | Senses / connector | OPEN | identity ambiguity must fail closed for side effects |
| Team chat/work systems | Communication/Body | OPEN | Slack/Teams-like adapters can be replaceable connectors |
| Notifications/follow-up | Will / automation | OPEN/PARTIAL | resident work/progress exists; general user automation engine remains open |

## 9. Long-running work / automation / recovery

| Product need | ZN owner | Status | Current evidence / open work |
| --- | --- | --- | --- |
| Persist work across restarts | Work / resident state | PARTIAL | resident work/progress state exists |
| Scheduled tasks | Will / resident scheduler | OPEN | must persist independently of chat/model provider |
| Event-triggered tasks | Senses / Will | OPEN | external events should become observations, not direct execution authority |
| Conditional monitoring | Investigation / Will | OPEN | evidence-based notification lifecycle required |
| Background task visibility/cancel | Work UI | OPEN | user must be able to inspect/cancel active work |
| Retry/backoff/idempotency | Action lifecycle | PARTIAL | exists in selected channels/actions; needs unified product semantics |
| Crash recovery/resume | resident / Work | PARTIAL | resident continuity exists; per-task recovery needs broader coverage |

## 10. Parallelism / delegation / cognition

| Product need | ZN owner | Status | Current evidence / open work |
| --- | --- | --- | --- |
| Multiple model providers | CognitiveResource | VERIFIED | providers/routes are replaceable cognition resources |
| Use specialist models for bounded gaps | Investigation / Thought | PARTIAL | architecture supports bounded cognition; broader orchestration can improve |
| Parallel independent investigations | Investigation / Work | OPEN | should be resident-owned concurrent work, not a society of agent identities |
| Merge competing hypotheses by evidence | Thought / Investigation | PARTIAL | contradiction/evidence principles exist; explicit parallel merge lifecycle open |
| Human/model maintainer collaboration | engineering workflow | PARTIAL | Git/PR/HANDOFF make maintainers replaceable; project work must not depend on any single model/provider being available |

## 11. Security / permission / trust

| Product need | ZN owner | Status | Current evidence / open work |
| --- | --- | --- | --- |
| Secret storage outside source/log/memory | credential boundary | VERIFIED | keyring/project secret boundaries exist |
| URL/private-network safety | network Body policy | VERIFIED/PARTIAL | strong URL checks exist; browser DNS-rebinding/network-sandbox hardening remains open |
| Action-specific authority | Body/Action | VERIFIED/PARTIAL | strong typed authority exists in several lifecycles; needs consistent expansion |
| Independent post-action evidence | Senses / Action | VERIFIED/PARTIAL | core principle and several real lifecycles verified |
| Global permission center | Self/user boundary | OPEN | user needs inspectable grants/revocation by capability/site/account |
| Sensitive action escalation | Will / permission | OPEN/PARTIAL | release/self-maintenance high-risk rules exist; general product policy engine open |
| Sandboxed untrusted code/content | Body | OPEN/PARTIAL | some boundaries exist; browser/code/plugin sandboxing needs a unified policy |
| Audit trail without secret leakage | Memory/observability | OPEN/PARTIAL | evidence records exist; product-level user audit UX incomplete |

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

This is a dependency order, not a promise that all work is sequential:

```text
A. keep resident continuity + CI trustworthy
B. preserve Managed Browser foundation and real local Chromium proof
C. preserve the verified narrow real Edge UIA provider sensing proof
D. harden managed-browser exact-node continuity at the execution boundary
E. add managed-browser FOCUS with execution-time re-sensing + independent focused-element evidence
F. add CLICK, TYPE_TEXT and other browser mutations one lifecycle at a time
G. expand target sensing to frames/accessibility/multiple targets only behind ZN-owned bounded evidence
H. design authenticated User Browser Bridge lifecycle from real provider evidence
I. build unified permission/audit semantics across browser/connectors/computer use
J. add isolated parallel Work/Investigation + checkpoints
K. add connector protocol/MCP interoperability behind ZN ownership
L. add scheduled/event-driven resident work
M. expand communication/personal-work connectors
N. close Windows install/update/rollback/signing continuity
O. advance SM1+ self-maintenance
```

Parallel maintainers may own different rows/domains as long as they share the same ZN contracts, work on isolated branches when appropriate, keep `dev/zn-agent` integration evidence current, and never create a second product control plane. No development or release capability may depend on one current model, chat session or machine.

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
