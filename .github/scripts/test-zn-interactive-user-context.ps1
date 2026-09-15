param(
    [string]$ExpectedRunnerName = 'zn-interactive'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if ($env:RUNNER_OS -and $env:RUNNER_OS -ne 'Windows') {
    throw "ZN interactive user context requires Windows; got $env:RUNNER_OS"
}
if ($env:RUNNER_ARCH -and $env:RUNNER_ARCH -ne 'X64') {
    throw "ZN interactive user context requires X64; got $env:RUNNER_ARCH"
}
if ($env:RUNNER_NAME -and $env:RUNNER_NAME -ne $ExpectedRunnerName) {
    throw "ZN interactive user context expected runner '$ExpectedRunnerName'; got '$env:RUNNER_NAME'."
}

$currentProcess = Get-Process -Id $PID -ErrorAction Stop
$currentSessionId = [int]$currentProcess.SessionId
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
$administratorToken = $principal.IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator
)

Write-Host "interactive_user_context.runner=$($env:RUNNER_NAME)"
Write-Host "interactive_user_context.session_id=$currentSessionId"
Write-Host "interactive_user_context.administrator_token=$($administratorToken.ToString().ToLowerInvariant())"

if ($currentSessionId -eq 0) {
    throw 'ZN interactive acceptance cannot run in Session 0; start the runner in the logged-on user desktop session.'
}
if ($administratorToken) {
    throw 'ZN interactive acceptance cannot run from an elevated/Administrator token. Start zn-interactive through the repository Limited watchdog (or another standard-user launch) instead of an Administrator PowerShell/run.cmd session.'
}

Write-Host 'interactive_user_context.ready=true'
