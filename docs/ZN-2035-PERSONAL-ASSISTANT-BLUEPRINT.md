# ZN 2035 Personal Assistant Blueprint

> Long-horizon product blueprint, written 2026-09-04.
>
> This is a directional architecture and product plan, not an implementation-status claim. Existing implementation facts remain in `docs/ZN-IMPLEMENTATION-STATUS.md`.

## 1. Product thesis

ZN should evolve from a desktop agent into a **user-owned personal intelligence layer** that lives across the computer and, later, across the user’s devices.

The target is not “a better chatbot”. The target is:

```text
always-present resident
+ personal context and memory
+ real device/app action capability
+ local + cloud cognition routing
+ long-running Work supervision
+ proactive event-driven behavior
+ verified learning from experience
+ extensible ecosystem
= personal assistant that becomes part of the user's computing environment
```

A mature ZN should feel less like opening an application and more like having a competent assistant already present in the computer.

The user can still converse naturally, but conversation is only one surface. ZN should also understand current screen/context, ongoing projects, files, apps, browser state, time, events, habits and explicit long-term goals.

## 2. What the next 5–10 years likely look like

The likely evolution of personal assistants is:

### Stage A — LLM copilots

```text
chat
→ model
→ tools
→ answer
```

Useful, but mostly request/response and session-oriented.

### Stage B — agentic applications

```text
goal
→ model plans
→ tools/apps/browser
→ multi-step completion
```

This is where much of the industry is now.

### Stage C — resident personal agents

```text
persistent identity
+ durable goals
+ personal context
+ OS/app awareness
+ proactive triggers
+ specialist delegation
+ long-running background work
```

The assistant no longer resets psychologically and operationally every conversation.

### Stage D — personal intelligence layer

```text
user intent and habits
↕
resident intelligence
↕
OS / apps / web / devices / cloud / specialists
```

At this point the assistant behaves like an intelligent coordination layer above the operating system rather than one application among many.

### Stage E — companion ecosystem

The user owns a persistent assistant identity that can move across PC, phone, tablet, vehicle, wearables and future devices while preserving:

- identity;
- projects and Work;
- user preferences;
- permissions;
- learned procedures;
- privacy policy;
- active tasks;
- trusted relationships with external services/agents.

The devices become different bodies/surfaces of one user-owned assistant rather than independent assistant instances.

## 3. ZN's architectural position

ZN should not try to beat every foundation-model company at model training.

Its long-term advantage should be **continuity + orchestration + embodiment + ownership**.

Models improve rapidly and can be replaced. The assistant relationship should not disappear every time the model changes.

Therefore:

```text
ZN owns:
identity
memory
user relationship
Work
Will
permissions
world state
resource routing
learning
verification
continuity

Models own:
bounded cognition and specialist reasoning

Tools/OS own:
real sensing and effects
```

The user experiences one ZN even when the cognitive backend changes from GPT to Claude, Gemini, a local model, a coding agent, or a future model family.

## 4. Layer 0 — Resident / OS Intelligence Substrate

This layer is required before the five application-level layers. Without it, ZN remains an intelligent desktop app rather than a resident intelligence layer.

### 4.1 Responsibilities

Layer 0 should provide stable, model-independent access to the user's actual computing environment:

- process/app identity;
- windows and foreground/focus state;
- accessibility/UI tree;
- clipboard;
- filesystem and file metadata;
- search/indexing;
- installed applications;
- notifications;
- audio/microphone where explicitly authorized;
- screen/display state;
- power/battery/network state;
- device capabilities;
- browser windows/tabs/session bridges;
- local terminal/process execution;
- calendars/mail/contacts through authorized connectors;
- hardware capability discovery (CPU/GPU/NPU/RAM/storage);
- local inference runtime discovery;
- background lifecycle and wake triggers;
- secure credential references and OS permission boundaries.

### 4.2 Windows-first technical stack

Near-term Windows-first implementation should prefer native OS capability instead of forcing everything through vision/UI automation.

Suggested stack:

