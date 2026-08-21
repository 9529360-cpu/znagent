# ZN implementation status

> Architecture contract: [`../ZN.md`](../ZN.md)
>
> Source-extraction contract: [`ZN-SOURCE-EXTRACTION.md`](ZN-SOURCE-EXTRACTION.md)
>
> This file records **what is actually implemented now**. It is deliberately separate from the forward blueprint so current code state never silently redefines the intended product.

## Current development rule

The development order remains:

```text
ZN.md / extraction contract first
→ inspect mature reference source
→ extract coherent mechanism into ZN ownership
→ switch active ZN caller
→ run real tests
→ update this status ledger
```

Formal packaging is not the current architecture driver. The inherited package path remains transitional until the active runtime/desktop boundaries are independently ZN-owned.

## Source extraction ledger

### External cognitive resources

Status: **first production seam extracted; expansion in progress**

Implemented:

- `agent/kernel/cognitive_resource.py`
  - ZN-owned `CognitiveResource` / `CognitiveIncrement` boundary;
  - direct OpenAI-compatible transport;
  - ZN-owned route/endpoint/credential resolution for OpenAI, OpenRouter, DeepSeek, Groq, Mistral, xAI and local compatible endpoints;
  - bounded context + bounded question request shape;
  - response/usage normalization;
  - no production need to construct old `AIAgent` for this path.
- `agent/kernel/config.py`
  - ZN-owned resident config under ZN home / explicit `ZN_CONFIG_PATH`.
- default `provider_bridge` runtime construction now chooses ZN cognitive resources.

Still transitional:

- `LegacyAIAgentWorkerFactory` remains as an explicit compatibility seam for old tests/callers;
- Anthropic native protocol has not yet been extracted;
- Gemini native protocol has not yet been extracted;
- remaining provider-specific reasoning/tool-request edge cases need selective source extraction.

Next:

1. preserve CI behavior contracts for the new default path;
2. extract Anthropic transport;
3. extract Gemini transport;
4. delete legacy worker from production callers once no active caller needs it.

### Local terminal / computer body

Status: **local non-PTY active resident path extracted; more mature backends remain**

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
  - inherited ZN/provider/channel credential isolation;
  - packaged-Python environment isolation.
- `NativeBody._command()` now calls the ZN terminal directly.
- explicit body actions can poll/stop background ZN terminal sessions.

Active old-product dependency removed:

```text
NativeBody -> tools.terminal_tool
```

Remaining extraction work:

- PTY/interactive execution;
- mature stdin streaming;
- spill-to-disk for very large output;
- Docker backend if/when ZN has a concrete need;
- SSH backend if/when ZN has a concrete need;
- cloud backends only when there is a ZN product requirement.

Do not pull the old terminal gateway/session/approval control plane back in to obtain those features.

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
- provider selection/failover based on ZN config and availability;
- shared URL/network-safety mechanisms that are worth porting;
- browser/content extraction only where the resident actually needs it.

### Communication channels

Status: **ZN channel ownership established; Telegram first slice implemented but not yet a full mature replacement**

Implemented:

- `agent/kernel/channel.py`
  - normalized `ChannelEvent`;
  - normalized `ChannelMessage`;
  - `ChannelDelivery`;
  - `ChannelAdapter` contract;
  - `ResidentChannelService` that feeds inbound communication to the same resident via `resident.submit()` and routes the resident response back out.
- `agent/kernel/telegram_channel.py`
  - direct Telegram Bot API transport;
  - long-poll update offsets;
  - message/channel-post normalization;
  - chat/thread/reply routing;
  - UTF-16-aware 4096-unit message splitting extracted from mature Telegram behavior;
  - token redaction from transport failures;
  - allowed-chat filtering support;
  - ZN-owned channel config loading boundary.

Architectural invariant now represented in code:

```text
Telegram/Discord/Slack/etc.
→ ChannelEvent
→ SAME ZN resident
→ resident cognition/body
→ ChannelMessage
→ platform adapter
```

A channel does not own an agent identity.

Still to extract from the mature Telegram implementation:

- stricter authorization/pairing defaults;
- proxy handling;
- IPv4/DoH fallback transport for broken Telegram network paths;
- reconnect/watchdog behavior;
- media receive/send;
- voice/audio semantics;
- rich-message formatting and robust fallback;
- typing/status behavior;
- webhook mode if needed.

After Telegram reaches the required product baseline, port Discord/Slack/WhatsApp as adapters to the same channel contract rather than copying the old gateway wholesale.

## Desktop/UI ownership

Status: **not fixed yet; explicitly next major product boundary after runtime resource extraction**

Current wrong/transitional state still includes:

```text
zn-main.ts -> inherited electron/main.ts
zn-preload.ts -> inherited preload.ts
zn-workbench.tsx -> inherited ContribController
apps/desktop/package.json -> inherited Hermes product metadata
```

Target remains the independent ChatGPT-style ZN workbench defined in `ZN.md`.

Do not spend product effort polishing the inherited UI shell. Reusable generic implementation patterns/components may be source-extracted later, but the final application root, navigation, work thread, artifact panel, settings and resident view are ZN-owned.

## Packaging/release ownership

Status: **paused as architecture driver**

Useful release mechanisms already written may be retained later:

- portable Python staging concept;
- versioned runtime identity;
- resident N -> N+1 handoff;
- ZN release manifest/stable channel;
- updater hash/size verification;
- multi-OS builder workflow structure.

But the current inherited package shape is not the release target. Multi-OS release CI is opt-in only again so ordinary source extraction does not burn three-platform build cost.

Formal package work resumes after the runtime and desktop active paths are independently ZN-owned.

## Immediate next development sequence

Unless a newly discovered code fact requires updating `ZN.md` first, continue in this order:

1. get the current source-extraction commits green under ordinary ZN CI;
2. finish the local terminal behavior slice needed by resident work (especially PTY/streaming only if the resident actually needs it now);
3. extract the next real external cognition protocols (Anthropic, Gemini);
4. harden and complete the Telegram adapter using the mature reference behavior, then add the next channel through the common contract;
5. extract useful additional web providers/failover;
6. remove any remaining active runtime imports from old product control-plane modules;
7. begin the independent Electron main/preload and new ZN workbench milestone from `ZN.md`;
8. only after those boundaries are owned, rebuild formal packaging around the actual ZN product.
