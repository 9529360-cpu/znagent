# ZN source adoption and extraction status

> Governing contract: [`../ZN.md`](../ZN.md)
>
> Canonical branch: `main`
>
> Active development: short-lived verified `work/*` branches start from current `main`; no permanent `dev/zn-agent` synchronization contract remains.
>
> Current status: **physical source evacuation complete; active repository is ZN-only**.

## 1. Purpose

This file is no longer a migration plan for an in-tree reference product. That phase is complete.

Its continuing purpose is to define how ZN may study and adopt mature implementation from a dedicated read-only reference branch, Git history, or external/upstream repositories without importing another product control plane.

## 2. Current verified state

The active tree has these ownership boundaries:

```text
runtime/python/zn_agent/core/   resident core
runtime/python/zn_agent/        installed ZN package
runtime/python/pyproject.toml    ZN Python distribution metadata
tests/zn_agent/core/            resident verification
apps/desktop/                    ZN desktop only
.github/workflows/               ZN CI / release automation only
```

The bulk source evacuation commit is:

```text
6d5f78d22883857fcc99aff5cfd4ba1b9a2d3e6b
```

One-shot verification run `32669071891` proved the physically reduced tree before the migration machinery was retired:

- fresh ZN-only Node lock/install;
- isolated ZN Python installation and zero-model resident boot;
- full `tests/zn_agent/core` discovery: 382 tests passed;
- desktop typecheck/bundle and 37 desktop tests passed;
- 8 retained release/runtime script tests passed;
- ZN-only Docker image build and zero-model resident boot;
- generated verification artifacts excluded from the commit;
- verified deleted tree committed and pushed.

M10 later promoted the verified ZN tree to canonical `main` without history rewrite. New product work now branches from current `main` and returns through normal verified review/promotion flow; retired migration/development branch names are not product architecture or synchronization requirements.

The one-shot migration job and migration script are not part of the steady-state architecture.

## 3. Extraction/adoption standard

A mature external mechanism may be adopted only when all of the following are true:

1. ZN has a concrete product need;
2. the mechanism is understood before copying or adaptation;
3. the production entrypoint is ZN-owned;
4. public interfaces and configuration are ZN-owned;
5. resident identity/state/lifecycle remain ZN-owned;
6. external product assumptions and control-plane dependencies are removed;
7. ZN tests cover the owned behavior and important edge cases;
8. clean build/test/package/release does not require the reference source;
9. applicable license/provenance obligations are retained.

Copying mature implementation is allowed. Cosmetic originality is not a goal. Ownership transfer and product fit are the goal.

Desktop/product UX has an additional boundary: external products may be studied for failure modes, interaction lessons, installer edge cases, or protocol behavior, but ZN does not adopt their desktop layout, navigation hierarchy, component tree, theme, renderer state model, or visual identity. Active desktop composition and styling remain ZN-owned under `apps/desktop/`; external desktop source is reference material only.

### 3a. User-directed exemption: open-claude-ui desktop presentation (2026-10-19)

The desktop boundary above is expressly exempted for one snapshot, by direct
user instruction ("按 open-claude-ui 原样复原用作 ZN 桌面"):

- **Snapshot:** `vendor/open-claude-ui/`, upstream
  https://github.com/Caho1/open-claude-ui.git @ `4045ce76`, MIT license,
  provenance recorded in `vendor/open-claude-ui/VENDOR.json`. All files
  under `vendor/open-claude-ui/src/`, `code-examples/`, `docs/` and
  `scripts/` are byte-identical to that commit; the only renames are the
  three `UPSTREAM-*` prose files, contents untouched.
- **Scope of the exemption:** desktop *presentation* only — the CDS design
  tokens (`cds-theme.css`), the Tailwind theme in the vendored
  `tailwind.config.js`, and the React presentation components composed by
  `apps/desktop/src/zn/` wrappers. The exemption covers no other product,
  no other directory, and no other layer.
