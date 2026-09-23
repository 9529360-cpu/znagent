import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { test } from 'vitest'

import {
  describeZnProviderReadiness,
  providerUpdateNotice
} from '../src/zn/provider-readiness'
import { parseZnDeepLink, znDeepLinksFromArgv } from './zn-protocol'

const here = path.dirname(fileURLToPath(import.meta.url))
const desktopRoot = path.resolve(here, '..')
const retiredProduct = Buffer.from('6865726d6573', 'hex').toString('utf8')
const retiredCli = Buffer.from('6865726d65735f636c69', 'hex').toString('utf8')
const retiredDesktop = `${retiredProduct}Desktop`
const retiredDesktopEnv = `${retiredProduct.toUpperCase()}_DESKTOP`
const retiredPackageScope = `@${retiredProduct}`

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
  assert.doesNotMatch(source, new RegExp(`${retiredCli}|run_agent|${retiredDesktopEnv}`))
})

test('ZN desktop is compact-first and can expand the same resident surface', () => {
  const main = read('electron/zn-main.ts')
  const preload = read('electron/zn-preload.ts')
  const styles = read('src/zn/styles.css')
  const minimum = main.match(/minWidth:\s*(\d+)/)

  assert.ok(minimum)
  assert.ok(Number(minimum[1]) <= 720)
  assert.match(main, /compact:\s*\{\s*width:\s*480,\s*height:\s*620\s*\}/)
  assert.match(main, /expanded:\s*\{\s*width:\s*1120,\s*height:\s*760\s*\}/)
  assert.match(main, /zn:shell:set-window-mode/)
  assert.match(main, /setZnWindowMode\(window, mode\)/)
  assert.match(main, /titleBarStyle:\s*['"]hidden['"]/)
  assert.match(main, /titleBarOverlay:/)
  assert.match(main, /backgroundMaterial:\s*['"]mica['"]/)
  assert.match(main, /window\.setMenu\(null\)/)
  assert.match(preload, /setWindowMode/)
  assert.match(styles, /@media \(max-width: 720px\)/)
  assert.match(styles, /\.zn-sidebar \{ display: none; \}/)
  assert.match(styles, /\.zn-app\.compact \.zn-sidebar/)
  const workbench = read('src/zn/workbench.tsx')
  assert.doesNotMatch(workbench, /zn-home-capabilities/)
})

test('ZN shell mode transition prepares renderer state before native resize and completes afterward', () => {
  const main = read('electron/zn-main.ts')
  const preload = read('electron/zn-preload.ts')
  const workbench = read('src/zn/workbench.tsx')

  assert.match(main, /ZN_WINDOW_TRANSITION_TIMEOUT_MS = 250/)
  assert.match(main, /zn:shell:window-mode-transition/)
  assert.match(main, /zn:shell:ack-window-mode-transition/)
  assert.match(main, /latestWindowTransitionIds\.set\(window\.id, transitionId\)/)
  assert.match(main, /latestWindowTransitionIds\.get\(window\.id\) !== transitionId/)
  assert.ok(main.includes('BrowserWindow.fromWebContents(event.sender)'))

  const transitionStart = main.indexOf('async function transitionZnWindowMode')
  const transitionEnd = main.indexOf('function focusComposerAfterInvocation', transitionStart)
  assert.ok(transitionStart >= 0)
  assert.ok(transitionEnd > transitionStart)
  const transition = main.slice(transitionStart, transitionEnd)
  assert.ok(transition.indexOf('prepareZnWindowTransition') < transition.indexOf('setZnWindowMode(window, mode)'))
  assert.ok(transition.indexOf('setZnWindowMode(window, mode)') < transition.indexOf("phase: 'complete'"))

  assert.match(preload, /ackWindowModeTransition/)
  assert.match(preload, /onWindowModeTransition/)
  assert.match(workbench, /onWindowModeTransition/)
  assert.match(workbench, /requestAnimationFrame/)
  assert.match(workbench, /ackWindowModeTransition/)
})
test('ZN global invocation is Windows-only, best-effort, and reuses the resident surface', () => {
  const source = read('electron/zn-main.ts')
  const preload = read('electron/zn-preload.ts')
  const workbench = read('src/zn/workbench.tsx')

  assert.match(source, /CommandOrControl\+Alt\+Space/)
  assert.match(source, /function initializeGlobalInvocation\(\)/)
  assert.match(source, /if \(process\.platform !== 'win32'\) return/)
  assert.match(source, /globalShortcut\.register\(ZN_GLOBAL_INVOCATION_SHORTCUT/)
  assert.match(source, /if \(!registered\)/)
  assert.match(source, /showPrimaryWindow\(true, ['"]compact['"]\)/)
  assert.ok(source.indexOf('windowsResidentSurface.show()') < source.indexOf('void transitionZnWindowMode('))
  assert.match(source, /zn:global-invocation/)
  assert.match(source, /globalShortcut\.unregister\(ZN_GLOBAL_INVOCATION_SHORTCUT\)/)
  assert.doesNotMatch(source, /globalShortcut\.unregisterAll\(\)/)
  assert.match(preload, /setWindowMode/)
  assert.match(preload, /onGlobalInvocation/)
  assert.match(preload, /zn:global-invocation/)
  assert.match(workbench, /onGlobalInvocation/)
  assert.match(workbench, /focusComposerInput\(\)/)

  const callbackStart = workbench.indexOf('onGlobalInvocation(() =>')
  const callbackEnd = workbench.indexOf('})', callbackStart)
  assert.ok(callbackStart >= 0)
  assert.ok(callbackEnd > callbackStart)
  const callback = workbench.slice(callbackStart, callbackEnd)
  assert.doesNotMatch(callback, /startZnWork|requestSubmit|submitZnWork/)
})

test('privileged desktop IPC accepts only the trusted top-level ZN renderer', () => {
  const trust = read('electron/zn-ipc-trust.ts')
  const main = read('electron/zn-main.ts')
  const resident = read('electron/zn-resident-ipc.ts')
  const workspace = read('electron/zn-workspace-ipc.ts')
  const updater = read('electron/zn-release-updater.ts')

  assert.match(main, /trustZnDesktopWebContents\(window\.webContents\)/)
  assert.match(trust, /trustedWebContentsIds\.has\(event\.sender\.id\)/)
  assert.match(trust, /frame !== frame\.top/)
  assert.match(trust, /frame !== event\.sender\.mainFrame/)
  assert.match(trust, /contents\.once\(['"]destroyed['"], revoke\)/)
  assert.match(trust, /ipcMain\.handle\(channel, \(event, \.\.\.args\) =>/)
  assert.doesNotMatch(resident, /ipcMain\.handle\(/)
  assert.doesNotMatch(workspace, /ipcMain\.handle\(/)
  assert.doesNotMatch(updater, /ipcMain\.handle\(/)
  assert.match(resident, /handleZnDesktopIpc\(['"]zn:resident:start['"]/)
  assert.match(workspace, /handleZnDesktopIpc\(['"]zn:workspaces:attach['"]/)
  assert.match(updater, /handleZnDesktopIpc\(['"]zn:updates:apply['"]/)
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
  assert.match(source, /zn:resident:work-cancel/)
  assert.match(source, /zn:resident:work-submit/)
  assert.match(source, /zn:workspaces:attach/)
  assert.match(source, /zn:workspaces:detach/)
  assert.doesNotMatch(source, /workspace_path/)
  assert.doesNotMatch(source, /safeStorage|keytar|keyring/i)
  assert.doesNotMatch(source, /import ['"]\.\/preload['"]/) 
  assert.doesNotMatch(source, new RegExp(`${retiredDesktop}|${retiredProduct}:`, 'i'))
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
  assert.doesNotMatch(source, new RegExp(retiredProduct, 'i'))
})

test('active ZN renderer root is content-first and independent of inherited shell', () => {
  const main = read('src/zn/main.tsx')
  const workbench = read('src/zn/workbench.tsx')
  const residentClient = read('src/zn/resident-client.ts')
  const styles = read('src/zn/styles.css')
  const html = read('electron/zn-shell.html')
  const localization = read('localization/zn-localization.ts')

  assert.match(main, /ZnWorkbench/)
  assert.doesNotMatch(main, /ZnProviderOnboarding/)
  assert.match(styles, /\.zn-settings\s*\{/)
  assert.match(styles, /\.zn-card\s*\{/)
  assert.match(workbench, /sidebar\.newWork/)
  assert.match(workbench, /sidebar\.workspaces/)
  assert.match(workbench, /settings\.title/)
  assert.match(workbench, /composer\.messageAria/)
  assert.match(localization, /'sidebar\.newWork': 'New chat'/)
  assert.match(workbench, /loadZnWorkThreads/)
  assert.match(workbench, /createZnWorkThread/)
  assert.match(workbench, /startZnWork/)
  assert.match(workbench, /loadZnWorkProgress/)
  assert.match(workbench, /cancelZnWork/)
  assert.match(workbench, /attachZnWorkspace/)
  assert.match(workbench, /detachZnWorkspace/)
  assert.match(workbench, /sidebar\.attachFolder/)
  assert.match(workbench, /selectedArtifactId/)
  assert.match(workbench, /details\.artifactsAria/)
  assert.match(workbench, /artifactKindLabel/)
  assert.match(workbench, /loadZnProviderSettings/)
  assert.match(workbench, /describeZnProviderReadiness/)
  assert.match(workbench, /topbar\.openSettings/)
  assert.match(workbench, /settings\.models\.description/)
  assert.match(localization, /Clear computer actions stay local when a deterministic path exists/)
  assert.match(workbench, /disabled=\{busy \|\| !draft\.trim\(\)\}/)
  assert.match(residentClient, /resident\.workList/)
  assert.match(residentClient, /resident\.workStart/)
  assert.match(residentClient, /resident\.workProgress/)
  assert.match(residentClient, /resident\.workCancel/)
  assert.match(residentClient, /bridge\.workspaces\.attach/)
  assert.match(residentClient, /normalizeArtifact/)
  assert.match(html, /zn-shell-renderer\.css/)
  assert.match(html, /zn-shell-renderer\.js/)

  const retiredRendererPattern = new RegExp(`ContribController|${retiredDesktop}|${retiredPackageScope}|src\\/main`, 'i')
  for (const source of [main, workbench, residentClient]) {
    assert.doesNotMatch(source, retiredRendererPattern)
  }
  assert.doesNotMatch(workbench, new RegExp(retiredProduct, 'i'))
  assert.doesNotMatch(workbench, /gateway|bootstrap-runner|src\/store/i)
  assert.doesNotMatch(workbench, /showOpenDialog|readFileSync|readFile\(/)
  assert.doesNotMatch(residentClient, /node:fs|electron/)
  assert.doesNotMatch(html, new RegExp(retiredProduct, 'i'))
})

test('ZN liquid OS hierarchy keeps glass in controls and content readable', () => {
  const styles = read('src/zn/styles.css')

  assert.match(styles, /body::before,\s*body::after\s*\{/)
  assert.match(styles, /@keyframes zn-liquid-a/)
  assert.match(styles, /@keyframes zn-liquid-b/)
  assert.match(styles, /\.zn-sidebar,\s*\.zn-context-panel,\s*\.zn-topbar,\s*\.zn-composer\s*\{\s*backdrop-filter:/)
  assert.doesNotMatch(styles, /\.zn-thread-surface\s*\{[^}]*backdrop-filter:/s)
  assert.doesNotMatch(styles, /\.zn-message\.activity\s*\{[^}]*backdrop-filter:/s)
  assert.match(styles, /@media \(prefers-reduced-motion: reduce\)/)
  assert.match(styles, /:focus-visible/)
})

test('workbench browser cache is bounded fallback state, not resident authority', () => {
  const state = read('src/zn/state.ts')
  const workbench = read('src/zn/workbench.tsx')

  assert.match(state, /MAX_THREADS = 24/)
  assert.match(state, /MAX_MESSAGES_PER_THREAD = 120/)
  assert.match(state, /MAX_ARTIFACTS_PER_THREAD = 48/)
  assert.match(state, /Resident identity\/memory must never/)
  assert.match(state, /delete cached\.restorePoints/)
  assert.match(workbench, /const authoritative = residentThreads\.length > 0/)
  assert.match(workbench, /setThreads\(current => authoritative\.map\(thread =>/)
  assert.match(workbench, /const previous = current\.find\(item => item\.id === thread\.id\)/)
  assert.match(workbench, /previous\?\.restorePoints !== undefined/)
  assert.match(workbench, /\{ \.\.\.thread, restorePoints: previous\.restorePoints \}/)
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
  const localization = read('localization/zn-localization.ts')
  assert.match(workbench, /kind === ['"]terminal['"]/) 
  assert.match(workbench, /artifact\.terminal/)
  assert.match(localization, /'artifact\.terminal': 'Terminal'/)
  assert.doesNotMatch(workbench, /@xterm|new Terminal\s*\(/)
  assert.doesNotMatch(client, /terminal\.execute|terminal\.start|terminal\.open/i)
})

test('provider settings stay resident-owned and renderer never receives a stored secret', () => {
  const ipc = read('electron/zn-resident-ipc.ts')
  const preload = read('electron/zn-preload.ts')
  const workbench = read('src/zn/workbench.tsx')
  const client = read('src/zn/resident-client.ts')
  const state = read('src/zn/state.ts')
  const localization = read('localization/zn-localization.ts')

  assert.match(ipc, /provider_settings/)
  assert.match(ipc, /provider_settings_update/)
  assert.match(preload, /providerSettingsUpdate/)
  assert.match(client, /loadZnProviderSettings/)
  assert.match(client, /updateZnProviderSettings/)
  assert.match(workbench, /loadZnProviderSettings/)
  assert.match(workbench, /updateZnProviderSettings/)
  assert.match(workbench, /providerReadinessDetail/)
  assert.match(workbench, /settings\.models\.title/)
  assert.match(workbench, /type="password"/)
  assert.match(workbench, /settings\.models\.save/)
  assert.match(workbench, /settings\.models\.description/)
  assert.match(localization, /'settings\.models\.title': 'API & models'/)
  assert.match(localization, /saved securely by ZN/)
  assert.doesNotMatch(ipc, /safeStorage|keytar|keyring/i)
  assert.doesNotMatch(preload, /safeStorage|keytar|keyring/i)
  assert.doesNotMatch(client, /localStorage|sessionStorage/)
  assert.doesNotMatch(state, /apiKey|api_key|credential_ref/)
})

test('provider readiness never turns an unavailable resident resource into success', () => {
  const unavailable = {
    provider: 'openai',
    model: 'gpt-test',
    cognitionAvailable: false,
    configurationError: 'missing credential',
    activeRoutes: []
  }

  const readiness = describeZnProviderReadiness(unavailable)
  assert.equal(readiness.ready, false)
  assert.equal(readiness.kind, 'unavailable')
  assert.match(providerUpdateNotice(unavailable), /not ready/i)
  assert.doesNotMatch(providerUpdateNotice(unavailable), /^Model ready\./)
})

test('running Work progress and uncertain cancellation come from resident state', () => {
  const processClient = read('electron/zn-resident-process.ts')
  const ipc = read('electron/zn-resident-ipc.ts')
  const preload = read('electron/zn-preload.ts')
  const client = read('src/zn/resident-client.ts')
  const workbench = read('src/zn/workbench.tsx')
  const state = read('src/zn/state.ts')

  assert.match(processClient, /['"]work_cancel['"]/)
  assert.match(ipc, /work_start/)
  assert.match(ipc, /work_progress/)
  assert.match(ipc, /work_cancel/)
  assert.match(preload, /workStart/)
  assert.match(preload, /workProgress/)
  assert.match(preload, /workCancel/)
  assert.match(client, /normalizeWorkProgress/)
  assert.match(client, /normalizeWorkRecovery/)
  assert.match(client, /cancelZnWork/)
  assert.match(workbench, /work\.residentProgress/)
  assert.match(workbench, /workProgress\.stage/)
  assert.match(workbench, /workProgress\.nextAction/)
  assert.match(workbench, /workProgress\.bodyActions/)
  assert.match(workbench, /workProgress\.recovery/)
  assert.match(workbench, /replayBlocked/)
  assert.match(workbench, /work\.outsideUncertain/)
  assert.match(workbench, /work\.stop/)
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
  assert.doesNotMatch(source, new RegExp(`legacy desktop shell|mature legacy|${retiredDesktopEnv}_IS_PACKAGED`))
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

test('ZN deep links reject retired and web schemes and preserve inert navigation data', () => {
  assert.deepEqual(parseZnDeepLink('zn://work/thread-42?workspace=alpha&mode=inspect'), {
    url: 'zn://work/thread-42?workspace=alpha&mode=inspect',
    route: 'work',
    path: '/thread-42',
    params: { workspace: 'alpha', mode: 'inspect' }
  })
  assert.equal(parseZnDeepLink('https://example.com/work'), null)
  assert.equal(parseZnDeepLink(`${retiredProduct}://work/thread-42`), null)
  assert.equal(parseZnDeepLink(`zn://work/${'x'.repeat(9000)}`), null)
})

test('single-instance argv deep links are normalized and deduplicated', () => {
  assert.deepEqual(
    znDeepLinksFromArgv(['electron', '.', 'zn://resident/status', 'zn://resident/status']),
    [{ url: 'zn://resident/status', route: 'resident', path: '/status', params: {} }]
  )
})
