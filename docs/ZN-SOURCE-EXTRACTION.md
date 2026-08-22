# ZN mature-source extraction plan

> Governing blueprint: [`../ZN.md`](../ZN.md)
>
> This document is the implementation contract for adopting mature capability code from the inherited/reference tree. It exists to prevent a recurring failure mode: packaging or calling an old product subsystem wholesale when ZN only needs the engineering mechanisms inside it.
>
> Current checkpoint: 2026-08-22. Active development branch: `dev/zn-agent`.

## 1. Non-negotiable rule

ZN does **source-level extraction**, not product-level embedding.

The reference tree is a library of solved engineering problems. When a mature implementation exists, the default is to study it, copy/adapt the coherent useful mechanism into a ZN-owned namespace or boundary, remove inherited product assumptions, and maintain the resulting code as ZN.

Correct:

```text
mature reference source
→ identify mechanism + edge cases + tests
→ extract the smallest coherent implementation slice
→ move/adapt behind ZN-owned interfaces/config/state/lifecycle
→ preserve applicable provenance/license
→ add ZN behavior tests
→ switch the active ZN caller
→ remove compatibility imports when no longer needed
```

Incorrect:

```text
need model access → instantiate the inherited full agent
need terminal → call the inherited product tool forever
need web search → keep inherited tool/config/plugin control plane
need messaging → run the inherited gateway as ZN's communications brain
need desktop → start inherited Electron main/preload/renderer behind a ZN wrapper
need release → package the inherited Python product under a ZN installer
```

Packaging is downstream validation. It is not architecture and must not hide old product dependencies.

## 2. Extraction standard

A capability is considered ZN-owned only when all of the following are true:

1. Production entry begins at a ZN-owned boundary.
2. Its public contract is defined by ZN.
3. ZN configuration/credentials own runtime choices.
4. ZN state/session/identity objects own continuity.
5. It can be tested without starting inherited CLI/agent/gateway/desktop control planes.
6. It can be packaged without inherited product entrypoints.
7. Reference source may remain beside it during migration, but the active caller does not cross back into the old product control plane.

Copying mature implementation is allowed and often preferable. Cosmetic rewrites are not a goal. Ownership transfer is.

The current physical source layout under `agent/kernel/` remains acceptable during migration. `runtime/python/pyproject.toml` installs this ZN-owned kernel under `zn_agent.core`. Namespace/topology cleanup remains lower priority than product completeness and release ownership.

## 3. Current extraction checkpoint

The original resident/runtime/desktop control-plane seams have been cut. Current M5/M6 work is primarily native ZN product development rather than Hermes extraction.

### 3.1 External cognitive/model resources

Status: **ZN-native production path active**.

Implemented:

- `agent/kernel/cognitive_resource.py` — bounded `CognitiveResource` / `CognitiveIncrement` and OpenAI-compatible transport/routing;
- `agent/kernel/anthropic_resource.py` — native Anthropic Messages behavior;
- `agent/kernel/gemini_resource.py` — native Gemini `generateContent` behavior;
- `agent/kernel/cognitive_factory.py` — ZN resource selection;
- `agent/kernel/provider_bridge.py` — resident construction from ZN config/resources;
- `agent/kernel/config.py` — ZN-owned configuration;
- `agent/kernel/worker.py` — generic worker contract and explicit zero-model unavailability.

The production kernel no longer constructs `run_agent.AIAgent`. Remaining provider-specific extraction is demand-driven and must not reconstruct a prompt-owning full-agent loop inside the resource layer.

### 3.2 Local terminal / computer body

Status: **ZN-native local terminal and PTY path active; resident work now has contextual terminal evidence**.

Implemented in `agent/kernel/terminal.py` and `agent/kernel/pty.py`:

