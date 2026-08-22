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
dd68e61c91e7aa222fba2f9b2c0516bbb2a190b8
```

Latest coherent M5/M6 source slice:

```text
dd68e61c91e7aa222fba2f9b2c0516bbb2a190b8  feat: add resident-owned provider settings
```

Normal ZN CI for that verified source HEAD:

```text
ZN Kernel / Python      success
Electron / TypeScript  success
Actions run             32583007696
```

Documentation-only synchronization commits use `[skip ci]`; the source baseline above is the executable/CI evidence for this ledger.

## Current development checkpoint

The active product boundary remains ZN-owned across resident runtime, provider cognition, local terminal/PTTY, web sensing, channel lifecycle, Electron main/preload/protocol and the React workbench.

M5/M6 now has:

- resident-backed durable work/thread continuity;
- real resident-backed local workspace/folder association;
- contextual resident-backed file/diff artifact presentation;
- contextual resident-backed terminal evidence after actual terminal/body invocation;
- resident-owned provider/settings editing with secure credential references and hot cognition reconfiguration.

The desktop remains a face/client. Work identity, workspace context, artifact records, provider configuration and credential ownership remain resident-side.

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
- native Git investigation and local command/body execution can anchor to the selected project rather than resident process cwd;
- relative native file actions with workspace/workdir context resolve against durable work context;
- artifact auto-preview containment rejects symlink/path escapes outside the workspace.

### Contextual file/diff/terminal artifacts

Implemented and CI-verified:

- `WorkArtifact` is resident-owned durable work presentation state with bounded retention;
- file artifacts derive from successful ZN Body observations/writes inside the attached workspace;
- writes are re-observed through ZN Body before preview is recorded;
- dirty-workspace context can produce bounded changed-file previews plus a bounded current Git diff;
- automatic artifact file preview is realpath-contained inside the canonical workspace;
- terminal artifacts derive only from actual same-event `NativeBody` command/shell/PTTY action evidence;
- terminal artifacts can exist without a workspace because terminal invocation itself is the condition;
- terminal evidence includes bounded command/output/error plus operation/status/cwd/exit/session metadata where available;
- renderer recognizes file/diff/terminal artifact kinds in the optional right context panel;
- there is no permanent file tree, xterm root or renderer-side terminal executor;
- recent work-list hydration returns only the newest artifact per thread and active get/submit snapshots return at most eight artifacts;
- presentation-layer Git-diff helper commands are not misrepresented as user-work terminal artifacts.

Current artifact support is intentionally partial. General rendered documents, binary previews, browser interaction artifacts, every clean native-investigation preview and richer historical artifact browsing remain future product work.

### Resident-owned provider and credential settings

Implemented and CI-verified:

- `agent/kernel/config.py` now atomically persists ZN-owned non-secret YAML configuration under the ZN home/config boundary;
- `agent/kernel/credentials.py` defines the resident credential-store contract and a `KeyringCredentialStore` backed by the host OS credential facility where available;
- UI-entered provider secrets are stored under stable ZN credential references such as `provider:openai`; raw UI secrets are not written to `config.yaml`;
- the packaged `runtime/python` distribution includes `keyring==25.7.0` so the resident, not Electron, can resolve secrets while the desktop is absent;
- no plaintext credential fallback is used when a secure host backend is unavailable; provider-standard environment variables remain valid existing runtime inputs;
- runtime credential materialization happens only in a transient deep-copied config immediately before ZN cognitive routes are built;
- provider settings RPC returns provider/model/base URL, credential presence/source/backend status and sanitized active route identity, never secret values;
- the desktop preload/IPC forwards provider settings to the long-lived resident and does not use Electron `safeStorage`, keytar or its own credential database;
- `ZnWorkbench` now has a real Models & providers editor for the default provider/model/base URL plus optional API-key replacement/clear;
- the API-key field is transient React state and is not added to the browser thread cache/localStorage;
- simple UI editing refuses to overwrite advanced `zn_kernel.routes` or nested advanced model configuration;
- `ZNKernelRuntime.reconfigure_resources()` hot-applies a new router/worker resource plan while retaining the same resident identity, store, SelfModel, memory and life loop;
- an in-flight goal snapshots its current router/factory so a settings change affects later cognition without mutating a running provider call underneath it;
- a configured remote provider with a missing/invalid credential now degrades to explicit `UnavailableModelWorkerFactory` / provider-unavailable status rather than preventing resident boot;
- secure-provider references survive resident reconstruction and recover the same provider route when the host credential store is available;
- tests verify that UI secrets never appear in YAML or sanitized RPC output, secure-store failure does not fall back to plaintext, advanced routes are protected, and zero-model resident boot remains meaningful.

The secure-store contract deliberately belongs to the Python resident rather than the Electron window. A Linux machine without a usable Secret Service/keyring backend may report secure storage unavailable; ZN remains alive and environment/local providers remain usable.

Current work loop:

```text
user work
→ durable resident thread/workspace
→ SAME ZNResidentRuntime cognition/event loop
→ native investigation/body movement
→ bounded external cognition only when useful/available
→ outcome + resident contextual evidence
→ durable WorkArtifact / activity
→ resident work snapshot
→ contextual workbench panel
```

## Current subsystem ledger

### Resident organism / kernel

Status: **ZN-native resident organism active**.

The resident owns identity, life pulses, Situation, Thought, Will, nervous memory, investigation, action, learning/reconsolidation, world/visual sensing and bounded external cognition.

Zero-model operation remains a hard behavior contract. Removing or misconfiguring external models does not erase resident identity/state or stop native pulses.

### Work/thread/workspace/artifact continuity

Status: **resident-backed durable work + workspace + contextual file/diff/terminal artifact foundation active; M6 still partial**.

Still pending:

- contextual browser surface only when a real browser interaction body/sense path exists;
- broader artifact types/renderers and richer artifact history/navigation where concrete outputs require them;
- richer ongoing progress/activity delivery while work is running;
- final thread/search/accessibility/keyboard polish.

### External cognitive resources and settings

Status: **native ZN resource layer plus resident-owned default provider/credential editor active**.

Implemented:

- ZN-owned `CognitiveResource` / `CognitiveIncrement` boundary;
- OpenAI-compatible transports/routing;
- native Anthropic resource;
- native Gemini resource;
- ZN cognitive-resource factory/configuration;
- secure credential-reference materialization owned by the resident;
- hot resource-plan reconfiguration without resident replacement;
- missing external credential/provider configuration degrades to unavailable cognition instead of resident death;
- desktop provider editor talks only to resident RPC and receives no stored secret.

Advanced multi-route authoring remains intentionally outside the simple editor and is preserved rather than silently flattened.

### Local terminal / computer body

Status: **active local body extracted; interactive PTY lifecycle plus contextual work presentation active**.

`agent/kernel/terminal.py` and `agent/kernel/pty.py` own local foreground/background execution, cwd continuity, timeout/process cleanup, bounded output, interactive PTY lifecycle, stdin/resize and completion cleanup. Workbench terminal presentation is resident evidence only.

### Web search / world sense

Status: **multiple ZN-owned providers, failover and network safety active**.

Implemented Tavily/failover, Exa, Firecrawl, URL/network target safety and resident `NativeWorldSense` routing.

Browser automation/rendering remains a separate body/sense requirement. Current code has no resident-owned browser interaction seam, so no contextual browser facade is claimed.

### Communication channels

Status: **resident-owned communication lifecycle active; Telegram first transport**.

The channel framework, durable ingress/delivery state, Telegram polling/network transport, inbound media and `OutboundMediaPathPolicy` are ZN-owned.

Still pending:

- Telegram outbound attachment/media transport through `OutboundMediaPathPolicy`;
- additional channels only behind the same resident contract.

### Python/runtime package ownership

Status: **M1 complete for the active packaged resident path**.

The packaged resident is the independent `runtime/python` `znagent` distribution and boots through `zn_agent.resident` / `zn-resident`. Runtime staging/verification rejects inherited `hermes_cli`; normal CI verifies isolated zero-model boot. The distribution now also carries the resident secure-credential backend dependency.

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

Implemented product boundaries include independent ZN main/preload/renderer, ZN-only active deep links, resident-backed work/workspace/artifacts, contextual terminal evidence, resident-owned provider settings, updates and resident context surfaces. The renderer does not own arbitrary host paths, filesystem reads, terminal execution or credential persistence.

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
zero-model resident boot must succeed
configured model with unavailable credential must not kill resident boot
UI provider secret must not be persisted in config.yaml
provider settings RPC must never return the stored secret
secure-store unavailability must not fall back to plaintext secret storage
advanced zn_kernel.routes must not be overwritten by the simple editor
provider settings hot apply must preserve resident identity/store
ZN desktop main/preload/renderer must not delegate to inherited control planes
ZN deep links must reject hermes://
resident work history/workspace must survive reconstruction
artifact auto-preview must reject workspace path escapes
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
M5  independent content-first ZN workbench                 IN PROGRESS; provider settings now active
M6  resident work/artifact/workspace end-to-end loop       PARTIAL; file/diff/terminal context active
M7  formal packaging around owned product                  NOT COMPLETE
M8  clean-machine/continuity multi-OS validation           NOT STARTED as release gate
M9  product completeness/hardening                         LATER
M10 repository migration / formal main promotion           LATER; main untouched
```

## Immediate next development sequence

Unless current code reveals a need to change the architecture contract first:

1. improve resident work progress/activity delivery so long-running work exposes meaningful ongoing state rather than only final response/activity snapshots;
2. add a contextual browser surface only after a real resident-owned browser body/sense interaction seam exists; do not relabel web-search results as browser ownership;
3. broaden artifact rendering/history only where concrete work output requires it;
4. wire Telegram outbound attachments only through `OutboundMediaPathPolicy` when an explicit resident artifact/message egress flow exists;
5. replace inherited desktop package metadata with ZN-owned metadata and ensure formal builder registers only `zn://`;
6. rebuild formal self-contained installers around independent ZN desktop + `zn_agent` runtime;
7. only then spend multi-OS/clean-machine CI budget validating install, autostart, resident continuity and N → N+1 handoff.

The architecture driver remains **finish the owned workbench/product loop, then close formal package identity**. Do not add compatibility wrappers or route active product behavior back through inherited control planes.
