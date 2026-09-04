# ZN OS-Level Assistant Industry Research

> Research snapshot: 2026-09-04
>
> This document records current public evidence from device/OS vendors and the product lessons ZN should absorb. It does not claim these vendors expose their full internal implementation. Separate verified facts from ZN inference.

## 1. Core conclusion

The strongest current device-assistant products are converging on a hybrid architecture:

```text
OS/device-owned context + intent + action + permission substrate
+ local/on-device small or medium models
+ cloud/frontier models for harder cognition
+ system/app service schemas
+ proactive event/recommendation engines
+ personal local indexes / memory
= modern personal assistant
```

This is materially different from:

```text
chat box
+ one large model
+ a bag of tools
```

The model is important, but model quality alone does not create a resident assistant. The assistant becomes useful because the operating system/device can expose real state, real actions, personal context, permissions, hardware acceleration, background lifecycle and trusted service integration.

## 2. What assistants used before large language models

Earlier phone/PC assistants were not “model-free”. They generally used smaller specialized models and deterministic systems:

- automatic speech recognition;
- wake-word detection;
- intent classification;
- slot/entity extraction;
- ranking/recommendation models;
- knowledge graphs and search indexes;
- rules/state machines;
- app/service APIs;
- notification/calendar/location/event triggers;
- device control APIs;
- cloud NLP/search for harder queries.

They did not need a frontier LLM to turn on Bluetooth, create a calendar event, call a contact, change a system setting or launch a known app function. Those tasks were primarily an **intent-to-capability mapping problem**.

Large models improve natural-language understanding, ambiguous intent resolution, planning, generation, multimodal reasoning and novel problem solving. They do not remove the need for the underlying device capability layer.

This distinction is foundational for ZN.

## 3. HONOR / YOYO

Primary official references:

- https://www.honor.com/cn/news/magicos-launch-2024/
- https://www.honor.com/cn/news/honor-magicos-9-launch/
- https://www.honor.com/cn/magic-os-9/
- https://www.honor.com/cn/tech/pc-yoyo-assistant-2/
- https://www.honor.com/cn/tech/yoyo-claw/

### 3.1 Verified public direction

MagicOS 8.0 publicly described a model in which an **on-device platform AI model acts as the central controller**, understands intent, decomposes/orchestrates tasks, connects to cloud large models, and dispatches/fuses atomic services. HONOR also emphasized filtering private personal information on-device before cloud use.

MagicOS 9.0 then described YOYO Agent as combining:

- natural-language understanding and computer vision;
- user habit learning and scenario sensing;
- intent recognition and decision making;
- in-app and cross-app operation.

HONOR also described an on-device personal knowledge base built from behavior, personal memory graphs and profile indexes, with user-visible control to inspect/delete stored personal memory.

The Windows YOYO product separately exposes semantic local search, DeepSeek-enhanced reasoning/coding, Windows/system control, first-party app control, cross-device control and cross-app control.

### 3.2 ZN lesson

HONOR is strong evidence for the architecture:

```text
local controller / personal context
→ understand intent
→ choose local atomic service when sufficient
→ call cloud model when difficult cognition is required
→ execute through device/app capabilities
```

This is close to the ZN principle that the Resident owns Work and resource routing while models are replaceable cognitive resources.

ZN should go further on explicit Work continuity, independent result verification, non-replay and user-scoped authority.

## 4. vivo / BlueLM / Blue Heart Intelligence

Primary official references:

- https://www.vivo.com.cn/brand/news/detail?id=1199&type=0
- https://www.vivo.com.cn/brand/news/detail?id=1270
- https://www.vivo.com.cn/service/questions/all?categoryId=170&questionId=1397
- https://www.vivo.com.cn/service/questions/all?categoryId=170&questionId=1745
- https://developers.vivo.com/product/ai/bluelm

### 4.1 Verified public direction

vivo publicly described a model matrix spanning multiple sizes. In its 2023 announcement:

