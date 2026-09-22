import {
  existsSync,
  mkdirSync,
  readFileSync,
  renameSync,
  rmSync,
  writeFileSync
} from 'node:fs'
import path from 'node:path'

import {
  isZnLocalePreference,
  type ZnLocalePreference
} from '../localization/zn-localization'

type StoredPreferences = {
  locale?: unknown
}

export function readZnLocalePreference(filePath: string): ZnLocalePreference {
  try {
    if (!existsSync(filePath)) return 'system'
    const parsed = JSON.parse(readFileSync(filePath, 'utf8')) as StoredPreferences
    return isZnLocalePreference(parsed.locale) ? parsed.locale : 'system'
  } catch {
    return 'system'
  }
}

export function writeZnLocalePreference(
  filePath: string,
  preference: ZnLocalePreference
): void {
  mkdirSync(path.dirname(filePath), { recursive: true })
  const temporary = filePath + '.tmp'
  try {
    writeFileSync(temporary, JSON.stringify({ locale: preference }, null, 2) + '\n', {
      encoding: 'utf8',
      mode: 0o600
    })
    renameSync(temporary, filePath)
  } finally {
    if (existsSync(temporary)) rmSync(temporary, { force: true })
  }
}
