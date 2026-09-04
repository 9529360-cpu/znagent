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

M10 canonical promotion is complete. `main` is the canonical source/release branch; `dev/zn-agent` is the fixed primary development branch.

Ordinary development, investigation and experiments must not be performed directly on `main`. They belong on `dev/zn-agent` or an isolated work branch.

That restriction does not freeze `main`. A coherent low-risk engineering stage may be promoted through the repository's normal PR/merge/promotion flow when all applicable gates are true:

```text
implementation complete for the claimed slice
→ relevant tests pass
→ full CI / required E2E pass
→ diff reviewed
→ status docs + HANDOFF match real code and CI
→ no unresolved promotion blocker
→ no high-risk boundary requiring human approval
→ normal traceable PR / merge / promotion
→ main becomes the new verified canonical source
```

A normal low-risk promotion that satisfies these repository gates does not require an extra chat-only approval sentence. High-risk boundaries still require explicit human approval, including identity, long-term memory, destructive data migration, credentials/permissions, updater/rollback/signing trust, and replacement of the user's currently installed formal version.

Promotion must never use force push, Git history rewrite, disabled CI, bypassed failed checks, or false completion claims.

## 1. Product definition

ZN is the only product and the only resident subject.

ZN is a long-lived intelligent resident that lives on the user's computer and continuously participates in the user's real digital environment. It is not primarily a framework, automation toolkit, collection of capabilities, test harness, workflow engine or release system. Those may exist inside the project, but the product the user experiences is one persistent intelligent subject that can understand ordinary requests and get real computer work done.

The intended user experience is simple:

```text
user says what they want in normal human language
→ ZN understands the goal
→ ZN looks at the real computer and existing context
→ ZN decides what it needs to inspect or use
→ ZN investigates when necessary
→ ZN operates the browser / desktop / files / terminal / network / other resources
→ ZN observes what changed
→ ZN continues, replans or investigates again
→ ZN verifies the real result
→ ZN remains present for the next task and future continuation
```

A normal user should not need to translate work into ZN internals, structured test commands or step-by-step instructions such as which button to click next. The user should be able to say things such as:

- "查一下这个问题，看看几个来源再告诉我结论。"
- "这个网页先别关，去另一个网站查点东西，然后回来继续。"
- "帮我把这个网站里的事情办完。"
- "打开那个软件，把这件事处理掉。"
- "找到我昨天下载的合同，看看内容，改好以后放到项目文件夹。"
- "网页上查到的数据整理进本地文件。"
- "帮我看看这个项目为什么报错，把 bug 修掉并验证。"
- "刚才做到哪了？继续。"
- "昨天那个继续。"
- "你自己看看怎么弄。"

ZN should then carry the task across the real computer rather than forcing the user to become the planner.

### 1.1 ZN lives in the whole computer, not in one tool

The browser, desktop, filesystem, terminal, applications and network are parts of the same lived environment from ZN's point of view.

A mature ZN must be able to move between them as one continuous task requires. For example:

```text
keep the user's current page A
→ open or use page B to investigate
→ open page C if more evidence is needed
→ return to A
→ re-observe A because its state may have changed
→ continue the original task
```

or:

```text
find a local file
→ understand its contents
→ search the web for missing information
→ return to the file or target application
→ update the result
→ verify the saved output
```

or:

```text
inspect a website
→ collect the needed information
→ open a desktop application
→ enter or transform the information there
→ verify the final application state
```

Browser tabs, windows, applications and files are therefore not isolated capability demos. They are places and objects inside one ongoing task world.

### 1.2 ZN should manage context like a competent computer user

ZN should preserve useful working context instead of destroying it unnecessarily.

If the user is working on page A and ZN needs page B for investigation, ZN should normally keep A available, create or use an appropriate B context, then return to the correct A context when needed. It should know which page, window, document or application belongs to which part of the task instead of relying only on "whatever is currently foreground".

