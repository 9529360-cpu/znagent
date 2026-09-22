import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'

import {
  ZN_DESKTOP_RESOURCES,
  resolveZnLocale,
  type ZnDesktopLocaleState,
  type ZnLocalePreference
} from '../../localization/zn-localization'

let localeState: ZnDesktopLocaleState = {
  preference: 'system',
  resolvedLocale: resolveZnLocale('system', navigator.languages),
  preferredSystemLanguages: [...navigator.languages]
}

function applyDocumentLocale(state: ZnDesktopLocaleState): void {
  document.documentElement.lang = state.resolvedLocale
  document.documentElement.dir = 'ltr'
}

export function getZnDesktopLocaleState(): ZnDesktopLocaleState {
  return {
    ...localeState,
    preferredSystemLanguages: [...localeState.preferredSystemLanguages]
  }
}

export async function initializeZnDesktopI18n(): Promise<ZnDesktopLocaleState> {
  try {
    const state = await window.znDesktop?.shell?.getLocaleState?.()
    if (state) localeState = state
  } catch {
    // Renderer fallback stays usable when the preload bridge is absent, such as
    // static visual inspection of the bundled shell.
  }

  await i18n
    .use(initReactI18next)
    .init({
      resources: ZN_DESKTOP_RESOURCES,
      lng: localeState.resolvedLocale,
      fallbackLng: 'en-US',
      supportedLngs: ['en-US', 'zh-CN'],
      keySeparator: false,
      nsSeparator: false,
      interpolation: { escapeValue: false },
      react: { useSuspense: false }
    })

  applyDocumentLocale(localeState)
  return getZnDesktopLocaleState()
}

export async function setZnDesktopLocalePreference(
  preference: ZnLocalePreference
): Promise<ZnDesktopLocaleState> {
  let next: ZnDesktopLocaleState
  try {
    next = await window.znDesktop.shell.setLocalePreference(preference)
  } catch {
    const preferredSystemLanguages = [...navigator.languages]
    next = {
      preference,
      resolvedLocale: resolveZnLocale(preference, preferredSystemLanguages),
      preferredSystemLanguages
    }
  }

  localeState = next
  await i18n.changeLanguage(next.resolvedLocale)
  applyDocumentLocale(next)
  return getZnDesktopLocaleState()
}

export default i18n
