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

### 3.1 External cognitive/model resources and credential ownership

Status: **ZN-native production path active; resident-owned default provider/credential settings active**.

Implemented:

- `agent/kernel/cognitive_resource.py` — bounded `CognitiveResource` / `CognitiveIncrement` and OpenAI-compatible transport/routing;
- `agent/kernel/anthropic_resource.py` — native Anthropic Messages behavior;
- `agent/kernel/gemini_resource.py` — native Gemini `generateContent` behavior;
- `agent/kernel/cognitive_factory.py` — ZN resource selection;
- `agent/kernel/provider_bridge.py` — resident construction and hot resource-plan application from ZN config/resources;
- `agent/kernel/config.py` — ZN-owned load plus atomic non-secret config persistence;
- `agent/kernel/credentials.py` — ZN credential references plus OS-keyring-backed secure store;
- `agent/kernel/provider_settings.py` — sanitized resident settings read/update boundary;
- `agent/kernel/worker.py` — generic worker contract and explicit zero-model unavailability.

The production kernel does not construct `run_agent.AIAgent` and the provider editor does not call inherited CLI/config code.

Latest provider-settings ownership flow:

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

Important invariants now enforced:

- raw UI-entered API keys are never persisted to ZN YAML by the settings flow;
- stored secrets are never returned through provider-settings RPC;
- Electron does not own credential persistence through `safeStorage`, keytar or an inherited desktop store;
- packaged `znagent` includes `keyring==25.7.0` so the long-lived Python resident can access appropriate host secure storage while no desktop window exists;
- no insecure plaintext fallback is used when the host secure backend is unavailable;
- provider-standard environment variables remain valid external configuration inputs;
- secure credential references survive resident reconstruction when the host store is available;
- advanced `zn_kernel.routes` are preserved rather than flattened by the simple default-provider editor;
- cognition resource reconfiguration replaces only the router/worker plan; identity, store, SelfModel, resident life, Will and memory are not recreated;
- an in-flight kernel goal keeps the router/factory snapshot it started with; later goals see the new resource plan;
- missing/invalid external provider credentials degrade to explicit cognition-unavailable behavior rather than preventing resident boot.

Remaining provider-specific extraction is demand-driven and must not reconstruct a prompt-owning full-agent loop inside the resource layer.

### 3.2 Local terminal / computer body

Status: **ZN-native local terminal and PTY path active; resident work has contextual terminal evidence**.

Implemented in `agent/kernel/terminal.py` and `agent/kernel/pty.py`: cwd continuity, shell discovery, foreground/background execution, timeout/process-tree cleanup, bounded output, environment isolation, POSIX/Windows PTY bridges, interactive stdin/resize lifecycle and completed-session reclamation.

`ResidentWorkLedger` turns actual same-event terminal/body action records into bounded `WorkArtifact(kind="terminal")` evidence. Command/PTTY execution remains in ZN Body; renderer receives only resident-backed evidence and does not instantiate a permanent terminal owner.

Optional Docker/SSH/cloud backends remain demand-driven. Do not restore inherited gateway/session ownership to obtain them.

### 3.3 Web search / world sense

Status: **ZN-native production path active**.

Implemented ZN web resource boundary, Tavily/failover, Exa, Firecrawl, URL/network target safety and `NativeWorldSense` routing.

Browser automation/rendering remains a separate body/sense requirement. Current `agent/kernel` has no resident-owned browser interaction module/action, so a browser contextual surface must not be invented by relabeling search results or inherited browser UI.

### 3.4 Communication channels

Status: **resident-owned lifecycle active; Telegram first transport**.

Core ZN contracts/lifecycle include normalized channel contracts, deterministic durable ingress, resident-owned channel supervisor, durable delivery/retry state, Telegram polling/checkpoints/network transport, bounded inbound media and `OutboundMediaPathPolicy` for local-file egress authorization.

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

Status: **M4 ownership complete; M5 materially advanced; M6 partial with resident work/workspace/file-diff/terminal context and provider settings active**.

The active desktop no longer routes through inherited Electron main, preload or `ContribController`.

Current ZN-owned control plane includes:

- `apps/desktop/electron/zn-main.ts` — BrowserWindow, single-instance lifecycle, packaged runtime activation, resident/update/workspace IPC, navigation and `zn://` ownership;
- `apps/desktop/electron/zn-preload.ts` — intentional ZN bridge only;
- `apps/desktop/electron/zn-protocol.ts` — ZN deep-link parser;
- `apps/desktop/electron/zn-workspace-ipc.ts` — native folder selection/canonicalization;
- `apps/desktop/src/zn/main.tsx` — independent React root;
- `apps/desktop/src/zn/workbench.tsx` — content-first workbench, contextual artifact surface and provider editor;
- `apps/desktop/src/zn/state.ts` — bounded non-authoritative browser convenience state;
- `apps/desktop/src/zn/resident-client.ts` — resident/workspace/provider/update client;
- `apps/desktop/scripts/bundle-electron-main.mjs` — ZN-only active bundle entries.

Current owned flow:

```text
ZnWorkbench
→ ZN preload / IPC
→ long-lived resident RPC
├─ ResidentWorkLedger → thread/workspace/artifacts
└─ ProviderSettingsService → config/credential references/resources
→ SAME resident organism
```

### 4.1 Resident-backed work/workspace ownership

