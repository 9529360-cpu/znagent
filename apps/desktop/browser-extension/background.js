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

async function fullAxTree(tabId) {
  const tree = await debuggerCommand(tabId, 'Accessibility.getFullAXTree')
  return Array.isArray(tree?.nodes) ? tree.nodes : []
}

async function exactNamedTextbox(tabId, targetName) {
  const name = String(targetName || '')
  if (!name || name.length > 512) {
    throw new Error('textbox observation requires one bounded exact accessible name')
  }
  const nodes = await fullAxTree(tabId)
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

async function exactNamedButton(tabId, targetName) {
  const name = String(targetName || '')
  if (!name || name.length > 256) {
    throw new Error('button observation requires one bounded exact accessible name')
  }
  const nodes = await fullAxTree(tabId)
  const matches = nodes.filter(node => {
    if (node?.ignored === true) return false
    return String(node?.role?.value || '').toLowerCase() === 'button' &&
      String(node?.name?.value || '') === name
  })
  if (matches.length !== 1) {
    throw new Error(
      matches.length === 0
        ? 'exact accessible button target was not found'
        : 'exact accessible button target is ambiguous'
    )
  }

  const node = matches[0]
  const backendNodeId = Number(node?.backendDOMNodeId || 0)
  if (!Number.isInteger(backendNodeId) || backendNodeId <= 0) {
    throw new Error('exact accessible button has no stable backend node identity')
  }
  if (axProperty(node, 'disabled') === true) {
    throw new Error('exact accessible button is disabled')
  }
  const described = await debuggerCommand(tabId, 'DOM.describeNode', { backendNodeId })
  const domNode = described?.node || {}
  if (String(domNode?.nodeName || '').toUpperCase() !== 'BUTTON') {
    throw new Error('safe button interaction currently requires a native button element')
  }
  const attributes = attributesObject(domNode?.attributes)
  if ('disabled' in attributes) {
    throw new Error('exact accessible button is disabled')
  }
  return {
    backendNodeId,
    targetId: `backend:${backendNodeId}`,
    role: 'button',
    name
  }
}

async function discoverUniqueSearchForm(tabId) {
  const tab = await currentTabEvidence(tabId)
  const tree = await fullAxTree(tabId)
  const candidates = []

  for (const node of tree) {
    if (node?.ignored === true) continue
    const role = String(node?.role?.value || '').toLowerCase()
    if (role !== 'searchbox' && role !== 'textbox') continue
    const backendNodeId = Number(node?.backendDOMNodeId || 0)
    if (!Number.isInteger(backendNodeId) || backendNodeId <= 0) continue
    if (axProperty(node, 'disabled') === true || axProperty(node, 'readonly') === true) continue

    const described = await debuggerCommand(tabId, 'DOM.describeNode', { backendNodeId })
    const domNode = described?.node || {}
    if (String(domNode?.nodeName || '').toUpperCase() !== 'INPUT') continue
    const attributes = attributesObject(domNode?.attributes)
    const inputType = String(attributes.type || 'text').toLowerCase()
    if (inputType !== 'search' && role !== 'searchbox') continue
    if ('disabled' in attributes || 'readonly' in attributes) continue
    const autocomplete = normalizedAutocomplete(attributes.autocomplete)
    if (autocomplete.some(token => SENSITIVE_AUTOCOMPLETE.has(token) || token.startsWith('cc-'))) continue
    const parameter = String(attributes.name || '').trim()
    if (!parameter || parameter.length > 128) continue
    const accessibleName = String(node?.name?.value || '').trim()
    if (!accessibleName || accessibleName.length > 160) continue
    if (String(node?.value?.value || '') !== '') continue

    const resolved = await debuggerCommand(tabId, 'DOM.resolveNode', { backendNodeId })
    const inputObjectId = String(resolved?.object?.objectId || '')
    if (!inputObjectId) continue
    const metadataCall = await debuggerCommand(tabId, 'Runtime.callFunctionOn', {
      objectId: inputObjectId,
      functionDeclaration: `function(){
        const form = this.form;
        if (!form) return null;
        const method = String(form.getAttribute('method') || 'get').toLowerCase();
        const action = new URL(form.getAttribute('action') || location.href, location.href).href;
        const buttons = Array.from(form.querySelectorAll('button')).filter(button => {
          if (button.disabled) return false;
          const type = String(button.getAttribute('type') || 'submit').toLowerCase();
          return type === 'submit';
        });
        const extraNamedControls = Array.from(form.elements || []).filter(element => {
          if (element === this || element.disabled || !element.name) return false;
          if (element.tagName === 'BUTTON' && !element.name) return false;
          return true;
        }).length;
        return {
          method,
          action,
          button_count: buttons.length,
          extra_named_controls: extraNamedControls
        };
      }`,
      returnByValue: true,
      awaitPromise: false
    })
    if (metadataCall?.exceptionDetails) continue
    const metadata = metadataCall?.result?.value
    if (!metadata || typeof metadata !== 'object') continue
    if (String(metadata.method || '').toLowerCase() !== 'get') continue
    if (Number(metadata.button_count || 0) !== 1) continue
    if (Number(metadata.extra_named_controls || 0) !== 0) continue
    const actionUrl = String(metadata.action || '')
    if (!isHttpPage(actionUrl)) continue
    let currentOrigin
    let actionOrigin
    try {
      currentOrigin = new URL(tab.url).origin
      actionOrigin = new URL(actionUrl).origin
    } catch {
      continue
    }
    if (currentOrigin !== actionOrigin) continue

    const buttonCall = await debuggerCommand(tabId, 'Runtime.callFunctionOn', {
      objectId: inputObjectId,
      functionDeclaration: `function(){
        const form = this.form;
        if (!form) return null;
        const buttons = Array.from(form.querySelectorAll('button')).filter(button => {
          if (button.disabled) return false;
          const type = String(button.getAttribute('type') || 'submit').toLowerCase();
          return type === 'submit';
        });
        return buttons.length === 1 ? buttons[0] : null;
      }`,
      returnByValue: false,
      awaitPromise: false
    })
    if (buttonCall?.exceptionDetails) continue
    const buttonObjectId = String(buttonCall?.result?.objectId || '')
    if (!buttonObjectId) continue
    const buttonDescription = await debuggerCommand(tabId, 'DOM.describeNode', {
      objectId: buttonObjectId
    })
    const buttonBackendNodeId = Number(buttonDescription?.node?.backendNodeId || 0)
    if (!Number.isInteger(buttonBackendNodeId) || buttonBackendNodeId <= 0) continue
    const buttonNodes = tree.filter(candidate => {
      return candidate?.ignored !== true &&
        Number(candidate?.backendDOMNodeId || 0) === buttonBackendNodeId &&
        String(candidate?.role?.value || '').toLowerCase() === 'button'
    })
    if (buttonNodes.length !== 1) continue
    const buttonName = String(buttonNodes[0]?.name?.value || '').trim()
    if (!buttonName || buttonName.length > 160) continue

    candidates.push({
      textboxBackendNodeId: backendNodeId,
      textboxTargetId: `backend:${backendNodeId}`,
      textboxName: accessibleName,
      buttonBackendNodeId,
      buttonTargetId: `backend:${buttonBackendNodeId}`,
      buttonName,
      actionUrl,
      parameter
    })
  }

  if (candidates.length !== 1) {
    throw new Error(
      candidates.length === 0
        ? 'no unique safe GET search form is visible on the authorized page'
        : 'multiple safe search forms are visible; autonomous target choice is ambiguous'
    )
  }

  const candidate = candidates[0]
  const exactTextbox = await exactNamedTextbox(tabId, candidate.textboxName)
  const exactButton = await exactNamedButton(tabId, candidate.buttonName)
  if (
    exactTextbox.backendNodeId !== candidate.textboxBackendNodeId ||
    exactButton.backendNodeId !== candidate.buttonBackendNodeId
  ) {
    throw new Error('search form target identity changed during discovery; fresh sensing is required')
  }

  return {
    ...tab,
    form_method: 'get',
    form_action: candidate.actionUrl,
    query_parameter: candidate.parameter,
    textbox_target_id: candidate.textboxTargetId,
    textbox_name: candidate.textboxName,
    button_target_id: candidate.buttonTargetId,
    button_name: candidate.buttonName
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

async function observeNamedButton(tabId, targetName) {
  const tab = await currentTabEvidence(tabId)
  const target = await exactNamedButton(tabId, targetName)
  return {
    ...tab,
    target_id: target.targetId,
    role: target.role,
    name: target.name
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

async function clickNamedButtonToUrl(tabId, args) {
  const targetName = String(args?.target_name || '')
  const targetId = String(args?.target_id || '')
  const expectedUrlBefore = String(args?.expected_url_before || '')
  const expectedUrlAfter = String(args?.expected_url_after || '')
  if (!isHttpPage(expectedUrlBefore) || !isHttpPage(expectedUrlAfter)) {
    throw new Error('button click requires fresh expected HTTP(S) URLs')
  }

  const beforeTab = await currentTabEvidence(tabId)
  if (beforeTab.url !== expectedUrlBefore) {
    throw new Error('authorized tab URL changed before button click; fresh sensing is required')
  }
  const before = await exactNamedButton(tabId, targetName)
  if (before.targetId !== targetId) {
    throw new Error('authorized button identity changed before click; fresh sensing is required')
  }

  let clickSent = false
  try {
    const resolved = await debuggerCommand(tabId, 'DOM.resolveNode', {
      backendNodeId: before.backendNodeId
    })
    const objectId = String(resolved?.object?.objectId || '')
    if (!objectId) {
      throw new Error('exact accessible button could not be resolved for dispatch')
    }
    // Crossing this call is the non-replayable boundary. Navigation may destroy
    // the execution context before CDP returns even though the click already ran.
    clickSent = true
    const dispatched = await debuggerCommand(tabId, 'Runtime.callFunctionOn', {
      objectId,
      functionDeclaration: 'function(){ this.click(); }',
      returnByValue: true,
      awaitPromise: false
    })
    if (dispatched?.exceptionDetails) {
      throw new Error('exact accessible button click returned JavaScript exception details')
    }

    let afterTab = await currentTabEvidence(tabId)
    const deadline = Date.now() + 3000
    while (afterTab.url !== expectedUrlAfter && Date.now() < deadline) {
      await sleep(50)
      afterTab = await currentTabEvidence(tabId)
    }
    const verified = afterTab.url === expectedUrlAfter
    return {
      tab_id: tabId,
      url_before: beforeTab.url,
      url_after: afterTab.url,
      target_id: before.targetId,
      click_sent: true,
      exact_node_continuity: true,
      target_revalidated_before_dispatch: true,
      expected_url: expectedUrlAfter,
      postcondition: verified ? 'url_equals_after_fresh_semantic_button_click' : ''
    }
  } catch (error) {
    if (!clickSent) throw error
    let afterUrl = beforeTab.url
    try {
      afterUrl = (await currentTabEvidence(tabId)).url
    } catch {
      // Keep the last proven pre-click URL only as uncertainty context.
    }
    return {
      tab_id: tabId,
      url_before: beforeTab.url,
      url_after: afterUrl,
      target_id: before.targetId,
      click_sent: true,
      exact_node_continuity: true,
      target_revalidated_before_dispatch: true,
      expected_url: expectedUrlAfter,
      postcondition: '',
      verification_error: String(error instanceof Error ? error.message : error).slice(0, 512)
    }
  }
}

async function executeResidentCommand(tabId, command) {
  const kind = String(command?.kind || '')
  if (kind === 'probe_current_tab') {
    if (command?.args?.discover_unique_search_form === true) {
      return discoverUniqueSearchForm(tabId)
    }
    return currentTabEvidence(tabId)
  }
  if (kind === 'observe_named_textbox') {
    return observeNamedTextbox(tabId, command?.args?.target_name)
  }
  if (kind === 'type_named_textbox') {
    return typeNamedTextbox(tabId, command?.args || {})
  }
  if (kind === 'observe_named_button') {
    return observeNamedButton(tabId, command?.args?.target_name)
  }
  if (kind === 'click_named_button_to_url') {
    return clickNamedButtonToUrl(tabId, command?.args || {})
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