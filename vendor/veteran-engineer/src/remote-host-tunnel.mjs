import { readRemoteHostConfig } from './remote-host-config.mjs';
import {
  assertRemoteMcpSdkReady,
  createRemoteMcpServerFactory,
  createRemoteVeteranApp
} from './remote-mcp-surface.mjs';

export async function startRemoteHostTunnelStdio({
  configPath,
  config: suppliedConfig = null,
  stateRoot = null,
  app: suppliedApp = null
} = {}) {
  const config = suppliedConfig || await readRemoteHostConfig(configPath);
  await assertRemoteMcpSdkReady();
  const app = await createRemoteVeteranApp({ config, stateRoot, app: suppliedApp });
  const factory = await createRemoteMcpServerFactory({ config, app });
  const { serveStdio } = await import('@modelcontextprotocol/server/stdio');
  serveStdio(factory, {
    legacy: 'serve',
    onerror: (error) => console.error(`[veteran-remote-host] secure tunnel MCP error: ${error.message}`)
  });
  return {
    app,
    config,
    transport: 'stdio',
    surfaceProfile: 'secure-tunnel'
  };
}
