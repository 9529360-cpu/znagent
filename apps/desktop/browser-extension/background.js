const RELAY_BASE = 'http://127.0.0.1:19991'
const PROTOCOL_VERSION = 1
const EXTENSION_ID = 'likpiakgiamipheeekdgekdahafjinnh'
const STORAGE_KEY = 'znAuthorizedTabId'

let pollingTabId = null

function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms))
}

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
    headers: {
      'Content-Type': 'application/json',
      'X-ZN-Browser-Extension-Id': EXTENSION_ID
    },
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

async function cdp(tabId, method, params = {}) {
  return await chrome.debugger.sendCommand({ tabId }, method, params)
}

function runtimeValue(response, label) {
  if (response?.exceptionDetails) {
    throw new Error(`${label} raised in the page`)
  }
  const result = response?.result
  if (!result || !Object.prototype.hasOwnProperty.call(result, 'value')) {
    throw new Error(`${label} returned no bounded value`)
  }
  return result.value
}

async function sha256Utf8(value) {
  const bytes = new TextEncoder().encode(String(value))
  const digest = await crypto.subtle.digest('SHA-256', bytes)
  return Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, '0')).join('')
}

async function observePage(tabId) {
  const response = await cdp(tabId, 'Runtime.evaluate', {
    expression: `(() => ({
      url: String(location.href),
      title: String(document.title || '').slice(0, 512),
      load_state: String(document.readyState || '')
    }))()`,
    returnByValue: true
  })
  const value = runtimeValue(response, 'page observation')
  if (!value || !isHttpPage(value.url)) {
    throw new Error('authorized tab is not a normal HTTP(S) page')
  }
  return {
    url: String(value.url),
    title: String(value.title || '').slice(0, 512),
    load_state: String(value.load_state || '').slice(0, 32)
  }
}

async function exactTextboxBackendNode(tabId, targetName) {
  const expected = String(targetName || '').trim()
  if (!expected || expected.length > 256) {
    throw new Error('exact textbox name is invalid')
  }
  const tree = await cdp(tabId, 'Accessibility.getFullAXTree', {})
  const nodes = Array.isArray(tree?.nodes) ? tree.nodes : []
  const matches = nodes.filter(node => {
    return node?.ignored !== true &&
      String(node?.role?.value || '').toLowerCase() === 'textbox' &&
      String(node?.name?.value || '') === expected &&
      Number.isInteger(Number(node?.backendDOMNodeId || 0)) &&
      Number(node.backendDOMNodeId) > 0
  })
  if (matches.length !== 1) {
    throw new Error(matches.length === 0
      ? 'exact accessible textbox was not found'
      : 'exact accessible textbox is ambiguous')
  }
  return Number(matches[0].backendDOMNodeId)
}

async function inspectTextboxBackend(tabId, backendNodeId) {
  const resolved = await cdp(tabId, 'DOM.resolveNode', { backendNodeId })
  const objectId = String(resolved?.object?.objectId || '')
  if (!objectId) throw new Error('textbox DOM node could not be resolved')
  try {
    const response = await cdp(tabId, 'Runtime.callFunctionOn', {
      objectId,
      functionDeclaration: `function () {
        const element = this;
        const connected = Boolean(element && element.isConnected);
        const tag = String(element && element.tagName || '').toLowerCase();
        const inputType = String(element && element.getAttribute('type') || '').trim().toLowerCase();
        const isPassword = tag === 'input' && inputType === 'password';
        const supported = Boolean(tag === 'textarea' || (tag === 'input' && (inputType === '' || inputType === 'text')));
        const disabled = Boolean(element && element.disabled);
        const readOnly = Boolean(element && element.readOnly);
        const style = connected ? getComputedStyle(element) : null;
        const rect = connected ? element.getBoundingClientRect() : null;
        const visible = Boolean(connected && !element.hidden && style && style.display !== 'none' && style.visibility !== 'hidden' && rect && rect.width > 0 && rect.height > 0);
        return {
          connected,
          visible,
          supported,
          disabled,
          read_only: readOnly,
          is_password: isPassword,
          value: connected && supported && !isPassword ? String(element.value || '') : null
        };
      }`,
      returnByValue: true
    })
    const value = runtimeValue(response, 'textbox safety observation')
    if (!value?.connected) throw new Error('textbox is no longer connected')
    if (!value?.visible) throw new Error('textbox is not visible')
    if (!value?.supported) throw new Error('textbox is not a supported native text control')
    if (value?.is_password) throw new Error('password textbox is protected')
    if (value?.disabled) throw new Error('textbox is disabled')
    if (value?.read_only) throw new Error('textbox is read-only')
    const text = String(value?.value ?? '')
    return {
      text_length: Array.from(text).length,
      text_utf16_units: text.length,
      text_sha256: await sha256Utf8(text)
    }
  } finally {
    await cdp(tabId, 'Runtime.releaseObject', { objectId }).catch(() => {})
  }
}

async function observeNamedTextbox(tabId, payload) {
  const targetName = String(payload?.target_name || '').trim()
  const page = await observePage(tabId)
  const backendNodeId = await exactTextboxBackendNode(tabId, targetName)
  const text = await inspectTextboxBackend(tabId, backendNodeId)
  return {
    ...page,
    target_name: targetName,
    role: 'textbox',
    backend_node_id: backendNodeId,
    ...text
  }
}

