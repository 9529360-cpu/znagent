import fs from 'node:fs/promises';
import {
  ELECTRON_SCENARIO_CONTRACT,
  ELECTRON_VALIDATION_CONTRACT,
  MAX_SCREENSHOT_BYTES,
  MAX_SCREENSHOT_TOTAL_BYTES,
  MAX_SURFACES,
  electronError,
  normalizeElectronScenario,
  normalizeElectronValidation,
  prepareElectronValidation,
  sanitizeElectronUrl
} from './electron-validation-contract.mjs';
import { nativeElectronAutomation } from './electron-validation-driver.mjs';

export {
  ELECTRON_SCENARIO_CONTRACT,
  ELECTRON_VALIDATION_CONTRACT,
  normalizeElectronScenario,
  normalizeElectronValidation
} from './electron-validation-contract.mjs';

const MAX_DIAGNOSTIC_COUNT = 1_000_000;
const SURFACE_PROBE_TIMEOUT_MS = 750;

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function matches(value, expected, mode) {
  return mode === 'equals' ? value === expected : value.includes(expected);
}

function windowStateMatches(observed, expected) {
  if (!observed || typeof observed !== 'object' || Array.isArray(observed)) return false;
  for (const key of ['visible', 'minimized', 'maximized', 'fullScreen']) {
    if (Object.hasOwn(expected, key) && observed[key] !== expected[key]) return false;
  }
  if (expected.bounds) {
    if (!observed.bounds || typeof observed.bounds !== 'object' || Array.isArray(observed.bounds)) return false;
    for (const key of ['width', 'height']) {
      if (Object.hasOwn(expected.bounds, key) && observed.bounds[key] !== expected.bounds[key]) return false;
    }
  }
  return true;
}

function menuItemMatches(observed, expected) {
  if (!observed || typeof observed !== 'object' || Array.isArray(observed)) return false;
  for (const [key, value] of Object.entries(expected)) {
    if (observed[key] !== value) return false;
  }
  return true;
}

function findMenuItem(menu, expected) {
  if (!menu || typeof menu !== 'object' || !Array.isArray(menu.items)) return null;
  return menu.items.find((item) => menuItemMatches(item, expected)) || null;
}

function remainingBudget(deadline, requested) {
  const remaining = deadline - Date.now();
  if (remaining <= 0) throw electronError('Electron validation exceeded its total timeout', 'ELECTRON_VALIDATION_TIMEOUT');
  return Math.max(1, Math.min(requested, remaining));
}

function sanitizeSurfaces(raw) {
  const clean = (items, type) => (Array.isArray(items) ? items : []).slice(0, MAX_SURFACES).map((item, index) => ({
    index: Number.isInteger(item?.index) ? item.index : index,
    id: Number.isInteger(item?.id) ? item.id : null,
    type,
    title: String(item?.title || '').slice(0, 240),
    url: sanitizeElectronUrl(item?.url || ''),
    hostId: Number.isInteger(item?.hostId) ? item.hostId : null
  }));
  return { windows: clean(raw?.windows, 'window'), webviews: clean(raw?.webviews, 'webview') };
}

function boundedDiagnosticCount(value) {
  const numeric = Number(value);
  return Number.isInteger(numeric) && numeric >= 0 ? Math.min(numeric, MAX_DIAGNOSTIC_COUNT) : 0;
}

function sanitizeRuntimeDiagnostics(raw) {
  return {
    consoleMessages: boundedDiagnosticCount(raw?.consoleMessages),
    pageErrors: boundedDiagnosticCount(raw?.pageErrors),
    crashes: boundedDiagnosticCount(raw?.crashes),
    unresponsiveEvents: boundedDiagnosticCount(raw?.unresponsiveEvents),
    responsiveEvents: boundedDiagnosticCount(raw?.responsiveEvents),
    activeUnresponsive: boundedDiagnosticCount(raw?.activeUnresponsive),
    webContentsObserved: boundedDiagnosticCount(raw?.webContentsObserved)
  };
}

