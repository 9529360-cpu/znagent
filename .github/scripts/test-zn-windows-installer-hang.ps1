[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if ($env:RUNNER_OS -and $env:RUNNER_OS -ne 'Windows') {
    throw "Installer hang regression requires Windows; got $env:RUNNER_OS"
}

$helper = Join-Path $PSScriptRoot 'invoke-zn-windows-installer.ps1'
if (-not (Test-Path -LiteralPath $helper -PathType Leaf)) {
    throw "Installer process helper is missing: $helper"
}

$testRoot = Join-Path ([IO.Path]::GetTempPath()) ("zn-installer-hang-{0}" -f [Guid]::NewGuid().ToString('N'))
$fixture = Join-Path $testRoot 'stuck-installer.ps1'
$marker = Join-Path $testRoot 'dispatch-marker.txt'
New-Item -ItemType Directory -Force -Path $testRoot | Out-Null

$fixtureSource = @'
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$markerPath = [string]$env:ZN_INSTALLER_HANG_MARKER
if ([string]::IsNullOrWhiteSpace($markerPath)) {
    throw 'ZN_INSTALLER_HANG_MARKER is required'
}

$selfPath = (Get-Process -Id $PID -ErrorAction Stop).Path
$children = @()
try {
    for ($index = 0; $index -lt 5; $index++) {
        $children += Start-Process -FilePath $selfPath -ArgumentList '-NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command "Start-Sleep -Seconds 300"' -PassThru
    }
    $childIds = @($children | ForEach-Object { $_.Id })
    "launch root=$PID children=$($childIds -join ',')" | Set-Content -LiteralPath $markerPath -Encoding ascii
    Wait-Process -Id $childIds
} finally {
    foreach ($child in $children) {
        Stop-Process -Id $child.Id -Force -ErrorAction SilentlyContinue
    }
}
'@
Set-Content -LiteralPath $fixture -Value $fixtureSource -Encoding utf8

$oldMarker = $env:ZN_INSTALLER_HANG_MARKER
$output = [Collections.Generic.List[string]]::new()
$caught = $null
$stopwatch = [Diagnostics.Stopwatch]::StartNew()
try {
    $env:ZN_INSTALLER_HANG_MARKER = $marker
    $shellPath = (Get-Process -Id $PID -ErrorAction Stop).Path
    $fixtureArguments = "-NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$fixture`""
    try {
        & $helper `
            -InstallerPath $shellPath `
            -InstallerArguments $fixtureArguments `
            -TimeoutSeconds 2 `
            -MaxDiagnosticProcesses 3 `
            -PollIntervalMilliseconds 100 *>&1 |
            ForEach-Object { [void]$output.Add([string]$_) }
    } catch {
        $caught = $_
        [void]$output.Add([string]$_.Exception.Message)
    }
} finally {
    $stopwatch.Stop()
    if ($null -eq $oldMarker) {
        Remove-Item Env:ZN_INSTALLER_HANG_MARKER -ErrorAction SilentlyContinue
    } else {
        $env:ZN_INSTALLER_HANG_MARKER = $oldMarker
    }
}

try {
    if ($null -eq $caught) {
        throw 'Expected deliberately stuck installer to fail with a bounded timeout.'
    }
    if ($stopwatch.Elapsed.TotalSeconds -gt 15) {
        throw "Synthetic installer hang regression exceeded its outer bound: $($stopwatch.Elapsed.TotalSeconds)s"
    }
    if (-not (Test-Path -LiteralPath $marker -PathType Leaf)) {
        throw 'Synthetic installer never crossed its single dispatch marker.'
    }

    $markerLines = @(Get-Content -LiteralPath $marker)
    if ($markerLines.Count -ne 1) {
        throw "Expected exactly one synthetic installer dispatch marker, got $($markerLines.Count)."
    }
    if ($markerLines[0] -notmatch '^launch root=(\d+) children=([0-9,]+)$') {
        throw "Unexpected synthetic installer marker: $($markerLines[0])"
    }
    $rootProcessId = [int]$Matches[1]
    $childProcessIds = @($Matches[2].Split(',') | ForEach-Object { [int]$_ })
    if ($childProcessIds.Count -ne 5) {
        throw "Expected five synthetic child processes, got $($childProcessIds.Count)."
    }

    $combined = $output -join "`n"
    if ($combined -notmatch [regex]::Escape('clean_install.failure_class=installer-process hang')) {
        throw "Missing installer-process hang classification. Output:`n$combined"
    }
    if ($combined -notmatch [regex]::Escape('clean_install.installer_dispatch_count=1')) {
        throw "Missing exactly-once dispatch evidence. Output:`n$combined"
    }
    if ($combined -notmatch ("clean_install\.installer_pid={0}" -f $rootProcessId)) {
        throw "Timeout evidence did not identify the dispatched installer PID $rootProcessId. Output:`n$combined"
    }
    if ($combined -notmatch [regex]::Escape('clean_install.process_evidence.count=3')) {
        throw "Bounded process evidence did not stop at the configured limit. Output:`n$combined"
    }
    if ($combined -notmatch [regex]::Escape('clean_install.process_evidence.truncated=True')) {
        throw "Synthetic wide process tree was not reported as truncated. Output:`n$combined"
    }
    if ($combined -notmatch [regex]::Escape("pid=$rootProcessId")) {
        throw "Root installer identity is missing from bounded process evidence. Output:`n$combined"
    }
    $visibleChildCount = @($childProcessIds | Where-Object { $combined -match [regex]::Escape("pid=$_ ") }).Count
    if ($visibleChildCount -lt 1) {
        throw "No synthetic child PID appeared in bounded process evidence. Output:`n$combined"
    }
    if ($combined -notmatch [regex]::Escape('clean_install.installer_terminated=True')) {
        throw "Installer tree cleanup was not confirmed. Output:`n$combined"
    }

    $remaining = @($rootProcessId) + $childProcessIds
    $cleanupDeadline = [DateTime]::UtcNow.AddSeconds(5)
    do {
        $alive = @($remaining | Where-Object { $null -ne (Get-Process -Id $_ -ErrorAction SilentlyContinue) })
        if ($alive.Count -eq 0) {
            break
        }
        Start-Sleep -Milliseconds 100
    } while ([DateTime]::UtcNow -lt $cleanupDeadline)
    if ($alive.Count -ne 0) {
        throw "Synthetic installer process tree leaked after timeout cleanup: $($alive -join ',')"
    }

    Write-Host 'installer_hang_regression.classification=installer-process hang'
    Write-Host 'installer_hang_regression.dispatch_count=1'
    Write-Host 'installer_hang_regression.process_evidence_limit=3'
    Write-Host 'installer_hang_regression.process_tree_clean=true'
    Write-Host ("installer_hang_regression.elapsed_seconds={0:N3}" -f $stopwatch.Elapsed.TotalSeconds)
} finally {
    Remove-Item -LiteralPath $testRoot -Recurse -Force -ErrorAction SilentlyContinue
}
