export const PROJECT_BOOTSTRAP_PLAN_CONTRACT = 'veteran-project-bootstrap-plan-v1';

function hasManifest(profile, kind) {
  return (profile?.manifests || []).some((item) => item.kind === kind);
}

function manifestPath(profile, kind, preferred = null) {
  const items = (profile?.manifests || []).filter((item) => item.kind === kind);
  if (preferred) {
    const exact = items.find((item) => item.path === preferred);
    if (exact) return exact.path;
  }
  return items[0]?.path || null;
}

function readinessCheck(readiness, id) {
  return (readiness?.checks || []).find((item) => item.id === id) || null;
}

function versionMajor(value) {
  const match = String(value || '').match(/(?:^|[^0-9])(\d+)/);
  return match ? Number(match[1]) : null;
}

function issue(code, owner, message, severity = 'warning') {
  return { code, owner, severity, message };
}

function installStep({ id, owner, command, reproducible, reason, lifecycleCode = true, network = true, manualOnly = false }) {
  return {
    id,
    kind: 'dependency-bootstrap',
    owner,
    command,
    cwd: '.',
    network,
    reproducible,
    executesThirdPartyCode: lifecycleCode,
    requiresAuthorization: true,
    executionPolicy: manualOnly ? 'manual-only' : 'approval-required',
    reason
  };
}

function nodePlan(profile, readiness, steps, issues) {
  if (!(profile?.runtimeFamilies || []).includes('node')) return;
  const managerInfo = profile?.packageManagers?.node;
  if (managerInfo?.ambiguous) {
    issues.push(issue('BOOTSTRAP_PACKAGE_MANAGER_AMBIGUOUS', 'node', 'Multiple Node package managers are authoritative; no install command was selected.', 'blocker'));
    return;
  }
  const manager = managerInfo?.selected;
  if (!manager) {
    issues.push(issue('BOOTSTRAP_PACKAGE_MANAGER_UNRESOLVED', 'node', 'Node project has no singular package-manager authority; no install command was selected.'));
    return;
  }
  const lockKind = `node-lock-${manager}`;
  const hasLock = hasManifest(profile, lockKind);
  if (manager === 'npm') {
    if (hasLock) steps.push(installStep({ id: 'node:npm', owner: 'node', command: ['npm', 'ci'], reproducible: true, reason: 'npm lockfile present; prefer clean lockfile installation.' }));
    else {
      steps.push(installStep({ id: 'node:npm', owner: 'node', command: ['npm', 'install'], reproducible: false, manualOnly: true, reason: 'No npm lockfile detected; installation may resolve and write dependency metadata.' }));
      issues.push(issue('BOOTSTRAP_LOCKFILE_MISSING', 'node', 'npm project has no lockfile; bootstrap is non-reproducible and remains manual-only.'));
    }
    return;
  }
  if (manager === 'pnpm') {
    if (hasLock) steps.push(installStep({ id: 'node:pnpm', owner: 'node', command: ['pnpm', 'install', '--frozen-lockfile'], reproducible: true, reason: 'pnpm lockfile present; freeze lockfile resolution.' }));
    else {
      steps.push(installStep({ id: 'node:pnpm', owner: 'node', command: ['pnpm', 'install'], reproducible: false, manualOnly: true, reason: 'No pnpm lockfile detected.' }));
      issues.push(issue('BOOTSTRAP_LOCKFILE_MISSING', 'node', 'pnpm project has no lockfile; bootstrap is non-reproducible and remains manual-only.'));
    }
    return;
  }
  if (manager === 'yarn') {
    if (!hasLock) {
      steps.push(installStep({ id: 'node:yarn', owner: 'node', command: ['yarn', 'install'], reproducible: false, manualOnly: true, reason: 'No Yarn lockfile detected.' }));
      issues.push(issue('BOOTSTRAP_LOCKFILE_MISSING', 'node', 'Yarn project has no lockfile; bootstrap is non-reproducible and remains manual-only.'));
      return;
    }
    const actualMajor = versionMajor(readinessCheck(readiness, 'node-package-manager:yarn')?.version);
    const declaredMajor = versionMajor(managerInfo?.declared?.version);
    const major = actualMajor ?? declaredMajor;
    if (major === null) {
      issues.push(issue('BOOTSTRAP_YARN_GENERATION_UNVERIFIED', 'node', 'Yarn lockfile exists but Yarn generation is unknown; Veteran will not guess between classic and Berry install flags.'));
      return;
    }
    const command = major >= 2 ? ['yarn', 'install', '--immutable'] : ['yarn', 'install', '--frozen-lockfile'];
    steps.push(installStep({ id: 'node:yarn', owner: 'node', command, reproducible: true, reason: `Yarn ${major >= 2 ? 'Berry' : 'Classic'} lockfile installation selected from observed/declared version evidence.` }));
    return;
  }
  if (manager === 'bun') {
    if (hasLock) steps.push(installStep({ id: 'node:bun', owner: 'node', command: ['bun', 'install', '--frozen-lockfile'], reproducible: true, reason: 'Bun lockfile present; freeze dependency resolution.' }));
    else {
      steps.push(installStep({ id: 'node:bun', owner: 'node', command: ['bun', 'install'], reproducible: false, manualOnly: true, reason: 'No Bun lockfile detected.' }));
      issues.push(issue('BOOTSTRAP_LOCKFILE_MISSING', 'node', 'Bun project has no lockfile; bootstrap is non-reproducible and remains manual-only.'));
    }
    return;
  }
  issues.push(issue('BOOTSTRAP_STRATEGY_UNSUPPORTED', 'node', `No bounded bootstrap strategy is defined for Node package manager ${manager}.`));
}