async function readRuntimeDiagnostics(session, timeoutMs) {
  if (!session || typeof session.command !== 'function') return null;
  try {
    const response = await session.command(null, 'diagnostics', {}, timeoutMs);
    if (!response?.ok) return null;
    return sanitizeRuntimeDiagnostics(response.diagnostics);
  } catch {
    return null;
  }
}

function targetMatches(surface, target) {
  if (target.titleIncludes !== undefined && !String(surface.title || '').includes(target.titleIncludes)) return false;
  if (target.urlIncludes !== undefined && !String(surface.url || '').includes(target.urlIncludes)) return false;
  return true;
}

function selectTarget(surfaces, target) {
  const list = target.type === 'webview' ? surfaces.webviews : surfaces.windows;
  return list.filter((surface) => targetMatches(surface, target))[target.index] || null;
}

function matchingSurfaceCount(surfaces, target) {
  const list = target.type === 'webview' ? surfaces?.webviews : surfaces?.windows;
  return (Array.isArray(list) ? list : []).filter((surface) => targetMatches(surface, target)).length;
}

function retryableSurfaceProbeError(error) {
  return error?.code === 'ELECTRON_BRIDGE_TIMEOUT';
}

function surfaceProbeTimeout(deadline) {
  return Math.max(1, Math.min(SURFACE_PROBE_TIMEOUT_MS, deadline - Date.now()));
}

async function waitForSurface(session, target, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  let sawInventory = false;
  let lastProbeTimeout = null;
  for (;;) {
    try {
      const surfaces = await session.listSurfaces(surfaceProbeTimeout(deadline));
      sawInventory = true;
      const selected = selectTarget(surfaces, target);
      if (selected) return selected;
    } catch (error) {
      if (!retryableSurfaceProbeError(error)) throw error;
      lastProbeTimeout = error;
    }
    if (Date.now() >= deadline) {
      if (!sawInventory && lastProbeTimeout) throw lastProbeTimeout;
      throw electronError('Electron target surface was not found before timeout', 'ELECTRON_SURFACE_NOT_FOUND', { target });
    }
    await delay(Math.min(50, Math.max(1, deadline - Date.now())));
  }
}

async function waitForSurfaceCount(session, target, expected, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  let observed = 0;
  let sawInventory = false;
  let lastProbeTimeout = null;
  for (;;) {
    try {
      const surfaces = await session.listSurfaces(surfaceProbeTimeout(deadline));
      sawInventory = true;
      observed = matchingSurfaceCount(surfaces, target);
      if (observed === expected) return observed;
    } catch (error) {
      if (!retryableSurfaceProbeError(error)) throw error;
      lastProbeTimeout = error;
    }
    if (Date.now() >= deadline) {
      if (!sawInventory && lastProbeTimeout) throw lastProbeTimeout;
      return observed;
    }
    await delay(Math.min(50, Math.max(1, deadline - Date.now())));
  }
}

async function commandUntil(session, step, operation, params, predicate) {
  const deadline = Date.now() + step.timeoutMs;
  let result = null;
  for (;;) {
    const requestTimeout = Math.max(1, Math.min(1000, deadline - Date.now()));
    result = await session.command(step.target, operation, params, requestTimeout);
    if (predicate(result)) return result;
    if (Date.now() >= deadline) return result || { ok: false };
    await delay(Math.min(50, Math.max(1, deadline - Date.now())));
  }
}

async function visualCompareOnce(session, step) {
  const deadline = Date.now() + step.timeoutMs;
  await waitForSurface(session, step.target, Math.max(1, deadline - Date.now()));
  return session.command(
    step.target,
    'visualCompare',
    step.visual,
    Math.max(1, deadline - Date.now())
  );
}

function pushScreenshotAttachment(attachments, attachment) {
  const content = Buffer.from(attachment.content);
  if (content.length > MAX_SCREENSHOT_BYTES) {
    throw electronError(`Electron screenshot exceeds ${MAX_SCREENSHOT_BYTES} bytes`, 'ELECTRON_SCREENSHOT_LIMIT_EXCEEDED');
  }
  const total = attachments.reduce((sum, item) => sum + Buffer.byteLength(item.content), 0) + content.length;
  if (total > MAX_SCREENSHOT_TOTAL_BYTES) {
    throw electronError(`Electron screenshots exceed ${MAX_SCREENSHOT_TOTAL_BYTES} total bytes`, 'ELECTRON_SCREENSHOT_LIMIT_EXCEEDED');
  }
  attachments.push({ ...attachment, content });
}

