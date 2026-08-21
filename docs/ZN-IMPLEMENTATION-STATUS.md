# ZN implementation status

> Architecture contract: [`../ZN.md`](../ZN.md)
>
> Source-extraction contract: [`ZN-SOURCE-EXTRACTION.md`](ZN-SOURCE-EXTRACTION.md)
>
> This file records **what is actually implemented now**. `ZN.md` remains the forward product contract; this ledger must be updated after implementation so a later development session never has to infer architecture from scattered code.

## Current development rule

```text
ZN.md / extraction contract first
→ inspect mature reference source
→ extract coherent mechanism into ZN ownership
→ switch active ZN caller
→ run real tests
→ update this status ledger
```

Formal packaging is not the current architecture driver. The inherited package path remains transitional until the active runtime and desktop boundaries are independently ZN-owned.

## Current verification

The source-extraction baseline through commit `998f680` passed ordinary branch CI:

- `ZN Kernel / Python`: success
- `Electron / TypeScript`: success

Later extraction commits are verified by the same ordinary branch CI before they are treated as a stable baseline. Expensive multi-OS release packaging remains opt-in only.

## Source extraction ledger

### External cognitive resources

Status: **OpenAI-compatible, Anthropic native and Gemini native production seams extracted**

Implemented:

- `agent/kernel/cognitive_resource.py`
  - ZN-owned `CognitiveResource` / `CognitiveIncrement` boundary;
  - direct OpenAI-compatible transport;
  - ZN-owned endpoint/credential resolution for OpenAI, OpenRouter, DeepSeek, Groq, Mistral, xAI and local compatible endpoints;
  - bounded context + bounded question request shape;
  - normalized response and token usage;
  - no need to construct the old `AIAgent` on the default path.
- `agent/kernel/anthropic_resource.py`
  - native Anthropic Messages API resource;
  - native system/user request shape;
  - text/thinking content-block normalization;
  - mature stop-reason mapping;
  - input/output/cache token accounting;
  - empty terminal `end_turn` / `refusal` recognized as protocol-terminal rather than malformed transport.
- `agent/kernel/gemini_resource.py`
  - native Gemini `generateContent` transport rather than Google's OpenAI-compat endpoint;
  - Gemini model-prefix normalization;
  - native system instruction and generation config;
  - thinking text/signature observation;
  - finish-reason and usage/cached/reasoning token normalization.
- `agent/kernel/cognitive_factory.py`
  - ZN-owned protocol dispatch:

```text
OpenAI-compatible providers -> OpenAICompatibleCognitiveResource
Anthropic                  -> AnthropicCognitiveResource
Gemini / Google            -> GeminiCognitiveResource
```

- `agent/kernel/config.py`
  - ZN-owned resident config under ZN home / explicit `ZN_CONFIG_PATH`.
- default `provider_bridge` runtime construction now selects ZN cognitive resources.

Still transitional / next extraction work:

- `LegacyAIAgentWorkerFactory` remains only as an explicit compatibility seam for old tests/callers;
- provider-specific advanced tool-turn/replay behavior should be extracted only when ZN's bounded cognition path actually needs it;
- additional native providers may be ported as concrete ZN requirements appear;
- production provider dependency installation/config UX still needs to become fully ZN-owned.

### Local terminal / computer body

Status: **local non-PTY active resident path extracted; mature interactive/remote slices remain**

Implemented:

- `agent/kernel/terminal.py`
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
- `NativeBody._command()` now calls the ZN terminal directly.
- body actions can poll/stop ZN terminal background sessions.

Active old-product dependency removed:

```text
NativeBody -> tools.terminal_tool
```

Remaining extraction work:

- PTY/interactive execution;
- mature stdin streaming;
- spill-to-disk for very large output;
- Docker backend only when ZN has a concrete consumer;
- SSH backend only when ZN has a concrete consumer;
- cloud execution backends only when there is a ZN product requirement.

Do not restore the old terminal gateway/session/approval control plane to obtain those features. Extract the relevant mechanisms behind the ZN terminal interface.

### Web search / world sense

Status: **first provider and active world-sense path extracted**

