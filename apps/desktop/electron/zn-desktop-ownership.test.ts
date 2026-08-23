import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { test } from 'vitest'

import { parseZnDeepLink, znDeepLinksFromArgv } from './zn-protocol'

const here = path.dirname(fileURLToPath(import.meta.url))
const desktopRoot = path.resolve(here, '..')

function read(relative: string): string {
  return fs.readFileSync(path.join(desktopRoot, relative), 'utf8')
}

test('ZN Electron main owns window and protocol lifecycle without inherited desktop main', () => {
  const source = read('electron/zn-main.ts')

  assert.match(source, /new BrowserWindow\(/)
  assert.match(source, /zn-shell\.html/)
  assert.match(source, /registerZnResidentIpc\(\)/)
  assert.match(source, /registerZnWorkspaceIpc\(\)/)
  assert.match(source, /requestSingleInstanceLock\(\)/)
  assert.match(source, /setAsDefaultProtocolClient\(['"]zn['"]\)/)
  assert.match(source, /contextIsolation:\s*true/)
  assert.match(source, /nodeIntegration:\s*false/)
  assert.match(source, /sandbox:\s*true/)
  assert.doesNotMatch(source, /import\(['"]\.\/main['"]\)/)
  assert.doesNotMatch(source, /from ['"]\.\/main['"]/) 
  assert.doesNotMatch(source, /hermes_cli|run_agent|HERMES_DESKTOP/)
})

test('ZN preload exposes only the ZN bridge and does not import inherited preload', () => {
  const source = read('electron/zn-preload.ts')

  assert.match(source, /exposeInMainWorld\(['"]znDesktop['"]/)
  assert.match(source, /zn:deep-link/)
  assert.match(source, /zn:resident:provider-settings/)
  assert.match(source, /zn:resident:provider-settings-update/)
  assert.match(source, /zn:resident:work-list/)
  assert.match(source, /zn:resident:work-start/)
  assert.match(source, /zn:resident:work-progress/)
  assert.match(source, /zn:resident:work-submit/)
  assert.match(source, /zn:workspaces:attach/)
  assert.match(source, /zn:workspaces:detach/)
  assert.doesNotMatch(source, /workspace_path/)
  assert.doesNotMatch(source, /safeStorage|keytar|keyring/i)
  assert.doesNotMatch(source, /import ['"]\.\/preload['"]/) 
  assert.doesNotMatch(source, /hermesDesktop|hermes:/)
})

test('workspace attachment uses an OS folder picker before resident association', () => {
  const source = read('electron/zn-workspace-ipc.ts')

  assert.match(source, /showOpenDialog/)
  assert.match(source, /openDirectory/)
  assert.match(source, /fs\.realpath/)
  assert.match(source, /fs\.stat/)
  assert.match(source, /stat\.isDirectory\(\)/)
  assert.match(source, /work_attach_workspace/)
  assert.match(source, /work_detach_workspace/)
  assert.doesNotMatch(source, /hermes/i)
})

test('active ZN renderer root is content-first and independent of inherited shell', () => {
  const main = read('src/zn/main.tsx')
  const workbench = read('src/zn/workbench.tsx')
  const residentClient = read('src/zn/resident-client.ts')
  const html = read('electron/zn-shell.html')

  assert.match(main, /ZnWorkbench/)
  assert.match(workbench, /New work/)
  assert.match(workbench, /Workspaces/)
  assert.match(workbench, /Settings/)
  assert.match(workbench, /Message ZN/)
  assert.match(workbench, /loadZnWorkThreads/)
  assert.match(workbench, /createZnWorkThread/)
  assert.match(workbench, /startZnWork/)
  assert.match(workbench, /loadZnWorkProgress/)
  assert.match(workbench, /attachZnWorkspace/)
  assert.match(workbench, /detachZnWorkspace/)
  assert.match(workbench, /Attach folder/)
  assert.match(workbench, /selectedArtifactId/)
  assert.match(workbench, /Work artifacts/)
  assert.match(workbench, /artifactKindLabel/)
  assert.match(residentClient, /resident\.workList/)
  assert.match(residentClient, /resident\.workStart/)
  assert.match(residentClient, /resident\.workProgress/)
  assert.match(residentClient, /bridge\.workspaces\.attach/)
  assert.match(residentClient, /normalizeArtifact/)
  assert.match(html, /zn-shell-renderer\.css/)
  assert.match(html, /zn-shell-renderer\.js/)

  for (const source of [main, workbench, residentClient]) {
    assert.doesNotMatch(source, /ContribController|hermesDesktop|@hermes|src\/main/i)
  }
  assert.doesNotMatch(workbench, /gateway/i)
  assert.doesNotMatch(workbench, /showOpenDialog|readFileSync|readFile\(/)
  assert.doesNotMatch(residentClient, /node:fs|electron/)
  assert.doesNotMatch(html, /hermes/i)
})

test('workbench browser cache is bounded fallback state, not resident authority', () => {
  const state = read('src/zn/state.ts')
  const workbench = read('src/zn/workbench.tsx')

  assert.match(state, /MAX_THREADS = 24/)
  assert.match(state, /MAX_MESSAGES_PER_THREAD = 120/)
  assert.match(state, /MAX_ARTIFACTS_PER_THREAD = 48/)
  assert.match(state, /Resident identity\/memory must never/)
  assert.match(workbench, /const authoritative = residentThreads\.length > 0/)
  assert.match(workbench, /setThreads\(authoritative\)/)
  assert.doesNotMatch(state, /nervous|kernel\.db|structured memory/i)
})

test('artifact context remains resident-backed and contextual rather than a permanent file tree', () => {
  const workbench = read('src/zn/workbench.tsx')
  const client = read('src/zn/resident-client.ts')
  const state = read('src/zn/state.ts')

  assert.match(state, /ZnArtifact/)
  assert.match(client, /rawArtifacts/)
  assert.match(workbench, /activeArtifacts/)
  assert.match(workbench, /zn-artifact-preview/)
  assert.match(workbench, /setContextOpen\(true\)/)
  assert.doesNotMatch(workbench, /file tree|treeview|react-arborist/i)
})

test('terminal context appears only as resident artifact evidence, not a permanent IDE terminal', () => {
  const workbench = read('src/zn/workbench.tsx')
  const client = read('src/zn/resident-client.ts')
  const state = read('src/zn/state.ts')

  assert.match(state, /['"]terminal['"]/)
  assert.match(client, /value === ['"]terminal['"]/)
  assert.match(workbench, /kind === ['"]terminal['"]/) 
  assert.match(workbench, /return ['"]Terminal['"]/)
  assert.doesNotMatch(workbench, /@xterm|new Terminal\s*\(/)
  assert.doesNotMatch(client, /terminal\.execute|terminal\.start|terminal\.open/i)
})

test('provider settings stay resident-owned and renderer never receives a stored secret', () => {
  const ipc = read('electron/zn-resident-ipc.ts')
  const preload = read('electron/zn-preload.ts')
  const workbench = read('src/zn/workbench.tsx')
  const client = read('src/zn/resident-client.ts')
  const state = read('src/zn/state.ts')

  assert.match(ipc, /provider_settings/)
  assert.match(ipc, /provider_settings_update/)
  assert.match(preload, /providerSettingsUpdate/)
  assert.match(client, /loadZnProviderSettings/)
  assert.match(client, /updateZnProviderSettings/)
  assert.match(workbench, /Models & providers/)
  assert.match(workbench, /type="password"/)
  assert.match(workbench, /Save provider/)
  assert.match(workbench, /secure credential boundary/)
  assert.doesNotMatch(ipc, /safeStorage|keytar|keyring/i)
  assert.doesNotMatch(preload, /safeStorage|keytar|keyring/i)
  assert.doesNotMatch(client, /localStorage|sessionStorage/)
  assert.doesNotMatch(state, /apiKey|api_key|credential_ref/)
})

test('running work progress comes from resident event state instead of renderer fake progress', () => {
  const ipc = read('electron/zn-resident-ipc.ts')
  const preload = read('electron/zn-preload.ts')
  const client = read('src/zn/resident-client.ts')
  const workbench = read('src/zn/workbench.tsx')
  const state = read('src/zn/state.ts')

  assert.match(ipc, /work_start/)
  assert.match(ipc, /work_progress/)
  assert.match(preload, /workStart/)
  assert.match(preload, /workProgress/)
  assert.match(client, /normalizeWorkProgress/)
  assert.match(workbench, /Resident progress/)
  assert.match(workbench, /workProgress\.stage/)
  assert.match(workbench, /workProgress\.nextAction/)
  assert.match(workbench, /workProgress\.bodyActions/)
  assert.doesNotMatch(state, /ZnWorkProgress|workProgress/)
  assert.doesNotMatch(workbench, /fake progress|Math\.random\(\).*progress/i)
})

test('Electron bundler emits only ZN control-plane and renderer entries', () => {
  const source = read('scripts/bundle-electron-main.mjs')

  assert.match(source, /electron\/zn-main\.ts/)
  assert.match(source, /electron\/zn-preload\.ts/)
  assert.match(source, /src\/zn\/main\.tsx/)
  assert.match(source, /zn-shell-renderer\.css/)
  assert.doesNotMatch(source, /electron\/zn-shell-renderer\.ts/)
  assert.doesNotMatch(source, /legacy desktop shell|mature legacy|HERMES_DESKTOP_IS_PACKAGED/)
})

test('formal Linux desktop identity is owned by the single ZN builder config', () => {
  const pkg = JSON.parse(read('package.json'))
  const builder = read('electron-builder.zn.yml')

  assert.equal(pkg.desktopName, 'ai.zn.desktop')
  assert.equal(pkg.build, undefined)
  assert.match(pkg.scripts?.builder || '', /--config electron-builder\.zn\.yml/)
  assert.match(builder, /^appId:\s+ai\.zn\.desktop$/m)
  assert.match(builder, /^\s+syncDesktopName:\s+true$/m)
  assert.match(builder, /^\s+StartupWMClass:\s+ai\.zn\.desktop$/m)
})

test('ZN deep links reject inherited and web schemes and preserve inert navigation data', () => {
  assert.deepEqual(parseZnDeepLink('zn://work/thread-42?workspace=alpha&mode=inspect'), {
    url: 'zn://work/thread-42?workspace=alpha&mode=inspect',
    route: 'work',
    path: '/thread-42',
    params: { workspace: 'alpha', mode: 'inspect' }
  })
  assert.equal(parseZnDeepLink('https://example.com/work'), null)
  assert.equal(parseZnDeepLink('hermes://work/thread-42'), null)
  assert.equal(parseZnDeepLink(`zn://work/${'x'.repeat(9000)}`), null)
})

test('single-instance argv deep links are normalized and deduplicated', () => {
  assert.deepEqual(
    znDeepLinksFromArgv(['electron', '.', 'zn://resident/status', 'zn://resident/status']),
    [{ url: 'zn://resident/status', route: 'resident', path: '/status', params: {} }]
  )
})
