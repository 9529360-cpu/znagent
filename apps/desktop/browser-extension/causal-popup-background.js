importScripts('research-background.js')

// E2E-07 requires causal authority, not a global before/after tab diff.  The
// creation event is used only to bind the exact action window.  Chromium may
// expose a newly-created Tab before every useful field has settled, so final
// opener authority is derived only from a fresh chrome.tabs.get() read while
// the exact root Page.windowOpen corroboration remains mandatory.

function freshCausalPopupWatcher(rootTabId, expectedUrl) {
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
        causalTabs: [],
        unrelatedCreatedCount: 0,
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

async function classifyFreshActionWindowTabs(state, rootTabId) {
  const causalTabs = []
  const unrelatedTabs = []
  const unresolvedTabs = []

  for (const rawId of state.createdTabIds || []) {
    const tabId = Number(rawId || 0)
    if (!Number.isInteger(tabId) || tabId <= 0 || tabId === rootTabId) continue
    if (state.removedTabs.has(tabId) || state.replacedTabs.has(tabId)) {
      unresolvedTabs.push(tabId)
      continue
    }
    let tab
    try {
      tab = await chrome.tabs.get(tabId)
    } catch {
      unresolvedTabs.push(tabId)
      continue
    }
    const openerTabId = Number(tab?.openerTabId || 0)
    if (openerTabId === rootTabId) {
      causalTabs.push({ tabId, openerTabId: rootTabId })
    } else if (openerTabId > 0) {
      unrelatedTabs.push({ tabId, openerTabId })
    } else {
      // Do not classify an early/partial Tab snapshot as unrelated. Keep it
      // unresolved until fresh browser state proves an opener or the action
      // window expires, then fail closed rather than guessing.
      unresolvedTabs.push(tabId)
    }
  }

  return { causalTabs, unrelatedTabs, unresolvedTabs }
}

async function waitForFreshCausalChildOrSameTab(watcher, rootTabId, expectedUrl) {
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
    if (
      state.windowOpenEvents.length === 1 &&
      state.windowOpenEvents[0].matchesExpected !== true
    ) {
      throw new Error('root Page.windowOpen URL did not match the expected child contract')
    }

    lastClassification = await classifyFreshActionWindowTabs(state, rootTabId)
    if (lastClassification.causalTabs.length > 1) {
      throw new Error('multiple freshly proven root-opener child tabs were created by one action; refusing ambiguity')
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
  lastClassification = await classifyFreshActionWindowTabs(state, rootTabId)
  if (state.windowOpenEvents.length === 1 && state.windowOpenEvents[0].matchesExpected !== true) {
    throw new Error('root Page.windowOpen URL did not match the expected child contract')
  }
  if (lastClassification.unresolvedTabs.length > 0) {
    throw new Error(
      'action-window tab creation remained unresolved after fresh opener re-read; refusing causal authority'
    )
  }
  if (lastClassification.causalTabs.length === 1 && state.windowOpenEvents.length === 0) {
    throw new Error(
      'one fresh root-opener child was proven but root Page.windowOpen corroboration was not observed'
    )
  }
  if (lastClassification.causalTabs.length === 0 && state.windowOpenEvents.length === 1) {
    throw new Error(
      'root Page.windowOpen was observed but no freshly re-read root-opener child was proven'
    )
  }
  throw new Error(
    'neither exact same-tab navigation nor one exact root-opener child was proven inside the action window'
  )
}

// research-background.js owns the causal click implementation and all bounded
// child/root handling. Replace only the two action-window primitives so the
// mature path keeps its existing authorization, privacy and return semantics.
causalPopupWatcher = freshCausalPopupWatcher
waitForCausalChildOrSameTab = waitForFreshCausalChildOrSameTab
