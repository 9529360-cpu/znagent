const RELAY_BASE = 'http://127.0.0.1:19991'
const PROTOCOL_VERSION = 1
const EXTENSION_ID = 'likpiakgiamipheeekdgekdahafjinnh'
const STORAGE_KEY = 'znAuthorizedTabId'
const SENSITIVE_AUTOCOMPLETE = new Set([
  'current-password',
  'new-password',
  'one-time-code',
  'cc-number',
  'cc-csc',
  'cc-exp',
  'cc-exp-month',
  'cc-exp-year'
])

let commandLoopTabId = null

function isHttpPage(url) {
  try {
    const parsed = new URL(String(url || ''))
    return parsed.protocol === 'http:' || parsed.protocol === 'https:'
  } catch {
    return false
  }
}

function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms))
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

async function debuggerCommand(tabId, method, params = {}) {
  return chrome.debugger.sendCommand({ tabId }, method, params)
}

function axProperty(node, name) {
  const property = Array.isArray(node?.properties)
    ? node.properties.find(item => String(item?.name || '') === name)
    : null
  return property?.value?.value
}

function attributesObject(attributes) {
  const result = {}
  const raw = Array.isArray(attributes) ? attributes : []
  for (let index = 0; index + 1 < raw.length; index += 2) {
    result[String(raw[index] || '').toLowerCase()] = String(raw[index + 1] || '')
  }
  return result
}

function normalizedAutocomplete(value) {
  return String(value || '')
    .toLowerCase()
    .split(/\s+/)
    .filter(Boolean)
}

async function sha256Text(value) {
  const encoded = new TextEncoder().encode(String(value || ''))
  const digest = await crypto.subtle.digest('SHA-256', encoded)
  return Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, '0')).join('')
}

function codePointLength(value) {
  return Array.from(String(value || '')).length
}

async function currentTabEvidence(tabId) {
  const tab = await chrome.tabs.get(tabId)
  const url = String(tab?.url || '')
  if (!isHttpPage(url)) {
    throw new Error('authorized tab is no longer a normal HTTP(S) page')
  }
  return {
    tab_id: tabId,
    url,
    title: String(tab?.title || '')
  }
}

async function exactNamedTextbox(tabId, targetName) {
  const name = String(targetName || '')
  if (!name || name.length > 512) {
    throw new Error('textbox observation requires one bounded exact accessible name')
  }
  const tree = await debuggerCommand(tabId, 'Accessibility.getFullAXTree')
  const nodes = Array.isArray(tree?.nodes) ? tree.nodes : []
  const matches = nodes.filter(node => {
    if (node?.ignored === true) return false
    const role = String(node?.role?.value || '').toLowerCase()
    const accessibleName = String(node?.name?.value || '')
    return (role === 'textbox' || role === 'searchbox') && accessibleName === name
  })
  if (matches.length !== 1) {
    throw new Error(
      matches.length === 0
        ? 'exact accessible textbox target was not found'
        : 'exact accessible textbox target is ambiguous'
    )
  }

  const node = matches[0]
  const backendNodeId = Number(node?.backendDOMNodeId || 0)
  if (!Number.isInteger(backendNodeId) || backendNodeId <= 0) {
    throw new Error('exact accessible textbox has no stable backend node identity')
  }
  if (axProperty(node, 'disabled') === true || axProperty(node, 'readonly') === true) {
    throw new Error('exact accessible textbox is disabled or read-only')
  }

  const described = await debuggerCommand(tabId, 'DOM.describeNode', { backendNodeId })
  const domNode = described?.node || {}
  const nodeName = String(domNode?.nodeName || '').toUpperCase()
  if (nodeName !== 'INPUT' && nodeName !== 'TEXTAREA') {
    throw new Error('safe text entry currently requires a native input or textarea')
  }
  const attributes = attributesObject(domNode?.attributes)
  const inputType = String(attributes.type || 'text').toLowerCase()
  if (inputType === 'password') {
    throw new Error('sensitive password fields are not available to autonomous text entry')
  }
  if ('disabled' in attributes || 'readonly' in attributes) {
    throw new Error('exact accessible textbox is disabled or read-only')
  }
  const autocomplete = normalizedAutocomplete(attributes.autocomplete)
  if (autocomplete.some(token => SENSITIVE_AUTOCOMPLETE.has(token) || token.startsWith('cc-'))) {
    throw new Error('sensitive credential or payment fields are not available to autonomous text entry')
  }

  const role = String(node?.role?.value || '').toLowerCase()
  const value = String(node?.value?.value || '')
  return {
    backendNodeId,
    targetId: `backend:${backendNodeId}`,
    role,
    name,
    value
  }
}

async function observeNamedTextbox(tabId, targetName) {
  const tab = await currentTabEvidence(tabId)
  const target = await exactNamedTextbox(tabId, targetName)
  return {
    ...tab,
    target_id: target.targetId,
    role: target.role,
    name: target.name,
    text_length: codePointLength(target.value),
    text_sha256: await sha256Text(target.value)
  }
}

