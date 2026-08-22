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

Tavily/failover, Exa, Firecrawl and URL/network safety remain ZN-owned. The mature inherited browser implementation remains entangled with inherited config/plugin/session/provider ownership plus Node/Chromium/`agent-browser` lifecycle. Future browser work must first establish a real ZN-owned body/sense contract and packageable lifecycle.

### 3.4 Communication channels and outbound media finding

Status: **resident-owned channel lifecycle active; Telegram text/inbound media active; outbound media still partial**.

`OutboundMediaPathPolicy` provides ZN local-file authorization. Current resident delivery still lacks explicit structured resident-owned artifact/path nomination for egress; adapters must not infer upload authority from arbitrary text or local paths.

## 4. Independent desktop/product work

Status: **M4 complete; M5/M6 materially advanced; M7 artifact evidence exists on Linux x86_64, Windows x64 and macOS arm64; M8 now has Linux amd64 deb fresh-install and installed autostart continuity proofs**.

Active desktop remains:

```text
ZnWorkbench
→ ZN preload / IPC
→ long-lived resident RPC
├─ ResidentWorkLedger → threads/workspace/WorkRun/progress/artifacts
└─ ProviderSettingsService → config/credential references/resources
→ SAME resident organism
```

Work identity/history, canonical workspace association and active `WorkRun` linkage are resident state. File/diff/terminal artifacts are bounded resident presentation records. Provider configuration and credential references are resident-owned. Browser localStorage remains bounded convenience state only.

## 5. Python/runtime packaging ownership

Status: **M1 active packaged resident path is ZN-owned; real Linux/Windows/macOS package artifacts and fresh Linux install/autostart evidence preserve that ownership**.

The independent `runtime/python` distribution is `znagent`, with `zn_agent` installed package and `zn-resident` / `zn_agent.resident` entrypoints. Runtime staging/verification rejects `hermes_cli`.

The formal release chain stages `build/zn-runtime` before electron-builder using portable CPython plus the independent ZN runtime distribution and a zero-model verification step. The formal desktop package explicitly includes that runtime payload.

### 5.1 Linux artifact evidence

Source `6219eaa61f6c444feb96864e149f886752b00ffe`; run `32586833761` built/extracted real AppImage/deb/rpm artifacts and booted the resident zero-model from every extracted runtime.

```text
ZN-0.17.0-linux-x86_64.AppImage  179M  e4b1548f630fcb376e22257c3e6cc3c22589dee55746d6f1951605cc2a906120
ZN-0.17.0-linux-amd64.deb         143M  3555059b606cf679b277e4f4452212c5ddaba7034aef9b9791d596adf8267606
ZN-0.17.0-linux-x86_64.rpm        117M  34bd11a006937d1746b2e487f742edc8cb6d9ec3da75da3d5475757db37c9d03
```

Corrected AppImage desktop integration source `46685b66ff1381cb0b41b1e0564cc62ca5e34467`; run `32587988440` proved generated `.desktop` filename/`StartupWMClass`/`Name=ZN`/`zn://` association.

### 5.2 Windows artifact evidence

Source `2e3cdb0ac893feca86325e19a058c455c906bfd7`; scoped run `32590239803` succeeded alongside normal Kernel/Python and Electron/TypeScript CI.

```text
ZN-0.17.0-win-x64.exe  138.9 MB  d7716714599b87c125ab4ad5095fd3fb34bf2860e0fbdeebdece7b5316d05192
ZN-0.17.0-win-x64.msi  151.8 MB  bd4dc2cd6bee636fdb94941b02776e196c2c0808d0b13717ab6576ce4f32c01f
```

Both installer payloads preserved ZN app/runtime resources, rejected `hermes_cli`, reported `ProductName=ZN`, `FileDescription=ZN`, `CompanyName=ZN Project`, and booted the embedded resident zero-model.

The Windows exercise closed source-level defects in portable-Python alias handling, backend-root discovery from installed `zn_agent`, and deterministic `ZNLifeCore` SQLite connection closure. The temporary workflow was removed in `36feb0092126e47929d7239f8518a2ad68908454`.

### 5.3 macOS artifact evidence

Source `518d233eafa39b2d12f2de5835a8c8c1ab7529ab`; run `32591343670` on `macos-26-arm64` succeeded.

```text
ZN-0.17.0-mac-arm64.dmg  160M  5e1b3b6cd538fcf0605c3be27d0513f551f48614dff865a984e281b52d8459b9
ZN-0.17.0-mac-arm64.zip  160M  416f6fbcde0477db6b201b1f8bcf2fbb2820d1e67f145c4a09bc24535ba72133
```

Both real extracted app bundles proved `CFBundleIdentifier=ai.zn.desktop`, ZN display/name/executable identity, only `[zn]` URL schemes, and zero-model resident boot from the embedded runtime.

The build intentionally ran unsigned and the notarization hook explicitly skipped because Apple API credentials were not configured. This is package ownership/runtime evidence, not signing/notarization evidence. The temporary workflow was removed in `f958db77041ffa88735e421159361d86e674849e`.

### 5.4 Linux clean-install evidence

Source:

```text
6e980ac2fe46a0680751dd55711ac53749419a14
```

Scoped validation:

```text
ZN Kernel / Python             success
Electron / TypeScript         success
ZN Linux Clean Install Smoke  success
Actions run                    32591603017
```

The clean-install test intentionally crossed an artifact boundary:

```text
Ubuntu build runner with repository
→ build/stage ZN
→ electron-builder deb
→ upload only deb artifact
→ NEW Ubuntu 24.04 runner with no checkout
→ download only deb
→ apt-get install
→ inspect dpkg-installed system files/desktop integration
→ boot installed embedded zn_agent resident zero-model
```

The produced clean-install artifact was:

```text
ZN-0.17.0-linux-amd64.deb
sha256 52d291538bee80e56d580eea05487926841fb9aa6a93de29c4083bac6dc618f9
Package zn-desktop
Version 0.17.0
Architecture amd64
```

On the fresh runner the package installed successfully to `/opt/ZN`, with `update-alternatives` providing `/usr/bin/ZN`. The system-installed desktop entry proved:

```text
Name=ZN
StartupWMClass=ai.zn.desktop
MimeType=x-scheme-handler/zn;
```

The installed runtime lived under `/opt/ZN/resources/zn-runtime`; its portable Python/backend were validated, inherited install stamp and `hermes_cli` were absent, and an isolated zero-model resident returned:

```text
clean installed resident pulse=1 mode=observing
external_brains == ()
```

The temporary clean-install workflow was removed after evidence in `1e5b2490a75eacfa5ec2c2e3240e6f9b1d015a05`.

### 5.5 Linux installed autostart continuity evidence

Source:

```text
6cc8becea3d97eea09c0887cd5c70612fc9ee573  fix: gracefully stop resident on SIGTERM
```

Validation:

```text
ZN Kernel / Python        success
Electron / TypeScript    success
normal CI run             32593886005
ZN Linux Autostart Smoke success
autostart run             32593886026
```

The fresh-runner gate installed the formal deb under `/opt/ZN`, then used only its embedded Python/installed package to create and exercise the systemd user login entry:

```text
zn_agent.core.resident_autostart install
→ enabled zn-resident.service / WantedBy=default.target
→ ExecStart uses embedded /opt/ZN Python + zn_agent.core.resident_server
→ resident active + packaged RPC status running
→ systemctl --user stop zn-resident.service
→ graceful SIGTERM cleanup retires endpoint and durable lease
→ systemctl --user restart default.target
→ packaged resident active/running again
→ uninstall autostart
```

The login entry had no source-checkout path, inherited `agent.kernel` runtime command or `WorkingDirectory` dependency. The source regression separately launches a real resident subprocess and proves SIGTERM exits `0` only after endpoint and SQLite resident lease are removed.

The exercise closed source/runtime-boundary defects in packaged module naming, startup cwd dependence and SIGTERM cleanup rather than introducing compatibility wrappers. The temporary autostart workflow was retired after successful evidence in `441f7a7e516118a2eac05668207dc8d8265cb610`.

This proves the currently scoped Linux installed autostart/start-stop-login-target continuity. N → N+1 runtime handoff and other intended-platform installation/login evidence remain separate M8 gates.

## 6. Formal desktop package identity

Status: **active formal product/build identity transferred to ZN; current intended OS-family artifact payloads verified; Linux deb also survives fresh system installation and installed user-login continuity**.

Implemented/verified:

- `apps/desktop/package.json` identifies `zn-desktop` / `ZN` and the ZN repository;
- default build metadata uses `ai.zn.desktop`, `ZN` executable/product and `ZN-*` artifacts;
- package-level and builder protocols contain only `zn`;
- `electron-builder.zn.yml` includes `build/zn-runtime` and excludes inherited install-stamp/bootstrap resources;
- Linux AppImage/deb/rpm extracted payloads preserve ZN app/runtime identity and zero-model resident boot;
- Windows NSIS/MSI extracted payloads preserve ZN PE identity and zero-model resident boot;
- macOS arm64 DMG/ZIP extracted payloads preserve ZN bundle/protocol identity and zero-model resident boot;
- a fresh Ubuntu 24.04 runner can install the formal Linux deb and boot the installed embedded resident without source tree or external model;
- the fresh installed Linux resident can be registered under the user login target, stopped cleanly with lease retirement and started again by `default.target` activation.

Important boundary: M7 artifact content/runtime identity is closed for the currently exercised targets, and E10/M8 is in progress. Clean-machine/continuity is still partial because runtime upgrade handoff and equivalent intended-platform release evidence remain open.

## 7. Remaining inherited/release debt

Still pending:

- N → N+1 application/runtime/resident handoff;
- Windows/macOS clean-install/login coverage for intended release targets;
- signing/notarization when release credentials/process are operationally configured;
- any additional architecture coverage required by the eventual release matrix;
- inactive inherited Electron/renderer/gateway/browser/source and dependency/script debt not on the active ZN control path;
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
E9  package independently bootable ZN product                 ARTIFACT SHAPE VERIFIED on Linux x86_64 / Windows x64 / macOS arm64
E10 verify clean-machine install/upgrade/multi-OS release      IN PROGRESS; Linux deb fresh-install + installed autostart continuity verified
```

## 9. Immediate code target

Priority order:

1. do not rebuild already-proven installer/autostart gates merely to recreate evidence;
2. trace the active ZN-owned update/runtime-selection/resident call chain before changing handoff behavior;
3. validate N → N+1 as two separate gates: busy resident must not be interrupted; idle resident must gracefully retire, start N+1 and preserve the same ZN home/identity/state;
4. add Windows/macOS clean-install/login coverage only where it provides genuinely new release evidence;
5. keep signing/notarization explicit and operational—never infer it from unsigned artifact success;
6. establish browser interaction only through a clean resident-owned body/sense seam;
7. define explicit resident artifact/message egress nomination before Telegram outbound attachment transport.

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
- preserve an independently bootable zero-model `zn_agent` resident inside real Linux/Windows/macOS artifact payloads;
- preserve ZN identity and embedded resident boot after a real fresh Linux deb installation;
- register/start/stop/restart the fresh installed Linux resident through a ZN-owned systemd user login entry without source checkout or stale resident lease.

The active source satisfies those structural boundaries for implemented slices. The next release-development work is N → N+1 continuity/upgrade validation; browser/egress work and later signing/repository migration remain explicit separate debt.