The same principle applies outside the browser. ZN should be able to keep a document open while checking another source, leave an application in a useful state while visiting another one, and return to the correct work context afterwards.

The exact choice — reuse the current tab, open a new tab, open another window, switch applications, keep something open, close something no longer needed — is part of ZN's task judgment. It should not be permanently hard-coded to one behavior.

### 1.3 ZN investigates instead of requiring a perfect script

Real computer tasks are not stable scripts. Websites change, windows move, dialogs appear, controls disappear, network requests fail, pages redirect, files have unexpected names and user descriptions are often approximate.

ZN must therefore be able to investigate the current reality.

The intended behavior is:

```text
goal
→ sense
→ Situation
→ Thought
→ hypothesis / plan
→ action
→ fresh observation
→ compare outcome with intention
→ continue / replan / investigate / ask only when genuinely necessary
```

It is not sufficient for mature ZN behavior to be:

```text
predefined parser / workflow
→ expected target not found
→ fail
```

A failed assumption should usually create a new information problem for ZN to investigate, not immediately terminate the user's task.

### 1.4 ZN should be able to use the web as part of thinking and doing

ZN should be able to search the internet, inspect multiple sources, follow links, compare information and continue searching when the first result is insufficient. It should also be able to use the user's existing authenticated browser state when the task belongs there, instead of forcing the user to recreate every login in a separate environment.

Autonomous web work and user-session browser work are both parts of the same product. Which one ZN uses depends on where the real task state exists.

### 1.5 ZN should complete work, not merely perform movements

Clicking a button, sending keys, opening a page, receiving HTTP 200, running a command successfully or receiving a confident model answer are only movements or intermediate events.

ZN's job is the user's requested outcome.

After acting, ZN must observe the resulting real state and decide whether the goal is actually satisfied. If the world contradicts the expected outcome, ZN should continue investigating or explain what remains unresolved rather than declaring success from the attempted action alone.

### 1.6 ZN is continuous across time

ZN is intended to remain present over long periods rather than act like a fresh stateless chat session every time.

Its identity, Work, relevant memory and learned experience should support user experiences such as:

- "刚才做到哪了？"
- "这个项目继续。"
- "昨天那个继续。"
- "上次这个网站遇到的问题别再犯。"
- "还是按照我以前习惯的方式。"

Restarting the Resident or closing an application should not automatically erase task continuity. When enough current evidence exists to safely resume, ZN should continue from the real state instead of blindly replaying old actions or restarting everything from zero.

### 1.7 The product is judged by real tasks

The meaningful measure of ZN maturity is not how many modules, providers, state machines, tests, installers or CI workflows exist.

The meaningful question is:

> If an ordinary user installs ZN on their computer and simply tells it what they want in normal language, how many real tasks can ZN independently, continuously and reliably complete?

Examples of the product-level task space include:

- autonomous web research across multiple pages and sources;
- work in the user's existing logged-in websites;
- multi-page and multi-tab browser tasks;
- continuous desktop application tasks;
- file discovery, understanding, modification and organization;
- browser + file tasks;
- browser + desktop tasks;
- cross-application information transfer;
- coding/repository work that combines specialist cognition with real File/Git/Terminal/Test tools;
- recovery after popups, page changes, window changes or network failures;
- resuming interrupted work;
- long-term project/task continuation;
- safe handling of permissions and sensitive fields;
- independent verification that the requested result really exists.

Individual primitives remain necessary parts of the Body, but they are not the product milestone by themselves.

### 1.8 ZN uses models. Models do not own ZN

**ZN uses models. Models do not own ZN.**

Models, browser engines/providers, search systems, code interpreters, specialized agents and future cognitive systems are replaceable resources. They do not own ZN identity, memory, Will, Work continuity or the resident life loop. ZN owns the semantics, state, authority, resource selection and evidence contracts around those resources.

ZN owns:

