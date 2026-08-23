from __future__ import annotations

import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def remove(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
    elif path.exists():
        shutil.rmtree(path)


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n", encoding="utf-8")


def replace_required(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"required migration text not found in {path.relative_to(ROOT)}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def keep_only(directory: Path, allowed: set[str]) -> None:
    if not directory.exists():
        return
    for child in directory.iterdir():
        if child.name not in allowed:
            remove(child)


# The final dev tree is an allowlist. Anything inherited outside these ZN-owned
# roots/files is removed instead of being retained as an unreviewed quarry.
root_dirs = {".agent", ".github", "apps", "docs", "runtime", "tests"}
root_files = {
    ".gitignore",
    "AGENTS.md",
    "Dockerfile",
    "LICENSE",
    "README.md",
    "ZN.md",
    "package-lock.json",
    "package.json",
}
for child in ROOT.iterdir():
    if child.name == ".git":
        continue
    if child.is_dir() and not child.is_symlink():
        if child.name not in root_dirs:
            remove(child)
    elif child.name not in root_files:
        remove(child)

# .agent is durable maintainer handoff only after this one-shot script exits.
keep_only(ROOT / ".agent", {"HANDOFF.md", "purge_hermes_source.py"})

# GitHub product automation is intentionally ZN-only.
github = ROOT / ".github"
if github.exists():
    keep_only(github, {"workflows"})
    keep_only(
        github / "workflows",
        {"zn-ci.yml", "zn-linux-appimage-update-smoke.yml", "zn-release.yml"},
    )

# Preserve only ZN architecture/status/provenance documentation.
docs = ROOT / "docs"
if docs.exists():
    for child in docs.iterdir():
        if not child.name.startswith("ZN-"):
            remove(child)

# Python verification belongs to the physical zn_agent namespace only.
keep_only(ROOT / "tests", {"zn_agent"})
keep_only(ROOT / "runtime", {"python"})

# Desktop is the only application retained in this repository.
keep_only(ROOT / "apps", {"desktop"})
desktop = ROOT / "apps" / "desktop"
keep_only(
    desktop,
    {
        "assets",
        "electron",
        "electron-builder.zn.yml",
        "package.json",
        "scripts",
        "src",
        "tsconfig.electron.json",
        "tsconfig.json",
        "vitest.config.ts",
    },
)

# Renderer: retain only the independent ZN workbench.
src = desktop / "src"
keep_only(src, {"zn"})

# Electron: retain the ZN control plane plus macOS entitlement policy.
electron = desktop / "electron"
if electron.exists():
    for child in electron.iterdir():
        keep = child.name.startswith("zn-") or child.name in {
            "entitlements.mac.plist",
            "entitlements.mac.inherit.plist",
        }
        if not keep:
            remove(child)

# Packaging/tooling: retain scripts that are explicitly ZN release/runtime
# machinery, plus the small generic hooks needed by electron-builder.
scripts = desktop / "scripts"
generic_scripts = {
    "before-build.mjs",
    "bundle-electron-main.mjs",
    "notarize.mjs",
    "patch-electron-builder-mac-binary.mjs",
    "run-electron-builder.mjs",
}
if scripts.exists():
    for child in scripts.iterdir():
        keep = child.is_file() and (
            "zn" in child.name.lower() or child.name in generic_scripts
        )
        if not keep:
            remove(child)

# Remove the last inherited product marker from the retained macOS packaging
# workaround; its behavior remains unchanged.
patcher = scripts / "patch-electron-builder-mac-binary.mjs"
if patcher.exists():
    patcher.write_text(
        patcher.read_text(encoding="utf-8").replace(
            "hermes-macos-electron-binary-fallback",
            "zn-macos-electron-binary-fallback",
        ),
        encoding="utf-8",
    )

# The pre-evacuation desktop tests still read duplicated package.json build
# metadata and packaging hooks that this migration deliberately removes. Rewrite
# only those exact contracts so the verified post-purge tree tests the single
# ZN builder config and proves the retired hook chain is physically absent.
replace_required(
    electron / "zn-desktop-ownership.test.ts",
    """test('formal Linux desktop identity keeps launcher and running window aligned', () => {
  const pkg = JSON.parse(read('package.json'))
  const builder = read('electron-builder.zn.yml')

  assert.equal(pkg.desktopName, 'ai.zn.desktop')
  assert.equal(pkg.build?.appId, 'ai.zn.desktop')
  assert.equal(pkg.build?.linux?.syncDesktopName, true)
  assert.equal(pkg.build?.linux?.desktop?.entry?.StartupWMClass, 'ai.zn.desktop')
  assert.match(builder, /^appId:\\s+ai\\.zn\\.desktop$/m)
  assert.match(builder, /^\\s+syncDesktopName:\\s+true$/m)
  assert.match(builder, /^\\s+StartupWMClass:\\s+ai\\.zn\\.desktop$/m)
})""",
    """test('formal Linux desktop identity is owned by the single ZN builder config', () => {
  const pkg = JSON.parse(read('package.json'))
  const builder = read('electron-builder.zn.yml')

  assert.equal(pkg.desktopName, 'ai.zn.desktop')
  assert.equal(pkg.build, undefined)
  assert.match(pkg.scripts?.builder || '', /--config electron-builder\\.zn\\.yml/)
  assert.match(builder, /^appId:\\s+ai\\.zn\\.desktop$/m)
  assert.match(builder, /^\\s+syncDesktopName:\\s+true$/m)
  assert.match(builder, /^\\s+StartupWMClass:\\s+ai\\.zn\\.desktop$/m)
})""",
)

replace_required(
    electron / "zn-packaged-runtime.test.ts",
    """test('formal desktop package, hooks and builder expose only ZN product identity', () => {
  const packageJson = JSON.parse(fs.readFileSync(path.join(desktopRoot, 'package.json'), 'utf8'))
  const build = packageJson.build
  const schemes = (build.protocols || []).flatMap((item: { schemes?: string[] }) => item.schemes || [])
  const resources = (build.extraResources || []).map((item: { from?: string }) => item.from)

  assert.equal(packageJson.name, 'zn-desktop')
  assert.equal(packageJson.productName, 'ZN')
  assert.equal(packageJson.repository?.url, 'git+https://github.com/9529360-cpu/znagent.git')
  assert.equal(build.appId, 'ai.zn.desktop')
  assert.equal(build.productName, 'ZN')
  assert.equal(build.executableName, 'ZN')
  assert.deepEqual(schemes, ['zn'])
  assert.match(build.artifactName, /^ZN-/)
  assert.deepEqual(resources.includes('build/zn-runtime'), true)
  assert.deepEqual(resources.includes('build/install-stamp.json'), false)
  assert.doesNotMatch(packageJson.scripts?.build || '', /write-build-stamp/)
  assert.match(packageJson.scripts?.builder || '', /--config electron-builder\\.zn\\.yml/)

  const publicIdentity = JSON.stringify({
    name: packageJson.name,
    productName: packageJson.productName,
    description: packageJson.description,
    author: packageJson.author,
    repository: packageJson.repository,
    build
  })
  assert.doesNotMatch(publicIdentity, /hermes|nousresearch/i)

  const builder = fs.readFileSync(path.join(desktopRoot, 'electron-builder.zn.yml'), 'utf8')
  assert.match(builder, /^appId: ai\\.zn\\.desktop$/m)
  assert.match(builder, /^productName: ZN$/m)
  assert.match(builder, /^\\s+- zn$/m)
  assert.match(builder, /from: build\\/zn-runtime/)
  assert.doesNotMatch(builder, /install-stamp|hermes/i)

  const activeHooks = [
    'scripts/before-build.mjs',
    'scripts/before-pack.mjs',
    'scripts/after-pack.mjs',
    'scripts/set-exe-identity.mjs',
    'scripts/notarize.mjs'
  ].map(relative => fs.readFileSync(path.join(desktopRoot, relative), 'utf8')).join('\\n')
  assert.match(activeHooks, /ProductName: 'ZN'/)
  assert.match(activeHooks, /CompanyName: 'ZN Project'/)
  assert.doesNotMatch(activeHooks, /Hermes|Nous Research|install\\.ps1|hermes_cli|hermes-notary/i)
})""",
    """test('formal desktop package and builder expose only ZN product identity', () => {
  const packageJson = JSON.parse(fs.readFileSync(path.join(desktopRoot, 'package.json'), 'utf8'))
  const builder = fs.readFileSync(path.join(desktopRoot, 'electron-builder.zn.yml'), 'utf8')

  assert.equal(packageJson.name, 'zn-desktop')
  assert.equal(packageJson.productName, 'ZN')
  assert.equal(packageJson.repository?.url, 'git+https://github.com/9529360-cpu/znagent.git')
  assert.equal(packageJson.build, undefined)
  assert.doesNotMatch(packageJson.scripts?.build || '', /write-build-stamp/)
  assert.match(packageJson.scripts?.builder || '', /--config electron-builder\\.zn\\.yml/)

  assert.match(builder, /^appId: ai\\.zn\\.desktop$/m)
  assert.match(builder, /^productName: ZN$/m)
  assert.match(builder, /^executableName: ZN$/m)
  assert.match(builder, /^artifactName: ZN-/m)
  assert.match(builder, /^\\s+- zn$/m)
  assert.match(builder, /from: build\\/zn-runtime/)
  assert.match(builder, /^\\s+legalTrademarks: ZN$/m)
  assert.doesNotMatch(builder, /install-stamp|hermes|beforePack|afterPack/i)

  const publicIdentity = `${JSON.stringify({
    name: packageJson.name,
    productName: packageJson.productName,
    description: packageJson.description,
    author: packageJson.author,
    repository: packageJson.repository
  })}\\n${builder}`
  assert.doesNotMatch(publicIdentity, /hermes|nousresearch/i)

  for (const retiredHook of [
    'scripts/before-pack.mjs',
    'scripts/after-pack.mjs',
    'scripts/set-exe-identity.mjs',
    'scripts/stage-native-deps.mjs'
  ]) {
    assert.equal(fs.existsSync(path.join(desktopRoot, retiredHook)), false)
  }

  const activeHooks = [
    'scripts/before-build.mjs',
    'scripts/notarize.mjs'
  ].map(relative => fs.readFileSync(path.join(desktopRoot, relative), 'utf8')).join('\\n')
  assert.doesNotMatch(activeHooks, /Hermes|Nous Research|install\\.ps1|hermes_cli|hermes-notary/i)
})""",
)

root_package = {
    "name": "znagent",
    "version": "0.17.0",
    "private": True,
    "description": "Repository-owned runtime, desktop and release automation for ZN.",
    "workspaces": ["apps/desktop"],
    "scripts": {
        "build": "npm run build --workspace apps/desktop",
        "typecheck": "npm run typecheck --workspace apps/desktop",
        "test": "npm run test --workspace apps/desktop",
    },
    "repository": {
        "type": "git",
        "url": "git+https://github.com/9529360-cpu/znagent.git",
    },
    "license": "MIT",
    "engines": {"node": ">=22.22.0"},
}
write(ROOT / "package.json", json.dumps(root_package, indent=2))

desktop_package = {
    "name": "zn-desktop",
    "productName": "ZN",
    "desktopName": "ai.zn.desktop",
    "private": True,
    "version": "0.17.0",
    "description": "Native desktop workbench for the ZN resident.",
    "author": "ZN Project",
    "repository": {
        "type": "git",
        "url": "git+https://github.com/9529360-cpu/znagent.git",
    },
    "type": "module",
    "main": "dist/electron-main.mjs",
    "engines": {"node": ">=22.22.0"},
    "scripts": {
        "build": "node scripts/bundle-electron-main.mjs --release",
        "bundle:dev": "node scripts/bundle-electron-main.mjs --dev",
        "typecheck": "tsc -p tsconfig.json --noEmit && tsc -p tsconfig.electron.json --noEmit",
        "test": "vitest run --config vitest.config.ts",
        "prebuilder": "node scripts/patch-electron-builder-mac-binary.mjs",
        "builder": "node scripts/run-electron-builder.mjs --config electron-builder.zn.yml",
    },
    "dependencies": {
        "electron-updater": "6.8.9",
        "react": "19.2.7",
        "react-dom": "19.2.7",
    },
    "devDependencies": {
        "@types/node": "22.20.1",
        "@types/react": "19.2.17",
        "@types/react-dom": "19.2.3",
        "electron": "40.10.2",
        "electron-builder": "26.15.3",
        "electron-builder-squirrel-windows": "26.15.3",
        "esbuild": "0.28.1",
        "typescript": "6.0.3",
        "vitest": "4.1.10",
    },
}
write(desktop / "package.json", json.dumps(desktop_package, indent=2))

write(
    desktop / "tsconfig.json",
    json.dumps(
        {
            "compilerOptions": {
                "target": "ES2023",
                "useDefineForClassFields": True,
                "lib": ["DOM", "DOM.Iterable", "ES2023"],
                "types": ["node"],
                "skipLibCheck": True,
                "esModuleInterop": True,
                "allowSyntheticDefaultImports": True,
                "strict": True,
                "forceConsistentCasingInFileNames": True,
                "module": "ESNext",
                "moduleResolution": "Bundler",
                "resolveJsonModule": True,
                "isolatedModules": True,
                "jsx": "react-jsx",
            },
            "include": ["src/zn"],
        },
        indent=2,
    ),
)

write(
    desktop / "tsconfig.electron.json",
    json.dumps(
        {
            "compilerOptions": {
                "target": "ES2023",
                "lib": ["ES2023"],
                "types": ["node"],
                "skipLibCheck": True,
                "esModuleInterop": True,
                "allowSyntheticDefaultImports": True,
                "strict": True,
                "forceConsistentCasingInFileNames": True,
                "module": "ESNext",
                "moduleResolution": "Bundler",
                "resolveJsonModule": True,
                "noEmit": True,
            },
            "include": ["electron/zn-*.ts"],
        },
        indent=2,
    ),
)

write(
    desktop / "vitest.config.ts",
    """import { defineConfig } from 'vitest/config'\n\nexport default defineConfig({\n  test: {\n    environment: 'node',\n    include: ['electron/zn-*.test.ts']\n  }\n})""",
)

write(
    src / "zn" / "desktop-env.d.ts",
    """declare module '*.css' {\n  const stylesheet: string\n  export default stylesheet\n}\n\ntype ZnDesktopPayload = Record<string, unknown>\n\ntype ZnDesktopDeepLink = {\n  url: string\n  route: string\n  path: string\n  params: Record<string, string>\n}\n\ntype ZnDesktopUpdateStatus = {\n  supported: boolean\n  currentVersion: string\n  updateAvailable: boolean\n  availableVersion?: string\n  releaseUrl?: string\n  assetName?: string\n  releaseNotes?: unknown\n  downloadState?: 'idle' | 'downloading' | 'ready' | 'failed'\n  downloadedBytes?: number\n  downloadTotalBytes?: number\n  downloadError?: string\n  message?: string\n}\n\ntype ZnDesktopUpdateApplyResult = {\n  ok: boolean\n  message?: string\n  error?: string\n}\n\ntype ZnDesktopResidentBridge = {\n  start: () => Promise<unknown>\n  stop: () => Promise<unknown>\n  status: () => Promise<unknown>\n  self: () => Promise<unknown>\n  providerSettings: () => Promise<unknown>\n  providerSettingsUpdate: (payload: ZnDesktopPayload) => Promise<unknown>\n  workList: (payload: ZnDesktopPayload) => Promise<unknown>\n  workCreate: (payload: ZnDesktopPayload) => Promise<unknown>\n  workGet: (payload: ZnDesktopPayload) => Promise<unknown>\n  workStart: (payload: ZnDesktopPayload) => Promise<unknown>\n  workProgress: (payload: ZnDesktopPayload) => Promise<unknown>\n  workSubmit: (payload: ZnDesktopPayload) => Promise<unknown>\n  pulses: (limit?: number) => Promise<unknown>\n  situations: (limit?: number) => Promise<unknown>\n  thoughts: (limit?: number) => Promise<unknown>\n  impasses: (limit?: number) => Promise<unknown>\n  learning: (limit?: number) => Promise<unknown>\n  neural: (limit?: number) => Promise<unknown>\n  perceive: (payload: ZnDesktopPayload) => Promise<unknown>\n  worldFollow: (payload: ZnDesktopPayload) => Promise<unknown>\n  worldFocuses: (payload?: ZnDesktopPayload) => Promise<unknown>\n  worldObserve: (payload: ZnDesktopPayload) => Promise<unknown>\n  submit: (payload: ZnDesktopPayload) => Promise<unknown>\n  remember: (payload: ZnDesktopPayload) => Promise<unknown>\n  forget: (key: string) => Promise<unknown>\n}\n\ndeclare interface Window {\n  znDesktop: {\n    resident: ZnDesktopResidentBridge\n    workspaces: {\n      attach: (threadId: string) => Promise<unknown>\n      detach: (threadId: string) => Promise<unknown>\n    }\n    updates: {\n      check: () => Promise<ZnDesktopUpdateStatus>\n      apply: () => Promise<ZnDesktopUpdateApplyResult>\n    }\n    shell: {\n      onDeepLink: (callback: (payload: ZnDesktopDeepLink) => void) => () => void\n    }\n  }\n}\n""",
)

write(
    desktop / "electron-builder.zn.yml",
    """electronVersion: 40.10.2\nappId: ai.zn.desktop\nproductName: ZN\nexecutableName: ZN\nprotocols:\n  - name: ZN Protocol\n    schemes:\n      - zn\nartifactName: ZN-${version}-${os}-${arch}.${ext}\nicon: assets/icon\ndirectories:\n  output: release\nfiles:\n  - dist/**\n  - assets/**\n  - package.json\nbeforeBuild: scripts/before-build.mjs\nextraResources:\n  - from: build/zn-runtime\n    to: zn-runtime\n  - from: assets/icon.ico\n    to: icon.ico\nasar: true\nafterSign: scripts/notarize.mjs\nasarUnpack:\n  - dist/**\nmac:\n  category: public.app-category.productivity\n  entitlements: electron/entitlements.mac.plist\n  entitlementsInherit: electron/entitlements.mac.inherit.plist\n  extendInfo:\n    CFBundleDisplayName: ZN\n    CFBundleExecutable: ZN\n    CFBundleName: ZN\n  gatekeeperAssess: false\n  hardenedRuntime: true\n  target:\n    - dmg\n    - zip\ndmg:\n  title: Install ZN\n  backgroundColor: '#f5f5f7'\n  iconSize: 96\n  window:\n    width: 560\n    height: 360\n  contents:\n    - x: 160\n      y: 170\n      type: file\n    - x: 400\n      y: 170\n      type: link\n      path: /Applications\nwin:\n  legalTrademarks: ZN\n  target:\n    - nsis\n    - msi\n  signAndEditExecutable: false\nlinux:\n  category: Utility\n  maintainer: ZN Project\n  synopsis: Resident AI workbench for ZN.\n  syncDesktopName: true\n  desktop:\n    entry:\n      StartupWMClass: ai.zn.desktop\n  target:\n    - AppImage\n    - deb\n    - rpm\nnsis:\n  oneClick: false\n  allowToChangeInstallationDirectory: true\n  perMachine: false\n  shortcutName: ZN\n  uninstallDisplayName: ZN\n  warningsAsErrors: false\n""",
)

write(
    ROOT / "Dockerfile",
    """FROM python:3.12-slim\n\nENV PYTHONUNBUFFERED=1 \\\n    PYTHONUTF8=1 \\\n    ZN_AGENT_HOME=/var/lib/zn\n\nWORKDIR /opt/zn\nCOPY runtime/python /opt/zn/runtime/python\nRUN python -m pip install --no-cache-dir /opt/zn/runtime/python \\\n    && useradd --create-home --uid 10001 zn \\\n    && mkdir -p /var/lib/zn \\\n    && chown -R zn:zn /var/lib/zn\n\nUSER zn\nENTRYPOINT [\"python\", \"-m\", \"zn_agent.core.resident_server\"]\n""",
)

write(
    ROOT / ".gitignore",
    """.DS_Store\n.env\n.env.*\n!.env.example\n__pycache__/\n*.py[cod]\n.pytest_cache/\n.venv/\nnode_modules/\napps/desktop/dist/\napps/desktop/build/\napps/desktop/release/\n.ci/\ncoverage/\n""",
)

write(
    ROOT / "README.md",
    """# ZN\n\nZN is a resident software agent whose identity, state, runtime, tests and release automation belong to this repository. External models are optional cognitive resources; they do not own the runtime.\n\n## Repository layout\n\n- `runtime/python/zn_agent/core/` — resident core\n- `tests/zn_agent/core/` — core verification\n- `apps/desktop/` — ZN desktop shell and release packaging\n- `.github/workflows/` — CI, update smoke and release automation\n- `ZN.md` — product architecture contract\n- `docs/ZN-SOURCE-EXTRACTION.md` — retained source provenance and extraction record\n\nHistorical reference source is not kept in the active development tree.\n""",
)

# The one-shot migration script must not survive the verified purge commit.
Path(__file__).unlink()
