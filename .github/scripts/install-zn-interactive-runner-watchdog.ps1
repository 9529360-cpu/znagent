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
    throw 'Could not resolve current Runner.Listener.exe from worker ancestry.'
}

if ($env:RUNNER_OS -and $env:RUNNER_OS -ne 'Windows') {
    throw "Interactive runner watchdog installer requires Windows; got $env:RUNNER_OS"
}
if ($env:RUNNER_NAME -and $env:RUNNER_NAME -ne $ExpectedRunnerName) {
    throw "Interactive runner watchdog installer expected '$ExpectedRunnerName'; got '$env:RUNNER_NAME'."
}

$currentSessionId = (Get-Process -Id $PID -ErrorAction Stop).SessionId
if ($currentSessionId -eq 0) {
    throw 'Interactive watchdog must be installed from a logged-on interactive session, not Session 0.'
}
$currentIdentity = [Security.Principal.WindowsIdentity]::GetCurrent().Name

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

$existingTask = Get-ScheduledTask -TaskPath '\' -TaskName $TaskName -ErrorAction Stop
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
$arguments = "-NoLogo -NoProfile -ExecutionPolicy Bypass -File $quotedWatchdog -RunnerRoot $quotedRoot -ExpectedRunnerName $ExpectedRunnerName"
$newAction = New-ScheduledTaskAction -Execute $powershell -Argument $arguments -WorkingDirectory $runnerRoot
$newTrigger = New-ScheduledTaskTrigger -AtLogOn -User $currentIdentity
$settings = $existingTask.Settings
$settings.Hidden = $false
$settings.ExecutionTimeLimit = 'PT0S'
$settings.RestartCount = 999
$settings.RestartInterval = 'PT1M'
$settings.MultipleInstances = 'IgnoreNew'

Set-ScheduledTask `
    -TaskPath '\' `
    -TaskName $TaskName `
    -Action $newAction `
    -Trigger $newTrigger `
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
foreach ($required in @('-ExecutionPolicy Bypass', 'watch-zn-interactive-runner.ps1')) {
    if ($updatedArguments.IndexOf($required, [StringComparison]::OrdinalIgnoreCase) -lt 0) {
        throw "Updated watchdog action is missing required argument fragment: $required"
    }
}
if ($updatedArguments.IndexOf('-WindowStyle Hidden', [StringComparison]::OrdinalIgnoreCase) -ge 0) {
    throw 'Updated watchdog action still requests a hidden window.'
}
if ($updatedTask.Settings.Hidden) {
    throw 'Updated watchdog task is still marked hidden.'
}
if (@($updatedTask.Triggers).Count -ne 1 -or [string]$updatedTask.Triggers[0].CimClass.CimClassName -ne 'MSFT_TaskLogonTrigger') {
    throw 'Updated watchdog task does not have exactly one logon trigger.'
}

Write-Host "ZN interactive watchdog configured as visible logon task for runner=$ExpectedRunnerName"
Write-Host "runner.root=$runnerRoot"
Write-Host "runner.session_id=$currentSessionId"
Write-Host "runner.task=$TaskName"
Write-Host 'The current listener remains intact. Future user logons start the visible watchdog automatically.'
