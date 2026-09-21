import path from 'node:path';
import fs from 'node:fs/promises';
import { HOST_ADAPTER_API_VERSION } from '../../constants.mjs';
import { pathExists } from '../../util.mjs';
import { writeJsonAtomic, readJson, stableObjectHash } from '../util.mjs';
import { requireSurfaceCapability, resolveSurfaceProfile } from '../../surface-capabilities.mjs';

function recordedBinding(context) {
  return context.previousBinding?.binding || context.previousBinding || null;
}

function selectedSurfaceProfile(context) {
  const recorded = recordedBinding(context)?.surfaceProfile || null;
  const profile = resolveSurfaceProfile(context.options.surfaceProfile || recorded || 'local-stdio');
  return requireSurfaceCapability(
    profile,
    'transport',
    'stdioMcp',
    `Generic MCP descriptors require a stdio-capable surface; ${profile.id} does not provide transport.stdioMcp`
  ).id;
}

function descriptorFor(context) {
  const surfaceProfile = selectedSurfaceProfile(context);
  return {
    mcpServers: {
      'veteran-engineer': {
        command: 'node',
        args: [path.join(context.runtimeRoot, 'mcp', 'server.mjs')],
        env: { VETERAN_ENGINEER_STATE_DIR: context.runtimeStateRoot, VETERAN_ENGINEER_SURFACE_PROFILE: surfaceProfile }
      }
    }
  };
}

function descriptorPath(context) {
  const recorded = recordedBinding(context)?.descriptorPath || null;
  return path.resolve(context.options.descriptorPath || recorded || path.join(context.installerRoot, 'veteran-engineer.mcp.json'));
}

function bindingOwnsPath(context, file) {
  const recorded = recordedBinding(context)?.descriptorPath;
  return Boolean(recorded && path.resolve(recorded) === path.resolve(file));
}

async function readDescriptorForOwnership(file) {
  try {
    return await readJson(file, null);
  } catch {
    return null;
  }
}

function descriptorDriftError(file, reason) {
  const error = new Error(`Generic MCP descriptor drift must be resolved before repair: ${file}`);
  error.code = 'HOST_BINDING_DRIFT';
  error.details = { descriptorPath: file, reason };
  return error;
}

export default {
  apiVersion: HOST_ADAPTER_API_VERSION,
  id: 'generic',
  displayName: 'Generic MCP Host',
  surfaceProfile: 'local-stdio',
  capabilities: { mcp: true, skill: false, portableDescriptor: true },
  async install(context) {
    const file = descriptorPath(context);
    const descriptor = descriptorFor(context);
    if (await pathExists(file)) {
      if (!bindingOwnsPath(context, file)) {
        const error = new Error(`Generic MCP descriptor already exists and is not recorded as Veteran-owned: ${file}`);
        error.code = 'HOST_BINDING_CONFLICT';
        throw error;
      }
      const current = await readDescriptorForOwnership(file);
      if (!current) throw descriptorDriftError(file, 'descriptor-unreadable');
      const currentDigest = stableObjectHash(current);
      const recordedDigest = recordedBinding(context)?.descriptorDigest || null;
      const owned = recordedDigest
        ? currentDigest === recordedDigest
        : currentDigest === stableObjectHash(descriptor);
      if (!owned) throw descriptorDriftError(file, 'descriptor-drift');
    }
    await writeJsonAtomic(file, descriptor);
    return {
      installed: true,
      descriptorPath: file,
      descriptorDigest: stableObjectHash(descriptor),
      surfaceProfile: selectedSurfaceProfile(context)
    };
  },
  async status(context) {
    const file = descriptorPath(context);
    const config = await readJson(file, null);
    const server = config?.mcpServers?.['veteran-engineer'];
    const expected = descriptorFor(context).mcpServers['veteran-engineer'];
    const serverDigest = server && typeof server === 'object' && !Array.isArray(server) ? stableObjectHash(server) : null;
    const expectedServerDigest = stableObjectHash(expected);
    const healthy = Boolean(serverDigest && serverDigest === expectedServerDigest);
    const currentDigest = config ? stableObjectHash(config) : null;
    const recordedDigest = recordedBinding(context)?.descriptorDigest || null;
    return {
      installed: healthy,
      descriptorPath: file,
      exists: await pathExists(file),
      drift: Boolean(config && !healthy),
      descriptorDigestCurrent: recordedDigest ? currentDigest === recordedDigest : null,
      surfaceProfile: selectedSurfaceProfile(context)
    };
  },
  async doctor(context) {
    const status = await this.status(context);
    return { ok: status.installed, checks: [{ name: 'generic-descriptor', ok: status.installed, details: status }] };
  },
  async uninstall(context) {
    const file = descriptorPath(context);
    if (!(await pathExists(file))) {
      return { removed: true, descriptorPath: file, descriptorRemoved: false, reason: 'descriptor-missing' };
    }

    const current = await readDescriptorForOwnership(file);
    const recorded = recordedBinding(context);
    const recordedDigest = recorded?.descriptorDigest || null;
    const currentDigest = current ? stableObjectHash(current) : null;
    const legacyExpectedDigest = current ? stableObjectHash(descriptorFor(context)) : null;
    const owned = recordedDigest
      ? currentDigest === recordedDigest
      : Boolean(bindingOwnsPath(context, file) && currentDigest && currentDigest === legacyExpectedDigest);

    if (!owned) {
      return {
        removed: true,
        descriptorPath: file,
        descriptorRemoved: false,
        preserved: true,
        reason: current ? 'descriptor-drift' : 'descriptor-unreadable'
      };
    }

    await fs.rm(file, { force: true });
    return { removed: true, descriptorPath: file, descriptorRemoved: true };
  }
};
