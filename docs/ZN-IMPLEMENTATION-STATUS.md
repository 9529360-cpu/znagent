# ZN implementation status

> Architecture contract: [`../ZN.md`](../ZN.md)
>
> Source-extraction contract: [`ZN-SOURCE-EXTRACTION.md`](ZN-SOURCE-EXTRACTION.md)
>
> This file records **what is actually implemented now**. Code remains authoritative over this ledger.
>
> Active development branch: `dev/zn-agent`. `main` remains untouched until the explicit promotion milestone in `ZN.md`.

## Verified implementation baseline

Current verified Windows-installer product source:

```text
2e3cdb0ac893feca86325e19a058c455c906bfd7  test: make MSI extraction deterministic
```

Normal CI and scoped installer validation for that source:

```text
ZN Kernel / Python        success
Electron / TypeScript    success
ZN Windows Installer Smoke success
Windows smoke run         32590239803
```

The Windows smoke exercised the real formal chain:

```text
locked npm workspace
→ stage-zn-runtime.mjs
→ portable CPython + runtime/python znagent
→ zero-model runtime staging verification
→ ZN renderer/Electron build
→ electron-builder.zn.yml --win nsis msi
→ extract real NSIS and MSI installer payloads
→ assert ZN executable/app.asar/zn-runtime and reject hermes_cli
→ read actual Windows PE product/company identity
→ boot the packaged resident zero-model from both extracted payloads
```

Verified Windows artifacts for version `0.17.0`:

```text
ZN-0.17.0-win-x64.exe  138.9 MB  sha256 d7716714599b87c125ab4ad5095fd3fb34bf2860e0fbdeebdece7b5316d05192
ZN-0.17.0-win-x64.msi  151.8 MB  sha256 bd4dc2cd6bee636fdb94941b02776e196c2c0808d0b13717ab6576ce4f32c01f
```

Both extracted payloads contained `ZN.exe`, `resources/app.asar`, one `resources/zn-runtime/runtime.json`, no packaged `hermes_cli`, and a Windows runtime backend under `Lib/site-packages`. The actual executable metadata read back as:

```text
ProductName     ZN
FileDescription ZN
CompanyName     ZN Project
```

The resident booted successfully from both installer payloads with zero external models. MSI administrative extraction is now awaited synchronously with `Start-Process -Wait`; the workflow also proves the Python `encodings` tree is complete immediately when extraction returns.

The Windows validation exposed two real packaging/runtime issues and both were fixed at their source boundaries:

1. portable Windows CPython installed by `uv` can include a top-level alias/symlink that is not a valid installer payload shape; `stage-zn-runtime.mjs` now removes matching Windows aliases before packaging and rejects remaining top-level aliases;
2. generic site-package discovery was not reliable for the staged portable Windows interpreter; runtime staging now derives `backend_root` from the installed `zn_agent` module itself and verifies `resident.py` and `core/resident_server.py` there.

A Windows-hosted zero-model smoke also exposed SQLite connection lifetime sensitivity. `ZNLifeCore` now closes its short-lived SQLite connections deterministically through `contextlib.closing`, with a regression test proving pulse/snapshot connections are closed.

The temporary Windows installer workflow was removed after success in:

```text
36feb0092126e47929d7239f8518a2ad68908454  test: finalize Windows installer validation
```

### Previously verified Linux M7 evidence

Linux formal packaging is already validated and should not be repeated merely to recreate evidence:

```text
6219eaa61f6c444feb96864e149f886752b00ffe  real AppImage/deb/rpm installer payload validation
46685b66ff1381cb0b41b1e0564cc62ca5e34467  corrected AppImage desktop integration validation
```

Verified Linux evidence includes:

- unpacked electron-builder product shape;
- real AppImage, deb and rpm construction and extraction;
- ZN executable, `app.asar`, self-contained `zn-runtime`, no inherited install stamp and no packaged `hermes_cli`;
- zero-model resident boot from every extracted installer runtime;
- generated desktop filename aligned to `ai.zn.desktop`;
- `StartupWMClass=ai.zn.desktop`;
- `Name=ZN` and only `x-scheme-handler/zn` in the real AppImage desktop entry.

Verified Linux installer artifacts for version `0.17.0`:

```text
ZN-0.17.0-linux-x86_64.AppImage  179M  sha256 e4b1548f630fcb376e22257c3e6cc3c22589dee55746d6f1951605cc2a906120
ZN-0.17.0-linux-amd64.deb         143M  sha256 3555059b606cf679b277e4f4452212c5ddaba7034aef9b9791d596adf8267606
ZN-0.17.0-linux-x86_64.rpm        117M  sha256 34bd11a006937d1746b2e487f742edc8cb6d9ec3da75da3d5475757db37c9d03
```

