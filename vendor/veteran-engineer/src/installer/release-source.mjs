import crypto from 'node:crypto';
import fs from 'node:fs/promises';
import path from 'node:path';
import { ensureDir } from '../util.mjs';
import { materializeRuntimeBundle } from './runtime-bundle.mjs';

export const DEFAULT_RELEASE_REPOSITORY = '9529360-cpu/veteran-engineer';
const DEFAULT_API_BASE = 'https://api.github.com';
const MAX_ASSET_BYTES = 96 * 1024 * 1024;

function sha256(value) {
  return crypto.createHash('sha256').update(value).digest('hex');
}

function releaseError(message, code, details = null) {
  const error = new Error(message);
  error.code = code;
  if (details) error.details = details;
  return error;
}

function normalizedSelector(selector) {
  const value = String(selector || '').trim();
  if (value === 'latest') return value;
  if (/^v\d+\.\d+\.\d+$/.test(value)) return value;
  throw releaseError(`Unsupported release selector: ${selector}`, 'RELEASE_SELECTOR_INVALID');
}

async function fetchBytes(fetchImpl, url, { headers = {}, maxBytes = MAX_ASSET_BYTES } = {}) {
  const response = await fetchImpl(url, { headers, redirect: 'follow' });
  if (!response?.ok) throw releaseError(`Release download failed (${response?.status || 'unknown'}): ${url}`, 'RELEASE_DOWNLOAD_FAILED', { status: response?.status || null });
  const declared = Number(response.headers?.get?.('content-length') || 0);
  if (declared > maxBytes) throw releaseError(`Release asset exceeds size limit: ${declared}`, 'RELEASE_ASSET_TOO_LARGE');
  const bytes = Buffer.from(await response.arrayBuffer());
  if (bytes.length > maxBytes) throw releaseError(`Release asset exceeds size limit: ${bytes.length}`, 'RELEASE_ASSET_TOO_LARGE');
  return bytes;
}

function requireAsset(release, name) {
  const asset = release.assets?.find((item) => item?.name === name);
  if (!asset) throw releaseError(`Release asset is missing: ${name}`, 'RELEASE_ASSET_MISSING');
  if (typeof asset.digest !== 'string' || !/^sha256:[0-9a-f]{64}$/.test(asset.digest)) {
    throw releaseError(`Release asset has no verified SHA-256 digest: ${name}`, 'RELEASE_ASSET_DIGEST_MISSING');
  }
  if (typeof asset.browser_download_url !== 'string' || !asset.browser_download_url) {
    throw releaseError(`Release asset has no download URL: ${name}`, 'RELEASE_ASSET_URL_INVALID');
  }
  return asset;
}

async function downloadVerifiedAsset(fetchImpl, asset, options = {}) {
  const bytes = await fetchBytes(fetchImpl, asset.browser_download_url, options);
  const actual = sha256(bytes);
  const expected = asset.digest.slice('sha256:'.length);
  if (actual !== expected) throw releaseError(`Release asset digest mismatch: ${asset.name}`, 'RELEASE_ASSET_DIGEST_MISMATCH', { expected, actual });
  return bytes;
}

export class GitHubReleaseSource {
  constructor({ repository = DEFAULT_RELEASE_REPOSITORY, apiBase = DEFAULT_API_BASE, fetchImpl = globalThis.fetch, installerRoot } = {}) {
    if (typeof fetchImpl !== 'function') throw new Error('fetchImpl is required');
    if (!installerRoot) throw new Error('installerRoot is required');
    this.repository = repository;
    this.apiBase = String(apiBase).replace(/\/$/, '');
    this.fetchImpl = fetchImpl;
    this.installerRoot = path.resolve(installerRoot);
  }

