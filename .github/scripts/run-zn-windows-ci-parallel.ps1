param(
    [ValidateSet('all', 'source-boundary', 'kernel', 'desktop')]
    [string]$Lane = 'all'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$workspace = $env:GITHUB_WORKSPACE
if ([string]::IsNullOrWhiteSpace($workspace)) {
    $workspace = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
}
Set-Location $workspace

function Assert-NativeSuccess {
    param([Parameter(Mandatory = $true)][string]$Description)
    if ($LASTEXITCODE -ne 0) {
        throw "$Description failed with exit code $LASTEXITCODE"
    }
}

function Invoke-SourceBoundaryLane {
    Write-Host "ZN lane source-boundary started at $([DateTime]::UtcNow.ToString('o'))"
    Remove-Item -Recurse -Force .ci/source-venv -ErrorAction SilentlyContinue
    & uv venv .ci/source-venv --python 3.12
    Assert-NativeSuccess 'create source-boundary virtual environment'
    & .\.ci\source-venv\Scripts\python.exe .agent/verify_zn_source_boundary.py
    Assert-NativeSuccess 'verify active tree is ZN-only'
    Write-Host "ZN lane source-boundary completed at $([DateTime]::UtcNow.ToString('o'))"
}

function Invoke-KernelLane {
    Write-Host "ZN lane kernel started at $([DateTime]::UtcNow.ToString('o'))"
    New-Item -ItemType Directory -Force -Path $env:ZN_AGENT_HOME | Out-Null
    Remove-Item -Recurse -Force .ci/runtime-venv -ErrorAction SilentlyContinue
    & uv venv .ci/runtime-venv --python 3.12
    Assert-NativeSuccess 'create kernel virtual environment'

    $python = Join-Path $workspace '.ci\runtime-venv\Scripts\python.exe'
    & uv pip install --python $python runtime/python
    Assert-NativeSuccess 'install isolated ZN runtime'

    @'
import os
from pathlib import Path
import zn_agent.resident
from zn_agent.core.provider_bridge import build_resident_runtime
home = Path(os.environ['ZN_AGENT_HOME']) / 'isolated-runtime'
home.mkdir(parents=True, exist_ok=True)
resident = build_resident_runtime(config={'model': {}}, store_path=home / 'kernel.db')
pulse = resident.pulse()
state = resident.life.snapshot()
assert pulse.sequence >= 1
assert state.body is not None
assert state.external_brains == ()
resident.store.close()
'@ | & $python -I -
    Assert-NativeSuccess 'boot isolated ZN distribution without a model'

    & $python -m compileall -q runtime/python/zn_agent/core
    Assert-NativeSuccess 'compile resident core'

    $env:PYTHONPATH = Join-Path $workspace 'runtime\python'
    & $python -m unittest discover -s tests/zn_agent/core -p 'test_*.py' -v
    Assert-NativeSuccess 'run ZN core tests against working tree'
    Write-Host "ZN lane kernel completed at $([DateTime]::UtcNow.ToString('o'))"
}

function Invoke-DesktopLane {
    Write-Host "ZN lane desktop started at $([DateTime]::UtcNow.ToString('o'))"
    & npm ci --ignore-scripts
    Assert-NativeSuccess 'install locked workspace dependencies'

    & npm audit --audit-level=high
    Assert-NativeSuccess 'reject high-severity npm advisories'

    & npm run typecheck --workspace apps/desktop
    Assert-NativeSuccess 'typecheck Electron desktop'

    & node apps/desktop/scripts/bundle-electron-main.mjs --dev
    Assert-NativeSuccess 'bundle independent ZN desktop control plane'

    & npm run test --workspace apps/desktop -- electron/zn-desktop-ownership.test.ts electron/zn-packaged-runtime.test.ts electron/zn-release-channel.test.ts electron/zn-resident-runtime-state.test.ts electron/zn-resident-application-handoff.test.ts electron/zn-resident-update-readiness.test.ts electron/zn-release-application-gate.test.ts
    Assert-NativeSuccess 'test ZN desktop ownership and runtime contracts'

    & node --test apps/desktop/scripts/prepare-zn-public-channel.test.mjs apps/desktop/scripts/stage-zn-runtime.test.mjs apps/desktop/scripts/verify-zn-packaged-runtime.test.mjs
    Assert-NativeSuccess 'test release-channel and packaged-runtime verifiers'
    Write-Host "ZN lane desktop completed at $([DateTime]::UtcNow.ToString('o'))"
}

if ($Lane -ne 'all') {
    switch ($Lane) {
        'source-boundary' { Invoke-SourceBoundaryLane }
        'kernel' { Invoke-KernelLane }
        'desktop' { Invoke-DesktopLane }
    }
    exit 0
}

$resultsPath = Join-Path $workspace '.ci\zn-ci-lane-results.json'
New-Item -ItemType Directory -Force -Path (Split-Path $resultsPath -Parent) | Out-Null
Remove-Item $resultsPath -Force -ErrorAction SilentlyContinue

$laneNames = @('source-boundary', 'kernel', 'desktop')
$jobs = [ordered]@{}
foreach ($laneName in $laneNames) {
    $jobs[$laneName] = Start-Job -Name "zn-ci-$laneName" -ArgumentList $PSCommandPath, $laneName, $workspace -ScriptBlock {
        param($scriptPath, $childLane, $childWorkspace)
        Set-Location $childWorkspace
        & powershell.exe -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $scriptPath -Lane $childLane
        if ($LASTEXITCODE -ne 0) {
            throw "ZN CI lane $childLane exited with code $LASTEXITCODE"
        }
    }
}

Wait-Job -Job @($jobs.Values) | Out-Null

$results = [ordered]@{}
$failed = @()
foreach ($laneName in $laneNames) {
    $job = $jobs[$laneName]
    Write-Host "::group::ZN CI lane: $laneName"
    Receive-Job -Job $job -ErrorAction Continue
    Write-Host '::endgroup::'

    if ($job.State -eq 'Completed') {
        $results[$laneName] = 'success'
    } else {
        $results[$laneName] = 'failure'
        $failed += $laneName
    }
    Remove-Job -Job $job -Force
}

$json = $results | ConvertTo-Json -Compress
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($resultsPath, $json, $utf8NoBom)
Write-Host "ZN CI lane results: $json"

if ($failed.Count -gt 0) {
    throw "ZN parallel CI failed lanes: $($failed -join ', ')"
}
