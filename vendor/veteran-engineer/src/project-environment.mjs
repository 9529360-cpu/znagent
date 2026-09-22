import fs from 'node:fs/promises';
import path from 'node:path';

export const PROJECT_ENVIRONMENT_CONTRACT = 'veteran-project-environment-v1';

const MAX_PACKAGE_JSON_BYTES = 1024 * 1024;
const MAX_SCRIPT_NAMES = 128;

const STATIC_MARKERS = Object.freeze([
  ['package.json', 'node-package'],
  ['package-lock.json', 'node-lock-npm'],
  ['npm-shrinkwrap.json', 'node-lock-npm'],
  ['pnpm-lock.yaml', 'node-lock-pnpm'],
  ['yarn.lock', 'node-lock-yarn'],
  ['bun.lock', 'node-lock-bun'],
  ['bun.lockb', 'node-lock-bun'],
  ['pnpm-workspace.yaml', 'node-workspace-pnpm'],
  ['turbo.json', 'node-workspace-turbo'],
  ['nx.json', 'node-workspace-nx'],
  ['lerna.json', 'node-workspace-lerna'],
  ['pyproject.toml', 'python-project'],
  ['requirements.txt', 'python-requirements'],
  ['requirements-dev.txt', 'python-requirements'],
  ['uv.lock', 'python-lock-uv'],
  ['poetry.lock', 'python-lock-poetry'],
  ['Pipfile', 'python-pipenv'],
  ['Pipfile.lock', 'python-lock-pipenv'],
  ['pdm.lock', 'python-lock-pdm'],
  ['go.mod', 'go-module'],
  ['go.work', 'go-workspace'],
  ['Cargo.toml', 'rust-cargo'],
  ['Cargo.lock', 'rust-lock'],
  ['pom.xml', 'jvm-maven'],
  ['build.gradle', 'jvm-gradle'],
  ['build.gradle.kts', 'jvm-gradle'],
  ['gradlew', 'jvm-gradle-wrapper'],
  ['Gemfile', 'ruby-bundler'],
  ['Gemfile.lock', 'ruby-lock-bundler'],
  ['composer.json', 'php-composer'],
  ['composer.lock', 'php-lock-composer'],
  ['Makefile', 'make'],
  ['justfile', 'just'],
  ['.nvmrc', 'version-node'],
  ['.node-version', 'version-node'],
  ['.python-version', 'version-python'],
  ['.tool-versions', 'version-asdf'],
  ['rust-toolchain', 'version-rust'],
  ['rust-toolchain.toml', 'version-rust']
]);

const VERSION_FILES = new Set(['.nvmrc', '.node-version', '.python-version']);
const START_SCRIPT_RE = /^(dev|start|serve|preview)(:|$)/;
const VALIDATION_SCRIPT_RE = /^(test($|:)|e2e($|:)|lint($|:)|typecheck($|:)|check($|:)|build($|:)|verify($|:))/;

function cleanString(value, max = 200) {
  if (typeof value !== 'string') return null;
  const text = value.trim();
  return text ? text.slice(0, max) : null;
}

async function rootEntry(root, rel, warnings) {
  const absolute = path.join(root, rel);
  try {
    const stat = await fs.lstat(absolute);
    if (stat.isSymbolicLink()) {
      warnings.push({ code: 'ENVIRONMENT_SYMLINK_IGNORED', path: rel });
      return null;
    }
    return { absolute, stat };
  } catch (error) {
    if (error?.code === 'ENOENT' || error?.code === 'ENOTDIR') return null;
    warnings.push({ code: 'ENVIRONMENT_MARKER_UNREADABLE', path: rel });
    return null;
  }
}

async function readSmallText(root, rel, warnings, maxBytes = 16 * 1024) {
  const entry = await rootEntry(root, rel, warnings);
  if (!entry || !entry.stat.isFile()) return null;
  if (entry.stat.size > maxBytes) {
    warnings.push({ code: 'ENVIRONMENT_MARKER_TOO_LARGE', path: rel });
    return null;
  }
  try {
    return await fs.readFile(entry.absolute, 'utf8');
  } catch {
    warnings.push({ code: 'ENVIRONMENT_MARKER_UNREADABLE', path: rel });
    return null;
  }
}