Work/thread identity and message history are resident-owned. Browser `localStorage` is only a bounded fallback/cache.

Workspace association remains native ZN product state: renderer supplies only thread identity, Electron owns OS folder picking/canonicalization, resident re-verifies the directory and durable work state propagates canonical `workspace_path` / `workdir` into native Git/body context.

### 4.2 Contextual artifacts

File/diff/terminal presentation is native ZN product work rather than inherited desktop session UI.

Implemented:

- bounded durable `WorkArtifact` records;
- file/write re-observation inside canonical workspace;
- dirty-workspace changed-file and current-diff context;
- symlink/path escape rejection;
- actual-invocation terminal artifacts;
- bounded resident RPC/browser hydration;
- optional right context panel only, with no permanent file tree or xterm control plane.

Current artifact support remains intentionally partial. General rendered documents, binary previews, browser interaction artifacts and richer historical browsing remain future product work.

### 4.3 Provider settings UI

Provider configuration UI is now native ZN product work rather than an inherited CLI/desktop settings wrapper.

Implemented and CI-verified:

- default provider/model/base-URL editing through resident RPC;
- transient password input for optional credential replacement;
- credential presence/source/backend status only returns to renderer;
- secure-store unavailability is explicit rather than silently writing plaintext;
- simple editor refuses to overwrite advanced route configuration;
- provider saves hot-apply to the current resident rather than restarting/replacing it;
- renderer state/cache does not become credential storage.

Verified source baseline:

```text
dd68e61c91e7aa222fba2f9b2c0516bbb2a190b8
```

Key source commit:

```text
dd68e61c91e7aa222fba2f9b2c0516bbb2a190b8  feat: add resident-owned provider settings
```

CI:

```text
ZN Kernel / Python      success
Electron / TypeScript  success
Actions run             32583007696
```

Remaining workbench/product work:

- richer ongoing activity/progress delivery while work is running;
- contextual browser surface only after a real resident browser interaction seam exists;
- broader artifact types/history where concrete output requires them;
- final accessibility/keyboard/visual polish.

## 5. Python/runtime packaging extraction

Status: **M1 active packaged resident path is ZN-owned**.

Implemented:

- independent `runtime/python` `znagent` distribution;
- `zn-resident` / `zn_agent.resident` entrypoint;
- runtime staging installs the ZN project and rejects `hermes_cli`;
- packaged-runtime materialization/verification is ZN-owned;
- Electron launches `python -m zn_agent.resident`;
- the resident runtime distribution now carries its secure credential backend dependency rather than relying on an Electron-only secret store.

Repository-root inherited metadata/source remains reference quarry, not the packaged resident.

## 6. What remains inherited and why it is still debt

Known product/release debt includes:

- root inherited/reference distribution metadata/source;
- `apps/desktop/package.json` still identifies Hermes product/repository/build history and retains inherited dependency/script debt;
- package-level default builder metadata remains inherited;
- `apps/desktop/electron-builder.zn.yml` still registers both `zn` and `hermes`;
- inactive inherited Electron/renderer/gateway/browser/source trees remain reference material;
- formal clean installers have not yet been rebuilt and clean-machine verified around only the independent ZN desktop + runtime.

These are migration debts, not permission to route active ZN paths back through inherited control planes.

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
E5  extract communication framework + first channel           DONE for Telegram text/inbound media; outbound media transport pending
E6  switch resident production callers to ZN-owned modules    DONE for cognition/terminal/web/channel lifecycle
E7  build independent ZN Electron main/preload/UI foundation  DONE
E8  remove active old-product control-plane imports           DONE for active resident + desktop; packaging metadata debt remains
E9  package independently bootable ZN product                 NEXT release-ownership milestone after remaining M5/M6 product loop
E10 verify clean-machine install/upgrade/multi-OS release      NOT STARTED as product gate
```

“DONE” means the active ZN path no longer needs the inherited control plane for that capability. It does not mean every optional reference feature was copied.

## 9. Immediate code target

Continue from the owned runtime/desktop and resident-backed work/workspace/artifact/provider-settings foundations.

Priority order:

1. improve resident progress/activity delivery so long-running work can expose meaningful ongoing state rather than only final snapshots;
2. add browser body/sense interaction and a contextual browser surface only when there is a concrete ZN product need; do not route the active product through inherited browser/session ownership;
3. broaden artifact rendering/history only where concrete work output requires it;
4. wire outbound channel attachments only through `OutboundMediaPathPolicy` when a concrete resident artifact/message egress path exists;
5. make `apps/desktop/package.json` fully ZN-owned and ensure formal builder registers only `zn://`;
6. rebuild formal self-contained packaging around independent ZN desktop + `zn_agent` runtime;
7. only then spend multi-OS CI/release budget on clean-machine, autostart and N → N+1 continuity validation.

Do not let installer polish become the architecture driver before the remaining product loop and package identity are corrected.

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
- preserve desktop work/thread/workspace continuity in resident state;
- persist/present bounded contextual file/diff/terminal evidence without giving renderer body ownership;

without importing inherited CLI/agent/gateway/desktop as the active product control plane.

The current code has reached that structural ownership boundary for the active runtime/desktop/provider-settings slices. Remaining work is product completeness plus release/repository migration: richer progress, real browser interaction/context when justified, broader artifacts where needed, outbound-media transport, package/release identity, clean formal installers and supported-OS continuity validation.
