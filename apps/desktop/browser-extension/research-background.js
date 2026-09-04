importScripts('background.js')

const baseExecuteResidentCommand = executeResidentCommand
const baseCurrentTabEvidence = currentTabEvidence
const baseDetachOwnedTab = detachOwnedTab
const CHILD_STORAGE_KEY = 'znAuthorizedChildTabIds'
const CHILD_ROOT_STORAGE_KEY = 'znAuthorizedChildRootTabId'
const MAX_ACTION_CHILDREN = 4

async function childRegistry() {
  const state = await chrome.storage.session.get([CHILD_STORAGE_KEY, CHILD_ROOT_STORAGE_KEY])
  const root = Number(state?.[CHILD_ROOT_STORAGE_KEY] || 0)
  const raw = Array.isArray(state?.[CHILD_STORAGE_KEY]) ? state[CHILD_STORAGE_KEY] : []
  const children = raw
    .map(value => Number(value || 0))
    .filter(value => Number.isInteger(value) && value > 0)
    .slice(0, MAX_ACTION_CHILDREN)
  return {
    rootTabId: Number.isInteger(root) && root > 0 ? root : null,
    childTabIds: [...new Set(children)]
  }
}

async function rememberChildTab(rootTabId, childTabId) {
  const registry = await childRegistry()
  const children = registry.rootTabId === rootTabId ? registry.childTabIds : []
  if (!children.includes(childTabId)) children.push(childTabId)
  if (children.length > MAX_ACTION_CHILDREN) {
    throw new Error('authorized child task-page allowance exceeded its bounded limit')
  }
  await chrome.storage.session.set({
    [CHILD_ROOT_STORAGE_KEY]: rootTabId,
    [CHILD_STORAGE_KEY]: children
  })
}

async function forgetChildTab(childTabId) {
  const registry = await childRegistry()
  const children = registry.childTabIds.filter(value => value !== childTabId)
  if (children.length === 0) {
    await chrome.storage.session.remove([CHILD_STORAGE_KEY, CHILD_ROOT_STORAGE_KEY])
    return
  }
  await chrome.storage.session.set({ [CHILD_STORAGE_KEY]: children })
}

async function clearChildTabs({ detach = true, notifyRelay = true } = {}) {
  const registry = await childRegistry()
  for (const childTabId of registry.childTabIds) {
    if (detach) {
      try {
        await chrome.debugger.detach({ tabId: childTabId })
      } catch {
        // The child may already be closed or detached.
      }
    }
    if (notifyRelay && registry.rootTabId !== null) {
      try {
        await relay('/v1/child/detach', {
          tab_id: registry.rootTabId,
          child_tab_id: childTabId
        })
      } catch {
        // Root revocation clears child authority in the relay even if this call races it.
      }
    }
  }
  await chrome.storage.session.remove([CHILD_STORAGE_KEY, CHILD_ROOT_STORAGE_KEY])
}

async function debuggerPageEvidence(tabId) {
  const evaluated = await debuggerCommand(tabId, 'Runtime.evaluate', {
    expression: `(() => ({
      url: String(location.href || ''),
      title: String(document.title || ''),
      ready: String(document.readyState || '')
    }))()`,
    returnByValue: true,
    awaitPromise: false
  })
  if (evaluated?.exceptionDetails) {
    throw new Error('debugger page identity evaluation failed')
  }
  const value = evaluated?.result?.value
  if (!value || typeof value !== 'object') {
    throw new Error('debugger page identity returned no structured evidence')
  }
  const url = String(value.url || '')
  if (!isHttpPage(url)) {
    throw new Error('task page is not a normal HTTP(S) page')
  }
  return {
    tab_id: tabId,
    url,
    title: String(value.title || '').slice(0, 512),
    ready: String(value.ready || '')
  }
}

currentTabEvidence = async function (tabId) {
  try {
    return await baseCurrentTabEvidence(tabId)
  } catch (error) {
    const registry = await childRegistry()
    if (!registry.childTabIds.includes(tabId)) throw error
    const evidence = await debuggerPageEvidence(tabId)
    return {
      tab_id: tabId,
      url: evidence.url,
      title: evidence.title
    }
  }
}