- ~1B-class models target on-device text tasks;
- ~7B-class models support phone/on-device and cloud scenarios;
- larger 70B/130B/175B-class models target cloud and harder reasoning/task orchestration.

In 2024 vivo described “Blue Heart Intelligence” as large-model technology deeply integrated into the phone OS, including:

- personal context and preferences;
- a local knowledge graph to build shared user-device memory;
- multimodal interaction;
- a service engine with data services, intent sensing and decision services;
- an intent framework that can plan and execute tasks;
- PhoneGPT-style screen understanding and app operation.

Blue Heart Xiao V exposes natural language local search, system/device management, screen understanding, calendar management and proactive service recommendations based on usage habits/events.

### 4.2 ZN lesson

vivo is direct evidence that “one giant model does everything” is not the necessary device architecture.

A practical assistant can use:

```text
small local cognition for high-frequency/private/latency-sensitive work
+ medium local cognition for richer understanding
+ cloud large models for hard reasoning
+ OS-level service/intent framework for real execution
```

ZN should therefore make hardware-aware local cognition a first-class resource tier, but never confuse local-model availability with action authority or task completion.

## 5. Huawei / Xiaoyi / HarmonyOS

Primary official references:

- https://developer.huawei.com/consumer/cn/sdk/intents-kit
- https://developer.huawei.com/consumer/cn/huawei-hag
- https://consumer.huawei.com/cn/mobileservices/celia/
- https://developer.huawei.com/consumer/cn/doc/service/harmonyos-service-0000001238266717/
- https://developer.huawei.com/consumer/cn/doc/

### 5.1 Verified public direction

HarmonyOS exposes Intents Kit as a **system-level intent standard** connecting application/meta-service business functions to system entry points. Public examples include:

- local content search;
- proactive service suggestions based on user habit/subscribed event/location;
- natural-language task execution powered by model understanding;
- automatic orchestration using both LUI and GUI.

Huawei’s current Xiaoyi pages describe a HarmonyOS multimodal agent framework (HMAF) that combines voice, image and gesture inputs, supports application autonomy, system-level continuous service and multi-agent collaboration. Huawei also exposes an A2A agent protocol and an agent/skill ecosystem compatible with device, cloud, MCP and intent tools.

HarmonyOS developer documentation also exposes local AI substrate pieces such as lightweight inference, cross-chip neural-network runtime, speech/vision/NLU services and system capabilities.

### 5.2 ZN lesson

The important lesson is not to copy Huawei’s platform taxonomy. It is that mature assistants need a **semantic contract between natural intent and real app/service capabilities**.

ZN should build its own Windows-first Action Schema / capability registry so that Browser/Desktop/Terminal/UI automation are not the only way to reach functionality. Where a trusted semantic/native API exists, ZN should prefer it over visual automation.

## 6. Apple / Siri AI / Apple Intelligence

Primary official references:

- https://developer.apple.com/apple-intelligence/
- https://developer.apple.com/documentation/appintents/apple-intelligence-and-siri-ai
- https://www.apple.com/newsroom/2026/06/apple-introduces-siri-ai-a-profoundly-more-capable-and-personal-assistant/
- https://security.apple.com/documentation/private-cloud-compute/

### 6.1 Verified public direction

Apple’s current architecture exposes several pieces relevant to ZN:

- on-device foundation models;
- Private Cloud Compute for harder requests;
- personal-context understanding across messages, mail, photos and integrated third-party content;
- on-screen awareness;
- a system orchestrator;
- Spotlight semantic indexes;
- an App Toolbox built from App Intents and app schemas;
- action/entity donation so the system can learn usage patterns and anticipate relevant future actions.

The important architectural pattern is:

```text
personal context/index stays close to device
+ app actions are exposed as typed semantic contracts
+ system orchestrator selects capabilities
+ larger cloud cognition is used when necessary
```

### 6.2 ZN lesson

ZN should treat conversation as only one interaction surface. Personal context, on-screen context and semantic actions should be available without forcing the user to explain everything in a chat turn.

