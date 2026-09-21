import path from 'node:path';
import {
  git,
  repositorySourceAuthority,
  resolveRepository,
  sourceIdentity,
  sourceIdentityFromAuthority,
  withDetachedWorktree
} from './git.mjs';
import { acquireRemoteRepository, normalizeRemoteRepositoryUrl, sanitizeStoredRemoteUrl } from './repository-acquisition.mjs';
import { nowIso, randomId, sha256 } from './util.mjs';
import { projectPolicy } from './operator-config.mjs';
import { requireSurfaceCapability, resolveSurfaceProfile } from './surface-capabilities.mjs';
import { inspectProjectEnvironment } from './project-environment.mjs';
import { assessProjectEnvironmentReadiness } from './project-environment-readiness.mjs';
import { compileProjectBootstrapPlan } from './project-bootstrap-plan.mjs';

async function inspectAuthorityEnvironment({ repo, projectKey, sourceAuthority, storeRoot, surfaceProfile }) {
  const environmentSourceIdentity = sourceIdentityFromAuthority(sourceAuthority);
  const inspect = async (snapshotRepo) => {
    const environmentProfile = await inspectProjectEnvironment(snapshotRepo);
    const environmentReadiness = await assessProjectEnvironmentReadiness(environmentProfile, {
      cwd: storeRoot,
      surfaceProfile: surfaceProfile.id
    });
    const bootstrapPlan = compileProjectBootstrapPlan(environmentProfile, environmentReadiness);
    return { environmentProfile, environmentReadiness, bootstrapPlan, environmentSourceIdentity };
  };

  if (sourceAuthority.scope === 'remote-default' && !sourceAuthority.aligned) {
    const snapshotPath = path.join(storeRoot, 'project-snapshots', `${projectKey}-${randomId('authority')}`);
    return withDetachedWorktree(repo, sourceAuthority.head, snapshotPath, inspect);
  }
  return inspect(repo);
}

export class ProjectService {
  constructor({ store, operatorConfig = { defaults: {}, projects: {} }, managedProjectsRoot, surfaceProfile = 'local-stdio' }) {
    this.store = store;
    this.operatorConfig = operatorConfig;
    this.managedProjectsRoot = managedProjectsRoot ? path.resolve(managedProjectsRoot) : null;
    this.surfaceProfile = resolveSurfaceProfile(surfaceProfile);
  }

