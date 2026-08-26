param(
    [Parameter(Mandatory = $true)]
    [string]$RunnerRoot,
    [string]$ExpectedRunnerName = 'zn-interactive'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$resolvedRoot = (Resolve-Path -LiteralPath $RunnerRoot -ErrorAction Stop).Path
$runCommand = Join-Path $resolvedRoot 'run.cmd'
$listenerPath = Join-Path $resolvedRoot 'bin\Runner.Listener.exe'
$runnerConfigPath = Join-Path $resolvedRoot '.runner'

foreach ($requiredPath in @($runCommand, $listenerPath, $runnerConfigPath)) {
    if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf)) {
        throw "Interactive runner watchdog is missing required path: $requiredPath"
    }
}

$runnerConfig = Get-Content -LiteralPath $runnerConfigPath -Raw -ErrorAction Stop | ConvertFrom-Json
if ([string]$runnerConfig.agentName -ne $ExpectedRunnerName) {
    throw "Interactive runner watchdog expected runner '$ExpectedRunnerName' but local config names '$($runnerConfig.agentName)'."
}

$currentSessionId = (Get-Process -Id $PID -ErrorAction Stop).SessionId
if ($currentSessionId -eq 0) {
    throw 'Interactive runner watchdog must execute in a logged-on interactive Windows session, not Session 0.'
}

function Get-ExpectedListener {
    $matches = @()
    foreach ($candidate in @(Get-CimInstance Win32_Process -Filter "Name = 'Runner.Listener.exe'" -ErrorAction SilentlyContinue)) {
        if ([string]$candidate.ExecutablePath -ne $listenerPath) {
            continue
        }
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

while ($true) {
    $listeners = @(Get-ExpectedListener)
    if ($listeners.Count -gt 1) {
        throw "Interactive runner watchdog found duplicate listeners in session $currentSessionId."
    }

    if ($listeners.Count -eq 1) {
        Start-Sleep -Seconds 10
        continue
    }

    Write-Output "ZN interactive runner listener absent; starting visible run.cmd in session $currentSessionId."
    Push-Location $resolvedRoot
    try {
        & $runCommand
        $exitCode = $LASTEXITCODE
        Write-Output "ZN interactive runner run.cmd exited with code $exitCode; restarting in 5 seconds."
    } catch {
        Write-Warning "ZN interactive runner run.cmd failed: $($_.Exception.Message)"
    } finally {
        Pop-Location
    }
    Start-Sleep -Seconds 5
}
