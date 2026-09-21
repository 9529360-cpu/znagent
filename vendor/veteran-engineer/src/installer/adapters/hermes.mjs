import path from 'node:path';
import fs from 'node:fs/promises';
import crypto from 'node:crypto';
import { HOST_ADAPTER_API_VERSION } from '../../constants.mjs';
import { ensureDir, pathExists } from '../../util.mjs';
import { findExecutable, readJson, writeJsonAtomic } from '../util.mjs';

const OWNERSHIP_FILE = '.veteran-engineer-owned.json';

function hermesHome(context) {
  return path.resolve(context.options.hermesHome || context.env.HERMES_HOME || path.join(context.home, '.hermes'));
}

function skillTarget(context) {
  return path.join(hermesHome(context), 'skills', 'runtime-regression-debugger');
}

function skillSource(context) {
  return path.join(context.runtimeRoot, 'skills', 'runtime-regression-debugger');
}

async function skillDigest(root) {
  const stat = await fs.lstat(root);
  if (!stat.isDirectory() || stat.isSymbolicLink()) {
    const error = new Error(`Hermes skill projection root must be a real directory: ${root}`);
    error.code = 'HOST_SKILL_PROJECTION_INVALID';
    throw error;
  }
  const files = [];
  async function walk(current, rel = '') {
    const entries = await fs.readdir(current, { withFileTypes: true });
    for (const entry of entries.sort((a, b) => a.name.localeCompare(b.name))) {
      if (!rel && entry.name === OWNERSHIP_FILE) continue;
      const childRel = rel ? path.join(rel, entry.name) : entry.name;
      const child = path.join(current, entry.name);
      if (entry.isDirectory()) await walk(child, childRel);
      else if (entry.isFile()) files.push({ rel: childRel, file: child });
      else {
        const error = new Error(`Hermes skill projection contains unsupported filesystem entry: ${childRel}`);
        error.code = 'HOST_SKILL_PROJECTION_INVALID';
        throw error;
      }
    }
  }
  await walk(root);
  const hash = crypto.createHash('sha256');
  for (const item of files) {
    hash.update(item.rel.replaceAll(path.sep, '/'));
    hash.update('\0');
    hash.update(await fs.readFile(item.file));
    hash.update('\0');
  }
  return hash.digest('hex');
}

async function inspectSkillProjection(context, marker) {
  let sourceDigest = null;
  let targetDigest = null;
  let skillProjectionError = null;
  try {
    sourceDigest = await skillDigest(skillSource(context));
  } catch (error) {
    skillProjectionError = `source:${error.code || 'SKILL_DIGEST_FAILED'}`;
  }
  try {
    targetDigest = await skillDigest(skillTarget(context));
  } catch (error) {
    const targetError = `target:${error.code || 'SKILL_DIGEST_FAILED'}`;
    skillProjectionError = skillProjectionError ? `${skillProjectionError};${targetError}` : targetError;
  }
  const skillOwned = marker?.ownedBy === 'veteran-engineer';
  const skillVersionCurrent = Boolean(skillOwned && marker?.version === context.version);
  const skillProjectionCurrent = Boolean(skillVersionCurrent && sourceDigest && targetDigest && sourceDigest === targetDigest);
  return { skillOwned, skillVersionCurrent, skillProjectionCurrent, skillProjectionError };
}

async function copyOwnedSkill(context) {
  const source = skillSource(context);
  const target = skillTarget(context);
  if (await pathExists(target)) {
    const marker = await readJson(path.join(target, OWNERSHIP_FILE), null);
    if (!marker?.ownedBy || marker.ownedBy !== 'veteran-engineer') {
      const error = new Error(`Hermes skill path already exists and is not Veteran-owned: ${target}`);
      error.code = 'HOST_SKILL_CONFLICT';
      throw error;
    }
    await fs.rm(target, { recursive: true, force: true });
  }
  await ensureDir(path.dirname(target));
  await fs.cp(source, target, { recursive: true, force: false, errorOnExist: true });
  await writeJsonAtomic(path.join(target, OWNERSHIP_FILE), { ownedBy: 'veteran-engineer', version: context.version });
  return target;
}

