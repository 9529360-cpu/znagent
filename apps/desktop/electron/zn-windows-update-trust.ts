import { execFile } from 'node:child_process'
import path from 'node:path'
import { promisify } from 'node:util'

const execFileAsync = promisify(execFile)

export type ZnWindowsAuthenticodeObservation = {
  status: string
  publisher: string
  thumbprint: string
}

type ZnWindowsAuthenticodeExecOptions = {
  env: NodeJS.ProcessEnv
  windowsHide: boolean
  maxBuffer: number
}

export type ZnWindowsAuthenticodeExec = (
  executable: string,
  args: string[],
  options: ZnWindowsAuthenticodeExecOptions
) => Promise<{ stdout: string }>

const AUTHENTICODE_SCRIPT = String.raw`
$ErrorActionPreference = 'Stop'
$target = [string]$env:ZN_VERIFY_UPDATE_PATH
if ([string]::IsNullOrWhiteSpace($target)) {
  throw 'ZN_VERIFY_UPDATE_PATH is required'
}
$signature = Get-AuthenticodeSignature -LiteralPath $target
$publisher = ''
$thumbprint = ''
if ($null -ne $signature.SignerCertificate) {
  $publisher = [string]$signature.SignerCertificate.GetNameInfo(
    [System.Security.Cryptography.X509Certificates.X509NameType]::SimpleName,
    $false
  )
  $thumbprint = [string]$signature.SignerCertificate.Thumbprint
}
[ordered]@{
  status = [string]$signature.Status
  publisher = $publisher
  thumbprint = $thumbprint
} | ConvertTo-Json -Compress
`.trim()

function normalizedPublisher(value: unknown): string {
  return String(value ?? '').trim()
}

export function parseZnWindowsSigningPublishers(value: unknown): string[] {
  if (typeof value !== 'string') return []
  const publishers: string[] = []
  const seen = new Set<string>()
  for (const raw of value.split(';')) {
    const publisher = normalizedPublisher(raw)
    if (!publisher) continue
    const key = publisher.toLocaleLowerCase('en-US')
    if (seen.has(key)) continue
    seen.add(key)
    publishers.push(publisher)
  }
  return publishers
}

export function assertZnWindowsAuthenticodeTrust(
  observation: Partial<ZnWindowsAuthenticodeObservation> | null | undefined,
  configuredPublishers: unknown
): ZnWindowsAuthenticodeObservation {
  const allowed = parseZnWindowsSigningPublishers(configuredPublishers)
  if (allowed.length === 0) {
    throw new Error('no trusted Windows update publishers are configured')
  }

  const status = String(observation?.status ?? '').trim()
  if (status.toLocaleLowerCase('en-US') !== 'valid') {
    throw new Error(`Windows update Authenticode signature is not valid: ${status || 'missing'}`)
  }

  const publisher = normalizedPublisher(observation?.publisher)
  if (!publisher) {
    throw new Error('Windows update Authenticode signature has no publisher')
  }
  const publisherKey = publisher.toLocaleLowerCase('en-US')
  if (!allowed.some(item => item.toLocaleLowerCase('en-US') === publisherKey)) {
    throw new Error(`Windows update publisher is not trusted: ${publisher}`)
  }

  return {
    status: 'Valid',
    publisher,
    thumbprint: String(observation?.thumbprint ?? '').trim().toUpperCase()
  }
}

async function defaultAuthenticodeExec(
  executable: string,
  args: string[],
  options: ZnWindowsAuthenticodeExecOptions
): Promise<{ stdout: string }> {
  const result = await execFileAsync(executable, args, {
    env: options.env,
    windowsHide: options.windowsHide,
    maxBuffer: options.maxBuffer,
    encoding: 'utf8'
  })
  return { stdout: String(result.stdout ?? '') }
}

export async function verifyZnWindowsUpdateAuthenticode(
  installerPath: string,
  configuredPublishers: unknown,
  execute: ZnWindowsAuthenticodeExec = defaultAuthenticodeExec,
  environ: NodeJS.ProcessEnv = process.env
): Promise<ZnWindowsAuthenticodeObservation> {
  const target = String(installerPath || '').trim()
  if (!target) throw new Error('Windows update installer path is required')

  // Fail before invoking PowerShell when the packaged build carries no trust root.
  const allowed = parseZnWindowsSigningPublishers(configuredPublishers)
  if (allowed.length === 0) {
    throw new Error('no trusted Windows update publishers are configured')
  }

  const windowsRoot = String(environ.SystemRoot || environ.WINDIR || 'C:\\Windows').trim()
  const powershell = path.win32.join(
    windowsRoot,
    'System32',
    'WindowsPowerShell',
    'v1.0',
    'powershell.exe'
  )
  const { stdout } = await execute(
    powershell,
    [
      '-NoLogo',
      '-NoProfile',
      '-NonInteractive',
      '-ExecutionPolicy',
      'Bypass',
      '-Command',
      AUTHENTICODE_SCRIPT
    ],
    {
      env: { ...environ, ZN_VERIFY_UPDATE_PATH: target },
      windowsHide: true,
      maxBuffer: 64 * 1024
    }
  )

  let observation: unknown
  try {
    observation = JSON.parse(String(stdout || '').trim())
  } catch {
    throw new Error('Windows update Authenticode verification returned invalid output')
  }
  if (!observation || typeof observation !== 'object' || Array.isArray(observation)) {
    throw new Error('Windows update Authenticode verification returned invalid output')
  }

  return assertZnWindowsAuthenticodeTrust(
    observation as Partial<ZnWindowsAuthenticodeObservation>,
    allowed.join(';')
  )
}