## Current development checkpoint

The active product boundary is ZN-owned across resident runtime, provider cognition, local terminal/PTTY, web sensing, communication lifecycle, Electron main/preload/protocol, the React workbench and the formal desktop package/build identity path.

M5/M6 currently has:

- resident-backed durable work/thread continuity;
- real resident-backed local workspace/folder association;
- contextual resident-backed file/diff/terminal artifacts;
- resident-owned provider/settings editing with secure credential references and hot cognition reconfiguration;
- durable active work-run identity plus resident-derived ongoing progress while work continues without the desktop.

M7 is now materially advanced across Linux **and Windows**:

- `apps/desktop/package.json` identifies `zn-desktop` / `ZN` and the ZN repository;
- default build metadata uses `ai.zn.desktop`, executable/product `ZN`, `ZN-*` artifacts and only `zn://`;
- the formal builder includes the staged self-contained `build/zn-runtime` and excludes inherited install-stamp/bootstrap resources;
- Linux unpacked/AppImage/deb/rpm payloads and AppImage desktop integration are verified;
- Windows NSIS/MSI real installer payloads are verified, including PE product identity and zero-model resident boot;
- runtime staging handles the real Windows portable-Python package layout rather than assuming Unix site-package behavior;
- normal ownership/runtime tests protect the active path.

This does **not** mean M7/M8 are complete. macOS DMG/ZIP artifact validation remains the next intended-platform M7 evidence. Clean-machine installation, autostart, N → N+1 continuity, signing/notarization and release-channel hardening remain separate M8/M9 work.

## M5/M6 product loop

### Resident-backed work and progress

`ResidentWorkLedger` owns durable threads/messages beside kernel state. `work_runs` links accepted resident events to work threads/messages before completion. `work_start` returns after resident acceptance so the life loop can continue when Electron disconnects. Completed work finalizes idempotently, including after resident reconstruction.

`work_progress` reports actual event/working state and can include matching Thought, investigation state and recent same-event Body actions. Renderer progress is resident-derived and is not persisted as localStorage authority.

### Workspace and contextual artifacts

Each thread can persist one canonical resident `WorkspaceAssociation`. Electron uses the OS folder picker; resident re-verifies the directory. Canonical workspace/workdir context reaches native Git/body movement.

`WorkArtifact` records are resident-owned and bounded. Current contextual kinds include file, diff and terminal. File previews remain workspace-contained; terminal evidence comes only from actual same-event body actions. The workbench renders artifacts contextually rather than as a permanent IDE shell.

### Resident-owned provider/credential settings

Provider settings persist non-secret configuration through the resident. UI secrets use resident credential references and OS keyring storage where available; raw secrets are not returned through settings RPC. Cognitive resources can hot-reconfigure without replacing resident identity/store/memory/life. Missing external credentials degrade to cognition unavailable rather than resident death.

## Browser and outbound-media investigation result

A browser contextual surface is **not** claimed yet. The mature inherited browser implementation remains tightly coupled to inherited configuration/plugin/session/provider ownership plus Node/Chromium/`agent-browser`. The independent resident runtime currently has no clean ZN-owned browser action seam. Mounting that old stack or relabeling web-search results as browser interaction would violate the architecture.

Telegram outbound media remains intentionally pending. `OutboundMediaPathPolicy` already provides local-file authorization and `ChannelMessage` can represent attachments, but the resident delivery path does not yet expose an explicit structured artifact/path nomination for egress. The adapter must not guess local paths and silently convert them into upload authority.

## Current subsystem ledger

### Resident organism / kernel

Status: **ZN-native resident organism active**.

Persistent life, Situation/Thought/Will, nervous memory, native investigation/action/learning, sensing and bounded external cognition remain resident-owned. Zero-model operation is a hard behavior contract. Short-lived life-state SQLite connections are now explicitly closed and regression-tested.

### Work/thread/workspace/artifacts

Status: **resident-backed durable work + active progress + workspace + contextual file/diff/terminal artifacts active; M6 still partial**.

Remaining product work includes a real browser seam only when justified, broader artifact/history rendering where concrete outputs require it, and final accessibility/keyboard/visual polish.

### External cognition/settings

Status: **ZN-native resource layer plus resident-owned provider/credential editor active**.

OpenAI-compatible, Anthropic and Gemini resources are ZN-owned. Advanced multi-route authoring remains intentionally outside the simple editor.

### Local terminal/body

