# ZN mature-source extraction plan

> Governing blueprint: [`../ZN.md`](../ZN.md)
>
> This document is the implementation contract for adopting mature capability code from the inherited/reference tree. It exists to prevent a recurring failure mode: packaging or calling an old product subsystem wholesale when ZN only needs the engineering mechanisms inside it.
>
> Current checkpoint: 2026-08-22. The active development branch is `dev/zn-agent`.

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
need desktop → start inherited Electron main/preload/renderer behind a ZN wrapper
need release → package the old Python product under a ZN installer
```

Packaging is downstream validation. It is not the architecture and it must not be used to hide product-level dependencies.

## 2. Extraction standard

A capability is considered ZN-owned only when all of the following are true:

1. The production import begins in a ZN-owned boundary.
2. Its public interface is defined by ZN.
3. ZN configuration and credential resolution own its runtime choices.
4. ZN state/session/identity objects own continuity.
5. The extracted code can be tested without starting the old CLI/agent/gateway/desktop.
6. The capability can be packaged without requiring old product entrypoints.
7. Old source may remain beside it as reference, but the active ZN call path does not cross back into the old product control plane.

Copying mature implementation is allowed and often preferred. Cosmetic rewrites are not a goal. The extraction must remove product coupling, not historical ancestry.

The current physical source layout under `agent/kernel/` is allowed during migration. `runtime/python/pyproject.toml` maps that ZN-owned kernel source into the installed `zn_agent.core` namespace. `ZN.md` deliberately places ownership-seam removal ahead of a mass namespace rename.

## 3. Current extraction checkpoint

The main resident/runtime seams that originally crossed into the inherited product have now been cut.

### 3.1 External cognitive/model resources

Status: **ZN-native production path active**.

Implemented ZN-owned mechanisms include:

- `agent/kernel/cognitive_resource.py`
  - bounded `CognitiveResource` / `CognitiveIncrement` contract;
  - direct OpenAI-compatible transport;
  - ZN-owned route, endpoint and credential resolution for compatible providers;
  - bounded context/question request shape and normalized usage/result handling.
- `agent/kernel/anthropic_resource.py`
  - native Anthropic Messages API behavior;
  - content/thinking normalization and token accounting.
- `agent/kernel/gemini_resource.py`
  - native Gemini `generateContent` behavior;
  - thinking/thought-signature and usage normalization where relevant.
- `agent/kernel/cognitive_factory.py`
  - provider/resource selection owned by ZN.
- `agent/kernel/provider_bridge.py`
  - resident construction from ZN config and ZN cognitive resources only.
- `agent/kernel/config.py`
  - ZN-owned configuration loading.
- `agent/kernel/worker.py`
  - only the generic worker contract plus zero-model `UnavailableModelWorkerFactory` remain.

The production kernel no longer constructs `run_agent.AIAgent`, and the old `LegacyAIAgentWorkerFactory` seam has been removed.

Ownership regression protection:

- `tests/agent/kernel/test_runtime_ownership.py` AST-scans the active kernel for forbidden `hermes_cli` / `run_agent` imports;
- normal CI installs the independent runtime distribution in a fresh venv and performs a zero-model pulse through `zn_agent`.

Remaining cognition extraction is demand-driven:

- provider-specific external tool-turn replay;
- uncommon reasoning/token edge cases;
- additional providers only when they materially improve resident capability or availability.

Do not reconstruct a prompt-owning full-agent loop inside the resource layer.

### 3.2 Local terminal / computer body

Status: **ZN-native local terminal and PTY path active**.

The mature reference terminal stack remains useful source material, but the active resident body no longer delegates terminal work to inherited `tools.terminal_tool`.

Implemented in `agent/kernel/terminal.py` and `agent/kernel/pty.py`:

- safe cwd resolution and per-ZN-context cwd continuity;
- POSIX shell selection and Windows Git Bash discovery;
- foreground/background local execution;
- timeout and process-tree/process-group cleanup;
- bounded output;
- inherited credential/runtime-environment isolation;
- POSIX `ptyprocess` and Windows `pywinpty`/ConPTY bridges;
- interactive session start/poll/stop;
- stdin writes and terminal resize;
- exit-code/cwd evidence preservation;
- completed-session reclamation even when a PTY exits immediately before or during `write_stdin()` / `resize()`.

`NativeBody` routes command/terminal actions through this ZN-owned terminal service.

Remaining terminal work is demand-driven:

- spill-to-disk semantics for very large interactive streams if required;
- Docker/SSH/cloud backends only for concrete ZN body requirements.

Do not restore the old gateway/session/approval control plane to obtain optional backends.

### 3.3 Web search / world sense

Status: **ZN-native production path active**.

Implemented:

- `agent/kernel/web_resource.py`
  - ZN-owned web resource contract;
  - Tavily search/extract;
  - explicit provider pinning and `auto`/failover behavior;
  - structured failure evidence.
- `agent/kernel/exa_web_resource.py`
  - Exa search/extract normalization.
- `agent/kernel/firecrawl_web_resource.py`
  - direct Firecrawl search/scrape path.
- `agent/kernel/url_safety.py`
  - HTTP(S)-only target boundary;
  - metadata/private/loopback/link-local/reserved/multicast/CGNAT protections;
  - fail-closed DNS semantics with explicit controlled exceptions.
- `NativeWorldSense._search()` routes through the ZN web resource layer.

The active old-product dependency `NativeWorldSense -> tools.web_tools.web_search_tool` has been removed.

Deferred deliberately:

- async-only providers such as the mature Parallel extraction path should not be hidden behind ad-hoc `asyncio.run()` in the synchronous resident organ contract;
- browser automation/rendering is a separate body/sense requirement, not a search-provider shortcut.

### 3.4 Communication channels

Status: **resident-owned channel lifecycle active; Telegram is the first extracted transport**.

Core ZN contracts and lifecycle:

- `agent/kernel/channel.py`
  - `ChannelEvent`, `ChannelMessage`, `ChannelAttachment`, `ChannelDelivery`, `ChannelAdapter`.
- `agent/kernel/event_ingress.py`
  - deterministic external event IDs and idempotent durable ingress.
- `agent/kernel/channel_runtime.py`
  - channel adapters live with the long-lived resident service;
  - transport threads never own cognition;
  - inbound percepts enter the same resident event queue;
  - completed resident outcomes are routed back outward.
- `agent/kernel/channel_delivery.py`
  - durable source-percept → resident-event → conversation/thread routing;
  - restart-safe pending delivery and retry state;
  - transport checkpoints separate from cognition state.
- `agent/kernel/telegram_resident_channel.py`
  - Telegram poll checkpoint/restore seam.
- `agent/kernel/telegram_channel.py`
  - direct Telegram Bot API transport;
  - authorization, long polling, reply/thread routing and UTF-16-aware splitting;
  - normalized inbound media and bounded attachment cache.
- `agent/kernel/telegram_network.py`
  - network fallback/pool/proxy handling extracted for the Telegram transport.

Current invariant:

```text
Telegram / future Discord / future Slack / ...
→ ChannelEvent
→ deterministic durable resident ingress
→ SAME ZN resident life loop
→ durable outcome
→ channel delivery ledger
→ selected platform adapter
```

Outbound local-file security is now separated from transport:

- `agent/kernel/outbound_media.py` defines `OutboundMediaPathPolicy`;
- default roots are ZN `artifacts/` and `channels/outbound/`;
- candidates and roots are realpath-resolved;
- relative paths, missing files, directories, empty files and symlink escapes are rejected;
- adapters must not interpret an arbitrary host path as permission to upload it.

Still pending for media egress:

- Telegram outbound attachment/media transport must consume `OutboundMediaPathPolicy` before local-file upload;
- wire it only when the resident exposes an explicit outbound artifact/message flow;
- add more channels behind the same resident contract rather than copying the old gateway wholesale.

## 4. Independent desktop extraction

Status: **M4 ownership seam complete; M5 workbench foundation active**.

The earlier transitional shape has been removed from the active ZN desktop path:

```text
zn-main.ts -> inherited electron/main.ts          removed
zn-preload.ts -> inherited preload.ts             removed
active renderer -> inherited ContribController    removed
```

Current ZN-owned desktop control plane:

- `apps/desktop/electron/zn-main.ts`
  - owns `BrowserWindow` creation;
  - owns single-instance behavior;
  - activates the packaged ZN runtime;
  - registers ZN resident/update IPC;
  - owns navigation policy and window lifecycle;
  - registers `zn://` with the OS.
