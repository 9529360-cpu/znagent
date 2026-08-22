# ZN implementation status

> Architecture contract: [`../ZN.md`](../ZN.md)
>
> Source-extraction contract: [`ZN-SOURCE-EXTRACTION.md`](ZN-SOURCE-EXTRACTION.md)
>
> This file records **what is actually implemented now**. Code remains authoritative over this ledger.

## Verified implementation baseline

Latest source implementation baseline verified before this documentation-only update:

```text
82cc401172fab0cff6cf2a6d79c07ed38924f99f
```

Normal ZN CI:

```text
ZN Kernel / Python      success
Electron / TypeScript  success
Actions run             32569950134
```

This baseline includes the independently installable ZN Python runtime distribution, final `zn-resident` entrypoint, isolated zero-model boot, removal of the legacy AIAgent worker seam, completed PTY-session reclamation, deterministic external-event ingress, durable channel routing/checkpoints, Telegram inbound media, ZN-owned outbound-media path authorization, and the ZN-owned multi-provider Web path.

The immediately preceding PTY cleanup baseline was also verified at `9ce663667ec3ba0013d41793199dd9a5c0076dcb` / Actions run `32569795951`. Earlier broad extraction baselines include `2849e4d46e1e0ea5d1f9c414e7adac9b38c95d37` / Actions run `32566761653`, `7fa92de864ed47a145a9afba033f08fea00b274d` / Actions run `32566228134`, and `bd15481db2cd80547d9fdd81386c6770a80b23bf` / Actions run `32565873478`.

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

Formal installer polishing is not the current architecture driver. Useful release mechanisms stay available for later, but runtime/product ownership comes first.

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
- the legacy `LegacyAIAgentWorkerFactory` / `run_agent.AIAgent` fallback has been removed from the ZN kernel runtime.

Remaining cognition extraction is demand-driven:

- provider-specific external tool-turn replay and uncommon reasoning edge cases should be source-extracted only when ZN has a concrete use;
- do not reconstruct a full-agent provider loop inside the resource layer.

### Local terminal / computer body

Status: **active local body extracted, including real interactive PTY sessions and completed-session reclamation**

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
  - terminal resize;
  - a PTY that completes immediately before or during `write_stdin()` / `resize()` is routed through the same final poll path, preserving exit/output evidence and reclaiming the session immediately.
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

Status: **resident-owned communication lifecycle with idempotent ingress, durable routing/checkpoints, Telegram inbound media and outbound path authorization active**

Core contract:

- `agent/kernel/channel.py`
  - normalized `ChannelEvent`;
  - normalized `ChannelMessage`;
  - normalized `ChannelAttachment`;
  - `ChannelDelivery`;
  - `ChannelAdapter` contract.
- `agent/kernel/event_ingress.py`
  - deterministic external resident event IDs derived from namespace + stable source key;
  - idempotent enqueue for replayed external percepts;
  - an already-existing resident event is never replaced or re-queued;
  - closes the crash window where an event can reach the resident queue before its channel route is persisted, without creating a second task store.
- `agent/kernel/outbound_media.py`
  - ZN-owned local-file authorization boundary before any channel upload;
  - default authorized roots are ZN `artifacts/` and `channels/outbound/`;
  - candidates and roots are realpath-resolved before containment checks;
  - relative paths, missing paths, directories, empty files and symlink escapes are rejected;
  - optional size cap is available without baking a specific platform limit into the generic policy;
  - extra export roots require explicit policy construction rather than implicit host-filesystem access.

Resident lifecycle:

