# ZN mature-source extraction plan

> Governing blueprint: `ZN.md`
>
> This document is the implementation contract for adopting mature capability code from the inherited/reference tree. It exists to prevent a recurring failure mode: packaging or calling an old product subsystem wholesale when ZN only needs the engineering mechanisms inside it.

## 1. Non-negotiable rule

ZN does **source-level extraction**, not product-level embedding.

The reference tree is a library of solved engineering problems. When a mature implementation exists, the default is to study it, copy/adapt the useful mechanism into a ZN-owned namespace, remove the old product assumptions, and maintain the resulting code as ZN.

Correct:

```text
mature reference source
→ identify mechanism + edge cases + tests
→ extract the smallest coherent implementation slice
→ move/adapt into ZN namespace
→ replace old config/state/session ownership with ZN ownership
→ preserve relevant provenance/license
→ add ZN behavior tests
→ switch ZN caller to the extracted module
→ delete the compatibility import when no longer needed
```

Incorrect:

```text
need model access → instantiate the old full agent
need terminal → call the old product tool forever
need web search → keep old tool/config/plugin control plane
need Telegram/Discord/WhatsApp → run the old gateway as ZN's communications brain
need release → package the old Python product under a ZN installer
```

Packaging is downstream validation. It is not the architecture and it must not be used to hide product-level dependencies.

## 2. Extraction standard

A capability is considered ZN-owned only when all of the following are true:

1. The production import begins in a ZN namespace.
2. Its public interface is defined by ZN.
3. ZN configuration and credential resolution own its runtime choices.
4. ZN state/session/identity objects own continuity.
5. The extracted code can be tested without starting the old CLI/agent/gateway/desktop.
6. The capability can be packaged without requiring old product entrypoints.
7. Old source may remain beside it as reference, but the active ZN call path does not cross back into the old product control plane.

Copying mature implementation is allowed and often preferred. Cosmetic rewrites are not a goal. The extraction must remove product coupling, not historical ancestry.

## 3. Current mature source map

Repository inspection confirms substantial reusable source already exists.

### 3.1 External cognitive/model resources

Useful mature sources include:

- `agent/transports/chat_completions.py` — OpenAI-compatible transport with provider-specific request normalization, reasoning options, strict-provider sanitization, tool-call compatibility and prompt-cache handling.
- `agent/anthropic_adapter.py` — native Anthropic request/response behavior.
- `agent/gemini_native_adapter.py` — native Gemini behavior and thinking/token handling.
- `agent/transports/*` — normalized transport abstractions and response types.
- `hermes_cli/runtime_provider.py` — mature provider-selection knowledge, useful as reference only; its CLI/config ownership must not survive the extraction.
- provider plugins such as `plugins/model-providers/openrouter/*` — provider-specific metadata/selection behavior worth selectively adopting.

Do **not** port the old conversation loop, prompt-owning AIAgent, old session identity, or full CLI provider orchestration as the ZN cognition layer.

Target ownership:

```text
zn_agent/cognition/
├── request.py          # bounded ZN CognitionRequest/CognitiveIncrement contract
├── resource.py         # provider resource interface
├── router.py           # ZN-owned availability/cost/capability routing
├── transports/
│   ├── openai_compat.py
│   ├── anthropic.py
│   └── gemini.py
└── providers/
    ├── openai.py
    ├── openrouter.py
    ├── anthropic.py
    ├── google.py
    └── ...
```

Extraction order:

1. normalized request/result types;
2. OpenAI-compatible transport because it covers many providers;
3. OpenAI/OpenRouter provider resources;
4. Anthropic native adapter;
5. Gemini native adapter;
6. additional providers as needed;
7. remove `LegacyAIAgentWorkerFactory` from the production resident path.

The resident remains the decision maker. A provider returns a bounded `CognitiveIncrement`; it does not become the agent.

## 4. Terminal/body extraction

The existing `tools/terminal_tool.py` contains substantial mature engineering that should not be discarded: local execution, background sessions, PTY behavior, Docker/cloud backends, workdir validation, process cleanup, interrupt handling, timeout behavior and platform-specific handling.

It is also heavily coupled to old product concepts (`HERMES_*` session state, old approval callbacks, old gateway/session context, Nous-specific managed-tool behavior, old display/config helpers). Therefore copying the whole module unchanged into the final runtime is also wrong.

Target ownership:

```text
zn_agent/body/terminal/
├── types.py
├── service.py          # ZN terminal body interface
├── local.py            # local process + PTY + background session core
├── sessions.py         # process/session lifecycle
├── docker.py           # optional extracted backend
├── ssh.py              # optional extracted backend
├── cloud/              # optional backends only when ZN needs them
└── safety.py           # concrete command/workdir boundaries
```

First extraction slice is **local terminal execution**, because it is fundamental to ZN's computer body. Do not pull Modal/Daytona/Vercel/Docker merely because they exist; port each backend when ZN has a concrete use for it.

Preserve the mature edge cases and their tests where relevant. Replace old session/env ownership with explicit ZN `TerminalRequest`, `TerminalSession` and `TerminalResult` state.

`NativeBody._command()` must eventually call the ZN terminal service directly, not `tools.terminal_tool`.

## 5. Web search/world-sense extraction

The reference `tools/web_tools.py` is already a multi-provider web layer and includes useful source for backend selection, provider normalization, URL-safety boundaries, search/extract behavior, fallbacks and provider plugins.

