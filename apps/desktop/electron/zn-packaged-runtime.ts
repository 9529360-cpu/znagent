import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'

type EnvRecord = Record<string, string | undefined>

type ZnRuntimeManifest = {
  schema: number
  product: string
  runtime_id: string
  version?: string
  commit?: string
  platform?: string
  arch?: string
  python_version?: string
  python: string
  backend_root: string
  browser_root?: string
  veteran_runtime?: string
  chrome_devtools_mcp_runtime?: string
  chrome_devtools_mcp_version?: string
}

type ResolvedZnRuntime = {
  root: string
  python: string
  backendRoot: string
  browserRoot?: string
  veteranRuntimeRoot?: string
  chromeDevtoolsMcpRuntimeRoot?: string
  manifest: ZnRuntimeManifest
}

const RUNTIME_DIR_NAME = 'zn-runtime'
const MANIFEST_NAME = 'runtime.json'
const RUNTIME_ID_RE = /^[0-9A-Za-z._-]{1,128}$/
const RETIRED_PACKAGE_NAME = Buffer.from('6865726d65735f636c69', 'hex').toString('utf8')

function resolveZnHome(
  env: EnvRecord = process.env,
  platform = process.platform,
  homeDir = os.homedir()
): string {
  const explicit = env.ZN_AGENT_HOME || env.ZN_HOME
  if (explicit) return path.resolve(explicit)
  if (platform === 'win32') return path.join(env.LOCALAPPDATA || homeDir, 'znagent')
  return path.join(homeDir, '.znagent')
}

function readManifest(runtimeRoot: string): ZnRuntimeManifest {
  const manifestPath = path.join(runtimeRoot, MANIFEST_NAME)
  let parsed: unknown
  try {
    parsed = JSON.parse(fs.readFileSync(manifestPath, 'utf8'))
  } catch (error) {
    throw new Error(`ZN runtime manifest is unreadable at ${manifestPath}: ${String(error)}`)
  }
  if (!parsed || typeof parsed !== 'object') throw new Error(`ZN runtime manifest is invalid at ${manifestPath}`)
  const manifest = parsed as Partial<ZnRuntimeManifest>
  if (manifest.schema !== 1 || manifest.product !== 'ZN') throw new Error(`Unsupported ZN runtime manifest at ${manifestPath}`)
  if (typeof manifest.runtime_id !== 'string' || !RUNTIME_ID_RE.test(manifest.runtime_id)) {
    throw new Error(`ZN runtime manifest has an invalid runtime_id at ${manifestPath}`)
  }
  if (typeof manifest.python !== 'string' || !manifest.python) throw new Error(`ZN runtime manifest is missing python at ${manifestPath}`)
  if (typeof manifest.backend_root !== 'string' || !manifest.backend_root) {
    throw new Error(`ZN runtime manifest is missing backend_root at ${manifestPath}`)
  }
  if (manifest.browser_root !== undefined && (typeof manifest.browser_root !== 'string' || !manifest.browser_root.trim())) {
    throw new Error(`ZN runtime manifest has an invalid browser_root at ${manifestPath}`)
  }
  if (manifest.veteran_runtime !== undefined && (typeof manifest.veteran_runtime !== 'string' || !manifest.veteran_runtime.trim())) {
    throw new Error(`ZN runtime manifest has an invalid veteran_runtime at ${manifestPath}`)
  }
  if (
    manifest.chrome_devtools_mcp_runtime !== undefined &&
    (typeof manifest.chrome_devtools_mcp_runtime !== 'string' || !manifest.chrome_devtools_mcp_runtime.trim())
  ) {
    throw new Error(`ZN runtime manifest has an invalid chrome_devtools_mcp_runtime at ${manifestPath}`)
  }
  if (
    manifest.chrome_devtools_mcp_version !== undefined &&
    (typeof manifest.chrome_devtools_mcp_version !== 'string' || !manifest.chrome_devtools_mcp_version.trim())
  ) {
    throw new Error(`ZN runtime manifest has an invalid chrome_devtools_mcp_version at ${manifestPath}`)
  }
  if ((manifest.chrome_devtools_mcp_runtime === undefined) !== (manifest.chrome_devtools_mcp_version === undefined)) {
    throw new Error(`ZN runtime manifest must declare Chrome DevTools MCP runtime and version together at ${manifestPath}`)
  }
  if (manifest.platform && manifest.platform !== process.platform) {
    throw new Error(`ZN runtime platform mismatch: expected ${process.platform}, got ${manifest.platform}`)
  }
  if (manifest.arch && manifest.arch !== process.arch) {
    throw new Error(`ZN runtime architecture mismatch: expected ${process.arch}, got ${manifest.arch}`)
  }
  return manifest as ZnRuntimeManifest
}

