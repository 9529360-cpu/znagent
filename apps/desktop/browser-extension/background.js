const RELAY_BASE = 'http://127.0.0.1:19991'
const PROTOCOL_VERSION = 1
const STORAGE_KEY = 'znAuthorizedTabId'

function isHttpPage(url) {
  try {
    const parsed = new URL(String(url || ''))
    return parsed.protocol === 'http:' || parsed.protocol === 'https:'
  } catch {
    return false
  }
}

async function relay(path, payload) {
  const response = await fetch(`${RELAY_BASE}${path}`, {
    method: 'POST',
    cache: 'no-store',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ protocol_version: PROTOCOL_VERSION, ...payload })
  })
  const body = await response.json().catch(() => ({}))
  if (!response.ok || body?.ok !== true) {
    throw new Error(String(body?.error || `ZN relay HTTP ${response.status}`))
  }
  return body
}

async function ownedTabId() {
  const state = await chrome.storage.session.get(STORAGE_KEY)
  const value = Number(state?.[STORAGE_KEY] || 0)
  return Number.isInteger(value) && value > 0 ? value : null
}

async function rememberOwnedTab(tabId) {
  await chrome.storage.session.set({ [STORAGE_KEY]: tabId })
}

async function forgetOwnedTab() {
  await chrome.storage.session.remove(STORAGE_KEY)
}

async function setAttachedUi(tabId, attached, title) {
  await chrome.action.setBadgeText({ tabId, text: attached ? 'ON' : '' })
  if (attached) {
    await chrome.action.setBadgeBackgroundColor({ tabId, color: '#2f7d32' })
  }
  await chrome.action.setTitle({
    tabId,
    title: title || (attached ? 'Revoke ZN access to this tab' : 'Allow ZN to use this tab')
  })
}

async function showError(tabId, message) {
  await chrome.action.setBadgeText({ tabId, text: '!' })
  await chrome.action.setBadgeBackgroundColor({ tabId, color: '#a12828' })
  await chrome.action.setTitle({ tabId, title: `ZN browser bridge: ${message}` })
}

async function detachOwnedTab(tabId, { notifyRelay = true } = {}) {
  try {
    await chrome.debugger.detach({ tabId })
  } catch {
    // The browser may already have detached the target. Ownership is still revoked.
  }
  if (notifyRelay) {
    try {
      await relay('/v1/detach', { tab_id: tabId })
    } catch {
      // Revocation is local-first. A restarted Resident has no durable tab authority.
    }
  }
  await forgetOwnedTab()
  await setAttachedUi(tabId, false)
}

chrome.action.onClicked.addListener(tab => {
  void (async () => {
    const tabId = Number(tab?.id || 0)
    if (!Number.isInteger(tabId) || tabId <= 0) return

    const currentOwned = await ownedTabId()
    if (currentOwned === tabId) {
      await detachOwnedTab(tabId)
      return
    }
    if (currentOwned !== null) {
      await showError(tabId, 'another tab is already authorized; revoke it first')
      return
    }
    if (!isHttpPage(tab.url)) {
      await showError(tabId, 'only normal HTTP(S) pages can be authorized')
      return
    }

    try {
      await chrome.debugger.attach({ tabId }, '1.3')
    } catch (error) {
      await showError(tabId, `cannot attach debugger: ${error instanceof Error ? error.message : String(error)}`)
      return
    }

    try {
      await relay('/v1/attach', {
        tab_id: tabId,
        url: String(tab.url || ''),
        title: String(tab.title || '')
      })
      await rememberOwnedTab(tabId)
      await setAttachedUi(tabId, true)
    } catch (error) {
      try {
        await chrome.debugger.detach({ tabId })
      } catch {
        // Best-effort rollback after relay rejection/unavailability.
      }
      await forgetOwnedTab()
      await showError(tabId, `authorization failed: ${error instanceof Error ? error.message : String(error)}`)
    }
  })()
})

chrome.debugger.onDetach.addListener(source => {
  void (async () => {
    const tabId = Number(source?.tabId || 0)
    if (!Number.isInteger(tabId) || tabId <= 0) return
    const currentOwned = await ownedTabId()
    if (currentOwned !== tabId) return
    try {
      await relay('/v1/detach', { tab_id: tabId })
    } catch {
      // The local authorization is still cleared below.
    }
    await forgetOwnedTab()
    await setAttachedUi(tabId, false)
  })()
})

chrome.tabs.onRemoved.addListener(tabId => {
  void (async () => {
    const currentOwned = await ownedTabId()
    if (currentOwned !== tabId) return
    try {
      await relay('/v1/detach', { tab_id: tabId })
    } catch {
      // Closing the tab already destroys its debugger authority.
    }
    await forgetOwnedTab()
  })()
})
