# ZN mature-source extraction plan

> Governing blueprint: [`../ZN.md`](../ZN.md)
>
> This document is the implementation contract for adopting mature capability code from the inherited/reference tree. It exists to prevent a recurring failure mode: packaging or calling an old product subsystem wholesale when ZN only needs the engineering mechanisms inside it.
>
> Current checkpoint: 2026-08-22. The active development branch is `dev/zn-agent`.

## 1. Non-negotiable rule

ZN does **source-level extraction**, not product-level embedding.

The reference tree is a library of solved engineering problems. When a mature implementation exists, the default is to study it, copy/adapt the useful mechanism into a ZN-owned namespace, remove old product assumptions, and maintain the resulting code as ZN.

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

Packaging is downstream validation. It is not the architecture and must not hide product-level dependencies.

## 2. Extraction standard

A capability is considered ZN-owned only when all of the following are true:

1. The production import begins in a ZN-owned boundary.
2. Its public interface is defined by ZN.
3. ZN configuration and credential resolution own runtime choices.
4. ZN state/session/identity objects own continuity.
5. The extracted code can be tested without starting the old CLI/agent/gateway/desktop.
6. The capability can be packaged without requiring old product entrypoints.
7. Old source may remain beside it as reference, but the active ZN call path does not cross back into the old product control plane.

Copying mature implementation is allowed and often preferred. Cosmetic rewrites are not a goal. The extraction must remove product coupling, not historical ancestry.

The current physical source layout under `agent/kernel/` is allowed during migration. `runtime/python/pyproject.toml` maps that ZN-owned kernel source into the installed `zn_agent.core` namespace. `ZN.md` deliberately places ownership-seam removal ahead of a mass namespace rename.

## 3. Current extraction checkpoint

The main resident/runtime seams that originally crossed into the inherited product are cut. Workbench development is now primarily ZN-native product work rather than inherited-source extraction.

### 3.1 External cognitive/model resources

Status: **ZN-native production path active**.

Implemented ZN-owned mechanisms include:

- `agent/kernel/cognitive_resource.py` — bounded `CognitiveResource` / `CognitiveIncrement`, OpenAI-compatible transport and provider routing;
- `agent/kernel/anthropic_resource.py` — native Anthropic Messages behavior;
- `agent/kernel/gemini_resource.py` — native Gemini `generateContent` behavior;
- `agent/kernel/cognitive_factory.py` — provider/resource selection;
- `agent/kernel/provider_bridge.py` — resident construction from ZN configuration/resources;
- `agent/kernel/config.py` — ZN-owned configuration loading;
- `agent/kernel/worker.py` — generic worker contract plus zero-model unavailability behavior.

The production kernel no longer constructs `run_agent.AIAgent`. Remaining cognition extraction is demand-driven and must not recreate a prompt-owning full-agent loop inside the resource layer.

### 3.2 Local terminal / computer body

Status: **ZN-native local terminal and PTY path active**.

Implemented in `agent/kernel/terminal.py` and `agent/kernel/pty.py`:

- cwd resolution/continuity;
- POSIX shell and Windows Git Bash discovery;
- foreground/background execution;
- timeout and process-tree/process-group cleanup;
- bounded output;
- inherited runtime/credential environment isolation;
- POSIX `ptyprocess` and Windows `pywinpty`/ConPTY bridges;
- interactive session start/poll/stop/stdin/resize;
- completed-session reclamation and exit/cwd evidence preservation.

Optional Docker/SSH/cloud backends remain demand-driven. Do not restore the old gateway/session control plane to obtain them.

### 3.3 Web search / world sense

Status: **ZN-native production path active**.

Implemented:

- `agent/kernel/web_resource.py` — ZN-owned web resource contract, Tavily and failover;
- `agent/kernel/exa_web_resource.py` — Exa search/extract;
- `agent/kernel/firecrawl_web_resource.py` — Firecrawl search/scrape;
- `agent/kernel/url_safety.py` — HTTP(S)-only and private/metadata/network target protections;
- `NativeWorldSense._search()` routes through the ZN web resource layer.

Browser automation/rendering remains a separate body/sense requirement, not a search-provider shortcut.

### 3.4 Communication channels

Status: **resident-owned channel lifecycle active; Telegram is the first extracted transport**.

Core ZN contracts and lifecycle:

- `agent/kernel/channel.py`;
- `agent/kernel/event_ingress.py`;
- `agent/kernel/channel_runtime.py`;
- `agent/kernel/channel_delivery.py`;
- `agent/kernel/telegram_resident_channel.py`;
- `agent/kernel/telegram_channel.py`;
- `agent/kernel/telegram_network.py`;
- `agent/kernel/outbound_media.py`.

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

Outbound local-file security is separated from transport. Telegram outbound media transport still must consume `OutboundMediaPathPolicy` before upload and should only be wired when the resident has an explicit artifact/message egress path.

## 4. Independent desktop extraction and current native product work

Status: **M4 ownership seam complete; M5 workbench foundation active; resident-backed work continuity now active**.

The active ZN desktop does not route through inherited Electron main, preload or `ContribController`.

Current ZN-owned desktop control plane:

- `apps/desktop/electron/zn-main.ts` — BrowserWindow, single-instance lifecycle, packaged runtime activation, resident/update IPC, navigation and `zn://` ownership;
- `apps/desktop/electron/zn-preload.ts` — intentional `window.znDesktop` bridge only;
- `apps/desktop/electron/zn-protocol.ts` — ZN-only deep-link parsing;
- `apps/desktop/electron/zn-shell.html` — minimal CSP-bound renderer document;
- `apps/desktop/src/zn/main.tsx` — independent React renderer root;
- `apps/desktop/src/zn/workbench.tsx` — content-first workbench;
- `apps/desktop/src/zn/state.ts` — bounded browser convenience cache only;
- `apps/desktop/src/zn/resident-client.ts` — direct ZN resident/update client;
- `apps/desktop/scripts/bundle-electron-main.mjs` — ZN-only active bundle entries.

The latest verified M5/M6 slice adds `agent/kernel/work.py` and makes work/thread continuity resident-backed:

```text
ZnWorkbench
→ ZN preload / IPC
→ resident work RPC
→ ResidentWorkLedger
→ same ZNResidentRuntime submit/event loop
→ durable work thread/messages/activity
→ resident snapshot back to workbench
```

This slice is native ZN product implementation, not an extraction from Hermes. It matters to the extraction ledger because it prevents browser state or an inherited desktop/session model from becoming the owner of work continuity.

Verified source baseline:

```text
0c3ba8e3c5b2c3450d9fd305f4b012d804994acd
```

CI:

```text
ZN Kernel / Python      success
Electron / TypeScript  success
Actions run             32573559233
```

Remaining workbench/product work includes:

- real workspace/folder association;
- contextual artifacts/files/diffs;
- invoked terminal/browser surfaces;
- provider/credential editor connected to ZN config/secure storage;
- richer resident activity/progress streaming;
- final product assets/visual polish/accessibility.

## 5. Python/runtime packaging extraction

Status: **M1 active packaged resident path is ZN-owned**.

Implemented:

- `runtime/python/pyproject.toml` — independent `znagent` distribution and `zn-resident` entrypoint;
- `runtime/python/zn_agent/resident.py` — ZN resident package entrypoint;
- `apps/desktop/scripts/stage-zn-runtime.mjs` — installs `runtime/python`, validates ZN runtime content and rejects `hermes_cli`;
- `apps/desktop/electron/zn-packaged-runtime.ts` — validates/materializes versioned ZN runtime payloads;
- `apps/desktop/electron/zn-resident-process.ts` — launches `python -m zn_agent.resident`.

Repository-root inherited source/metadata remains source quarry. It is not the active packaged resident distribution.

## 6. What remains inherited and why it is still debt

The active resident runtime and active desktop control plane are independent, but the repository is not yet a fully migrated ZN product.

Known remaining product/release debt includes:

- root repository distribution metadata/reference source remains inherited;
- `apps/desktop/package.json` still identifies the package/product/repository as Hermes and contains inherited scripts/dependencies;
- the package-level default Electron builder metadata still identifies Hermes;
- `apps/desktop/electron-builder.zn.yml` is ZN-branded but still registers both `zn` and `hermes` schemes;
- inactive inherited Electron/renderer/gateway/source trees remain as reference material;
- formal self-contained installer/clean-machine validation has not yet been rebuilt around the independent ZN desktop + runtime boundary.

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
E9  package independently bootable ZN product                 NEXT release-ownership milestone after M5/M6 product loop
E10 verify clean-machine install/upgrade/multi-OS release      NOT STARTED as product gate
```

“DONE” means the active ZN path no longer needs the old product control plane for that slice; it does not mean every optional reference feature was copied.

## 9. Immediate code target

The next work should continue from the owned runtime, desktop and resident-backed work foundations rather than adding compatibility wrappers.

Priority order:

1. add real workspace/folder association to resident-backed work;
2. add contextual artifact/file/diff presentation and terminal/browser surfaces only when invoked;
3. connect provider/settings editing to the ZN-owned configuration/credential boundary;
4. wire outbound channel attachments only through `OutboundMediaPathPolicy` when the resident has a concrete artifact/message egress path;
5. remove remaining package/release identity debt: make `apps/desktop/package.json` ZN-owned and ensure the formal builder registers only `zn://`;
6. rebuild formal self-contained packaging around the independent ZN desktop + `zn_agent` runtime;
7. only after that spend multi-OS CI/release budget on clean-machine, autostart and N → N+1 continuity validation.

Do not make installer polish the architecture driver before the remaining product loop and ownership metadata are corrected.

## 10. Completion test

The source-extraction phase is structurally complete for the active runtime/desktop slices when ZN can, from its own interfaces/state and active product control plane:

- consult a real external model without constructing the inherited full agent;
- execute local terminal/PTY work and observe the result;
- search/extract web evidence and feed it into `NativeWorldSense`;
- receive and deliver through at least one external communication channel;
- authorize local-file media egress through a ZN-owned policy before transport;
- launch its own Electron main/preload/renderer and `zn://` protocol;
- install/start its own `zn_agent` resident distribution;
- preserve desktop work/thread continuity in resident-owned state rather than inherited/session/browser authority;

without importing the old product CLI/agent/gateway/desktop as the control plane.

The current code has reached that structural ownership boundary for the active runtime/desktop slices. Remaining work is product completeness plus release/repository migration: workspaces/artifacts/settings, outbound-media transport wiring, package/release identity, clean formal installers, then supported-OS continuity validation.
