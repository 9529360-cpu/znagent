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

The mature inherited browser implementation remains entangled with inherited config/plugin/session/provider ownership plus Node/Chromium/`agent-browser` lifecycle. The independent resident distribution does not currently carry a clean resident browser-action seam. Therefore no browser facade is claimed and web-search evidence is not mislabeled as browser interaction.

Future browser work must first establish a real ZN-owned body/sense contract and packageable lifecycle, then expose contextual browser evidence only after actual invocation.

### 3.4 Communication channels and outbound media finding

Status: **resident-owned channel lifecycle active; Telegram text/inbound media active; outbound media still partial**.

`OutboundMediaPathPolicy` already provides ZN local-file authorization. Telegram `ChannelMessage` can represent attachments, but current resident delivery construction does not yet provide structured resident-owned artifact/path nomination for egress.

Do not let the adapter infer upload authority from arbitrary text or local paths. Define explicit resident artifact/message egress nomination first, then route it through `OutboundMediaPathPolicy` and finally the Telegram media transport.

## 4. Independent desktop/product work

Status: **M4 complete; M5/M6 materially advanced; M7 Linux + Windows real installer evidence verified**.

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

Status: **M1 active packaged resident path is ZN-owned and has survived real Linux and Windows installer packaging**.

The independent `runtime/python` distribution is `znagent`, with `zn_agent` installed package and `zn-resident` / `zn_agent.resident` entrypoints. Runtime staging/verification rejects `hermes_cli`.

The formal release chain stages `build/zn-runtime` before electron-builder using portable CPython plus the independent ZN runtime distribution and a zero-model verification step. The formal desktop package explicitly includes that runtime payload.

### 5.1 Linux artifact evidence

Source commit `6219eaa61f6c444feb96864e149f886752b00ffe` built and extracted real AppImage/deb/rpm artifacts, then booted the resident zero-model from every extracted runtime. Run `32586833761` succeeded.

Verified Linux artifacts:

```text
ZN-0.17.0-linux-x86_64.AppImage  179M  e4b1548f630fcb376e22257c3e6cc3c22589dee55746d6f1951605cc2a906120
ZN-0.17.0-linux-amd64.deb         143M  3555059b606cf679b277e4f4452212c5ddaba7034aef9b9791d596adf8267606
ZN-0.17.0-linux-x86_64.rpm        117M  34bd11a006937d1746b2e487f742edc8cb6d9ec3da75da3d5475757db37c9d03
```

A later corrected AppImage desktop integration build at `46685b66ff1381cb0b41b1e0564cc62ca5e34467` proved generated `.desktop` filename/`StartupWMClass`/`Name=ZN`/`zn://` association while retaining the same independently bootable resident. Run `32587988440` succeeded.

### 5.2 Windows artifact evidence

Source commit:

```text
2e3cdb0ac893feca86325e19a058c455c906bfd7
```

Scoped real Windows validation:

```text
ZN Kernel / Python          success
Electron / TypeScript      success
ZN Windows Installer Smoke success
Actions run                 32590239803
```

Real chain:

```text
npm ci --ignore-scripts
→ stage-zn-runtime.mjs
→ portable Windows CPython + znagent
→ zero-model runtime staging verification
→ ZN build
→ electron-builder.zn.yml --win nsis msi
→ extract NSIS app payload with 7z
→ administratively extract MSI with synchronous msiexec
→ verify ZN.exe + app.asar + zn-runtime and reject hermes_cli
→ read actual PE ProductName/FileDescription/CompanyName
→ run verify-zn-packaged-runtime.mjs for both payloads
→ zero-model resident boot from both installer runtimes
```

Verified Windows artifacts:

```text
ZN-0.17.0-win-x64.exe  138.9 MB  d7716714599b87c125ab4ad5095fd3fb34bf2860e0fbdeebdece7b5316d05192
ZN-0.17.0-win-x64.msi  151.8 MB  bd4dc2cd6bee636fdb94941b02776e196c2c0808d0b13717ab6576ce4f32c01f
```