function resolveInside(root: string, relativePath: string, label: string): string {
  if (path.isAbsolute(relativePath)) throw new Error(`ZN runtime ${label} must be relative: ${relativePath}`)
  const resolvedRoot = path.resolve(root)
  const target = path.resolve(resolvedRoot, relativePath)
  const relative = path.relative(resolvedRoot, target)
  if (relative.startsWith('..') || path.isAbsolute(relative)) {
    throw new Error(`ZN runtime ${label} escapes its payload root: ${relativePath}`)
  }
  return target
}

function requireFile(filePath: string, label: string) {
  try {
    if (fs.statSync(filePath).isFile()) return
  } catch { void 0 }
  throw new Error(`ZN runtime ${label} is missing: ${filePath}`)
}

function requireDirectory(dirPath: string, label: string) {
  try {
    if (fs.statSync(dirPath).isDirectory()) return
  } catch { void 0 }
  throw new Error(`ZN runtime ${label} is missing: ${dirPath}`)
}

function resolveRuntime(runtimeRoot: string, expectedRuntimeId?: string): ResolvedZnRuntime {
  const manifest = readManifest(runtimeRoot)
  if (expectedRuntimeId && manifest.runtime_id !== expectedRuntimeId) {
    throw new Error(`ZN runtime id mismatch: expected ${expectedRuntimeId}, got ${manifest.runtime_id}`)
  }
  const python = resolveInside(runtimeRoot, manifest.python, 'python')
  const backendRoot = resolveInside(runtimeRoot, manifest.backend_root, 'backend_root')
  const browserRoot = manifest.browser_root
    ? resolveInside(runtimeRoot, manifest.browser_root, 'browser_root')
    : undefined
  const veteranRuntimeRoot = manifest.veteran_runtime
    ? resolveInside(runtimeRoot, manifest.veteran_runtime, 'veteran_runtime')
    : undefined
  const chromeDevtoolsMcpRuntimeRoot = manifest.chrome_devtools_mcp_runtime
    ? resolveInside(runtimeRoot, manifest.chrome_devtools_mcp_runtime, 'chrome_devtools_mcp_runtime')
    : undefined
  requireFile(python, 'python executable')
  requireDirectory(backendRoot, 'backend root')
  if (browserRoot) requireDirectory(browserRoot, 'managed browser root')
  if (veteranRuntimeRoot) {
    requireDirectory(veteranRuntimeRoot, 'Veteran runtime root')
    requireFile(path.join(veteranRuntimeRoot, 'mcp', 'server.mjs'), 'Veteran MCP server')
    requireFile(path.join(veteranRuntimeRoot, 'VENDOR.json'), 'Veteran vendor manifest')
  }
  if (chromeDevtoolsMcpRuntimeRoot) {
    requireDirectory(chromeDevtoolsMcpRuntimeRoot, 'Chrome DevTools MCP runtime root')
    requireFile(
      path.join(
        chromeDevtoolsMcpRuntimeRoot,
        'node_modules',
        'chrome-devtools-mcp',
        'build',
        'src',
        'bin',
        'chrome-devtools-mcp.js'
      ),
      'Chrome DevTools MCP server'
    )
    const chromePackagePath = path.join(
      chromeDevtoolsMcpRuntimeRoot,
      'node_modules',
      'chrome-devtools-mcp',
      'package.json'
    )
    requireFile(chromePackagePath, 'Chrome DevTools MCP package manifest')
    const chromePackage = JSON.parse(fs.readFileSync(chromePackagePath, 'utf8'))
    if (chromePackage.version !== manifest.chrome_devtools_mcp_version) {
      throw new Error(
        `ZN runtime Chrome DevTools MCP version mismatch: expected ${manifest.chrome_devtools_mcp_version}, got ${chromePackage.version}`
      )
    }
  }
  requireFile(path.join(backendRoot, 'zn_agent', 'resident.py'), 'resident package entrypoint')
  requireFile(path.join(backendRoot, 'zn_agent', 'core', 'resident_server.py'), 'resident core entrypoint')
  if (fs.existsSync(path.join(backendRoot, RETIRED_PACKAGE_NAME))) {
    throw new Error(`ZN runtime contains forbidden retired package: ${path.join(backendRoot, RETIRED_PACKAGE_NAME)}`)
  }
  return {
    root: path.resolve(runtimeRoot),
    python,
    backendRoot,
    ...(browserRoot ? { browserRoot } : {}),
    ...(veteranRuntimeRoot ? { veteranRuntimeRoot } : {}),
    ...(chromeDevtoolsMcpRuntimeRoot ? { chromeDevtoolsMcpRuntimeRoot } : {}),
    manifest
  }
}