async function requireHermes(context) {
  const executable = await findExecutable('hermes', context.env);
  if (!executable) {
    const error = new Error('Hermes CLI not found on PATH');
    error.code = 'HOST_CLI_NOT_FOUND';
    throw error;
  }
  return executable;
}

async function listHermes(executable, context) {
  return context.exec(executable, ['mcp', 'list'], { env: context.env, allowFailure: true, timeoutMs: 30_000 });
}

export default {
  apiVersion: HOST_ADAPTER_API_VERSION,
  id: 'hermes',
  displayName: 'Hermes Agent',
  surfaceProfile: 'local-stdio',
  capabilities: { mcp: true, skill: true },
  async install(context) {
    const executable = await requireHermes(context);
    const before = await listHermes(executable, context);
    const already = /\bveteran-engineer\b/.test(`${before.stdout}\n${before.stderr}`);
    if (already && !context.previousBinding) {
      const error = new Error('Hermes already has an MCP server named veteran-engineer that is not recorded as Veteran-owned');
      error.code = 'HOST_BINDING_CONFLICT';
      throw error;
    }
    if (already && context.previousBinding) {
      await context.exec(executable, ['mcp', 'remove', 'veteran-engineer'], { env: context.env, allowFailure: true, timeoutMs: 30_000 });
    }
    const server = path.join(context.runtimeRoot, 'mcp', 'server.mjs');
    await context.exec(executable, ['mcp', 'add', 'veteran-engineer', '--command', 'node', '--args', server], { env: context.env, timeoutMs: 30_000 });
    const skillPath = await copyOwnedSkill(context);
    return { installed: true, cli: executable, skillPath, mcpServer: server, hermesHome: hermesHome(context) };
  },
  async status(context) {
    const executable = await findExecutable('hermes', context.env);
    const marker = await readJson(path.join(skillTarget(context), OWNERSHIP_FILE), null);
    let mcpInstalled = false;
    let list = null;
    if (executable) {
      list = await listHermes(executable, context);
      mcpInstalled = /\bveteran-engineer\b/.test(`${list.stdout}\n${list.stderr}`);
    }
    const projection = await inspectSkillProjection(context, marker);
    const skillInstalled = projection.skillProjectionCurrent;
    return {
      installed: Boolean(executable && mcpInstalled && skillInstalled),
      cliAvailable: Boolean(executable),
      mcpInstalled,
      skillInstalled,
      ...projection,
      skillPath: skillTarget(context),
      hermesHome: hermesHome(context),
      listExitCode: list?.code ?? null
    };
  },
  async doctor(context) {
    const status = await this.status(context);
    const checks = [
      { name: 'hermes-cli', ok: status.cliAvailable },
      { name: 'hermes-mcp-binding', ok: status.mcpInstalled },
      { name: 'hermes-skill-projection', ok: status.skillInstalled }
    ];
    if (status.cliAvailable && status.mcpInstalled) {
      const executable = await findExecutable('hermes', context.env);
      const probe = await context.exec(executable, ['mcp', 'test', 'veteran-engineer'], { env: context.env, allowFailure: true, timeoutMs: 30_000 });
      checks.push({ name: 'hermes-mcp-test', ok: probe.code === 0, exitCode: probe.code, stderr: probe.stderr.slice(0, 1000) });
    }
    return { ok: checks.every((check) => check.ok), checks, status };
  },
  async uninstall(context) {
    const executable = await findExecutable('hermes', context.env);
    const actions = [];
    if (executable) {
      const remove = await context.exec(executable, ['mcp', 'remove', 'veteran-engineer'], { env: context.env, allowFailure: true, timeoutMs: 30_000 });
      actions.push({ action: 'mcp-remove', exitCode: remove.code });
    } else actions.push({ action: 'mcp-remove', skipped: true, reason: 'cli-unavailable' });
    const target = skillTarget(context);
    const marker = await readJson(path.join(target, OWNERSHIP_FILE), null);
    if (marker?.ownedBy === 'veteran-engineer') {
      await fs.rm(target, { recursive: true, force: true });
      actions.push({ action: 'skill-remove', removed: true });
    }
    return { removed: true, actions };
  }
};
