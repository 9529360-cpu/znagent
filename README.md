# ZN

ZN is a resident digital subject implemented and maintained by this repository. Its software body, runtime, tests, desktop and release automation are repository-owned; its lived identity and persistent state belong to the resident continuity boundary, not to a source checkout or any external model.

External models are optional cognitive resources. They do not own ZN identity, memory, Will, action authority or runtime lifecycle.

## Run ZN from source

The normal source-development path is:

```powershell
npm run dev
```

The first run creates/reuses a repository-local `.venv` (via system Python, or via `uv` when no supported Python is present), installs the ZN Python runtime with managed-browser support, installs the version-bound Playwright Chromium payload into `.dev/playwright-browsers`, and launches the Resident engine from source (`python -m zn_agent.resident`).

Prerequisites are Node.js 22.22.0 or newer plus either `uv` (recommended) or Python 3.11-3.13. First setup needs network access for package/runtime downloads.

Useful development commands:

```powershell
npm run setup
npm run doctor
npm run test:dev-bootstrap
```

Source development is intentionally isolated from an installed ZN. By default it uses `.dev/zn-home` for Resident state, `.dev/playwright-browsers` for managed Chromium, and `.venv` for Python.

Advanced development state can be redirected with `ZN_DEV_AGENT_HOME`. Do not point that variable at an installed ZN home merely to reuse state.

To prove a clean-checkout startup end to end (spawns `npm run dev`, waits for the Resident's authenticated endpoint, performs an authenticated status RPC, then shuts down and requires the endpoint to retire):

```powershell
node scripts/verify-zn-source-start.mjs
```

## Repository layout

- `runtime/python/zn_agent/core/` — resident core
- `tests/zn_agent/core/` — core verification
- `apps/desktop/` — ZN desktop surface and release packaging
- `.github/workflows/` — CI, installed-update smoke and release automation
- `ZN.md` — product and engineering contract
- `docs/ZN-SOURCE-EXTRACTION.md` — source-adoption/provenance boundary

Historical reference source is not kept in the active development tree. Mature mechanisms may be studied from the dedicated reference branch, Git history or external sources, then adapted behind ZN-owned interfaces and tests.
