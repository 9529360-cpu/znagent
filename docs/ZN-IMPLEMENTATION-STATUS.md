# ZN implementation status

> Architecture contract: [`../ZN.md`](../ZN.md)
>
> Source-extraction contract: [`ZN-SOURCE-EXTRACTION.md`](ZN-SOURCE-EXTRACTION.md)
>
> This file records **what is actually implemented now**. Code remains authoritative over this ledger.
>
> Active development branch: `dev/zn-agent`. `main` remains untouched until the explicit promotion milestone in `ZN.md`.

## Verified implementation baseline

M7 has real installer-content/runtime evidence on the three current intended OS families:

```text
Linux   x86_64   AppImage / deb / rpm
Windows x64      NSIS / MSI
macOS   arm64    DMG / ZIP
```

M8 now has two deliberately scoped Linux proofs. First, a Linux amd64 `.deb` was built on one Ubuntu runner, transferred as the only artifact to a second fresh Ubuntu 24.04 runner with no repository checkout, installed through `apt`, and the installed embedded resident booted zero-model from `/opt/ZN`. Second, a fresh installed deb created a ZN-owned systemd user login entry, started the packaged resident, stopped it cleanly, and started the same resident again through `default.target` activation.

This is not complete M8/release validation. N → N+1 continuity, Windows/macOS clean-install coverage, signing/notarization and any additional release architectures remain separate gates.

### Linux M8 clean-install evidence

Verified source:

```text
6e980ac2fe46a0680751dd55711ac53749419a14  test: validate clean Linux ZN installation
```

CI:

```text
ZN Kernel / Python             success
Electron / TypeScript         success
ZN Linux Clean Install Smoke  success
clean-install run              32591603017
clean runner                   Ubuntu 24.04.4 LTS
```

The gate deliberately used separate build/install runners:

```text
build runner
→ locked npm workspace
→ stage self-contained portable CPython + znagent
→ zero-model staging smoke
→ build ZN desktop
→ electron-builder.zn.yml --linux deb
→ upload only ZN-0.17.0-linux-amd64.deb

fresh Ubuntu runner (no checkout)
→ download only built deb
→ apt-get install local deb
→ verify dpkg/system-installed ZN identity
→ verify installed desktop integration
→ locate /opt/ZN/resources/zn-runtime
→ boot resident with installed embedded Python and no external model
```

The clean-install build produced:

```text
ZN-0.17.0-linux-amd64.deb
sha256 52d291538bee80e56d580eea05487926841fb9aa6a93de29c4083bac6dc618f9
Package: zn-desktop
Version: 0.17.0
Architecture: amd64
```

The second runner proved an actual package installation:

```text
dpkg state       install ok installed
installed package zn-desktop 0.17.0 amd64
app root          /opt/ZN
system command    /usr/bin/ZN → /opt/ZN/ZN via update-alternatives
embedded Python   /opt/ZN/resources/zn-runtime/python/cpython-3.11.15-linux-x86_64-gnu/bin/python3.11
embedded backend  /opt/ZN/resources/zn-runtime/python/cpython-3.11.15-linux-x86_64-gnu/lib/python3.11/site-packages
```

Installed desktop integration remained ZN-owned:

```text
Name=ZN
StartupWMClass=ai.zn.desktop
MimeType=x-scheme-handler/zn;
```

The gate also rejected inherited install-stamp/Hermes identity and packaged `hermes_cli`. The resident was constructed using the installed embedded Python under isolated mode and reported:

```text
clean installed resident pulse=1 mode=observing
external_brains == ()
```

The temporary clean-install workflow was removed after successful evidence in:

```text
1e5b2490a75eacfa5ec2c2e3240e6f9b1d015a05  test: finalize Linux clean-install validation
```

### Linux M8 installed autostart evidence

Verified source:

```text
6cc8becea3d97eea09c0887cd5c70612fc9ee573  fix: gracefully stop resident on SIGTERM
```

Normal CI:

