# ZN implementation status

> Architecture contract: [`../ZN.md`](../ZN.md)
>
> Source-extraction contract: [`ZN-SOURCE-EXTRACTION.md`](ZN-SOURCE-EXTRACTION.md)
>
> This file records **what is actually implemented now**. Code remains authoritative over this ledger.

## Verified implementation baseline

Latest source implementation baseline verified before this documentation-only update:

```text
7fa92de864ed47a145a9afba033f08fea00b274d
```

Normal ZN CI:

```text
ZN Kernel / Python      success
Electron / TypeScript  success
Actions run             32566228134
```

The preceding broad extraction batch was also verified at `bd15481db2cd80547d9fdd81386c6770a80b23bf` / Actions run `32565873478`.

## Current development rule

The active development order is:

```text
inspect mature reference source
→ isolate the coherent mechanism
→ implement a ZN-owned boundary
→ switch the active resident caller
→ verify real behavior
→ record remaining migration debt
```

Hermes/reference code is a source mine, not ZN's runtime dependency graph or product control plane.

Formal packaging is not the current architecture driver. Useful release mechanisms stay available for later, but product/runtime ownership comes first.

## Source extraction ledger

### External cognitive resources

Status: **native ZN resource layer active; main protocol families extracted**

Implemented:

- `agent/kernel/cognitive_resource.py`
  - ZN-owned `CognitiveResource` / `CognitiveIncrement` boundary;
  - direct OpenAI-compatible transport;
  - ZN-owned route/endpoint/credential resolution for OpenAI, OpenRouter, DeepSeek, Groq, Mistral, xAI and local compatible endpoints;
  - bounded context + bounded question request shape;
  - response/usage normalization.
- `agent/kernel/anthropic_resource.py`
  - native Anthropic Messages API;
  - content-block normalization;
  - thinking/text handling;
  - stop-reason mapping;
  - cache/input/output token accounting.
- `agent/kernel/gemini_resource.py`
  - native Gemini `generateContent` path;
  - native thinking/thought-signature semantics where relevant;
  - finish-reason and token-usage normalization.
- `agent/kernel/config.py`
  - ZN-owned resident/resource configuration.
- default resident runtime construction chooses ZN cognitive resources and does not need the old `AIAgent`.

Still transitional:

- `LegacyAIAgentWorkerFactory` remains only as an explicit compatibility seam for old tests/callers;
- provider-specific external tool-turn replay and uncommon reasoning edge cases should be source-extracted only when ZN has a concrete use;
- remove the legacy worker entirely once no active compatibility caller remains.

### Local terminal / computer body

Status: **active local body extracted, including real interactive PTY sessions**

Implemented:

- `agent/kernel/terminal.py`
  - safe cwd recovery;
  - per-ZN-context cwd continuity;
  - POSIX shell selection and Windows Git Bash discovery;
  - foreground/background command execution;
  - timeout handling;
  - POSIX process-group and Windows process-tree cleanup;
  - bounded output;
  - inherited credential/runtime-environment isolation;
  - interactive PTY session lifecycle;
  - session poll/stop;
  - stdin writes;
  - terminal resize.
- `agent/kernel/pty.py`
  - POSIX `ptyprocess` bridge;
  - Windows `pywinpty` / ConPTY bridge;
  - byte-safe PTY I/O;
  - winsize bounds;
  - TERM setup;
  - exit-code and process-group cleanup.
- `NativeBody`
  - command execution routes directly through ZN terminal;
  - `terminal_input` / `terminal_resize` / poll / stop are body actions.
- real POSIX PTY smoke tests exercise the locked dependency, not only fake objects.

Active old-product dependency removed:

```text
NativeBody -> tools.terminal_tool
```

Remaining terminal work:

- close the small PTY lifecycle edge where `write_stdin()` can observe a just-completed child before the next poll reclaims the session;
- spill-to-disk semantics for very large interactive streams if resident workloads require it;
- Docker/SSH backends only when ZN has a concrete resident-body use;
- cloud execution only when a ZN product requirement exists.

Do not restore the old gateway/session/approval control plane to obtain those features.

### Web search / world sense

Status: **multiple ZN-owned providers, failover and network safety active**

Implemented:

- `agent/kernel/web_resource.py`
  - ZN-owned `WebResource` boundary;
  - Tavily search + extract;
  - explicit provider pinning;
  - explicit `auto` / `failover` chain;
  - search failover only on provider/transport failure;
  - empty search results remain valid reality evidence;
  - per-URL extraction failover;
  - successful extraction is not repeated on the next provider;
  - final failures remain explicit evidence.
- `agent/kernel/exa_web_resource.py`
  - Exa SDK search/extract;
  - highlight normalization;
  - batch extraction and per-URL failure behavior.
- `agent/kernel/firecrawl_web_resource.py`
  - direct Firecrawl REST search/scrape;
  - keyed/keyless operation;
  - markdown/html normalization;
  - requested URL and redirected final URL are both preserved;
  - final redirect target is safety-checked before content is admitted.
- `agent/kernel/url_safety.py`
  - HTTP(S)-only network target boundary;
  - cloud metadata endpoint floor;
  - private/loopback/link-local/reserved/multicast/CGNAT blocking;
  - IPv4-mapped IPv6 handling;
  - fail-closed DNS semantics with proxy-side resolution exception;
  - ZN-owned `security.allow_private_urls` / `ZN_ALLOW_PRIVATE_URLS` opt-out without weakening metadata protection.
