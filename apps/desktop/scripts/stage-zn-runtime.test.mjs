import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

const here = path.dirname(fileURLToPath(import.meta.url))
const source = fs.readFileSync(path.join(here, 'stage-zn-runtime.mjs'), 'utf8')

test('runtime staging derives backend root from the installed zn_agent module', () => {
  assert.match(source, /importlib\.util\.find_spec\(['"]zn_agent['"]\)/)
  assert.match(source, /Path\(spec\.origin\)\.resolve\(\)\.parent\.parent/)
  assert.match(source, /backend_root:\s*portableRelative\(runtimeRoot, backendRoot\)/)
  assert.doesNotMatch(source, /site\.getsitepackages\(\)/)
})

test('Windows runtime staging removes uv top-level Python aliases before packaging', () => {
  assert.match(source, /function removeWindowsPythonAliases\(/)
  assert.match(source, /entry\.isSymbolicLink\(\)/)
  assert.match(source, /fs\.realpathSync\(candidate\)/)
  assert.match(source, /fs\.unlinkSync\(candidate\)/)
  assert.match(source, /removeWindowsPythonAliases\(pythonInstallDir, pythonPath\)/)
  assert.match(source, /unsupported top-level aliases/)
})

test('runtime staging packages Playwright and Chromium inside the versioned ZN runtime', () => {
  assert.match(source, /const browserInstallDir = path\.join\(runtimeRoot, ['"]playwright-browsers['"]\)/)
  assert.match(source, /`\$\{runtimeProject\}\[browser\]`/)
  assert.match(source, /\['-m', 'playwright', 'install', 'chromium'\]/)
  assert.match(source, /PLAYWRIGHT_BROWSERS_PATH:\s*browserInstallDir/)
  assert.match(source, /browser_root:\s*portableRelative\(runtimeRoot, browserInstallDir\)/)
  assert.doesNotMatch(source, /PLAYWRIGHT_BROWSERS_PATH\s*:\s*(?:os\.|process\.env\.LOCALAPPDATA|process\.env\.USERPROFILE)/)
})


test('runtime staging packages the pinned Veteran engineering sidecar', () => {
  assert.match(source, /const veteranSourceRoot = path\.join\(repoRoot, ['"]vendor['"], ['"]veteran-engineer['"]\)/)
  assert.match(source, /const veteranRuntimeDir = path\.join\(runtimeRoot, ['"]veteran-engineer['"]\)/)
  assert.match(source, /Vendored Veteran runtime is incomplete/)
  assert.match(source, /fs\.cpSync\(veteranSourceRoot, veteranRuntimeDir/)
  assert.match(source, /veteran_runtime:\s*portableRelative\(runtimeRoot, veteranRuntimeDir\)/)
})


test('runtime staging transports the installed backend path as ASCII-safe JSON', () => {
  assert.match(source, /const backendRoot = JSON\.parse\(capture\(pythonPath/)
  assert.match(source, /import importlib\.util, json/)
  assert.match(source, /json\.dumps\(str\(Path\(spec\.origin\)\.resolve\(\)\.parent\.parent\)\)/)
})

test('runtime staging invokes npm CLI through the active Node executable', () => {
  assert.match(source, /function resolveNpmCli\(\)/)
  assert.match(source, /path\.join\(path\.dirname\(process\.execPath\), ['"]node_modules['"], ['"]npm['"], ['"]bin['"], ['"]npm-cli\.js['"]\)/)
  assert.match(source, /run\(process\.execPath, \[\s*npmCli,/)
  assert.doesNotMatch(source, /npm\.cmd/)
})

test('runtime staging packages exact Chrome DevTools MCP sidecar inside ZN runtime', () => {
  assert.match(source, /const chromeDevtoolsMcpVersion = '1\.9\.0'/)
  assert.match(source, /chrome-devtools-mcp@\$\{chromeDevtoolsMcpVersion\}/)
  assert.match(source, /chrome_devtools_mcp_runtime:\s*portableRelative\(runtimeRoot, chromeDevtoolsMcpRuntimeDir\)/)
  assert.match(source, /chrome_devtools_mcp_version:\s*chromeDevtoolsMcpVersion/)
  assert.match(source, /build['"],\s*['"]src['"],\s*['"]bin['"],\s*['"]chrome-devtools-mcp\.js['"]/)
})