```text
ZN Kernel / Python      success
Electron / TypeScript  success
run                     32593886005
```

The kernel suite includes a real POSIX subprocess regression: it launches `agent.kernel.resident_server`, waits until both endpoint and SQLite resident lease exist, sends SIGTERM, then requires exit code `0`, endpoint retirement and deletion of the resident lease before process exit.

The scoped installed-package gate also succeeded:

```text
ZN Linux Autostart Smoke  success
run                        32593886026
fresh runner               Ubuntu 24.04.4 LTS
```

The gate crossed a real artifact/install boundary:

```text
build runner with repository
→ stage self-contained zn_agent runtime
→ build formal Linux deb
→ upload only the deb

fresh Ubuntu runner with no checkout
→ apt install deb under /opt/ZN
→ start isolated systemd user manager
→ embedded Python executes zn_agent.core.resident_autostart install
→ verify enabled zn-resident.service
→ verify packaged resident becomes active and RPC status is running
→ systemctl --user stop zn-resident.service
→ verify service is inactive after graceful SIGTERM cleanup
→ restart default.target
→ verify packaged resident is active/running again
→ uninstall login entry
```

The installed login command was ZN-owned and self-contained:

```text
/opt/ZN/resources/zn-runtime/python/cpython-3.11.15-linux-x86_64-gnu/bin/python3.11
-m zn_agent.core.resident_server
--home /home/runner/.local/share/zn-autostart-smoke
```

The generated service used `WantedBy=default.target`, contained no inherited `agent.kernel` runtime command, no checkout path and no runtime `WorkingDirectory` dependency. The first installed resident was observed active with PID `2447`; after the explicit service stop and `default.target` restart the packaged status returned to `running; autostart: installed`.

This validation exposed and closed three real lifecycle/package defects rather than adding compatibility wrappers:

1. desktop autostart and generated login commands now use installed `zn_agent.core` modules instead of source-only `agent.kernel` names;
2. login entries no longer depend on a runtime working directory;
3. service-manager SIGTERM now unwinds through the resident's existing cleanup path so endpoint, organs, store and durable lease are retired before exit.

The temporary autostart workflow was removed after successful evidence in:

```text
441f7a7e516118a2eac05668207dc8d8265cb610  test: retire Linux autostart smoke [skip ci]
```

This proves the current Linux installed OS-login/start-stop-start continuity slice. It does not prove N → N+1 runtime handoff, Windows/macOS login behavior, equivalent clean installation on those platforms, signing/notarization or a final release matrix.

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

The temporary macOS workflow was removed after successful evidence in `f958db77041ffa88735e421159361d86e674849e`.

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

M7 artifact/package shape is verified on Linux x86_64, Windows x64 and macOS arm64. M8 now has both a Linux amd64 deb fresh-install proof and an installed systemd user autostart/start-stop-login-target-restart proof on a fresh Ubuntu runner without source checkout.

This still does **not** make the release ready. M8 continuity remains partial: N → N+1 application/runtime handoff and equivalent intended-platform clean-install/login coverage remain unverified; signing/notarization remains separate operational release hardening.

## M5/M6 product loop

`ResidentWorkLedger` owns durable threads/messages, workspace association, active work linkage/progress and bounded contextual file/diff/terminal artifacts beside kernel state. Provider settings/credential references remain resident-owned. Renderer progress/localStorage do not become resident authority.

## Browser and outbound-media investigation result

A browser contextual surface is **not** claimed yet. The mature inherited browser implementation remains coupled to inherited configuration/plugin/session/provider ownership plus Node/Chromium/`agent-browser`. The independent resident runtime has no clean ZN-owned browser action seam yet.

Telegram outbound media remains intentionally pending. `OutboundMediaPathPolicy` already provides local-file authorization and `ChannelMessage` can represent attachments, but resident delivery does not yet expose explicit structured artifact/path nomination for egress. The adapter must not infer arbitrary local paths as upload authority.

## Current subsystem ledger