Status: **ZN local terminal/PTTY active with contextual resident presentation**.

### Web/world sense

Status: **ZN-owned search/extract providers and network safety active; browser automation not yet owned**.

### Communication channels

Status: **resident-owned channel framework and Telegram text/inbound media active; outbound attachment transport pending explicit resident egress nomination**.

### Python/runtime package ownership

Status: **M1 complete for the active packaged resident path**.

The independent `runtime/python` `znagent` distribution boots through `zn_agent.resident` / `zn-resident`. Runtime staging rejects inherited `hermes_cli`. It has survived real electron-builder Linux and Windows installer packaging and zero-model boot after extraction. Windows staging now removes invalid portable-Python aliases and derives the runtime backend from the installed `zn_agent` module.

### Desktop/UI ownership

Status: **M4 complete; M5/M6 materially advanced**.

```text
ZN Electron main
→ ZN preload
→ ZN React workbench
→ ZN resident RPC
→ long-lived zn_agent resident
```

### Packaging/release ownership

Status: **formal package identity plus Linux AppImage/deb/rpm and Windows NSIS/MSI payloads verified; M7 overall still in progress**.

Verified:

- ZN package/repository/product/app/executable/artifact identity;
- ZN-only formal protocol registration;
- ZN-owned runtime resource path and no inherited install stamp;
- Linux launcher/window identity and real AppImage desktop integration;
- Windows PE product/company identity in real installer payloads;
- independently bootable zero-model `zn_agent` runtime inside real Linux and Windows installer artifacts.

Still pending:

- macOS DMG/ZIP artifact validation;
- clean-machine install and resident continuity gates;
- autostart and N → N+1 release validation;
- signing/notarization when operationally configured;
- eventual cleanup of inactive inherited source/dependency/script debt without regressing active ownership.

## Ownership/behavior tests protecting the active path

The suite protects, among other behavior:

```text
agent/kernel must not import hermes_cli or run_agent
runtime distribution must identify as znagent
packaged runtime must reject hermes_cli
zero-model resident boot must succeed
life-state SQLite connections must be closed after use
Windows runtime staging must derive backend_root from installed zn_agent
Windows runtime staging must reject leftover portable-Python aliases
provider secrets/settings remain resident-owned and sanitized
resident accepted work persists before completion
completed detached work finalizes after reconstruction
one thread rejects parallel active resident work
progress comes from resident state, not renderer/localStorage
workspace/artifacts remain resident-backed and bounded
ZN desktop main/preload/renderer do not delegate to inherited control planes
ZN deep links reject hermes://
formal package metadata identifies ZN
formal builder registers only zn://
formal builder includes build/zn-runtime and excludes inherited install-stamp
formal Linux launcher/window identity is explicitly aligned
formal Windows pack hooks stamp ZN identity
real packaged zn-runtime boots zero-model after Linux/Windows installer packaging
```

## Milestone status snapshot

```text
M0  blueprint/reset ownership contract                     COMPLETE
M1  independently packageable ZN Python resident runtime   COMPLETE for active packaged path
M2  ZN-native bounded provider cognition                   COMPLETE for active main provider families
M3  ZN-owned terminal + web body/sense paths               COMPLETE for active local/web paths
M4  independent Electron main + preload + zn://            COMPLETE
M5  independent content-first ZN workbench                 IN PROGRESS; core owned surfaces active
M6  resident work/artifact/workspace end-to-end loop       PARTIAL; durable active work/progress active
M7  formal packaging around owned product                  IN PROGRESS; Linux + Windows real installer payloads verified
M8  clean-machine/continuity multi-OS validation           NOT STARTED as release gate
M9  product completeness/hardening                         LATER
M10 repository migration / formal main promotion           LATER; main untouched
```

## Immediate next development sequence

1. validate the intended macOS DMG/ZIP artifacts from the same corrected ZN package shape, keeping the work scoped to M7 artifact/content/runtime evidence rather than a full clean-machine matrix;
2. fix any active package-content/runtime-entrypoint/macOS integration debt the real artifacts expose;
3. once Linux + Windows + macOS intended-platform artifacts are genuinely valid, stop installer-format churn and move to deliberate M8 clean-machine/autostart/N → N+1 continuity gates;
4. in parallel product work, establish browser interaction only through a clean resident-owned body/sense seam;
5. define explicit resident artifact/message egress nomination before Telegram outbound attachment transport;
6. broaden artifact rendering/history only where concrete work output requires it.

The architecture driver remains the owned resident/workbench/product loop and independently bootable ZN package—not compatibility with inherited control planes.