Implemented:

- `agent/kernel/web_resource.py`
  - ZN-owned `WebResource` boundary;
  - Tavily search + extract;
  - keyed and keyless request modes;
  - normalized structured results;
  - per-URL extraction failures;
  - ZN-owned config/env resolution;
  - no old web registry/config import.
- `NativeWorldSense._search()` now uses the ZN web resource directly.

Active old-product dependency removed:

```text
NativeWorldSense -> tools.web_tools.web_search_tool
```

Remaining extraction work:

- Exa provider;
- Firecrawl provider;
- Parallel provider;
- SearXNG / other useful providers;
- ZN-owned provider selection/failover;
- shared URL/network-safety mechanisms worth retaining from the mature source;
- browser/content extraction only where resident behavior actually requires it.

### Communication channels

Status: **ZN channel ownership established; Telegram first transport slice implemented**

Implemented:

- `agent/kernel/channel.py`
  - normalized `ChannelEvent`;
  - normalized `ChannelMessage`;
  - `ChannelDelivery`;
  - `ChannelAdapter` contract;
  - `ResidentChannelService` feeds inbound communication to the same resident via `resident.submit()` and routes the resident response back out.
- `agent/kernel/telegram_channel.py`
  - direct Telegram Bot API transport;
  - long-poll update offsets;
  - message / edited-message / channel-post normalization;
  - chat/thread/reply routing;
  - UTF-16-aware 4096-unit splitting extracted from the mature Telegram behavior;
  - token redaction from transport errors;
  - allowed-chat filtering;
  - ZN-owned channel config boundary.

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

A communication channel is an I/O organ. It does not own a separate agent identity.

Still to extract from mature Telegram source:

- stricter authorization/pairing defaults before enabling the channel by default;
- proxy handling;
- IPv4/DoH fallback for broken Telegram network paths;
- reconnect/watchdog behavior;
- media receive/send;
- voice/audio semantics;
- rich-message formatting and fallback;
- typing/status behavior;
- webhook mode only if the product needs it.

After Telegram reaches the required product baseline, Discord/Slack/WhatsApp should be ported as adapters to the same channel contract rather than by reviving the old gateway.

## Desktop/UI ownership

Status: **not fixed yet; intentionally follows runtime capability ownership**

Current wrong/transitional state still includes:

```text
zn-main.ts -> inherited electron/main.ts
zn-preload.ts -> inherited preload.ts
zn-workbench.tsx -> inherited ContribController
apps/desktop/package.json -> inherited Hermes product metadata
```

Target remains the independent ChatGPT-style ZN workbench defined in `ZN.md`:

- calm left navigation/history/workspaces;
- central conversation/work surface;
- one clear composer;
- contextual artifact/tool/file/terminal surfaces;
- resident view and settings owned by ZN;
- no inherited Hermes application root.

Do not polish the inherited UI shell as if it were the product. Reusable implementation patterns may be source-extracted later into ZN-owned components.

## Packaging/release ownership

Status: **paused as architecture driver**

Useful release mechanisms may be retained later:

- portable Python staging concept;
- versioned runtime identity;
- resident N -> N+1 handoff;
- ZN release manifest/stable channel;
- updater size/hash verification;
- multi-OS workflow structure.

But the current inherited package shape is not the release target. Multi-OS release CI is opt-in only so source extraction does not burn three-platform build cost.

Formal packaging resumes only after the active runtime and desktop are independently ZN-owned.

## Immediate next development sequence

Unless new repository facts require a blueprint correction first:

1. verify the latest Anthropic/Gemini source extraction under ordinary ZN CI;
2. harden the local terminal seam where resident behavior proves a need, especially PTY/stdin/large-output handling rather than blindly copying all backends;
3. harden Telegram from the mature source: authorization first, then reconnect/network fallback and media according to product need;
4. port additional Web providers and ZN-owned failover;
5. remove remaining active runtime imports from old product control-plane modules;
6. start the independent Electron main/preload and ChatGPT-style ZN workbench milestone from `ZN.md`;
7. rebuild formal packaging only around that actual ZN product.
