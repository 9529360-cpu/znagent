import { runProcess } from './git.mjs';

export const PROJECT_ENVIRONMENT_READINESS_CONTRACT = 'veteran-project-environment-readiness-v1';

const PROBE_TIMEOUT_MS = 2_000;
const MAX_VERSION_TEXT = 120;

function compactVersion(value) {
  if (!value) return null;
  const match = String(value).match(/(?:^|[^0-9])(\d+)(?:\.(\d+))?(?:\.(\d+))?/);
  if (!match) return null;
  return [match[1], match[2], match[3]].filter((part) => part !== undefined).join('.').slice(0, MAX_VERSION_TEXT);
}

function versionTuple(value) {
  const compact = compactVersion(value);
  if (!compact) return null;
  const parts = compact.split('.').map((part) => Number(part));
  while (parts.length < 3) parts.push(0);
  return parts.slice(0, 3);
}

function compareVersion(left, right) {
  for (let i = 0; i < 3; i += 1) {
    if (left[i] < right[i]) return -1;
    if (left[i] > right[i]) return 1;
  }
  return 0;
}

function evaluateClause(actual, clause) {
  const trimmed = clause.trim();
  if (!trimmed) return { supported: false, matches: null };
  const wildcard = trimmed.match(/^v?(\d+)(?:\.(\d+))?\.(?:x|\*)$/i) || trimmed.match(/^v?(\d+)\.(?:x|\*)$/i);
  if (wildcard) {
    const major = Number(wildcard[1]);
    const minor = wildcard[2] === undefined ? null : Number(wildcard[2]);
    return { supported: true, matches: actual[0] === major && (minor === null || actual[1] === minor) };
  }
  const match = trimmed.match(/^(>=|<=|>|<|\^|~)?\s*v?(\d+)(?:\.(\d+))?(?:\.(\d+))?$/i);
  if (!match) return { supported: false, matches: null };
  const op = match[1] || '=';
  const expected = [Number(match[2]), Number(match[3] ?? 0), Number(match[4] ?? 0)];
  const specifiedParts = [match[2], match[3], match[4]].filter((part) => part !== undefined).length;
  const cmp = compareVersion(actual, expected);
  if (op === '>=') return { supported: true, matches: cmp >= 0 };
  if (op === '<=') return { supported: true, matches: cmp <= 0 };
  if (op === '>') return { supported: true, matches: cmp > 0 };
  if (op === '<') return { supported: true, matches: cmp < 0 };
  if (op === '^') {
    let upper;
    if (expected[0] > 0 || specifiedParts === 1) upper = [expected[0] + 1, 0, 0];
    else if (expected[1] > 0 || specifiedParts === 2) upper = [0, expected[1] + 1, 0];
    else upper = [0, 0, expected[2] + 1];
    return { supported: true, matches: cmp >= 0 && compareVersion(actual, upper) < 0 };
  }
  if (op === '~') {
    const upper = specifiedParts === 1
      ? [expected[0] + 1, 0, 0]
      : [expected[0], expected[1] + 1, 0];
    return { supported: true, matches: cmp >= 0 && compareVersion(actual, upper) < 0 };
  }
  return {
    supported: true,
    matches: specifiedParts === 1
      ? actual[0] === expected[0]
      : specifiedParts === 2
        ? actual[0] === expected[0] && actual[1] === expected[1]
        : cmp === 0
  };
}

export function evaluateVersionRequirement(actualVersion, requirement) {
  const actual = versionTuple(actualVersion);
  const raw = typeof requirement === 'string' ? requirement.trim() : '';
  if (!actual || !raw || raw.includes('||') || /\blts\b|latest|node|stable/i.test(raw)) {
    return { supported: false, matches: null, actual: compactVersion(actualVersion), requirement: raw || null };
  }
  const clauses = raw.split(/\s+/).filter(Boolean);
  let supported = true;
  let matches = true;
  for (const clause of clauses) {
    const result = evaluateClause(actual, clause);
    if (!result.supported) supported = false;
    if (result.supported && !result.matches) matches = false;
  }
  return { supported, matches: supported ? matches : null, actual: compactVersion(actualVersion), requirement: raw };
}

function commandName(name) {
  if (process.platform !== 'win32') return name;
  if (['npm', 'pnpm', 'yarn', 'mvn', 'bundle', 'composer'].includes(name)) return `${name}.cmd`;
  if (name === 'gradle') return 'gradle.bat';
  return name;
}

async function defaultProbe(spec, { cwd }) {
  try {
    const result = await runProcess(spec.command, spec.args, { cwd, timeoutMs: spec.timeoutMs || PROBE_TIMEOUT_MS, allowFailure: true });
    const text = `${result.stdout || ''}\n${result.stderr || ''}`;
    return {
      available: result.code === 0,
      exitCode: result.code,
      version: compactVersion(text),
      reason: result.code === 0 ? 'ok' : 'nonzero-exit'
    };
  } catch (error) {
    return {
      available: false,
      exitCode: null,
      version: null,
      reason: error?.code === 'ENOENT' ? 'not-found' : 'probe-error'
    };
  }
}

