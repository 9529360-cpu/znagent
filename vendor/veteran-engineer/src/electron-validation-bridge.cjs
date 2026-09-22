'use strict';

const fs = require('node:fs');
const readline = require('node:readline');
const { app, BrowserWindow, Menu, dialog, nativeImage, webContents } = require('electron');
const { openBoundedFileDialog } = require('./electron-native-dialog.cjs');
const { applicationMenuInventory } = require('./electron-native-menu.cjs');
const { compareVisualSnapshot } = require('./electron-visual-regression.cjs');

const CONTRACT = 'veteran-electron-bridge-v1';
const MAX_SURFACES = 64;
const MAX_MESSAGE_BYTES = 256 * 1024;
const CAPTURE_RETRY_WINDOW_MS = 8_000;
const MAX_CAPTURE_ATTEMPTS = 16;

const input = fs.createReadStream(null, { fd: 3, autoClose: false });
const output = fs.createWriteStream(null, { fd: 4, autoClose: false });
const rl = readline.createInterface({ input, crlfDelay: Infinity });
const trackedWebContents = new WeakSet();
const unresponsiveWebContents = new Set();
const runtimeDiagnostics = {
  consoleMessages: 0,
  pageErrors: 0,
  crashes: 0,
  unresponsiveEvents: 0,
  responsiveEvents: 0,
  activeUnresponsive: 0,
  webContentsObserved: 0
};

function reply(message) {
  try {
    output.write(`${JSON.stringify(message)}\n`);
  } catch {}
}

function boundedText(value, max) {
  return typeof value === 'string' ? value.slice(0, max) : '';
}

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function refreshActiveUnresponsive() {
  runtimeDiagnostics.activeUnresponsive = unresponsiveWebContents.size;
}

function trackWebContents(contents) {
  if (!contents || trackedWebContents.has(contents)) return;
  trackedWebContents.add(contents);
  runtimeDiagnostics.webContentsObserved += 1;

  const forgetUnresponsive = () => {
    if (unresponsiveWebContents.delete(contents)) refreshActiveUnresponsive();
  };

  contents.on('console-message', (_event, detailsOrLevel) => {
    runtimeDiagnostics.consoleMessages += 1;
    const level = detailsOrLevel && typeof detailsOrLevel === 'object'
      ? detailsOrLevel.level
      : detailsOrLevel;
    if (level === 'error' || level === 3) runtimeDiagnostics.pageErrors += 1;
  });
  contents.on('preload-error', () => {
    runtimeDiagnostics.pageErrors += 1;
  });
  contents.on('render-process-gone', (_event, details) => {
    if (String(details?.reason || '') !== 'clean-exit') runtimeDiagnostics.crashes += 1;
    forgetUnresponsive();
  });
  contents.on('unresponsive', () => {
    if (unresponsiveWebContents.has(contents)) return;
    unresponsiveWebContents.add(contents);
    runtimeDiagnostics.unresponsiveEvents += 1;
    refreshActiveUnresponsive();
  });
  contents.on('responsive', () => {
    if (!unresponsiveWebContents.delete(contents)) return;
    runtimeDiagnostics.responsiveEvents += 1;
    refreshActiveUnresponsive();
  });
  contents.once('destroyed', forgetUnresponsive);
}

function observeCurrentWebContents() {
  for (const contents of webContents.getAllWebContents()) trackWebContents(contents);
}

function diagnosticsSnapshot() {
  observeCurrentWebContents();
  refreshActiveUnresponsive();
  return { ...runtimeDiagnostics };
}

app.on('web-contents-created', (_event, contents) => trackWebContents(contents));

