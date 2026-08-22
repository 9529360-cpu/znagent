# ZN implementation status

> Architecture contract: [`../ZN.md`](../ZN.md)
>
> Source-extraction contract: [`ZN-SOURCE-EXTRACTION.md`](ZN-SOURCE-EXTRACTION.md)
>
> This file records **what is actually implemented now**. Code remains authoritative over this ledger.
>
> Active development branch: `dev/zn-agent`. `main` remains untouched until the explicit promotion milestone in `ZN.md`.

## Verified implementation baseline

Latest source implementation baseline verified before this documentation-only synchronization:

```text
31a7e3d88bd8ea4df15060dfa100f8112289a015
```

Commit:

```text
feat: build ZN content-first workbench
```

Normal ZN CI for that source baseline:

```text
ZN Kernel / Python      success
Electron / TypeScript  success
Actions run             32570858396
```

Documentation-only synchronization commits use `[skip ci]`; the source baseline above is therefore the current executable/CI evidence for this ledger.

## What this conversation completed

This conversation started from source baseline:

```text
6f549642885c0ca55d20d5055b848dbe49c1ead4
```

and advanced the implementation through source baseline `31a7e3d88bd8ea4df15060dfa100f8112289a015`.

The work completed in this conversation is:

### 1. M1 packaged Python/runtime ownership

- added independent `runtime/python/pyproject.toml` with distribution identity `znagent`;
- added final installed entrypoint `zn-resident = "zn_agent.resident:main"`;
- added `runtime/python/zn_agent/resident.py`;
- changed packaged runtime staging to install `runtime/python`, not the inherited repository-root Python distribution;
- changed runtime verification to require `zn_agent` resident/core entrypoints and reject `hermes_cli`;
- changed Electron resident launch to `python -m zn_agent.resident`;
- made `agent/kernel/provider_bridge.py` construct the resident from ZN config/resources only;
- removed the production `LegacyAIAgentWorkerFactory` / `run_agent.AIAgent` seam from `agent/kernel/worker.py`;
- added runtime ownership tests that reject `hermes_cli` / `run_agent` imports in the active kernel;
- added an isolated CI venv that installs only the ZN runtime distribution and performs a zero-model resident pulse.

Result:

```text
portable/isolated Python
→ install runtime/python
→ import/start zn_agent
→ build ZN resident
→ zero-model pulse succeeds
```

without requiring the inherited CLI/agent product.

### 2. PTY completed-session lifecycle closure

- fixed interactive PTY sessions that die immediately before or during `write_stdin()` / `resize()`;
- all such paths now converge on the same final poll/finalization path;
- exit code, buffered output and observed cwd are preserved;
- the completed session is removed and the PTY is closed exactly through the normal forget path;
- regression tests cover completion during write, completion during resize and late interaction with an already-dead PTY.

### 3. Outbound local-media authorization boundary

- added `agent/kernel/outbound_media.py`;
- added `OutboundMediaPathPolicy` before any future channel local-file upload;
- default authorized roots are ZN `artifacts/` and `channels/outbound/`;
- roots and candidates are realpath-resolved before containment checks;
- relative paths, missing files, directories, empty files and symlink escapes are rejected;
- optional size bounds are supported without baking a platform-specific limit into the generic policy;
- tests lock the authorization behavior.

This is the **authorization boundary**, not yet Telegram outbound media transport. Telegram local-file sending still must be wired through this policy before it is considered implemented.

### 4. M4 independent Electron main/preload/protocol ownership

The active desktop no longer uses the inherited product main/preload as its control plane.

Implemented:

- `apps/desktop/electron/zn-main.ts`
  - owns `BrowserWindow` creation and lifecycle;
  - owns packaged-runtime activation;
  - owns resident/update IPC registration;
  - owns single-instance behavior;
  - owns navigation routing;
  - owns `zn://` OS protocol registration and deep-link delivery.
- `apps/desktop/electron/zn-preload.ts`
  - exposes only the intentional `window.znDesktop` bridge;
  - no longer imports inherited preload.
- `apps/desktop/electron/zn-protocol.ts`
  - accepts only `zn:` deep links;
  - rejects inherited/web schemes as ZN deep links;
  - bounds input length;
  - normalizes/deduplicates argv links.
- `apps/desktop/electron/zn-shell.html`
  - minimal CSP-bound ZN renderer document.
- `apps/desktop/scripts/bundle-electron-main.mjs`
  - bundles only the ZN main, ZN preload and active ZN renderer entrypoints.

The old active shapes are removed:

```text
zn-main.ts -> inherited electron/main.ts          removed
zn-preload.ts -> inherited preload.ts             removed
active ZN renderer -> inherited ContribController removed
```

### 5. M5 content-first ZN workbench foundation

Implemented independent renderer files:

- `apps/desktop/src/zn/main.tsx`;
- `apps/desktop/src/zn/workbench.tsx`;
- `apps/desktop/src/zn/resident-client.ts`;
- `apps/desktop/src/zn/state.ts`;
- `apps/desktop/src/zn/styles.css`.

Current workbench behavior includes:

- New work;
- recent work and search;
- workspace placeholder/surface;
- central conversation/work thread;
- `Message ZN` composer;
- direct resident task submission through ZN IPC;
- resident status/health/context inspection;
- compact resident activity rendering;
- settings surface;
- update check/apply controls;
- inert deep-link notice: receiving a `zn://` link does not automatically execute an action;
- bounded browser thread cache used only as UI convenience state.

The old transitional `electron/zn-shell-renderer.ts` was removed. The active React renderer root does not import/render `ContribController` or the inherited application shell.

## Current development rule

The active engineering order remains:

```text
inspect mature reference source
→ isolate the coherent mechanism
→ implement a ZN-owned boundary
→ switch the active resident/product caller
→ verify real behavior
→ record remaining migration debt
```

Hermes/reference code is a source mine, not ZN's runtime dependency graph or product control plane.

## Current subsystem ledger

### Resident organism / kernel

Status: **ZN-native resident organism active**.

The resident continues to own identity, life pulses, Situation, Thought, Will, nervous memory, investigation, action, learning/reconsolidation, world/visual sensing and bounded external cognition.

Zero-model operation remains a hard behavior contract: disconnecting external cognition does not erase resident identity/state or stop native pulses.

### External cognitive resources

Status: **native ZN resource layer active; main protocol families extracted**.

Implemented:

- `agent/kernel/cognitive_resource.py`
  - ZN-owned `CognitiveResource` / `CognitiveIncrement` boundary;
  - direct OpenAI-compatible transport;
  - ZN-owned route/endpoint/credential resolution for OpenAI, OpenRouter, DeepSeek, Groq, Mistral, xAI and compatible local endpoints;
  - bounded request/result normalization.
- `agent/kernel/anthropic_resource.py`
  - native Anthropic Messages API behavior;
  - content/thinking normalization and token accounting.
- `agent/kernel/gemini_resource.py`
  - native Gemini `generateContent` behavior;
  - thinking/thought-signature and usage normalization where relevant.
- `agent/kernel/cognitive_factory.py`
  - ZN-owned cognitive-resource selection.
- `agent/kernel/provider_bridge.py`
  - ZN-owned runtime construction.
- `agent/kernel/config.py`
  - ZN-owned runtime/resource configuration.

Production no longer constructs the inherited full AIAgent.

Remaining cognition work is demand-driven: uncommon provider-specific tool-turn/reasoning edge cases and additional providers should be extracted only for concrete resident needs.

### Local terminal / computer body

Status: **active local body extracted, including interactive PTY lifecycle and completed-session reclamation**.

Implemented in `agent/kernel/terminal.py` and `agent/kernel/pty.py`:

- cwd recovery and per-context cwd continuity;
- POSIX shell selection / Windows Git Bash discovery;
- foreground/background execution;
- timeout handling;
- POSIX process-group / Windows process-tree cleanup;
- bounded output;
- inherited credential/runtime-environment isolation;
- POSIX `ptyprocess` and Windows `pywinpty`/ConPTY bridges;
- PTY poll/stop/stdin/resize;
- completion race cleanup and exit/output evidence preservation.

`NativeBody` routes command/terminal work through the ZN terminal path. The active dependency on inherited `tools.terminal_tool` is removed.

Remaining terminal features such as Docker/SSH/cloud execution or large-stream spill-to-disk are demand-driven and must not resurrect the inherited gateway/session control plane.

### Web search / world sense

Status: **multiple ZN-owned providers, failover and network safety active**.

Implemented:

- `agent/kernel/web_resource.py` — ZN-owned web resource boundary, Tavily and failover behavior;
- `agent/kernel/exa_web_resource.py` — Exa search/extract;
- `agent/kernel/firecrawl_web_resource.py` — Firecrawl search/scrape;
- `agent/kernel/url_safety.py` — HTTP(S)-only target boundary and private/metadata/network safety checks;
- `NativeWorldSense._search()` routes through the ZN web resource layer.

The active dependency on inherited `tools.web_tools.web_search_tool` is removed.

### Communication channels

Status: **resident-owned communication lifecycle active; Telegram is the first extracted channel**.

Core contracts/lifecycle:

- `agent/kernel/channel.py` — normalized channel event/message/attachment/delivery contracts;
- `agent/kernel/event_ingress.py` — deterministic external event IDs and idempotent durable ingress;
- `agent/kernel/channel_runtime.py` — channel lifecycle owned by the resident service, never a separate cognition loop;
- `agent/kernel/channel_delivery.py` — durable route/delivery ledger and restart-safe retry state;
- `agent/kernel/telegram_resident_channel.py` — durable Telegram polling checkpoint seam;
- `agent/kernel/telegram_channel.py` — direct Bot API, authorization, long polling, routing, message splitting and bounded inbound media;
- `agent/kernel/telegram_network.py` — Telegram network fallback/proxy/pool handling;
- `agent/kernel/outbound_media.py` — ZN-owned local-file egress authorization boundary.

Invariant:

```text
channel transport
→ normalized ChannelEvent
→ deterministic durable resident ingress
→ SAME resident life loop
→ durable outcome
→ delivery ledger
→ channel transport
```

