# ZN mature-source extraction plan

> Governing blueprint: [`../ZN.md`](../ZN.md)
>
> This document is the implementation contract for adopting mature capability code from the inherited/reference tree. It exists to prevent a recurring failure mode: packaging or calling an old product subsystem wholesale when ZN only needs the engineering mechanisms inside it.
>
> Current checkpoint: 2026-08-22. Active development branch: `dev/zn-agent`.

## 1. Non-negotiable rule

ZN does **source-level extraction**, not product-level embedding.

The reference tree is a library of solved engineering problems. When a mature implementation exists, study it, extract/adapt the smallest coherent mechanism behind a ZN-owned namespace/interface/config/state/lifecycle, remove inherited product assumptions, add ZN tests, switch the active ZN caller, and maintain the result as ZN.

Incorrect shortcuts remain prohibited: inherited full-agent construction, inherited gateway/session ownership, inherited Electron main/preload/renderer, inherited CLI/config as the active product control plane, or packaging the inherited Python product under a ZN installer.

## 2. Extraction standard

A capability is considered ZN-owned only when:

1. production entry begins at a ZN-owned boundary;
2. its public contract is defined by ZN;
3. ZN configuration/credentials own runtime choices;
4. ZN state/session/identity objects own continuity;
5. it can be tested without inherited CLI/agent/gateway/desktop control planes;
6. it can be packaged without inherited product entrypoints;
7. active callers do not cross back into the old control plane.

Copying mature implementation is allowed and often preferable. Cosmetic originality is not a goal. Ownership transfer is.

The current physical source layout under `agent/kernel/` remains acceptable during migration. `runtime/python/pyproject.toml` installs this ZN-owned kernel under `zn_agent.core`.

## 3. Current extraction checkpoint

The original resident/runtime/desktop control-plane seams have been cut. Current M5/M6 work is primarily native ZN product development rather than Hermes extraction.

### 3.1 External cognitive/model resources and credential ownership

Status: **ZN-native production path active; resident-owned default provider/credential settings active**.

Implemented:

- `agent/kernel/cognitive_resource.py` — bounded `CognitiveResource` / `CognitiveIncrement` and OpenAI-compatible routing;
- `agent/kernel/anthropic_resource.py` — native Anthropic Messages behavior;
- `agent/kernel/gemini_resource.py` — native Gemini behavior;
- `agent/kernel/cognitive_factory.py` — ZN resource selection;
- `agent/kernel/provider_bridge.py` — resident construction and hot resource-plan application;
- `agent/kernel/config.py` — ZN-owned load plus atomic non-secret persistence;
- `agent/kernel/credentials.py` — ZN credential references plus OS-keyring-backed secure store;
- `agent/kernel/provider_settings.py` — sanitized resident settings read/update boundary;
- `agent/kernel/worker.py` — generic worker contract and explicit zero-model unavailability.

Provider settings ownership flow:

```text
ZnWorkbench Settings
→ ZN preload / resident IPC
→ provider_settings_update
→ ProviderSettingsService
→ non-secret config.yaml + secure credential reference
→ resident OS credential backend
→ transient credential materialization
→ ZN cognitive resource plan
→ SAME ZNKernelRuntime / SAME resident identity
```

Important invariants:

- raw UI API keys are not persisted to YAML;
- stored secrets are never returned through RPC;
- Electron does not own credential persistence;
- packaged `znagent` carries `keyring==25.7.0`;
- no insecure plaintext fallback exists when host secure storage is unavailable;
- environment variables remain valid external inputs;
- advanced routes are preserved rather than flattened;
- hot resource reconfiguration does not replace resident identity/store/memory/life;
- in-flight work retains the cognition resource snapshot it began with;
- invalid/missing external credentials degrade to cognition unavailable rather than resident death.

### 3.2 Local terminal / computer body

Status: **ZN-native local terminal/PTTY path active; resident work has contextual terminal evidence**.

`agent/kernel/terminal.py` and `agent/kernel/pty.py` own local foreground/background execution, cwd continuity, cleanup, bounded output, interactive PTY stdin/resize and completed-session reclamation.

`ResidentWorkLedger` converts actual same-event terminal/body records into bounded `WorkArtifact(kind="terminal")` evidence. Execution remains in ZN Body; renderer receives evidence only and does not instantiate a terminal control plane.

Optional Docker/SSH/cloud backends remain demand-driven.

### 3.3 Web search / world sense

Status: **ZN-native production path active**.

Tavily/failover, Exa, Firecrawl, URL/network target safety and `NativeWorldSense` routing are ZN-owned.