Both payloads reported:

```text
ProductName     ZN
FileDescription ZN
CompanyName     ZN Project
backend_root    .../Lib/site-packages
```

Both embedded residents booted zero-model successfully.

The real Windows artifact exercise exposed and closed three source-level defects rather than adding compatibility wrappers:

1. `uv` portable Windows CPython could leave a top-level alias/symlink unsuitable for installer materialization; runtime staging removes the matching alias and rejects remaining top-level aliases.
2. generic `site.getsitepackages()` assumptions did not identify the installed package root reliably for the portable Windows interpreter; staging derives `backend_root` from `importlib.util.find_spec('zn_agent')` and verifies the required resident entries there.
3. short-lived SQLite connections in `ZNLifeCore` were not all deterministically closed; life-state database operations now use `contextlib.closing`, with regression coverage proving pulse/snapshot connections are closed.

The one-purpose Windows installer workflow was deleted after successful evidence in `36feb0092126e47929d7239f8518a2ad68908454` so ordinary dev pushes do not keep paying Windows installer CI cost.

## 6. Formal desktop package identity

Status: **active formal product/build identity transferred to ZN; Linux and Windows intended artifact payloads verified; macOS artifact validation pending**.

Implemented/verified:

- `apps/desktop/package.json` package/product/repository identity is ZN-owned (`zn-desktop`, `ZN`, ZN repository);
- default build metadata uses `ai.zn.desktop`, `ZN` executable/product and `ZN-*` artifacts;
- package-level and builder protocols contain only `zn`;
- `electron-builder.zn.yml` includes `build/zn-runtime`;
- inherited install-stamp/bootstrap resource is removed from the active formal packaging path;
- Windows `afterPack` stamping writes ZN product/company identity;
- Windows NSIS and MSI extracted payloads preserve that identity and boot the embedded resident;
- Linux AppImage/deb/rpm extracted payloads preserve the ZN-owned app/runtime shape;
- Linux desktop launcher/window association is explicitly aligned to `ai.zn.desktop`;
- macOS builder metadata already targets `ZN.app`, `ai.zn.desktop`, DMG/ZIP and a ZN-owned notarization temp prefix, but the real DMG/ZIP payload evidence remains to be completed.

Important boundary: this closes active Linux and Windows **artifact content/runtime identity evidence**. It does not yet prove macOS artifacts or any M8 clean-machine/continuity gate, and it does not purge inactive inherited source/dependency names from the repository.

## 7. Remaining inherited/release debt

Still pending:

- real macOS DMG/ZIP artifact validation from the corrected package shape;
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
E9  package independently bootable ZN product                 IN PROGRESS; Linux + Windows real installer payloads verified
E10 verify clean-machine install/upgrade/multi-OS release      NOT STARTED as product gate
```

## 9. Immediate code target

Priority order:

1. validate real macOS DMG/ZIP artifacts from the corrected ZN package shape, scoped to package content/identity/runtime boot rather than full M8 clean-machine validation;
2. fix any active package-content/runtime-entrypoint/macOS integration debt exposed by those artifacts at the source boundary;
3. once intended Linux + Windows + macOS M7 artifacts are genuinely valid, stop installer-format churn and move deliberate release-validation budget to M8 clean-machine, autostart and N → N+1 continuity;
4. establish browser interaction only through a clean resident-owned body/sense seam, not inherited browser/session ownership;
5. define explicit resident artifact/message egress nomination before Telegram outbound attachment transport;
6. broaden artifact rendering/history only when concrete product output needs it.

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
- preserve an independently bootable zero-model `zn_agent` resident inside real Linux AppImage/deb/rpm and Windows NSIS/MSI installer payloads.

The active source satisfies those structural boundaries for implemented slices. Remaining M7 work is real macOS artifact evidence; remaining product work includes clean browser/egress seams only when justified; M8 and later release/repository migration remain deliberately separate.