function listSurfaceEntries(type) {
  if (type === 'window') {
    return BrowserWindow.getAllWindows()
      .filter((win) => {
        try { return !win.isDestroyed() && win.webContents && !win.webContents.isDestroyed(); } catch { return false; }
      })
      .sort((left, right) => left.webContents.id - right.webContents.id)
      .slice(0, MAX_SURFACES)
      .map((win, index) => {
        const contents = win.webContents;
        trackWebContents(contents);
        return {
          index,
          id: contents.id,
          type: 'window',
          title: boundedText(contents.getTitle(), 240),
          url: boundedText(contents.getURL(), 2000),
          hostId: null,
          contents
        };
      });
  }
  return webContents.getAllWebContents()
    .filter((contents) => {
      try { return !contents.isDestroyed() && contents.getType() === 'webview'; } catch { return false; }
    })
    .sort((left, right) => left.id - right.id)
    .slice(0, MAX_SURFACES)
    .map((contents, index) => {
      trackWebContents(contents);
      return {
        index,
        id: contents.id,
        type: 'webview',
        title: boundedText(contents.getTitle(), 240),
        url: boundedText(contents.getURL(), 2000),
        hostId: contents.hostWebContents?.id || null,
        contents
      };
    });
}

function publicSurface(surface) {
  if (!surface) return null;
  return {
    index: surface.index,
    id: surface.id,
    type: surface.type,
    title: surface.title,
    url: surface.url,
    hostId: surface.hostId
  };
}

function readWindowState(surface) {
  if (!surface || surface.type !== 'window') return { ok: false, code: 'ELECTRON_WINDOW_STATE_TARGET_INVALID' };
  try {
    const owner = BrowserWindow.fromWebContents(surface.contents);
    if (!owner || owner.isDestroyed()) return { ok: false, code: 'ELECTRON_SURFACE_NOT_FOUND' };
    const bounds = owner.getBounds();
    const width = Number.isInteger(bounds?.width) && bounds.width >= 0 ? bounds.width : null;
    const height = Number.isInteger(bounds?.height) && bounds.height >= 0 ? bounds.height : null;
    return {
      ok: true,
      state: {
        visible: Boolean(owner.isVisible()),
        minimized: Boolean(owner.isMinimized()),
        maximized: Boolean(owner.isMaximized()),
        fullScreen: Boolean(owner.isFullScreen()),
        bounds: { width, height }
      }
    };
  } catch {
    return { ok: false, code: 'ELECTRON_WINDOW_STATE_UNAVAILABLE' };
  }
}

function inventory() {
  observeCurrentWebContents();
  return {
    windows: listSurfaceEntries('window').map(publicSurface),
    webviews: listSurfaceEntries('webview').map(publicSurface)
  };
}

function resolveTarget(target) {
  const type = target?.type === 'webview' ? 'webview' : 'window';
  const index = Number.isInteger(target?.index) && target.index >= 0 ? target.index : 0;
  const titleIncludes = typeof target?.titleIncludes === 'string' ? target.titleIncludes : null;
  const urlIncludes = typeof target?.urlIncludes === 'string' ? target.urlIncludes : null;
  const candidates = listSurfaceEntries(type).filter((surface) => {
    if (titleIncludes !== null && !surface.title.includes(titleIncludes)) return false;
    if (urlIncludes !== null && !surface.url.includes(urlIncludes)) return false;
    return true;
  });
  return candidates[index] || null;
}

function focusSurface(surface) {
  try {
    const contents = surface.contents;
    const owner = surface.type === 'window'
      ? BrowserWindow.fromWebContents(contents)
      : BrowserWindow.fromWebContents(contents.hostWebContents || contents);
    if (owner && !owner.isDestroyed()) {
      owner.show();
      owner.focus();
    }
    if (typeof contents.focus === 'function') contents.focus();
  } catch {}
}

function captureFailureCode(error) {
  const message = String(error?.message || error || '').toLowerCase();
  if (message.includes('frame gone')) return 'ELECTRON_CAPTURE_FRAME_GONE';
  if (message.includes('timeout')) return 'ELECTRON_CAPTURE_TIMEOUT';
  if (message.includes('empty bitmap') || message.includes('vizsentemptybitmap')) return 'ELECTRON_CAPTURE_EMPTY_BITMAP';
  if (
    message.includes('display surface') ||
    message.includes('surface not available') ||
    message.includes('embeddingtokenchanged') ||
    message.includes('unknownvizerror') ||
    message.includes('copyfromsurface')
  ) return 'ELECTRON_CAPTURE_SURFACE_UNAVAILABLE';
  return 'ELECTRON_SCREENSHOT_FAILED';
}

function retryableCaptureFailure(code) {
  return code === 'ELECTRON_CAPTURE_SURFACE_UNAVAILABLE'
    || code === 'ELECTRON_CAPTURE_EMPTY_BITMAP'
    || code === 'ELECTRON_CAPTURE_FRAME_GONE';
}

