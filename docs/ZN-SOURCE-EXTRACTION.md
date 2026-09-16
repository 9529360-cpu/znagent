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

## 4. Forbidden regressions

Do not reintroduce another product or agent framework as:

- resident runtime or main loop;
- identity/memory/Will owner;
- CLI or gateway brain;
- provider/plugin control plane;
- desktop main/preload/renderer shell;
- desktop layout/navigation/component/theme owner;
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
- package/runtime verifiers reject foreign product package/control-plane content;
- zero-model resident boot remains valid;
- no clean ZN build requires a reference source checkout;
- tracked source-boundary scanning remains green.

If this file and the real repository ever disagree, the real tree and real CI win; update this ledger immediately.
