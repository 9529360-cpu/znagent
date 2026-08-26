# ZN — Product and Engineering Contract

> Active development branch: `dev/zn-agent`
>
> Canonical source/release branch: `main`
>
> This file is the current architecture contract. Real code and Git state determine what exists; tests/CI determine what has been verified; `.agent/HANDOFF.md` records the current work site.

## 0. Development contract

Before changing the project, restore the real repository state and inspect the active call chain.

Fact priority:

```text
real code and Git state
> real tests / builds / CI
> .agent/HANDOFF.md
> chat descriptions
```

Normal engineering loop:

```text
inspect repository + branch + CI
→ identify entry / owner / state / lifecycle / dependency / tests / active caller
→ update ZN.md first when architecture direction changes
→ implement the smallest coherent ZN-owned step on dev/zn-agent or an isolated work branch
→ add or update tests
→ run relevant verification
→ inspect diff
→ commit / push
→ verify real CI
→ synchronize status docs and HANDOFF
```

M10 canonical promotion is complete. Ordinary development must still not experiment directly on `main`; verified development flows through `dev/zn-agent` or isolated work branches and reaches `main` only through the repository's deliberate promotion/release process.

## 1. Product definition

ZN is the only product and the only resident subject.

**ZN uses models. Models do not own ZN.**

Models, browser engines/providers, search systems, code interpreters and future cognitive systems are replaceable resources. They do not own ZN identity, memory, Will, continuity or the resident life loop. ZN owns the semantics, state, authority and evidence contracts around those resources.

ZN owns:

- persistent Self and life;
- Body and Senses;
- Situation, Thought and Will;
- lived memory and learning;
- Investigation and Action;
- provider/resource boundaries;
- communication channels;
- runtime, configuration and credential references;
- desktop main/preload/renderer and product identity;
- update and release behavior.

Disconnecting every external model must not erase ZN identity/state or prevent native resident pulses and owned deterministic behavior.

## 2. Repository ownership boundary

The active development tree is ZN-only. Historical/reference product source is not kept inside the active tree and is not a runtime, build, test, packaging, release or maintenance dependency.

Reference mechanisms may be studied from Git history, the dedicated reference branch, or an external/upstream repository. Reuse is allowed only when the mechanism is understood, adapted behind ZN-owned interfaces/config/state/lifecycle, covered by ZN tests and free of reference-product control-plane assumptions.

Never restore a historical product tree merely because a test, import or build step breaks. Decide whether the capability belongs to ZN. If it does, implement or adapt it as ZN-owned code; otherwise remove the obsolete caller or contract.

The steady-state physical topology is:

```text
znagent/
├── ZN.md
├── AGENTS.md
├── LICENSE
├── runtime/
│   └── python/
│       ├── pyproject.toml
│       └── zn_agent/
│           ├── core/
│           └── resident.py
├── apps/
│   └── desktop/
│       ├── electron/
│       ├── src/zn/
│       ├── assets/
│       ├── scripts/
│       └── package.json
├── tests/
│   └── zn_agent/core/
├── docs/
├── .agent/
└── .github/workflows/
```

A small root Node manifest/lock may exist only to provide a reproducible ZN desktop workspace install.

## 3. Resident architecture

There is one subject with modular organs:

```text
ZN
├── Self / identity
├── Body
├── Senses
├── Nervous system / lived memory
├── Situation
├── Thought
├── Will
├── Investigation
├── Action
├── Learning / reconsolidation
├── Communication organs
└── External cognitive resources
```

Normal life loop:

```text
exist
→ sense current body/world/internal state
→ Situation
→ Thought
→ maintain/form intention
→ Investigation / Action / reflection
→ observe real outcome
→ lived experience
→ learning / Will change
→ continue existing
```

External cognition is a bounded increment:

```text
specific gap
→ optional CognitiveResource
→ CognitiveIncrement
→ ZN checks against current evidence
→ integrate / reject / investigate further / act
```

Model output is never automatically fact, decision, execution authority or completion proof.

## 4. Body, verification and learned competence

Files, processes, Git, terminal, browser and network sensing are Body/Senses, not extra agent personalities.

Movement success alone is not task success. Completion and positive learning require independent current-world verification appropriate to the effect.

Engineering competence must preserve:

- explicit typed or resident-proven authority before side effects;
- structured current repository/path evidence where Git state matters;
- fresh post-action verification;
- contradiction returns to Investigation;
- procedural memory may influence only freshly re-formed safe choices;
- familiar execution never makes current evidence optional;
- model suggestions do not create execution authority.

### 4.1 Browser is a first-class resident Body/Senses subsystem

Browser capability is not a late tool attachment and must not be reduced to "a model controlling Playwright". Product-grade ZN needs two distinct browser planes from the architecture level:

```text
Resident Managed Browser
+ User Browser Bridge
= complete browser capability
```

They serve different realities and neither can replace the other.

The browser subsystem must be ZN-owned at the contract/lifecycle/evidence layer even when the underlying engine or provider is replaceable.

### 4.2 Resident Managed Browser

ZN needs a managed browser for autonomous web work that should not require a visible user browser or an already logged-in personal session.

