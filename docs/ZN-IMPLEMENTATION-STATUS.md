# ZN implementation status

> Architecture contract: [`../ZN.md`](../ZN.md)
>
> Source-extraction contract: [`ZN-SOURCE-EXTRACTION.md`](ZN-SOURCE-EXTRACTION.md)
>
> This file records **what is actually implemented now**. Code remains authoritative over this ledger.
>
> Active development branch: `dev/zn-agent`. `main` remains untouched until the explicit promotion milestone in `ZN.md`.

## Verified implementation baseline

Latest installer-validated product source shape:

```text
6219eaa61f6c444feb96864e149f886752b00ffe
```

Cleanup immediately after validation removed only the temporary installer-smoke workflow:

```text
b138d917a131c61977bf6a226f97d5c54a071ec9  test: finalize Linux ZN installer validation
```

Recent coherent source slices:

```text
dd68e61c91e7aa222fba2f9b2c0516bbb2a190b8  feat: add resident-owned provider settings
89d24027249e1a13b6f6b5e9639127f0fc5f4ddc  feat: persist active work runs [skip ci]
37e662433f958e298d3f2d337af9935c4303a370  feat: expose resident work progress
2157283a4e3392ec34f22c100fd0b238805be9b6  test: isolate resident progress cache assertion
6cbe1e608e22e90e2f218665a2937684ca402796  feat: make desktop package identity ZN-owned
3a75a0da212a8fd8c362f4ac4c836dcba2a65731  fix: remove inherited identity from formal pack hooks
92525d7c41c19a064a99e7b936b5bb2da80f9598  chore: synchronize ZN desktop package lock [skip ci]
c0e8bb8563b323313304cc961ff07640d92d02cf  test: validate final ZN desktop package identity
8c626fd44e7e0270e65fe1b3db629efa9350facf  test: finalize ZN package smoke validation
6219eaa61f6c444feb96864e149f886752b00ffe  test: validate Linux ZN installer artifacts
b138d917a131c61977bf6a226f97d5c54a071ec9  test: finalize Linux ZN installer validation
```

Normal ZN CI for the installer-validation source commit:

```text
ZN Kernel / Python      success
Electron / TypeScript  success
Actions run             32586833739
```

A deliberately scoped Linux installer-format validation also passed on the same product source shape:

```text
ZN Linux Installer Smoke  success
AppImage extraction       success
deb extraction            success
rpm extraction            success
packaged resident boot    success from all three extracted artifacts (zero-model)
Actions run                32586833761
```

The smoke exercised the real formal Linux chain:

```text
locked npm workspace
→ stage-zn-runtime.mjs
→ portable CPython + runtime/python znagent
→ zero-model runtime staging verification
→ ZN renderer/Electron build
→ electron-builder.zn.yml --linux AppImage deb rpm
→ extract each real installer artifact
→ package-shape assertions inside each extracted artifact
→ packaged-runtime verification + zero-model resident boot from each artifact
```

Verified artifacts for version `0.17.0`:

```text
ZN-0.17.0-linux-x86_64.AppImage  179M  sha256 e4b1548f630fcb376e22257c3e6cc3c22589dee55746d6f1951605cc2a906120
ZN-0.17.0-linux-amd64.deb         143M  sha256 3555059b606cf679b277e4f4452212c5ddaba7034aef9b9791d596adf8267606
ZN-0.17.0-linux-x86_64.rpm        117M  sha256 34bd11a006937d1746b2e487f742edc8cb6d9ec3da75da3d5475757db37c9d03
```

Each extracted artifact contained the ZN executable/application payload, `resources/app.asar`, `resources/zn-runtime/runtime.json`, no inherited install-stamp resource and no packaged `hermes_cli`. The runtime manifest matched product/version/commit, and the resident booted with zero external models from the AppImage SquashFS payload, the deb `/opt/ZN` payload and the rpm `/opt/ZN` payload. The temporary validation workflow was deleted immediately after success and is not part of the current branch.

The installer build also surfaced a non-failing Linux desktop-integration warning from electron-builder: `desktopName` is not explicitly set, so WM_CLASS / `.desktop` association is not yet proven. That is release polish debt, not a failure of the packaged resident/runtime ownership seam, and should be resolved before calling Linux packaging release-ready.

The earlier package-identity CI attempt correctly failed because the root npm lock still described the desktop workspace as `hermes`. A one-shot GitHub runner executed npm's own `npm install --package-lock-only --ignore-scripts`; npm changed only the workspace package/link identity to `zn-desktop`. The temporary lock synchronization workflow was then deleted. Documentation-only synchronization commits use `[skip ci]`.

## Current development checkpoint

The active product boundary is ZN-owned across resident runtime, provider cognition, local terminal/PTTY, web sensing, communication lifecycle, Electron main/preload/protocol, the React workbench and the formal desktop package/build identity path.

