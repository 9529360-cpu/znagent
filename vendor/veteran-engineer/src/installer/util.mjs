import { spawn } from 'node:child_process';
import { constants as fsConstants } from 'node:fs';
import fs from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';
import os from 'node:os';
import { ensureDir, pathExists, stableStringify } from '../util.mjs';

const COPY_EXCLUDES = new Set(['.git', 'node_modules', '.DS_Store']);

export async function runCommand(command, args = [], { cwd, env, timeoutMs = 30_000, allowFailure = false, input } = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, {
      cwd,
      env: env ? { ...process.env, ...env } : process.env,
      shell: false,
      windowsHide: true,
      stdio: ['pipe', 'pipe', 'pipe']
    });
    let stdout = '';
    let stderr = '';
    let settled = false;
    const timer = setTimeout(() => {
      child.kill('SIGTERM');
      setTimeout(() => child.kill('SIGKILL'), 1000).unref();
    }, timeoutMs);
    child.stdout.on('data', (chunk) => { stdout += chunk; if (stdout.length > 2_000_000) stdout = stdout.slice(-2_000_000); });
    child.stderr.on('data', (chunk) => { stderr += chunk; if (stderr.length > 2_000_000) stderr = stderr.slice(-2_000_000); });
    child.on('error', (error) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      if (allowFailure) resolve({ code: -1, stdout, stderr: `${stderr}${error.message}`, error });
      else reject(error);
    });
    child.on('close', (code, signal) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      const result = { code: code ?? -1, signal, stdout, stderr };
      if (result.code !== 0 && !allowFailure) {
        const error = new Error(`${command} ${args.join(' ')} failed with exit ${result.code}: ${stderr.trim() || stdout.trim()}`);
        error.code = 'COMMAND_FAILED';
        error.details = result;
        reject(error);
      } else resolve(result);
    });
    if (input !== undefined) child.stdin.end(input);
    else child.stdin.end();
  });
}

async function isExecutableFile(candidate) {
  try {
    const stat = await fs.stat(candidate);
    if (!stat.isFile()) return false;
    if (process.platform !== 'win32') await fs.access(candidate, fsConstants.X_OK);
    return true;
  } catch {
    return false;
  }
}

export async function findExecutable(command, env = process.env) {
  if (!command || command.includes('/') || command.includes('\\')) {
    return (await isExecutableFile(command)) ? path.resolve(command) : null;
  }
  const paths = String(env.PATH || '').split(path.delimiter).filter(Boolean);
  const extensions = process.platform === 'win32'
    ? String(env.PATHEXT || '.EXE;.CMD;.BAT;.COM').split(';').filter(Boolean)
    : [''];
  for (const dir of paths) {
    for (const ext of extensions) {
      const candidate = path.join(dir, process.platform === 'win32' ? `${command}${ext}` : command);
      if (await isExecutableFile(candidate)) return candidate;
    }
  }
  return null;
}

async function walkFiles(root, rel = '') {
  const current = path.join(root, rel);
  const entries = await fs.readdir(current, { withFileTypes: true });
  const out = [];
  for (const entry of entries.sort((a, b) => a.name.localeCompare(b.name))) {
    if (COPY_EXCLUDES.has(entry.name)) continue;
    const childRel = rel ? path.join(rel, entry.name) : entry.name;
    if (entry.isDirectory()) out.push(...await walkFiles(root, childRel));
    else if (entry.isFile()) out.push(childRel);
    else if (entry.isSymbolicLink()) {
      const error = new Error(`Distribution contains unsupported symlink: ${childRel}`);
      error.code = 'DISTRIBUTION_SYMLINK_REJECTED';
      throw error;
    }
  }
  return out;
}

export async function distributionDigest(root) {
  const files = await walkFiles(root);
  const hash = crypto.createHash('sha256');
  for (const rel of files) {
    hash.update(rel.replaceAll(path.sep, '/'));
    hash.update('\0');
    hash.update(await fs.readFile(path.join(root, rel)));
    hash.update('\0');
  }
  return hash.digest('hex');
}

export async function copyDistribution(sourceRoot, targetRoot) {
  const sourceReal = await fs.realpath(sourceRoot);
  const targetResolved = path.resolve(targetRoot);
  const targetReal = await fs.realpath(targetResolved).catch(() => null);
  if (targetReal && targetReal === sourceReal) return { changed: false, runtimeRoot: targetResolved };

  await ensureDir(path.dirname(targetResolved));
  const stage = `${targetResolved}.stage-${crypto.randomUUID()}`;
  const backup = `${targetResolved}.backup-${crypto.randomUUID()}`;
  await fs.rm(stage, { recursive: true, force: true });
  await ensureDir(stage);
  const files = await walkFiles(sourceReal);
  for (const rel of files) {
    const src = path.join(sourceReal, rel);
    const dst = path.join(stage, rel);
    await ensureDir(path.dirname(dst));
    await fs.copyFile(src, dst);
  }
  let movedOld = false;
  try {
    if (await pathExists(targetResolved)) {
      await fs.rename(targetResolved, backup);
      movedOld = true;
    }
    await fs.rename(stage, targetResolved);
    if (movedOld) {
      const priorNodeModules = path.join(backup, 'node_modules');
      const nextNodeModules = path.join(targetResolved, 'node_modules');
      if (await pathExists(priorNodeModules) && !(await pathExists(nextNodeModules))) {
        await fs.rename(priorNodeModules, nextNodeModules);
      }
      await fs.rm(backup, { recursive: true, force: true });
    }
  } catch (error) {
    await fs.rm(stage, { recursive: true, force: true }).catch(() => {});
    if (movedOld && !(await pathExists(targetResolved)) && await pathExists(backup)) {
      await fs.rename(backup, targetResolved).catch(() => {});
    }
    throw error;
  }
  return { changed: true, runtimeRoot: targetResolved };
}

export async function readJson(file, fallback = null) {
  try { return JSON.parse(await fs.readFile(file, 'utf8')); }
  catch (error) {
    if (error.code === 'ENOENT') return fallback;
    throw error;
  }
}

export async function writeJsonAtomic(file, value) {
  await ensureDir(path.dirname(file));
  const tmp = `${file}.tmp-${process.pid}-${crypto.randomUUID()}`;
  const data = `${JSON.stringify(value, null, 2)}\n`;
  await fs.writeFile(tmp, data, { mode: 0o600 });
  await fs.rename(tmp, file);
}

export async function backupFile(file) {
  if (!(await pathExists(file))) return null;
  const backup = `${file}.veteran-backup-${Date.now()}`;
  await fs.copyFile(file, backup);
  return backup;
}

export function defaultInstallerPaths(home = os.homedir()) {
  const installerRoot = path.join(home, '.veteran-engineer');
  return {
    home,
    installerRoot,
    installerStatePath: path.join(installerRoot, 'installer.json'),
    runtimeStateRoot: path.join(installerRoot, 'state'),
    runtimeRoot: path.join(home, 'plugins', 'veteran-engineer')
  };
}

export function stableObjectHash(value) {
  return crypto.createHash('sha256').update(stableStringify(value)).digest('hex');
}
