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
$currentAccount = ($currentIdentity -split '\\')[-1]

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

$existingTask = Get-ScheduledTask -TaskPath '\' -TaskName $TaskName -ErrorAction SilentlyContinue
if ($null -ne $existingTask) {
    $principal = $existingTask.Principal
    if ($principal.LogonType -notin @('Interactive','InteractiveToken')) {
        throw "Existing watchdog task does not use an interactive logon type: $($principal.LogonType)"
    }
    $taskAccount = ([string]$principal.UserId -split '\\')[-1]
    if (-not [string]::IsNullOrWhiteSpace([string]$principal.UserId) -and $taskAccount -ne $currentAccount) {
        throw "Existing watchdog task is owned by '$($principal.UserId)', but current runner session is '$currentIdentity'."
    }
}

$cmd = Join-Path $env:SystemRoot 'System32\cmd.exe'
$arguments = "/d /c `"cd /d $runnerRoot && run.cmd`""
$newAction = New-ScheduledTaskAction -Execute $cmd -Argument $arguments -WorkingDirectory $runnerRoot
$newTrigger = New-ScheduledTaskTrigger -AtLogOn -User $currentIdentity
# Always rebuild the task principal from the currently logged-on identity. Reusing an
# existing principal can preserve RunLevel=Highest from an older task and make the next
# zn-interactive listener elevated even though the watchdog action itself is unchanged.
$limitedPrincipal = New-ScheduledTaskPrincipal `
    -UserId $currentIdentity `
    -LogonType Interactive `
    -RunLevel Limited

if ($null -eq $existingTask) {
    $settings = New-ScheduledTaskSettingsSet `
        -ExecutionTimeLimit ([TimeSpan]::Zero) `
        -RestartCount 999 `
        -RestartInterval (New-TimeSpan -Minutes 1) `
        -MultipleInstances IgnoreNew
    $settings.Hidden = $false
    Register-ScheduledTask `
        -TaskPath '\' `
        -TaskName $TaskName `
        -Action $newAction `
        -Trigger $newTrigger `
        -Principal $limitedPrincipal `
        -Settings $settings | Out-Null
    Write-Host "Created visible Limited watchdog task for current interactive identity '$currentIdentity'."
} else {
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
        -Principal $limitedPrincipal `
        -Settings $settings | Out-Null
}

$updatedTask = Get-ScheduledTask -TaskPath '\' -TaskName $TaskName -ErrorAction Stop
$updatedAction = @($updatedTask.Actions)
if ($updatedAction.Count -ne 1) {
    throw "Updated watchdog task has unexpected action count: $($updatedAction.Count)"
}
if ([string]$updatedAction[0].Execute -ne $cmd) {
    throw 'Updated interactive task does not execute cmd.exe.'
}
$updatedArguments = [string]$updatedAction[0].Arguments
foreach ($required in @('/d /c', 'run.cmd')) {
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
if ($updatedTask.Principal.LogonType -notin @('Interactive','InteractiveToken')) {
    throw "Updated watchdog task left interactive desktop boundary: $($updatedTask.Principal.LogonType)"
}
if ([string]$updatedTask.Principal.RunLevel -ne 'Limited') {
    throw "Updated watchdog task must run with Limited privileges; got $($updatedTask.Principal.RunLevel)."
}
if (-not [string]::IsNullOrWhiteSpace([string]$updatedTask.Principal.UserId) -and ([string]$updatedTask.Principal.UserId -split '\\')[-1] -ne $currentAccount) {
    throw "Updated watchdog task belongs to '$($updatedTask.Principal.UserId)', not current interactive identity '$currentIdentity'."
}
if (@($updatedTask.Triggers).Count -ne 1 -or [string]$updatedTask.Triggers[0].CimClass.CimClassName -ne 'MSFT_TaskLogonTrigger') {
    throw 'Updated watchdog task does not have exactly one logon trigger.'
}

Write-Host "ZN interactive watchdog configured as visible logon task for runner=$ExpectedRunnerName"
Write-Host "runner.root=$runnerRoot"
Write-Host "runner.session_id=$currentSessionId"
Write-Host "runner.task=$TaskName"
Write-Host "runner.task_run_level=$($updatedTask.Principal.RunLevel)"
Write-Host 'The current listener remains intact. Future user logons start the visible Limited watchdog automatically.'
