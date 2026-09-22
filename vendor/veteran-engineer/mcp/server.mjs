#!/usr/bin/env node
import { startMcpServer } from '../src/mcp-server.mjs';

startMcpServer().catch((error) => {
  console.error(error?.stack || error);
  process.exitCode = 1;
});
