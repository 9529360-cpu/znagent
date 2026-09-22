import crypto from 'node:crypto';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { ensureWorkspaceRoots, normalizedAllowedLocalRoots } from './workspace-policy.mjs';

export const REMOTE_HOST_CONFIG_VERSION = 1;
export const DEFAULT_REMOTE_HOST_PORT = 8765;
export const DEFAULT_REMOTE_HOST_BIND = '127.0.0.1';

function sha256(value) {
  return crypto.createHash('sha256').update(value).digest('hex');
}

export function defaultRemoteHostConfigPath() {
  return path.join(os.homedir(), '.veteran-engineer', 'remote-host.json');
}

export function defaultRemoteHostStateRoot() {
  return path.join(os.homedir(), '.veteran-engineer', 'state');
}

function normalizedPort(value) {
  const port = Number(value ?? DEFAULT_REMOTE_HOST_PORT);
  if (!Number.isInteger(port) || port < 0 || port > 65535) {
    const error = new Error(`Invalid remote host port: ${value}`);
    error.code = 'REMOTE_HOST_PORT_INVALID';
    throw error;
  }
  return port;
}

function normalizedBind(value) {
  const bind = String(value || DEFAULT_REMOTE_HOST_BIND).trim();
  if (!bind) throw new Error('Remote host bind address must not be empty');
  return bind;
}

function normalizedOrigins(values) {
  if (values == null) return [];
  if (!Array.isArray(values)) throw new TypeError('allowedOrigins must be an array');
  return [...new Set(values.map((value) => {
    const text = String(value || '').trim();
    if (!text) throw new TypeError('allowedOrigins must contain non-empty absolute origins');
    const url = new URL(text);
    if (!['http:', 'https:'].includes(url.protocol) || url.pathname !== '/' || url.search || url.hash) {
      throw new TypeError(`Invalid allowed origin: ${text}`);
    }
    return url.origin;
  }))];
}

function normalizedAllowedHosts(values, bind) {
  const defaults = bind === '127.0.0.1' || bind === 'localhost' || bind === '::1'
    ? ['127.0.0.1', 'localhost', '::1']
    : [bind];
  if (values == null) return defaults;
  if (!Array.isArray(values)) throw new TypeError('allowedHosts must be an array');
  return [...new Set(values.map((value) => String(value || '').trim()).filter(Boolean))];
}

export function generatePairingToken() {
  return `veteran_${crypto.randomBytes(32).toString('base64url')}`;
}

export function tokenDigest(token) {
  return sha256(String(token || ''));
}

export async function initRemoteHostConfig({
  configPath = defaultRemoteHostConfigPath(),
  stateRoot = defaultRemoteHostStateRoot(),
  workspaces = [],
  bind = DEFAULT_REMOTE_HOST_BIND,
  port = DEFAULT_REMOTE_HOST_PORT,
  allowedOrigins = [],
  allowedHosts = null,
  force = false,
  token = generatePairingToken()
} = {}) {
  const resolvedConfigPath = path.resolve(configPath);
  const resolvedStateRoot = path.resolve(stateRoot);
  const resolvedBind = normalizedBind(bind);
  const roots = normalizedAllowedLocalRoots(workspaces);
  const canonicalRoots = await ensureWorkspaceRoots(roots);
  await fs.mkdir(path.dirname(resolvedConfigPath), { recursive: true });
  if (!force) {
    try {
      await fs.access(resolvedConfigPath);
      const error = new Error(`Remote host config already exists: ${resolvedConfigPath}`);
      error.code = 'REMOTE_HOST_CONFIG_EXISTS';
      throw error;
    } catch (error) {
      if (error?.code !== 'ENOENT') throw error;
    }
  }
  const config = {
    schemaVersion: REMOTE_HOST_CONFIG_VERSION,
    deviceId: `device_${crypto.randomUUID()}`,
    deviceName: os.hostname(),
    createdAt: new Date().toISOString(),
    stateRoot: resolvedStateRoot,
    bind: resolvedBind,
    port: normalizedPort(port),
    allowedLocalRoots: canonicalRoots,
    allowedOrigins: normalizedOrigins(allowedOrigins),
    allowedHosts: normalizedAllowedHosts(allowedHosts, resolvedBind),
    tokenSha256: tokenDigest(token)
  };
  const temporary = `${resolvedConfigPath}.${process.pid}.${crypto.randomUUID()}.tmp`;
  await fs.writeFile(temporary, `${JSON.stringify(config, null, 2)}\n`, { mode: 0o600 });
  await fs.rename(temporary, resolvedConfigPath);
  await fs.chmod(resolvedConfigPath, 0o600).catch(() => {});
  return {
    config,
    configPath: resolvedConfigPath,
    pairingToken: token,
    pairingHint: token.slice(-8)
  };
}

export async function readRemoteHostConfig(configPath = defaultRemoteHostConfigPath()) {
  const resolvedConfigPath = path.resolve(configPath);
  let config;
  try {
    config = JSON.parse(await fs.readFile(resolvedConfigPath, 'utf8'));
  } catch (error) {
    if (error?.code === 'ENOENT') {
      const missing = new Error(`Remote host is not initialized: ${resolvedConfigPath}`);
      missing.code = 'REMOTE_HOST_NOT_INITIALIZED';
      throw missing;
    }
    throw error;
  }
  if (config?.schemaVersion !== REMOTE_HOST_CONFIG_VERSION || typeof config.deviceId !== 'string' || typeof config.tokenSha256 !== 'string') {
    const error = new Error(`Unsupported or invalid remote host config: ${resolvedConfigPath}`);
    error.code = 'REMOTE_HOST_CONFIG_INVALID';
    throw error;
  }
  return {
    ...config,
    stateRoot: path.resolve(config.stateRoot || defaultRemoteHostStateRoot()),
    bind: normalizedBind(config.bind),
    port: normalizedPort(config.port),
    allowedLocalRoots: normalizedAllowedLocalRoots(config.allowedLocalRoots || []),
    allowedOrigins: normalizedOrigins(config.allowedOrigins || []),
    allowedHosts: normalizedAllowedHosts(config.allowedHosts || [], normalizedBind(config.bind))
  };
}

export async function rotateRemoteHostToken(configPath = defaultRemoteHostConfigPath()) {
  const resolvedConfigPath = path.resolve(configPath);
  const config = await readRemoteHostConfig(resolvedConfigPath);
  const token = generatePairingToken();
  config.tokenSha256 = tokenDigest(token);
  config.tokenRotatedAt = new Date().toISOString();
  const temporary = `${resolvedConfigPath}.${process.pid}.${crypto.randomUUID()}.tmp`;
  await fs.writeFile(temporary, `${JSON.stringify(config, null, 2)}\n`, { mode: 0o600 });
  await fs.rename(temporary, resolvedConfigPath);
  await fs.chmod(resolvedConfigPath, 0o600).catch(() => {});
  return { config, pairingToken: token, pairingHint: token.slice(-8) };
}