function nodeRequirement(profile) {
  const hints = Array.isArray(profile?.versionHints) ? profile.versionHints : [];
  const preferred = hints.find((item) => item.path === '.nvmrc') || hints.find((item) => item.path === '.node-version');
  if (preferred?.value) return { requirement: preferred.value, source: preferred.path };
  if (profile?.node?.engines?.node) return { requirement: profile.node.engines.node, source: 'package.json#engines.node' };
  return null;
}

function pythonRequirement(profile) {
  const hint = (profile?.versionHints || []).find((item) => item.path === '.python-version');
  return hint?.value ? { requirement: hint.value, source: hint.path } : null;
}

function hasManifest(profile, kind) {
  return (profile?.manifests || []).some((item) => item.kind === kind);
}

function issue(code, tool, message, severity = 'blocker') {
  return { code, tool, severity, message };
}

function checkRecord(spec, probed, versionEvaluation = null) {
  return {
    id: spec.id,
    tool: spec.tool,
    required: spec.required !== false,
    available: probed.available === true,
    version: probed.version || null,
    requirement: spec.requirement || null,
    requirementSource: spec.requirementSource || null,
    compatibility: versionEvaluation
      ? versionEvaluation.supported
        ? (versionEvaluation.matches ? 'match' : 'mismatch')
        : 'unverified'
      : null,
    reason: probed.reason || null,
    exitCode: Number.isInteger(probed.exitCode) ? probed.exitCode : null
  };
}