- persistent Self and life;
- user goal and durable Work identity;
- Body and Senses;
- Situation, Thought and Will;
- lived memory and learning;
- Investigation and Action coordination;
- provider/resource selection and boundaries;
- communication channels;
- runtime, configuration and credential references;
- desktop main/preload/renderer and product identity;
- update and release behavior;
- final completion judgment from current evidence.

Disconnecting every external model must not erase ZN identity/state or prevent native resident pulses and owned deterministic behavior. It may reduce what ZN can competently accomplish. **Provider independence is not a requirement that ZN pretend to perform model-dependent cognition without a model.** If a task genuinely requires unavailable coding, language, vision, research or reasoning cognition, ZN should preserve the Work and report the resource gap rather than fabricate an answer or force an unsuitable deterministic path.

### 1.9 ZN owns the task; it does not have to personally implement every specialty

ZN is the long-lived task owner, continuity owner, context/resource orchestrator and truth/safety boundary. That does **not** mean the resident core must personally perform every intellectual specialty.

A difficult coding task may be performed substantially by a strong coding model. A deep research task may need a research model plus web resources. A visual task may need a vision model. Writing and translation may legitimately use language models. Other bounded specialist agents may also be used when they provide a real product advantage.

The ownership boundary is:

```text
user goal / durable Work                         owned by ZN
current Situation / authority / evidence         owned by ZN
specialist cognition or bounded delegated work   may be external
real computer operations                         performed through appropriate tools/Body
result verification / continuation / completion  owned by ZN
```

For example, "fix this bug" should be allowed to look like:

```text
user goal
→ ZN restores the real repository/Work context
→ File/Git/Terminal establish current facts
→ coding resource reads the relevant code and reasons about the bug
→ coding resource proposes or performs a bounded edit through authorized tools
→ tests/runtime produce fresh evidence
→ failures are fed back as new evidence for further cognition
→ ZN continues until the user's actual outcome is verified or a real blocker remains
```

The coding model may do most of the code reasoning and code generation. It still does not acquire ZN identity, durable Work ownership, arbitrary repository authority or the right to declare completion from its own confidence.

### 1.10 Cognition, tools, authority and verification are complementary

A capable model without the needed tools cannot make a real computer task happen. A powerful tool set without enough cognition cannot reliably solve unfamiliar or ambiguous work. Permission without competence is not enough, and apparent success without verification is not completion.

A real task therefore depends on an appropriate composition of:

```text
cognition / expertise
+ sensing and action tools
+ current authority / access
+ current-world verification
= executable task capability
```

ZN should diagnose the missing resource instead of treating every gap as an LLM prompt:

```text
missing understanding / planning / generation
→ use an appropriate CognitiveResource or specialist

missing world facts
→ Sense / inspect / search / read first

missing ability to affect the world
→ choose the appropriate Browser / Desktop / File / Terminal / API tool

missing permission or user presence
→ request the minimum necessary authority or handoff

missing proof that the intended result happened
→ observe / query / test / compare again
```

Do not ask a model to invent facts that an owned sensor or tool can establish. Do not force a deterministic local program to solve genuinely open-ended cognition merely to avoid model use. Use the strongest suitable resource when the task warrants it, and bind it to the tools and evidence it actually needs.

### 1.11 Token and cognitive cost are product constraints, not the product goal

ZN should not reproduce the common agent pattern where every click, wait, poll, known state transition or deterministic check causes another large-model round trip. That is expensive, slow and often less reliable than resident-owned state and tools.

The target is **appropriate cognition**, not minimum model use and not maximum model use.

Prefer resident/local mechanisms for things they can establish reliably, including identity, Work state, permissions, waiting/polling, deterministic transformations, known invariants, target freshness checks and postcondition probes. Prefer bounded model calls for actual cognitive gaps. Give external cognition the minimum sufficient, relevant context rather than automatically dumping full transcripts, complete DOMs, private memory and unrelated tool history into every call.

