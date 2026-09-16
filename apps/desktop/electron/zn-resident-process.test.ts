import assert from 'node:assert/strict'
import { once } from 'node:events'
import { promises as fs } from 'node:fs'
import { tmpdir } from 'node:os'
import * as path from 'node:path'

import { test } from 'vitest'

import {
  defaultZnResidentLaunch,
  isZnResidentLoopbackHost,
  ZnResidentProcess,
} from './zn-resident-process'

const fixtureSource = String.raw`
import crypto from 'node:crypto'
import fs from 'node:fs'
import net from 'node:net'
import path from 'node:path'

const endpointPath = process.argv[2]
const diagnosticsPath = process.argv[3]
if (!endpointPath) throw new Error('missing endpoint path')
if (!diagnosticsPath) throw new Error('missing diagnostics path')

function diagnose(stage, detail = {}) {
  try {
    fs.appendFileSync(
      diagnosticsPath,
      JSON.stringify({
        at: new Date().toISOString(),
        pid: process.pid,
        stage,
        ...detail,
      }) + '\n',
      'utf8'
    )
  } catch {}
}

function diagnosticError(error) {
  return {
    code: typeof error?.code === 'string' ? error.code : undefined,
    name: typeof error?.name === 'string' ? error.name : undefined,
    message: typeof error?.message === 'string' ? error.message.slice(0, 500) : String(error).slice(0, 500),
  }
}

process.on('uncaughtException', error => {
  diagnose('uncaught_exception', diagnosticError(error))
  process.exit(1)
})
process.on('unhandledRejection', error => {
  diagnose('unhandled_rejection', diagnosticError(error))
  process.exit(1)
})

diagnose('starting')
const secret = crypto.randomBytes(32).toString('hex')
const instanceId = 'fixture-' + process.pid + '-' + crypto.randomUUID()

const server = net.createServer(socket => {
  socket.setEncoding('utf8')
  let buffer = ''
  let authenticated = false

  const send = payload => socket.write(JSON.stringify(payload) + '\n')

  socket.on('data', chunk => {
    buffer += chunk
    while (true) {
      const newline = buffer.indexOf('\n')
      if (newline < 0) return
      const raw = buffer.slice(0, newline)
      buffer = buffer.slice(newline + 1)
      if (!raw.trim()) continue

      const request = JSON.parse(raw)
      const id = request.id ?? null
      if (!authenticated) {
        if (request.method !== 'authenticate' || request.params?.secret !== secret) {
          send({ id, ok: false, error: 'authentication failed' })
          socket.end()
          return
        }
        authenticated = true
        send({ id, ok: true, result: { authenticated: true, scheme: 'session-secret-v1' } })
        continue
      }

      if (request.method === 'status') {
        send({ id, ok: true, result: { fixture_pid: process.pid, instance_id: instanceId } })
        continue
      }

      if (request.method === 'shutdown') {
        socket.end(JSON.stringify({ id, ok: true, result: { shutdown: true } }) + '\n', () => {
          server.close(() => {
            try {
              const current = JSON.parse(fs.readFileSync(endpointPath, 'utf8'))
              if (Number(current.pid) === process.pid) fs.unlinkSync(endpointPath)
            } catch {}
            diagnose('shutdown_complete')
            process.exit(0)
          })
        })
        return
      }

      send({ id, ok: false, error: 'unsupported fixture method' })
    }
  })
})

server.on('error', error => {
  diagnose('listen_error', diagnosticError(error))
  process.exit(1)
})

server.listen(0, '127.0.0.1', () => {
  try {
    const address = server.address()
    if (!address || typeof address === 'string') throw new Error('fixture server did not bind TCP')
    diagnose('listening', { port: address.port })
    fs.mkdirSync(path.dirname(endpointPath), { recursive: true })
    const payload = {
      version: 2,
      transport: 'tcp',
      host: '127.0.0.1',
      port: address.port,
      pid: process.pid,
      instance_id: instanceId,
      started_at: new Date().toISOString(),
      runtime_id: 'fixture-runtime',
      python: process.execPath,
      authentication: {
        scheme: 'session-secret-v1',
        secret,
      },
    }
    const temporary = endpointPath + '.' + process.pid + '.tmp'
    fs.writeFileSync(temporary, JSON.stringify(payload))
    diagnose('endpoint_staged')
    fs.renameSync(temporary, endpointPath)
    diagnose('endpoint_published', { port: address.port })
  } catch (error) {
    diagnose('endpoint_publish_error', diagnosticError(error))
    throw error
  }
})
`

type FixtureEndpoint = {
  pid: number
  instance_id: string
  runtime_id: string
  authentication: { secret: string }
}

type FixtureStatus = {
  fixture_pid: number
  instance_id: string
}

type FixtureDiagnostic = {
  at?: string
  pid?: number
  stage?: string
  port?: number
  code?: string
  name?: string
  message?: string
}

async function readEndpoint(endpointPath: string): Promise<FixtureEndpoint> {
  return JSON.parse(await fs.readFile(endpointPath, 'utf8')) as FixtureEndpoint
}

