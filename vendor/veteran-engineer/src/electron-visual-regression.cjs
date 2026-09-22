'use strict';

const crypto = require('node:crypto');
const fs = require('node:fs/promises');
const path = require('node:path');

const MAX_VISUAL_BASELINE_BYTES = 16 * 1024 * 1024;
const MAX_VISUAL_PIXELS = 50_000_000;
const MAX_VISUAL_PATH_LENGTH = 1000;
const PNG_SIGNATURE = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);

function visualError(message, code) {
  const error = new Error(message);
  error.code = code;
  return error;
}

function boundedRelativePng(value) {
  if (typeof value !== 'string' || value.length === 0 || value.length > MAX_VISUAL_PATH_LENGTH || value.includes('\u0000')) {
    throw visualError('Electron visual baselinePath must be a bounded relative PNG path', 'ELECTRON_VISUAL_BASELINE_PATH_INVALID');
  }
  const raw = value.replaceAll('\\', '/');
  if (raw.startsWith('/') || raw.startsWith('//') || /^[A-Za-z]:/.test(raw)) {
    throw visualError('Electron visual baselinePath must remain inside the project root', 'ELECTRON_VISUAL_BASELINE_PATH_ESCAPE');
  }
  const normalized = path.posix.normalize(raw.replace(/^\.\//, ''));
  if (!normalized || normalized === '.' || normalized === '..' || normalized.startsWith('../') || normalized.startsWith('/') || !normalized.toLowerCase().endsWith('.png')) {
    throw visualError('Electron visual baselinePath must remain inside the project root and end in .png', 'ELECTRON_VISUAL_BASELINE_PATH_ESCAPE');
  }
  return normalized;
}

function normalizeVisualCompareRequest(raw = {}) {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) {
    throw visualError('Electron visual comparison request must be an object', 'ELECTRON_VISUAL_REQUEST_INVALID');
  }
  const supported = new Set(['baselinePath', 'maxDiffPixels', 'channelThreshold']);
  if (Object.keys(raw).some((key) => !supported.has(key))) {
    throw visualError('Electron visual comparison request contains an unsupported field', 'ELECTRON_VISUAL_REQUEST_INVALID');
  }
  const baselinePath = boundedRelativePng(raw.baselinePath);
  const maxDiffPixels = raw.maxDiffPixels === undefined ? 0 : raw.maxDiffPixels;
  if (!Number.isInteger(maxDiffPixels) || maxDiffPixels < 0 || maxDiffPixels > MAX_VISUAL_PIXELS) {
    throw visualError(`Electron visual maxDiffPixels must be an integer between 0 and ${MAX_VISUAL_PIXELS}`, 'ELECTRON_VISUAL_REQUEST_INVALID');
  }
  const channelThreshold = raw.channelThreshold === undefined ? 0 : raw.channelThreshold;
  if (!Number.isInteger(channelThreshold) || channelThreshold < 0 || channelThreshold > 255) {
    throw visualError('Electron visual channelThreshold must be an integer between 0 and 255', 'ELECTRON_VISUAL_REQUEST_INVALID');
  }
  return Object.freeze({ baselinePath, maxDiffPixels, channelThreshold });
}

function insideRoot(root, candidate) {
  const relative = path.relative(root, candidate);
  return relative === '' || (!relative.startsWith('..') && !path.isAbsolute(relative));
}

function isPng(buffer) {
  return Buffer.isBuffer(buffer)
    && buffer.length >= PNG_SIGNATURE.length
    && buffer.subarray(0, PNG_SIGNATURE.length).equals(PNG_SIGNATURE);
}

function hashBuffer(buffer) {
  return crypto.createHash('sha256').update(buffer).digest('hex');
}

async function readBaseline(root, relativePath, fsPromises) {
  if (typeof root !== 'string' || !root) throw visualError('Electron visual project root is invalid', 'ELECTRON_VISUAL_ROOT_INVALID');
  const realRoot = await fsPromises.realpath(root).catch(() => null);
  if (!realRoot) throw visualError('Electron visual project root is unavailable', 'ELECTRON_VISUAL_ROOT_INVALID');
  const rootInfo = await fsPromises.stat(realRoot).catch(() => null);
  if (!rootInfo?.isDirectory?.()) throw visualError('Electron visual project root must be a directory', 'ELECTRON_VISUAL_ROOT_INVALID');
  const candidate = path.resolve(realRoot, ...relativePath.split('/'));
  if (!insideRoot(realRoot, candidate)) throw visualError('Electron visual baseline escapes the project root', 'ELECTRON_VISUAL_BASELINE_PATH_ESCAPE');
  const lstat = await fsPromises.lstat(candidate).catch(() => null);
  if (!lstat?.isFile?.() || lstat.isSymbolicLink?.() || lstat.size <= 0 || lstat.size > MAX_VISUAL_BASELINE_BYTES) {
    throw visualError('Electron visual baseline must be a bounded regular PNG file', 'ELECTRON_VISUAL_BASELINE_INVALID');
  }
  const resolved = await fsPromises.realpath(candidate).catch(() => null);
  if (!resolved || !insideRoot(realRoot, resolved)) throw visualError('Electron visual baseline resolves outside the project root', 'ELECTRON_VISUAL_BASELINE_PATH_ESCAPE');
  const buffer = await fsPromises.readFile(resolved);
  if (!isPng(buffer)) throw visualError('Electron visual baseline is not a PNG image', 'ELECTRON_VISUAL_BASELINE_INVALID');
  return buffer;
}

function representationScale(image, label) {
  let factors;
  try {
    factors = image?.getScaleFactors?.();
  } catch {
    factors = null;
  }
  const valid = Array.isArray(factors)
    ? factors.filter((factor) => Number.isFinite(factor) && factor > 0).sort((left, right) => left - right)
    : [];
  if (valid.length === 0) {
    throw visualError(`Electron visual ${label} has no usable bitmap representation`, 'ELECTRON_VISUAL_BITMAP_UNSUPPORTED');
  }
  return valid[0];
}

function decodeBitmap(nativeImage, buffer, label) {
  if (!nativeImage || typeof nativeImage.createFromBuffer !== 'function') {
    throw visualError('Electron nativeImage decoder is unavailable', 'ELECTRON_VISUAL_DECODER_UNAVAILABLE');
  }
  if (!isPng(buffer)) throw visualError(`Electron visual ${label} is not a PNG image`, 'ELECTRON_VISUAL_IMAGE_INVALID');
  let image;
  try {
    image = nativeImage.createFromBuffer(buffer, { scaleFactor: 1 });
  } catch {
    throw visualError(`Electron visual ${label} could not be decoded`, 'ELECTRON_VISUAL_IMAGE_INVALID');
  }
  if (!image || typeof image.isEmpty !== 'function' || image.isEmpty()) {
    throw visualError(`Electron visual ${label} decoded to an empty image`, 'ELECTRON_VISUAL_IMAGE_INVALID');
  }

  const scaleFactor = representationScale(image, label);
  const size = image.getSize?.(scaleFactor);
  const dipWidth = Number(size?.width);
  const dipHeight = Number(size?.height);
  const width = Math.round(dipWidth * scaleFactor);
  const height = Math.round(dipHeight * scaleFactor);
  if (
    !Number.isFinite(dipWidth) || !Number.isFinite(dipHeight) || dipWidth <= 0 || dipHeight <= 0
    || !Number.isSafeInteger(width) || !Number.isSafeInteger(height) || width <= 0 || height <= 0
    || width * height > MAX_VISUAL_PIXELS
  ) {
    throw visualError(`Electron visual ${label} dimensions are invalid or too large`, 'ELECTRON_VISUAL_IMAGE_INVALID');
  }

  const bitmap = image.toBitmap?.({ scaleFactor });
  const expectedBytes = width * height * 4;
  if (!Buffer.isBuffer(bitmap) || bitmap.length !== expectedBytes) {
    throw visualError(`Electron visual ${label} bitmap layout is unsupported`, 'ELECTRON_VISUAL_BITMAP_UNSUPPORTED');
  }
  return { width, height, bitmap };
}

function compareBitmaps(current, baseline, { maxDiffPixels, channelThreshold }) {
  if (current.width !== baseline.width || current.height !== baseline.height) {
    return {
      passed: false,
      reason: 'dimension-mismatch',
      diffPixels: null,
      totalPixels: null,
      diffRatio: null
    };
  }
  const totalPixels = current.width * current.height;
  let diffPixels = 0;
  for (let offset = 0; offset < current.bitmap.length; offset += 4) {
    let different = false;
    for (let channel = 0; channel < 4; channel += 1) {
      if (Math.abs(current.bitmap[offset + channel] - baseline.bitmap[offset + channel]) > channelThreshold) {
        different = true;
        break;
      }
    }
    if (different) diffPixels += 1;
  }
  return {
    passed: diffPixels <= maxDiffPixels,
    reason: diffPixels <= maxDiffPixels ? 'within-threshold' : 'pixel-diff-exceeded',
    diffPixels,
    totalPixels,
    diffRatio: totalPixels === 0 ? 0 : diffPixels / totalPixels
  };
}

async function compareVisualSnapshot({ nativeImage, currentPng, request, root, fsPromises = fs } = {}) {
  const normalized = normalizeVisualCompareRequest(request);
  if (!Buffer.isBuffer(currentPng) || currentPng.length <= 0 || currentPng.length > MAX_VISUAL_BASELINE_BYTES || !isPng(currentPng)) {
    throw visualError('Electron visual current screenshot is not a bounded PNG image', 'ELECTRON_VISUAL_IMAGE_INVALID');
  }
  const baselinePng = await readBaseline(root, normalized.baselinePath, fsPromises);
  const current = decodeBitmap(nativeImage, currentPng, 'current screenshot');
  const baseline = decodeBitmap(nativeImage, baselinePng, 'baseline');
  const comparison = compareBitmaps(current, baseline, normalized);
  return Object.freeze({
    ok: true,
    passed: comparison.passed,
    reason: comparison.reason,
    baselineHash: hashBuffer(baselinePng),
    currentHash: hashBuffer(currentPng),
    baseline: Object.freeze({ width: baseline.width, height: baseline.height }),
    current: Object.freeze({ width: current.width, height: current.height }),
    diffPixels: comparison.diffPixels,
    totalPixels: comparison.totalPixels,
    diffRatio: comparison.diffRatio,
    maxDiffPixels: normalized.maxDiffPixels,
    channelThreshold: normalized.channelThreshold
  });
}

module.exports = {
  MAX_VISUAL_BASELINE_BYTES,
  MAX_VISUAL_PIXELS,
  normalizeVisualCompareRequest,
  compareVisualSnapshot
};