### Resident organism / kernel

Status: **ZN-native resident organism active**.

Persistent life, Situation/Thought/Will, nervous memory, native investigation/action/learning, sensing and bounded external cognition remain resident-owned. Zero-model operation is a hard contract. The resident service now treats service-manager SIGTERM as a graceful stop request and unwinds through the same endpoint/organ/life/lease/store cleanup path used by normal service exit.

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

The independent `runtime/python` `znagent` distribution boots through `zn_agent.resident` / `zn-resident`, rejects inherited `hermes_cli`, has real extraction/boot evidence inside Linux/Windows/macOS artifacts, and now has fresh-runner installed Linux package resident-boot plus login-autostart continuity proof.

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

Status: **M7 artifact ownership verified for current Linux x86_64, Windows x64 and macOS arm64 targets; M8 has Linux amd64 deb clean-install and installed autostart continuity proofs**.

Verified:

- ZN package/repository/product/app/executable/artifact identity;
- ZN-only formal protocol registration;
- ZN-owned runtime resource path and no inherited install stamp;
- Linux AppImage/deb/rpm package contents + desktop integration + resident boot;
- Windows NSIS/MSI package contents + PE identity + resident boot;
- macOS arm64 DMG/ZIP package contents + Info.plist identity + `zn://` + resident boot;
- fresh Ubuntu 24.04 `.deb` installation from an artifact-only handoff, installed `/opt/ZN` product identity, system desktop integration and zero-model embedded resident boot;
- fresh installed Linux systemd user autostart using packaged `zn_agent.core` modules, graceful service stop/lease cleanup and resident return after `default.target` activation.

Still pending:

- N → N+1 update/runtime handoff and resident continuity;
- Windows/macOS clean-install and login-autostart coverage for the intended release matrix;
- signing/notarization when operationally configured;
- any additional architecture coverage required by the eventual release matrix (for example macOS x64/universal);
- eventual cleanup of inactive inherited source/dependency/script debt without regressing active ownership.

## Ownership/behavior tests protecting the active path

The suite and scoped artifact/install runs protect, among other behavior:

```text
agent/kernel must not import hermes_cli or run_agent
runtime distribution must identify as znagent
packaged runtime must reject hermes_cli
zero-model resident boot must succeed
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
real packaged zn-runtime boots zero-model after Linux/Windows/macOS artifact packaging
fresh-runner Linux deb installation preserves ZN identity and boots its installed embedded resident zero-model
SIGTERM stops a real resident subprocess with endpoint and durable lease retired before exit
fresh-installed Linux systemd user autostart starts packaged zn_agent, stops cleanly, and returns through default.target
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
M7  formal packaging around owned product                  ARTIFACT SHAPE VERIFIED on Linux x86_64 / Windows x64 / macOS arm64
M8  clean-machine/continuity multi-OS validation           IN PROGRESS; Linux deb fresh-install + installed autostart continuity verified
M9  product completeness/hardening                         LATER
M10 repository migration / formal main promotion           LATER; main untouched
```

## Immediate next development sequence

1. do not repeat M7, the Linux deb clean-install gate or the proven Linux autostart gate merely to recreate evidence;
2. trace the active ZN-owned update/runtime-selection/resident call chain and define the smallest truthful N → N+1 continuity gate from current code;
3. validate the busy case first: materializing/selecting N+1 must not interrupt active resident work;
4. validate the idle case separately: graceful shutdown, endpoint retirement, N+1 start and runtime-identity verification must preserve the same ZN home/identity/state;
5. extend clean-install/login coverage to Windows/macOS only when it adds release evidence rather than duplicating package-shape proof;
6. keep signing/notarization explicit and operational—never infer it from unsigned package success;
7. in parallel product work, establish browser interaction only through a clean resident-owned body/sense seam and define explicit resident egress nomination before Telegram outbound attachments.

The architecture driver remains the owned resident/workbench/product loop and independently bootable ZN package—not compatibility with inherited control planes.