function tryResolveRuntime(runtimeRoot: string, expectedRuntimeId: string): ResolvedZnRuntime | null {
  try { return resolveRuntime(runtimeRoot, expectedRuntimeId) } catch { return null }
}

function materializeRuntime(resourcesPath: string, znHome: string): ResolvedZnRuntime {
  const bundledRoot = path.resolve(resourcesPath, RUNTIME_DIR_NAME)
  const bundled = resolveRuntime(bundledRoot)
  const runtimeParent = path.join(znHome, 'runtime')
  const targetRoot = path.join(runtimeParent, bundled.manifest.runtime_id)
  const existing = tryResolveRuntime(targetRoot, bundled.manifest.runtime_id)
  if (existing) return existing
  fs.mkdirSync(runtimeParent, { recursive: true })
  if (fs.existsSync(targetRoot)) fs.rmSync(targetRoot, { recursive: true, force: true })
  const tempRoot = `${targetRoot}.tmp-${process.pid}-${Date.now()}`
  try {
    fs.cpSync(bundledRoot, tempRoot, { recursive: true, force: true, verbatimSymlinks: true })
    const staged = resolveRuntime(tempRoot, bundled.manifest.runtime_id)
    try {
      fs.renameSync(tempRoot, targetRoot)
    } catch (error) {
      const raced = tryResolveRuntime(targetRoot, bundled.manifest.runtime_id)
      if (raced) return raced
      throw error
    }
    return resolveRuntime(targetRoot, staged.manifest.runtime_id)
  } finally {
    if (fs.existsSync(tempRoot)) fs.rmSync(tempRoot, { recursive: true, force: true })
  }
}

function configureZnPackagedRuntime({
  resourcesPath,
  env = process.env,
  znHome = resolveZnHome(env),
  desktopExecutable = process.execPath
}: {
  resourcesPath: string
  env?: EnvRecord
  znHome?: string
  desktopExecutable?: string
}): ResolvedZnRuntime {
  const resolvedHome = path.resolve(znHome)
  const runtime = materializeRuntime(resourcesPath, resolvedHome)
  env.ZN_AGENT_HOME = resolvedHome
  env.ZN_PACKAGED_RUNTIME_ROOT = runtime.root
  env.ZN_RUNTIME_ID = runtime.manifest.runtime_id
  env.ZN_RESIDENT_PYTHON = runtime.python
  if (runtime.browserRoot) env.PLAYWRIGHT_BROWSERS_PATH = runtime.browserRoot
  else delete env.PLAYWRIGHT_BROWSERS_PATH
  if (runtime.veteranRuntimeRoot) env.ZN_VETERAN_RUNTIME_ROOT = runtime.veteranRuntimeRoot
  else delete env.ZN_VETERAN_RUNTIME_ROOT
  if (runtime.chromeDevtoolsMcpRuntimeRoot) {
    env.ZN_CHROME_DEVTOOLS_MCP_ROOT = runtime.chromeDevtoolsMcpRuntimeRoot
  } else {
    delete env.ZN_CHROME_DEVTOOLS_MCP_ROOT
  }
  env.ZN_DESKTOP_EXECUTABLE = path.resolve(desktopExecutable)
  env.PYTHONNOUSERSITE = '1'
  env.PYTHONUTF8 = '1'
  return runtime
}

export {
  configureZnPackagedRuntime,
  materializeRuntime,
  resolveRuntime,
  resolveZnHome,
  type ResolvedZnRuntime,
  type ZnRuntimeManifest
}
