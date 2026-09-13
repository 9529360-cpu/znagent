importScripts('background.js')

const baseExecuteResidentCommand = executeResidentCommand

function normalizedOrigin(url) {
  try {
    const parsed = new URL(String(url || ''))
    if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') return ''
    return parsed.origin
  } catch {
    return ''
  }
}

function boundedControlFree(value, limit) {
  const text = String(value || '').trim()
  if (!text || text.length > limit || /[\u0000-\u001f\u007f]/.test(text)) {
    throw new Error('causal popup evidence contained invalid bounded text')
  }
  return text
}

function causalPopupWatcher(rootTabId, expectedUrl) {
  let actionWindowOpen = false
  let rootRemoved = false
  let rootReplaced = false
  const createdTabIds = []
  const removedTabs = new Set()
  const replacedTabs = new Set()
  const windowOpenEvents = []

  const onCreated = tab => {
    if (!actionWindowOpen) return
    const createdId = Number(tab?.id || 0)
    if (!Number.isInteger(createdId) || createdId <= 0 || createdId === rootTabId) return
    if (!createdTabIds.includes(createdId)) createdTabIds.push(createdId)
  }
  const onRemoved = tabId => {
    if (!actionWindowOpen) return
    const removed = Number(tabId || 0)
    removedTabs.add(removed)
    if (removed === rootTabId) rootRemoved = true
  }
  const onReplaced = (addedTabId, removedTabId) => {
    if (!actionWindowOpen) return
    const removed = Number(removedTabId || 0)
    const added = Number(addedTabId || 0)
    replacedTabs.add(removed)
    replacedTabs.add(added)
    if (removed === rootTabId) rootReplaced = true
  }
  const onDebuggerEvent = (source, method, params) => {
    if (!actionWindowOpen) return
    if (Number(source?.tabId || 0) !== rootTabId || String(method || '') !== 'Page.windowOpen') return
    const url = String(params?.url || '')
    windowOpenEvents.push({
      url,
      matchesExpected: url === expectedUrl,
      userGesture: params?.userGesture === true
    })
  }

  chrome.tabs.onCreated.addListener(onCreated)
  chrome.tabs.onRemoved.addListener(onRemoved)
  chrome.tabs.onReplaced.addListener(onReplaced)
  chrome.debugger.onEvent.addListener(onDebuggerEvent)

  return {
    openActionWindow() { actionWindowOpen = true },
    closeActionWindow() { actionWindowOpen = false },
    snapshot() {
      return {
        createdTabIds: createdTabIds.slice(),
        rootRemoved,
        rootReplaced,
        removedTabs: new Set(removedTabs),
        replacedTabs: new Set(replacedTabs),
        windowOpenEvents: windowOpenEvents.slice()
      }
    },
    stop() {
      chrome.tabs.onCreated.removeListener(onCreated)
      chrome.tabs.onRemoved.removeListener(onRemoved)
      chrome.tabs.onReplaced.removeListener(onReplaced)
      chrome.debugger.onEvent.removeListener(onDebuggerEvent)
    }
  }
}

async function exactRootDebuggerTarget(rootTabId) {
  const targets = await chrome.debugger.getTargets()
  const matches = targets.filter(target =>
    String(target?.type || '') === 'page' && Number(target?.tabId || 0) === rootTabId
  )
  if (matches.length !== 1) {
    throw new Error('exact authorized root debugger target identity is unavailable or ambiguous')
  }
  const targetId = String(matches[0]?.id || '')
  if (!targetId) throw new Error('exact authorized root debugger target has no target id')
  return targetId
}

async function freshProtocolTargets(rootTabId) {
  const result = await debuggerCommand(rootTabId, 'Target.getTargets')
  return Array.isArray(result?.targetInfos) ? result.targetInfos : []
}

async function debuggerTargetTabsById() {
  const targets = await chrome.debugger.getTargets()
  const byId = new Map()
  for (const target of targets) {
    const id = String(target?.id || '')
    if (!id) continue
    byId.set(id, target)
  }
  return byId
}

