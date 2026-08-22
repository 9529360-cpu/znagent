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
1ac78c06bf28da299094318921e0ff5fcf256887
```

Latest coherent M5/M6 source slice:

```text
5be1916970b6b339e85efcaf1a9aa0893af93842  feat: present resident work artifacts contextually
8cea9fdd552bc414c0af61ce7fda59fc756d3d44  test: isolate resident artifact assertions
1ac78c06bf28da299094318921e0ff5fcf256887  perf: bound resident artifact snapshots
```

Normal ZN CI for that verified source HEAD:

```text
ZN Kernel / Python      success
Electron / TypeScript  success
Actions run             32575297967
```

The first artifact CI run exposed a test assertion that depended on an unrelated native-investigation response string rather than on artifact behavior. The repository was independently confirmed dirty before the work ran, and the test was corrected to verify the artifact contract itself. No production cognition behavior was weakened to satisfy that test.

Documentation-only synchronization commits use `[skip ci]`; the source baseline above is the executable/CI evidence for this ledger.

## Current development checkpoint

The active product boundary remains ZN-owned across resident runtime, provider cognition, local terminal/PTTY, web sensing, channel lifecycle, Electron main/preload/protocol and the React workbench.

M5/M6 now has:

- resident-backed durable work/thread continuity;
- real resident-backed local workspace/folder association;
- contextual resident-backed file/diff artifact presentation.

The desktop remains a face/client. Work identity, workspace context and artifact records are resident-owned.

### Resident-backed work/thread continuity

Implemented:

- `agent/kernel/work.py` provides `ResidentWorkLedger`;
- work threads and messages persist beside kernel state in resident-owned SQLite;
- work history is interaction state, not nervous-memory facts and not another agent;
- all work submission still enters the same `ZNResidentRuntime.submit()` event loop;
- resident events are linked to originating work/thread/message IDs;
- completed response/activity returns to durable resident work history;
- resident RPC provides work list/create/get/submit;
- renderer hydrates resident work as authoritative history when available;
- browser storage remains a bounded offline/convenience cache only.

### Real workspace/folder association

Implemented and CI-verified:

- each work thread can persist one canonical `WorkspaceAssociation`;
- `workspace` is reserved resident metadata and cannot be forged through generic work metadata;
- renderer asks only to attach a folder to a thread; it does not submit an arbitrary local path through the normal attach bridge;
- Electron uses the OS-native `openDirectory` picker, then `realpath` + directory verification;
- resident independently resolves/verifies the directory before storing it;
- attach/change/detach state survives desktop and resident reconstruction;
- work submission injects resident-owned `workspace_path`, `workdir` and `workspace_name` into the event payload;
- native Git investigation and local command/body execution can therefore anchor to the selected project rather than resident process cwd;
- relative native file actions with workspace/workdir context are resolved against that durable work context;
- artifact auto-preview containment rejects symlink/path escapes outside the workspace.

### Contextual file/diff artifacts

Implemented and CI-verified:

- `WorkArtifact` is a resident-owned durable work record with event ID, kind, name, optional path, bounded textual content, metadata and creation time;
- `work_artifacts` persist in the same resident work database with bounded retention;
- artifact creation does not create a new agent, tool owner or renderer filesystem backend;
- file artifacts are derived from successful ZN Body file observations/writes inside the attached workspace;
- after a successful write, ZN Body re-observes the resulting file before the preview is recorded;
- dirty-workspace context can produce bounded changed-file previews plus a bounded current Git diff;
- Git diff collection uses fixed ZN-owned local commands and the canonical resident workspace;
- the diff is explicitly labeled as current workspace state after the event, not falsely attributed as entirely created by that event;
- artifact paths are realpath-contained inside the attached workspace before automatic file preview;
- artifact summaries are included in resident activity evidence;
- work RPC snapshots expose resident artifacts to the renderer;
- `ZnWorkbench` renders files/diffs only in the contextual right panel and automatically opens that panel when new artifacts appear;
- no permanent file tree or IDE-style multi-pane shell was introduced;
- renderer does not read local files directly;
- browser artifact cache is bounded and non-authoritative;
- resident RPC hydration is bounded further: recent work list carries only the newest artifact per thread, while active get/submit snapshots carry at most eight artifacts.

Current artifact scope is intentionally partial rather than universal. File artifacts currently materialize from ZN Body file observations/writes and dirty-workspace Git context. General rendered documents, binary artifact rendering, every clean native-investigation preview, and richer historical artifact browsing remain future product work.

Current work loop:

```text
user work
→ durable resident thread/workspace
→ SAME ZNResidentRuntime cognition/event loop
→ native investigation/body movement
→ outcome
→ bounded resident contextual observation
→ durable WorkArtifact / activity
→ resident work snapshot
→ contextual workbench panel
```

Artifact collection after an event is bounded/read-only presentation context. Destructive movements are not performed by the presentation layer.

## Current subsystem ledger

### Resident organism / kernel

Status: **ZN-native resident organism active**.

The resident owns identity, life pulses, Situation, Thought, Will, nervous memory, investigation, action, learning/reconsolidation, world/visual sensing and bounded external cognition.

Zero-model operation remains a hard behavior contract: removing external models does not erase resident identity/state or stop native pulses.

### Work/thread/workspace/artifact continuity

Status: **resident-backed durable work + workspace + contextual file/diff artifact foundation active; M6 still partial**.

Implemented:

- durable work/thread identity and messages;
- resident work RPC;
- event-to-thread/message linkage;
- real workspace attach/change/detach;
- workspace propagation into native Git/body context;
- workspace-relative native file-action resolution;
- resident-backed file/diff artifact records;
- bounded artifact hydration/presentation;
- contextual workbench file/diff preview.

Still pending:

- contextual terminal surface only when a work event invokes/needs terminal interaction;
- contextual browser surface only when browser interaction exists;
- broader artifact types/renderers and richer artifact history/navigation;
- richer ongoing progress/activity delivery while work is running;
- final thread/search/accessibility/keyboard polish.

### External cognitive resources

Status: **native ZN resource layer active; main protocol families extracted**.

Implemented:

- ZN-owned `CognitiveResource` / `CognitiveIncrement` boundary;
- OpenAI-compatible transports/routing;
- native Anthropic resource;
- native Gemini resource;
- ZN cognitive-resource factory and configuration;
- resident construction no longer creates inherited `run_agent.AIAgent`.

Additional provider-specific mechanisms remain demand-driven.

### Local terminal / computer body

Status: **active local body extracted, including interactive PTY lifecycle and completed-session reclamation**.

`agent/kernel/terminal.py` and `agent/kernel/pty.py` own local foreground/background execution, cwd continuity, timeout/process cleanup, bounded output, interactive PTY lifecycle, stdin/resize and completion cleanup.

A PTY operation such as `write_stdin()` can itself observe completion and return the final result while reclaiming the session. The real POSIX PTY smoke consumes that returned state rather than performing a stale extra poll.

`NativeBody` is also the source for artifact file/diff presentation observations; this does not transfer filesystem ownership to the workbench.

### Web search / world sense

Status: **multiple ZN-owned providers, failover and network safety active**.

Implemented:

- `agent/kernel/web_resource.py` — ZN web boundary, Tavily and failover;
- Exa search/extract;
- Firecrawl search/scrape;
- URL/network target safety;
- `NativeWorldSense` routes through the ZN resource layer.

### Communication channels

Status: **resident-owned communication lifecycle active; Telegram first transport**.

The channel framework, durable ingress/delivery state, Telegram polling/network transport, inbound media and `OutboundMediaPathPolicy` are ZN-owned.

Still pending:

- Telegram outbound attachment/media transport through `OutboundMediaPathPolicy`;
- additional channels only behind the same resident contract.

### Python/runtime package ownership

Status: **M1 complete for the active packaged resident path**.

The packaged resident is the independent `runtime/python` `znagent` distribution and boots through `zn_agent.resident` / `zn-resident`. Runtime staging and verification reject inherited `hermes_cli` content; normal CI verifies isolated zero-model boot.

Repository-root inherited/reference Python metadata remains source quarry/migration debt, not the packaged resident.

### Desktop/UI ownership

Status: **M4 complete; M5 materially advanced; M6 partial**.

Active path:

```text
ZN Electron main
→ ZN preload
→ ZN React workbench
→ ZN resident IPC
→ long-lived zn_agent resident
```

Implemented product boundaries include:

- independent ZN main/preload/renderer;
- ZN-only active deep-link handling and bundle entries;
- resident-backed work history;
- native folder picker + resident workspace continuity;
- contextual resident-backed file/diff artifacts;
- renderer does not directly own arbitrary host-path attachment or filesystem reads;
- settings/update and resident context surfaces;
- ownership regression tests for all these active seams.

M5/M6 still require:

- terminal/browser surfaces only when invoked;
- provider/credential editor connected to ZN config/secure storage;
- richer ongoing activity/progress delivery;
- broader artifact rendering/history;
- final visual/accessibility/keyboard polish.

### Packaging/release ownership

Status: **not formal-release ready**.

Known debt remains:

- `apps/desktop/package.json` still identifies inherited Hermes product/repository/build history;
- default package-level builder metadata remains inherited;
- `apps/desktop/electron-builder.zn.yml` still registers both `zn` and `hermes`;
- formal installers have not yet been rebuilt/clean-machine verified around only the independent ZN desktop + `zn_agent` runtime.

Do not call the inherited package shape a final ZN installer.

## Ownership/behavior tests protecting the active path

The suite now protects, among other behavior:

```text
agent/kernel must not import hermes_cli or run_agent
runtime distribution must identify as znagent
packaged runtime must reject hermes_cli
ZN desktop main/preload/renderer must not delegate to inherited control planes
ZN deep links must reject hermes://
resident work history must survive reconstruction
workspace attach must use OS folder picker before resident association
renderer normal workspace bridge must not accept arbitrary workspace_path
workspace association must survive restart and anchor native Git observation
relative native file action can inherit workspace context
artifact auto-preview must reject workspace symlink escape
resident dirty-workspace context must persist file + diff artifacts
work RPC must expose resident artifacts
active renderer must hydrate/render artifacts without direct filesystem access
artifact browser/RPC snapshots must remain bounded
```

## Milestone status snapshot

```text
M0  blueprint/reset ownership contract                     COMPLETE
M1  independently packageable ZN Python resident runtime   COMPLETE for active packaged path
M2  ZN-native bounded provider cognition                   COMPLETE for active main provider families
M3  ZN-owned terminal + web body/sense paths               COMPLETE for active local/web paths
M4  independent Electron main + preload + zn://            COMPLETE
M5  independent content-first ZN workbench                 IN PROGRESS; work/workspace/context artifacts active
M6  resident work/artifact/workspace end-to-end loop       PARTIAL; durable file/diff context active
M7  formal packaging around owned product                  NOT COMPLETE
M8  clean-machine/continuity multi-OS validation           NOT STARTED as release gate
M9  product completeness/hardening                         LATER
M10 repository migration / formal main promotion           LATER; main untouched
```

## Immediate next development sequence

Unless current code reveals a need to change the architecture contract first:

1. add contextual terminal/browser surfaces only when explicitly invoked by work rather than permanent IDE panes;
2. broaden artifact rendering/history only where concrete work output requires it;
3. connect provider/credential settings to the ZN-owned config/secure-storage boundary;
4. wire Telegram outbound attachments only through `OutboundMediaPathPolicy` when an explicit resident artifact/message egress flow exists;
5. replace inherited desktop package metadata with ZN-owned metadata and ensure formal builder registers only `zn://`;
6. rebuild formal self-contained installers around independent ZN desktop + `zn_agent` runtime;
7. only then spend multi-OS/clean-machine CI budget validating install, autostart, resident continuity and N → N+1 handoff.

The architecture driver remains **finish the owned workbench/product loop, then close formal package identity**. Do not add compatibility wrappers or route active product behavior back through inherited control planes.
