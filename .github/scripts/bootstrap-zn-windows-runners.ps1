param(
    [ValidateRange(1, 6)]
    [int]$WorkerCount = 3,
    [string]$Repository = '9529360-cpu/znagent',
    [string]$WorkerPrefix = 'zn-ci',
    [string]$InstallRoot = 'C:\zn-runners'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Assert-NativeSuccess {
    param([Parameter(Mandatory = $true)][string]$Description)
    if ($LASTEXITCODE -ne 0) {
        throw "$Description failed with exit code $LASTEXITCODE"
    }
}

function Invoke-GhJson {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)
    $raw = & gh @Arguments
    Assert-NativeSuccess "gh $($Arguments -join ' ')"
    if ([string]::IsNullOrWhiteSpace(($raw -join "`n"))) {
        return $null
    }
    return (($raw -join "`n") | ConvertFrom-Json)
}

function Get-RepositoryRunners {
    return Invoke-GhJson @('api', "repos/$Repository/actions/runners", '--paginate')
}

function Get-RegistrationToken {
    $result = Invoke-GhJson @('api', '--method', 'POST', "repos/$Repository/actions/runners/registration-token")
    $token = [string]$result.token
    if ([string]::IsNullOrWhiteSpace($token)) {
        throw 'GitHub returned an empty self-hosted runner registration token.'
    }
    Write-Host "::add-mask::$token"
    return $token
}

function Test-Administrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Get-RunnerPackage {
    $release = Invoke-GhJson @('api', 'repos/actions/runner/releases/latest')
    $asset = @($release.assets | Where-Object { $_.name -match '^actions-runner-win-x64-[0-9.]+\.zip$' }) | Select-Object -First 1
    if ($null -eq $asset) {
        throw 'Could not resolve the latest official Windows x64 GitHub Actions runner asset.'
    }
    return [pscustomobject]@{
        Name = [string]$asset.name
        Url = [string]$asset.browser_download_url
        Version = [string]$release.tag_name
    }
}

function Expand-FreshRunner {
    param(
        [Parameter(Mandatory = $true)][string]$Target,
        [Parameter(Mandatory = $true)][psobject]$Package,
        [Parameter(Mandatory = $true)][string]$CacheZip
    )

    if (Test-Path $Target) {
        $entries = @(Get-ChildItem -Force $Target -ErrorAction SilentlyContinue)
        if ($entries.Count -gt 0) {
            throw "Target runner directory $Target is not empty. Refusing to overwrite or reuse runner state."
        }
    } else {
        New-Item -ItemType Directory -Force -Path $Target | Out-Null
    }

    if (-not (Test-Path $CacheZip)) {
        Write-Host "Downloading official GitHub Actions runner $($Package.Version): $($Package.Name)"
        Invoke-WebRequest -Uri $Package.Url -OutFile $CacheZip -UseBasicParsing
    }

    Expand-Archive -LiteralPath $CacheZip -DestinationPath $Target -Force
    if (-not (Test-Path (Join-Path $Target 'config.cmd'))) {
        throw "Fresh runner package did not produce config.cmd in $Target"
    }
}

if ($env:RUNNER_OS -and $env:RUNNER_OS -ne 'Windows') {
    throw "ZN Windows runner bootstrap requires Windows; got $env:RUNNER_OS"
}

if ($null -eq (Get-Command gh -ErrorAction SilentlyContinue)) {
    throw 'GitHub CLI (gh) is required on the bootstrap runner.'
}

& gh auth status --hostname github.com *> $null
Assert-NativeSuccess 'verify host GitHub CLI authentication'

$probe = Invoke-GhJson @('api', "repos/$Repository", '--jq', '{full_name: .full_name, permissions: .permissions}')
if ($probe.full_name -ne $Repository) {
    throw "GitHub CLI authentication cannot resolve expected repository $Repository"
}

$existing = Get-RepositoryRunners
$interactive = @($existing.runners | Where-Object { $_.name -eq $env:RUNNER_NAME })
if ($interactive.Count -ne 1) {
    throw "Cannot uniquely resolve current runner '$env:RUNNER_NAME' in repository runner inventory."
}
if (-not ($interactive[0].labels.name -contains 'zn-interactive')) {
    throw "Bootstrap runner '$env:RUNNER_NAME' is missing required zn-interactive label."
}

if (-not (Test-Administrator)) {
    throw 'Runner bootstrap needs an elevated Windows account to install additional runners as services. No worker runner was configured.'
}

New-Item -ItemType Directory -Force -Path $InstallRoot | Out-Null
$package = Get-RunnerPackage
$cacheZip = Join-Path $InstallRoot $package.Name

for ($index = 1; $index -le $WorkerCount; $index++) {
    $name = '{0}-{1:d2}' -f $WorkerPrefix, $index
    $inventory = Get-RepositoryRunners
    $remote = @($inventory.runners | Where-Object { $_.name -eq $name })

    if ($remote.Count -eq 1 -and $remote[0].status -eq 'online' -and ($remote[0].labels.name -contains 'zn-ci')) {
        Write-Host "Runner $name is already online with zn-ci label; leaving it intact."
        continue
    }
    if ($remote.Count -gt 1) {
        throw "Repository runner inventory contains duplicate name $name"
    }
    if ($remote.Count -eq 1) {
        throw "Runner $name already exists but is not healthy/online. Refusing destructive replacement; inspect its local service before retrying."
    }

    $target = Join-Path $InstallRoot $name
    Expand-FreshRunner -Target $target -Package $package -CacheZip $cacheZip

    Push-Location $target
    try {
        $registrationToken = Get-RegistrationToken
        & .\config.cmd --unattended --url "https://github.com/$Repository" --token $registrationToken --name $name --labels zn-ci --work _work --runasservice --windowslogonaccount 'NT AUTHORITY\NETWORK SERVICE' --disableupdate
        Assert-NativeSuccess "configure runner $name"
        & .\svc.cmd start
        Assert-NativeSuccess "start runner service $name"
    } finally {
        $registrationToken = $null
        Pop-Location
    }
}

$deadline = [DateTime]::UtcNow.AddSeconds(90)
$onlineWorkers = @()
$workers = @()
do {
    Start-Sleep -Seconds 3
    $inventory = Get-RepositoryRunners
    $workers = @($inventory.runners | Where-Object { $_.name -match ('^' + [regex]::Escape($WorkerPrefix) + '-\d{2}$') })
    $onlineWorkers = @($workers | Where-Object { $_.status -eq 'online' -and ($_.labels.name -contains 'zn-ci') })
    if ($onlineWorkers.Count -ge $WorkerCount) {
        break
    }
} while ([DateTime]::UtcNow -lt $deadline)

if ($onlineWorkers.Count -lt $WorkerCount) {
    $summary = $workers | ForEach-Object { "$($_.name)=$($_.status)" }
    throw "Only $($onlineWorkers.Count)/$WorkerCount zn-ci workers became online before timeout. Inventory: $($summary -join ', ')"
}

Write-Host "ZN runner pool ready: $WorkerCount zn-ci workers online; interactive runner '$env:RUNNER_NAME' remains isolated by label zn-interactive."
