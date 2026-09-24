import path from 'node:path';
import { sha256 } from './util.mjs';

const ENGINES = new Set(['docker', 'podman']);
const DIGEST_IMAGE = /^[^\s@]+@sha256:[0-9a-f]{64}$/i;
const ENV_KEY = /^[A-Z_][A-Z0-9_]*$/;
const ENGINE_CONTROL_ENV = new Set(['DOCKER_HOST', 'DOCKER_CONTEXT', 'DOCKER_TLS_VERIFY', 'DOCKER_CERT_PATH', 'CONTAINER_HOST', 'CONTAINER_CONNECTION']);

function positiveNumber(value, name, { integer = false } = {}) {
  const number = Number(value);
  if (!Number.isFinite(number) || number <= 0 || (integer && !Number.isInteger(number))) {
    const error = new Error(`Container worker ${name} must be a positive ${integer ? 'integer' : 'number'}`);
    error.code = 'CONTAINER_WORKER_CONFIG_INVALID';
    throw error;
  }
  return number;
}

function bindSpec(source, target, readonly = false) {
  if (String(source).includes(',')) {
    const error = new Error('Container worker bind paths may not contain commas');
    error.code = 'CONTAINER_WORKER_PATH_UNSUPPORTED';
    throw error;
  }
  return `type=bind,source=${source},target=${target}${readonly ? ',readonly' : ''}`;
}

function containerName({ packetPath, mission, task }) {
  const dispatch = path.basename(packetPath, path.extname(packetPath));
  const readable = `veteran-${mission.id}-${task.id}`.toLowerCase().replace(/[^a-z0-9_.-]+/g, '-');
  const digest = sha256(`${mission.id}\u0000${task.id}\u0000${dispatch}`).slice(0, 16);
  const maxPrefix = 63 - digest.length - 1;
  const prefix = readable.slice(0, maxPrefix).replace(/[-_.]+$/g, '') || 'veteran';
  return `${prefix}-${digest}`;
}

function containerUser(config) {
  if (config.user !== undefined && config.user !== null && String(config.user).length) return String(config.user);
  if (typeof process.getuid === 'function' && typeof process.getgid === 'function') {
    return `${process.getuid()}:${process.getgid()}`;
  }
  return null;
}

export function validateContainerWorkerConfig(config) {
  const engine = String(config?.engine || 'docker');
  if (!ENGINES.has(engine)) {
    const error = new Error(`Container worker engine must be one of: ${[...ENGINES].join(', ')}`);
    error.code = 'CONTAINER_WORKER_ENGINE_BLOCKED';
    throw error;
  }
  if (!DIGEST_IMAGE.test(String(config?.image || ''))) {
    const error = new Error('Container worker image must be pinned to an explicit sha256 digest');
    error.code = 'CONTAINER_WORKER_IMAGE_UNPINNED';
    throw error;
  }
  if (!Array.isArray(config.containerCommand) || config.containerCommand.length === 0 || config.containerCommand.some((part) => typeof part !== 'string' || !part.length)) {
    const error = new Error('Container worker requires a non-empty containerCommand argv array');
    error.code = 'CONTAINER_WORKER_CONFIG_INVALID';
    throw error;
  }
  if (config.envAllowlist !== undefined && !Array.isArray(config.envAllowlist)) {
    const error = new Error('Container worker envAllowlist must be an array when supplied');
    error.code = 'CONTAINER_WORKER_CONFIG_INVALID';
    throw error;
  }
  for (const key of config.envAllowlist || []) {
    if (typeof key !== 'string' || !ENV_KEY.test(key) || ENGINE_CONTROL_ENV.has(key)) {
      const error = new Error(`Invalid or engine-controlling container environment key: ${key}`);
      error.code = 'CONTAINER_WORKER_CONFIG_INVALID';
      throw error;
    }
  }
  if (config.pidsLimit !== undefined) positiveNumber(config.pidsLimit, 'pidsLimit', { integer: true });
  if (config.memoryMb !== undefined) positiveNumber(config.memoryMb, 'memoryMb', { integer: true });
  if (config.cpus !== undefined) positiveNumber(config.cpus, 'cpus');
  return { ...config, engine };
}

export function buildContainerInvocation({ config, worktreePath, packetPath, task, mission, runtimeNamespace = null }) {
  const validated = validateContainerWorkerConfig(config);
  const pidsLimit = validated.pidsLimit === undefined ? 256 : positiveNumber(validated.pidsLimit, 'pidsLimit', { integer: true });
  const memoryMb = validated.memoryMb === undefined ? 1024 : positiveNumber(validated.memoryMb, 'memoryMb', { integer: true });
  const cpus = validated.cpus === undefined ? 1 : positiveNumber(validated.cpus, 'cpus');
  const name = containerName({ packetPath, mission, task });
  const user = containerUser(validated);
  const args = [
    'run', '--rm',
    '--name', name,
    '--network', 'none',
    '--read-only',
    '--cap-drop', 'ALL',
    '--security-opt', 'no-new-privileges',
    '--pids-limit', String(pidsLimit),
    '--memory', `${memoryMb}m`,
    '--cpus', String(cpus),
    '--tmpfs', '/tmp:rw,noexec,nosuid,size=64m',
    '--mount', bindSpec(worktreePath, '/workspace'),
    '--mount', bindSpec(path.join(worktreePath, '.git'), '/workspace/.git', true),
    '--mount', bindSpec(packetPath, '/veteran/task.json', true),
    '--workdir', '/workspace',
    '--env', 'VETERAN_TASK_PACKET=/veteran/task.json',
    '--env', 'VETERAN_WORKTREE=/workspace',
    '--env', `VETERAN_TASK_ID=${task.id}`,
    '--env', `VETERAN_MISSION_ID=${mission.id}`
  ];
  if (runtimeNamespace) args.push('--env', `VETERAN_RUNTIME_NAMESPACE=${runtimeNamespace}`);
  for (const key of validated.envAllowlist || []) args.push('--env', key);
  if (user) args.push('--user', user);
  if (validated.stdin !== undefined) args.push('--interactive');
  args.push(validated.image, ...validated.containerCommand);
  return { command: validated.engine, args, container: { engine: validated.engine, name, user } };
}
