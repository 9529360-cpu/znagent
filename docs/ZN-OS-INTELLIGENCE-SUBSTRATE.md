# ZN OS Intelligence Substrate Contract

> Product-contract supplement: 2026-09-04
>
> This document defines the long-term OS/device integration direction for ZN. It does not claim that ZN currently owns Windows or has system privileges it does not actually possess. Real code, Git state, tests and E2E remain authoritative.

## 1. Product boundary

ZN currently runs as a Windows-first Resident application.

The long-term product target is not to remain a smart desktop app with a chat box. ZN should progressively become a **user-owned Personal Intelligence Layer** that lives above Windows and can participate in the operating environment through durable identity, local context, semantic actions, system events, hardware-aware local cognition and bounded cloud/specialist cognition.

### 1.1 Product-language framing: a Windows intelligent native

At the product level, ZN should be understood as a **Windows intelligent native** ("Windows 智能原住民"): a persistent intelligent resident that treats the user's Windows computing environment as its lived environment rather than as an occasional external tool.

This framing does **not** mean that ZN replaces Windows, runs inside the Windows kernel, or automatically possesses elevated system authority. It means that, within explicit user permission and real platform boundaries, ZN should progressively gain durable, model-independent awareness of and access to the computer it lives on.

A mature Windows-native ZN should therefore:

- remain resident across conversations and ordinary application boundaries;
- know current machine and application facts through deterministic/native sensing where available, instead of asking a model to guess them;
- understand installed applications, processes, windows, files, devices, system state and available execution surfaces as parts of its own operating environment;
- prefer native Windows/application semantics and typed capabilities over screenshot-and-click automation when trustworthy interfaces exist;
- expose those capabilities through one ZN-owned Body / Senses / Capability / Action / Permission / Verification stack;
- treat GPT, Claude, local models and future specialist systems as replaceable CognitiveResources rather than as owners of ZN identity or machine truth;
- allow delegated agents/workers to use bounded portions of the same ZN-owned computer capability system instead of creating separate OS-agent identities or duplicate control stacks;
- verify real effects in the operating environment before considering Work complete.

In short:

```text
Windows is ZN's current primary lived computing environment.
ZN is the persistent intelligent resident inside that environment.
Models are replaceable cognition resources.
Agents/workers are bounded execution units inside ZN.
Computer/application capabilities are part of ZN's body, not model knowledge.
```

The shorthand **PCOS** may be used internally to describe this long-term product shape — persistent personal intelligence + agentic Work + native computer capability — but it must not imply a replacement operating-system kernel. The architectural meaning remains a ZN-owned Personal Intelligence Layer that lives **on top of and through** Windows and its applications.

The target is:

```text
user
  ↓
ZN Self / Memory / Work / Will / Situation / Thought
  ↓
Personal Intelligence Layer
  ├─ Context / semantic index
  ├─ Action fabric
  ├─ Event / proactive substrate
  ├─ Cognition routing
  ├─ Permission / authority boundary
  └─ Result verification
  ↓
Windows / apps / browser / files / terminal / network / devices
```

ZN is not replacing Windows. It is building a persistent intelligence layer **on top of and through** the capabilities Windows and applications expose.

## 2. Why this matters

Modern mobile/PC assistants increasingly work because the device/OS exposes:

- system state and events;
- app/service intents;
- typed actions;
- personal/local indexes;
- notification/calendar/contact/location context;
- foreground/on-screen context;
- hardware acceleration for local inference;
- background lifecycle;
- permissions and user-presence boundaries.

Models improve understanding, planning, generation and novel reasoning, but they do not replace the device capability layer.

Therefore ZN must not collapse into:

```text
Electron chat UI
+ one large model
+ screenshots/clicks for everything
```

## 3. Existing ZN architecture remains the owner

This direction must extend the existing ZN organs rather than add a parallel OS-agent architecture.