function nodePackageManager(packageJson, manifests) {
  const lockManagers = [];
  const lockMap = new Map([
    ['node-lock-pnpm', 'pnpm'],
    ['node-lock-yarn', 'yarn'],
    ['node-lock-npm', 'npm'],
    ['node-lock-bun', 'bun']
  ]);
  for (const item of manifests) {
    const manager = lockMap.get(item.kind);
    if (manager && !lockManagers.includes(manager)) lockManagers.push(manager);
  }
  let declared = null;
  if (packageJson) {
    const raw = cleanString(packageJson.packageManager, 160);
    const match = raw?.match(/^(npm|pnpm|yarn|bun)@(.+)$/);
    if (match) declared = { name: match[1], version: match[2].slice(0, 120), source: 'package.json#packageManager' };
  }
  const candidateNames = [...new Set([...(declared ? [declared.name] : []), ...lockManagers])];
  const selected = candidateNames.length === 1 ? candidateNames[0] : null;
  return {
    selected,
    declared,
    lockfileCandidates: lockManagers,
    ambiguous: candidateNames.length > 1
  };
}

function inferFamilies(manifests) {
  const kinds = new Set(manifests.map((item) => item.kind));
  const families = [];
  if ([...kinds].some((kind) => kind.startsWith('node-'))) families.push('node');
  if ([...kinds].some((kind) => kind.startsWith('python-'))) families.push('python');
  if ([...kinds].some((kind) => kind.startsWith('go-'))) families.push('go');
  if ([...kinds].some((kind) => kind.startsWith('rust-'))) families.push('rust');
  if ([...kinds].some((kind) => kind.startsWith('jvm-'))) families.push('jvm');
  if ([...kinds].some((kind) => kind.startsWith('ruby-'))) families.push('ruby');
  if ([...kinds].some((kind) => kind.startsWith('php-'))) families.push('php');
  return families;
}

function pythonManagers(manifests) {
  const kinds = new Set(manifests.map((item) => item.kind));
  const managers = [];
  if (kinds.has('python-lock-uv')) managers.push('uv');
  if (kinds.has('python-lock-poetry')) managers.push('poetry');
  if (kinds.has('python-lock-pipenv') || kinds.has('python-pipenv')) managers.push('pipenv');
  if (kinds.has('python-lock-pdm')) managers.push('pdm');
  if (kinds.has('python-requirements')) managers.push('pip');
  return managers;
}

function jvmBuildTools(manifests) {
  const kinds = new Set(manifests.map((item) => item.kind));
  const tools = [];
  if (kinds.has('jvm-maven')) tools.push('maven');
  if (kinds.has('jvm-gradle') || kinds.has('jvm-gradle-wrapper')) tools.push('gradle');
  return tools;
}

function nodeDetails(packageJson) {
  if (!packageJson) return null;
  const scriptNames = packageJson.scripts && typeof packageJson.scripts === 'object' && !Array.isArray(packageJson.scripts)
    ? Object.keys(packageJson.scripts).filter((name) => typeof name === 'string' && name.trim()).sort().slice(0, MAX_SCRIPT_NAMES)
    : [];
  const engines = {};
  if (packageJson.engines && typeof packageJson.engines === 'object' && !Array.isArray(packageJson.engines)) {
    for (const key of ['node', 'npm', 'pnpm', 'yarn', 'bun']) {
      const value = cleanString(packageJson.engines[key], 120);
      if (value) engines[key] = value;
    }
  }
  const workspaces = Array.isArray(packageJson.workspaces)
    ? packageJson.workspaces.length > 0
    : Boolean(packageJson.workspaces && typeof packageJson.workspaces === 'object');
  return {
    engines,
    scriptNames,
    startScriptNames: scriptNames.filter((name) => START_SCRIPT_RE.test(name)),
    validationScriptNames: scriptNames.filter((name) => VALIDATION_SCRIPT_RE.test(name)),
    workspaces
  };
}

