param(
    [Parameter(Mandatory = $true)]
    [string]$RunnerRoot,
    [string]$TaskName = 'ZN GitHub Actions Interactive Runner Watchdog',
    [string]$ExpectedRunnerName = 'zn-interactive',
    [int]$WorkerDrainTimeoutSeconds = 300
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$resolvedRoot = (Resolve-Path -LiteralPath $RunnerRoot -ErrorAction Stop).Path
$listenerPath = Join-Path $resolvedRoot 'bin\Runner.Listener.exe'
$workerPath = Join-Path $resolvedRoot 'bin\Runner.Worker.exe'
$runnerConfigPath = Join-Path $resolvedRoot '.runner'
$logPath = Join-Path $resolvedRoot '_diag\zn-hidden-watchdog-handoff.log'

function Write-HandoffLog {
    param([string]$Message)
    $directory = Split-Path $logPath -Parent
    New-Item -ItemType Directory -Force -Path $directory | Out-Null
    $line = "{0:o} {1}" -f [DateTime]::UtcNow, $Message
    Add-Content -LiteralPath $logPath -Value $line -Encoding UTF8
}

if (-not (Test-Path -LiteralPath $runnerConfigPath -PathType Leaf)) {
    throw "Runner config is missing: $runnerConfigPath"
}
$runnerConfig = Get-Content -LiteralPath $runnerConfigPath -Raw -ErrorAction Stop | ConvertFrom-Json
if ([string]$runnerConfig.agentName -ne $ExpectedRunnerName) {
    throw "Hidden handoff expected '$ExpectedRunnerName' but local runner is '$($runnerConfig.agentName)'."
}

$currentSessionId = (Get-Process -Id $PID -ErrorAction Stop).SessionId
if ($currentSessionId -eq 0) {
    throw 'Hidden interactive runner handoff must execute in a logged-on interactive session.'
}

function Get-RunnerProcesses {
    param([string]$ImageName, [string]$ExpectedPath)
    $matches = @()
    foreach ($candidate in @(Get-CimInstance Win32_Process -Filter "Name = '$ImageName'" -ErrorAction SilentlyContinue)) {
        if ([string]$candidate.ExecutablePath -ne $ExpectedPath) { continue }
        try {
            $native = Get-Process -Id ([int]$candidate.ProcessId) -ErrorAction Stop
        } catch {
            continue
        }
        if ($native.SessionId -eq $currentSessionId) {
            $matches += $candidate
        }
    }
    return @($matches)
}

$deadline = [DateTime]::UtcNow.AddSeconds($WorkerDrainTimeoutSeconds)
do {
    $workers = @(Get-RunnerProcesses -ImageName 'Runner.Worker.exe' -ExpectedPath $workerPath)
    if ($workers.Count -eq 0) { break }
    Start-Sleep -Seconds 2
} while ([DateTime]::UtcNow -lt $deadline)

$workers = @(Get-RunnerProcesses -ImageName 'Runner.Worker.exe' -ExpectedPath $workerPath)
if ($workers.Count -ne 0) {
    Write-HandoffLog "aborted: worker did not drain within $WorkerDrainTimeoutSeconds seconds"
    exit 2
}

$listeners = @(Get-RunnerProcesses -ImageName 'Runner.Listener.exe' -ExpectedPath $listenerPath)
if ($listeners.Count -gt 1) {
    Write-HandoffLog 'aborted: duplicate matching listeners found'
    exit 3
}

$manualConsolePid = $null
if ($listeners.Count -eq 1) {
    $listener = $listeners[0]
    $parent = Get-CimInstance Win32_Process -Filter "ProcessId = $($listener.ParentProcessId)" -ErrorAction SilentlyContinue
    if ($null -ne $parent -and $parent.Name -eq 'cmd.exe') {
        $commandLine = [string]$parent.CommandLine
        if ($commandLine.IndexOf('run.cmd', [StringComparison]::OrdinalIgnoreCase) -ge 0 -and
            $commandLine.IndexOf($resolvedRoot, [StringComparison]::OrdinalIgnoreCase) -ge 0) {
            $manualConsolePid = [int]$parent.ProcessId
        }
    }
}

try {
    Stop-ScheduledTask -TaskPath '\' -TaskName $TaskName -ErrorAction SilentlyContinue
} catch {
    Write-HandoffLog "warning: could not stop existing watchdog task: $($_.Exception.Message)"
}

if ($listeners.Count -eq 1) {
    Stop-Process -Id ([int]$listeners[0].ProcessId) -Force -ErrorAction Stop
    Write-HandoffLog "stopped foreground listener pid=$($listeners[0].ProcessId)"
}

if ($null -ne $manualConsolePid) {
    try {
        Stop-Process -Id $manualConsolePid -Force -ErrorAction Stop
        Write-HandoffLog "closed dedicated foreground runner cmd pid=$manualConsolePid"
    } catch {
        Write-HandoffLog "warning: could not close dedicated runner cmd pid=$manualConsolePid: $($_.Exception.Message)"
    }
}

Start-ScheduledTask -TaskPath '\' -TaskName $TaskName -ErrorAction Stop
Write-HandoffLog "started hidden watchdog task in session=$currentSessionId"

$onlineDeadline = [DateTime]::UtcNow.AddSeconds(90)
do {
    Start-Sleep -Seconds 2
    $newListeners = @(Get-RunnerProcesses -ImageName 'Runner.Listener.exe' -ExpectedPath $listenerPath)
    if ($newListeners.Count -eq 1) {
        Write-HandoffLog "hidden listener online pid=$($newListeners[0].ProcessId)"
        exit 0
    }
} while ([DateTime]::UtcNow -lt $onlineDeadline)

Write-HandoffLog 'hidden listener did not return within 90 seconds'
exit 4