```text
Resident core:
Python initially for existing ZN runtime
+ selective Rust/C++ native components where lifecycle/perf/security justify it

Windows integration:
Win32 / COM / WinRT
UI Automation (UIA)
Windows Accessibility APIs
PowerShell only as an execution tool, not control-plane truth
ETW / Event Log where useful
Windows Search / indexing APIs where accessible
Windows notifications APIs
Task Scheduler / service / background lifecycle primitives where appropriate

Local AI:
ONNX Runtime / Windows ML
Foundry Local where product-ready
DirectML / NPU-capable Windows APIs
llama.cpp / MLX-like equivalents only where Windows support and packaging make sense

Storage:
SQLite for durable structured state
content-addressed local artifact store where useful
vector/embedding index only for retrieval problems that require it
full-text search for exact user history and Work

IPC:
local authenticated RPC
named pipes / local sockets where suitable
bounded Electron ↔ Resident bridge
```

Do not add Rust/C++ merely because it sounds more systems-level. Use native components only where Python/Electron genuinely block latency, security, packaging, hardware access or lifecycle reliability.

### 4.3 Device capability graph

ZN should maintain a current capability view:

```text
DeviceCapabilityGraph
- installed apps
- available system APIs
- connected browsers
- available local models
- GPU/NPU capability
- online cloud providers
- authorized accounts/connectors
- accessible devices
- network availability
- current restrictions
```

Task planning should depend on actual capabilities, not assumptions.

## 5. Layer 1 — Redefine interaction: not a chat box

Chat remains useful, but it should not be the product's primary mental model.

### 5.1 Interaction surfaces

ZN should have several lightweight surfaces:

- global invocation / command palette;
- voice conversation;
- small resident status surface;
- task/Work board;
- contextual overlay near the current app/window;
- selection-based actions on text/files/images;
- notification/action cards;
- background progress/activity timeline;
- permission prompts;
- quick “continue/cancel/change direction” controls.

The user should be able to say a broad request without moving everything into a dedicated ZN window.

Examples:

```text
select file → “把这个整理一下”

current browser → “这个页面里的订单你帮我处理完”

global voice → “昨天那个项目继续”

notification → “下午会议提前了，要不要把冲突的安排一起处理？”
```

### 5.2 Context attachment instead of repeated explanation

Interaction should automatically bind the current relevant context when authorized:

- selected file;
- foreground app;
- current browser tab;
- current project/workspace;
- current Work;
- current meeting/event;
- selected text/image.

The user should not repeatedly paste context that ZN can already sense safely.

### 5.3 Human interruptibility

Every autonomous operation should be steerable:

```text
pause
cancel
change direction
approve
reject
explain
show evidence
```

Long tasks should feel supervised, not opaque.

## 6. Layer 2 — Memory, identity and personality

The goal is to eliminate the feeling that the assistant “meets the user again every morning”.

### 6.1 Identity

ZN needs a persistent Self that survives:

- restarts;
- model replacement;
- app upgrades;
- device replacement/migration when explicitly transferred;
- UI redesign.

### 6.2 Memory layers

ZN should keep distinct memory types rather than one vector database:

```text
Working memory
→ what matters right now

Episodic memory
→ verified previous events/Work

Semantic personal memory
→ stable user/project facts with provenance

Preference memory
→ explicit/inferred preferences with confidence

Procedural memory
→ verified repeated ways of doing things

Relationship/context memory
→ people/projects/entities and their links
```

The existing ZN memory/learning architecture should remain the owner; new storage technologies are implementation choices only.

### 6.3 Personal knowledge graph

Over time ZN should build a local provenance-aware personal graph:

```text
User
├─ people
├─ projects
├─ organizations
├─ files
├─ applications
├─ websites
├─ recurring tasks
├─ preferences
├─ devices
└─ prior Work
```

This graph must never be treated as infallible truth. Every important fact should retain source/provenance, confidence and freshness.

### 6.4 Personality is behavioral continuity, not a prompt

Personality should emerge from:

- stable interaction style;
- user preferences;
- remembered relationship context;
- consistent decision principles;
- boundaries/permissions;
- learned ways of helping.

It should not be only a hidden system prompt saying “be friendly”.

### 6.5 Memory governance

The user must be able to:

```text
see what ZN remembers
correct it
forget it
disable categories
mark sensitive things non-retainable
export/migrate personal memory
```