function pythonPlan(profile, steps, issues) {
  if (!(profile?.runtimeFamilies || []).includes('python')) return;
  const managers = profile?.packageManagers?.python || [];
  if (managers.includes('uv') && hasManifest(profile, 'python-lock-uv')) {
    steps.push(installStep({ id: 'python:uv', owner: 'python', command: ['uv', 'sync', '--frozen'], reproducible: true, reason: 'uv lockfile present.' }));
    return;
  }
  if (managers.includes('poetry') && hasManifest(profile, 'python-lock-poetry')) {
    steps.push(installStep({ id: 'python:poetry', owner: 'python', command: ['poetry', 'install', '--no-interaction'], reproducible: true, reason: 'Poetry lockfile present; install from locked dependency graph.' }));
    return;
  }
  if (managers.includes('pipenv') && hasManifest(profile, 'python-lock-pipenv')) {
    steps.push(installStep({ id: 'python:pipenv', owner: 'python', command: ['pipenv', 'sync'], reproducible: true, reason: 'Pipfile.lock present.' }));
    return;
  }
  if (managers.includes('pip')) {
    const requirements = manifestPath(profile, 'python-requirements', 'requirements.txt');
    if (requirements) {
      issues.push(issue('BOOTSTRAP_PYTHON_INTERPRETER_INVOCATION_UNRESOLVED', 'python', `requirements file ${requirements} is present, but readiness intentionally does not persist an interpreter command/path; pip bootstrap remains manual.`));
      return;
    }
  }
  if (managers.length) issues.push(issue('BOOTSTRAP_STRATEGY_UNSUPPORTED', 'python', `No bounded reproducible bootstrap strategy was selected for Python manager(s): ${managers.join(', ')}.`));
}