- cwd continuity;
- POSIX shell / Windows Git Bash discovery;
- foreground/background local execution;
- timeout/process-tree cleanup;
- bounded output;
- inherited credential/runtime-environment isolation;
- POSIX `ptyprocess` and Windows ConPTY bridges;
- interactive start/poll/stop/stdin/resize;
- completed-session reclamation and final exit/output/cwd evidence preservation.

The real POSIX PTY smoke consumes a final result returned directly by `write_stdin()` when the child exits during that operation. Production cleanup remains immediate; the test no longer assumes a stale follow-up poll is valid.

`ResidentWorkLedger` now turns actual same-event terminal/body action records into bounded `WorkArtifact(kind="terminal")` presentation evidence. This does not create a second terminal owner: command/PTTY execution remains in ZN Body. Electron/React receives only resident-backed evidence after terminal invocation, and the active renderer does not instantiate xterm or expose a direct terminal executor for this slice.

Optional Docker/SSH/cloud backends remain demand-driven. Do not restore inherited gateway/session ownership to obtain them.

### 3.3 Web search / world sense

Status: **ZN-native production path active**.

Implemented:

- ZN web resource boundary and Tavily/failover;
- Exa search/extract;
- Firecrawl search/scrape;
- URL/network target safety;
- `NativeWorldSense` routes through this ZN layer.

Browser automation/rendering remains a separate body/sense requirement, not a shortcut through search-provider code. No browser contextual surface should be invented until a real resident browser interaction seam exists.

### 3.4 Communication channels

Status: **resident-owned lifecycle active; Telegram first transport**.

Core ZN contracts/lifecycle include:

- normalized channel contracts;
- deterministic durable ingress;
- resident-owned channel supervisor;
- durable delivery/retry state;
- Telegram polling/checkpoint/network transport;
- bounded inbound media;
- `OutboundMediaPathPolicy` for local-file egress authorization.

Invariant:

```text
platform transport
→ normalized ChannelEvent
→ deterministic durable resident ingress
→ SAME ZN resident life loop
→ durable outcome
→ delivery ledger
→ selected transport
```

Telegram outbound media still must pass through `OutboundMediaPathPolicy` when a concrete resident artifact/message egress flow exists.

## 4. Independent desktop extraction and current native product work

Status: **M4 ownership complete; M5 materially advanced; M6 partial with resident work/workspace/file-diff/terminal context active**.

The active desktop no longer routes through inherited Electron main, preload or `ContribController`.

Current ZN-owned control plane includes:

- `apps/desktop/electron/zn-main.ts` — BrowserWindow, single-instance lifecycle, packaged runtime activation, resident/update/workspace IPC, navigation and `zn://` ownership;
- `apps/desktop/electron/zn-preload.ts` — intentional ZN bridge only;
- `apps/desktop/electron/zn-protocol.ts` — ZN deep-link parser;
- `apps/desktop/electron/zn-workspace-ipc.ts` — native folder selection/canonicalization;
- `apps/desktop/src/zn/main.tsx` — independent React root;
- `apps/desktop/src/zn/workbench.tsx` — content-first workbench and optional artifact/tool context panel;
- `apps/desktop/src/zn/state.ts` — bounded non-authoritative browser convenience state;
- `apps/desktop/src/zn/resident-client.ts` — resident/workspace/update client;
- `apps/desktop/scripts/bundle-electron-main.mjs` — ZN-only active bundle entries.

Latest verified M5/M6 flow:

```text
ZnWorkbench
→ ZN preload / IPC
→ resident work RPC
→ ResidentWorkLedger
→ durable thread + canonical workspace
→ SAME ZNResidentRuntime event loop
→ NativeInvestigator / NativeBody
→ bounded WorkArtifact file/diff/terminal context
→ durable resident work snapshot
→ contextual workbench panel
```

### 4.1 Resident-backed work/workspace ownership

Work/thread identity and message history are resident-owned. Browser `localStorage` is only a bounded fallback/cache.

Workspace association is native ZN product state, not an inherited project/session model:

```text
renderer supplies threadId only
→ Electron OS-native openDirectory picker
→ Electron realpath + directory check
→ resident work_attach_workspace RPC
→ resident realpath + directory check
→ durable workspace metadata
→ workspace_path / workdir in later work events
```

Generic work metadata cannot forge the reserved workspace field. Native Git/command/body context consumes the durable association.

Relative native file movements with workspace/workdir context are anchored through a ZN-owned path-context helper, while absolute-path behavior remains explicit. Automatic artifact preview verifies realpath containment and rejects symlink escape from the workspace.

### 4.2 Contextual file/diff artifacts

File/diff presentation is native ZN product work, not an extraction of the inherited desktop file/session model.

Implemented:

- durable resident-owned `WorkArtifact` records keyed to thread/event;
- artifacts persist in resident work SQLite with bounded retention;
- file artifacts derive from successful ZN Body file observations/writes inside the attached workspace;
- writes are re-observed through ZN Body before preview is recorded;
- dirty-workspace context can produce a small set of changed-file previews and a bounded current Git diff;
- the diff is labeled as current workspace state after the event, avoiding false attribution of preexisting changes;
- renderer receives artifact content only through resident work snapshots and does not read the host filesystem directly;
- artifacts appear in the optional right context panel; no permanent file tree or IDE shell was added;
- RPC/browser hydration is explicitly bounded: recent work list carries only the newest artifact per thread, active snapshots carry at most eight, browser cache remains bounded/non-authoritative.

### 4.3 Contextual terminal surface

Terminal presentation is also native ZN product work around the already extracted body, not a copy of an inherited terminal/session UI.

Implemented and CI-verified:

- actual same-event command/shell/PTTY action evidence is selected from `NativeBody.recent_actions()`;
- each relevant action can persist a bounded `WorkArtifact(kind="terminal")` with command/output/error/status/cwd/exit/pid/session metadata;
- terminal artifacts work even when no workspace is attached because actual terminal invocation is the contextual trigger;
- presentation helper commands issued later for workspace diff collection are not included in the terminal action snapshot, so they are not misrepresented as user-work terminal activity;
- resident work RPC carries terminal artifacts through the same bounded artifact hydration path;
- renderer recognizes and labels terminal artifacts inside the existing optional context panel;
- no permanent terminal pane, xterm root or renderer-owned terminal execution control plane was introduced.

This is evidence/presentation after invocation, not a complete interactive PTY surface. A future interactive control surface should be added only for a concrete work need and must preserve `NativeBody` / `ZNLocalTerminal` ownership.

Current artifact support remains intentionally partial. General rendered documents, binary previews, browser interaction artifacts, every clean native-investigation preview and richer historical artifact browsing remain future product work.

Verified source baseline:

```text
f8679e0487df68623bf08fc6941fd848169b3044
```

Key source commits:

```text
9015246f0c2b28858a848bcc88241af9bbc25c91  feat: persist contextual terminal artifacts
e9a31f854866633ec338871fdf73f6899b60dc1d  test: cover contextual terminal artifacts
6b444302975e65dae2d5402c3ba7ba802adcf2ec  feat: type contextual terminal artifacts
30dfeb91ce252e277c3a30a4bbdb56cda0efb905  feat: hydrate terminal artifact kind
3fe4e5558c98fb9ef5d8b978b27b89785cae7411  feat: label invoked terminal context
f8679e0487df68623bf08fc6941fd848169b3044  test: keep terminal surface contextual
```

CI:

```text
ZN Kernel / Python      success
Electron / TypeScript  success
Actions run             32582229428
```

Remaining workbench/product work:

- contextual browser surface only when a real browser interaction body/sense seam exists;
- broader artifact types/history where concrete output requires them;
- provider/credential editor connected to ZN config/secure storage;
- richer ongoing activity/progress streaming;
- final accessibility/keyboard/visual polish.

## 5. Python/runtime packaging extraction

Status: **M1 active packaged resident path is ZN-owned**.

