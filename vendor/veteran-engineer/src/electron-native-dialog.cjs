'use strict';

const fs = require('node:fs/promises');
const path = require('node:path');

const MAX_DIALOG_SELECTIONS = 16;
const MAX_DIALOG_FILTERS = 8;
const MAX_DIALOG_FILTER_EXTENSIONS = 16;
const MAX_DIALOG_PATH_LENGTH = 1000;

function nativeDialogError(message, code) {
  const error = new Error(message);
  error.code = code;
  return error;
}

function boundedLabel(value, label, max) {
  if (value === undefined) return null;
  if (typeof value !== 'string' || value.length === 0 || value.length > max || value.includes('\u0000')) {
    throw nativeDialogError(`${label} must be a non-empty bounded string`, 'ELECTRON_FILE_DIALOG_REQUEST_INVALID');
  }
  return value;
}

function relativeDialogPath(value) {
  if (value === undefined) return null;
  if (typeof value !== 'string' || value.length === 0 || value.length > MAX_DIALOG_PATH_LENGTH || value.includes('\u0000')) {
    throw nativeDialogError('Electron file dialog defaultPath must be a bounded relative path', 'ELECTRON_FILE_DIALOG_PATH_ESCAPE');
  }
  const raw = value.replaceAll('\\', '/');
  if (raw.startsWith('/') || raw.startsWith('//') || /^[A-Za-z]:/.test(raw)) {
    throw nativeDialogError('Electron file dialog defaultPath must remain inside the project root', 'ELECTRON_FILE_DIALOG_PATH_ESCAPE');
  }
  const normalized = path.posix.normalize(raw.replace(/^\.\//, ''));
  if (!normalized || normalized === '..' || normalized.startsWith('../') || normalized.startsWith('/')) {
    throw nativeDialogError('Electron file dialog defaultPath must remain inside the project root', 'ELECTRON_FILE_DIALOG_PATH_ESCAPE');
  }
  return normalized;
}

function normalizeFilters(raw) {
  if (raw === undefined) return [];
  if (!Array.isArray(raw) || raw.length > MAX_DIALOG_FILTERS) {
    throw nativeDialogError(`Electron file dialog filters must contain at most ${MAX_DIALOG_FILTERS} entries`, 'ELECTRON_FILE_DIALOG_REQUEST_INVALID');
  }
  return raw.map((filter) => {
    if (!filter || typeof filter !== 'object' || Array.isArray(filter)) {
      throw nativeDialogError('Electron file dialog filter must be an object', 'ELECTRON_FILE_DIALOG_REQUEST_INVALID');
    }
    const keys = Object.keys(filter);
    if (keys.some((key) => key !== 'name' && key !== 'extensions')) {
      throw nativeDialogError('Electron file dialog filter contains an unsupported field', 'ELECTRON_FILE_DIALOG_REQUEST_INVALID');
    }
    const name = boundedLabel(filter.name ?? '', 'Electron file dialog filter name', 80);
    if (!Array.isArray(filter.extensions) || filter.extensions.length === 0 || filter.extensions.length > MAX_DIALOG_FILTER_EXTENSIONS) {
      throw nativeDialogError(`Electron file dialog filter extensions must contain 1-${MAX_DIALOG_FILTER_EXTENSIONS} values`, 'ELECTRON_FILE_DIALOG_REQUEST_INVALID');
    }
    const extensions = filter.extensions.map((extension) => {
      if (typeof extension !== 'string' || (extension !== '*' && !/^[A-Za-z0-9][A-Za-z0-9_+-]{0,15}$/.test(extension))) {
        throw nativeDialogError('Electron file dialog filter extension is invalid', 'ELECTRON_FILE_DIALOG_REQUEST_INVALID');
      }
      return extension;
    });
    if (extensions.includes('*') && extensions.length !== 1) {
      throw nativeDialogError('Electron file dialog wildcard filter may not be combined with other extensions', 'ELECTRON_FILE_DIALOG_REQUEST_INVALID');
    }
    return Object.freeze({ name, extensions: Object.freeze(extensions) });
  });
}

function normalizeOpenDialogRequest(raw = {}) {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) {
    throw nativeDialogError('Electron file dialog request must be an object', 'ELECTRON_FILE_DIALOG_REQUEST_INVALID');
  }
  const supported = new Set(['selection', 'multiple', 'title', 'buttonLabel', 'defaultPath', 'filters']);
  if (Object.keys(raw).some((key) => !supported.has(key))) {
    throw nativeDialogError('Electron file dialog request contains an unsupported field', 'ELECTRON_FILE_DIALOG_REQUEST_INVALID');
  }
  const selection = raw.selection === undefined ? 'file' : String(raw.selection);
  if (selection !== 'file' && selection !== 'directory') {
    throw nativeDialogError('Electron file dialog selection must be file or directory', 'ELECTRON_FILE_DIALOG_REQUEST_INVALID');
  }
  if (raw.multiple !== undefined && typeof raw.multiple !== 'boolean') {
    throw nativeDialogError('Electron file dialog multiple must be boolean', 'ELECTRON_FILE_DIALOG_REQUEST_INVALID');
  }
  const multiple = raw.multiple === true;
  const title = boundedLabel(raw.title, 'Electron file dialog title', 160);
  const buttonLabel = boundedLabel(raw.buttonLabel, 'Electron file dialog buttonLabel', 80);
  const defaultPath = relativeDialogPath(raw.defaultPath);
  const filters = normalizeFilters(raw.filters);
  if (selection === 'directory' && filters.length > 0) {
    throw nativeDialogError('Electron directory dialog may not declare file filters', 'ELECTRON_FILE_DIALOG_REQUEST_INVALID');
  }
  return Object.freeze({
    selection,
    multiple,
    ...(title === null ? {} : { title }),
    ...(buttonLabel === null ? {} : { buttonLabel }),
    ...(defaultPath === null ? {} : { defaultPath }),
    filters: Object.freeze(filters)
  });
}

function insideRoot(root, candidate) {
  const relative = path.relative(root, candidate);
  return relative === '' || (!relative.startsWith('..') && !path.isAbsolute(relative));
}

async function realProjectRoot(root, fsPromises) {
  if (typeof root !== 'string' || !root) throw nativeDialogError('Electron file dialog project root is invalid', 'ELECTRON_FILE_DIALOG_ROOT_INVALID');
  const resolved = await fsPromises.realpath(root).catch(() => null);
  if (!resolved) throw nativeDialogError('Electron file dialog project root is unavailable', 'ELECTRON_FILE_DIALOG_ROOT_INVALID');
  const info = await fsPromises.stat(resolved).catch(() => null);
  if (!info?.isDirectory?.()) throw nativeDialogError('Electron file dialog project root must be a directory', 'ELECTRON_FILE_DIALOG_ROOT_INVALID');
  return resolved;
}

async function resolveDefaultPath(root, relativePath, fsPromises) {
  if (!relativePath) return root;
  const candidate = path.resolve(root, ...relativePath.split('/'));
  if (!insideRoot(root, candidate)) throw nativeDialogError('Electron file dialog defaultPath escapes the project root', 'ELECTRON_FILE_DIALOG_PATH_ESCAPE');
  const resolved = await fsPromises.realpath(candidate).catch(() => null);
  if (!resolved || !insideRoot(root, resolved)) {
    throw nativeDialogError('Electron file dialog defaultPath is unavailable inside the project root', 'ELECTRON_FILE_DIALOG_DEFAULT_PATH_INVALID');
  }
  return resolved;
}

async function normalizeSelections(root, request, result, fsPromises) {
  if (!result || typeof result !== 'object' || Array.isArray(result) || typeof result.canceled !== 'boolean') {
    throw nativeDialogError('Electron file dialog returned an invalid result', 'ELECTRON_FILE_DIALOG_RESULT_INVALID');
  }
  if (result.canceled) return Object.freeze({ canceled: true, paths: Object.freeze([]) });
  if (!Array.isArray(result.filePaths) || result.filePaths.length === 0 || result.filePaths.length > MAX_DIALOG_SELECTIONS) {
    throw nativeDialogError('Electron file dialog returned an invalid selection count', 'ELECTRON_FILE_DIALOG_SELECTION_LIMIT_EXCEEDED');
  }
  if (!request.multiple && result.filePaths.length !== 1) {
    throw nativeDialogError('Electron file dialog returned multiple paths for a single-selection request', 'ELECTRON_FILE_DIALOG_SELECTION_LIMIT_EXCEEDED');
  }
  const output = [];
  const seen = new Set();
  for (const selected of result.filePaths) {
    if (typeof selected !== 'string' || !selected || selected.includes('\u0000')) {
      throw nativeDialogError('Electron file dialog returned an invalid path', 'ELECTRON_FILE_DIALOG_SELECTION_INVALID');
    }
    const resolved = await fsPromises.realpath(selected).catch(() => null);
    if (!resolved) throw nativeDialogError('Electron file dialog selection is unavailable', 'ELECTRON_FILE_DIALOG_SELECTION_INVALID');
    if (!insideRoot(root, resolved)) {
      throw nativeDialogError('Electron file dialog selection is outside the project root', 'ELECTRON_FILE_DIALOG_SELECTION_OUTSIDE_ROOT');
    }
    const info = await fsPromises.stat(resolved).catch(() => null);
    const validType = request.selection === 'file' ? info?.isFile?.() : info?.isDirectory?.();
    if (!validType) throw nativeDialogError('Electron file dialog selection has the wrong type', 'ELECTRON_FILE_DIALOG_SELECTION_INVALID');
    if (seen.has(resolved)) continue;
    seen.add(resolved);
    const relative = path.relative(root, resolved).split(path.sep).join('/') || '.';
    output.push(relative);
  }
  if (output.length === 0) throw nativeDialogError('Electron file dialog returned no distinct selections', 'ELECTRON_FILE_DIALOG_SELECTION_INVALID');
  return Object.freeze({ canceled: false, paths: Object.freeze(output) });
}

async function openBoundedFileDialog({ dialog, owner, request, root, fsPromises = fs } = {}) {
  if (!dialog || typeof dialog.showOpenDialog !== 'function') {
    throw nativeDialogError('Electron native file dialog is unavailable', 'ELECTRON_FILE_DIALOG_UNAVAILABLE');
  }
  if (!owner || typeof owner !== 'object' || (typeof owner.isDestroyed === 'function' && owner.isDestroyed())) {
    throw nativeDialogError('Electron file dialog requires a live app-owned window', 'ELECTRON_FILE_DIALOG_TARGET_INVALID');
  }
  const normalized = normalizeOpenDialogRequest(request);
  const projectRoot = await realProjectRoot(root, fsPromises);
  const defaultPath = await resolveDefaultPath(projectRoot, normalized.defaultPath, fsPromises);
  const properties = [normalized.selection === 'file' ? 'openFile' : 'openDirectory'];
  if (normalized.multiple) properties.push('multiSelections');
  const options = {
    defaultPath,
    properties,
    ...(normalized.title ? { title: normalized.title } : {}),
    ...(normalized.buttonLabel ? { buttonLabel: normalized.buttonLabel } : {}),
    ...(normalized.filters.length > 0 ? { filters: normalized.filters.map((filter) => ({ name: filter.name, extensions: [...filter.extensions] })) } : {})
  };
  const result = await dialog.showOpenDialog(owner, options);
  const selected = await normalizeSelections(projectRoot, normalized, result, fsPromises);
  return Object.freeze({ ok: true, ...selected });
}

module.exports = {
  MAX_DIALOG_SELECTIONS,
  MAX_DIALOG_FILTERS,
  MAX_DIALOG_FILTER_EXTENSIONS,
  normalizeOpenDialogRequest,
  openBoundedFileDialog
};
