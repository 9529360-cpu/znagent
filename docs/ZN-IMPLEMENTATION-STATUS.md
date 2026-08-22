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
d66d2b5d95b82bd7ba7fd9a7fcee3f7223a5d7a9
```

Source commits in the latest coherent M5/M6 slice:

```text
8ccbb324c875af506ef45cb3ab21d864504e9064  feat: attach durable workspaces to resident work
d66d2b5d95b82bd7ba7fd9a7fcee3f7223a5d7a9  test: honor PTY completion from stdin write
```

Normal ZN CI for that verified source HEAD:

```text
ZN Kernel / Python      success
Electron / TypeScript  success
Actions run             32574451330
```

The first CI run for the workspace feature exposed an existing real-PTY smoke race in which the test discarded a terminal completion returned directly by `write_stdin()` and then polled an intentionally reclaimed session. Production PTY cleanup already matched the established contract, so the corrective commit fixes the smoke test to consume the returned terminal state instead of changing completed-session reclamation semantics.

Documentation-only synchronization commits use `[skip ci]`; the source baseline above is therefore the current executable/CI evidence for this ledger.

## Current development checkpoint

The active product boundary remains ZN-owned across the resident runtime, main provider families, local terminal/PTTY, web sensing, channel lifecycle, Electron main/preload/protocol and active React renderer.

M5/M6 now has both resident-backed work continuity and real resident-backed local workspace association.

### Resident-backed work/thread continuity

Implemented:

- `agent/kernel/work.py` provides `ResidentWorkLedger`;
- work threads and work messages persist in resident-owned SQLite state beside the kernel store, but remain a separate interaction/history substrate rather than nervous-memory facts;
- work submission still enters the same `ZNResidentRuntime.submit()` event loop;
- resident events are linked to the originating work thread/message through event payload metadata;
- completed responses and compact resident activity are persisted back into the durable thread;
- resident RPC provides work list/create/get/submit;
- Electron IPC/preload and the renderer consume the resident work boundary;
- `ZnWorkbench` hydrates resident work history as authoritative state when the resident is available;
- bounded browser storage remains only an offline/convenience fallback;
- New work becomes a durable resident thread rather than a renderer-owned identity.

### Real workspace/folder association

Implemented and CI-verified:

- each resident work thread can persist one local `WorkspaceAssociation` containing canonical path, display name and attachment time;
- workspace metadata is a reserved resident-owned field, so generic work metadata cannot forge a workspace association;
- the normal desktop attach flow accepts only a thread ID from the renderer;
- Electron uses an OS-native `openDirectory` picker, resolves the selected directory with `realpath`, verifies it is a directory, then sends the canonical path to the resident;
- the resident independently resolves/verifies the directory before storing it;
- attaching a folder to the first empty work is enough to make that work durable;
- attach/change/detach state is visible in the workbench sidebar and contextual panel;
- resident work hydration restores the workspace after desktop/re-resident reconstruction;
- every work submission from an associated thread injects resident-owned `workspace_path`, `workdir` and `workspace_name` into the event payload;
- existing native Git investigation consumes `workspace_path`, so repository observations are anchored to the selected project rather than the resident process cwd;
- existing terminal/body action paths can consume `workdir`, so the same durable association is the execution anchor when a local command is formed;
- regression coverage creates a real temporary Git repository, attaches it to a work thread, and verifies zero-model native branch inspection against that repository.

Current work loop:

```text
OS-native folder selection
→ ZN Electron canonicalization
→ resident work_attach_workspace RPC
→ ResidentWorkLedger durable workspace
→ work_submit
→ SAME ZNResidentRuntime event loop
→ event payload workspace_path / workdir
→ native Git/body investigation or action
→ durable response/activity
→ resident-backed thread snapshot
→ renderer
```

The workspace is therefore resident work context, not a renderer label and not an inherited project/session control plane.

## Current subsystem ledger

### Resident organism / kernel

Status: **ZN-native resident organism active**.

The resident owns identity, life pulses, Situation, Thought, Will, nervous memory, investigation, action, learning/reconsolidation, world/visual sensing and bounded external cognition.

Zero-model operation remains a hard behavior contract: disconnecting external cognition does not erase resident identity/state or stop native pulses.

### Work/thread/workspace continuity

Status: **resident-backed durable work history and real local workspace association active; artifact/tool presentation still in progress**.

Implemented:

- durable work thread identity;
- durable user/ZN/activity messages;
- resident RPC list/create/get/submit;
- desktop bridge and renderer hydration from resident history;
- event-to-thread/message linkage;
- browser cache demoted to non-authoritative fallback;
- real attach/change/detach local folder association;
- canonical directory validation in Electron and resident boundaries;
- durable workspace restoration across restart;
- automatic workspace propagation to native investigation/body execution context.

Still pending around this product loop:

- contextual artifact/file/diff production and presentation;
- terminal/browser surfaces only when explicitly invoked by work;
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

A PTY operation such as `write_stdin()` can itself observe terminal completion, return the final `TerminalResult`, and reclaim the session. Callers must consume that returned state rather than assuming a later `poll()` remains valid. The real POSIX PTY smoke now verifies this lifecycle without weakening the cleanup contract.

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

Status: **M4 complete; M5 materially advanced; M6 partial**.

Active ZN product path:

```text
ZN Electron main
→ ZN preload
→ ZN renderer root / workbench
→ ZN resident IPC
→ long-lived zn_agent resident
```

Implemented ownership/product boundaries:

- no inherited Electron main import from active `zn-main.ts`;
- no inherited preload import from active `zn-preload.ts`;
- no inherited `ContribController`/application shell in the active renderer root;
- active `zn://` parsing, single-instance routing and renderer delivery;
- ZN-only active desktop bundle entries;
- resident-backed durable work/thread continuity;
- OS-native local folder selection and resident-backed workspace continuity;
- renderer does not receive a bridge that accepts arbitrary workspace paths for the normal attach flow;
- settings/update and resident context surfaces;
- ownership regression tests covering the active path.