export async function assessProjectEnvironmentReadiness(profile, { cwd = process.cwd(), probe = defaultProbe, surfaceProfile = null } = {}) {
  const checks = [];
  const issues = [];

  const execute = async (spec) => {
    const probed = await probe(spec, { cwd });
    const versionEvaluation = spec.requirement && probed.available
      ? evaluateVersionRequirement(probed.version, spec.requirement)
      : null;
    const record = checkRecord(spec, probed, versionEvaluation);
    checks.push(record);
    if (!probed.available) {
      issues.push(issue('HOST_TOOL_MISSING', spec.tool, `${spec.tool} is not available on the current execution host.`, spec.required === false ? 'warning' : 'blocker'));
    } else if (versionEvaluation && versionEvaluation.supported && !versionEvaluation.matches) {
      issues.push(issue('HOST_TOOL_VERSION_MISMATCH', spec.tool, `${spec.tool} does not satisfy the repository requirement.`, spec.required === false ? 'warning' : 'blocker'));
    } else if (versionEvaluation && !versionEvaluation.supported) {
      issues.push(issue('HOST_TOOL_REQUIREMENT_UNVERIFIED', spec.tool, `${spec.tool} is available but the declared version requirement is outside the bounded evaluator.`, 'warning'));
    }
    return record;
  };

  const families = new Set(profile?.runtimeFamilies || []);
  if (families.has('node')) {
    const requirement = nodeRequirement(profile);
    await execute({ id: 'node', tool: 'node', command: process.execPath, args: ['--version'], required: true, requirement: requirement?.requirement || null, requirementSource: requirement?.source || null });
    const nodeManager = profile?.packageManagers?.node;
    if (nodeManager?.ambiguous) {
      issues.push(issue('HOST_PACKAGE_MANAGER_AMBIGUOUS', 'node-package-manager', 'Repository evidence names multiple Node package managers; Veteran will not guess which one owns installs/scripts.'));
    } else if (nodeManager?.selected) {
      const manager = nodeManager.selected;
      const declared = nodeManager.declared?.name === manager ? nodeManager.declared.version : null;
      const engineRequirement = profile?.node?.engines?.[manager] || null;
      const managerRequirement = declared || engineRequirement;
      const managerRequirementSource = declared ? 'package.json#packageManager' : engineRequirement ? `package.json#engines.${manager}` : null;
      await execute({ id: `node-package-manager:${manager}`, tool: manager, command: commandName(manager), args: ['--version'], required: true, requirement: managerRequirement || null, requirementSource: managerRequirementSource });
    } else if (profile?.node) {
      issues.push(issue('HOST_PACKAGE_MANAGER_UNRESOLVED', 'node-package-manager', 'Node project detected without singular package-manager authority; installation commands remain unselected.', 'warning'));
    }
  }

  if (families.has('python')) {
    const requirement = pythonRequirement(profile);
    let pythonRecord = null;
    let pythonCommand = null;
    let firstAvailable = null;
    for (const name of ['python3', 'python']) {
      const probed = await probe({ id: 'python', tool: 'python', command: name, args: ['--version'], timeoutMs: PROBE_TIMEOUT_MS, required: true }, { cwd });
      if (!probed.available) continue;
      const evaluation = requirement ? evaluateVersionRequirement(probed.version, requirement.requirement) : null;
      const candidate = { name, probed, evaluation };
      firstAvailable ||= candidate;
      if (!requirement || (evaluation?.supported && evaluation.matches)) {
        firstAvailable = candidate;
        break;
      }
      if (evaluation && !evaluation.supported && evaluation.actual) break;
    }
    if (firstAvailable) {
      pythonCommand = firstAvailable.name;
      pythonRecord = checkRecord(
        { id: 'python', tool: 'python', required: true, requirement: requirement?.requirement || null, requirementSource: requirement?.source || null },
        firstAvailable.probed,
        firstAvailable.evaluation
      );
      checks.push(pythonRecord);
      if (firstAvailable.evaluation?.supported && !firstAvailable.evaluation.matches) issues.push(issue('HOST_TOOL_VERSION_MISMATCH', 'python', 'python does not satisfy the repository requirement.'));
      else if (firstAvailable.evaluation && !firstAvailable.evaluation.supported) issues.push(issue('HOST_TOOL_REQUIREMENT_UNVERIFIED', 'python', 'python is available but the declared version requirement is outside the bounded evaluator.', 'warning'));
    }
    if (!pythonRecord) {
      checks.push({ id: 'python', tool: 'python', required: true, available: false, version: null, requirement: requirement?.requirement || null, requirementSource: requirement?.source || null, compatibility: null, reason: 'not-found', exitCode: null });
      issues.push(issue('HOST_TOOL_MISSING', 'python', 'python is not available on the current execution host.'));
    }
    for (const manager of profile?.packageManagers?.python || []) {
      if (manager === 'pip') {
        if (pythonCommand) await execute({ id: 'python-package-manager:pip', tool: 'pip', command: pythonCommand, args: ['-m', 'pip', '--version'], required: true });
        continue;
      }
      await execute({ id: `python-package-manager:${manager}`, tool: manager, command: commandName(manager), args: ['--version'], required: true });
    }
  }

  if (families.has('go')) await execute({ id: 'go', tool: 'go', command: 'go', args: ['version'], required: true });
  if (families.has('rust')) {
    await execute({ id: 'rustc', tool: 'rustc', command: 'rustc', args: ['--version'], required: true });
    await execute({ id: 'cargo', tool: 'cargo', command: 'cargo', args: ['--version'], required: true });
  }
  if (families.has('jvm')) {
    await execute({ id: 'java', tool: 'java', command: 'java', args: ['-version'], required: true });
    for (const buildTool of profile?.packageManagers?.jvmBuildTools || []) {
      const hasGradleWrapper = buildTool === 'gradle' && hasManifest(profile, 'jvm-gradle-wrapper');
      if (hasGradleWrapper) {
        checks.push({ id: 'jvm-build:gradle', tool: 'gradle', required: true, available: true, version: null, requirement: null, requirementSource: 'gradlew', compatibility: null, reason: 'repository-wrapper', exitCode: null });
      } else {
        await execute({ id: `jvm-build:${buildTool}`, tool: buildTool, command: commandName(buildTool === 'maven' ? 'mvn' : buildTool), args: ['--version'], required: true });
      }
    }
  }
  if (families.has('ruby')) {
    await execute({ id: 'ruby', tool: 'ruby', command: 'ruby', args: ['--version'], required: true });
    if (hasManifest(profile, 'ruby-bundler') || hasManifest(profile, 'ruby-lock-bundler')) {
      await execute({ id: 'ruby-bundler', tool: 'bundle', command: commandName('bundle'), args: ['--version'], required: true });
    }
  }
  if (families.has('php')) {
    await execute({ id: 'php', tool: 'php', command: 'php', args: ['--version'], required: true });
    if (hasManifest(profile, 'php-composer') || hasManifest(profile, 'php-lock-composer')) {
      await execute({ id: 'php-composer', tool: 'composer', command: commandName('composer'), args: ['--version'], required: true });
    }
  }

  const hasContainerEvidence = Boolean(profile?.container?.dockerfiles?.length || profile?.container?.composeFiles?.length || profile?.container?.devcontainer);
  if (hasContainerEvidence) {
    const docker = await execute({ id: 'docker-cli', tool: 'docker', command: 'docker', args: ['--version'], required: false });
    if (docker.available && (profile?.container?.composeFiles?.length || profile?.container?.devcontainer)) {
      await execute({ id: 'docker-daemon', tool: 'docker-daemon', command: 'docker', args: ['info', '--format', '{{.ServerVersion}}'], required: false, timeoutMs: 3_000 });
    }
  }

  checks.sort((a, b) => a.id.localeCompare(b.id));
  const blockerCount = issues.filter((item) => item.severity === 'blocker').length;
  const warningCount = issues.filter((item) => item.severity === 'warning').length;
  return {
    contract: PROJECT_ENVIRONMENT_READINESS_CONTRACT,
    surfaceProfile,
    status: blockerCount > 0 ? 'blocked' : warningCount > 0 ? 'degraded' : 'ready',
    usable: blockerCount === 0,
    verified: blockerCount === 0 && warningCount === 0,
    checks,
    issues,
    summary: { blockers: blockerCount, warnings: warningCount, checks: checks.length }
  };
}