async function typeNamedTextbox(tabId, args) {
  const targetName = String(args?.target_name || '')
  const targetId = String(args?.target_id || '')
  const expectedUrl = String(args?.expected_url || '')
  const text = args?.text
  if (typeof text !== 'string' || !text || text.length > 32768) {
    throw new Error('text entry requires one bounded non-empty string')
  }
  if (!isHttpPage(expectedUrl)) {
    throw new Error('text entry requires the fresh expected HTTP(S) URL')
  }

  const beforeTab = await currentTabEvidence(tabId)
  if (beforeTab.url !== expectedUrl) {
    throw new Error('authorized tab URL changed before text entry; fresh sensing is required')
  }
  const before = await exactNamedTextbox(tabId, targetName)
  if (before.targetId !== targetId) {
    throw new Error('authorized textbox identity changed before text entry; fresh sensing is required')
  }

  const expectedDigest = await sha256Text(text)
  const beforeDigest = await sha256Text(before.value)
  let inputSent = false
  try {
    await debuggerCommand(tabId, 'DOM.focus', { backendNodeId: before.backendNodeId })
    await debuggerCommand(tabId, 'Input.dispatchKeyEvent', {
      type: 'rawKeyDown',
      modifiers: 2,
      windowsVirtualKeyCode: 65,
      nativeVirtualKeyCode: 65,
      key: 'a',
      code: 'KeyA'
    })
    await debuggerCommand(tabId, 'Input.dispatchKeyEvent', {
      type: 'keyUp',
      modifiers: 2,
      windowsVirtualKeyCode: 65,
      nativeVirtualKeyCode: 65,
      key: 'a',
      code: 'KeyA'
    })
    await debuggerCommand(tabId, 'Input.insertText', { text })
    inputSent = true

    const afterTab = await currentTabEvidence(tabId)
    const after = await exactNamedTextbox(tabId, targetName)
    const afterDigest = await sha256Text(after.value)
    const exactNode = after.targetId === before.targetId
    const verified = Boolean(
      exactNode &&
      afterTab.url === beforeTab.url &&
      codePointLength(after.value) === codePointLength(text) &&
      afterDigest === expectedDigest
    )
    return {
      tab_id: tabId,
      url_before: beforeTab.url,
      url_after: afterTab.url,
      target_id: after.targetId,
      input_sent: true,
      exact_node_continuity: exactNode,
      text_length_before: codePointLength(before.value),
      text_sha256_before: beforeDigest,
      text_length_after: codePointLength(after.value),
      text_sha256_after: afterDigest,
      expected_text_length: codePointLength(text),
      expected_text_sha256: expectedDigest,
      expected_utf16_units: text.length,
      postcondition: verified ? 'same_exact_target_text_equals_requested' : ''
    }
  } catch (error) {
    if (!inputSent) throw error
    const emptyDigest = await sha256Text('')
    return {
      tab_id: tabId,
      url_before: beforeTab.url,
      url_after: beforeTab.url,
      target_id: before.targetId,
      input_sent: true,
      exact_node_continuity: false,
      text_length_before: codePointLength(before.value),
      text_sha256_before: beforeDigest,
      text_length_after: 0,
      text_sha256_after: emptyDigest,
      expected_text_length: codePointLength(text),
      expected_text_sha256: expectedDigest,
      expected_utf16_units: text.length,
      postcondition: '',
      verification_error: String(error instanceof Error ? error.message : error).slice(0, 512)
    }
  }
}

async function executeResidentCommand(tabId, command) {
  const kind = String(command?.kind || '')
  if (kind === 'probe_current_tab') {
    return currentTabEvidence(tabId)
  }
  if (kind === 'observe_named_textbox') {
    return observeNamedTextbox(tabId, command?.args?.target_name)
  }
  if (kind === 'type_named_textbox') {
    return typeNamedTextbox(tabId, command?.args || {})
  }
  throw new Error(`unsupported ZN browser command: ${kind}`)
}

async function commandLoop(tabId) {
  if (commandLoopTabId === tabId) return
  commandLoopTabId = tabId
  try {
    while ((await ownedTabId()) === tabId) {
      let body
      try {
        body = await relay('/v1/command/next', { tab_id: tabId, wait_seconds: 20 })
      } catch {
        if ((await ownedTabId()) !== tabId) return
        await sleep(500)
        continue
      }
      const command = body?.command
      if (!command) continue

      let success = false
      let result = {}
      let error = null
      try {
        result = await executeResidentCommand(tabId, command)
        success = true
      } catch (commandError) {
        error = commandError instanceof Error ? commandError.message : String(commandError)
      }

      try {
        await relay('/v1/command/result', {
          tab_id: tabId,
          command_id: String(command.command_id || ''),
          success,
          result,
          error
        })
      } catch {
        // Resident may have stopped or revoked authority while this exact command
        // was executing. Never retry the command or replay its result automatically.
      }
    }
  } finally {
    if (commandLoopTabId === tabId) commandLoopTabId = null
  }
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
      void commandLoop(tabId)
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

void (async () => {
  const tabId = await ownedTabId()
  if (tabId !== null) void commandLoop(tabId)
})()