async function captureSurface(surface) {
  const deadline = Date.now() + CAPTURE_RETRY_WINDOW_MS;
  let failureCode = 'ELECTRON_SCREENSHOT_FAILED';
  for (let attempt = 0; attempt < MAX_CAPTURE_ATTEMPTS; attempt += 1) {
    try {
      focusSurface(surface);
      const options = { stayHidden: true, stayAwake: true };
      let image;
      if (surface.type === 'window') {
        const owner = BrowserWindow.fromWebContents(surface.contents);
        if (!owner || owner.isDestroyed()) return { ok: false, code: 'ELECTRON_SURFACE_NOT_FOUND' };
        image = await owner.capturePage(undefined, options);
      } else {
        image = await surface.contents.capturePage(undefined, options);
      }
      const png = image?.toPNG?.();
      if (Buffer.isBuffer(png) && png.length > 0 && !image?.isEmpty?.()) {
        return { ok: true, pngBase64: png.toString('base64') };
      }
      failureCode = 'ELECTRON_CAPTURE_EMPTY_BITMAP';
    } catch (error) {
      failureCode = captureFailureCode(error);
    }

    if (!retryableCaptureFailure(failureCode) || Date.now() >= deadline) break;
    const remaining = deadline - Date.now();
    const retryDelay = Math.min(500, 100 + attempt * 50, remaining);
    if (retryDelay > 0) await delay(retryDelay);
  }
  return { ok: false, code: failureCode };
}

async function runDom(contents, operation, params) {
  const payload = {
    operation,
    selector: typeof params?.selector === 'string' ? params.selector : null
  };
  const source = `(() => {
    const p = ${JSON.stringify(payload)};
    const el = p.selector ? document.querySelector(p.selector) : null;
    const visible = (node) => {
      if (!node) return false;
      const style = getComputedStyle(node);
      const rect = node.getBoundingClientRect();
      return style.display !== 'none' && style.visibility !== 'hidden' && Number(style.opacity || 1) !== 0 && rect.width > 0 && rect.height > 0;
    };
    if (p.operation === 'inspect') {
      if (!el) return { found: false, visible: false, text: null, value: null, rect: null };
      const rect = el.getBoundingClientRect();
      return {
        found: true,
        visible: visible(el),
        text: el.textContent ?? '',
        value: 'value' in el ? String(el.value ?? '') : null,
        rect: { x: rect.x, y: rect.y, width: rect.width, height: rect.height }
      };
    }
    if (p.operation === 'focus-clear') {
      if (!el) return { found: false };
      el.focus();
      if ('value' in el) {
        const proto = Object.getPrototypeOf(el);
        const setter = Object.getOwnPropertyDescriptor(proto, 'value')?.set;
        if (setter) setter.call(el, ''); else el.value = '';
        el.dispatchEvent(new Event('input', { bubbles: true }));
      }
      return { found: true };
    }
    if (p.operation === 'focus') {
      if (!el) return { found: false };
      el.focus();
      return { found: true };
    }
    return { found: false };
  })()`;
  return contents.executeJavaScript(source, true);
}