App Intents also supports the ZN direction that thousands of useful actions should be **declared/discovered through schemas**, not individually hard-coded into a giant prompt.

## 7. Google / Gemini Intelligence on Android

Primary official references:

- https://blog.google/security/android-gemini-intelligence-security-privacy/
- https://blog.google/innovation-and-ai/products/gemini-app/android-multi-step-tasks/
- https://blog.google/innovation-and-ai/products/gemini-app/next-evolution-gemini-app/

### 7.1 Verified public direction

Google describes Android as evolving from an operating system into an “intelligence system” that understands context, anticipates needs and completes tasks. Current multi-step automation previews use controlled/limited app environments, user-visible live progress, interruptibility and user control.

Google is also explicitly moving toward proactive, background, around-the-clock assistance.

### 7.2 ZN lesson

Proactivity must be paired with:

- explicit user control;
- transparent progress;
- limited execution scope;
- the ability to intervene/stop;
- careful privacy boundaries.

ZN should not implement “always autonomous” as an infinite model loop.

## 8. Microsoft / Windows local AI

Primary official references:

- https://learn.microsoft.com/en-us/windows/ai/
- https://learn.microsoft.com/en-us/windows/ai/windows-ai-comparison
- https://learn.microsoft.com/en-us/windows/ai/apis/local-llms
- https://support.microsoft.com/en-us/windows/experience/performance-optimization/search-indexing-in-windows

### 8.1 Verified public direction

Microsoft’s current Windows AI stack includes:

- built-in on-device models/APIs for supported hardware;
- NPU-tuned local language models;
- Foundry Local for local open-source LLMs;
- Windows ML / ONNX-based custom local inference with hardware acceleration;
- semantic indexing of local documents/images on Copilot+ PCs, stored locally;
- cloud AI as a fallback for harder requests.

Microsoft explicitly documents a resilient local-to-cloud tiering approach and hardware-aware execution across NPU/GPU/CPU.

### 8.2 ZN lesson

Because ZN is Windows-first today, this is particularly important.

ZN should eventually detect local AI capability and treat it as a normal cognitive-resource tier:

```text
OS-native/local specialized API
→ local SLM/LLM on NPU/GPU
→ user-selected cloud model
→ stronger specialist/frontier model when the task warrants it
```

The local layer is useful for privacy, latency, offline operation and avoiding cloud/token cost on high-frequency bounded cognition.

## 9. Cross-vendor convergence

The vendors differ in implementation and ecosystem, but the common pattern is strong:

| Need | Converging implementation |
| --- | --- |
| Natural intent | language/multimodal models |
| Fast/high-frequency cognition | local/edge models |
| Hard cognition | cloud/frontier models |
| Personal context | local semantic index / knowledge graph / profile |
| Real actions | intent schemas / app actions / system APIs / controlled UI automation |
| On-screen understanding | vision + UI semantics |
| Proactivity | event/habit/time/location recommendation engines |
| Background work | durable task/run state + visible progress |
| Privacy | local-first, scoped cloud disclosure |
| Ecosystem | app/skill/agent protocols and action schemas |
| Hardware | CPU/GPU/NPU-aware local inference |

## 10. What this means for ZN

ZN should not compete by training one proprietary giant model.

ZN’s durable differentiation should be:

1. **One persistent user-owned Resident identity.**
2. **A trustworthy personal memory/context substrate.**
3. **A Windows-first semantic Action fabric reaching real OS/apps/files/browser/terminal.**
4. **A Work system that owns long-running goals and delegated workers.**
5. **A cognition router spanning local models, cloud models and specialist agents.**
6. **Independent current-world verification and non-replay safety.**
7. **A proactive event-driven Will that acts within explicit autonomy envelopes.**
8. **An ecosystem where capabilities can be added without changing who ZN is.**

The long-horizon product design derived from this research is recorded in `docs/ZN-2035-PERSONAL-ASSISTANT-BLUEPRINT.md`.