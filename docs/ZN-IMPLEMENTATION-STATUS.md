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
2157283a4e3392ec34f22c100fd0b238805be9b6
```

Latest coherent M5/M6 source slices:

```text
dd68e61c91e7aa222fba2f9b2c0516bbb2a190b8  feat: add resident-owned provider settings
89d24027249e1a13b6f6b5e9639127f0fc5f4ddc  feat: persist active work runs [skip ci]
37e662433f958e298d3f2d337af9935c4303a370  feat: expose resident work progress
2157283a4e3392ec34f22c100fd0b238805be9b6  test: isolate resident progress cache assertion
```

Normal ZN CI for the current verified source HEAD:

```text
ZN Kernel / Python      success
Electron / TypeScript  success
Actions run             32584154366
```

The provider-settings source slice was independently verified by normal CI in Actions run `32583007696` before the later progress slice. Documentation-only synchronization commits use `[skip ci]`.

## Current development checkpoint

The active product boundary remains ZN-owned across resident runtime, provider cognition, local terminal/PTTY, web sensing, channel lifecycle, Electron main/preload/protocol and the React workbench.

M5/M6 now has:

- resident-backed durable work/thread continuity;
- real resident-backed local workspace/folder association;
- contextual resident-backed file/diff artifact presentation;
- contextual resident-backed terminal evidence after actual terminal/body invocation;
- resident-owned provider/settings editing with secure credential references and hot cognition reconfiguration;
- durable active work-run identity plus resident-derived ongoing progress while work continues without the desktop.

The desktop remains a face/client. Work identity, active-run state, workspace context, artifact records, provider configuration and credential ownership remain resident-side.

### Resident-backed work/thread continuity

Implemented:

- `agent/kernel/work.py` provides `ResidentWorkLedger`;
- work threads and messages persist beside kernel state in resident-owned SQLite;
- work history is interaction state, not nervous-memory facts and not another agent;
- work enters the same `ZNResidentRuntime` event loop;
- resident events are linked to originating work/thread/message IDs;
- completed response/activity returns to durable resident work history;
- resident RPC provides work list/create/get/start/progress/submit;
- renderer hydrates resident work as authoritative history when available;
- browser storage remains a bounded offline/convenience cache only.

### Durable active work and ongoing progress

Implemented and CI-verified:

- `work_runs` durably links an accepted resident event to its work thread and originating user message before the event completes;
- `work_start` enqueues resident work and returns immediately instead of making the Electron request own the whole cognition lifetime;
- the resident life loop can continue that durable event after the desktop disconnects;
- one thread rejects a second parallel active event instead of ambiguously interleaving two work runs;
- completed resident events are finalized idempotently into deterministic ZN/activity messages and contextual artifacts;
- finalization can occur after resident reconstruction, so desktop absence does not lose the outcome;
- `work_progress` reports real resident event status/stage/next action rather than simulated percentages;
- progress can include current matching Thought, investigation rounds/unresolved gap/next probe and recent same-event Body actions;
- renderer polls only the resident progress RPC and keeps progress out of the localStorage thread cache;
- final thread/artifact hydration occurs from the resident after durable finalization;
- renderer interruption after resident acceptance is reported as a reconnectable condition, not converted into a false work failure.

Current progress is meaningful state sampling, not token/step streaming. A future push/stream transport may improve latency, but is not required to preserve work ownership or continuity.

### Real workspace/folder association

Implemented and CI-verified:

- each work thread can persist one canonical `WorkspaceAssociation`;
- `workspace` is reserved resident metadata and cannot be forged through generic work metadata;
- renderer asks only to attach a folder to a thread;
- Electron uses the OS-native `openDirectory` picker, then realpath + directory verification;
- resident independently resolves/verifies the directory before storing it;
- attach/change/detach survives desktop and resident reconstruction;
- work events receive resident-owned `workspace_path`, `workdir` and `workspace_name` context;
- native Git investigation and local command/body execution anchor to the selected project;
- relative native file actions resolve against durable work context;
- artifact auto-preview containment rejects symlink/path escapes outside the workspace.

### Contextual file/diff/terminal artifacts

Implemented and CI-verified:

- `WorkArtifact` is resident-owned durable work presentation state with bounded retention;
- file artifacts derive from successful ZN Body observations/writes inside the attached workspace;
- writes are re-observed through ZN Body before preview is recorded;
- dirty-workspace context can produce bounded changed-file previews plus a bounded current Git diff;
- automatic artifact file preview is realpath-contained inside the canonical workspace;
- terminal artifacts derive only from actual same-event `NativeBody` command/shell/PTTY action evidence;
- terminal evidence can exist without a workspace and includes bounded operation/status/output metadata;
- renderer recognizes file/diff/terminal artifact kinds only in the optional right context panel;
- there is no permanent file tree, xterm root or renderer-side terminal executor;
- recent work-list hydration returns only the newest artifact per thread and active snapshots remain bounded;
- presentation-layer Git-diff helper commands are not misrepresented as user-work terminal artifacts.

Current artifact support is intentionally partial. General rendered documents, binary previews, browser interaction artifacts and richer historical artifact browsing remain future product work.

### Resident-owned provider and credential settings

Implemented and CI-verified:

- `agent/kernel/config.py` atomically persists ZN-owned non-secret YAML configuration;
- `agent/kernel/credentials.py` defines resident credential references and an OS-keyring-backed secure store;
- UI-entered provider secrets are stored under stable ZN credential references rather than written to `config.yaml`;
- packaged `runtime/python` includes `keyring==25.7.0` so credential ownership remains with the resident;
- no plaintext credential fallback is used when a secure host backend is unavailable;
- provider-standard environment variables remain valid runtime inputs;
- runtime credential materialization exists only in a transient deep-copied config used to build cognitive routes;
- provider settings RPC returns sanitized provider/model/base URL, credential presence/source/backend and route identity, never stored secret values;
- Electron does not own credential persistence through `safeStorage`, keytar or another desktop credential database;
- `ZnWorkbench` has a real default provider/model/base URL editor plus optional API-key replace/clear;
- the API-key field is transient React state and is not browser-cached;
- simple UI editing refuses to overwrite advanced `zn_kernel.routes` or nested advanced model configuration;
- `ZNKernelRuntime.reconfigure_resources()` hot-applies a new cognition resource plan without replacing resident identity/store/SelfModel/memory/life;
- an in-flight goal uses the router/factory snapshot it started with;
- a configured remote provider with missing/invalid credential degrades to explicit unavailable cognition rather than resident boot failure.

A Linux machine without a usable Secret Service/keyring backend may report secure storage unavailable; ZN remains alive and environment/local providers remain usable.

Current work loop:

```text
user work
→ durable resident thread/workspace
→ durable WorkRun + resident event
→ SAME ZNResidentRuntime life/cognition loop
→ native investigation/body movement
→ optional bounded external cognition
→ resident-derived ongoing progress
→ durable outcome + contextual evidence
→ WorkArtifact / activity finalization
→ resident work snapshot
→ content-first workbench
```

## Current subsystem ledger

### Resident organism / kernel

Status: **ZN-native resident organism active**.

The resident owns identity, life pulses, Situation, Thought, Will, nervous memory, investigation, action, learning/reconsolidation, world/visual sensing and bounded external cognition. Zero-model operation remains a hard behavior contract.

### Work/thread/workspace/artifact continuity

Status: **resident-backed durable work + active-run progress + workspace + contextual file/diff/terminal artifacts active; M6 still partial**.

Still pending:

- contextual browser surface only when a real resident-owned browser interaction body/sense path exists;
- broader artifact renderers/history where concrete outputs require them;
- final thread/search/accessibility/keyboard polish.

### External cognitive resources and settings

Status: **native ZN resource layer plus resident-owned default provider/credential editor active**.

OpenAI-compatible, Anthropic and Gemini resources are ZN-owned. Secure credential-reference materialization and hot resource-plan reconfiguration are resident-owned. Advanced multi-route authoring remains intentionally outside the simple editor and is preserved rather than silently flattened.

### Local terminal / computer body

Status: **active ZN local body/PTTY plus contextual work presentation active**.

`agent/kernel/terminal.py` and `agent/kernel/pty.py` own foreground/background execution, cwd continuity, timeout/process cleanup, bounded output, interactive PTY stdin/resize and completed-session reclamation. Workbench terminal presentation is resident evidence only.

### Web search / world sense

Status: **multiple ZN-owned providers, failover and network safety active**.

Tavily/failover, Exa, Firecrawl, URL/network target safety and `NativeWorldSense` routing are active. Browser automation/rendering remains a separate body/sense requirement; current active kernel has no resident-owned browser interaction seam yet.

### Communication channels

Status: **resident-owned communication lifecycle active; Telegram first transport**.

Durable ingress/delivery state, Telegram polling/network transport, inbound media and `OutboundMediaPathPolicy` are ZN-owned. Telegram outbound attachment/media transport through that policy remains pending.

### Python/runtime package ownership

Status: **M1 complete for the active packaged resident path**.

The packaged resident is the independent `runtime/python` `znagent` distribution and boots through `zn_agent.resident` / `zn-resident`. Runtime staging/verification rejects inherited `hermes_cli`; normal CI verifies isolated zero-model boot.

### Desktop/UI ownership

Status: **M4 complete; M5 materially advanced; M6 materially advanced but still partial**.

Active path:

```text
ZN Electron main
→ ZN preload
→ ZN React workbench
→ ZN resident RPC
→ long-lived zn_agent resident
```

The renderer does not own arbitrary host paths, filesystem reads, terminal execution, work progress truth or credential persistence.

### Packaging/release ownership

Status: **not formal-release ready**.

Known debt remains:

- `apps/desktop/package.json` still identifies inherited Hermes product/repository/build history;
- default package-level builder metadata remains inherited;
- `apps/desktop/electron-builder.zn.yml` still registers both `zn` and `hermes`;
- formal installers have not yet been rebuilt/clean-machine verified around only the independent ZN desktop + `zn_agent` runtime.

## Ownership/behavior tests protecting the active path

The suite protects, among other behavior:

```text
agent/kernel must not import hermes_cli or run_agent
runtime distribution must identify as znagent
packaged runtime must reject hermes_cli
zero-model resident boot must succeed
configured model with unavailable credential must not kill resident boot
UI provider secret must not be persisted in config.yaml
provider settings RPC must never return the stored secret
secure-store unavailability must not fall back to plaintext secret storage
advanced zn_kernel.routes must not be overwritten by the simple editor
provider settings hot apply must preserve resident identity/store
resident accepted work must persist before completion
completed detached work must finalize after resident reconstruction
one thread must reject parallel active resident work
work progress must come from resident event/thought/investigation/body state
progress truth must not be persisted in renderer localStorage
ZN desktop must not delegate to inherited control planes
ZN deep links must reject hermes://
resident work history/workspace must survive reconstruction
file/diff/terminal artifacts must remain resident-backed and bounded
renderer must not own direct filesystem/terminal/credential backends
```

## Milestone status snapshot

```text
M0  blueprint/reset ownership contract                     COMPLETE
M1  independently packageable ZN Python resident runtime   COMPLETE for active packaged path
M2  ZN-native bounded provider cognition                   COMPLETE for active main provider families
M3  ZN-owned terminal + web body/sense paths               COMPLETE for active local/web paths
M4  independent Electron main + preload + zn://            COMPLETE
M5  independent content-first ZN workbench                 IN PROGRESS; settings/work/progress/context active
M6  resident work/artifact/workspace end-to-end loop       PARTIAL; durable active work + progress active
M7  formal packaging around owned product                  NOT COMPLETE
M8  clean-machine/continuity multi-OS validation           NOT STARTED as release gate
M9  product completeness/hardening                         LATER
M10 repository migration / formal main promotion           LATER; main untouched
```

## Immediate next development sequence

Unless current code reveals a need to change the architecture contract first:

1. inspect mature browser mechanisms and add a real resident-owned browser body/sense seam only if it can be extracted without inherited browser/session product ownership; then expose browser context only after actual invocation;
2. broaden artifact rendering/history only where concrete work output requires it;
3. wire Telegram outbound attachments only through `OutboundMediaPathPolicy` when an explicit resident artifact/message egress flow exists;
4. replace inherited desktop package metadata with ZN-owned metadata and ensure formal builder registers only `zn://`;
5. rebuild formal self-contained installers around independent ZN desktop + `zn_agent` runtime;
6. only then spend multi-OS/clean-machine CI budget validating install, autostart, resident continuity and N → N+1 handoff.

The architecture driver remains **finish the owned workbench/product loop, then close formal package identity**. Do not invent a browser facade by relabeling web search results, and do not route active behavior back through inherited browser/session control planes.