async function invoke(target, operation, params = {}) {
  const surface = resolveTarget(target);
  if (!surface) return { ok: false, code: 'ELECTRON_SURFACE_NOT_FOUND' };
  const contents = surface.contents;
  if (operation === 'inventory') return { ok: true, surface: publicSurface(surface) };
  if (operation === 'openFileDialog') {
    if (surface.type !== 'window') return { ok: false, code: 'ELECTRON_FILE_DIALOG_TARGET_INVALID' };
    const owner = BrowserWindow.fromWebContents(contents);
    if (!owner || owner.isDestroyed()) return { ok: false, code: 'ELECTRON_FILE_DIALOG_TARGET_INVALID' };
    return openBoundedFileDialog({ dialog, owner, request: params, root: process.cwd() });
  }
  if (operation === 'url') return { ok: true, url: surface.url };
  if (operation === 'inspect') return { ok: true, ...(await runDom(contents, 'inspect', params)) };
  if (operation === 'click') {
    const inspected = await runDom(contents, 'inspect', params);
    if (!inspected.found || !inspected.visible || !inspected.rect) {
      return { ok: false, code: 'ELECTRON_SELECTOR_NOT_INTERACTABLE' };
    }
    focusSurface(surface);
    const x = Math.floor(inspected.rect.x + inspected.rect.width / 2);
    const y = Math.floor(inspected.rect.y + inspected.rect.height / 2);
    contents.sendInputEvent({ type: 'mouseMove', x, y, movementX: 0, movementY: 0 });
    contents.sendInputEvent({ type: 'mouseDown', x, y, button: 'left', clickCount: 1 });
    contents.sendInputEvent({ type: 'mouseUp', x, y, button: 'left', clickCount: 1 });
    return { ok: true };
  }
  if (operation === 'fill') {
    const focused = await runDom(contents, 'focus-clear', params);
    if (!focused.found) return { ok: false, code: 'ELECTRON_SELECTOR_NOT_FOUND' };
    focusSurface(surface);
    await contents.insertText(String(params?.value ?? ''));
    return { ok: true };
  }
  if (operation === 'press') {
    if (params?.selector) {
      const focused = await runDom(contents, 'focus', params);
      if (!focused.found) return { ok: false, code: 'ELECTRON_SELECTOR_NOT_FOUND' };
    }
    focusSurface(surface);
    const pieces = String(params?.key || '').split('+').filter(Boolean);
    const keyCode = pieces.pop() || '';
    const modifiers = pieces.map((part) => ({
      Control: 'control', Ctrl: 'control', Shift: 'shift', Alt: 'alt', Meta: 'meta', Command: 'meta'
    }[part] || part.toLowerCase()));
    contents.sendInputEvent({ type: 'keyDown', keyCode, modifiers });
    contents.sendInputEvent({ type: 'keyUp', keyCode, modifiers });
    return { ok: true };
  }
  if (operation === 'screenshot') return captureSurface(surface);
  if (operation === 'visualCompare') {
    const captured = await captureSurface(surface);
    if (!captured.ok) return captured;
    return compareVisualSnapshot({
      nativeImage,
      currentPng: Buffer.from(captured.pngBase64, 'base64'),
      request: params,
      root: process.cwd()
    });
  }
  return { ok: false, code: 'ELECTRON_OPERATION_INVALID' };
}

let chain = Promise.resolve();
rl.on('line', (line) => {
  if (!line || Buffer.byteLength(line) > MAX_MESSAGE_BYTES) return;
  let message;
  try { message = JSON.parse(line); } catch { return; }
  if (!Number.isInteger(message?.id) || message.id <= 0) return;

  try {
    if (message.operation === 'inventory') {
      reply({ id: message.id, ok: true, inventory: inventory() });
      return;
    }
    if (message.operation === 'diagnostics') {
      reply({ id: message.id, ok: true, diagnostics: diagnosticsSnapshot() });
      return;
    }
    if (message.operation === 'windowState') {
      const surface = resolveTarget(message.target);
      reply({ id: message.id, ...(surface ? readWindowState(surface) : { ok: false, code: 'ELECTRON_SURFACE_NOT_FOUND' }) });
      return;
    }
    if (message.operation === 'menuInventory') {
      if (!app.isReady()) {
        reply({ id: message.id, ok: false, code: 'ELECTRON_APP_NOT_READY' });
        return;
      }
      reply({ id: message.id, ok: true, menu: applicationMenuInventory(Menu.getApplicationMenu()) });
      return;
    }
    if (message.operation === 'quit') {
      reply({ id: message.id, ok: true });
      setImmediate(() => app.quit());
      return;
    }
  } catch (error) {
    reply({ id: message.id, ok: false, code: error?.code || 'ELECTRON_BRIDGE_OPERATION_FAILED' });
    return;
  }

  chain = chain.then(async () => {
    try {
      const result = await invoke(message.target, message.operation, message.params || {});
      reply({ id: message.id, ...result });
    } catch (error) {
      reply({ id: message.id, ok: false, code: error?.code || 'ELECTRON_BRIDGE_OPERATION_FAILED' });
    }
  }).catch(() => {});
});

input.on('error', () => {});
output.on('error', () => {});
reply({ type: 'ready', contract: CONTRACT });
