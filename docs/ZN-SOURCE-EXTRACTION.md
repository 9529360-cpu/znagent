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

Status: **M4 complete; M5/M6 materially advanced; M7 formal identity plus Linux unpacked and AppImage/deb/rpm payload validation active**.

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

Status: **M1 active packaged resident path is ZN-owned and has survived real electron-builder packaging plus extraction from actual Linux installer formats**.

The independent `runtime/python` distribution is `znagent`, with `zn_agent` installed package and `zn-resident` / `zn_agent.resident` entrypoints. Runtime staging/verification rejects `hermes_cli`.

The formal release chain stages `build/zn-runtime` before electron-builder by using portable CPython plus the independent ZN runtime distribution and a zero-model verification step. The formal desktop package explicitly includes that runtime payload.

The earlier deliberately scoped Linux unpacked package smoke exercised:

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

That verified executable `ZN`, `resources/app.asar`, `resources/zn-runtime/runtime.json`, valid resident/core entrypoints, zero-model boot, no inherited `install-stamp.json` and no packaged `hermes_cli` in the unpacked app. The smoke workflow was temporary and was removed after verification.

A second deliberately scoped validation then built and inspected the actual Linux installer formats from source commit:

```text
6219eaa61f6c444feb96864e149f886752b00ffe
```

Real chain:

```text
npm ci --ignore-scripts
→ stage-zn-runtime.mjs
→ portable Python + znagent
→ ZN build
→ electron-builder.zn.yml --linux AppImage deb rpm
→ AppImage --appimage-extract
→ dpkg-deb -x
→ rpm2cpio | cpio
→ verify app.asar + zn-runtime + ZN executable and reject inherited payloads
→ run verify-zn-packaged-runtime.mjs across all extracted installer trees
→ zero-model resident boot from every extracted installer runtime
```

Result:

```text
ZN Linux Installer Smoke  success
Actions run                32586833761
```

Verified artifact evidence:

```text
ZN-0.17.0-linux-x86_64.AppImage  179M  e4b1548f630fcb376e22257c3e6cc3c22589dee55746d6f1951605cc2a906120
ZN-0.17.0-linux-amd64.deb         143M  3555059b606cf679b277e4f4452212c5ddaba7034aef9b9791d596adf8267606
ZN-0.17.0-linux-x86_64.rpm        117M  34bd11a006937d1746b2e487f742edc8cb6d9ec3da75da3d5475757db37c9d03
```

The packaged resident booted from the AppImage SquashFS payload, deb `/opt/ZN/resources/zn-runtime`, and rpm `/opt/ZN/resources/zn-runtime`. The temporary installer-smoke workflow was deleted immediately after success in `b138d917a131c61977bf6a226f97d5c54a071ec9`; no product source changed in that cleanup.

## 6. Formal desktop package identity

Status: **active formal product/build identity transferred to ZN; Linux unpacked plus actual AppImage/deb/rpm package payloads verified; full intended-platform M7 validation still pending**.

Verified package-identity source baseline:

```text
c0e8bb8563b323313304cc961ff07640d92d02cf
```

Prior final branch source verification after the unpacked-package smoke workflow was removed:

```text
8c626fd44e7e0270e65fe1b3db629efa9350facf
ZN Kernel / Python      success
Electron / TypeScript  success
Actions run             32586385421
```

Linux installer-validation source verification:

```text
6219eaa61f6c444feb96864e149f886752b00ffe
ZN Kernel / Python       success
Electron / TypeScript   success
ZN Linux Installer Smoke success
normal CI run            32586833739
installer smoke run      32586833761
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
- Linux unpacked formal package shape and packaged runtime boot are verified against real electron-builder output;
- Linux AppImage, deb and rpm artifacts have each been extracted and shown to preserve the ZN executable/app.asar/self-contained runtime shape;
- the self-contained resident booted zero-model from the runtime embedded in every tested Linux installer format.

The installer build emitted a non-failing electron-builder warning that Linux `desktopName` is not explicitly set, so `.desktop` / WM_CLASS association is not yet proven. This is Linux package integration debt to close before release-ready status; it does not change the successful runtime ownership/boot result.

The first normal CI attempt after renaming the package correctly failed because `package-lock.json` still contained the old workspace package/link name. A temporary one-shot workflow ran `npm install --package-lock-only --ignore-scripts`; npm changed only the desktop workspace name/link. That workflow was immediately removed. The corrected source then passed normal CI.

Important boundary: this closes the active **product/build identity seam** and now proves actual Linux installer payloads preserve the independently bootable ZN runtime. It does not purge every inherited source/dependency name from the repository and does not yet prove Windows/macOS installer or M8 continuity gates.

## 7. Remaining inherited/release debt

Still pending:

- explicit Linux `.desktop` / WM_CLASS association cleanup/verification (`desktopName` / `linux.syncDesktopName`);
- intended Windows/macOS installer artifact validation from the corrected package shape;
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
E9  package independently bootable ZN product                 IN PROGRESS; identity + Linux unpacked + AppImage/deb/rpm runtime boot verified
E10 verify clean-machine install/upgrade/multi-OS release      NOT STARTED as product gate
```

## 9. Immediate code target

Priority order:

1. keep M7 scoped and close Linux installer integration debt exposed by real artifacts, especially explicit desktop-file/WM_CLASS association; do not prematurely launch the full M8 clean-machine matrix;
2. validate intended Windows/macOS installer artifacts only when they provide enough additional M7 evidence to justify the CI cost;
3. fix any active package-content/runtime-entrypoint debt exposed by later real installer artifacts;
4. establish browser interaction only through a clean resident-owned body/sense seam, not inherited browser/session ownership;
5. define explicit resident artifact/message egress nomination before Telegram outbound attachment transport;
6. broaden artifact rendering/history only when concrete product output needs it;
7. after intended-platform M7 artifacts are genuinely valid, spend M8 CI budget on clean-machine, autostart and upgrade continuity.

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
- preserve an independently bootable zero-model `zn_agent` resident inside a real packaged desktop application;
- preserve and boot that same ZN-owned resident runtime after extraction from real AppImage, deb and rpm artifacts.

The active source now satisfies those structural boundaries for implemented slices. Remaining work is intended-platform installer validation/integration polish, missing product capabilities that justify clean ZN-owned seams, and later clean-machine/repository migration.