- `NativeWorldSense._search()` routes through the ZN Web resource layer.

Active old-product dependency removed:

```text
NativeWorldSense -> tools.web_tools.web_search_tool
```

Deferred deliberately:

- Parallel's mature extraction path is async while the current resident Web organ contract is synchronous; do not hide that mismatch with `asyncio.run()` just to increase provider count;
- add more providers only when they improve resident availability/capability materially;
- browser automation/content rendering should remain a separate concrete body/sense requirement rather than being smuggled into search.

### Communication channels

Status: **resident-owned communication lifecycle, durable routing and Telegram inbound media active**

Core contract:

- `agent/kernel/channel.py`
  - normalized `ChannelEvent`;
  - normalized `ChannelMessage`;
  - normalized `ChannelAttachment`;
  - `ChannelDelivery`;
  - `ChannelAdapter` contract.

Resident lifecycle:

- `agent/kernel/channel_runtime.py`
  - channel adapters live with `ResidentSocketService`, not with an Electron window;
  - each transport gets an isolated polling/reconnect thread;
  - channel transport failures use bounded exponential backoff;
  - **channel threads do not drive cognition**;
  - inbound percepts call `resident.enqueue()` only;
  - cognition remains owned by the resident life loop;
  - completed results are observed through `resident.result_for()` and routed outward.
- `agent/kernel/channel_delivery.py`
  - durable `channel source percept -> resident event -> conversation/thread` routing ledger;
  - pending outcomes survive resident process restart;
  - successful deliveries are marked durably;
  - send failures remain pending for retry;
  - stable source keys deduplicate replayed updates;
  - adapter poll checkpoints are persisted separately from cognition state.
- `agent/kernel/telegram_resident_channel.py`
  - Telegram long-poll offset checkpoint/restore seam;
  - offset only moves forward;
  - supervisor persists it only after all percepts from that poll have reached the durable route ledger.

Telegram transport:

- `agent/kernel/telegram_channel.py`
  - direct Telegram Bot API transport;
  - long-poll update normalization;
  - thread/reply routing;
  - UTF-16-aware message splitting;
  - default deny-all inbound authorization;
  - explicit `allowed_chat_ids` or `allow_all` opening;
  - token-safe transport errors;
  - normalized inbound photos/documents/audio/voice/video/video-note/animation/sticker attachments;
  - attachment-only messages become resident percepts;
  - captions remain primary text;
  - ZN-owned attachment cache;
  - declared-size and streaming-size bounds;
  - per-attachment failure evidence instead of dropping the whole message.
- `agent/kernel/telegram_network.py`
  - IPv4-first Telegram fallback paths;
  - hostname/TLS SNI preservation;
  - sticky healthy route;
  - failed pool replacement;
  - bounded connection pools;
  - proxy + `NO_PROXY` host/IP/CIDR behavior;
  - optional Google/Cloudflare DoH A-record discovery.

Current communication invariant:

```text
Telegram / future Discord / future Slack / ...
→ ChannelEvent
→ durable resident event queue
→ SAME ZN resident life loop
→ durable outcome
→ channel delivery ledger
→ platform adapter
```

A channel does not own an agent identity or cognition loop.

Remaining communication work:

- remove the very small crash window between `resident.enqueue()` and insertion of the matching channel route, ideally by reserving a deterministic resident event id or making the enqueue/route write atomic;
- extract a ZN-owned outbound media path authorization policy before allowing local-file uploads;
- then add Telegram outbound attachments/media, rich formatting/status/typing only where product value justifies them;
- add Discord/Slack/other adapters behind the same contract rather than copying the old gateway wholesale.

### Desktop/UI ownership

Status: **still transitional and intentionally not hidden**

Current inherited/product-debt examples still include:

```text
zn-main.ts -> inherited electron/main.ts
zn-preload.ts -> inherited preload.ts
zn-workbench.tsx -> inherited ContribController
apps/desktop/package.json -> inherited Hermes product metadata
```

Target remains the independent ZN workbench defined in `ZN.md`.

Do not spend product effort polishing the inherited shell. Reusable generic implementation may be source-extracted, but the final app root, navigation, work thread, artifact panel, settings and resident view must be ZN-owned.

## Packaging/release ownership

Status: **paused as architecture driver**

Useful release mechanisms already written can be retained later:

- portable Python staging;
- versioned runtime identity;
- resident N -> N+1 handoff;
- ZN release manifest/stable channel;
- updater hash/size verification;
- multi-OS builder workflow structure.

The inherited package shape is not the release target. Formal package work resumes after the active runtime and desktop paths are independently ZN-owned.

## Immediate next development sequence

Unless a newly discovered code fact requires changing the architecture contract first:

1. close the channel enqueue -> route atomicity gap without creating a second task store;
2. close the remaining PTY completed-session cleanup edge;
3. extract ZN-owned outbound media path authorization before Telegram file sending;
4. finish only the Telegram rich/status/media behaviors the resident actually needs;
5. add the next communication platform through the common durable channel contract;
6. remove remaining active old-product control-plane dependencies as they are encountered;
7. begin the independent Electron main/preload/workbench ownership milestone;
8. only after those boundaries are owned, rebuild formal packaging around the actual ZN product.