async function classifyFreshActionWindowTargets(
  state,
  rootTabId,
  rootTargetId,
  baselineTargetIds
) {
  const causalTabs = []
  const unrelatedTabs = []
  const unresolvedTabs = []
  const protocolTargets = await freshProtocolTargets(rootTabId)
  const debuggerTargets = await debuggerTargetTabsById()

  for (const info of protocolTargets) {
    const targetId = String(info?.targetId || '')
    if (
      !targetId ||
      targetId === rootTargetId ||
      baselineTargetIds.has(targetId) ||
      String(info?.type || '') !== 'page'
    ) continue

    const debugTarget = debuggerTargets.get(targetId)
    const tabId = Number(debugTarget?.tabId || 0)
    if (!Number.isInteger(tabId) || tabId <= 0 || tabId === rootTabId) {
      unresolvedTabs.push({ targetId, tabId: 0 })
      continue
    }
    if (state.removedTabs.has(tabId) || state.replacedTabs.has(tabId)) {
      unresolvedTabs.push({ targetId, tabId })
      continue
    }

    const openerTargetId = String(info?.openerId || '')
    if (openerTargetId === rootTargetId) {
      causalTabs.push({
        tabId,
        openerTabId: rootTabId,
        targetId,
        openerTargetId: rootTargetId
      })
    } else if (openerTargetId) {
      unrelatedTabs.push({ tabId, targetId, openerTargetId })
    } else {
      unresolvedTabs.push({ targetId, tabId })
    }
  }
  return { causalTabs, unrelatedTabs, unresolvedTabs }
}

async function freshExactCausalTarget(
  rootTabId,
  rootTargetId,
  childTargetId,
  childTabId
) {
  const protocolTargets = await freshProtocolTargets(rootTabId)
  const matches = protocolTargets.filter(info => String(info?.targetId || '') === childTargetId)
  if (matches.length !== 1) {
    throw new Error('fresh causal child debugger target identity is unavailable or ambiguous')
  }
  const info = matches[0]
  if (
    String(info?.type || '') !== 'page' ||
    String(info?.openerId || '') !== rootTargetId ||
    childTargetId === rootTargetId
  ) {
    throw new Error('fresh causal child target no longer proves the exact root opener relationship')
  }

  const debuggerTargets = await debuggerTargetTabsById()
  const debugTarget = debuggerTargets.get(childTargetId)
  if (Number(debugTarget?.tabId || 0) !== childTabId) {
    throw new Error('fresh causal child target-to-tab identity changed before child authority derivation')
  }
  return info
}

async function waitForCausalChildOrSameTab(
  watcher,
  rootTabId,
  expectedUrl,
  rootTargetId,
  baselineTargetIds
) {
  const deadline = Date.now() + 3000
  let stableSince = 0
  let lastClassification = { causalTabs: [], unrelatedTabs: [], unresolvedTabs: [] }
  while (Date.now() < deadline) {
    const state = watcher.snapshot()
    if (state.rootRemoved || state.rootReplaced) {
      throw new Error('root tab disappeared or was replaced during causal popup action')
    }
    if (state.windowOpenEvents.length > 1) {
      throw new Error('multiple root Page.windowOpen events occurred in one action; refusing ambiguity')
    }
    if (state.windowOpenEvents.length === 1 && state.windowOpenEvents[0].matchesExpected !== true) {
      throw new Error('root Page.windowOpen URL did not match the expected child contract')
    }

    lastClassification = await classifyFreshActionWindowTargets(
      state,
      rootTabId,
      rootTargetId,
      baselineTargetIds
    )
    if (lastClassification.causalTabs.length > 1) {
      throw new Error('multiple freshly proven root-opener child targets were created by one action; refusing ambiguity')
    }
    if (
      lastClassification.causalTabs.length === 1 &&
      lastClassification.unresolvedTabs.length === 0 &&
      state.windowOpenEvents.length === 1 &&
      state.windowOpenEvents[0].matchesExpected === true
    ) {
      const child = lastClassification.causalTabs[0]
      if (child.tabId === rootTabId || state.removedTabs.has(child.tabId) || state.replacedTabs.has(child.tabId)) {
        throw new Error('causal child identity disappeared or was replaced before evidence completed')
      }
      if (!stableSince) stableSince = Date.now()
      if (Date.now() - stableSince >= 120) {
        return {
          kind: 'causal_child',
          child,
          state: {
            ...state,
            causalTabs: lastClassification.causalTabs.slice(),
            unrelatedCreatedCount: lastClassification.unrelatedTabs.length
          }
        }
      }
    } else {
      stableSince = 0
    }

    if (
      lastClassification.causalTabs.length === 0 &&
      lastClassification.unresolvedTabs.length === 0 &&
      state.windowOpenEvents.length === 0
    ) {
      try {
        const root = await currentTabEvidence(rootTabId)
        if (root.url === expectedUrl) {
          return {
            kind: 'same_tab',
            root,
            state: {
              ...state,
              causalTabs: [],
              unrelatedCreatedCount: lastClassification.unrelatedTabs.length
            }
          }
        }
      } catch {
        // A transient navigation state is not success; keep waiting for fresh evidence.
      }
    }
    await sleep(20)
  }

  const state = watcher.snapshot()
  lastClassification = await classifyFreshActionWindowTargets(
    state,
    rootTabId,
    rootTargetId,
    baselineTargetIds
  )
  if (state.windowOpenEvents.length === 1 && state.windowOpenEvents[0].matchesExpected !== true) {
    throw new Error('root Page.windowOpen URL did not match the expected child contract')
  }
  if (lastClassification.unresolvedTabs.length > 0) {
    throw new Error(
      `action-window target creation remained unresolved after fresh CDP opener re-read; created=${state.createdTabIds.length} unresolved=${lastClassification.unresolvedTabs.length} window_open=${state.windowOpenEvents.length}`
    )
  }
  if (lastClassification.causalTabs.length === 1 && state.windowOpenEvents.length === 0) {
    throw new Error('one fresh root-opener child target was proven but root Page.windowOpen corroboration was not observed')
  }
  if (lastClassification.causalTabs.length === 0 && state.windowOpenEvents.length === 1) {
    throw new Error('root Page.windowOpen was observed but no fresh CDP root-opener child target was proven')
  }
  throw new Error(
    `neither exact same-tab navigation nor one exact root-opener child target was proven inside the action window; created=${state.createdTabIds.length} causal=${lastClassification.causalTabs.length} unrelated=${lastClassification.unrelatedTabs.length} window_open=${state.windowOpenEvents.length}`
  )
}

