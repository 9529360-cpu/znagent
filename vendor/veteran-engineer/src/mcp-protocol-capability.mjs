import { LEGACY_PROTOCOL_VERSION, MODERN_PROTOCOL_VERSION } from './constants.mjs';

export const MCP_TRANSPORT_MODES = Object.freeze({
  OFFICIAL_SDK: 'official-sdk',
  STANDALONE_FALLBACK: 'standalone-fallback'
});

export function protocolCapability(mode) {
  if (mode === MCP_TRANSPORT_MODES.OFFICIAL_SDK) {
    return {
      transport: 'stdio',
      implementation: mode,
      eras: ['modern', 'legacy'],
      protocols: [MODERN_PROTOCOL_VERSION, LEGACY_PROTOCOL_VERSION],
      negotiation: {
        modern: 'server/discover',
        legacy: 'initialize',
        autoFallbackToLegacy: true
      }
    };
  }
  if (mode === MCP_TRANSPORT_MODES.STANDALONE_FALLBACK) {
    return {
      transport: 'stdio',
      implementation: mode,
      eras: ['legacy'],
      protocols: [LEGACY_PROTOCOL_VERSION],
      negotiation: {
        modern: null,
        legacy: 'initialize',
        autoFallbackToLegacy: true
      }
    };
  }
  throw new Error(`Unknown MCP transport mode: ${mode}`);
}