M5/M6 now has:

- resident-backed durable work/thread continuity;
- real resident-backed local workspace/folder association;
- contextual resident-backed file/diff/terminal artifacts;
- resident-owned provider/settings editing with secure credential references and hot cognition reconfiguration;
- durable active work-run identity plus resident-derived ongoing progress while work continues without the desktop.

M7 is now materially advanced:

- `apps/desktop/package.json` identifies `zn-desktop` / `ZN` and the ZN repository;
- default build metadata uses `ai.zn.desktop`, executable/product `ZN`, `ZN-*` artifacts and only `zn://`;
- the normal builder command explicitly selects `electron-builder.zn.yml`;
- the formal ZN builder includes the staged self-contained `build/zn-runtime`;
- inherited install-stamp/bootstrap resources are no longer part of the active formal packaging path;
- Windows PE stamping writes ZN product/company identity;
- Windows rollback preservation defaults to `ZN.exe`;
- macOS notarization temporary key material uses a ZN-owned prefix;
- npm lock metadata agrees with the `zn-desktop` workspace identity;
- formal package/build-hook identity is protected by regression tests;
- a real Linux unpacked package has been built and its packaged resident has booted successfully with zero external models;
- real AppImage, deb and rpm artifacts have each been built, extracted, shape-checked and used to boot the packaged resident zero-model from inside the artifact payload.

This does **not** mean M7/M8 are complete. Windows/macOS installer artifacts, Linux desktop integration polish, clean-machine installation, autostart, N → N+1 continuity and release signing/notarization gates remain separate work.

## M5/M6 product loop

### Resident-backed work and progress

`ResidentWorkLedger` owns durable threads/messages beside kernel state. `work_runs` links accepted resident events to work threads/messages before completion. `work_start` returns after resident acceptance, so the life loop can continue when Electron disconnects. Completed work finalizes idempotently, including after resident reconstruction.

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

Persistent life, Situation/Thought/Will, nervous memory, native investigation/action/learning, sensing and bounded external cognition remain resident-owned. Zero-model operation is a hard behavior contract.

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

The independent `runtime/python` `znagent` distribution boots through `zn_agent.resident` / `zn-resident`. Runtime staging rejects inherited `hermes_cli`. The packaged runtime has now survived both electron-builder's unpacked application output and extraction from actual AppImage/deb/rpm artifacts, with zero-model resident boot from every tested payload.

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

Status: **formal package identity plus Linux unpacked and AppImage/deb/rpm artifact payloads verified; M7 overall still in progress**.

Verified:

- ZN package/repository/product/app/executable/artifact identity;
- ZN-only formal protocol registration;
- ZN-only active Windows PE identity stamping;
- ZN-owned runtime resource path;
- inherited install-stamp removed from active formal packaging;
- npm lock synchronized to `zn-desktop`;
- formal release workflow stages self-contained `zn-runtime` before electron-builder;
- real Linux unpacked formal package contains ZN executable/app.asar/self-contained runtime;
- real AppImage/deb/rpm artifacts can be extracted and each contains the same ZN-owned application/runtime shape;
- packaged resident runtime manifest and zero-model boot pass after extraction from all three Linux installer formats.

Still pending:

- resolve/verify Linux `.desktop` / WM_CLASS association (`desktopName` / `linux.syncDesktopName`) before calling Linux packaging release-ready;
- Windows/macOS installer artifact validation;
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
formal Windows pack hooks stamp ZN identity
formal active pack/sign hooks contain no Hermes/Nous product identity
real packaged zn-runtime can boot zero-model after electron-builder packaging
real Linux AppImage/deb/rpm payloads preserve the same ZN-only runtime and boot it zero-model
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
M7  formal packaging around owned product                  IN PROGRESS; identity + Linux unpacked + AppImage/deb/rpm payloads verified
M8  clean-machine/continuity multi-OS validation           NOT STARTED as release gate
M9  product completeness/hardening                         LATER
M10 repository migration / formal main promotion           LATER; main untouched
```

## Immediate next development sequence

1. keep M7 scoped: close Linux installer integration debt exposed by the real artifacts, especially explicit desktop-file/WM_CLASS association, without launching the full M8 clean-machine matrix;
2. validate intended Windows/macOS installer artifacts only when that additional M7 evidence justifies the CI cost;
3. fix package-content/runtime-entrypoint debt if later real artifacts expose any;
4. establish browser interaction only through a clean resident-owned body/sense seam;
5. define explicit resident artifact/message egress nomination before Telegram outbound attachment transport;
6. broaden artifact rendering/history only where concrete work output requires it;
7. after intended-platform M7 artifacts are genuinely valid, spend M8 budget on clean-machine, autostart and N → N+1 continuity.

The architecture driver remains the owned resident/workbench/product loop and independently bootable ZN package—not compatibility with inherited control planes.