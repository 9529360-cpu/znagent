# ZN mature-source extraction plan

> Governing blueprint: [`../ZN.md`](../ZN.md)
>
> This document is the implementation contract for adopting mature capability code from the inherited/reference tree without embedding the inherited product control plane.
>
> Current checkpoint: 2026-08-22. Active development branch: `dev/zn-agent`.

## 1. Non-negotiable rule

ZN does **source-level extraction**, not product-level embedding.

When a mature implementation is useful, study the mechanism, extract/adapt the smallest coherent implementation behind ZN-owned interfaces/config/state/lifecycle, remove inherited product assumptions, add ZN behavior tests, switch the active caller, and maintain the result as ZN.

Inherited full-agent orchestration, gateway/session identity, Electron main/preload/renderer, CLI/config control plane, browser-session product ownership and inherited runtime packaging remain prohibited active dependencies.

## 2. Extraction standard

A capability is ZN-owned only when:

1. production entry begins at a ZN-owned boundary;
2. its public contract is defined by ZN;
3. ZN configuration/credentials own runtime choices;
4. ZN state/identity own continuity;
5. it can be tested without inherited product control planes;
6. it can be packaged without inherited product entrypoints;
7. active callers do not cross back into the old control plane.

Copying mature implementation is allowed. Cosmetic originality is not the goal; ownership transfer is.

The physical `agent/kernel/` source layout remains acceptable during migration because `runtime/python` packages the owned kernel under the installed `zn_agent` distribution. Namespace cleanup remains lower priority than product/release correctness.

## 3. Current extraction checkpoint

### 3.1 External cognition and credentials

Status: **ZN-native production path active; resident-owned provider/credential settings active**.

Owned components include OpenAI-compatible, Anthropic and Gemini cognitive resources, ZN resource routing/factory, atomic non-secret config persistence, credential references/OS keyring storage, sanitized provider-settings RPC and hot resource-plan reconfiguration.

Important invariants:

- production does not construct inherited `run_agent.AIAgent`;
- raw UI secrets are not persisted in YAML or returned to Electron;
- no insecure plaintext fallback is introduced when secure storage is unavailable;
- advanced routes are preserved rather than flattened;
- cognition reconfiguration does not replace resident identity/store/memory/life;
- missing provider credentials degrade to cognition unavailable rather than resident death.

### 3.2 Local terminal/body

Status: **ZN-native local terminal/PTTY active with resident contextual evidence**.

Foreground/background process execution, cwd continuity, cleanup, bounded output and interactive PTY lifecycle live behind ZN Body. `ResidentWorkLedger` derives bounded terminal artifacts from actual same-event body actions. Renderer does not become a terminal owner.

### 3.3 Web/world sense and browser finding

Status: **ZN-native web search/extract active; browser interaction not yet owned**.

Tavily/failover, Exa, Firecrawl and URL/network safety remain ZN-owned.

The mature inherited browser implementation was re-inspected before starting new browser work. Its useful mechanisms remain entangled with inherited config/plugin/session/provider ownership plus Node/Chromium/`agent-browser` lifecycle. The independent ZN resident distribution does not currently carry a clean resident browser-action seam. Therefore no browser facade was added and web-search evidence was not mislabeled as browser interaction.

Future browser work must first establish a real ZN-owned body/sense contract and packageable lifecycle, then expose contextual browser evidence only after actual invocation.

### 3.4 Communication channels and outbound media finding

Status: **resident-owned channel lifecycle active; Telegram text/inbound media active; outbound media still partial**.

`OutboundMediaPathPolicy` already provides ZN local-file authorization. Telegram `ChannelMessage` can represent attachments, but current resident delivery construction only emits response text and does not yet provide a structured resident-owned artifact/path nomination for egress.

Do not let the adapter infer upload authority from arbitrary text or local paths. Define explicit resident artifact/message egress nomination first, then route it through `OutboundMediaPathPolicy` and finally the Telegram media transport.

## 4. Independent desktop/product work

Status: **M4 complete; M5/M6 materially advanced; M7 formal package identity plus Linux unpacked package shape verified**.

Active desktop remains:

```text
ZnWorkbench
→ ZN preload / IPC
→ long-lived resident RPC
├─ ResidentWorkLedger → threads/workspace/WorkRun/progress/artifacts
└─ ProviderSettingsService → config/credential references/resources
→ SAME resident organism
```

### 4.1 Resident work/workspace/progress

Work identity/history, canonical workspace association and active `WorkRun` linkage are resident state. Browser localStorage is bounded convenience state only.

`work_start` durably accepts resident work before completion; the life loop can continue after desktop disconnect. `work_progress` samples actual resident event/working state, matching Thought, investigation and Body evidence. Finalization is idempotent and can happen after reconstruction.

### 4.2 Contextual artifacts

File/diff/terminal artifacts are bounded resident presentation records. Renderer receives them through resident work snapshots; it does not read arbitrary host files or own terminal execution. No permanent IDE file tree or xterm control plane was added.

### 4.3 Provider settings

Default provider/model/base URL and credential replacement/clear are resident RPC operations. Secrets stay resident-side, secure-store unavailability is explicit, advanced routes are preserved, and provider changes hot-apply to the same resident.

## 5. Python/runtime packaging ownership

Status: **M1 active packaged resident path is ZN-owned and has now survived real electron-builder packaging on Linux**.

The independent `runtime/python` distribution is `znagent`, with `zn_agent` installed package and `zn-resident` / `zn_agent.resident` entrypoints. Runtime staging/verification rejects `hermes_cli`.