Resource selection may legitimately escalate:

```text
resident deterministic knowledge / learned competence
→ small or specialized model for a bounded language/selection gap
→ general strong model for difficult reasoning
→ specialist coding/research/vision model when the task requires it
```

A hard coding, research, writing or reasoning task may consume substantial tokens because cognition is genuinely the work. ZN must not sacrifice task quality merely to reduce token count. The efficiency goal is to stop paying large-model cost for mechanics that the resident, tools or already-learned competence can handle reliably, while spending cognition where cognition creates real value.

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

Resource orchestration is part of the resident task loop, not a separate agent personality:

```text
current goal + Work + Situation
→ identify the actual gap
→ select a resource bundle
   (cognition + senses/tools + authority + verification path)
→ let the selected specialist/tool perform its bounded role
→ collect fresh result/evidence
→ integrate into Situation
→ continue / replan / escalate / ask for authority / complete
```

A resource bundle can legitimately combine a strong model with real tools. For example, a coding model without File/Git/Terminal/Test access is not equivalent to a coding capability that can change and verify a repository. Conversely, granting tools does not make the model the resident subject or give it unbounded authority.

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

### 4.6 Resident intelligence must accumulate inside ZN

ZN must not behave like a newborn agent that re-solves every recurring task from scratch merely because an external model is available. A mature resident should become both more capable and more reliable through mechanisms and experience that belong to ZN itself.

Resident intelligence has three distinct sources:

```text
ZN-owned built-in competence
+ ZN-owned learned experience / procedural competence
+ replaceable external cognition for genuine novelty and specialist work
= mature resident intelligence
```

**Built-in competence** is mature engineering and computer-use knowledge crystallized into ZN-owned mechanisms: state machines, evidence contracts, Body/Senses semantics, verification, recovery, conflict detection, deterministic capabilities, tests and other resident behavior. When a class of failure is already well understood and can be handled by explicit evidence, ZN should not repeatedly ask a model to rediscover the same rule.

**Learned competence** is what ZN acquires through its own verified lived experience: familiar procedures, context-specific expectations, anomaly patterns, recovery tendencies and project/user-specific ways of working. This competence must remain reality-gated and should survive provider replacement when the competence has genuinely become resident-owned.

**External cognition** remains valuable for unfamiliar situations, hard reasoning, open-ended generation, specialist work and genuine knowledge gaps. Its output is candidate cognition rather than resident truth, but that does not make it optional when the task actually requires such cognition. External model quality may change without redefining who ZN is or erasing what ZN already knows how to do.

The knowledge-crystallization rule is:

```text
well-understood recurring low-level problem
→ encode resident-owned observation / invariant / procedure / verification
→ prove it with tests and current-world evidence
→ stop paying a model to rediscover the same mechanical rule every time
```

This rule must not be misread as "turn every intelligent task into local deterministic code." Open-ended coding, research, writing, interpretation and novel reasoning may remain model work indefinitely even when the surrounding mechanics, context restoration, tool use and verification become cheaper and more resident-owned.

Some questions are never model-authority questions. Whether an action executed, a file now contains intended bytes, a browser mutation took effect, an event is terminal, or the outside world changed must be established from owned state and fresh observation, not inferred from model confidence.

Repeated mechanical structure should proceduralize rather than become repeated prompting. The first unfamiliar attempt may require deep Investigation and external cognition; later compatible attempts should use accumulated resident competence for the parts that are actually learnable while still calling specialist cognition for unresolved semantic work. A hundred prior successes do not authorize a blind hundred-and-first action when current evidence has drifted.

A mature familiar path therefore needs both speed and interruption semantics:

```text
familiar Situation
→ resident competence activates
→ act
→ verify expected result
→ compatible reality strengthens familiarity

but:

changed / ambiguous / contradictory reality
→ stop automatic continuation
→ re-sense
→ raise uncertainty
→ Thought / Investigation
→ adapt or relearn
```