Mature sources include:

- `tools/web_tools.py`;
- `plugins/web/firecrawl/provider.py`;
- `plugins/web/tavily/provider.py`;
- `plugins/web/parallel/provider.py`;
- `plugins/web/exa/provider.py`;
- other registered web providers and their tests;
- URL safety/normalization helpers that are genuinely provider-independent.

Do not keep `hermes tools`, Hermes config files, Nous subscription routing or the old plugin registry as the owner of ZN world sensing.

Target ownership:

```text
zn_agent/senses/web/
├── types.py
├── resource.py         # SearchResource / ExtractResource interfaces
├── registry.py         # ZN-owned backend registry and availability
├── safety.py           # URL/request safety
└── providers/
    ├── tavily.py
    ├── exa.py
    ├── firecrawl.py
    ├── parallel.py
    ├── searxng.py
    └── ...
```

`NativeWorldSense` continues to own attention, sampling rhythm, persistence and interpretation of world change. The extracted web layer only performs transport/search/extract work.

First extraction slice should provide one reliable configured provider plus a clean provider interface; additional mature providers can then be ported with much less coupling.

## 6. Communication channels extraction

The reference repository contains a large mature messaging/gateway system. Useful sources include:

- `gateway/platforms/base.py` — platform adapter behavior and many delivery edge cases;
- platform adapters under `gateway/platforms/`;
- plugin adapters under `plugins/platforms/`;
- Telegram/Discord/Slack/Signal/WhatsApp/Feishu/DingTalk and related implementations;
- `gateway/session.py`, pairing/authz and relay transport mechanisms where they solve actual channel problems;
- channel-specific message splitting, media handling, thread/reply routing, rate limits, reconnection and webhook/socket behavior.

The old gateway must **not** become ZN's communications brain. ZN resident identity, memory, Will and task processing stay in the resident. A communication channel is an I/O organ.

Target ownership:

```text
zn_agent/channels/
├── event.py            # normalized inbound ZN communication event
├── message.py          # normalized outbound message/media types
├── adapter.py          # channel interface
├── registry.py
├── service.py          # channel lifecycle + resident bridge
└── providers/
    ├── telegram/
    ├── discord/
    ├── slack/
    ├── whatsapp/
    ├── signal/
    └── ...
```

Inbound path:

```text
platform SDK/webhook/socket
→ ZN ChannelAdapter
→ normalized ChannelEvent
→ resident perception/event queue
→ Situation / Thought / action
```

Outbound path:

```text
resident intention/action
→ ZN ChannelMessage
→ selected ChannelAdapter
→ platform API
→ delivery result
→ resident evidence
```

This is important: a message arriving from Telegram is a perception/event for the same ZN resident. It does not start a separate Telegram-owned agent identity.

Extraction order for channels:

1. define normalized channel event/message contracts;
2. extract shared delivery primitives that are genuinely cross-platform;
3. port one high-value channel end to end (Telegram is a strong first candidate because its mature adapter exercises threading/media/reconnect behavior);
4. connect it directly to resident events;
5. port Discord/Slack/WhatsApp/etc. incrementally;
6. only retain shared gateway infrastructure that has a clear ZN consumer.

## 7. What not to extract

Do not blindly migrate these categories:

- old product branding and paths;
- old CLI UX merely because a capability is configured there;
- old full-agent orchestration/prompt ownership;
- old desktop shell/UI;
- old gateway identity/session model when ZN resident already owns identity/continuity;
- vendor/subscription code that ZN does not use;
- every optional backend at once;
- compatibility shims whose only consumer is the old product;
- tests that only freeze old product naming/snapshots rather than useful behavior.

The reference implementation is a quarry, not a dependency graph that must be preserved.

## 8. Revised engineering order

Source extraction comes before formal product packaging.

```text
E0  document the extraction boundary                      [this document]
E1  establish ZN-native resource/channel/body interfaces
E2  extract external model transports/providers
E3  extract local terminal body and then needed backends
E4  extract web search/extract providers
E5  extract communication channel framework + first channel
E6  switch resident production callers to ZN-owned modules
E7  build independent ZN Electron main/preload/UI
E8  remove active old-product imports from the runtime
E9  package the independently bootable ZN product
E10 verify clean-machine install, upgrade and multi-OS release
```

Packaging work before E8 is allowed only as a narrow development experiment. It must not dictate architecture or be treated as the release target.

## 9. Immediate code target

The next implementation work should not be another release-package patch.

Start with the common ownership seam:

1. add ZN-native resource contracts for external cognition;
2. extract the OpenAI-compatible transport/provider path from the mature source into that contract;
3. keep resident calls bounded (`CognitionRequest → CognitiveIncrement`);
4. add tests that can run without importing `hermes_cli` or constructing `run_agent.AIAgent`;
5. then extract the local terminal body and web resource using the same ownership rule.

Communication-channel contracts should be created before the first channel is ported, so Telegram/Discord/Slack do not recreate separate mini-agents.

## 10. Completion test

This extraction phase is complete when ZN can, from its own namespaces and state:

- consult a real external model;
- execute a local terminal command and observe the result;
- search the web and feed the observation into `NativeWorldSense`;
- receive and send through at least one external communication channel;

without importing the old product CLI/agent/gateway as the control plane.

Only after that boundary exists should formal self-contained packaging become a primary milestone.
