# ZN implementation status

> Architecture contract: [`../ZN.md`](../ZN.md)
>
> Source-extraction contract: [`ZN-SOURCE-EXTRACTION.md`](ZN-SOURCE-EXTRACTION.md)
>
> This file records **what is actually implemented now**. Code remains authoritative over this ledger.
>
> Active development branch: `dev/zn-agent`. `main` remains untouched until the explicit promotion milestone in `ZN.md`.

## Verified implementation baseline

Latest source implementation baseline:

```text
8c626fd44e7e0270e65fe1b3db629efa9350facf
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
```

Final normal ZN CI for the verified source HEAD:

```text
ZN Kernel / Python      success
Electron / TypeScript  success
Actions run             32586385421
```

A deliberately scoped real-package validation also passed on the same executable/package source shape (with only the temporary smoke workflow present during that run):

```text
ZN Formal Package Smoke  success
Linux unpacked package   success
packaged resident boot   success (zero-model)
Actions run              32586304510
```

That smoke used the same real chain as formal packaging for the relevant Linux shape:

```text
locked npm workspace
→ stage-zn-runtime.mjs
→ portable CPython + runtime/python znagent
→ zero-model runtime staging verification
→ ZN renderer/Electron build
→ electron-builder.zn.yml --linux --dir
→ packaged-runtime verification + zero-model boot
→ package shape assertions
```

It verified an executable `ZN`, `resources/app.asar`, `resources/zn-runtime/runtime.json`, correct ZN runtime product/version/commit, absence of the inherited install-stamp resource and absence of packaged `hermes_cli`. The temporary smoke workflow was deleted immediately after success. It is not part of the current branch.

The first package-identity CI attempt correctly failed because the root npm lock still described the desktop workspace as `hermes`. A one-shot GitHub runner executed npm's own `npm install --package-lock-only --ignore-scripts`; npm changed only the workspace package/link identity to `zn-desktop`. The temporary lock synchronization workflow was then deleted. Documentation-only synchronization commits use `[skip ci]`.

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
- a real Linux unpacked package has been built and its packaged resident has booted successfully with zero external models.

This does **not** mean M7/M8 are complete. Multi-OS installers, clean-machine installation, autostart, N → N+1 continuity and release signing/notarization gates remain separate work.

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

The independent `runtime/python` `znagent` distribution boots through `zn_agent.resident` / `zn-resident`. Runtime staging rejects inherited `hermes_cli`. The formal package smoke proved the staged runtime survives actual electron-builder packaging and still boots zero-model from inside the packaged application resource tree.

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

Status: **formal package identity plus Linux unpacked package shape verified; M7 overall still in progress**.

Verified:

- ZN package/repository/product/app/executable/artifact identity;
- ZN-only formal protocol registration;
- ZN-only active Windows PE identity stamping;
- ZN-owned runtime resource path;
- inherited install-stamp removed from active formal packaging;
- npm lock synchronized to `zn-desktop`;
- formal release workflow stages self-contained `zn-runtime` before electron-builder;
- real Linux unpacked formal package contains ZN executable/app.asar/self-contained runtime;
- packaged resident runtime manifest and zero-model boot pass after packaging.

Still pending:

- actual Linux installer-format artifacts (AppImage/deb/rpm) from the corrected package shape;
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
M7  formal packaging around owned product                  IN PROGRESS; identity + Linux unpacked package verified
M8  clean-machine/continuity multi-OS validation           NOT STARTED as release gate
M9  product completeness/hardening                         LATER
M10 repository migration / formal main promotion           LATER; main untouched
```

## Immediate next development sequence

1. keep M7 scoped: validate actual installer-format artifacts from the corrected ZN package shape only when useful, without prematurely running the full M8 clean-machine matrix;
2. fix package-content/runtime-entrypoint debt if real installer artifacts expose any;
3. establish browser interaction only through a clean resident-owned body/sense seam;
4. define explicit resident artifact/message egress nomination before Telegram outbound attachment transport;
5. broaden artifact rendering/history only where concrete work output requires it;
6. after M7 artifacts are genuinely valid across intended platforms, spend M8 budget on clean-machine, autostart and N → N+1 continuity.

The architecture driver remains the owned resident/workbench/product loop and independently bootable ZN package—not compatibility with inherited control planes.