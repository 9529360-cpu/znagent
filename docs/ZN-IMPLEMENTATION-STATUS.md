# ZN implementation status

> Architecture contract: [`../ZN.md`](../ZN.md)
>
> Source-extraction contract: [`ZN-SOURCE-EXTRACTION.md`](ZN-SOURCE-EXTRACTION.md)
>
> This file records **what is actually implemented now**. `ZN.md` remains the forward product contract; this ledger follows implementation so later development never has to infer architecture from scattered code.

## Current development rule

```text
ZN.md / extraction contract first
→ inspect mature reference source
→ extract coherent mechanism into ZN ownership
→ switch active ZN caller
→ run real tests
→ update this status ledger
```

Formal packaging is not the current architecture driver. The inherited package shape remains transitional until the active runtime and desktop boundaries are independently ZN-owned.

## Verification state

The source-extraction baseline through commit `998f680` passed ordinary branch CI:

- `ZN Kernel / Python`: success
- `Electron / TypeScript`: success

The newer Anthropic, Gemini, Telegram-authorization and Exa extraction commits are being validated by the same ordinary branch CI. They are not treated as the next stable baseline until those checks report success. Expensive multi-OS release packaging remains opt-in only.

## External cognitive resources

Status: **OpenAI-compatible, Anthropic native and Gemini native production seams extracted**

Implemented:

- `agent/kernel/cognitive_resource.py`
  - ZN-owned `CognitiveResource` / `CognitiveIncrement` boundary;
  - direct OpenAI-compatible transport;
  - ZN-owned endpoint/credential resolution for OpenAI, OpenRouter, DeepSeek, Groq, Mistral, xAI and local compatible endpoints;
  - bounded context + bounded question request shape;
  - response and token-usage normalization.
- `agent/kernel/anthropic_resource.py`
  - native Anthropic Messages API;
  - native system/user request shape;
  - text/thinking block normalization;
  - mature stop-reason mapping;
  - input/output/cache token accounting;
  - terminal empty `end_turn` / `refusal` treated as protocol-terminal rather than malformed transport.
- `agent/kernel/gemini_resource.py`
  - native Gemini `generateContent` rather than the brittle OpenAI-compat endpoint;
  - Gemini model-prefix normalization;
  - native system instruction and generation config;
  - thinking text/signature observation;
  - finish reason plus prompt/output/cached/reasoning token normalization.
- `agent/kernel/cognitive_factory.py`

```text
OpenAI-compatible providers -> OpenAICompatibleCognitiveResource
Anthropic                  -> AnthropicCognitiveResource
Gemini / Google            -> GeminiCognitiveResource
```

- `agent/kernel/config.py` owns resident configuration under ZN home / `ZN_CONFIG_PATH`.
- default runtime construction selects these ZN resources and does not construct the old `AIAgent`.

Still transitional:

- `LegacyAIAgentWorkerFactory` remains only as an explicit compatibility seam for old callers/tests;
- advanced provider-specific tool-turn/replay behavior should be extracted only when ZN's bounded cognition path actually needs it;
- provider dependency installation and credentials UX still need a fully ZN-owned product surface.

## Local terminal / computer body

Status: **local non-PTY resident path extracted; mature interactive/remote slices remain**

Implemented in `agent/kernel/terminal.py`:

- safe cwd recovery;
- per-ZN-context cwd continuity across fresh shell processes;
- POSIX shell selection and Windows Git Bash discovery;
- foreground execution;
- timeout handling;
- POSIX process-group termination and Windows process-tree termination;
- background process handles with poll/stop;
- bounded head/tail output;
- inherited provider/channel credential isolation;
- packaged-Python environment isolation.

`NativeBody._command()` now calls the ZN terminal directly, and body actions can poll/stop ZN terminal background sessions.

Active old-product dependency removed:

```text
NativeBody -> tools.terminal_tool
```

Remaining extraction work is capability-driven, not wholesale copying:

- PTY/interactive execution;
- stdin streaming;
- spill-to-disk for very large output;
- Docker / SSH / cloud backends only when a concrete ZN consumer exists.

The old terminal gateway/session/approval control plane must not be restored to obtain those mechanisms.

## Web search / world sense

Status: **Tavily and Exa extracted; active world-sense path is ZN-owned**

Implemented:

- `agent/kernel/web_resource.py`
  - ZN-owned `WebResource`, `WebSearchItem`, `WebDocument` contracts;
  - Tavily keyed/keyless search + extract;
  - normalized structured results and per-URL extraction failures;
  - ZN-owned config/env selection.
