import {
  loadOperatorConfig,
  projectPolicy as coreProjectPolicy
} from './operator-config-core.mjs';

export { loadOperatorConfig };

function configuredWorkerMaxWorkers(operatorConfig, repoPath, remoteUrl) {
  const config = operatorConfig && typeof operatorConfig === 'object' && !Array.isArray(operatorConfig)
    ? operatorConfig
    : {};
  const defaults = config.defaults && typeof config.defaults === 'object' ? config.defaults : {};
  const projects = config.projects && typeof config.projects === 'object' ? config.projects : {};
  const normalizedRepoPath = typeof repoPath === 'string' ? repoPath.replaceAll('\\', '/') : repoPath;
  const specific = projects[repoPath] || projects[normalizedRepoPath] || (remoteUrl ? projects[remoteUrl] : null) || {};
  return specific.workerPolicy?.maxWorkers ?? defaults.workerPolicy?.maxWorkers;
}

export function projectPolicy(operatorConfig, repoPath, remoteUrl = null) {
  const policy = coreProjectPolicy(operatorConfig, repoPath, remoteUrl);
  if (configuredWorkerMaxWorkers(operatorConfig, repoPath, remoteUrl) === undefined) {
    policy.workerPolicy.maxWorkers = 4;
  }
  return policy;
}