M5/M6 work still required:

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
workspace attach must use the OS folder picker before resident association
renderer preload must not accept an arbitrary workspace_path for normal attach
workspace association must survive resident reconstruction and anchor native Git observation
reserved work metadata must not forge workspace association
```

These tests protect active ownership. They do not imply inactive reference source has been deleted from the repository.

## Milestone status snapshot

```text
M0  blueprint/reset ownership contract                     COMPLETE
M1  independently packageable ZN Python resident runtime   COMPLETE for active packaged path
M2  ZN-native bounded provider cognition                   COMPLETE for active main provider families
M3  ZN-owned terminal + web body/sense paths               COMPLETE for active local/web paths
M4  independent Electron main + preload + zn://            COMPLETE
M5  independent content-first ZN workbench                 IN PROGRESS; resident work + real workspace active
M6  resident/work/artifact/workspace end-to-end loop       PARTIAL; durable work/workspace continuity active
M7  formal packaging around owned product                  NOT COMPLETE
M8  clean-machine/continuity multi-OS validation           NOT STARTED as release gate
M9  product completeness/hardening                         LATER
M10 repository migration / formal main promotion           LATER; main untouched
```

## Immediate next development sequence

Unless a newly discovered code fact requires changing the architecture contract first:

1. add contextual artifact/file/diff production and presentation to resident-backed work;
2. add terminal/browser surfaces only when explicitly invoked by work rather than permanent IDE panes;
3. connect provider/credential settings to the ZN-owned config/secure-storage boundary;
4. wire Telegram outbound attachments only through `OutboundMediaPathPolicy` when an explicit resident artifact/message egress flow exists;
5. replace inherited desktop package metadata with ZN-owned metadata and ensure the formal builder registers only `zn://`;
6. rebuild formal self-contained installers around the independent ZN desktop + `zn_agent` runtime;
7. only then spend multi-OS/clean-machine CI budget validating install, autostart, resident continuity and N → N+1 handoff.

The current architecture driver remains **finish the owned workbench/product loop, then close formal package identity**. Do not add a compatibility wrapper or route the active product back through inherited control planes.
