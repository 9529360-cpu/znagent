# ZN implementation status

> Architecture contract: [`../ZN.md`](../ZN.md)
>
> Source-extraction contract: [`ZN-SOURCE-EXTRACTION.md`](ZN-SOURCE-EXTRACTION.md)
>
> This file records **what is actually implemented now**. Code remains authoritative over this ledger.
>
> Active development branch: `dev/zn-agent`. `main` remains untouched until the explicit promotion milestone in `ZN.md`.

## Verified implementation baseline

Latest source implementation baseline:

```text
0c3ba8e3c5b2c3450d9fd305f4b012d804994acd
```

Commit:

```text
feat: persist resident work threads
```

Normal ZN CI for that source baseline:

```text
ZN Kernel / Python      success
Electron / TypeScript  success
Actions run             32573559233
```

Documentation-only synchronization commits use `[skip ci]`; the source baseline above is therefore the current executable/CI evidence for this ledger.

## Current development checkpoint

The active product boundary remains ZN-owned across the resident runtime, main provider families, local terminal/PTTY, web sensing, channel lifecycle, Electron main/preload/protocol and active React renderer.

This baseline advances M5/M6 by moving work/thread continuity out of renderer-owned browser storage and into resident-owned durable state.

### Resident-backed work/thread continuity

Implemented in this baseline:

- added `agent/kernel/work.py` with `ResidentWorkLedger`;
- work threads and work messages persist in resident-owned SQLite state beside the kernel store, but remain a separate interaction/history substrate rather than nervous-memory facts;
- work submission still enters the same `ZNResidentRuntime.submit()` event loop;
- resident events are linked to the originating work thread/message through event payload metadata;
- completed responses and compact resident activity are persisted back into the durable thread;
- added resident RPC methods for work list/create/get/submit;
- added Electron IPC/preload bridge methods for the same work boundary;
- `ZnWorkbench` now loads resident work history as authoritative state when the resident is available;
- the bounded browser cache remains only an offline/convenience fallback and is replaced by resident snapshots after reconnection;
- New work creates the durable resident thread rather than only a renderer object;
- regression tests cover persistence across resident reconstruction and RPC access;
- desktop ownership tests verify that the active workbench uses the resident work APIs.

Result:

```text
renderer
→ ZN preload / IPC
→ resident work RPC
→ ResidentWorkLedger
→ SAME ZNResidentRuntime task/event loop
→ durable response/activity
→ resident-backed thread snapshot
→ renderer
```

Closing/reopening the desktop no longer makes browser `localStorage` the authority for work history.

## Current subsystem ledger

### Resident organism / kernel

Status: **ZN-native resident organism active**.

The resident owns identity, life pulses, Situation, Thought, Will, nervous memory, investigation, action, learning/reconsolidation, world/visual sensing and bounded external cognition.

Zero-model operation remains a hard behavior contract: disconnecting external cognition does not erase resident identity/state or stop native pulses.

### Work/thread continuity

Status: **resident-backed durable work history active; richer work/project semantics still in progress**.

Implemented:

- durable work thread identity;
- durable user/ZN/activity messages;
- resident RPC list/create/get/submit;
- desktop bridge and renderer hydration from resident history;
- event-to-thread/message linkage;
- browser cache demoted to non-authoritative fallback.

Still pending around this product loop:

- real workspace/folder association;
- artifact/file/diff production and presentation;
- contextual terminal/browser invocation surfaces;
- richer ongoing progress/activity streaming while work is running;
- final thread/search UX polish.

### External cognitive resources

Status: **native ZN resource layer active; main protocol families extracted**.

Implemented:

- `agent/kernel/cognitive_resource.py` — ZN-owned `CognitiveResource` / `CognitiveIncrement` boundary and OpenAI-compatible transports;
- `agent/kernel/anthropic_resource.py` — native Anthropic Messages behavior;
- `agent/kernel/gemini_resource.py` — native Gemini `generateContent` behavior;
- `agent/kernel/cognitive_factory.py` — ZN-owned resource selection;
- `agent/kernel/provider_bridge.py` — ZN-owned resident construction;
- `agent/kernel/config.py` — ZN-owned runtime/resource configuration.

Production no longer constructs the inherited full AIAgent. Additional provider-specific mechanisms remain demand-driven.

### Local terminal / computer body

Status: **active local body extracted, including interactive PTY lifecycle and completed-session reclamation**.

`agent/kernel/terminal.py` and `agent/kernel/pty.py` own local foreground/background process execution, cwd continuity, timeout/process cleanup, bounded output, interactive PTY lifecycle, stdin/resize and completion-race cleanup.

`NativeBody` routes local terminal work through the ZN-owned path. Optional Docker/SSH/cloud backends remain demand-driven.

### Web search / world sense

Status: **multiple ZN-owned providers, failover and network safety active**.

Implemented:

- `agent/kernel/web_resource.py` — web resource boundary, Tavily and failover;
- `agent/kernel/exa_web_resource.py` — Exa search/extract;
- `agent/kernel/firecrawl_web_resource.py` — Firecrawl search/scrape;
- `agent/kernel/url_safety.py` — target/network safety boundary;
- `NativeWorldSense._search()` routes through the ZN resource layer.

### Communication channels

Status: **resident-owned communication lifecycle active; Telegram is the first extracted channel**.

Core contracts/lifecycle:

- `agent/kernel/channel.py`;
- `agent/kernel/event_ingress.py`;
- `agent/kernel/channel_runtime.py`;
- `agent/kernel/channel_delivery.py`;
- `agent/kernel/telegram_resident_channel.py`;
- `agent/kernel/telegram_channel.py`;
- `agent/kernel/telegram_network.py`;
- `agent/kernel/outbound_media.py`.

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

Still pending:

- Telegram outbound attachment/media transport through `OutboundMediaPathPolicy`;
- additional channels only behind the same resident-owned contract.

### Python/runtime package ownership

Status: **M1 complete for the active packaged resident path**.

The active packaged resident is the independent `runtime/python` `znagent` distribution and boots via `zn_agent.resident` / `zn-resident`.

Runtime staging and packaged-runtime verification reject inherited `hermes_cli` content. Normal CI verifies an isolated install and zero-model pulse.

The repository root still contains inherited/reference Python source and distribution metadata as source quarry/migration debt; it is not the active packaged ZN resident distribution.

### Desktop/UI ownership

Status: **M4 complete; M5 foundation active; M6 materially advanced but still partial**.

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
- resident-backed durable work/thread continuity;
- settings/update and resident context surfaces;
- ownership regression tests covering the active path.

M5/M6 work still required:

- real workspace/folder association;
- contextual artifacts/files/diffs;
- terminal/browser work surfaces only when invoked;
- provider/credential editor connected to ZN config and appropriate secure storage;
- richer ongoing resident progress/activity delivery;
- final visual assets, accessibility and keyboard polish.

### Packaging/release ownership

Status: **not formal-release ready**.

Useful mechanisms remain valid:

- portable Python staging;
- versioned runtime identity/materialization;
- resident N → N+1 handoff machinery;
- ZN release manifest/stable channel;
- updater hash/size verification;
- multi-OS builder workflow structure.

Known formal-release debt remains:

- `apps/desktop/package.json` still identifies the package/product as Hermes and retains inherited package/dependency history;
- its default Electron builder metadata still uses inherited app/protocol/artifact identity;
- `apps/desktop/electron-builder.zn.yml` is mostly ZN-branded but still registers both `zn` and `hermes` schemes;
- formal clean-machine installers have not yet been rebuilt and verified around only the independent ZN desktop + `zn_agent` runtime.

A green inherited package shape must not be called a final ZN installer.

## Ownership tests currently protecting the active path

The active test suite protects, among other behavior:

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
resident work history must survive resident reconstruction
active workbench must hydrate/submit through resident work APIs
```

These tests protect active ownership. They do not imply inactive reference source has been deleted from the repository.

## Milestone status snapshot

```text
M0  blueprint/reset ownership contract                     COMPLETE
M1  independently packageable ZN Python resident runtime   COMPLETE for active packaged path
M2  ZN-native bounded provider cognition                   COMPLETE for active main provider families
M3  ZN-owned terminal + web body/sense paths               COMPLETE for active local/web paths
M4  independent Electron main + preload + zn://            COMPLETE
M5  independent content-first ZN workbench                 IN PROGRESS; resident work history now active
M6  resident/work/artifact/workspace end-to-end loop       PARTIAL; durable work continuity active
M7  formal packaging around owned product                  NOT COMPLETE
M8  clean-machine/continuity multi-OS validation           NOT STARTED as release gate
M9  product completeness/hardening                         LATER
M10 repository migration / formal main promotion           LATER; main untouched
```

## Immediate next development sequence

Unless a newly discovered code fact requires changing the architecture contract first:

1. add real workspace/folder association to the resident-backed work model;
2. add contextual artifact/file/diff surfaces and terminal/browser surfaces only when invoked;
3. connect provider/credential settings to the ZN-owned config/secure-storage boundary;
4. wire Telegram outbound attachments only through `OutboundMediaPathPolicy` when an explicit resident artifact/message egress flow exists;
5. replace inherited desktop package metadata with ZN-owned metadata and ensure the formal builder registers only `zn://`;
6. rebuild formal self-contained installers around the independent ZN desktop + `zn_agent` runtime;
7. only then spend multi-OS/clean-machine CI budget validating install, autostart, resident continuity and N → N+1 handoff.

The current architecture driver remains **finish the owned workbench/product loop, then close formal package identity**. Do not add a compatibility wrapper or route the active product back through inherited control planes.
