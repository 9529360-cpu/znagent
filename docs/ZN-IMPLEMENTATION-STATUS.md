# ZN implementation status

> Architecture contract: [`../ZN.md`](../ZN.md)
>
> Source-extraction contract: [`ZN-SOURCE-EXTRACTION.md`](ZN-SOURCE-EXTRACTION.md)
>
> This file records **what is actually implemented now**. Code remains authoritative over this ledger.
>
> Active development branch: `dev/zn-agent`. `main` remains untouched until the explicit promotion milestone in `ZN.md`.

## Verified implementation baseline

M7 now has real installer-content/runtime evidence on the three current intended OS families:

```text
Linux   x86_64   AppImage / deb / rpm
Windows x64      NSIS / MSI
macOS   arm64    DMG / ZIP
```

This is artifact/package evidence, not clean-machine release validation. Signing/notarization, OS-login autostart, N → N+1 continuity and clean-machine installation remain later gates.

### macOS M7 evidence

Verified source:

```text
518d233eafa39b2d12f2de5835a8c8c1ab7529ab  test: make macOS installer extraction runner-compatible
```

CI:

```text
ZN Kernel / Python          success
Electron / TypeScript      success
ZN macOS Installer Smoke   success
macOS smoke run             32591343670
runner                      macos-26-arm64
```

The scoped macOS workflow exercised the real formal chain:

```text
locked npm workspace
→ stage-zn-runtime.mjs
→ portable CPython 3.11.15 macOS arm64 + runtime/python znagent
→ zero-model runtime staging verification
→ ZN renderer/Electron build
→ electron-builder.zn.yml --mac dmg zip
→ mount real DMG + extract real ZIP
→ assert ZN.app / app.asar / zn-runtime and reject hermes_cli
→ read real Info.plist identity and URL schemes
→ boot packaged resident zero-model from both extracted payloads
```

Verified artifacts for version `0.17.0`:

```text
ZN-0.17.0-mac-arm64.dmg  160M  sha256 5e1b3b6cd538fcf0605c3be27d0513f551f48614dff865a984e281b52d8459b9
ZN-0.17.0-mac-arm64.zip  160M  sha256 416f6fbcde0477db6b201b1f8bcf2fbb2820d1e67f145c4a09bc24535ba72133
```

Both real extracted app bundles proved:

```text
CFBundleIdentifier  ai.zn.desktop
CFBundleDisplayName ZN
CFBundleName        ZN
CFBundleExecutable  ZN
URL scheme          zn  (and no second inherited scheme)
```

Both embedded `ZN.app/Contents/Resources/zn-runtime` payloads booted the resident successfully with zero external models.

The macOS build explicitly logged:

```text
skipped macOS application code signing
Skipping notarization: APPLE_API_KEY, APPLE_API_KEY_ID, and APPLE_API_ISSUER are not fully configured.
```

Therefore this evidence proves unsigned package shape/runtime ownership only. It does **not** claim signing/notarization completion.

The temporary macOS workflow was removed after successful evidence in:

```text
f958db77041ffa88735e421159361d86e674849e  test: finalize macOS installer validation
```

### Windows M7 evidence

Verified product source:

```text
2e3cdb0ac893feca86325e19a058c455c906bfd7  test: make MSI extraction deterministic
```

Validation:

```text
ZN Kernel / Python            success
Electron / TypeScript        success
ZN Windows Installer Smoke   success
Windows smoke run             32590239803
```

Verified artifacts:

```text
ZN-0.17.0-win-x64.exe  138.9 MB  sha256 d7716714599b87c125ab4ad5095fd3fb34bf2860e0fbdeebdece7b5316d05192
ZN-0.17.0-win-x64.msi  151.8 MB  sha256 bd4dc2cd6bee636fdb94941b02776e196c2c0808d0b13717ab6576ce4f32c01f
```

Both extracted payloads contained `ZN.exe`, `resources/app.asar`, one `resources/zn-runtime/runtime.json`, no packaged `hermes_cli`, and an independently bootable zero-model resident. Actual PE metadata read back as:

```text
ProductName     ZN
FileDescription ZN
CompanyName     ZN Project
```

The real Windows packaging exercise closed three source-level defects:

1. portable CPython top-level aliases are removed/rejected before installer materialization;
2. runtime `backend_root` is derived from installed `zn_agent` rather than generic site-package assumptions;
3. `ZNLifeCore` short-lived SQLite connections are deterministically closed, with regression coverage.

The temporary Windows workflow was removed after success in `36feb0092126e47929d7239f8518a2ad68908454`.

### Linux M7 evidence

Verified source points:

```text
6219eaa61f6c444feb96864e149f886752b00ffe  real AppImage/deb/rpm installer payload validation
46685b66ff1381cb0b41b1e0564cc62ca5e34467  corrected AppImage desktop integration validation
```

Verified artifacts:

```text
ZN-0.17.0-linux-x86_64.AppImage  179M  sha256 e4b1548f630fcb376e22257c3e6cc3c22589dee55746d6f1951605cc2a906120
ZN-0.17.0-linux-amd64.deb         143M  sha256 3555059b606cf679b277e4f4452212c5ddaba7034aef9b9791d596adf8267606
ZN-0.17.0-linux-x86_64.rpm        117M  sha256 34bd11a006937d1746b2e487f742edc8cb6d9ec3da75da3d5475757db37c9d03
```

Each extracted runtime booted zero-model. AppImage desktop integration proved `Name=ZN`, `StartupWMClass=ai.zn.desktop` and only `x-scheme-handler/zn`.

## Current development checkpoint

The active product boundary is ZN-owned across resident runtime, cognition resources, local terminal/PTTY, web sensing, communication lifecycle, Electron main/preload/protocol, React workbench and formal desktop package/build identity.

M5/M6 currently has:

- resident-backed durable work/thread continuity;
- real resident-backed workspace/folder association;
- contextual resident-backed file/diff/terminal artifacts;
- resident-owned provider/settings editing with secure credential references and hot cognition reconfiguration;
- durable active work-run identity plus resident-derived ongoing progress while work continues without the desktop.

M7 artifact/package shape is now verified on Linux x86_64, Windows x64 and macOS arm64. The formal path uses ZN package/repository/product/app/executable identity, only `zn://`, staged self-contained `build/zn-runtime`, and no inherited install-stamp/bootstrap resource.

This still does **not** make the release ready. M8 clean-machine installation/continuity, autostart, N → N+1 handoff and operational signing/notarization remain unverified.

## M5/M6 product loop

### Resident-backed work and progress

`ResidentWorkLedger` owns durable threads/messages beside kernel state. `work_runs` links accepted resident events before completion. `work_start` returns after resident acceptance so the life loop can continue after Electron disconnects. Completion finalizes idempotently, including after resident reconstruction.

`work_progress` reports actual event/working state and can include matching Thought, investigation and same-event Body actions. Renderer progress is resident-derived and is not localStorage authority.

### Workspace and contextual artifacts

Each thread can persist one canonical resident `WorkspaceAssociation`; resident re-verifies the OS-selected folder. Workspace/workdir context reaches native Git/body movement.

`WorkArtifact` records are resident-owned and bounded. Current contextual kinds include file, diff and terminal. File previews remain workspace-contained; terminal evidence comes from actual same-event body actions. The workbench remains content-first rather than a permanent IDE shell.

### Resident-owned provider/credential settings

Provider settings persist non-secret configuration through the resident. UI secrets use resident credential references and OS keyring storage where available; raw secrets are not returned through settings RPC. Cognitive resources hot-reconfigure without replacing resident identity/store/memory/life. Missing external credentials degrade to cognition unavailable rather than resident death.

## Browser and outbound-media investigation result

A browser contextual surface is **not** claimed yet. The mature inherited browser implementation remains coupled to inherited configuration/plugin/session/provider ownership plus Node/Chromium/`agent-browser`. The independent resident runtime has no clean ZN-owned browser action seam yet. Mounting that old stack or relabeling web-search results as browser interaction would violate the architecture.

