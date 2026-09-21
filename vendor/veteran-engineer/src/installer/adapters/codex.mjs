import path from 'node:path';
import fs from 'node:fs/promises';
import { HOST_ADAPTER_API_VERSION } from '../../constants.mjs';
import { ensureDir, pathExists } from '../../util.mjs';
import { backupFile, findExecutable, readJson, stableObjectHash, writeJsonAtomic } from '../util.mjs';

const PLUGIN_NAME = 'veteran-engineer';

function marketplacePath(context) {
  return path.join(context.home, '.agents', 'plugins', 'marketplace.json');
}

function expectedRuntimeRoot(context) {
  return path.join(context.home, 'plugins', PLUGIN_NAME);
}

function expectedMarketplaceEntry() {
  return {
    name: PLUGIN_NAME,
    source: { source: 'local', path: `./plugins/${PLUGIN_NAME}` },
    policy: { installation: 'AVAILABLE', authentication: 'ON_INSTALL' },
    category: 'Developer Tools'
  };
}

function recordedBinding(context) {
  const previous = context.previousBinding;
  return previous?.binding && typeof previous.binding === 'object' ? previous.binding : previous;
}

function marketplaceEntryDriftError(file) {
  const error = new Error(`Codex marketplace entry drift must be resolved before host mutation: ${file}`);
  error.code = 'HOST_BINDING_DRIFT';
  error.details = { marketplacePath: file, plugin: PLUGIN_NAME };
  return error;
}

function marketplaceEntryOwnedByBinding(context, entry) {
  const previous = recordedBinding(context);
  if (!previous || !entry || typeof entry !== 'object' || Array.isArray(entry)) return false;
  const currentDigest = stableObjectHash(entry);
  const recordedDigest = typeof previous.marketplaceEntryDigest === 'string' ? previous.marketplaceEntryDigest : null;
  return recordedDigest
    ? currentDigest === recordedDigest
    : currentDigest === stableObjectHash(expectedMarketplaceEntry());
}

async function requireCodex(context) {
  const executable = await findExecutable('codex', context.env);
  if (!executable) {
    const error = new Error('Codex CLI not found on PATH');
    error.code = 'HOST_CLI_NOT_FOUND';
    throw error;
  }
  return executable;
}

function normalizeMarketplace(raw) {
  if (raw === null) return { name: 'personal', interface: { displayName: 'Personal' }, plugins: [] };
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) throw new Error('Codex personal marketplace must be a JSON object');
  if (!raw.name || typeof raw.name !== 'string') throw new Error('Codex personal marketplace is missing a valid name');
  if (!Array.isArray(raw.plugins)) throw new Error('Codex personal marketplace plugins must be an array');
  return raw;
}

async function ensureMarketplaceEntry(context) {
  if (path.resolve(context.runtimeRoot) !== path.resolve(expectedRuntimeRoot(context))) {
    const error = new Error(`Codex personal marketplace requires the shared runtime at ${expectedRuntimeRoot(context)}`);
    error.code = 'CODEX_RUNTIME_ROOT_UNSUPPORTED';
    throw error;
  }
  const file = marketplacePath(context);
  const original = await readJson(file, null);
  const marketplace = normalizeMarketplace(original);
  const index = marketplace.plugins.findIndex((entry) => entry?.name === PLUGIN_NAME);
  const nextEntry = expectedMarketplaceEntry();
  if (index >= 0) {
    const existing = marketplace.plugins[index];
    const previous = recordedBinding(context);
    if (!previous) {
      const error = new Error('Codex marketplace already contains veteran-engineer without recorded Veteran ownership');
      error.code = 'HOST_BINDING_CONFLICT';
      throw error;
    }
    if (!marketplaceEntryOwnedByBinding(context, existing)) throw marketplaceEntryDriftError(file);
    marketplace.plugins[index] = nextEntry;
  } else marketplace.plugins.push(nextEntry);
  await ensureDir(path.dirname(file));
  const backup = original ? await backupFile(file) : null;
  await writeJsonAtomic(file, marketplace);
  return { file, name: marketplace.name, backup, entryDigest: stableObjectHash(nextEntry) };
}

async function removeMarketplaceEntry(context) {
  const file = marketplacePath(context);
  const raw = await readJson(file, null);
  if (!raw || !Array.isArray(raw.plugins)) return { changed: false, file };
  const before = raw.plugins.length;
  raw.plugins = raw.plugins.filter((entry) => !(entry?.name === PLUGIN_NAME && entry?.source?.source === 'local' && entry?.source?.path === `./plugins/${PLUGIN_NAME}`));
  if (raw.plugins.length === before) return { changed: false, file };
  await backupFile(file);
  await writeJsonAtomic(file, raw);
  return { changed: true, file };
}

function listContainsPlugin(stdout, marketplaceName) {
  try {
    const parsed = JSON.parse(stdout);
    const items = Array.isArray(parsed) ? parsed : (Array.isArray(parsed?.plugins) ? parsed.plugins : []);
    return items.some((item) => {
      const name = item?.name || item?.pluginName || item?.plugin?.name;
      const market = item?.marketplace || item?.marketplaceName || item?.marketplace?.name;
      const installed = item?.installed ?? item?.enabled ?? item?.isInstalled ?? true;
      return name === PLUGIN_NAME && (!marketplaceName || !market || market === marketplaceName) && installed !== false;
    });
  } catch {
    return new RegExp(`\\b${PLUGIN_NAME}\\b`).test(stdout);
  }
}

