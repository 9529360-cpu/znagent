# ZN

ZN is a Windows-first resident personal assistant. The repository owns the Resident runtime, desktop surface, real-computer capabilities, tests, packaging and release automation. External models are optional cognitive resources; they do not own ZN identity, memory, Work, Will, action authority or lifecycle.

## Run ZN from source

The source-development path is intentionally one command after prerequisites are present:

```powershell
npm run dev
```

On the first run, that command will:

1. install the locked Node workspace dependencies when needed;
2. create `.venv` with a supported Python interpreter;
3. install the ZN Python runtime with managed-browser support;
4. install the repository-pinned Playwright Chromium runtime;
5. build the Electron desktop in development mode;
6. launch the existing Desktop -> Resident product path.

Later runs reuse the prepared environment unless the dependency inputs changed.

### Prerequisites

The current product acceptance target is Windows x64. Source development requires:

- Node.js **22.22.0 or newer**;
- Python **3.11, 3.12 or 3.13**; Python 3.12 is recommended;
- npm, which is included with Node.js;
- network access on the first setup so npm/Python/Playwright dependencies can be installed.

No manual `ZN_AGENT_HOME`, `PYTHONPATH`, Resident endpoint, or Electron command is required for the normal source path.

If several Python installations exist, you can pin the interpreter used to create `.venv`:

```powershell
$env:ZN_DEV_PYTHON = 'C:\Python312\python.exe'
npm run setup
```

## Setup and diagnostics

Prepare dependencies without opening the desktop:

```powershell
npm run setup
```

Check the prepared source environment without changing it:

```powershell
npm run doctor
```

Run only the fast source-bootstrap contract tests:

```powershell
npm run test:dev-bootstrap
```

Normal repository checks remain available:

```powershell
npm run typecheck
npm test
```

The desktop typecheck gate also runs the fast bootstrap contract tests before TypeScript compilation.

## Development isolation

`npm run dev` is a source-development instance, not the installed-production identity.

By default it uses repository-local ignored state:

```text
.dev/zn-home/              Resident state and endpoint
.dev/electron-user-data/   Electron profile/session state
.dev/playwright-browsers/  managed Chromium runtime
.venv/                     Python environment
```

The source instance deliberately does **not** register `zn://` as the OS protocol handler and does **not** install Resident login autostart. This prevents ordinary source development from taking over system integration or durable state owned by an installed ZN build. Packaged builds keep the existing production protocol/autostart behavior.

Advanced development overrides are available when isolation needs to live elsewhere:

```powershell
$env:ZN_DEV_AGENT_HOME = 'D:\zn-dev\resident'
$env:ZN_DEV_USER_DATA = 'D:\zn-dev\electron'
npm run dev
```

Do not point those variables at a real installed ZN home/profile merely to reuse state.

## First useful interaction

ZN can start without a cloud model. Deterministic/local Resident paths remain available, while model-backed cognition reports that a provider is unavailable until configured.

Open **Settings -> Models & providers** in the desktop when a model-backed task needs a provider. Provider credentials stay behind the Resident credential boundary; the renderer does not persist stored secrets.

The repository deliberately describes many capabilities as bounded or representative paths rather than claiming arbitrary-browser, arbitrary-Windows or complete Office automation. The acceptance rule is user-goal completion backed by fresh real-world evidence, not merely a successful model/tool call.

## Repository layout

- `runtime/python/zn_agent/core/` — Resident core and product composition
- `tests/zn_agent/core/` — Resident verification
- `apps/desktop/` — ZN Electron desktop and release packaging
- `scripts/zn-dev.mjs` — source setup/doctor/dev entrypoint
- `.github/workflows/` — CI, real Windows E2E, clean-install and release automation
- `ZN.md` — governing product and engineering contract
- `docs/ZN-REAL-TASK-E2E-CATALOG.md` — ordinary-user task acceptance catalog
- `docs/ZN-IMPLEMENTATION-STATUS.md` — current implementation truth
- `docs/ZN-SOURCE-EXTRACTION.md` — source-adoption/provenance boundary

Historical reference source is not kept in the active development tree. Mature mechanisms may be studied from Git history or external sources, then adapted behind ZN-owned interfaces and verification.