The default design target is a locally available Chromium-class browser controlled through a ZN-owned adapter, with both headless and headed execution when the platform supports them. A remote/cloud browser may be an optional provider, but basic resident web ability must not depend on a cloud browser account.

The managed browser is responsible for product capabilities such as:

- page/session lifecycle and bounded profile storage;
- navigation, redirects and URL safety;
- DOM/accessibility/page-state sensing;
- screenshots and visual evidence where needed;
- click, focus, form entry and bounded script-driven page interaction;
- downloads/uploads with explicit file authority;
- multi-page/tab state where justified;
- current page URL/title/load/error evidence;
- post-action verification and recovery from stale targets;
- explicit network/proxy/provider configuration;
- deterministic cleanup of ephemeral sessions.

Managed browser profiles are isolated from the user's ordinary browser profiles by default. ZN must not silently copy Chrome/Edge cookies, password stores, browser databases, profile directories or authentication secrets into its managed browser.

Search/extract APIs such as Tavily, Exa or Firecrawl remain useful WebResources, but they complement rather than replace a real managed browser. API extraction cannot prove interactive page state, JavaScript behavior, authenticated UI flows or browser-side effects.

### 4.3 User Browser Bridge

Many important tasks depend on state that already exists in the user's real browser: authenticated applications, enterprise SSO, remembered MFA, local certificates, site grants, extensions, open tabs or data that the user should not have to log into again inside a second ZN-managed profile.

ZN therefore also needs a separate bridge to the user's existing browser session.

The user browser remains the user's application and profile; it does not become ZN runtime or identity storage. ZN may sense and act through bounded adapters such as:

```text
Windows UIA / accessibility / desktop evidence
+ optional ZN browser companion extension
+ optional native-messaging or similarly bounded local bridge
```

A companion extension/bridge may provide higher-fidelity semantic page evidence when installed and explicitly permitted, while UIA/desktop control remains an independent path and fallback for visible user interaction.

The user must not be forced to reproduce every login inside the managed browser merely because ZN needs data from an authenticated user session. Conversely, ZN must not solve this by extracting raw cookies, saved passwords or browser credential databases. Authentication material stays in the browser/OS security boundary whenever possible; ZN acts through the already-authorized session.

Per-site/page/session permission, sensitive-field handling and user-visible control must be explicit. Password fields, payment secrets, recovery codes and other sensitive inputs require conservative handling and must never become ordinary observation or learned-memory content.

### 4.4 Shared browser action and evidence contract

Managed-browser and user-browser paths may use different providers, but they should converge on ZN-owned semantic contracts rather than create two unrelated automation stacks.

Common concepts should include:

```text
BrowserTarget
BrowserObservation
BrowserAction
BrowserActionAuthority
BrowserEffectEvidence
BrowserSessionIdentity
BrowserPermissionContext
```

Actions must bind to fresh target/session evidence. Successful dispatch is not successful completion. Navigation, form submission, downloads, uploads and state-changing page actions require appropriate postconditions.

DOM identity, accessibility identity, UIA RuntimeId, coordinates and visual regions are all scoped evidence, not permanent truth. The resident must be able to reject stale targets and re-sense after page/process/frame changes.

Cloud browser providers, local Chromium, browser extensions and desktop automation are implementations behind ZN ownership. No provider may become the browser control plane or own resident intention, permission, memory or completion semantics.

### 4.5 Product-level browser requirements

The browser subsystem should be designed for the eventual real product rather than a CI-demo minimum. Important requirements include:

- local-first managed browsing with optional cloud capacity;
- use of the user's existing authenticated browser when task reality lives there;
- no hidden credential/profile copying between browser planes;
- first-class privacy boundaries for text, screenshots, downloads and page metadata;
- explicit MFA/user-presence handoff where automation cannot or should not continue alone;
- robust handling of popups, new tabs, redirects, downloads, file pickers and browser crashes;
- bounded persistence and cleanup for managed sessions;
- observable provider/session health and actionable failure reasons;
- anti-stale target checks and independent post-action evidence;
- replaceable providers without changing ZN identity or resident semantics;
- real-browser E2E evidence for supported user-browser integrations;
- managed-browser E2E evidence for supported autonomous browser integrations.

A product slice may implement only part of this at one time, but status documents must name the missing product requirements explicitly. Passing a narrow test is evidence for that slice, not evidence that the browser product is complete.

## 5. Memory and learning

Memory is lived resident change, not merely transcript/context retrieval.

```text
experience
→ resident-owned traces/relations
→ repeated compatible evidence
→ candidate tendency
→ current-reality applicability
→ bounded procedural influence
→ prediction check
→ reinforcement, inhibition or relearning
```

One success does not create a permanent skill. Contradiction must be able to weaken or inhibit stale competence. Mature resident-owned ability should survive provider replacement and full model removal.

Detailed direction is maintained in `docs/ZN-MEMORY-LEARNING.md` and `docs/ZN-NEXT-PHASE.md`.

## 6. Desktop boundary

Electron is ZN's face/work surface, not the owner of resident life.

```text
ZN Electron main
→ ZN preload / IPC
→ long-lived ZN resident
→ independent ZN renderer (`src/zn`)
```