  async open({ repoPath, repoUrl, name, refreshRemote = true }) {
    const hasPath = typeof repoPath === 'string' && repoPath.trim();
    const hasUrl = typeof repoUrl === 'string' && repoUrl.trim();
    if ((hasPath && hasUrl) || (!hasPath && !hasUrl)) {
      throw Object.assign(new Error('project_open requires exactly one of repoPath or repoUrl'), { code: 'PROJECT_SOURCE_INVALID' });
    }
    if (hasPath) requireSurfaceCapability(this.surfaceProfile, 'repository', 'localPath', `Surface ${this.surfaceProfile.id} cannot open caller-local repository paths; provide repoUrl instead.`);
    if (hasUrl) {
      requireSurfaceCapability(this.surfaceProfile, 'repository', 'remoteGit');
      const normalizedRemote = normalizeRemoteRepositoryUrl(repoUrl.trim());
      if (normalizedRemote.protocol === 'file:') requireSurfaceCapability(this.surfaceProfile, 'repository', 'fileUrl', `Surface ${this.surfaceProfile.id} cannot use file:// repository URLs because they address runtime-local filesystem state.`);
    }

    let repo;
    let remoteUrl = null;
    let sourceKind = 'local';
    let managedCheckout = null;
    let defaultName = null;
    if (hasUrl) {
      if (!this.managedProjectsRoot) {
        throw Object.assign(new Error('Remote repository onboarding is unavailable without a managed project root'), { code: 'PROJECT_REMOTE_ROOT_REQUIRED' });
      }
      const acquired = await acquireRemoteRepository({
        repoUrl: repoUrl.trim(),
        managedRoot: this.managedProjectsRoot,
        refresh: refreshRemote !== false
      });
      repo = acquired.repoPath;
      remoteUrl = acquired.remoteUrl;
      sourceKind = 'managed-remote';
      defaultName = acquired.suggestedName;
      managedCheckout = {
        managed: true,
        reused: acquired.reused,
        refreshed: acquired.refresh.refreshed,
        canonicalRemoteUrl: acquired.canonicalRemoteUrl
      };
    } else {
      repo = await resolveRepository(repoPath.trim());
      const remote = await git(repo, ['config', '--get', 'remote.origin.url'], { allowFailure: true });
      remoteUrl = sanitizeStoredRemoteUrl(remote.stdout.trim());
      defaultName = path.basename(repo);
    }

    const identity = await sourceIdentity(repo);
    const sourceAuthority = await repositorySourceAuthority(repo, { observedIdentity: identity });
    const projectKey = sha256(repo).slice(0, 24);
    const {
      environmentProfile,
      environmentReadiness,
      bootstrapPlan,
      environmentSourceIdentity
    } = await inspectAuthorityEnvironment({
      repo,
      projectKey,
      sourceAuthority,
      storeRoot: this.store.root,
      surfaceProfile: this.surfaceProfile
    });
    const policy = projectPolicy(this.operatorConfig, repo, remoteUrl);
    return this.store.transaction('project_opened', (state) => {
      let project = Object.values(state.projects).find((item) => item.projectKey === projectKey);
      if (!project) {
        project = {
          id: randomId('project'),
          projectKey,
          name: name || defaultName,
          repoPath: repo,
          remoteUrl,
          sourceKind,
          managedCheckout: sourceKind === 'managed-remote',
          createdAt: nowIso(),
          updatedAt: nowIso(),
          sourceIdentity: identity,
          sourceAuthority,
          environmentSourceIdentity,
          environmentProfile,
          environmentReadiness,
          bootstrapPlan,
          validationCapabilities: policy.validationCapabilities,
          validationPolicy: policy.validationPolicy,
          runtimeFeedbackCapabilities: policy.runtimeFeedbackCapabilities,
          runtimeFeedbackPolicy: policy.runtimeFeedbackPolicy,
          workerPolicy: policy.workerPolicy,
          plannerProvider: policy.plannerProvider,
          reviewerProvider: policy.reviewerProvider,
          requireSemanticReview: policy.requireSemanticReview,
          requireValidation: policy.requireValidation,
          requiredValidationCapabilities: policy.requiredValidationCapabilities
        };
        state.projects[project.id] = project;
      } else {
        project.updatedAt = nowIso();
        project.sourceIdentity = identity;
        project.sourceAuthority = sourceAuthority;
        project.environmentSourceIdentity = environmentSourceIdentity;
        project.environmentProfile = environmentProfile;
        project.environmentReadiness = environmentReadiness;
        project.bootstrapPlan = bootstrapPlan;
        project.remoteUrl = remoteUrl;
        project.sourceKind = sourceKind;
        project.managedCheckout = sourceKind === 'managed-remote';
        project.validationCapabilities = policy.validationCapabilities;
        project.validationPolicy = policy.validationPolicy;
        project.runtimeFeedbackCapabilities = policy.runtimeFeedbackCapabilities;
        project.runtimeFeedbackPolicy = policy.runtimeFeedbackPolicy;
        project.workerPolicy = policy.workerPolicy;
        project.plannerProvider = policy.plannerProvider;
        project.reviewerProvider = policy.reviewerProvider;
        project.requireSemanticReview = policy.requireSemanticReview;
        project.requireValidation = policy.requireValidation;
        project.requiredValidationCapabilities = policy.requiredValidationCapabilities;
      }
      return managedCheckout ? { ...project, checkout: managedCheckout } : project;
    }, {
      repo,
      head: identity.head,
      dirty: identity.dirty,
      sourceKind,
      remoteUrl,
      sourceAuthority: { scope: sourceAuthority.scope, ref: sourceAuthority.ref, head: sourceAuthority.head, aligned: sourceAuthority.aligned },
      environmentSourceHead: environmentSourceIdentity.head,
      environmentContract: environmentProfile.contract,
      environmentReadiness: environmentReadiness.status,
      bootstrapPlan: bootstrapPlan.status,
      runtimeFamilies: environmentProfile.runtimeFamilies
    });
  }

  async snapshot({ projectId }) {
    const state = await this.store.read();
    const project = state.projects[projectId];
    if (!project) throw Object.assign(new Error(`Unknown project: ${projectId}`), { code: 'PROJECT_NOT_FOUND' });
    const identity = await sourceIdentity(project.repoPath);
    const sourceAuthority = await repositorySourceAuthority(project.repoPath, { observedIdentity: identity });
    const {
      environmentProfile,
      environmentReadiness,
      bootstrapPlan,
      environmentSourceIdentity
    } = await inspectAuthorityEnvironment({
      repo: project.repoPath,
      projectKey: project.projectKey,
      sourceAuthority,
      storeRoot: this.store.root,
      surfaceProfile: this.surfaceProfile
    });
    const result = await this.store.transaction('project_snapshotted', (working) => {
      const target = working.projects[projectId];
      target.sourceIdentity = identity;
      target.sourceAuthority = sourceAuthority;
      target.environmentSourceIdentity = environmentSourceIdentity;
      target.environmentProfile = environmentProfile;
      target.environmentReadiness = environmentReadiness;
      target.bootstrapPlan = bootstrapPlan;
      target.updatedAt = nowIso();
      return target;
    }, {
      projectId,
      head: identity.head,
      dirty: identity.dirty,
      sourceAuthority: { scope: sourceAuthority.scope, ref: sourceAuthority.ref, head: sourceAuthority.head, aligned: sourceAuthority.aligned },
      environmentSourceHead: environmentSourceIdentity.head,
      environmentContract: environmentProfile.contract,
      environmentReadiness: environmentReadiness.status,
      bootstrapPlan: bootstrapPlan.status,
      runtimeFamilies: environmentProfile.runtimeFamilies
    });
    return result;
  }

  async get(projectId) {
    const state = await this.store.read();
    const project = state.projects[projectId];
    if (!project) throw Object.assign(new Error(`Unknown project: ${projectId}`), { code: 'PROJECT_NOT_FOUND' });
    return project;
  }
}
