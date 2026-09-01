importScripts('background.js')

const baseExecuteResidentCommand = executeResidentCommand

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

executeResidentCommand = async function (tabId, command) {
  if (
    String(command?.kind || '') === 'probe_current_tab' &&
    command?.args?.discover_reference_context === true
  ) {
    return discoverBoundedReferenceContext(tabId)
  }
  return baseExecuteResidentCommand(tabId, command)
}
