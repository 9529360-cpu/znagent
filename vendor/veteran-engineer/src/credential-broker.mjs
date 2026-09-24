export const CREDENTIAL_REFERENCE_CONTRACT = 'veteran-credential-reference-v1';
export const CREDENTIAL_BROKER_CONTRACT = 'veteran-credential-broker-v1';

const MAX_REFERENCES = 64;
const MAX_PROVIDER_ID_LENGTH = 80;
const MAX_REFERENCE_NAME_LENGTH = 240;
const MAX_SECRET_BYTES = 64 * 1024;
const PROVIDER_ID = /^[a-z][a-z0-9._-]*$/;
const ENV_NAME = /^[A-Za-z_][A-Za-z0-9_]*$/;
const PROTECTED_TARGET_ENV = new Set([
  'PATH', 'PATHEXT', 'SYSTEMROOT', 'WINDIR', 'COMSPEC', 'SHELL',
  'HOME', 'USERPROFILE', 'XDG_CONFIG_HOME', 'XDG_CACHE_HOME', 'GIT_TERMINAL_PROMPT',
  'NODE_OPTIONS', 'NODE_PATH', 'PYTHONPATH', 'PYTHONHOME', 'RUBYOPT', 'RUBYLIB',
  'PERL5OPT', 'LD_PRELOAD', 'LD_LIBRARY_PATH', 'DYLD_INSERT_LIBRARIES', 'DYLD_LIBRARY_PATH'
]);

function codedError(message, code, details = null) {
  const error = new Error(message);
  error.code = code;
  if (details) error.details = details;
  return error;
}

function canonicalTargetEnv(value) {
  return String(value).toUpperCase();
}

function normalizeReference(raw, index) {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) {
    throw codedError(`Credential reference ${index + 1} must be an object`, 'CREDENTIAL_REFERENCE_INVALID');
  }
  const provider = String(raw.provider || 'environment').trim();
  const name = String(raw.name || '').trim();
  const targetEnv = String(raw.targetEnv || name).trim();
  if (!provider || provider.length > MAX_PROVIDER_ID_LENGTH || !PROVIDER_ID.test(provider)) {
    throw codedError(`Credential reference ${index + 1} has an invalid provider id`, 'CREDENTIAL_REFERENCE_INVALID');
  }
  if (!name || name.length > MAX_REFERENCE_NAME_LENGTH || name.includes('\0')) {
    throw codedError(`Credential reference ${index + 1} has an invalid name`, 'CREDENTIAL_REFERENCE_INVALID');
  }
  if (!ENV_NAME.test(targetEnv) || PROTECTED_TARGET_ENV.has(canonicalTargetEnv(targetEnv))) {
    throw codedError(`Credential reference ${index + 1} has an invalid or protected targetEnv`, 'CREDENTIAL_TARGET_INVALID', { targetEnv });
  }
  return Object.freeze({ contract: CREDENTIAL_REFERENCE_CONTRACT, provider, name, targetEnv });
}

export function normalizeCredentialReferences(raw, { legacyEnvironmentNames = [] } = {}) {
  if (raw !== undefined && raw !== null && !Array.isArray(raw)) {
    throw codedError('credentialRefs must be an array', 'CREDENTIAL_REFERENCE_INVALID');
  }
  if (!Array.isArray(legacyEnvironmentNames)) {
    throw codedError('legacyEnvironmentNames must be an array', 'CREDENTIAL_REFERENCE_INVALID');
  }
  const combined = [
    ...(raw || []),
    ...legacyEnvironmentNames.map((name) => ({ provider: 'environment', name, targetEnv: name }))
  ];
  if (combined.length > MAX_REFERENCES) {
    throw codedError(`At most ${MAX_REFERENCES} credential references are allowed`, 'CREDENTIAL_REFERENCE_INVALID');
  }
  const targets = new Set();
  return combined.map((item, index) => {
    const reference = normalizeReference(item, index);
    const targetKey = canonicalTargetEnv(reference.targetEnv);
    if (targets.has(targetKey)) {
      throw codedError(`Credential target ${reference.targetEnv} is duplicated`, 'CREDENTIAL_TARGET_DUPLICATE', { targetEnv: reference.targetEnv });
    }
    targets.add(targetKey);
    return reference;
  });
}

export class EnvironmentCredentialProvider {
  constructor({ environment = process.env } = {}) {
    this.environment = environment;
  }

  async resolve({ name }) {
    const value = this.environment?.[name];
    if (typeof value !== 'string' || value.length === 0) {
      throw codedError('Credential is not available from the environment provider', 'CREDENTIAL_NOT_AVAILABLE', { provider: 'environment', name });
    }
    return value;
  }
}

export class CredentialBroker {
  constructor({ providers = null } = {}) {
    const source = providers || { environment: new EnvironmentCredentialProvider() };
    const entries = source instanceof Map ? [...source.entries()] : Object.entries(source);
    this.providers = new Map();
    for (const [providerId, provider] of entries) {
      if (!PROVIDER_ID.test(String(providerId)) || !provider || typeof provider.resolve !== 'function') {
        throw codedError('Credential broker provider registry is invalid', 'CREDENTIAL_PROVIDER_INVALID', { provider: String(providerId) });
      }
      this.providers.set(String(providerId), provider);
    }
  }

  async materialize(references) {
    const normalized = normalizeCredentialReferences(references);
    const env = {};
    const targets = [];
    for (const reference of normalized) {
      const provider = this.providers.get(reference.provider);
      if (!provider) {
        throw codedError('Credential provider is not registered', 'CREDENTIAL_PROVIDER_NOT_FOUND', { provider: reference.provider });
      }
      let value;
      try {
        value = await provider.resolve({ name: reference.name, targetEnv: reference.targetEnv, reference });
      } catch (error) {
        if (error?.code) throw error;
        throw codedError('Credential provider failed', 'CREDENTIAL_PROVIDER_FAILED', { provider: reference.provider });
      }
      if (typeof value !== 'string' || value.length === 0 || value.includes('\0') || Buffer.byteLength(value) > MAX_SECRET_BYTES) {
        throw codedError('Credential provider returned an invalid secret value', 'CREDENTIAL_VALUE_INVALID', { provider: reference.provider, targetEnv: reference.targetEnv });
      }
      env[reference.targetEnv] = value;
      targets.push(reference.targetEnv);
    }
    return { contract: CREDENTIAL_BROKER_CONTRACT, env, targets };
  }
}
