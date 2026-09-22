export const SURFACE_CAPABILITY_CONTRACT = 'veteran-surface-capabilities-v1';

const PROFILE_DEFINITIONS = Object.freeze({
  'local-stdio': Object.freeze({
    id: 'local-stdio',
    description: 'Local stdio host with repository and execution access on the runtime machine.',
    capabilities: Object.freeze({
      repository: Object.freeze({ localPath: true, remoteGit: true, fileUrl: true }),
      execution: Object.freeze({ localProcess: true, container: true }),
      transport: Object.freeze({ stdioMcp: true, remoteMcp: false, secureTunnel: false }),
      credentials: Object.freeze({ localGit: true, delegatedAuth: false }),
      state: Object.freeze({ localDurable: true, hostedDurable: true })
    })
  }),
  'remote-mcp': Object.freeze({
    id: 'remote-mcp',
    description: 'Remote MCP service where repositories must be acquired by URL into runtime-managed storage.',
    capabilities: Object.freeze({
      repository: Object.freeze({ localPath: false, remoteGit: true, fileUrl: false }),
      execution: Object.freeze({ localProcess: true, container: true }),
      transport: Object.freeze({ stdioMcp: false, remoteMcp: true, secureTunnel: false }),
      credentials: Object.freeze({ localGit: false, delegatedAuth: true }),
      state: Object.freeze({ localDurable: true, hostedDurable: true })
    })
  }),
  'secure-tunnel': Object.freeze({
    id: 'secure-tunnel',
    description: 'Developer-machine or private-network runtime reached through a secure remote MCP tunnel.',
    capabilities: Object.freeze({
      repository: Object.freeze({ localPath: true, remoteGit: true, fileUrl: true }),
      execution: Object.freeze({ localProcess: true, container: true }),
      transport: Object.freeze({ stdioMcp: true, remoteMcp: true, secureTunnel: true }),
      credentials: Object.freeze({ localGit: true, delegatedAuth: true }),
      state: Object.freeze({ localDurable: true, hostedDurable: true })
    })
  })
});

function cloneProfile(profile) {
  return JSON.parse(JSON.stringify({
    contract: SURFACE_CAPABILITY_CONTRACT,
    id: profile.id,
    description: profile.description,
    capabilities: profile.capabilities
  }));
}

function invalidContract(input) {
  const error = new Error(`Surface profile objects must declare ${SURFACE_CAPABILITY_CONTRACT} and a profile id`);
  error.code = 'SURFACE_CAPABILITY_CONTRACT_INVALID';
  error.details = {
    expectedContract: SURFACE_CAPABILITY_CONTRACT,
    receivedContract: typeof input?.contract === 'string' ? input.contract : null,
    receivedId: typeof input?.id === 'string' ? input.id : null
  };
  return error;
}

export function surfaceProfileNames() {
  return Object.keys(PROFILE_DEFINITIONS);
}

export function resolveSurfaceProfile(input = 'local-stdio') {
  let id;
  if (input && typeof input === 'object') {
    if (input.contract !== SURFACE_CAPABILITY_CONTRACT || typeof input.id !== 'string' || !input.id.trim()) {
      throw invalidContract(input);
    }
    id = input.id.trim();
  } else {
    id = typeof input === 'string' && input.trim() ? input.trim() : 'local-stdio';
  }

  const profile = PROFILE_DEFINITIONS[id];
  if (!profile) {
    const error = new Error(`Unknown Veteran Engineer surface profile: ${id}`);
    error.code = 'SURFACE_PROFILE_UNSUPPORTED';
    error.details = { requested: id, supported: surfaceProfileNames() };
    throw error;
  }
  return cloneProfile(profile);
}

export function requireSurfaceCapability(profile, group, capability, message = null) {
  const resolved = resolveSurfaceProfile(profile);
  if (resolved.capabilities?.[group]?.[capability] === true) return resolved;
  const error = new Error(message || `Surface ${resolved.id} does not provide ${group}.${capability}`);
  error.code = 'SURFACE_CAPABILITY_UNAVAILABLE';
  error.details = { surfaceProfile: resolved.id, capability: `${group}.${capability}` };
  throw error;
}