- **What stays ZN-owned (never exempted):** Electron main/preload/IPC,
  Resident connection, workspace/update/protocol/tray/window-mode logic,
  renderer wiring and state, identity/memory/lifecycle, and every data
  call (`resident-client.ts`). Vendored components receive only real ZN
  data through their props; components whose props cannot carry ZN data
  (hardcoded demo sessions, Claude model menus, fake file mentions,
  simulated tool execution) are *not* rendered — see `apps/desktop/src/zn/cds.ts`.
- **No hand edits:** a vendored file is never edited to change its look.
  When ZN needs different behaviour, the wrapper lives in
  `apps/desktop/src/zn/`, not in `vendor/`. To update: re-copy from a
  pinned upstream commit, update `VENDOR.json`, re-run the byte-diff
  against upstream plus the TypeScript verification.
- **Precedence:** the user instruction outranks this document. If this
  exemption and any other clause of this file disagree, the exemption
  wins for the snapshot above only, and the rest of the file still applies.

## 4. Forbidden regressions

Do not reintroduce another product or agent framework as:

- resident runtime or main loop;
- identity/memory/Will owner;
- CLI or gateway brain;
- provider/plugin control plane;
- desktop main/preload/renderer shell;
- desktop layout/navigation/component/theme owner — except the
  open-claude-ui presentation snapshot expressly exempted in §3a, which
  owns desktop presentation components/tokens only and never the shell,
  wiring, state, or data layer;
- Python distribution;
- build/package/release dependency;
- required checkout, submodule or source path.

A broken test or build is not permission to restore a removed control plane. Fix the ZN caller/contract or adapt the needed mechanism into ZN ownership.

## 5. Reference access after closure

Reference access belongs outside the active development tree:

```text
dedicated read-only reference branch
or
Git history
or
external/upstream repository
```

Any dedicated reference branch is quarry material for maintainers only. It must not be merged back wholesale, added as a submodule, included in packaging, or treated as a build/runtime dependency.

The one exception is the open-claude-ui snapshot exempted in §3a: it lives
in-tree at `vendor/open-claude-ui/` by explicit user direction, pinned to
one upstream commit, byte-identical, MIT-licensed, and bundled only as
desktop presentation. It is not a submodule, not a Resident dependency,
and not a control plane.

If a future investigation studies a mature mechanism, record only the durable result that matters to ZN: the need, chosen design, provenance/license obligation if applicable, tests and active caller. Do not recreate a permanent source quarry inside the active tree.

## 6. Retained ZN research documents

Retain documents that describe current ZN architecture or active research, including:

- `ZN-MEMORY-LEARNING.md`;
- `ZN-LEARNING-SOURCE-RESEARCH.md`;
- `ZN-NEXT-PHASE.md`.

Retired directions such as the former standalone self-maintenance program are historical inputs, not current product-stage claims. Git history preserves migration-only and retired planning material; do not cite it as a live implementation direction merely because an old branch once did.

## 7. Ongoing verification

Steady-state CI and ownership tests must continue to prove:

- the installed Python package is `zn_agent`;
- core source is physically under `runtime/python/zn_agent/core`;
- tests run from `tests/zn_agent/core`;
- root Node workspace is ZN-owned;
- desktop build uses the ZN builder configuration;
- active desktop layout/components/styles remain ZN-owned and do not depend on an external product desktop;
- the open-claude-ui exemption (§3a) stays within scope: vendored files
  byte-identical to the pinned upstream commit, ZN wrappers carry all
  wiring, and no vendored component renders demo data or simulated
  execution as if it were ZN reality;
- package/runtime verifiers reject foreign product package/control-plane content;
- zero-model resident boot remains valid;
- no clean ZN build requires a reference source checkout;
- tracked source-boundary scanning remains green.

If this file and the real repository ever disagree, the real tree and real CI win; update this ledger immediately.