## 7. Layer 3 — Action Fabric: tens of thousands of actions without tens of thousands of hard-coded functions

The objective is not literally to hand-write 50,000 action functions. The objective is to expose a very large action space through a small number of consistent semantic mechanisms.

### 7.1 Action hierarchy

Actions should be layered:

```text
Level A — OS primitives
open app, focus window, read clipboard, move/copy file, invoke command

Level B — semantic app actions
create calendar event, send email draft, open document, add row, start call

Level C — UI semantic actions
focus/click/type/select/drag when no native semantic API exists

Level D — web/browser actions
navigate, extract, submit, upload, interact with authenticated session

Level E — composite learned procedures
“prepare weekly report”
“deploy this project the usual way”
```

### 7.2 Action schema

Every actionable capability should expose a common contract similar to:

```text
ActionDescriptor
- action_id
- provider/app
- description
- input schema
- output schema
- effect class
- required authority
- sensitivity
- reversibility
- preconditions
- postcondition / verification contract
- idempotency / replay semantics
- cost/latency estimate
```

This schema is more important than having thousands of bespoke tools.

### 7.3 Capability discovery

ZN should discover actions from several sources:

- ZN native actions;
- Windows/system APIs;
- app plugins/adapters;
- browser companion extension;
- MCP-like servers;
- A2A/agent protocols;
- REST/OpenAPI services;
- application automation/accessibility schemas;
- learned verified procedures.

These should be normalized behind a ZN-owned action registry.

### 7.4 Prefer semantic action over visual automation

Priority should be:

```text
trusted native API/action
> application semantic/accessibility API
> browser semantic DOM/accessibility
> desktop UI automation
> raw visual/coordinate control
```

Computer vision remains essential for unknown interfaces, but it should be the fallback rather than the default when better semantic evidence exists.

### 7.5 Action graph instead of giant prompt

At runtime ZN should retrieve only the actions relevant to the current task/context rather than injecting thousands of tool definitions into every model prompt.

Use:

- capability metadata;
- app/context identity;
- task domain;
- permission scope;
- prior success evidence;
- semantic search over descriptors.

## 8. Layer 4 — Active Agent: from reactive execution to bounded proactivity

A real assistant does not only wait for direct commands.

### 8.1 Event-driven Will

ZN should observe authorized triggers:

- calendar changes;
- deadlines;
- incoming messages/mail;
- file/project changes;
- weather/travel conditions;
- system/device health;
- long-running task completion;
- user habits;
- explicit recurring goals.

But these triggers should feed **Will/Situation**, not directly trigger arbitrary actions.

### 8.2 Autonomy envelopes

Each proactive capability needs an explicit user-defined autonomy level.

Example:

```text
Observe only
Suggest
Prepare/draft
Execute reversible actions
Execute bounded external actions
Always require approval for sensitive/irreversible effects
```

The envelope should be scoped by domain/app/site/action, not one dangerous “fully autonomous” global switch.

### 8.3 Example: calendar + weather + food + meeting coordination

User policy might say:

```text
- You may monitor calendar conflicts.
- You may check weather/travel time automatically.
- You may propose food orders.
- You may reschedule internal focus blocks automatically.
- You must ask before changing meetings with other people.
- You must ask before placing any paid order.
```

Then ZN could:

```text
calendar event changes
→ detect lunch/meeting conflict
→ check weather/travel time locally/web
→ inspect preferences and nearby options
→ propose plan
→ move permitted personal block automatically
→ ask once for meeting-party change and paid order
→ verify calendar/order result after approval
```

The important architecture is not “weather agent + food agent”. It is Will + Work + Action authority + current evidence.

### 8.4 Background autonomy without constant LLM loops

Proactive operation should be event-driven and tiered:

```text
cheap deterministic trigger
→ local classifier/small model if needed
→ create/update Situation
→ strong cognition only if the event matters
→ Work only if an actual goal/action is justified
```

Do not run a frontier model every minute asking “anything to do?”.

## 9. Layer 5 — Ecosystem and evolution: from tool to partner

ZN should become more useful because the ecosystem grows and because ZN learns verified experience.

### 9.1 Capability ecosystem

