[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$InstallerPath,

    [string]$InstallerArguments = '',

    [ValidateRange(1, 3600)]
    [int]$TimeoutSeconds = 180,

    [ValidateRange(1, 256)]
    [int]$MaxDiagnosticProcesses = 32,

    [ValidateRange(25, 5000)]
    [int]$PollIntervalMilliseconds = 250
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Get-ZnProcessSnapshot {
    try {
        return @(Get-CimInstance Win32_Process -ErrorAction Stop)
    } catch {
        Write-Host "clean_install.process_evidence_error=$($_.Exception.GetType().Name)"
        return @()
    }
}

function Get-ZnProcessTreeIds {
    param(
        [Parameter(Mandatory = $true)][int]$RootProcessId,
        [Parameter(Mandatory = $true)][object[]]$Snapshot
    )

    $queue = [Collections.Generic.Queue[int]]::new()
    $seen = [Collections.Generic.HashSet[int]]::new()
    $ordered = [Collections.Generic.List[int]]::new()
    $queue.Enqueue($RootProcessId)

    while ($queue.Count -gt 0) {
        $processId = $queue.Dequeue()
        if (-not $seen.Add($processId)) {
            continue
        }
        [void]$ordered.Add($processId)
        foreach ($child in @($Snapshot | Where-Object { [int]$_.ParentProcessId -eq $processId })) {
            $queue.Enqueue([int]$child.ProcessId)
        }
    }

    return @($ordered)
}

function Format-ZnProcessCreationTime {
    param([Parameter(Mandatory = $true)]$CreationDate)

    if ($null -eq $CreationDate) {
        return 'unknown'
    }
    if ($CreationDate -is [DateTime]) {
        return $CreationDate.ToUniversalTime().ToString('o')
    }
    return [string]$CreationDate
}

function Write-ZnBoundedProcessEvidence {
    param(
        [Parameter(Mandatory = $true)][int[]]$TreeProcessIds,
        [Parameter(Mandatory = $true)][object[]]$Snapshot,
        [Parameter(Mandatory = $true)][int]$Limit
    )

    $visibleIds = @($TreeProcessIds | Select-Object -First $Limit)
    Write-Host "clean_install.process_evidence.count=$($visibleIds.Count)"
    Write-Host "clean_install.process_evidence.truncated=$([bool]($TreeProcessIds.Count -gt $visibleIds.Count))"
    Write-Host '--- installer process-tree evidence ---'
    foreach ($processId in $visibleIds) {
        $record = $Snapshot | Where-Object { [int]$_.ProcessId -eq $processId } | Select-Object -First 1
        if ($null -eq $record) {
            Write-Host "pid=$processId state=missing-from-snapshot"
            continue
        }
        $created = Format-ZnProcessCreationTime -CreationDate $record.CreationDate
        Write-Host ("pid={0} ppid={1} name={2} created={3}" -f $record.ProcessId, $record.ParentProcessId, $record.Name, $created)
    }
}

function Stop-ZnInstallerProcessTree {
    param(
        [Parameter(Mandatory = $true)][Diagnostics.Process]$RootProcess
    )

    # The CIM snapshot above is diagnostic evidence only. Do not turn descendant
    # PIDs from that point-in-time snapshot into later kill authority: a child can
    # exit and its PID can be reused before cleanup. The root Process object is
    # still the live timed-out installer we started, so let Windows resolve its
    # current descendant tree atomically enough for this cleanup boundary.
    try {
        & "$env:SystemRoot\System32\taskkill.exe" /PID $RootProcess.Id /T /F > $null 2>&1
    } catch {
        # Preserve the original installer-hang classification; verification below
        # still decides whether the captured root actually terminated.
    }

    try {
        [void]$RootProcess.WaitForExit(5000)
    } catch {
        # Failure classification must remain the original installer hang.
    }

    try {
        $RootProcess.Refresh()
        return [bool]$RootProcess.HasExited
    } catch {
        return $true
    }
}

$installer = Get-Item -LiteralPath $InstallerPath -ErrorAction Stop
if ($installer.PSIsContainer) {
    throw "Installer path must be a file: $InstallerPath"
}

$startParameters = @{
    FilePath = $installer.FullName
    PassThru = $true
}
if (-not [string]::IsNullOrWhiteSpace($InstallerArguments)) {
    $startParameters.ArgumentList = $InstallerArguments
}

$started = Get-Date
$process = Start-Process @startParameters
$createTime = $null
try {
    $createTime = $process.StartTime.ToUniversalTime().ToString('o')
} catch {
    $createTime = [DateTime]::UtcNow.ToString('o')
}

Write-Host 'clean_install.installer_dispatch_count=1'
Write-Host "clean_install.installer_pid=$($process.Id)"
Write-Host "clean_install.installer_created=$createTime"
Write-Host "clean_install.installer_name=$($installer.Name)"

$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
while ((Get-Date) -lt $deadline) {
    $process.Refresh()
    if ($process.HasExited) {
        break
    }
    Start-Sleep -Milliseconds $PollIntervalMilliseconds
}

$process.Refresh()
if (-not $process.HasExited) {
    $snapshot = Get-ZnProcessSnapshot
    $treeProcessIds = @(Get-ZnProcessTreeIds -RootProcessId $process.Id -Snapshot $snapshot)
    Write-Host 'clean_install.failure_class=installer-process hang'
    Write-Host "clean_install.installer_has_exited=false"
    Write-ZnBoundedProcessEvidence -TreeProcessIds $treeProcessIds -Snapshot $snapshot -Limit $MaxDiagnosticProcesses
    $terminated = Stop-ZnInstallerProcessTree -RootProcess $process
    Write-Host "clean_install.installer_terminated=$terminated"
    throw "installer-process hang: installer did not exit within $TimeoutSeconds seconds"
}

$installSeconds = [int]((Get-Date) - $started).TotalSeconds
Write-Host "clean_install.install_seconds=$installSeconds"
Write-Host "clean_install.installer_exit_code=$($process.ExitCode)"
if ($process.ExitCode -ne 0) {
    Write-Host 'clean_install.failure_class=installer-process failure'
    throw "installer-process failure: installer exited with code $($process.ExitCode)"
}