async function readFixtureDiagnostics(diagnosticsPath: string): Promise<FixtureDiagnostic[]> {
  try {
    const raw = await fs.readFile(diagnosticsPath, 'utf8')
    const records: FixtureDiagnostic[] = []
    for (const line of raw.split(/\r?\n/)) {
      if (!line.trim()) continue
      try {
        const parsed = JSON.parse(line) as FixtureDiagnostic
        if (parsed && typeof parsed === 'object') records.push(parsed)
      } catch { void 0 }
    }
    return records.slice(-24)
  } catch {
    return []
  }
}

async function withFixtureDiagnostics<T>(
  promise: Promise<T>,
  diagnosticsPath: string
): Promise<T> {
  try {
    return await promise
  } catch (error) {
    const diagnostics = await readFixtureDiagnostics(diagnosticsPath)
    const message = error instanceof Error ? error.message : String(error)
    const detail = diagnostics.length > 0
      ? ` Fixture diagnostics: ${JSON.stringify(diagnostics)}`
      : ' Fixture diagnostics: no records were written.'
    throw new Error(`${message}${detail}`, { cause: error })
  }
}

async function within<T>(promise: Promise<T>, timeoutMs: number, label: string): Promise<T> {
  let timer: NodeJS.Timeout | null = null
  try {
    return await Promise.race([
      promise,
      new Promise<T>((_, reject) => {
        timer = setTimeout(() => reject(new Error(`Timed out waiting for ${label}`)), timeoutMs)
      })
    ])
  } finally {
    if (timer) clearTimeout(timer)
  }
}

function killFixture(pid: number | null): void {
  if (!pid) return
  try { process.kill(pid, 'SIGKILL') } catch { void 0 }
}

test('resident endpoint host accepts loopback aliases only', () => {
  for (const host of ['127.0.0.1', ' localhost ', '::1']) {
    assert.equal(isZnResidentLoopbackHost(host), true, host)
  }
  for (const host of ['', '0.0.0.0', '192.0.2.10', 'example.com', '::']) {
    assert.equal(isZnResidentLoopbackHost(host), false, host)
  }
})

test('default desktop launch uses the stable formal resident entrypoint', () => {
  const launch = defaultZnResidentLaunch({
    ZN_AGENT_HOME: '/tmp/zn-home',
    ZN_RESIDENT_PYTHON: '/tmp/python'
  })

  assert.deepEqual(launch.args, ['-m', 'zn_agent.resident'])
})

test('desktop client relaunches and reauthenticates after a hard resident crash leaves a stale endpoint', async () => {
  const root = await fs.mkdtemp(path.join(tmpdir(), 'zn-resident-process-'))
  const endpointPath = path.join(root, 'resident-endpoint.json')
  const diagnosticsPath = path.join(root, 'fixture-diagnostics.ndjson')
  const fixturePath = path.join(root, 'fixture-resident.mjs')
  await fs.writeFile(fixturePath, fixtureSource, 'utf8')

  const resident = new ZnResidentProcess({
    command: process.execPath,
    args: [fixturePath, endpointPath, diagnosticsPath],
    endpointPath,
    env: { ...process.env }
  })

  let firstPid: number | null = null
  let secondPid: number | null = null
  try {
    const firstStatus = await withFixtureDiagnostics(
      resident.start(8_000) as Promise<FixtureStatus>,
      diagnosticsPath
    )
    firstPid = Number(firstStatus.fixture_pid)
    const firstEndpoint = await readEndpoint(endpointPath)
    assert.equal(firstEndpoint.pid, firstPid)
    assert.equal(firstEndpoint.instance_id, firstStatus.instance_id)
    assert.equal(resident.runtimeIdentity.runtimeId, 'fixture-runtime')

    const disconnected = once(resident, 'disconnect')
    process.kill(firstPid, 'SIGKILL')
    await within(disconnected, 5_000, 'resident disconnect after hard crash')
    assert.equal(resident.running, false)

    const staleEndpoint = await readEndpoint(endpointPath)
    assert.equal(staleEndpoint.pid, firstPid)
    assert.equal(staleEndpoint.instance_id, firstEndpoint.instance_id)
    assert.equal(staleEndpoint.authentication.secret, firstEndpoint.authentication.secret)

    const secondStatus = await withFixtureDiagnostics(
      resident.request('status', {}, 8_000) as Promise<FixtureStatus>,
      diagnosticsPath
    )
    secondPid = Number(secondStatus.fixture_pid)
    const secondEndpoint = await readEndpoint(endpointPath)
    assert.equal(secondEndpoint.pid, secondPid)
    assert.equal(secondEndpoint.instance_id, secondStatus.instance_id)
    assert.notEqual(secondPid, firstPid)
    assert.notEqual(secondEndpoint.instance_id, firstEndpoint.instance_id)
    assert.notEqual(secondEndpoint.authentication.secret, firstEndpoint.authentication.secret)
    assert.equal(resident.running, true)
    assert.equal(resident.runtimeIdentity.runtimeId, 'fixture-runtime')
  } finally {
    try { await resident.stop() } catch { void 0 }
    killFixture(firstPid)
    killFixture(secondPid)
    await fs.rm(root, { recursive: true, force: true })
  }
}, 20_000)
