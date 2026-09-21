import assert from 'node:assert/strict'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { test } from 'vitest'

import {
  normalizeZnSupportedLocale,
  resolveZnLocale,
  translateZnDesktop
} from '../localization/zn-localization'
import {
  readZnLocalePreference,
  writeZnLocalePreference
} from './zn-locale-preference'

const here = path.dirname(fileURLToPath(import.meta.url))
const desktopRoot = path.resolve(here, '..')

function read(relative: string): string {
  return fs.readFileSync(path.join(desktopRoot, relative), 'utf8')
}

test('desktop localization resolves supported Windows language families with English fallback', () => {
  assert.equal(normalizeZnSupportedLocale('zh-CN'), 'zh-CN')
  assert.equal(normalizeZnSupportedLocale('zh-Hans-CN'), 'zh-CN')
  assert.equal(normalizeZnSupportedLocale('zh-TW'), 'zh-CN')
  assert.equal(normalizeZnSupportedLocale('en-GB'), 'en-US')
  assert.equal(normalizeZnSupportedLocale('fr-FR'), null)

  assert.equal(resolveZnLocale('system', ['fr-FR', 'zh-Hans-CN']), 'zh-CN')
  assert.equal(resolveZnLocale('system', ['fr-FR', 'de-DE']), 'en-US')
  assert.equal(resolveZnLocale('en-US', ['zh-CN']), 'en-US')
  assert.equal(resolveZnLocale('zh-CN', ['en-US']), 'zh-CN')
})

test('English and Simplified Chinese resources cover the same typed UI keys', () => {
  assert.equal(translateZnDesktop('en-US', 'sidebar.newWork'), 'New work')
  assert.equal(translateZnDesktop('zh-CN', 'sidebar.newWork'), '新任务')
  assert.equal(translateZnDesktop('en-US', 'tray.quit'), 'Quit ZN')
  assert.equal(translateZnDesktop('zh-CN', 'tray.quit'), '退出 ZN')
  assert.equal(
    translateZnDesktop('zh-CN', 'settings.language.systemDetected', { languages: 'zh-CN, en-US' }),
    'Windows 语言：zh-CN, en-US'
  )
})

test('desktop locale preference persists independently from Resident and Work state', () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'zn-locale-'))
  const file = path.join(root, 'desktop-preferences.json')
  try {
    assert.equal(readZnLocalePreference(file), 'system')
    writeZnLocalePreference(file, 'zh-CN')
    assert.equal(readZnLocalePreference(file), 'zh-CN')
    writeZnLocalePreference(file, 'en-US')
    assert.equal(readZnLocalePreference(file), 'en-US')
    fs.writeFileSync(file, JSON.stringify({ locale: 'not-a-locale' }))
    assert.equal(readZnLocalePreference(file), 'system')
  } finally {
    fs.rmSync(root, { recursive: true, force: true })
  }
})

test('Electron and renderer share the same locale contract and switch live without a second runtime', () => {
  const main = read('electron/zn-main.ts')
  const preload = read('electron/zn-preload.ts')
  const renderer = read('src/zn/i18n.ts')
  const workbench = read('src/zn/workbench.tsx')

  assert.match(main, /getPreferredSystemLanguages/)
  assert.match(main, /zn:shell:get-locale-state/)
  assert.match(main, /zn:shell:set-locale-preference/)
  assert.match(main, /writeZnLocalePreference/)
  assert.match(main, /refreshWindowsTrayMenu/)
  assert.match(preload, /getLocaleState/)
  assert.match(preload, /setLocalePreference/)
  assert.match(renderer, /initReactI18next/)
  assert.match(renderer, /i18n\.changeLanguage/)
  assert.match(renderer, /fallbackLng: 'en-US'/)
  assert.match(workbench, /settings\.language\.system/)
  assert.match(workbench, /settings\.language\.zhCN/)
  assert.match(workbench, /settings\.language\.enUS/)
  assert.doesNotMatch(main, /new BrowserWindow\([^)]*locale/i)
})