function assertionName(step, index) {
  return step.name || `${step.action} step ${index + 1}`;
}

function assertionDetail(value) {
  if (value === undefined || value === null) return '';
  return String(value).slice(0, 1200);
}

function visualAssertionDetail(value) {
  const dimension = (item) => Number.isInteger(item?.width) && Number.isInteger(item?.height)
    ? `${item.width}x${item.height}`
    : 'unknown';
  const diffPixels = Number.isInteger(value?.diffPixels) ? value.diffPixels : 'n/a';
  const totalPixels = Number.isInteger(value?.totalPixels) ? value.totalPixels : 'n/a';
  const diffRatio = Number.isFinite(value?.diffRatio) ? value.diffRatio : 'n/a';
  return assertionDetail(
    `reason=${String(value?.reason || 'unknown')} diffPixels=${diffPixels} totalPixels=${totalPixels} diffRatio=${diffRatio} baseline=${dimension(value?.baseline)} current=${dimension(value?.current)} maxDiffPixels=${value?.maxDiffPixels ?? 'n/a'} channelThreshold=${value?.channelThreshold ?? 'n/a'}`
  );
}

async function executeStep(session, step, stepIndex, assertions, attachments) {
  if (step.action === 'waitForSurface') {
    await waitForSurface(session, step.target, step.timeoutMs);
    return;
  }

  if (step.action === 'assertSurfaceCount') {
    const observed = await waitForSurfaceCount(session, step.target, step.count, step.timeoutMs);
    const passed = observed === step.count;
    assertions.push({
      name: assertionName(step, stepIndex),
      passed,
      detail: `expected=${step.count} observed=${observed}`
    });
    if (!passed) throw electronError(`Electron assertion failed: ${assertionName(step, stepIndex)}`, 'ELECTRON_ASSERTION_FAILED', { stepIndex });
    return;
  }

  if (step.action === 'assertWindowState') {
    const value = await commandUntil(session, step, 'windowState', {}, (item) => item?.ok && windowStateMatches(item.state, step.state));
    const passed = Boolean(value?.ok && windowStateMatches(value.state, step.state));
    const detail = assertionDetail(`expected=${JSON.stringify(step.state)} observed=${JSON.stringify(value?.state ?? null)}`);
    assertions.push({ name: assertionName(step, stepIndex), passed, detail });
    if (!passed) throw electronError(`Electron assertion failed: ${assertionName(step, stepIndex)}`, 'ELECTRON_ASSERTION_FAILED', { stepIndex });
    return;
  }

  if (step.action === 'assertMenuItem') {
    const value = await commandUntil(session, step, 'menuInventory', {}, (item) => item?.ok && Boolean(findMenuItem(item.menu, step.item)));
    const matched = value?.ok ? findMenuItem(value.menu, step.item) : null;
    const passed = Boolean(matched);
    const truncated = Boolean(value?.menu?.truncated);
    const detail = assertionDetail(`expected=${JSON.stringify(step.item)} matched=${passed} truncated=${truncated}`);
    assertions.push({ name: assertionName(step, stepIndex), passed, detail });
    if (!passed && truncated) throw electronError('Electron menu inventory was truncated before the asserted item could be proven absent', 'ELECTRON_MENU_INVENTORY_TRUNCATED', { stepIndex });
    if (!passed) throw electronError(`Electron assertion failed: ${assertionName(step, stepIndex)}`, 'ELECTRON_ASSERTION_FAILED', { stepIndex });
    return;
  }

  if (step.action === 'assertVisual') {
    const value = await visualCompareOnce(session, step);
    if (!value?.ok) throw electronError('Electron visual comparison failed', value?.code || 'ELECTRON_VISUAL_COMPARISON_FAILED', { stepIndex });
    const passed = value.passed === true;
    const detail = visualAssertionDetail(value);
    assertions.push({ name: assertionName(step, stepIndex), passed, detail });
    if (!passed) throw electronError(`Electron assertion failed: ${assertionName(step, stepIndex)}`, 'ELECTRON_ASSERTION_FAILED', { stepIndex });
    return;
  }

  if (step.action === 'click' || step.action === 'fill' || step.action === 'press') {
    const result = await commandUntil(session, step, step.action, {
      selector: step.selector || null,
      value: step.value,
      key: step.key
    }, (item) => item?.ok);
    if (!result?.ok) throw electronError(`Electron ${step.action} failed`, result?.code || 'ELECTRON_ACTION_FAILED', { stepIndex });
    return;
  }

  if (step.action === 'screenshot') {
    const result = await session.command(step.target, 'screenshot', {}, step.timeoutMs);
    if (!result?.ok || !result.pngBase64) throw electronError('Electron screenshot failed', result?.code || 'ELECTRON_SCREENSHOT_FAILED', { stepIndex });
    pushScreenshotAttachment(attachments, {
      name: `electron/${step.filename}`,
      kind: step.target.type === 'webview' ? 'electron-webview-screenshot' : 'electron-screenshot',
      content: Buffer.from(result.pngBase64, 'base64')
    });
    return;
  }

  let value = null;
  if (step.action === 'assertVisible') {
    value = await commandUntil(session, step, 'inspect', { selector: step.selector }, (item) => item?.ok && item.found && item.visible);
  } else if (step.action === 'assertText') {
    value = await commandUntil(session, step, 'inspect', { selector: step.selector }, (item) => item?.ok && item.found && matches(String(item.text ?? ''), step.text, step.match));
  } else if (step.action === 'assertValue') {
    value = await commandUntil(session, step, 'inspect', { selector: step.selector }, (item) => item?.ok && item.found && String(item.value ?? '') === step.value);
  } else if (step.action === 'assertUrl') {
    value = await commandUntil(session, step, 'url', {}, (item) => item?.ok && matches(String(item.url || ''), step.url, step.match));
  }

  let passed = false;
  let detail = '';
  if (step.action === 'assertVisible') passed = Boolean(value?.found && value?.visible);
  if (step.action === 'assertText') {
    passed = Boolean(value?.found && matches(String(value.text ?? ''), step.text, step.match));
    detail = assertionDetail(value?.text);
  }
  if (step.action === 'assertValue') {
    passed = Boolean(value?.found && String(value.value ?? '') === step.value);
    detail = assertionDetail(value?.value);
  }
  if (step.action === 'assertUrl') {
    passed = matches(String(value?.url || ''), step.url, step.match);
    detail = assertionDetail(sanitizeElectronUrl(value?.url || ''));
  }
  assertions.push({ name: assertionName(step, stepIndex), passed, ...(detail ? { detail } : {}) });
  if (!passed) throw electronError(`Electron assertion failed: ${assertionName(step, stepIndex)}`, 'ELECTRON_ASSERTION_FAILED', { stepIndex });
}