- `apps/desktop/electron/zn-preload.ts`
  - exposes only the intentional `window.znDesktop` bridge.
- `apps/desktop/electron/zn-protocol.ts`
  - parses only `zn:` deep links;
  - bounds link size;
  - normalizes and deduplicates argv links.
- `apps/desktop/electron/zn-shell.html`
  - minimal CSP-bound ZN renderer document.
- `apps/desktop/src/zn/main.tsx`
  - independent React renderer root.
- `apps/desktop/src/zn/workbench.tsx`
  - content-first workbench with New work, recent/search, workspace placeholder, conversation/thread surface, composer, resident health/context, settings and update controls.
- `apps/desktop/src/zn/state.ts`
  - bounded browser-side thread convenience cache only; resident identity/memory never depends on it.
- `apps/desktop/src/zn/resident-client.ts`
  - direct ZN preload/IPC client for resident task submission/status and updates.
- `apps/desktop/scripts/bundle-electron-main.mjs`
  - bundles only ZN main, ZN preload and the active ZN renderer entries.

Ownership tests in `apps/desktop/electron/zn-desktop-ownership.test.ts` lock the boundary:

- main must create the ZN window and may not import inherited main;
- preload may expose only ZN bridge behavior and may not import inherited preload;
- active renderer may not import/render `ContribController` or inherited shell roots;
- deep links reject web and `hermes://` schemes as ZN navigation data;
- bundle entries are ZN-only.