Product quality is not measured only by whether ZN can complete a task once. Important intelligence criteria include repeated-task reliability, anomaly detection, uncertainty calibration, self-correction, restart continuity, resistance to stale state, provider independence, efficient resource selection and retention of mature resident-owned competence when particular models are unavailable.

This does not mean copying a model's weights, hidden training data or unverified textual knowledge into ZN. It means converting applicable mature systems knowledge into explicit ZN-owned architecture and tests, while allowing ZN's personal/project-specific competence to emerge from verified experience and continuing to use external cognition where it remains the right tool.

Detailed learning mechanics remain governed by `docs/ZN-MEMORY-LEARNING.md`. The broader product/engineering implications of resident intelligence are recorded in `docs/ZN-RESIDENT-INTELLIGENCE.md`.

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

One success does not create a permanent skill. Contradiction must be able to weaken or inhibit stale competence. Mature procedural ability that has genuinely become resident-owned should survive provider replacement; this is not a claim that open-ended model-dependent tasks must remain solvable with all cognitive providers removed.

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

Installed ZN instances must know a bounded **upstream update identity/channel** so they can check for newer official versions and verify update metadata/artifacts. That knowledge is not repository authority. The source repository may remain private; an installed client must not require source checkout, repository read access, GitHub credentials, system Python or Node/npm in order to update.

The installed-product update boundary is deliberately one-way and narrow:

```text
official upstream update channel
→ installed ZN reads/verifies/downloads approved update metadata/artifacts
```

Knowing the official update channel or product upstream identity never implies source-repository read/write, PR, merge, release or signing authority.

Hashes are integrity checks, not signatures. Windows signing remains a separate release hardening gate.

## 9. Retired dedicated self-maintenance direction

The former dedicated self-maintenance / self-repair / upstream BUG-report product lane is retired. It must not reappear as a separate resident cognition stack, maintenance runtime, repair workflow, transport/intake/reconcile control plane, maintenance-specific UI/RPC, or special repository-authority path.

Normal resident Health, Recovery, Work, Memory, Browser, Desktop, File, Terminal, Git, Repo Test and Update capabilities remain valid. If ZN ever needs to work on code — including its own code — that work must use the same general task/resource model as any other repository task rather than creating a privileged second product inside ZN.

Observing an update channel does not authorize source mutation. Familiarity with its own repository does not grant extra Git/release authority. Any future mechanism in this area must first justify itself by closing a concrete real-user task or safety/continuity blocker and must remain inside the ordinary ZN ownership, authority and verification contracts.

## 10. Testing contract

The steady-state daily CI target is Windows x64. It should run automatically from repository events on a replaceable self-hosted Windows x64 runner rather than depending on a specific runner name or maintainer session. A replacement Windows x64 runner registered to the repository must be able to resume the same workflow.

At minimum protect:

- zero-model resident boot and persistence;
- Situation/Thought/Will continuity;
- task/resource ownership: specialist models/agents and tools must not become owners of durable Work, resident authority or completion judgment;
- model-dependent tasks may fail explicitly on unavailable cognition instead of fabricating a resident-only substitute;
- Body result feedback and independent verification;
- nervous learning/reconsolidation;
- current-reality-gated procedural influence;
- channel restart/idempotency behavior;
- runtime package ownership;
- active ZN renderer/main/preload/protocol ownership;
- release/runtime staging integrity;
- repository-boundary scans that prevent historical/reference product paths, package namespaces or control planes from becoming active dependencies again;
- installed-resident update-channel knowledge must not imply repository write/merge/release authority;
- retired dedicated self-maintenance/reporting control planes must not become active dependencies again;
- managed-browser lifecycle/evidence contracts once implemented;
- real user-browser integration and privacy/permission boundaries once implemented.

Tests retained in the active tree must describe ZN behavior or guard ZN ownership boundaries. Optional Linux/macOS checks remain supplementary unless restored as product targets.