- `agent/kernel/channel_runtime.py`
  - channel adapters live with `ResidentSocketService`, not with an Electron window;
  - each transport gets an isolated polling/reconnect thread;
  - channel transport failures use bounded exponential backoff;
  - **channel threads do not drive cognition**;
  - inbound percepts enter the resident durable event queue through idempotent external ingress;
  - cognition remains owned by the resident life loop;
  - completed results are observed through `resident.result_for()` and routed outward;
  - replayed percepts with the same stable source key resolve to the same resident event identity.
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
  - supervisor persists it only after all percepts from that poll have reached durable resident ingress/routing.

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
→ deterministic durable resident event ingress
→ SAME ZN resident life loop
→ durable outcome
→ channel delivery ledger
→ platform adapter
```

A channel does not own an agent identity or cognition loop.

Remaining communication work:

- local-file sending must consume `OutboundMediaPathPolicy`; no adapter may upload an arbitrary path directly;
- add Telegram outbound attachments/media only when the resident has an explicit outbound artifact/message path to feed that contract;
- rich formatting/status/typing should be extracted only where product value justifies them;
- add Discord/Slack/other adapters behind the same durable contract rather than copying the old gateway wholesale.

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

## Python/runtime package ownership

Status: **M1 distribution/runtime ownership complete for the active packaged resident path**

Implemented:

- `runtime/python/pyproject.toml`
  - independent `znagent` distribution identity;
  - `zn-resident = "zn_agent.resident:main"` console entrypoint;
  - only ZN runtime dependencies are declared;
  - the packaged `zn_agent.core` namespace is built from the ZN resident-kernel source boundary without packaging the old CLI/gateway product.
- `runtime/python/zn_agent/resident.py`
  - final ZN resident entrypoint.
- `apps/desktop/scripts/stage-zn-runtime.mjs`
  - installs `runtime/python`, not the inherited repository-root distribution;
  - smoke-imports/boots `zn_agent` only;
  - rejects an installed `hermes_cli` package in the staged runtime.
- `apps/desktop/electron/zn-packaged-runtime.ts` and release verification
  - packaged-runtime validity requires ZN entrypoints rather than `hermes_cli/main.py`;
  - packaged payloads containing the inherited CLI are rejected.
- `apps/desktop/electron/zn-resident-process.ts`
  - detached resident launch uses `python -m zn_agent.resident`.
- normal Python CI
  - creates a fresh isolated venv;
  - installs only `runtime/python` into it;
  - imports `zn_agent.resident` and performs a zero-model resident pulse with no repository-root package dependency.
- `agent/kernel/worker.py` / runtime construction
  - the `run_agent.AIAgent` compatibility worker has been removed.

The repository root still contains inherited/reference product source and metadata because that tree remains a source quarry during extraction. It is not the active packaged ZN runtime distribution and must not become one again.

This completes the M1 ownership seam without requiring a mass physical rename of every `agent/kernel/` source file; `ZN.md` explicitly places product-level dependency removal ahead of cosmetic namespace migration.

## Packaging/release ownership

Status: **paused as architecture driver**

Useful release mechanisms already written can be retained later:

- portable Python staging;
- versioned runtime identity;
- resident N -> N+1 handoff;
- ZN release manifest/stable channel;
- updater hash/size verification;
- multi-OS builder workflow structure.

The inherited package shape is not the release target. Formal installer work resumes after the active Python runtime and desktop paths are independently ZN-owned.

## Immediate next development sequence

Unless a newly discovered code fact requires changing the architecture contract first:

1. audit and remove remaining active old-product runtime/control-plane seams that block desktop independence, without reintroducing Hermes as a runtime dependency;
2. begin M4 by replacing `zn-main.ts -> inherited electron/main.ts` with an independent ZN Electron main process that owns ZN packaged-runtime activation, resident connection and window lifecycle;
3. replace the inherited preload with a ZN-owned preload/API boundary;
4. build the M5 content-first ZN workbench on that independent desktop foundation rather than polishing the inherited `ContribController` shell;
5. wire Telegram outbound attachments only through the ZN outbound-media authorization contract when the resident exposes a concrete outbound artifact/message flow;
6. rebuild formal packaging only around the actual ZN-owned runtime + desktop product.

The next architecture driver is desktop/control-plane ownership, not installer polish and not another compatibility wrapper around inherited Electron code.