async function exactChildPageEvidence(childTabId, expectedUrl) {
  const expectedOrigin = normalizedOrigin(expectedUrl)
  if (!expectedOrigin) throw new Error('causal child expected URL is invalid')
  const deadline = Date.now() + 3000
  while (Date.now() < deadline) {
    const evaluated = await debuggerCommand(childTabId, 'Runtime.evaluate', {
      expression: `(() => ({
        href: String(location.href || ''),
        title: String(document.title || ''),
        readyState: String(document.readyState || '')
      }))()`,
      returnByValue: true,
      awaitPromise: false
    })
    if (evaluated?.exceptionDetails) {
      throw new Error('causal child page probe returned JavaScript exception details')
    }
    const value = evaluated?.result?.value
    if (value && typeof value === 'object') {
      const url = String(value.href || '')
      if (isHttpPage(url) && normalizedOrigin(url) !== expectedOrigin) {
        throw new Error('causal child navigated outside the expected origin')
      }
      if (url === expectedUrl && String(value.readyState || '') !== 'loading') {
        return {
          url,
          title: boundedControlFree(value.title, 512),
          ready_state: String(value.readyState || '')
        }
      }
    }
    await sleep(30)
  }
  throw new Error('causal child URL did not reach the exact expected contract')
}

async function activateExactTab(tabId) {
  const before = await chrome.tabs.get(tabId)
  const windowId = Number(before?.windowId || 0)
  if (!Number.isInteger(windowId) || windowId <= 0) {
    throw new Error('task tab has invalid browser window identity')
  }
  await chrome.tabs.update(tabId, { active: true })
  await chrome.windows.update(windowId, { focused: true })
  const [tab, win] = await Promise.all([
    chrome.tabs.get(tabId),
    chrome.windows.get(windowId)
  ])
  if (tab?.active !== true || win?.focused !== true) {
    throw new Error('browser did not activate and focus the exact task tab')
  }
  return { windowId, active: true, focused: true }
}