Browser automation/rendering remains a separate body/sense requirement. Current active `agent/kernel` has no resident-owned browser interaction action/module, so a browser context surface must not be invented by relabeling search results or mounting inherited browser UI.

### 3.4 Communication channels

Status: **resident-owned lifecycle active; Telegram first transport**.

Core ZN contracts include normalized channel events, deterministic durable ingress, resident-owned supervision, durable delivery/retry state, Telegram polling/checkpoints/network transport, bounded inbound media and `OutboundMediaPathPolicy` for local-file egress authorization.

Telegram outbound media still must pass through `OutboundMediaPathPolicy` when a concrete artifact/message egress flow exists.

## 4. Independent desktop and current native product work

Status: **M4 ownership complete; M5/M6 materially advanced with durable work/workspace/artifacts/provider settings/ongoing progress active**.

Current ZN-owned control plane includes:

- `apps/desktop/electron/zn-main.ts` — BrowserWindow, single-instance, resident/update/workspace IPC, navigation and `zn://` ownership;
- `apps/desktop/electron/zn-preload.ts` — intentional ZN bridge only;
- `apps/desktop/electron/zn-protocol.ts` — ZN deep-link parser;
- `apps/desktop/electron/zn-workspace-ipc.ts` — native folder selection/canonicalization;
- `apps/desktop/src/zn/main.tsx` — independent React root;
- `apps/desktop/src/zn/workbench.tsx` — content-first workbench, resident progress, contextual artifacts and provider editor;
- `apps/desktop/src/zn/state.ts` — bounded non-authoritative convenience state;
- `apps/desktop/src/zn/resident-client.ts` — resident/work/provider/update client;
- `apps/desktop/scripts/bundle-electron-main.mjs` — ZN-only active bundle entries.

Current owned flow:

```text
ZnWorkbench
→ ZN preload / IPC
→ long-lived resident RPC
├─ ResidentWorkLedger → thread/workspace/WorkRun/progress/artifacts
└─ ProviderSettingsService → config/credential references/resources
→ SAME resident organism
```

### 4.1 Resident-backed work/workspace ownership

Work/thread identity and message history are resident-owned. Browser `localStorage` is only bounded fallback/cache.

Workspace association is resident product state: Electron owns OS folder picking/canonicalization, resident re-verifies it, and durable work context propagates canonical workspace/workdir into native Git/body movement.

### 4.2 Durable active work and progress ownership

The latest M6 slice removes another desktop-lifetime dependency:

```text
renderer work_start
→ ResidentWorkLedger.start
→ durable user message + WorkRun
→ resident enqueue
→ desktop may disconnect
→ SAME resident life loop continues event
→ work_progress samples resident event/working/thought/investigation/body state
→ terminal outcome
→ idempotent resident finalization
→ durable ZN/activity/artifacts
→ renderer rehydrates final thread
```

Important invariants:

- the Electron request does not own event completion;
- active event/thread linkage survives resident reconstruction;
- completed detached work can be finalized after restart/reconnect;
- deterministic final message IDs prevent duplicate finalization;
- one work thread rejects parallel active events;
- progress truth comes from resident event/working state, current matching Thought, investigation and Body evidence;
- progress is not stored as browser authority or simulated by the renderer;
- polling is currently a transport choice, not an ownership boundary.

### 4.3 Contextual artifacts

File/diff/terminal presentation is native ZN product work rather than inherited desktop session UI. Artifacts are bounded, resident-owned and presented only in optional context UI. Renderer does not own host filesystem or terminal execution.

Current artifact support remains intentionally partial. General rendered documents, binary previews, browser interaction artifacts and richer historical browsing remain future work.

### 4.4 Provider settings UI

Default provider/model/base URL and credential replacement/clear are resident RPC operations. Secure-store availability is explicit; secrets are not returned to the renderer; simple settings do not flatten advanced route configuration; provider changes hot-apply to the same resident.

Verified source baseline:

```text
2157283a4e3392ec34f22c100fd0b238805be9b6
```

Key source commits:

```text
dd68e61c91e7aa222fba2f9b2c0516bbb2a190b8  feat: add resident-owned provider settings
89d24027249e1a13b6f6b5e9639127f0fc5f4ddc  feat: persist active work runs [skip ci]
37e662433f958e298d3f2d337af9935c4303a370  feat: expose resident work progress
2157283a4e3392ec34f22c100fd0b238805be9b6  test: isolate resident progress cache assertion
```

CI:

```text
ZN Kernel / Python      success
Electron / TypeScript  success
Actions run             32584154366
```