Third parties should eventually be able to expose:

- actions;
- sensors/data sources;
- specialist cognition;
- domain adapters;
- device bridges;
- automation providers.

But extensions do not become independent resident identities.

### 9.2 Extension contract

A ZN extension should declare:

```text
identity/provider
capabilities/actions
input/output schemas
authority requirements
data accessed
data leaving device
side effects
verification support
version/compatibility
health/status
```

Extensions should be sandboxed/permissioned where feasible.

### 9.3 Specialist agent ecosystem

Coding agents, research agents, design agents and future specialists can run as delegated workers under Work.

ZN provides:

```text
bounded objective
context pack
tools/authority
acceptance criteria
budget
```

The specialist returns result/evidence/blockers. ZN keeps root ownership.

### 9.4 Learning/evolution

ZN’s evolution should have several channels:

```text
software updates
→ new built-in competence

new models/providers
→ better replaceable cognition

new extensions/actions
→ larger body/ecosystem

verified user experience
→ personalized memory/procedural competence

new devices
→ more bodies/sensors
```

This means ZN can improve without redefining its identity.

## 10. Cognition hierarchy

ZN should use a tiered cognition architecture.

### Tier 0 — deterministic/native

Use for:

- state lookup;
- known rules;
- permissions;
- timestamps;
- waiting/polling;
- exact file/process/app identity;
- postcondition checks;
- known transformations.

### Tier 1 — tiny/local specialized models

Use for high-frequency bounded tasks:

- classification;
- semantic search/ranking;
- entity extraction;
- embeddings;
- wake-word/audio intent;
- screenshot/UI element classification;
- short summarization where sufficient.

### Tier 2 — local SLM/LLM

Use for:

- private short-form reasoning;
- offline assistance;
- local document understanding;
- intent decomposition;
- cheap background cognition.

### Tier 3 — general cloud frontier model

Use for:

- hard planning;
- ambiguity;
- broad reasoning;
- language generation;
- unfamiliar situations.

### Tier 4 — specialist models/agents

Use for:

- software engineering;
- deep research;
- vision/video;
- legal/scientific domain reasoning;
- other expert tasks.

Routing should depend on capability, privacy, cost, latency, availability, historical performance and user policy.

## 11. Hardware-aware local intelligence

Future personal assistants should know the machine they live on.

ZN should eventually measure:

```text
CPU
GPU
NPU
VRAM/RAM
power mode
battery
thermal state
network
available local models
```

Then route local workloads accordingly.

Example:

```text
battery saver
→ avoid expensive local vision model

private local file
→ prefer local SLM if sufficient

large coding task
→ specialist cloud coding agent if user allows

no network
→ degrade to local abilities instead of losing identity/function entirely
```

## 12. Privacy architecture

Personal assistant usefulness and privacy are tightly coupled because the most valuable context is personal.

Default principles:

- local-first storage for identity/Work/memory;
- local preprocessing/filtering before cloud where feasible;
- bounded context disclosure to models;
- per-provider data policy;
- explicit sensitive-memory exclusion;
- no silent copying of browser credential stores;
- user-visible audit of meaningful external actions;
- revocable site/app/account permissions;
- encrypted storage for sensitive persisted material where appropriate.

The user should know:

```text
what ZN knows
what leaves the device
which model/provider sees it
which action will happen
which account/site/app it affects
```

## 13. Verification layer

This remains one of ZN’s most important differentiators.

Every action system should distinguish:

```text
dispatch succeeded
vs
real effect verified
vs
root user goal completed
```

Examples:

```text
send API returned 200
!= recipient/message state verified

click succeeded
!= form submitted

model wrote patch
!= program works

calendar API accepted request
!= desired schedule has no conflict
```

The assistant should earn autonomy through reliable verification.

## 14. Recommended technical architecture

Long-term logical architecture:

```text
                  User / Context / Events
                           │
                           ▼
                   ┌───────────────┐
                   │    ZN Self    │
                   └───────┬───────┘
                           │
        ┌──────────────────┼──────────────────┐
        ▼                  ▼                  ▼
      Will               Memory              Work
        │                  │                  │
        └─────────────┬────┴─────┬────────────┘
                      ▼          ▼
                  Situation    Thought
                      │          │
                      └────┬─────┘
                           ▼
                 Resource Orchestration
            ┌──────────────┼──────────────┐
            ▼              ▼              ▼
       Cognition       Action Fabric     Sensors
            │              │              │
    local/cloud/       OS/App/Web/       OS/App/Web/
    specialist        Device actions     Device state
            │              │              │
            └──────────────┬──────────────┘
                           ▼
                       Reality
                           │
                           ▼
                      Verification
                           │
                           └──→ Work / Memory / Learning
```

This extends the current ZN architecture rather than replacing it.

## 15. Concrete technology choices for ZN

### Now / Windows-first

Keep:

- Python Resident core;
- SQLite durable store;
- Electron desktop face;
- UIA/Win32/desktop automation;
- browser managed plane + User Browser Bridge;
- current CognitiveResource / ModelRouter;
- current Work/Memory/Recovery.

Add incrementally:

- durable WorkItem/WorkerRun supervision;
- model policy/routing per WorkItem;
- semantic Action registry;
- Windows native capability adapters;
- local semantic index/search;
- local model runtime adapter;
- event/trigger service;
- user autonomy policy store;
- personal entity/context graph;
- improved non-chat resident surfaces.

### Later

Evaluate:

- Rust service for hardened native host / high-frequency sensors / local inference coordination;
- protobuf/gRPC or a compact typed local protocol where current RPC becomes limiting;
- ONNX Runtime/Windows ML/Foundry Local for hardware local inference;
- DuckDB/Arrow only for large analytical local data tasks;
- encrypted SQLite/OS-protected key material for sensitive state;
- plugin sandbox/process isolation;
- mobile companion apps and encrypted device sync;
- CRDT/event-log mechanisms if true multi-device concurrent Work becomes necessary.

Do not adopt these technologies before a concrete product integration need proves the need.

## 16. Roadmap: how ZN should evolve

### Horizon 1 — Reliable resident worker

Goal: ZN can independently complete a broad set of real Windows tasks.

Focus:

- authenticated browser;
- desktop/file/terminal;
- replanning;
- Work continuation;
- verification;
- delegated Work;
- model routing.

### Horizon 2 — Personal context assistant

Goal: ZN consistently knows the user’s active projects/context.

Focus:

- personal search/index;
- entity/project graph;
- explicit memory UX;
- contextual invocation;
- habits/preferences;
- local model tier.

### Horizon 3 — Proactive resident

Goal: ZN can safely advance work without waiting for every prompt.

Focus:

- event triggers;
- autonomy envelopes;
- recurring/long-running goals;
- bounded background Work;
- meaningful notifications;
- active steering.

### Horizon 4 — Personal intelligence platform

Goal: external apps/services/devices expose semantic actions to ZN.

Focus:

- Action/Extension SDK;
- third-party integrations;
- device bridges;
- specialist agent ecosystem;
- fine-grained permission/audit system.

### Horizon 5 — Cross-device companion

Goal: one ZN accompanies the user across devices while preserving identity and Work.

Focus:

- phone companion;
- device handoff;
- encrypted memory/Work sync;
- multiple bodies;
- context-aware execution placement;
- user-owned data portability.

## 17. What not to do

Avoid these strategic traps:

- building only a chat UI;
- assuming one frontier LLM should handle every micro-step;
- trying to replace foundation-model providers with a homegrown giant model;
- implementing thousands of bespoke actions without a semantic action contract;
- using only computer vision when semantic/native APIs exist;
- storing all memory as embeddings/transcripts;
- implementing proactivity as an infinite autonomous LLM loop;
- treating every extension/worker as a new agent identity;
- building a generic multi-agent framework instead of real user tasks;
- optimizing token cost at the expense of actual task success;
- declaring completion from model/tool self-report instead of reality.

## 18. The core product sentence

> **ZN is a user-owned, long-lived personal intelligence layer that lives with the user’s computer, understands ongoing context, remembers verified experience, autonomously combines local and cloud cognition with real device/app actions, supervises long-running work, and increasingly helps before the user has to explain every step.**

That is the direction against which future major architecture decisions should be judged.