async function clickNamedButtonWithCausalChild(tabId, command) {
  const args = command?.args || {}
  const targetName = String(args.target_name || '')
  const targetId = String(args.target_id || '')
  const expectedUrlBefore = String(args.expected_url_before || '')
  const expectedUrlAfter = String(args.expected_url_after || '')
  const taskActionId = boundedControlFree(args.task_action_id, 160)
  const authorizationGeneration = boundedControlFree(command?.authorization_attached_at, 128)
  if (!isHttpPage(expectedUrlBefore) || !isHttpPage(expectedUrlAfter)) {
    throw new Error('causal button click requires fresh expected HTTP(S) URLs')
  }
  if (normalizedOrigin(expectedUrlBefore) !== normalizedOrigin(expectedUrlAfter)) {
    throw new Error('causal child URL must remain inside the root origin')
  }

  const beforeTab = await currentTabEvidence(tabId)
  const rootTabBefore = await chrome.tabs.get(tabId)
  if (beforeTab.url !== expectedUrlBefore || Number(rootTabBefore?.id || 0) !== tabId) {
    throw new Error('authorized root changed before causal button click; fresh sensing is required')
  }
  const before = await exactNamedButton(tabId, targetName)
  if (before.targetId !== targetId) {
    throw new Error('authorized button identity changed before causal click; fresh sensing is required')
  }

  await debuggerCommand(tabId, 'Page.enable')
  const rootTargetId = await exactRootDebuggerTarget(tabId)
  const baselineProtocolTargets = await freshProtocolTargets(tabId)
  const baselineTargetIds = new Set(
    baselineProtocolTargets.map(info => String(info?.targetId || '')).filter(Boolean)
  )
  if (!baselineTargetIds.has(rootTargetId)) {
    throw new Error('authorized root target was not present in the fresh pre-click CDP target baseline')
  }

  const watcher = causalPopupWatcher(tabId, expectedUrlAfter)
  let clickSent = false
  let childTabId = 0
  let childDebuggerAttached = false
  let childDebuggerDetached = false
  let finalState = null
  try {
    const resolved = await debuggerCommand(tabId, 'DOM.resolveNode', {
      backendNodeId: before.backendNodeId
    })
    const objectId = String(resolved?.object?.objectId || '')
    if (!objectId) throw new Error('exact accessible button could not be resolved for causal dispatch')

    watcher.openActionWindow()
    clickSent = true
    const dispatched = await debuggerCommand(tabId, 'Runtime.callFunctionOn', {
      objectId,
      functionDeclaration: 'function(){ this.click(); }',
      returnByValue: true,
      awaitPromise: false
    })
    if (dispatched?.exceptionDetails) {
      throw new Error('exact accessible button causal click returned JavaScript exception details')
    }

    const outcome = await waitForCausalChildOrSameTab(
      watcher,
      tabId,
      expectedUrlAfter,
      rootTargetId,
      baselineTargetIds
    )
    finalState = outcome.state
    watcher.closeActionWindow()
    if (outcome.kind === 'same_tab') {
      return {
        tab_id: tabId,
        url_before: beforeTab.url,
        url_after: outcome.root.url,
        target_id: before.targetId,
        click_sent: true,
        exact_node_continuity: true,
        target_revalidated_before_dispatch: true,
        expected_url: expectedUrlAfter,
        task_action_id: taskActionId,
        postcondition: 'url_equals_after_fresh_semantic_button_click'
      }
    }

    childTabId = Number(outcome.child.tabId)
    const childTargetId = String(outcome.child.targetId || '')
    if ((await ownedTabId()) !== tabId) {
      throw new Error('root browser authorization was revoked before child authority could be derived')
    }
    if (!childTargetId || childTabId === tabId) {
      throw new Error('fresh causal child identity is invalid')
    }
    await freshExactCausalTarget(tabId, rootTargetId, childTargetId, childTabId)
    if (finalState.removedTabs.has(childTabId) || finalState.replacedTabs.has(childTabId)) {
      throw new Error('causal child identity was removed or replaced before debugger attach')
    }

    await chrome.debugger.attach({ tabId: childTabId }, '1.3')
    childDebuggerAttached = true
    await activateExactTab(childTabId)
    if ((await ownedTabId()) !== tabId) {
      throw new Error('root authorization was revoked while the causal child was active')
    }
    const childPage = await exactChildPageEvidence(childTabId, expectedUrlAfter)
    if ((await ownedTabId()) !== tabId) {
      throw new Error('root authorization was revoked before returning from the causal child')
    }
    const rootBeforeReturn = await chrome.tabs.get(tabId)
    if (
      Number(rootBeforeReturn?.id || 0) !== tabId ||
      String(rootBeforeReturn?.url || '') !== expectedUrlBefore
    ) {
      throw new Error('exact root tab disappeared or left its Work origin while child was active')
    }
    const rootWindowState = await activateExactTab(tabId)
    const returnedRoot = await currentTabEvidence(tabId)
    if (returnedRoot.url !== expectedUrlBefore || (await ownedTabId()) !== tabId) {
      throw new Error('fresh root re-sense did not preserve exact tab identity and authorization')
    }

    try {
      await chrome.debugger.detach({ tabId: childTabId })
      childDebuggerDetached = true
    } catch (detachError) {
      try {
        await chrome.tabs.get(childTabId)
        throw detachError
      } catch (tabError) {
        if (tabError === detachError) throw detachError
        childDebuggerDetached = true
      }
    }
    childDebuggerAttached = false

    return {
      tab_id: tabId,
      url_before: beforeTab.url,
      url_after: returnedRoot.url,
      target_id: before.targetId,
      click_sent: true,
      exact_node_continuity: true,
      target_revalidated_before_dispatch: true,
      expected_url: expectedUrlAfter,
      task_action_id: taskActionId,
      authorization_generation: authorizationGeneration,
      relationship: 'causal_child',
      child_tab_id: childTabId,
      opener_tab_id: tabId,
      opener_matches_root: true,
      opener_proof: 'fresh_cdp_target_opener_id',
      fresh_child_identity: childTabId !== tabId,
      page_window_open_matches_expected: true,
      causal_candidate_count: finalState.causalTabs.length,
      unrelated_created_count: finalState.unrelatedCreatedCount,
      window_open_event_count: finalState.windowOpenEvents.length,
      child_url: childPage.url,
      child_title: childPage.title,
      child_authority_task_scoped: true,
      child_debugger_detached: childDebuggerDetached,
      root_authorization_preserved: true,
      root_generation_unchanged: true,
      returned_to_exact_root_tab: true,
      fresh_root_resense_after_return: true,
      root_active_after_return: rootWindowState?.active === true,
      root_window_focused_after_return: rootWindowState?.focused === true,
      postcondition: 'causal_child_verified_and_returned_to_exact_root'
    }
  } catch (error) {
    if (!clickSent) throw error
    watcher.closeActionWindow()
    let rootUrl = beforeTab.url
    try {
      if ((await ownedTabId()) === tabId) rootUrl = (await currentTabEvidence(tabId)).url
    } catch {
      // Preserve only the pre-click root URL as uncertainty context.
    }
    return {
      tab_id: tabId,
      url_before: beforeTab.url,
      url_after: rootUrl,
      target_id: before.targetId,
      click_sent: true,
      exact_node_continuity: true,
      target_revalidated_before_dispatch: true,
      expected_url: expectedUrlAfter,
      task_action_id: taskActionId,
      causal_candidate_count: finalState?.causalTabs?.length || 0,
      unrelated_created_count: finalState?.unrelatedCreatedCount || 0,
      window_open_event_count: finalState?.windowOpenEvents?.length || 0,
      postcondition: '',
      verification_error: String(error instanceof Error ? error.message : error).slice(0, 512)
    }
  } finally {
    watcher.stop()
    if (childDebuggerAttached && !childDebuggerDetached) {
      try {
        await chrome.debugger.detach({ tabId: childTabId })
      } catch {
        // Best-effort cleanup after a fail-closed result.
      }
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
        const text = String(anchor.innerText || anchor.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 240);
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

executeResidentCommand = async function (tabId, command) {
  if (
    String(command?.kind || '') === 'probe_current_tab' &&
    command?.args?.discover_reference_context === true
  ) {
    return discoverBoundedReferenceContext(tabId)
  }
  if (
    String(command?.kind || '') === 'click_named_button_to_url' &&
    command?.args?.causal_popup_allowed === true
  ) {
    return clickNamedButtonWithCausalChild(tabId, command)
  }
  return baseExecuteResidentCommand(tabId, command)
}

chrome.tabs.onReplaced.addListener((addedTabId, removedTabId) => {
  void (async () => {
    const currentOwned = await ownedTabId()
    if (currentOwned !== Number(removedTabId || 0)) return
    try {
      await relay('/v1/detach', { tab_id: currentOwned })
    } catch {
      // Local revocation remains authoritative when the Resident is unavailable.
    }
    await forgetOwnedTab()
    try {
      await setAttachedUi(Number(addedTabId || 0), false)
    } catch {
      // The replacement is intentionally not authorized.
    }
  })()
})