The formal release chain stages `build/zn-runtime` before electron-builder by using portable CPython plus the independent ZN runtime distribution and a zero-model verification step. The formal desktop package explicitly includes that runtime payload.

A deliberately scoped Linux unpacked package smoke then exercised the real path:

```text
npm ci --ignore-scripts
→ stage-zn-runtime.mjs
→ portable Python + znagent
→ ZN build
→ electron-builder.zn.yml --linux --dir
→ locate packaged resources/zn-runtime
→ verify runtime manifest and ZN entrypoints
→ run packaged Python zero-model resident smoke
```

Result:

```text
ZN Formal Package Smoke  success
Actions run              32586304510
```

Verified in the unpacked app:

- executable name `ZN`;
- `resources/app.asar` present;
- `resources/zn-runtime/runtime.json` present with product/version/commit identity;
- packaged `zn_agent` resident/core entrypoints valid;
- packaged resident boots zero-model after packaging;
- inherited `install-stamp.json` absent;
- packaged `hermes_cli` absent.

The smoke workflow was temporary and was removed after verification.

## 6. Formal desktop package identity

Status: **active formal product/build identity transferred to ZN; actual Linux unpacked package verified; full multi-platform M7 artifact validation still pending**.

Verified package-identity source baseline:

```text
c0e8bb8563b323313304cc961ff07640d92d02cf
```

Final branch source verification after the temporary smoke workflow was removed:

```text
8c626fd44e7e0270e65fe1b3db629efa9350facf
ZN Kernel / Python      success
Electron / TypeScript  success
Actions run             32586385421
```

Implemented/verified:

- `apps/desktop/package.json` package/product/repository identity is ZN-owned (`zn-desktop`, `ZN`, ZN repository);
- default build metadata uses `ai.zn.desktop`, `ZN` executable/product and `ZN-*` artifacts;
- package-level protocols contain only `zn`;
- builder command explicitly selects `electron-builder.zn.yml`;
- `electron-builder.zn.yml` registers only `zn://` and includes `build/zn-runtime`;
- inherited install-stamp/bootstrap resource is removed from the active formal packaging path;
- Windows `afterPack`/`rcedit` stamps ZN product/company identity;
- rollback preservation defaults to `ZN.exe`;
- active macOS notarization temporary key paths use a ZN prefix;
- root npm lock workspace identity is synchronized to `zn-desktop` using npm's own lock generator;
- formal package/build-hook identity is protected by regression tests;
- Linux unpacked formal package shape and packaged runtime boot are verified against real electron-builder output.

The first normal CI attempt after renaming the package correctly failed because `package-lock.json` still contained the old workspace package/link name. A temporary one-shot workflow ran `npm install --package-lock-only --ignore-scripts`; npm changed only the desktop workspace name/link. That workflow was immediately removed. The corrected source then passed normal CI.

Important boundary: this closes the active **product/build identity seam** and verifies one real packaged application shape. It does not purge every inherited source/dependency name from the repository and does not yet prove every installer/OS continuity gate.

## 7. Remaining inherited/release debt

Still pending:

- actual installer-format artifact validation (Linux AppImage/deb/rpm and intended Windows/macOS artifacts) from the corrected package shape;
- clean-machine installation and resident continuity validation;
- OS-login autostart and N → N+1 upgrade validation;
- signing/notarization as configured release hardening;
- inactive inherited Electron/renderer/gateway/browser/source and dependency/script debt that is not on the active ZN control path;
- root inherited/reference package/distribution metadata until later repository migration.

These debts do not permit active callers to cross back into inherited control planes.

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
E8  remove active old-product control-plane imports           DONE for active resident + desktop
E9  package independently bootable ZN product                 IN PROGRESS; identity + Linux unpacked package/runtime boot verified
E10 verify clean-machine install/upgrade/multi-OS release      NOT STARTED as product gate
```

## 9. Immediate code target

Priority order:

1. keep M7 scoped and validate installer-format artifacts from the corrected ZN package shape only when they provide new evidence; do not prematurely launch the full M8 clean-machine matrix;
2. fix any active package-content/runtime-entrypoint debt exposed by real installer artifacts;
3. establish browser interaction only through a clean resident-owned body/sense seam, not inherited browser/session ownership;
4. define explicit resident artifact/message egress nomination before Telegram outbound attachment transport;
5. broaden artifact rendering/history only when concrete product output needs it;
6. after intended-platform M7 artifacts are genuinely valid, spend M8 CI budget on clean-machine, autostart and upgrade continuity.

## 10. Completion test

The current ownership/extraction boundary requires ZN to be able to:

- remain alive and useful without an external model;
- consult external cognition without inherited full-agent construction;
- securely own provider configuration/credentials;
- execute local terminal/PTTY movement;
- search/extract web evidence;
- preserve resident work/thread/workspace/active-run continuity;
- expose real ongoing resident progress;
- present bounded contextual artifacts without giving renderer body ownership;
- receive/deliver through resident-owned channel lifecycle and authorize future local-file egress through ZN policy;
- launch independent Electron main/preload/renderer and `zn://`;
- install/start the independent `zn_agent` runtime;
- package formal desktop product identity without inherited Hermes product/protocol/PE/bootstrap identity;
- preserve an independently bootable zero-model `zn_agent` resident inside a real packaged desktop application.

The active source now satisfies those structural boundaries for implemented slices. Remaining work is installer-format/platform validation, missing product capabilities that justify clean ZN-owned seams, and later clean-machine/repository migration.