```text
Self       -> persistent identity
Body       -> Windows/apps/browser/files/terminal/devices
Senses     -> current system/app/world evidence
Memory     -> durable personal/project context and learned experience
Situation  -> interpretation of current state
Thought    -> reasoning / replanning
Will       -> intention and proactive goals
Work       -> durable user tasks and delegated SubWork
CognitiveResource -> local/cloud/specialist cognition
Recovery   -> restart/non-replay/uncertain-side-effect discipline
```

Do not create a second “OS Agent”, “System Agent”, “Device Agent” or separate resident identity.

## 4. Native semantic capability before GUI automation

ZN should prefer the highest-fidelity trustworthy execution plane available for a task.

Default order:

```text
native OS/app semantic API or typed action
→ trusted app/browser extension/native bridge
→ accessibility/UIA semantic control
→ DOM/browser semantic control
→ keyboard/pointer/visual computer use
```

This is not an absolute rule: task reality, permissions and available state decide the actual path. But if a reliable typed semantic action exists, ZN should not deliberately simulate a human click sequence merely because computer-use is available.

Examples:

- changing a known Windows setting should prefer a supported system API when available;
- querying a local file should prefer filesystem/index APIs over visually opening Explorer;
- calendar/contact/app operations should prefer trusted semantic APIs when available;
- authenticated web work may still require the User Browser Bridge because the real session state exists there;
- unknown third-party desktop applications may require UIA/vision fallback.

## 5. Action Fabric

ZN should evolve from a collection of manually selected tools into a discoverable **Action Fabric**.

A useful action should eventually carry a semantic contract such as:

```text
ActionDescriptor
- action_id
- provider / application / device
- description
- input_schema
- output_schema
- required_authority
- sensitivity
- preconditions
- postconditions
- verification
- reversibility
- idempotency / replay semantics
- cost / latency hints
```

Actions may come from:

- Win32 / COM / WinRT / Windows APIs;
- filesystem/process/network APIs;
- application APIs/SDKs;
- browser extensions/native messaging;
- DOM/accessibility/UIA;
- MCP or similar external capability protocols;
- OpenAPI/HTTP services;
- Terminal/Git/development tools;
- specialist agents;
- future ZN extensions;
- mature ZN procedural competence when it has truly become resident-owned.

The user does not choose from thousands of Actions. ZN retrieves a small relevant subset for the current Work/Situation.

## 6. Context Fabric

A resident assistant needs more than chat history.

ZN should gradually build a local, provenance-aware context substrate for things such as:

- current foreground app/window/document/page;
- open Work and project context;
- filesystem/project indexes;
- recent user-owned task artifacts;
- semantic local search;
- user-approved personal preferences and relationships;
- application/entity references;
- device/system state;
- relevant event history.

Context must remain source-scoped and permission-aware. A context index is not blanket authority to act on the indexed data.

Do not dump the complete personal context into every model request. Retrieve the smallest relevant context for the current cognition gap.

## 7. Hardware-aware local cognition

ZN should treat local AI capability as a normal CognitiveResource tier.

Target resource ladder:

```text
resident deterministic logic / learned local competence
→ OS-native specialized AI APIs
→ tiny/local model for bounded classification/extraction/ranking
→ local SLM/LLM on available NPU/GPU/CPU
→ user-selected cloud general model
→ stronger specialist/frontier model or coding/research/vision agent
```

Resource selection should consider:

- task capability need;
- privacy/data locality;
- current hardware (CPU/GPU/NPU/RAM/VRAM);
- battery/power state where relevant;
- latency;
- network availability;
- cost/token budget;
- model/provider health;
- user routing policy.

Local execution is not automatically better. Hard cognition should still use a stronger permitted resource when task quality requires it.

## 8. Proactive/Event-driven Resident behavior

ZN should become proactive through **events + Work + Will**, not by continuously asking a large model what to do.

Target pattern:

```text
system/app/user event
→ cheap deterministic/local filter
→ Situation update
→ does this matter to an active goal or known user preference?
→ if needed, bounded local cognition
→ if needed, stronger cognition
→ propose or form Work inside the user's autonomy envelope
→ act / ask / wait
→ verify outcome
```