Implemented:

- independent `runtime/python` `znagent` distribution;
- `zn-resident` / `zn_agent.resident` entrypoint;
- runtime staging installs the ZN project and rejects `hermes_cli`;
- packaged-runtime materialization/verification is ZN-owned;
- Electron launches `python -m zn_agent.resident`.

Repository-root inherited metadata/source remains reference quarry, not the packaged resident.

## 6. What remains inherited and why it is still debt

Known product/release debt includes:

- root inherited/reference distribution metadata/source;
- `apps/desktop/package.json` still identifies Hermes product/repository/build history and retains inherited dependency/script debt;
- package-level default builder metadata remains inherited;
- `apps/desktop/electron-builder.zn.yml` still registers both `zn` and `hermes`;
- inactive inherited Electron/renderer/gateway/source trees remain reference material;
- formal clean installers have not yet been rebuilt and clean-machine verified around only the independent ZN desktop + runtime.

These are migration debts, not permission to route active ZN paths back through inherited control planes.

## 7. What not to extract

Do not blindly migrate:

- inherited branding/paths;
- old CLI UX merely because configuration exists there;
- inherited full-agent orchestration/prompt ownership;
- inherited desktop shell/UI;
- inherited gateway/session identity model;
- vendor/subscription features without a concrete ZN requirement;
- all optional backends at once;
- compatibility shims whose only consumer is the old product;
- snapshot/name tests that preserve old product identity rather than useful behavior.

The reference implementation is a quarry, not a dependency graph to preserve.

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
E9  package independently bootable ZN product                 NEXT release-ownership milestone after M5/M6 core loop
E10 verify clean-machine install/upgrade/multi-OS release      NOT STARTED as product gate
```

“DONE” means the active ZN path no longer needs the inherited control plane for that capability. It does not mean every optional reference feature was copied.

## 9. Immediate code target

Continue from the owned runtime/desktop and resident-backed work/workspace/artifact foundations.

Priority order:

1. add a contextual browser surface only when a real resident browser body/sense interaction seam exists; do not relabel web-search output as browser control;
2. if that browser seam is not yet concrete, connect provider/settings editing to the ZN-owned config/credential boundary rather than inventing a browser facade;
3. broaden artifact rendering/history only where concrete work output requires it;
4. wire outbound channel attachments only through `OutboundMediaPathPolicy` when a concrete resident artifact/message egress path exists;
5. make `apps/desktop/package.json` fully ZN-owned and ensure formal builder registers only `zn://`;
6. rebuild formal self-contained packaging around independent ZN desktop + `zn_agent` runtime;
7. only then spend multi-OS CI/release budget on clean-machine, autostart and N → N+1 continuity validation.

Do not let installer polish become the architecture driver before the remaining product loop and package identity are corrected.

## 10. Completion test

The source-extraction phase is structurally complete for the active slices when ZN can, through its own interfaces/state/control plane:

- consult external cognition without constructing inherited full agent;
- execute local terminal/PTTY work;
- search/extract web evidence;
- receive/deliver through a resident-owned external channel;
- authorize local-file media egress through ZN policy;
- launch its own Electron main/preload/renderer and `zn://` protocol;
- install/start its own `zn_agent` resident distribution;
- preserve desktop work/thread continuity in resident state;
- preserve real workspace association in resident work state and propagate it into native Git/body context;
- persist/present bounded contextual workspace file/diff artifacts without giving the renderer filesystem ownership;
- persist/present bounded terminal evidence only after actual resident/body terminal invocation, without making renderer the terminal owner;

without importing inherited CLI/agent/gateway/desktop as the active product control plane.

The current code has reached that structural ownership boundary for the active runtime/desktop slices. Remaining work is product completeness plus release/repository migration: real browser interaction/context when justified, provider settings, broader artifacts where needed, outbound-media transport, package/release identity, clean formal installers and supported-OS continuity validation.
