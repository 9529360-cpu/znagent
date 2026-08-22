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
c0e8bb8563b323313304cc961ff07640d92d02cf
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
```

Normal ZN CI for the current verified source HEAD:

```text
ZN Kernel / Python      success
Electron / TypeScript  success
Actions run             32586113616
```

The first package-identity CI attempt correctly failed because the root npm lock still described the desktop workspace as `hermes`. A one-shot GitHub runner executed npm's own `npm install --package-lock-only --ignore-scripts`; the resulting lock change only renamed the workspace package/link to `zn-desktop`. The temporary synchronization workflow was then deleted. The final source HEAD above passed normal CI.

Documentation-only synchronization commits use `[skip ci]`.

## Current development checkpoint

The active product boundary is ZN-owned across resident runtime, provider cognition, local terminal/PTTY, web sensing, communication lifecycle, Electron main/preload/protocol, the React workbench, and now the formal desktop package/build identity path.

M5/M6 now has:

- resident-backed durable work/thread continuity;
- real resident-backed local workspace/folder association;
- contextual resident-backed file/diff/terminal artifacts;
- resident-owned provider/settings editing with secure credential references and hot cognition reconfiguration;
- durable active work-run identity plus resident-derived ongoing progress while work continues without the desktop.

The M7 package-identity seam is now materially advanced:

- `apps/desktop/package.json` identifies the desktop product as `zn-desktop` / `ZN` and points at the ZN repository;
- package-level builder metadata uses `ai.zn.desktop`, executable/product `ZN`, `ZN-*` artifacts and only the `zn` protocol;
- the normal builder command explicitly selects `electron-builder.zn.yml`;
- the ZN builder override registers only `zn://` and explicitly includes the staged `build/zn-runtime` payload;
- the obsolete inherited install-stamp/bootstrap resource is no longer part of the formal build path;
- Windows `afterPack` PE stamping now writes ZN product/company identity instead of Hermes/Nous Research identity;
- Windows rollback preservation defaults to `ZN.exe`;
- macOS notarization temporary key material uses a ZN-owned temporary filename prefix;
- npm workspace lock metadata now agrees with the `zn-desktop` package identity;
- formal package/build-hook identity is protected by regression tests.

This does **not** mean all M7/M8 release work is complete. Formal installers still need deliberate build/verification, and inactive inherited source/dependency/script debt remains outside the active product identity seam.

## M5/M6 product loop

### Resident-backed work/thread continuity

`ResidentWorkLedger` owns durable work threads/messages beside kernel state. Work enters the same `ZNResidentRuntime` event loop. Renderer localStorage is bounded convenience state only. Resident RPC owns work list/create/get/start/progress/submit.

### Durable active work and ongoing progress

`work_runs` durably links accepted resident events to their work thread and originating message before completion. `work_start` returns after resident acceptance instead of making an Electron request own cognition lifetime. The resident can continue while the desktop is disconnected. Completed work finalizes idempotently into durable ZN/activity messages and artifacts, including after resident reconstruction.

`work_progress` reports actual event/working state and can include current matching Thought, investigation progress and recent same-event Body evidence. The renderer samples that resident state; it does not manufacture progress or persist progress truth in browser storage.

### Workspace and contextual artifacts

Each thread can persist one canonical resident `WorkspaceAssociation`. Electron uses an OS folder picker; resident re-verifies the directory. Canonical workspace/workdir context reaches native Git/body movement.

`WorkArtifact` records are resident-owned and bounded. Current contextual kinds include file, diff and terminal. File previews remain workspace-contained; terminal evidence comes only from actual same-event body/terminal actions. The workbench renders artifacts in the optional context panel rather than a permanent IDE file tree/terminal.

### Resident-owned provider/credential settings

Provider settings persist non-secret config through the resident. UI-entered secrets use resident credential references and OS keyring storage where available; raw secrets are never returned through settings RPC or written by the UI flow into YAML. The packaged runtime carries its secure-store dependency. Cognition resources hot-reconfigure without replacing resident identity/store/memory/life, and missing external credentials degrade to explicit unavailable cognition rather than resident death.

## Browser and outbound-media investigation result

