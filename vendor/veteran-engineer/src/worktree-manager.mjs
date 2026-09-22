import fs from 'node:fs/promises';
import path from 'node:path';
import { git, sourceIdentity } from './git.mjs';
import { ensureDir, pathExists, sha256 } from './util.mjs';

function safeSegment(value) {
  const raw = String(value);
  const normalized = raw.replace(/[^a-zA-Z0-9._-]+/g, '-');
  if (normalized === raw && raw.length <= 96) return normalized;
  const digest = sha256(raw).slice(0, 16);
  const prefix = normalized.slice(0, 96 - digest.length - 1);
  return `${prefix || 'id'}-${digest}`;
}

function gitRefSegment(value) {
  let segment = safeSegment(value)
    .replace(/\.\.+/g, '-')
    .replace(/^\.+/, '')
    .replace(/\.+$/, '');
  if (segment.endsWith('.lock')) segment = `${segment.slice(0, -5)}-lock`;
  return segment || 'id';
}

export class WorktreeManager {
  constructor({ store }) {
    this.store = store;
  }

  missionPath(mission) {
    return path.join(this.store.worktreesDir, `mission-${safeSegment(mission.id)}`);
  }

  taskPath(mission, task) {
    return path.join(this.store.worktreesDir, `task-${safeSegment(mission.id)}-${safeSegment(task.id)}`);
  }

  missionBranch(mission) {
    return `veteran/mission/${gitRefSegment(mission.id)}`;
  }

  taskBranch(mission, task, attempt) {
    return `veteran/task/${gitRefSegment(mission.id)}/${gitRefSegment(task.id)}-${attempt}`;
  }

  async ensureMissionWorktree(project, mission) {
    const target = this.missionPath(mission);
    if (await pathExists(path.join(target, '.git'))) {
      const identity = await sourceIdentity(target);
      return { path: target, branch: this.missionBranch(mission), head: identity.head, reused: true };
    }
    await ensureDir(path.dirname(target));
    const branch = this.missionBranch(mission);
    const branchExists = await git(project.repoPath, ['show-ref', '--verify', '--quiet', `refs/heads/${branch}`], { allowFailure: true });
    if (branchExists.code === 0) {
      await git(project.repoPath, ['worktree', 'add', target, branch]);
    } else {
      await git(project.repoPath, ['worktree', 'add', '-b', branch, target, mission.baseSourceIdentity.head]);
    }
    const identity = await sourceIdentity(target);
    return { path: target, branch, head: identity.head, reused: false };
  }

  async createTaskWorktree(project, mission, task, baseHead) {
    const target = this.taskPath(mission, task);
    if (await pathExists(target)) {
      await git(project.repoPath, ['worktree', 'remove', '--force', target], { allowFailure: true });
      await fs.rm(target, { recursive: true, force: true });
    }
    await ensureDir(path.dirname(target));
    const branch = this.taskBranch(mission, task, task.attempts + 1);
    await git(project.repoPath, ['branch', '-D', branch], { allowFailure: true });
    await git(project.repoPath, ['worktree', 'add', '-b', branch, target, baseHead]);
    const identity = await sourceIdentity(target);
    return { path: target, branch, head: identity.head };
  }

  async removeTaskWorktree(project, mission, task) {
    const target = this.taskPath(mission, task);
    await git(project.repoPath, ['worktree', 'remove', '--force', target], { allowFailure: true });
    await fs.rm(target, { recursive: true, force: true });
  }

  async prune(project) {
    await git(project.repoPath, ['worktree', 'prune', '--expire', 'now'], { allowFailure: true });
  }
}
