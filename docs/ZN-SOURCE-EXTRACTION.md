# ZN source adoption and extraction status

> Governing contract: [`../ZN.md`](../ZN.md)
>
> Active branch: `dev/zn-agent`
>
> Current status: **physical source evacuation complete; active repository is ZN-only**.

## 1. Purpose

This file is no longer a migration plan for an in-tree reference product. That phase is complete.

Its continuing purpose is to define how ZN may study and adopt mature implementation from Git history or external/upstream repositories without importing another product control plane.

## 2. Current verified state — 2026-08-23

The active development tree now has these ownership boundaries:

```text
runtime/python/zn_agent/core/   resident core
runtime/python/zn_agent/        installed ZN package
runtime/python/pyproject.toml    ZN Python distribution metadata
tests/zn_agent/core/             resident verification
apps/desktop/                    ZN desktop only
.github/workflows/               ZN CI / release automation only
```

The bulk source evacuation was committed on `dev/zn-agent` as:

```text
6d5f78d22883857fcc99aff5cfd4ba1b9a2d3e6b
refactor: evacuate inherited source from ZN
```

The verifying CI run was `32669071891`. Its one-shot migration job proved, on the physically reduced tree before committing it:

- a fresh ZN-only Node lock/install;
- isolated ZN Python installation and zero-model resident boot;
- full `tests/zn_agent/core` discovery: 382 tests passed;
- desktop typecheck/bundle and 37 desktop tests passed;
- 8 retained release/runtime script tests passed;
- ZN-only Docker image build and zero-model resident boot;
- generated verification artifacts were excluded from the commit;
- the verified deleted tree was committed and pushed to `dev/zn-agent`.

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
8. clean build/test/package/release does not require the reference repository;
9. applicable license/provenance obligations are retained.

Copying mature implementation is allowed. Cosmetic originality is not a goal. Ownership transfer and product fit are the goal.

## 4. Forbidden regressions

Do not reintroduce another product or agent framework as:

- resident runtime or main loop;
- identity/memory/Will owner;
- CLI or gateway brain;
- provider/plugin control plane;
- desktop main/preload/renderer shell;
- Python distribution;
- build/package/release dependency;
- required checkout, submodule or source path.

A broken test or build is not permission to restore a removed control plane. Fix the ZN caller/contract or adapt the needed mechanism into ZN ownership.

## 5. Reference access after closure

Reference access belongs outside the active development tree:

```text
Git history
or
external/upstream repository
```

If a future investigation studies a mature mechanism, record only the durable result that matters to ZN: the need, chosen design, provenance/license obligation if applicable, tests and active caller. Do not recreate a permanent source quarry inside this repository.

## 6. Retained ZN research documents

The following documents remain because they describe ZN architecture/research rather than an in-tree migration dependency:

- `ZN-MEMORY-LEARNING.md`;
- `ZN-LEARNING-SOURCE-RESEARCH.md`;
- `ZN-NEXT-PHASE.md`;
- `ZN-SELF-MAINTENANCE.md`.

Historical migration-only documents should not be retained merely for nostalgia; Git history already preserves them.

## 7. Ongoing verification

Steady-state CI and ownership tests should continue to prove:

- the installed Python package is `zn_agent`;
- core source is physically under `runtime/python/zn_agent/core`;
- tests run from `tests/zn_agent/core`;
- root Node workspace is ZN-owned;
- desktop build uses the ZN builder configuration;
- package/runtime verifiers reject foreign product package/control-plane content;
- zero-model resident boot remains valid;
- no clean ZN build requires a reference source checkout.

If this file and the real repository ever disagree, the real tree and real CI win; update this ledger immediately.