function recordedMarketplaceName(context) {
  const binding = recordedBinding(context);
  if (typeof binding?.marketplaceName === 'string' && binding.marketplaceName.length > 0) return binding.marketplaceName;
  if (typeof binding?.selector === 'string') {
    const prefix = `${PLUGIN_NAME}@`;
    if (binding.selector.startsWith(prefix) && binding.selector.length > prefix.length) return binding.selector.slice(prefix.length);
  }
  return null;
}

export default {
  apiVersion: HOST_ADAPTER_API_VERSION,
  id: 'codex',
  displayName: 'OpenAI Codex',
  surfaceProfile: 'local-stdio',
  capabilities: { mcp: true, skill: true, nativePlugin: true },
  async install(context) {
    const executable = await requireCodex(context);
    const marketplace = await ensureMarketplaceEntry(context);
    const selector = `${PLUGIN_NAME}@${marketplace.name}`;
    const result = await context.exec(executable, ['plugin', 'add', selector, '--json'], { env: context.env, timeoutMs: 45_000 });
    return {
      installed: true,
      cli: executable,
      selector,
      marketplaceName: marketplace.name,
      marketplacePath: marketplace.file,
      marketplaceEntryDigest: marketplace.entryDigest,
      backup: marketplace.backup,
      result: result.stdout.trim()
    };
  },
  async status(context) {
    const executable = await findExecutable('codex', context.env);
    const marketplace = await readJson(marketplacePath(context), null);
    const entry = marketplace?.plugins?.find?.((item) => item?.name === PLUGIN_NAME);
    const marketplaceOwned = entry?.source?.source === 'local' && entry?.source?.path === `./plugins/${PLUGIN_NAME}`;
    const entryDigest = entry && typeof entry === 'object' && !Array.isArray(entry) ? stableObjectHash(entry) : null;
    const expectedEntryDigest = stableObjectHash(expectedMarketplaceEntry());
    const marketplaceEntryCurrent = Boolean(entryDigest && entryDigest === expectedEntryDigest);
    const recordedDigest = recordedBinding(context)?.marketplaceEntryDigest || null;
    const marketplaceEntryDigestCurrent = recordedDigest ? entryDigest === recordedDigest : null;
    let cliInstalled = false;
    let listExitCode = null;
    if (executable) {
      const result = await context.exec(executable, ['plugin', 'list', '--json'], { env: context.env, allowFailure: true, timeoutMs: 30_000 });
      listExitCode = result.code;
      cliInstalled = result.code === 0 && listContainsPlugin(result.stdout, marketplace?.name);
    }
    const manifestPresent = await pathExists(path.join(context.runtimeRoot, '.codex-plugin', 'plugin.json'));
    const mcpPresent = await pathExists(path.join(context.runtimeRoot, '.mcp.json'));
    return {
      installed: Boolean(executable && marketplaceOwned && marketplaceEntryCurrent && cliInstalled && manifestPresent && mcpPresent),
      cliAvailable: Boolean(executable),
      marketplaceOwned,
      marketplaceEntryCurrent,
      marketplaceEntryDigestCurrent,
      cliInstalled,
      manifestPresent,
      mcpPresent,
      marketplacePath: marketplacePath(context),
      marketplaceName: marketplace?.name || null,
      listExitCode
    };
  },
  async doctor(context) {
    const status = await this.status(context);
    const checks = [
      { name: 'codex-cli', ok: status.cliAvailable },
      { name: 'codex-marketplace-entry', ok: status.marketplaceOwned && status.marketplaceEntryCurrent },
      { name: 'codex-plugin-installed', ok: status.cliInstalled },
      { name: 'codex-plugin-manifest', ok: status.manifestPresent },
      { name: 'codex-mcp-manifest', ok: status.mcpPresent }
    ];
    return { ok: checks.every((check) => check.ok), checks, status };
  },
  async uninstall(context) {
    const file = marketplacePath(context);
    const raw = await readJson(file, null);
    let marketplace = null;
    if (raw !== null) {
      try { marketplace = normalizeMarketplace(raw); }
      catch { throw marketplaceEntryDriftError(file); }
      const entry = marketplace.plugins.find((item) => item?.name === PLUGIN_NAME);
      if (entry && !marketplaceEntryOwnedByBinding(context, entry)) throw marketplaceEntryDriftError(file);
    }

    const marketName = marketplace?.name || recordedMarketplaceName(context) || 'personal';
    const executable = await findExecutable('codex', context.env);
    const actions = [];
    if (executable) {
      const result = await context.exec(executable, ['plugin', 'remove', `${PLUGIN_NAME}@${marketName}`, '--json'], { env: context.env, allowFailure: true, timeoutMs: 45_000 });
      actions.push({ action: 'plugin-remove', exitCode: result.code, stderr: result.stderr.slice(0, 1000) });
    } else actions.push({ action: 'plugin-remove', skipped: true, reason: 'cli-unavailable' });
    const entry = await removeMarketplaceEntry(context);
    actions.push({ action: 'marketplace-entry-remove', changed: entry.changed });
    return { removed: true, actions };
  }
};