- `agent/kernel/exa_web_resource.py`
  - source-extracted Exa semantic search;
  - mature highlight normalization;
  - batch content extraction;
  - partial-batch omissions become explicit per-URL evidence rather than silent success;
  - no old plugin registry, Hermes env resolver or lazy-dependency control plane.
- `NativeWorldSense._search()` uses the ZN web resource directly.

Active old-product dependency removed:

```text
NativeWorldSense -> tools.web_tools.web_search_tool
```

Remaining extraction work:

- Firecrawl;
- Parallel;
- SearXNG and other useful providers;
- ZN-owned provider availability/failover;
- shared URL/network safety mechanisms worth retaining from mature source;
- browser/content extraction only where resident behavior actually needs it.

## Communication channels

Status: **ZN channel ownership established; Telegram first production transport slice implemented and inbound authorization hardened**

Implemented:

- `agent/kernel/channel.py`
  - `ChannelEvent`;
  - `ChannelMessage`;
  - `ChannelDelivery`;
  - `ChannelAdapter`;
  - `ResidentChannelService` feeds inbound messages into the same resident through `resident.submit()` and routes responses back out.
- `agent/kernel/telegram_channel.py`
  - direct Telegram Bot API transport;
  - long-poll offset handling;
  - message / edited-message / channel-post normalization;
  - thread/reply routing;
  - UTF-16-aware 4096-unit splitting from the mature implementation;
  - token redaction from transport errors;
  - explicit inbound authorization;
  - default inbound policy is deny-all;
  - `allowed_chat_ids` enables selected chats;
  - `allow_all` must be explicit to accept arbitrary chats;
  - denied updates still advance offset so an unauthorized message cannot starve long polling.

Architectural invariant:

```text
Telegram / Discord / Slack / WhatsApp / ...
→ ZN ChannelAdapter
→ ChannelEvent
→ SAME ZN resident
→ Situation / Thought / body / cognition
→ ChannelMessage
→ ZN ChannelAdapter
→ platform
```

A communication channel is an I/O organ, not a separate agent identity.

Still to extract from mature Telegram source:

- pairing/authorization UX beyond static allowlists;
- proxy handling;
- IPv4/DoH fallback for broken Telegram network paths;
- reconnect/watchdog behavior;
- media receive/send;
- voice/audio semantics;
- rich-message formatting/fallback;
- typing/status behavior;
- webhook mode only if the product needs it.

After Telegram reaches the product baseline, Discord/Slack/WhatsApp should be ported as adapters to the same contract rather than by reviving the old gateway.

## Desktop/UI ownership

Status: **not fixed yet; intentionally follows runtime capability ownership**

Current wrong/transitional state still includes:

```text
zn-main.ts -> inherited electron/main.ts
zn-preload.ts -> inherited preload.ts
zn-workbench.tsx -> inherited ContribController
apps/desktop/package.json -> inherited Hermes product metadata
```

Target remains the independent ChatGPT-style ZN workbench in `ZN.md`:

- calm left navigation/history/workspaces;
- central conversation/work surface;
- one clear composer;
- contextual artifact/tool/file/terminal surfaces;
- ZN-owned resident view and settings;
- no inherited Hermes application root.

Do not polish the inherited UI shell as if it were the product. Good generic implementation ideas may be source-extracted into ZN-owned components.

## Packaging/release ownership

Status: **paused as architecture driver**

Useful mechanisms may be retained later: portable Python staging, versioned runtime identity, N -> N+1 resident handoff, ZN stable channel, update integrity checks and multi-OS workflow structure.

The current inherited package shape is not the release target. Multi-OS release CI is opt-in only. Formal packaging resumes only around the independently owned ZN runtime and desktop.

## Immediate next sequence

Unless a new repository fact requires a blueprint correction first:

1. get the latest Anthropic/Gemini/Telegram/Exa extraction commits green under ordinary ZN CI;
2. continue terminal maturity only where the resident needs PTY/stdin/large-output behavior;
3. extract Telegram reconnect/network fallback and media according to actual product need;
4. add Web provider failover and the next useful mature providers;
5. remove remaining active runtime imports from old product control-plane modules;
6. begin independent Electron main/preload and the ChatGPT-style ZN workbench from `ZN.md`;
7. rebuild formal packaging only around that actual ZN product.