export async function inspectProjectEnvironment(repoPath) {
  const root = await fs.realpath(repoPath);
  const warnings = [];
  const manifests = [];
  const versionHints = [];

  for (const [rel, kind] of STATIC_MARKERS) {
    const entry = await rootEntry(root, rel, warnings);
    if (!entry || !entry.stat.isFile()) continue;
    manifests.push({ path: rel, kind });
    if (VERSION_FILES.has(rel)) {
      const content = await readSmallText(root, rel, warnings, 4096);
      const value = cleanString(content, 160);
      if (value) versionHints.push({ path: rel, value });
    }
  }

  let rootNames = [];
  try {
    rootNames = await fs.readdir(root);
  } catch {
    warnings.push({ code: 'ENVIRONMENT_ROOT_UNREADABLE', path: '.' });
  }
  const dockerfiles = [];
  const composeFiles = [];
  const envTemplates = [];
  for (const name of rootNames.sort()) {
    if (name === 'Dockerfile' || /^Dockerfile[.-][A-Za-z0-9._-]+$/.test(name)) {
      const entry = await rootEntry(root, name, warnings);
      if (entry?.stat.isFile()) dockerfiles.push(name);
    }
    if (/^(?:docker-)?compose(?:[.-][A-Za-z0-9._-]+)?\.ya?ml$/i.test(name)) {
      const entry = await rootEntry(root, name, warnings);
      if (entry?.stat.isFile()) composeFiles.push(name);
    }
    if (/^\.env\.(?:example|sample|template)(?:\.[A-Za-z0-9._-]+)?$/i.test(name)) {
      const entry = await rootEntry(root, name, warnings);
      if (entry?.stat.isFile()) envTemplates.push(name);
    }
  }

  const devcontainerEntry = await rootEntry(root, '.devcontainer/devcontainer.json', warnings);
  const devcontainer = Boolean(devcontainerEntry?.stat.isFile());
  if (devcontainer) manifests.push({ path: '.devcontainer/devcontainer.json', kind: 'devcontainer' });
  for (const file of dockerfiles) manifests.push({ path: file, kind: 'container-dockerfile' });
  for (const file of composeFiles) manifests.push({ path: file, kind: 'container-compose' });
  for (const file of envTemplates) manifests.push({ path: file, kind: 'environment-template' });

  let packageJson = null;
  const packageEntry = await rootEntry(root, 'package.json', warnings);
  if (packageEntry?.stat.isFile()) {
    if (packageEntry.stat.size > MAX_PACKAGE_JSON_BYTES) {
      warnings.push({ code: 'ENVIRONMENT_PACKAGE_JSON_TOO_LARGE', path: 'package.json' });
    } else {
      try {
        packageJson = JSON.parse(await fs.readFile(packageEntry.absolute, 'utf8'));
        if (!packageJson || typeof packageJson !== 'object' || Array.isArray(packageJson)) {
          packageJson = null;
          warnings.push({ code: 'ENVIRONMENT_PACKAGE_JSON_INVALID', path: 'package.json' });
        }
      } catch {
        warnings.push({ code: 'ENVIRONMENT_PACKAGE_JSON_INVALID', path: 'package.json' });
      }
    }
  }

  const monorepoMarkers = manifests
    .filter((item) => ['node-workspace-pnpm', 'node-workspace-turbo', 'node-workspace-nx', 'node-workspace-lerna', 'go-workspace'].includes(item.kind))
    .map((item) => item.path);
  const node = nodeDetails(packageJson);
  if (node?.workspaces && !monorepoMarkers.includes('package.json#workspaces')) monorepoMarkers.push('package.json#workspaces');

  manifests.sort((a, b) => a.path.localeCompare(b.path) || a.kind.localeCompare(b.kind));
  versionHints.sort((a, b) => a.path.localeCompare(b.path));
  const uniqueWarnings = [...new Map(warnings.map((item) => [`${item.code}:${item.path}`, item])).values()];

  return {
    contract: PROJECT_ENVIRONMENT_CONTRACT,
    scope: 'repository-root',
    runtimeFamilies: inferFamilies(manifests),
    manifests,
    packageManagers: {
      node: nodePackageManager(packageJson, manifests),
      python: pythonManagers(manifests),
      jvmBuildTools: jvmBuildTools(manifests)
    },
    node,
    container: {
      dockerfiles,
      composeFiles,
      devcontainer
    },
    monorepo: {
      detected: monorepoMarkers.length > 0,
      markers: monorepoMarkers.sort()
    },
    envTemplates,
    versionHints,
    warnings: uniqueWarnings
  };
}