The earlier provider-settings source was independently verified by Actions run `32583007696`.

Remaining workbench/product work:

- real resident browser interaction/context only when a ZN-owned body/sense seam is extracted;
- broader artifact rendering/history where concrete work requires it;
- final accessibility/keyboard/visual polish.

## 5. Python/runtime packaging extraction

Status: **M1 active packaged resident path is ZN-owned**.

Implemented independent `runtime/python` `znagent`, `zn-resident` / `zn_agent.resident`, ZN-owned runtime staging/verification, Electron launch through `python -m zn_agent.resident`, and resident secure-credential backend dependency.

Repository-root inherited metadata/source remains reference quarry, not the packaged resident.

## 6. What remains inherited and why it is still debt

Known product/release debt includes:

- root inherited/reference distribution metadata/source;
- `apps/desktop/package.json` still identifies Hermes product/repository/build history and retains inherited dependency/script debt;
- package-level default builder metadata remains inherited;
- `apps/desktop/electron-builder.zn.yml` still registers both `zn` and `hermes`;
- inactive inherited Electron/renderer/gateway/browser/source trees remain reference material;
- formal clean installers have not yet been rebuilt and clean-machine verified around only independent ZN desktop + runtime.

These are migration debts, not permission to route active paths back through inherited control planes.

## 7. What not to extract

Do not blindly migrate inherited branding/paths, old CLI UX, full-agent orchestration/prompt ownership, desktop shell/UI, gateway/session identity, vendor/subscription features without a concrete requirement, every optional backend at once, compatibility shims whose only consumer is the old product, or snapshot/name tests whose purpose is preserving old identity.

The reference implementation is a quarry, not a dependency graph to preserve.

## 8. Extraction ledger

```text
E0  document extraction boundary                              DONE
E1  establish ZN-native resource/channel/body interfaces      DONE
E2  extract main external model transports/providers          DONE for active provider families
E3  extract local terminal body/PTTY lifecycle                DONE
E4  extract web search/extract providers + URL safety         DONE for active provider set
E5  extract communication framework + first channel           DONE for Telegram text/inbound media; outbound media pending
E6  switch resident production callers to ZN-owned modules    DONE for cognition/terminal/web/channel lifecycle
E7  build independent ZN Electron main/preload/UI foundation  DONE
E8  remove active old-product control-plane imports           DONE for active resident + desktop; packaging metadata debt remains
E9  package independently bootable ZN product                 NEXT release-ownership milestone after remaining M5/M6 loop
E10 verify clean-machine install/upgrade/multi-OS release      NOT STARTED as product gate
```

## 9. Immediate code target

Continue from the owned runtime/desktop and resident-backed work/workspace/artifact/provider/progress foundations.

Priority order:

1. inspect mature browser mechanisms and extract a real resident-owned browser body/sense seam only when it can be isolated from inherited browser/session ownership; expose contextual browser evidence only after actual invocation;
2. broaden artifact rendering/history only where concrete work output requires it;
3. wire outbound channel attachments only through `OutboundMediaPathPolicy` when a concrete resident artifact/message egress path exists;
4. make `apps/desktop/package.json` fully ZN-owned and ensure formal builder registers only `zn://`;
5. rebuild formal self-contained packaging around independent ZN desktop + `zn_agent` runtime;
6. only then spend multi-OS CI/release budget on clean-machine, autostart and N → N+1 continuity validation.

Do not let installer polish become the architecture driver before remaining product-loop and package identity work is corrected.

## 10. Completion test

The active source-extraction boundary is structurally satisfied when ZN can, through its own interfaces/state/control plane:

- consult external cognition without constructing inherited full agent;
- persist provider configuration and securely reference credentials without inherited CLI/desktop ownership;
- remain alive when external cognition is unavailable or misconfigured;
- execute local terminal/PTTY work;
- search/extract web evidence;
- receive/deliver through a resident-owned external channel;
- authorize local-file media egress through ZN policy;
- launch its own Electron main/preload/renderer and `zn://` protocol;
- install/start its own `zn_agent` resident distribution;
- preserve work/thread/workspace continuity in resident state;
- preserve active accepted work across desktop absence and expose resident-derived progress;
- persist/present bounded contextual file/diff/terminal evidence without giving renderer body ownership;

without importing inherited CLI/agent/gateway/desktop as the active product control plane.

Remaining work is product completeness plus release/repository migration: real browser interaction/context when justified, broader artifacts where needed, outbound-media transport, package/release identity, clean formal installers and supported-OS continuity validation.