A channel never owns a separate ZN identity or cognition loop.

Still pending:

- Telegram outbound attachment/media transport through `OutboundMediaPathPolicy`;
- additional channels only behind the same resident-owned contract.

### Python/runtime package ownership

Status: **M1 complete for the active packaged resident path**.

The active packaged resident is the independent `runtime/python` `znagent` distribution and boots via `zn_agent.resident` / `zn-resident`.

Runtime staging and packaged-runtime verification reject inherited `hermes_cli` content. Normal CI verifies an isolated install and zero-model pulse.

Important remaining distinction:

- the repository root still contains inherited/reference Python source and distribution metadata;
- it is retained as source quarry/migration debt;
- it is **not** the active packaged ZN resident distribution;
- final repository topology migration remains later work and should not trigger a cosmetic mass rename before ownership/product seams are finished.

### Desktop/UI ownership

Status: **M4 complete; M5 foundation active; M6 partial**.

Active ZN product path:

```text
ZN Electron main
→ ZN preload
→ ZN renderer root / workbench
→ ZN resident IPC
→ long-lived zn_agent resident
```

Implemented ownership boundaries:

- no inherited Electron main import from active `zn-main.ts`;
- no inherited preload import from active `zn-preload.ts`;
- no inherited `ContribController`/application shell in the active renderer root;
- active `zn://` parsing, single-instance routing and renderer delivery;
- ZN-only active desktop bundle entries;
- ownership regression tests covering all of the above.

M5/M6 work still required:

- real workspace/folder association;
- resident-backed durable work/thread identity/history instead of treating renderer cache as authoritative;
- provider/credential editor connected to ZN config and appropriate secure storage;
- contextual artifacts/files/diffs;
- terminal/browser work surfaces only when invoked;
- richer ongoing resident progress/activity delivery;
- final visual assets, accessibility and keyboard polish.

### Packaging/release ownership

Status: **not formal-release ready; this is now the largest remaining ownership seam**.

The useful mechanisms remain valid:

- portable Python staging;
- versioned runtime identity/materialization;
- resident N → N+1 handoff machinery;
- ZN release manifest/stable channel;
- updater hash/size verification;
- multi-OS builder workflow structure.

But current repository/package facts still include release debt:

- `apps/desktop/package.json` still identifies the package/product as Hermes and points at inherited product metadata;
- its default Electron builder metadata still uses inherited app/protocol/artifact identity;
- `apps/desktop/electron-builder.zn.yml` is mostly ZN-branded but still registers both `zn` and `hermes` schemes;
- formal clean-machine installers have not yet been rebuilt and verified around only the independent ZN desktop + `zn_agent` runtime.

Therefore a green inherited package shape must not be called a final ZN installer.

## Ownership tests currently protecting the active path

The active test suite now protects, among other behavior:

```text
agent/kernel must not import hermes_cli
agent/kernel must not import run_agent
runtime distribution must identify as znagent
runtime staging must install the ZN runtime project
packaged runtime must reject hermes_cli
ZN desktop main must not import inherited main
ZN preload must not import inherited preload
active renderer must not import/render ContribController
ZN deep links must reject hermes:// as a ZN protocol
active bundle must emit the ZN control-plane/renderer entries
```

These tests protect active ownership. They do not imply inactive reference source has been deleted from the repository.

## Milestone status snapshot

```text
M0  blueprint/reset ownership contract                     COMPLETE
M1  independently packageable ZN Python resident runtime   COMPLETE for active packaged path
M2  ZN-native bounded provider cognition                   COMPLETE for active main provider families
M3  ZN-owned terminal + web body/sense paths               COMPLETE for active local/web paths
M4  independent Electron main + preload + zn://            COMPLETE
M5  independent content-first ZN workbench                 IN PROGRESS; foundation active
M6  resident/work/artifact/workspace end-to-end loop       PARTIAL
M7  formal packaging around owned product                  NOT COMPLETE
M8  clean-machine/continuity multi-OS validation           NOT STARTED as release gate
M9  product completeness/hardening                         LATER
M10 repository migration / formal main promotion           LATER; main untouched
```

## Immediate next development sequence

Unless a newly discovered code fact requires changing the architecture contract first:

1. finish M5/M6 around real resident work continuity rather than expanding the inherited UI tree;
2. make work/thread continuity resident-backed and add real workspace/folder association;
3. add contextual artifact/file/diff surfaces and terminal/browser surfaces only when invoked;
4. connect provider/credential settings to the ZN-owned config/secure-storage boundary;
5. wire Telegram outbound attachments only through `OutboundMediaPathPolicy` when an explicit resident artifact/message egress flow exists;
6. replace inherited desktop package metadata with ZN-owned metadata and ensure the formal builder registers only `zn://`;
7. rebuild formal self-contained installers around the independent ZN desktop + `zn_agent` runtime;
8. only then spend multi-OS/clean-machine CI budget validating install, autostart, resident continuity and N → N+1 handoff.

The current architecture driver is now **finish the owned workbench/product loop and close formal package identity**, not another compatibility wrapper and not a return to the inherited control plane.