Telegram outbound media remains intentionally pending. `OutboundMediaPathPolicy` already provides local-file authorization and `ChannelMessage` can represent attachments, but resident delivery does not yet expose explicit structured artifact/path nomination for egress. The adapter must not infer arbitrary local paths as upload authority.

## Current subsystem ledger

### Resident organism / kernel

Status: **ZN-native resident organism active**.

Persistent life, Situation/Thought/Will, nervous memory, native investigation/action/learning, sensing and bounded external cognition remain resident-owned. Zero-model operation is a hard contract. Short-lived life-state SQLite connections are explicitly closed and regression-tested.

### Work/thread/workspace/artifacts

Status: **resident-backed durable work + active progress + workspace + contextual file/diff/terminal artifacts active; M6 still partial**.

### External cognition/settings

Status: **ZN-native resource layer plus resident-owned provider/credential editor active**.

### Local terminal/body

Status: **ZN local terminal/PTTY active with contextual resident presentation**.

### Web/world sense

Status: **ZN-owned search/extract providers and network safety active; browser automation not yet owned**.

### Communication channels

Status: **resident-owned channel framework and Telegram text/inbound media active; outbound attachment transport pending explicit resident egress nomination**.

### Python/runtime package ownership

Status: **M1 complete for the active packaged resident path**.

The independent `runtime/python` `znagent` distribution boots through `zn_agent.resident` / `zn-resident`, rejects inherited `hermes_cli`, and now has real zero-model extraction/boot evidence inside Linux, Windows and macOS installer artifacts.

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

Status: **M7 package/artifact ownership materially complete for current Linux x86_64, Windows x64 and macOS arm64 targets; M8 release validation not started**.

Verified:

- ZN package/repository/product/app/executable/artifact identity;
- ZN-only formal protocol registration;
- ZN-owned runtime resource path and no inherited install stamp;
- Linux AppImage/deb/rpm package contents + desktop integration + resident boot;
- Windows NSIS/MSI package contents + PE identity + resident boot;
- macOS arm64 DMG/ZIP package contents + Info.plist identity + `zn://` + resident boot.

Still pending:

- clean-machine installation and resident continuity gates;
- OS-login autostart;
- N → N+1 update/runtime handoff;
- signing/notarization when operationally configured;
- any additional architecture coverage required by the eventual release matrix (for example macOS x64/universal) rather than assumed from the arm64 proof;
- eventual cleanup of inactive inherited source/dependency/script debt without regressing active ownership.

## Ownership/behavior tests protecting the active path

The suite and scoped artifact runs protect, among other behavior:

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
formal Linux launcher/window identity is aligned
formal Windows pack hooks stamp ZN identity
real macOS app bundles identify as ai.zn.desktop / ZN and only zn://
real packaged zn-runtime boots zero-model after Linux/Windows/macOS installer packaging
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
M7  formal packaging around owned product                  ARTIFACT SHAPE VERIFIED on Linux x86_64 / Windows x64 / macOS arm64; release gates remain
M8  clean-machine/continuity multi-OS validation           NEXT RELEASE GATE
M9  product completeness/hardening                         LATER
M10 repository migration / formal main promotion           LATER; main untouched
```

## Immediate next development sequence

1. stop repeating installer-format builds merely to recreate M7 evidence;
2. define the first deliberately scoped M8 clean-machine/continuity gate, beginning with the cheapest high-value target and proving installed ZN can start its embedded resident independently with zero external model;
3. then validate OS-login autostart and N → N+1 runtime/application continuity without conflating those with signing/notarization;
4. keep signing/notarization as explicit operational release hardening and never infer it from unsigned package success;
5. in parallel product work, establish browser interaction only through a clean resident-owned body/sense seam;
6. define explicit resident artifact/message egress nomination before Telegram outbound attachment transport;
7. broaden artifact rendering/history only where concrete work output requires it.

The architecture driver remains the owned resident/workbench/product loop and independently bootable ZN package—not compatibility with inherited control planes.