async function focusTextboxBackend(tabId, backendNodeId) {
  const resolved = await cdp(tabId, 'DOM.resolveNode', { backendNodeId })
  const objectId = String(resolved?.object?.objectId || '')
  if (!objectId) throw new Error('textbox DOM node could not be resolved for focus')
  try {
    const response = await cdp(tabId, 'Runtime.callFunctionOn', {
      objectId,
      functionDeclaration: `function () {
        if (!this || !this.isConnected) return false;
        this.focus();
        return document.activeElement === this;
      }`,
      returnByValue: true
    })
    if (runtimeValue(response, 'textbox focus') !== true) {
      throw new Error('textbox did not gain focus')
    }
  } finally {
    await cdp(tabId, 'Runtime.releaseObject', { objectId }).catch(() => {})
  }
}

async function typeNamedTextbox(tabId, payload) {
  const targetName = String(payload?.target_name || '').trim()
  const text = String(payload?.text ?? '')
  const expectedBackend = Number(payload?.expected_backend_node_id || 0)
  if (!targetName || targetName.length > 256) throw new Error('exact textbox name is invalid')
  if (!text || text.length > 512) throw new Error('requested text is outside the bounded size')
  if (Array.from(text).some(char => {
    const code = char.codePointAt(0)
    return code < 0x20 || code === 0x7f
  })) throw new Error('requested text contains control characters')
  if (!Number.isInteger(expectedBackend) || expectedBackend <= 0) {
    throw new Error('fresh textbox backend node identity is required')
  }

  const beforePage = await observePage(tabId)
  const backendNodeId = await exactTextboxBackendNode(tabId, targetName)
  if (backendNodeId !== expectedBackend) {
    throw new Error('exact textbox identity changed before input')
  }
  const before = await inspectTextboxBackend(tabId, backendNodeId)
  if (before.text_length !== 0 || before.text_utf16_units !== 0) {
    throw new Error('textbox is no longer empty; refusing replacement')
  }

  await focusTextboxBackend(tabId, backendNodeId)
  await cdp(tabId, 'Input.insertText', { text })

  const afterPage = await observePage(tabId)
  const backendAfter = await exactTextboxBackendNode(tabId, targetName)
  if (backendAfter !== backendNodeId) {
    throw new Error('exact textbox identity changed after input')
  }
  const after = await inspectTextboxBackend(tabId, backendAfter)
  const expectedSha = await sha256Utf8(text)
  const expectedLength = Array.from(text).length
  if (after.text_length !== expectedLength || after.text_sha256 !== expectedSha) {
    throw new Error('fresh textbox digest does not match requested text')
  }
  return {
    url_before: beforePage.url,
    url_after: afterPage.url,
    target_name: targetName,
    role: 'textbox',
    backend_node_id: backendNodeId,
    exact_node_continuity: true,
    input_sent: true,
    text_length_before: before.text_length,
    text_sha256_before: before.text_sha256,
    text_length_after: after.text_length,
    text_sha256_after: after.text_sha256,
    expected_text_length: expectedLength,
    expected_text_sha256: expectedSha,
    expected_utf16_units: text.length
  }
}

async function executeCommand(tabId, command) {
  const kind = String(command?.kind || '')
  const payload = command?.payload && typeof command.payload === 'object' ? command.payload : {}
  if (kind === 'observe_page') return await observePage(tabId)
  if (kind === 'observe_named_textbox') return await observeNamedTextbox(tabId, payload)
  if (kind === 'type_named_textbox') return await typeNamedTextbox(tabId, payload)
  throw new Error(`unsupported ZN browser command: ${kind}`)
}

async function announceOwnedTab(tabId) {
  const page = await observePage(tabId)
  const tab = await chrome.tabs.get(tabId)
  await relay('/v1/attach', {
    tab_id: tabId,
    url: page.url,
    title: String(tab?.title || page.title || '')
  })
}

function startCommandPolling(tabId) {
  if (pollingTabId === tabId) return
  pollingTabId = tabId
  void (async () => {
    let needsAnnouncement = false
    while (pollingTabId === tabId && await ownedTabId() === tabId) {
      try {
        if (needsAnnouncement) {
          await announceOwnedTab(tabId)
          needsAnnouncement = false
        }
        const envelope = await relay('/v1/command/next', { tab_id: tabId })
        const command = envelope?.command
        if (!command) continue
        const commandId = String(command?.command_id || '')
        if (!commandId) throw new Error('ZN relay returned a command without identity')
        try {
          const result = await executeCommand(tabId, command)
          await relay('/v1/command/result', {
            tab_id: tabId,
            command_id: commandId,
            result
          })
        } catch (error) {
          await relay('/v1/command/result', {
            tab_id: tabId,
            command_id: commandId,
            error: error instanceof Error ? error.message : String(error)
          }).catch(() => {})
        }
      } catch {
        needsAnnouncement = true
        await sleep(500)
      }
    }
    if (pollingTabId === tabId) pollingTabId = null
  })()
}

async function detachOwnedTab(tabId, { notifyRelay = true } = {}) {
  if (pollingTabId === tabId) pollingTabId = null
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
      await announceOwnedTab(tabId)
      await rememberOwnedTab(tabId)
      await setAttachedUi(tabId, true)
      startCommandPolling(tabId)
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
    if (pollingTabId === tabId) pollingTabId = null
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
    if (pollingTabId === tabId) pollingTabId = null
    try {
      await relay('/v1/detach', { tab_id: tabId })
    } catch {
      // Closing the tab already destroys its debugger authority.
    }
    await forgetOwnedTab()
  })()
})

void (async () => {
  const tabId = await ownedTabId()
  if (tabId === null) return
  try {
    await announceOwnedTab(tabId)
    await setAttachedUi(tabId, true)
    startCommandPolling(tabId)
  } catch {
    await forgetOwnedTab()
    await setAttachedUi(tabId, false).catch(() => {})
  }
})()