A browser contextual surface is **not** claimed yet. The mature inherited browser stack is tightly coupled to inherited configuration/plugin/session/provider ownership plus Node/Chromium/`agent-browser`; the independent ZN runtime currently has no clean resident-owned browser action seam. Mounting that old stack or relabeling web search as browser interaction would violate the architecture.

Telegram outbound media is also still intentionally pending. `OutboundMediaPathPolicy` already provides the local-file authorization boundary and Telegram `ChannelMessage` can carry attachments, but the resident outcome path does not yet have an explicit structured contract nominating an artifact/path for egress. The adapter must not guess local paths and silently turn them into upload authority.

## Current subsystem ledger

### Resident organism / kernel

Status: **ZN-native resident organism active**.

Persistent life, Situation/Thought/Will, nervous memory, native investigation/action/learning, sensing and bounded external cognition remain resident-owned. Zero-model boot/life is a hard behavior contract.

### Work/thread/workspace/artifact continuity

Status: **resident-backed durable work + active-run progress + workspace + contextual file/diff/terminal artifacts active; M6 still partial**.

Remaining product work includes a real browser body/sense seam only when justified, broader artifact/history rendering where concrete outputs require it, and final accessibility/keyboard/visual polish.

### External cognitive resources/settings

Status: **ZN-native resource layer plus resident-owned default provider/credential editor active**.

OpenAI-compatible, Anthropic and Gemini resources are ZN-owned. Advanced multi-route authoring remains intentionally outside the simple editor and is preserved rather than flattened.

### Local terminal / computer body

Status: **ZN local terminal/PTTY active with contextual resident presentation**.

Foreground/background execution, cwd continuity, cleanup, bounded output and interactive PTY lifecycle are ZN-owned. Workbench terminal presentation is evidence, not execution ownership.

### Web/world sense

Status: **ZN-owned search/extract providers and network safety active; browser automation not yet owned**.

### Communication channels

Status: **resident-owned framework and Telegram text/inbound media active; outbound attachment transport pending explicit resident egress nomination**.

### Python/runtime package ownership

Status: **M1 complete for the active packaged resident path**.

The independent `runtime/python` `znagent` distribution boots through `zn_agent.resident` / `zn-resident`. Runtime staging/verification rejects inherited `hermes_cli` and formal release staging builds a self-contained `build/zn-runtime` from portable CPython plus this distribution.

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

Status: **formal package identity seam verified; M7 overall still in progress**.

Completed/verified in source:

- ZN package/repository/product/app/executable/artifact identity;
- ZN-only formal protocol registration;
- ZN-only active Windows PE identity stamping;
- ZN-owned formal runtime resource path;
- inherited install-stamp removed from active formal packaging;
- npm lock synchronized to `zn-desktop`;
- formal release workflow already stages self-contained `zn-runtime` before electron-builder.

Still pending:

- deliberately build and inspect formal installer artifacts around this corrected shape;
- verify installer contents/runtime manifest/entrypoints on actual artifacts;
- clean-machine installation and continuity gates;
- autostart and N → N+1 release validation;
- signing/notarization only when configured as release hardening;
- eventual cleanup of inactive inherited source/dependency/script debt without regressing active ownership.

## Ownership/behavior tests protecting the active path

The suite now protects, among other behavior:

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
M7  formal packaging around owned product                  IN PROGRESS; package identity seam verified
M8  clean-machine/continuity multi-OS validation           NOT STARTED as release gate
M9  product completeness/hardening                         LATER
M10 repository migration / formal main promotion           LATER; main untouched
```

## Immediate next development sequence

1. perform a deliberately scoped formal-package validation around the corrected ZN package identity and existing self-contained `zn-runtime` staging, without yet spending the full multi-OS/clean-machine matrix;
2. fix any package-content/runtime-entrypoint debt exposed by that real artifact inspection;
3. add a browser body/sense seam only if a clean ZN-owned implementation can be isolated from inherited browser/session ownership;
4. define explicit resident artifact/message egress nomination before wiring Telegram outbound attachments through `OutboundMediaPathPolicy`;
5. broaden artifact rendering/history only where concrete work output requires it;
6. only after M7 artifacts are genuinely valid, spend M8 budget on clean-machine install, autostart, continuity and N → N+1 validation.

The architecture driver remains the owned resident/workbench/product loop and independently bootable ZN package—not compatibility with inherited control planes.