The renderer is content/work oriented. Files, diffs and terminal are contextual surfaces. Closing the desktop must not define or erase resident identity.

## 7. Runtime, data and credentials

Packaged runtime identity:

```text
Python distribution: znagent
Python package:      zn_agent
entrypoint:          zn-resident
```

The physical core source is `runtime/python/zn_agent/core/`; tests live under `tests/zn_agent/core/`.

Persistent identity/state belongs outside immutable runtime versions. Runtime N and N+1 may coexist during safe handoff.

Credentials and secrets belong in appropriate secure stores/project secret infrastructure and must not be committed, written into HANDOFF, logs or ordinary resident memory.

## 8. Release/update architecture

The current intended desktop platform is **Windows x64**. Formal release readiness and M8 evidence are Windows-first. Linux and macOS packaging or continuity checks may be retained as optional/on-demand evidence, but they do not block normal development or M8 unless they are explicitly restored as intended product targets.

Formal installers and update assets are ZN-only:

```text
traceable commit/tag
→ CI
→ build self-contained ZN artifacts
→ verify artifacts/runtime
→ publish immutable version assets
→ optional archival GitHub Release
→ advance stable.json LAST
```

A clean Windows machine must not require a source checkout, system Python, Node/npm or private source credentials.

Hashes are integrity checks, not signatures. Windows signing remains a separate release hardening gate.

## 9. Self-maintenance

Self-maintenance follows `docs/ZN-SELF-MAINTENANCE.md`.

First-stage principle: ZN may investigate, develop, test, prepare branches/PRs and release candidates, but replacing the user's currently installed body defaults to explicit user approval.

Identity, long-term memory, credentials, updater, rollback, signing and self-maintenance permission rules remain high-risk boundaries requiring conservative approval.

## 10. Testing contract

The steady-state daily CI target is Windows x64. It should run automatically from repository events on a replaceable self-hosted Windows x64 runner rather than depending on a specific runner name or maintainer session. A replacement Windows x64 runner registered to the repository must be able to resume the same workflow.

At minimum protect:

- zero-model resident boot and persistence;
- Situation/Thought/Will continuity;
- Body result feedback and independent verification;
- nervous learning/reconsolidation;
- current-reality-gated procedural influence;
- channel restart/idempotency behavior;
- runtime package ownership;
- active ZN renderer/main/preload/protocol ownership;
- release/runtime staging integrity;
- repository-boundary scans that prevent historical/reference product paths, package namespaces or control planes from becoming active dependencies again;
- managed-browser lifecycle/evidence contracts once implemented;
- real user-browser integration and privacy/permission boundaries once implemented.

Tests retained in the active tree must describe ZN behavior or guard ZN ownership boundaries. Optional Linux/macOS checks must not be presented as required evidence while those platforms are not intended targets.

## 11. M8 and M10 boundaries

M8 release continuity debt remains separate and must not be falsely reported complete. For the current Windows x64 product target, M8 requires Windows clean-install/login evidence, installed N→N+1 continuity, rollback evidence and applicable Windows signing evidence.

Historical Linux/macOS evidence remains useful engineering evidence, but Linux AppImage, Linux container and macOS continuity/signing are not current M8 blockers unless those platforms are deliberately restored as intended targets.

M10 canonical source promotion is complete. Its continuing value is the stable ownership rule it established:

1. ZN owns resident runtime and persistent identity/state paths;
2. ZN owns desktop main/preload/renderer and product identity;
3. ZN owns build, package and release automation;
4. CI verifies the active canonical source;
5. applicable license/provenance obligations remain preserved;
6. historical/reference source is not an active dependency;
7. unresolved release risks remain explicit rather than being hidden by branch promotion.

The 2026-08-24 promotion was performed by non-forced fast-forward after a fresh full CI review. No history rewrite was used.

Canonical branch promotion does not mean M8 or formal release readiness is complete. M8 remains a separate evidence-based milestone.

## 12. Current priority

The repository-boundary evacuation and M10 canonical promotion are complete. Engineering priority is now:

```text
keep automatic Windows x64 self-hosted CI green on push / PR
→ keep ZN-only ownership guards green
→ build the product-grade browser foundation as two explicit planes
   → Resident Managed Browser for autonomous local/headless/headed web work
   → User Browser Bridge for existing authenticated user sessions
→ preserve common ZN-owned browser action/evidence/privacy semantics across both planes
→ continue real Windows desktop/UIA computer-use evidence without confusing it with managed-browser automation
→ remove remaining development/tooling security debt where safely possible
→ advance resident-owned engineering competence
→ close Windows M8 install / N→N+1 / rollback / signing gaps
→ maintain self-maintenance/release automation
```

Linux/macOS work is optional/on-demand at the current product stage. Do not let dormant secondary-platform work block Windows development, and do not expand product behavior by restoring old control planes or generic agent-framework ownership.

## 13. Provenance

Historical upstream provenance and license obligations are retained through repository history, the dedicated reference branch and applicable license records. Provenance is legal/historical information only; it must not become a runtime, build, test, release or maintenance dependency.