The workbench is functional but not M5/M6 complete. Remaining product work includes:

- real workspace/folder association;
- durable resident-backed work/thread identity instead of relying on renderer cache for UI history;
- provider/credential editor connected to ZN config/secure storage;
- contextual artifacts/files/diffs;
- invoked terminal/browser surfaces;
- richer resident activity/progress streaming;
- final product assets/visual polish/accessibility.

## 5. Python/runtime packaging extraction

Status: **M1 active packaged resident path is ZN-owned**.

Implemented:

- `runtime/python/pyproject.toml`
  - independent `znagent` distribution;
  - `zn-resident = "zn_agent.resident:main"`;
  - ZN runtime dependencies only.
- `runtime/python/zn_agent/resident.py`
  - ZN resident package entrypoint.
- `apps/desktop/scripts/stage-zn-runtime.mjs`
  - installs `runtime/python`, not the inherited repository-root distribution;
  - validates only `zn_agent` resident/core files;
  - rejects `hermes_cli` in the staged runtime;
  - performs an isolated zero-model pulse.
- `apps/desktop/electron/zn-packaged-runtime.ts`
  - validates/materializes versioned ZN runtime payloads;
  - rejects inherited `hermes_cli` payloads;
  - sets ZN-owned runtime environment variables.
- `apps/desktop/electron/zn-resident-process.ts`
  - launches `python -m zn_agent.resident`.

Repository-root inherited source/metadata still exists as source quarry. It is not the active packaged resident distribution.

## 6. What remains inherited and why it is still debt

The active resident runtime and active desktop control plane are now independent, but the repository is not yet a fully migrated ZN product.

Known remaining product/release debt includes:

- root repository distribution metadata/reference source remains inherited;
- `apps/desktop/package.json` still identifies the package/product/repository as Hermes and still contains inherited scripts/dependencies;
- the package-level default Electron builder metadata still identifies Hermes;
- `apps/desktop/electron-builder.zn.yml` is ZN-branded but still registers both `zn` and `hermes` schemes;
- inactive inherited Electron/renderer/gateway/source trees remain in the repository as reference material;
- formal self-contained installer/clean-machine validation has not yet been rebuilt around the now-independent ZN desktop + runtime boundary.

These are migration/release debts, not permission to route active ZN code back through the inherited product.

## 7. What not to extract

Do not blindly migrate:

- old product branding and paths;
- old CLI UX merely because a capability is configured there;
- old full-agent orchestration/prompt ownership;
- old desktop shell/UI;
- old gateway identity/session model when ZN resident already owns identity/continuity;
- vendor/subscription code that ZN does not use;
- every optional backend at once;
- compatibility shims whose only consumer is the old product;
- tests that only freeze old naming/snapshots rather than useful behavior.

The reference implementation is a quarry, not a dependency graph that must be preserved.

## 8. Extraction ledger

```text
E0  document extraction boundary                              DONE
E1  establish ZN-native resource/channel/body interfaces      DONE
E2  extract main external model transports/providers          DONE for active provider families
E3  extract local terminal body/PTTY lifecycle                DONE
E4  extract web search/extract providers + URL safety         DONE for active provider set
E5  extract communication framework + first channel           DONE for Telegram text/inbound media; outbound media transport pending
E6  switch resident production callers to ZN-owned modules    DONE for cognition/terminal/web/channel lifecycle
E7  build independent ZN Electron main/preload/UI foundation  DONE
E8  remove active old-product control-plane imports           DONE for active resident + desktop; packaging metadata debt remains
E9  package independently bootable ZN product                 NEXT release-ownership milestone
E10 verify clean-machine install/upgrade/multi-OS release      NOT STARTED as product gate
```

This ledger is intentionally capability-specific. “DONE” does not mean every optional reference feature was copied; it means the active ZN path no longer needs the old product control plane for that slice.

## 9. Immediate code target

The next work should continue from the owned runtime and desktop foundations rather than adding compatibility wrappers.

Priority order:

1. finish the M5/M6 workbench loop around real ZN work: resident-backed thread/work continuity, contextual artifacts and actual workspace association;
2. connect provider/settings editing to the ZN-owned configuration/credential boundary;
3. wire outbound channel attachments only through `OutboundMediaPathPolicy` when the resident has a concrete artifact/message egress path;
4. remove remaining active package/release identity debt: make `apps/desktop/package.json` ZN-owned and ensure the formal builder registers only `zn://`;
5. then rebuild formal self-contained packaging around the independent ZN desktop + `zn_agent` runtime;
6. only after that spend multi-OS CI/release budget on clean-machine, autostart and N → N+1 continuity validation.

Do not make installer polish the architecture driver before the remaining product ownership metadata is corrected.

## 10. Completion test

The source-extraction phase is considered structurally complete when ZN can, from its own interfaces/state and active product control plane:

- consult a real external model without constructing the inherited full agent;
- execute local terminal/PTY work and observe the result;
- search/extract web evidence and feed it into `NativeWorldSense`;
- receive and deliver through at least one external communication channel;
- authorize local-file media egress through a ZN-owned policy before transport;
- launch its own Electron main/preload/renderer and `zn://` protocol;
- install/start its own `zn_agent` resident distribution;

without importing the old product CLI/agent/gateway/desktop as the control plane.

The current code has reached that structural ownership boundary for the active runtime/desktop slices. The remaining work is product completeness plus release/repository migration: finish M5/M6 behavior, close outbound-media transport wiring, replace inherited package/release identity, build clean formal installers, then verify continuity on supported operating systems.