function directChildCapture(openerTabId) {
  const children = new Set()
  const listener = tab => {
    const childTabId = Number(tab?.id || 0)
    const opener = Number(tab?.openerTabId || 0)
    if (
      Number.isInteger(childTabId) && childTabId > 0 &&
      opener === openerTabId
    ) {
      children.add(childTabId)
    }
  }
  chrome.tabs.onCreated.addListener(listener)
  return async () => {
    await sleep(250)
    chrome.tabs.onCreated.removeListener(listener)
    return [...children]
  }
}

async function verifyAndRegisterDirectChild(rootTabId, command, childTabId, expectedUrl) {
  let attached = false
  try {
    await chrome.debugger.attach({ tabId: childTabId }, '1.3')
    attached = true
    let evidence = null
    const deadline = Date.now() + 3000
    while (Date.now() < deadline) {
      try {
        const current = await debuggerPageEvidence(childTabId)
        if (current.url === expectedUrl) {
          evidence = current
          break
        }
      } catch {
        // A newly created child may still be at about:blank during its first ticks.
      }
      await sleep(50)
    }
    if (evidence === null) {
      throw new Error('direct child did not reach the Resident-derived expected result URL')
    }
    await relay('/v1/child/attach', {
      tab_id: rootTabId,
      command_id: String(command?.command_id || ''),
      child_tab_id: childTabId,
      opener_tab_id: Number(command?.target_tab_id || rootTabId),
      url: evidence.url,
      title: evidence.title
    })
    await rememberChildTab(rootTabId, childTabId)
    return evidence
  } catch (error) {
    if (attached) {
      try {
        await chrome.debugger.detach({ tabId: childTabId })
      } catch {
        // Best effort after a child failed identity validation.
      }
    }
    throw error
  }
}

async function executeDirectChildClick(rootTabId, command) {
  const targetTabId = Number(command?.target_tab_id || rootTabId)
  const expectedUrl = String(command?.args?.expected_url_after || '')
  if (!isHttpPage(expectedUrl)) {
    throw new Error('direct child click requires one expected HTTP(S) result URL')
  }
  const finishCapture = directChildCapture(targetTabId)
  const baseResult = await baseExecuteResidentCommand(targetTabId, command)
  const childIds = await finishCapture()
  if (
    baseResult?.click_sent !== true ||
    baseResult?.target_revalidated_before_dispatch !== true
  ) {
    return baseResult
  }
  if (childIds.length !== 1) {
    return {
      ...baseResult,
      postcondition: '',
      verification_error: childIds.length === 0
        ? 'exact click was dispatched but no unique direct child page was observed; refusing replay'
        : 'exact click was dispatched but multiple direct child pages were observed; refusing authority choice or replay'
    }
  }
  try {
    const child = await verifyAndRegisterDirectChild(
      rootTabId,
      command,
      childIds[0],
      expectedUrl
    )
    return {
      ...baseResult,
      tab_id: child.tab_id,
      opener_tab_id: targetTabId,
      url_after: child.url,
      expected_url: expectedUrl,
      direct_child: true,
      postcondition: 'direct_child_url_equals_after_fresh_semantic_button_click',
      verification_error: undefined
    }
  } catch (error) {
    return {
      ...baseResult,
      postcondition: '',
      verification_error: String(error instanceof Error ? error.message : error).slice(0, 512)
    }
  }
}

