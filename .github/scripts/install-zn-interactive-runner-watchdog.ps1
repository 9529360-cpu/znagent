param(
    [string]$TaskName = 'ZN GitHub Actions Interactive Runner Watchdog',
    [string]$ExpectedRunnerName = 'zn-interactive'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Get-CurrentRunnerListener {
    $currentPid = $PID
    $cursor = Get-CimInstance Win32_Process -Filter "ProcessId = $currentPid" -ErrorAction Stop
    for ($depth = 0; $depth -lt 16 -and $null -ne $cursor; $depth++) {
        if ($cursor.Name -eq 'Runner.Listener.exe') {
            return $cursor
        }
        if (-not $cursor.ParentProcessId) { break }
        $cursor = Get-CimInstance Win32_Process -Filter "ProcessId = $($cursor.ParentProcessId)" -ErrorAction SilentlyContinue
    }

    $sessionId = (Get-Process -Id $PID -ErrorAction Stop).SessionId
    $candidates = @()
    foreach ($candidate in @(Get-CimInstance Win32_Process -Filter "Name = 'Runner.Listener.exe'" -ErrorAction SilentlyContinue)) {
        try {
            if ((Get-Process -Id ([int]$candidate.ProcessId) -ErrorAction Stop).SessionId -eq $sessionId) {
                $candidates += $candidate
            }
        } catch {}
    }
    if ($candidates.Count -ne 1) {
        throw "Could not uniquely resolve the current interactive Runner.Listener.exe in session $sessionId."
    }
    return $candidates[0]
}

if ($env:RUNNER_OS -and $env:RUNNER_OS -ne 'Windows') {
    throw "Interactive runner watchdog installer requires Windows; got $env:RUNNER_OS"
}
if ($env:RUNNER_NAME -and $env:RUNNER_NAME -ne $ExpectedRunnerName) {
    throw "Interactive runner watchdog installer expected '$ExpectedRunnerName'; got '$env:RUNNER_NAME'."
}

$listener = Get-CurrentRunnerListener
$listenerPath = [string]$listener.ExecutablePath
if ([string]::IsNullOrWhiteSpace($listenerPath)) {
    throw 'Current runner listener path is unavailable.'
}
$runnerRoot = Split-Path (Split-Path $listenerPath -Parent) -Parent
$runnerConfigPath = Join-Path $runnerRoot '.runner'
if (-not (Test-Path -LiteralPath $runnerConfigPath -PathType Leaf)) {
    throw "Runner config is missing: $runnerConfigPath"
}
$runnerConfig = Get-Content -LiteralPath $runnerConfigPath -Raw -ErrorAction Stop | ConvertFrom-Json
if ([string]$runnerConfig.agentName -ne $ExpectedRunnerName) {
    throw "Resolved runner root belongs to '$($runnerConfig.agentName)', not '$ExpectedRunnerName'."
}

$sourceWatchdog = Join-Path $env:GITHUB_WORKSPACE '.github\scripts\watch-zn-interactive-runner.ps1'
if (-not (Test-Path -LiteralPath $sourceWatchdog -PathType Leaf)) {
    throw "Repository watchdog script is missing: $sourceWatchdog"
}
$installedWatchdog = Join-Path $runnerRoot 'watch-zn-interactive-runner.ps1'
Copy-Item -LiteralPath $sourceWatchdog -Destination $installedWatchdog -Force

$currentIdentity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$currentSessionId = (Get-Process -Id $PID -ErrorAction Stop).SessionId
if ($currentSessionId -eq 0) {
    throw 'Interactive watchdog must be installed from a logged-on interactive session, not Session 0.'
}

$existingTask = Get-ScheduledTask -TaskPath '\' -TaskName $TaskName -ErrorAction SilentlyContinue
if ($null -eq $existingTask) {
    throw "Expected existing interactive watchdog task '$TaskName' was not found. Refusing to invent a new login principal from CI."
}

$principal = $existingTask.Principal
if ($principal.LogonType -notin @('Interactive','InteractiveToken')) {
    throw "Existing watchdog task does not use an interactive logon type: $($principal.LogonType)"
}
if (-not [string]::IsNullOrWhiteSpace([string]$principal.UserId) -and [string]$principal.UserId -ne $currentIdentity) {
    throw "Existing watchdog task is owned by '$($principal.UserId)', but current runner session is '$currentIdentity'."
}

$powershell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$quotedWatchdog = '"' + $installedWatchdog + '"'
$quotedRoot = '"' + $runnerRoot + '"'
$arguments = "-NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File $quotedWatchdog -RunnerRoot $quotedRoot -ExpectedRunnerName $ExpectedRunnerName"
$newAction = New-ScheduledTaskAction -Execute $powershell -Argument $arguments -WorkingDirectory $runnerRoot

$settings = $existingTask.Settings
$settings.Hidden = $true
$settings.ExecutionTimeLimit = 'PT0S'
$settings.RestartCount = 999
$settings.RestartInterval = 'PT1M'
$settings.MultipleInstances = 'IgnoreNew'

Set-ScheduledTask `
    -TaskPath '\' `
    -TaskName $TaskName `
    -Action $newAction `
    -Trigger $existingTask.Triggers `
    -Principal $existingTask.Principal `
    -Settings $settings | Out-Null

$updatedTask = Get-ScheduledTask -TaskPath '\' -TaskName $TaskName -ErrorAction Stop
$updatedAction = @($updatedTask.Actions)
if ($updatedAction.Count -ne 1) {
    throw "Updated watchdog task has unexpected action count: $($updatedAction.Count)"
}
if ([string]$updatedAction[0].Execute -ne $powershell) {
    throw 'Updated watchdog task does not execute Windows PowerShell.'
}
$updatedArguments = [string]$updatedAction[0].Arguments
foreach ($required in @('-WindowStyle Hidden', '-ExecutionPolicy Bypass', 'watch-zn-interactive-runner.ps1')) {
    if ($updatedArguments.IndexOf($required, [StringComparison]::OrdinalIgnoreCase) -lt 0) {
        throw "Updated watchdog action is missing required argument fragment: $required"
    }
}
if (-not $updatedTask.Settings.Hidden) {
    throw 'Updated watchdog task is not marked hidden.'
}

Write-Host "ZN interactive watchdog installed for runner=$ExpectedRunnerName"
Write-Host "runner.root=$runnerRoot"
Write-Host "runner.session_id=$currentSessionId"
Write-Host "runner.task=$TaskName"
Write-Host "runner.task.hidden=$($updatedTask.Settings.Hidden)"
Write-Host 'The currently running listener/watchdog is intentionally left intact; the hidden action applies on the next watchdog launch.'