async function captureFailure(session, step, stepIndex, attachments, timeoutMs) {
  try {
    await waitForSurface(session, step.target, Math.min(1000, timeoutMs));
    const result = await session.command(step.target, 'screenshot', {}, Math.min(1000, timeoutMs));
    if (!result?.ok || !result.pngBase64) return;
    pushScreenshotAttachment(attachments, {
      name: `electron/failure-step-${String(stepIndex + 1).padStart(3, '0')}.png`,
      kind: step.target.type === 'webview' ? 'electron-webview-failure-screenshot' : 'electron-failure-screenshot',
      content: Buffer.from(result.pngBase64, 'base64')
    });
  } catch {}
}

export async function runElectronValidation(electron, {
  cwd,
  environment = process.env,
  automation = null
} = {}) {
  const startedAt = Date.now();
  const deadline = startedAt + electron.timeoutMs;
  const prepared = await prepareElectronValidation(electron, cwd, environment);
  const driver = automation || nativeElectronAutomation();
  const assertions = [];
  const attachments = [];
  const diagnostics = {
    consoleMessages: 0,
    pageErrors: 0,
    crashes: 0,
    unresponsiveEvents: 0,
    responsiveEvents: 0,
    activeUnresponsive: 0,
    webContentsObserved: 0,
    windowsObserved: 0,
    webviewsObserved: 0,
    stepsCompleted: 0,
    durationMs: 0
  };
  let session = null;
  let failureCode = null;
  let failureMessage = null;
  let failureStep = null;
  let finalSurfaces = { windows: [], webviews: [] };
  try {
    session = await driver.launch({
      executablePath: prepared.executablePath,
      args: [...electron.args],
      cwd,
      env: prepared.env,
      timeout: remainingBudget(deadline, electron.timeoutMs),
      chromiumSandbox: electron.chromiumSandbox
    });

    for (let index = 0; index < prepared.scenario.steps.length; index += 1) {
      const step = prepared.scenario.steps[index];
      const boundedStep = Object.freeze({ ...step, timeoutMs: remainingBudget(deadline, step.timeoutMs) });
      try {
        await executeStep(session, boundedStep, index, assertions, attachments);
        diagnostics.stepsCompleted = index + 1;
      } catch (error) {
        failureCode = error?.code || 'ELECTRON_STEP_FAILED';
        failureMessage = String(error?.message || error).slice(0, 1000);
        failureStep = index;
        await captureFailure(session, step, index, attachments, Math.max(1, deadline - Date.now()));
        break;
      }
    }

    try { finalSurfaces = sanitizeSurfaces(await session.listSurfaces(Math.min(1000, Math.max(1, deadline - Date.now())))); } catch {}
    diagnostics.windowsObserved = finalSurfaces.windows.length;
    diagnostics.webviewsObserved = finalSurfaces.webviews.length;

    const runtimeDiagnostics = await readRuntimeDiagnostics(session, Math.min(1000, Math.max(1, deadline - Date.now())));
    if (runtimeDiagnostics) Object.assign(diagnostics, runtimeDiagnostics);
    if (diagnostics.crashes > 0) {
      const priorFailure = failureCode;
      failureCode = 'ELECTRON_RENDERER_CRASHED';
      failureMessage = `Electron observed ${diagnostics.crashes} renderer crash event(s)${priorFailure ? `; prior step failure was ${priorFailure}` : ''}.`;
    } else if (!failureCode && diagnostics.activeUnresponsive > 0) {
      failureCode = 'ELECTRON_RENDERER_UNRESPONSIVE';
      failureMessage = `Electron ended validation with ${diagnostics.activeUnresponsive} unresponsive renderer surface(s).`;
    }

    if (!failureCode && attachments.length === 0 && finalSurfaces.windows.length > 0) {
      try {
        const result = await session.command({ type: 'window', index: 0 }, 'screenshot', {}, Math.min(1000, Math.max(1, deadline - Date.now())));
        if (result?.ok && result.pngBase64) {
          pushScreenshotAttachment(attachments, { name: 'electron/final.png', kind: 'electron-screenshot', content: Buffer.from(result.pngBase64, 'base64') });
        }
      } catch {}
    }
  } catch (error) {
    failureCode = error?.code || 'ELECTRON_VALIDATION_FAILED';
    failureMessage = String(error?.message || error).slice(0, 1000);
  } finally {
    if (session) await session.close().catch(() => {});
    await fs.rm(prepared.home, { recursive: true, force: true }).catch(() => {});
    diagnostics.durationMs = Date.now() - startedAt;
  }

  const passed = !failureCode && assertions.every((item) => item.passed);
  return {
    contract: ELECTRON_VALIDATION_CONTRACT,
    passed,
    failureCode: passed ? null : (failureCode || 'ELECTRON_ASSERTION_FAILED'),
    summary: passed
      ? `Electron scenario passed ${assertions.length} assertion(s) across ${diagnostics.stepsCompleted} step(s).`
      : `Electron scenario failed${failureStep === null ? '' : ` at step ${failureStep + 1}`}: ${failureMessage || failureCode || 'unknown failure'}`,
    assertions,
    surfaces: finalSurfaces,
    diagnostics,
    attachments
  };
}