async function discoverBoundedReferenceContext(tabId) {
  const tab = await currentTabEvidence(tabId)
  const evaluated = await debuggerCommand(tabId, 'Runtime.evaluate', {
    expression: `(() => {
      const visible = element => {
        if (!element || !element.isConnected || element.hidden) return false;
        const style = getComputedStyle(element);
        const rect = element.getBoundingClientRect();
        return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
      };
      const results = [];
      for (const anchor of Array.from(document.querySelectorAll('a[href]'))) {
        if (results.length >= 16 || !visible(anchor)) continue;
        let href = '';
        try { href = new URL(anchor.href, location.href).href; } catch { continue; }
        if (!/^https?:/i.test(href)) continue;
        const text = String(anchor.innerText || anchor.textContent || '').trim().replace(/\\s+/g, ' ').slice(0, 240);
        if (!text) continue;
        results.push({ href, text });
      }
      return results;
    })()`,
    returnByValue: true,
    awaitPromise: false
  })
  if (evaluated?.exceptionDetails) {
    throw new Error('authorized-page reference discovery returned JavaScript exception details')
  }
  const references = Array.isArray(evaluated?.result?.value) ? evaluated.result.value : []
  const searchForm = await discoverUniqueSearchForm(tabId)
  return {
    ...tab,
    references: references
      .filter(item => item && isHttpPage(item.href))
      .slice(0, 16)
      .map(item => ({
        href: String(item.href || '').slice(0, 2048),
        text: String(item.text || '').slice(0, 240)
      })),
    search_form: {
      form_method: searchForm.form_method,
      form_action: searchForm.form_action,
      query_parameter: searchForm.query_parameter,
      textbox_target_id: searchForm.textbox_target_id,
      textbox_name: searchForm.textbox_name,
      button_target_id: searchForm.button_target_id,
      button_name: searchForm.button_name
    }
  }
}

executeResidentCommand = async function (rootTabId, command) {
  const targetTabId = Number(command?.target_tab_id || rootTabId)
  if (
    String(command?.kind || '') === 'click_named_button_to_url' &&
    command?.args?.expect_direct_child === true
  ) {
    return executeDirectChildClick(rootTabId, command)
  }
  if (
    String(command?.kind || '') === 'probe_current_tab' &&
    command?.args?.discover_reference_context === true
  ) {
    return discoverBoundedReferenceContext(targetTabId)
  }
  return baseExecuteResidentCommand(targetTabId, command)
}

detachOwnedTab = async function (tabId, options = {}) {
  await clearChildTabs({ detach: true, notifyRelay: options.notifyRelay !== false })
  return baseDetachOwnedTab(tabId, options)
}

chrome.tabs.onRemoved.addListener(tabId => {
  void (async () => {
    const registry = await childRegistry()
    if (registry.rootTabId === tabId) {
      await clearChildTabs({ detach: true, notifyRelay: false })
      return
    }
    if (!registry.childTabIds.includes(tabId) || registry.rootTabId === null) return
    try {
      await relay('/v1/child/detach', {
        tab_id: registry.rootTabId,
        child_tab_id: tabId
      })
    } catch {
      // Closing a child locally already destroys that task-page attachment.
    }
    await forgetChildTab(tabId)
  })()
})

chrome.tabs.onReplaced.addListener((addedTabId, removedTabId) => {
  void (async () => {
    const registry = await childRegistry()
    const rootTabId = await ownedTabId()
    if (rootTabId === removedTabId || registry.rootTabId === removedTabId) {
      try {
        await relay('/v1/detach', { tab_id: removedTabId })
      } catch {
        // Replacement destroys the old identity; never transfer authority to addedTabId.
      }
      await clearChildTabs({ detach: true, notifyRelay: false })
      await forgetOwnedTab()
      return
    }
    if (!registry.childTabIds.includes(removedTabId) || registry.rootTabId === null) return
    try {
      await relay('/v1/child/detach', {
        tab_id: registry.rootTabId,
        child_tab_id: removedTabId
      })
    } catch {
      // A replaced child loses task-page identity; addedTabId is not auto-authorized.
    }
    await forgetChildTab(removedTabId)
  })()
})

chrome.debugger.onDetach.addListener(source => {
  void (async () => {
    const tabId = Number(source?.tabId || 0)
    if (!Number.isInteger(tabId) || tabId <= 0) return
    const registry = await childRegistry()
    if (!registry.childTabIds.includes(tabId) || registry.rootTabId === null) return
    try {
      await relay('/v1/child/detach', {
        tab_id: registry.rootTabId,
        child_tab_id: tabId
      })
    } catch {
      // Local debugger detach is authoritative for the child task page.
    }
    await forgetChildTab(tabId)
  })()
})