  async #release(selector) {
    const normalized = normalizedSelector(selector);
    const endpoint = normalized === 'latest'
      ? `${this.apiBase}/repos/${this.repository}/releases/latest`
      : `${this.apiBase}/repos/${this.repository}/releases/tags/${encodeURIComponent(normalized)}`;
    const response = await this.fetchImpl(endpoint, { headers: { Accept: 'application/vnd.github+json', 'User-Agent': 'veteran-engineer-installer' } });
    if (!response?.ok) throw releaseError(`GitHub release lookup failed (${response?.status || 'unknown'}): ${normalized}`, 'RELEASE_LOOKUP_FAILED', { selector: normalized, status: response?.status || null });
    const release = await response.json();
    if (release?.draft || release?.prerelease) throw releaseError(`Release is not public/stable: ${release?.tag_name || normalized}`, 'RELEASE_NOT_STABLE');
    if (normalized !== 'latest' && release?.tag_name !== normalized) throw releaseError(`Release lookup returned the wrong tag: ${release?.tag_name}`, 'RELEASE_TAG_MISMATCH');
    if (!/^v\d+\.\d+\.\d+$/.test(release?.tag_name || '')) throw releaseError(`Release tag is invalid: ${release?.tag_name}`, 'RELEASE_TAG_INVALID');
    if (!/^[0-9a-f]{40}$/.test(release?.target_commitish || '')) throw releaseError('Release target must be an exact commit SHA', 'RELEASE_SOURCE_IDENTITY_INVALID');
    return release;
  }

  async stage(selector = 'latest') {
    const release = await this.#release(selector);
    const manifestAsset = requireAsset(release, 'veteran-engineer-release-manifest.json');
    const manifestBytes = await downloadVerifiedAsset(this.fetchImpl, manifestAsset);
    let manifest;
    try { manifest = JSON.parse(manifestBytes.toString('utf8')); }
    catch { throw releaseError('Release manifest is invalid JSON', 'RELEASE_MANIFEST_INVALID'); }
    const version = release.tag_name.slice(1);
    if (manifest?.schemaVersion !== 1 || manifest?.product !== 'veteran-engineer' || manifest?.version !== version || manifest?.tag !== release.tag_name || manifest?.commit !== release.target_commitish) {
      throw releaseError('Release manifest identity does not match GitHub release', 'RELEASE_MANIFEST_IDENTITY_MISMATCH');
    }
    const runtime = manifest.assets?.find((item) => item?.profile === 'runtime');
    if (!runtime?.filename || !runtime?.checksumFile || !/^[0-9a-f]{64}$/.test(runtime?.sha256 || '')) {
      throw releaseError('Release manifest does not contain a canonical runtime asset', 'RELEASE_RUNTIME_ASSET_MISSING');
    }
    const runtimeAsset = requireAsset(release, runtime.filename);
    const checksumAsset = requireAsset(release, runtime.checksumFile);
    const runtimeBytes = await downloadVerifiedAsset(this.fetchImpl, runtimeAsset);
    if (runtime.bytes !== runtimeBytes.length || (Number.isInteger(runtimeAsset.size) && runtimeAsset.size !== runtimeBytes.length)) throw releaseError('Runtime asset size does not match release metadata', 'RELEASE_RUNTIME_SIZE_MISMATCH');
    if (sha256(runtimeBytes) !== runtime.sha256) throw releaseError('Runtime asset digest does not match release manifest', 'RELEASE_RUNTIME_DIGEST_MISMATCH');
    const checksumBytes = await downloadVerifiedAsset(this.fetchImpl, checksumAsset, { maxBytes: 4096 });
    const checksumLine = checksumBytes.toString('utf8').trim();
    if (checksumLine !== `${runtime.sha256}  ${runtime.filename}`) throw releaseError('Runtime checksum asset does not match release manifest', 'RELEASE_RUNTIME_CHECKSUM_MISMATCH');

    const downloads = path.join(this.installerRoot, 'downloads');
    await ensureDir(downloads);
    const stageRoot = await fs.mkdtemp(path.join(downloads, 'release-'));
    const distributionRoot = path.join(stageRoot, 'distribution');
    try {
      const materialized = await materializeRuntimeBundle(runtimeBytes, distributionRoot);
      if (materialized.version !== version) throw releaseError(`Runtime bundle version ${materialized.version} does not match release ${version}`, 'RELEASE_RUNTIME_VERSION_MISMATCH');
      return {
        root: distributionRoot,
        version,
        tag: release.tag_name,
        commit: release.target_commitish,
        releaseId: release.id || null,
        runtimeSha256: runtime.sha256,
        cleanup: async () => { await fs.rm(stageRoot, { recursive: true, force: true }); }
      };
    } catch (error) {
      await fs.rm(stageRoot, { recursive: true, force: true }).catch(() => {});
      throw error;
    }
  }
}