function rustPlan(profile, steps, issues) {
  if (!(profile?.runtimeFamilies || []).includes('rust')) return;
  if (hasManifest(profile, 'rust-lock')) {
    steps.push(installStep({ id: 'rust:cargo', owner: 'rust', command: ['cargo', 'fetch', '--locked'], reproducible: true, lifecycleCode: false, reason: 'Cargo.lock present; fetch locked crates without building the project.' }));
  } else {
    steps.push(installStep({ id: 'rust:cargo', owner: 'rust', command: ['cargo', 'fetch'], reproducible: false, lifecycleCode: false, manualOnly: true, reason: 'Cargo.lock not detected; dependency resolution may change.' }));
    issues.push(issue('BOOTSTRAP_LOCKFILE_MISSING', 'rust', 'Cargo.lock not detected; cargo bootstrap remains manual-only.'));
  }
}

function goPlan(profile, steps, issues) {
  if (!(profile?.runtimeFamilies || []).includes('go')) return;
  if (hasManifest(profile, 'go-module')) {
    steps.push(installStep({ id: 'go:modules', owner: 'go', command: ['go', 'mod', 'download'], reproducible: false, lifecycleCode: false, manualOnly: true, reason: 'go.mod is present, but v1 environment evidence does not yet prove go.sum completeness; keep fetch manual-only.' }));
    issues.push(issue('BOOTSTRAP_CHECKSUM_EVIDENCE_UNVERIFIED', 'go', 'go.sum authority is not part of the current environment profile, so automatic execution is not enabled.'));
  }
}

function rubyPlan(profile, steps) {
  if (!(profile?.runtimeFamilies || []).includes('ruby')) return;
  if (hasManifest(profile, 'ruby-lock-bundler')) {
    steps.push(installStep({ id: 'ruby:bundle', owner: 'ruby', command: ['bundle', 'install'], reproducible: true, reason: 'Gemfile.lock present; Bundler will resolve from the lockfile.' }));
  }
}

function phpPlan(profile, steps) {
  if (!(profile?.runtimeFamilies || []).includes('php')) return;
  if (hasManifest(profile, 'php-lock-composer')) {
    steps.push(installStep({ id: 'php:composer', owner: 'php', command: ['composer', 'install', '--no-interaction', '--no-progress'], reproducible: true, reason: 'composer.lock present; install locked dependencies.' }));
  }
}

function jvmPlan(profile, issues) {
  if (!(profile?.runtimeFamilies || []).includes('jvm')) return;
  issues.push(issue('BOOTSTRAP_STRATEGY_UNSUPPORTED', 'jvm', 'JVM dependency/bootstrap behavior is build-tool and wrapper-version sensitive; v1 plan records it as manual instead of guessing.'));
}

export function compileProjectBootstrapPlan(profile, readiness) {
  const steps = [];
  const issues = [];
  nodePlan(profile, readiness, steps, issues);
  pythonPlan(profile, steps, issues);
  goPlan(profile, steps, issues);
  rustPlan(profile, steps, issues);
  jvmPlan(profile, issues);
  rubyPlan(profile, steps);
  phpPlan(profile, steps);

  const readinessBlocked = readiness?.usable === false || readiness?.status === 'blocked';
  if (readinessBlocked) {
    issues.unshift(issue('BOOTSTRAP_HOST_NOT_READY', 'host', 'Current execution host does not satisfy required repository tools; bootstrap execution is blocked.', 'blocker'));
  }
  const manualOnly = steps.some((step) => step.executionPolicy === 'manual-only') || issues.some((item) => item.severity === 'warning');
  const blockerCount = issues.filter((item) => item.severity === 'blocker').length;
  const status = blockerCount > 0
    ? 'blocked'
    : steps.length === 0
      ? (issues.length ? 'manual' : 'not-needed')
      : manualOnly
        ? 'manual'
        : 'planned';
  return {
    contract: PROJECT_BOOTSTRAP_PLAN_CONTRACT,
    status,
    autoExecute: false,
    requiresAuthorization: steps.length > 0,
    steps,
    issues,
    summary: {
      steps: steps.length,
      reproducibleSteps: steps.filter((step) => step.reproducible).length,
      blockers: blockerCount,
      warnings: issues.filter((item) => item.severity === 'warning').length
    }
  };
}