Potential event sources can include, where supported and authorized:

- calendar changes;
- reminders/deadlines;
- file changes;
- process/app state;
- browser/session state;
- network/device availability;
- user arrival/return to an active Work context;
- external service events;
- future phone/device sensors.

No background event automatically creates broad mutation authority.

## 9. Autonomy envelopes

Proactivity must be controlled by explicit user policy.

The user should eventually be able to express rules such as:

```text
weather/research can run automatically
my private focus blocks may be rearranged automatically
meetings involving other people require approval
purchases require approval
sensitive fields always require user presence
this project is local-model-only
this Work may continue autonomously until a defined checkpoint
```

Autonomy scope belongs to ZN authority policy/Work, not to a model or worker.

## 10. Interaction is not chat-centric

Conversation remains important, but it is only one face of ZN.

Long-term interaction surfaces may include:

- global summon/command;
- voice;
- current-selection/current-window commands;
- Explorer/file context actions;
- browser contextual actions;
- compact overlays;
- Work/progress surface;
- permission/approval cards;
- proactive recommendation/attention cards;
- notifications;
- future phone/device surfaces.

The user should often be able to say only:

```text
“这个整理一下。”
“帮我把这个事情处理掉。”
“昨天那个继续。”
```

because the Resident already owns enough current Work/context to resolve the reference.

## 11. Cross-device direction

The long-term identity model is one ZN with multiple Bodies, not one unrelated ZN per device.

```text
              ZN Self
                 │
        durable Work / Memory
                 │
        ┌────────┼────────┐
        │        │        │
     Windows   Phone    Tablet / future device
       Body      Body       Body
```

A device may have local-only state and permissions, but changing devices must not redefine the assistant identity.

A future task should be able to continue across device boundaries when current authority/evidence permits it.

## 12. Windows-first implementation surfaces

Possible Windows substrate work includes, only when a real E2E requires it:

- Win32 / COM / WinRT integration;
- Windows UI Automation / accessibility;
- filesystem/process/window/session sensing;
- Windows Search / local semantic indexing where technically appropriate;
- notification/event integration;
- Windows ML / ONNX Runtime / DirectML / NPU-capable local inference where available;
- Foundry Local or successor Windows-local model runtimes when product-appropriate;
- browser companion/native messaging;
- application-specific semantic connectors;
- hardware/resource detection;
- secure local credential references and OS permission boundaries.

Do not turn this list into a capability-driven backlog. Add the smallest substrate mechanism required by the next high-value real task.

## 13. Development priority rule

“OS intelligence layer” is a long-horizon architectural direction, not permission to spend months building low-level platform infrastructure.

Every implementation still has to answer:

1. Which real user task currently fails?
2. Which missing OS/context/action/cognition mechanism causes that failure?
3. Is there already an existing ZN Body/Senses/Work mechanism that should be extended instead?
4. Which E2E changes from failure to success after this work?

If there is no direct real-task answer, keep it out of the current mainline.

## 14. Long-term product identity

The intended evolution is:

```text
assistant application
→ resident assistant
→ resident task owner
→ OS-aware personal assistant
→ Windows intelligent native / user-owned Personal Intelligence Layer
→ one persistent intelligence across multiple personal devices
```

The product is not successful because it owns the most models or the most Actions.

It is successful when the user has one persistent assistant that:

- knows enough relevant context without being reintroduced every session;
- can reach real device/app capabilities;
- chooses local, cloud or specialist cognition appropriately;
- acts within explicit authority;
- supervises long Work continuously;
- verifies what actually happened;
- learns from verified experience;
- remains the same assistant as models, applications and devices change.

Related documents:

- `ZN.md`
- `docs/ZN-2035-PERSONAL-ASSISTANT-BLUEPRINT.md`
- `docs/ZN-OS-ASSISTANT-INDUSTRY-RESEARCH.md`
- `docs/ZN-DELEGATED-WORK-DESIGN.md`
- `docs/ZN-REAL-TASK-E2E-CATALOG.md`
