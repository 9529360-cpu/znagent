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

if ($env:RUNNER_OS -and $env:RUNNER_OS -ne 'Windows') {
    throw "ZN Windows runner bootstrap requires Windows; got $env:RUNNER_OS"
}

$gh = Get-Command gh -ErrorAction SilentlyContinue
if ($null -eq $gh) {
    throw 'GitHub CLI (gh) is required on the bootstrap runner.'
}

& gh auth status --hostname github.com *> $null
Assert-NativeSuccess 'verify host GitHub CLI authentication'

$probe = Invoke-GhJson @('api', "repos/$Repository", '--jq', '{full_name: .full_name, permissions: .permissions}')
if ($probe.full_name -ne $Repository) {
    throw "GitHub CLI authentication cannot resolve expected repository $Repository"
}

$runnerTemp = $env:RUNNER_TEMP
if ([string]::IsNullOrWhiteSpace($runnerTemp)) {
    throw 'RUNNER_TEMP is unavailable; bootstrap must run from the existing repository runner.'
}
$sourceRunnerRoot = Split-Path (Split-Path $runnerTemp -Parent) -Parent
if (-not (Test-Path (Join-Path $sourceRunnerRoot 'config.cmd'))) {
    throw "Cannot locate current actions runner installation at $sourceRunnerRoot"
}

$existing = Get-RepositoryRunners
$interactive = @($existing.runners | Where-Object { $_.name -eq $env:RUNNER_NAME })
if ($interactive.Count -ne 1) {
    throw "Cannot uniquely resolve current runner '$env:RUNNER_NAME' in repository runner inventory."
}

$interactiveId = [int64]$interactive[0].id
$null = Invoke-GhJson @(
    'api', '--method', 'POST',
    "repos/$Repository/actions/runners/$interactiveId/labels",
    '-f', 'labels[]=zn-interactive'
)
Write-Host "Current runner '$($interactive[0].name)' is reserved with label zn-interactive."

$isAdministrator = Test-Administrator
if (-not $isAdministrator) {
    throw 'Runner bootstrap needs an elevated Windows account to install additional runners as services. No worker runner was configured.'
}

New-Item -ItemType Directory -Force -Path $InstallRoot | Out-Null

for ($index = 1; $index -le $WorkerCount; $index++) {
    $name = '{0}-{1:d2}' -f $WorkerPrefix, $index
    $inventory = Get-RepositoryRunners
    $remote = @($inventory.runners | Where-Object { $_.name -eq $name })

    if ($remote.Count -eq 1 -and $remote[0].status -eq 'online') {
        Write-Host "Runner $name is already online; leaving it intact."
        continue
    }
    if ($remote.Count -gt 1) {
        throw "Repository runner inventory contains duplicate name $name"
    }
    if ($remote.Count -eq 1) {
        throw "Runner $name already exists but is not online. Refusing destructive replacement; inspect its local service before retrying."
    }

    $target = Join-Path $InstallRoot $name
    if (Test-Path $target) {
        if (Test-Path (Join-Path $target '.runner')) {
            throw "Local runner directory $target is already configured but repository inventory does not contain $name. Refusing to overwrite it."
        }
        Remove-Item -Recurse -Force $target
    }
    New-Item -ItemType Directory -Force -Path $target | Out-Null

    Write-Host "Preparing runner $name from current runner binaries."
    & robocopy.exe $sourceRunnerRoot $target /E /R:2 /W:1 /XD _work _diag /XF .runner .credentials .credentials_rsaparams .service .env .path
    if ($LASTEXITCODE -gt 7) {
        throw "robocopy runner payload for $name failed with exit code $LASTEXITCODE"
    }

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

Write-Host "ZN runner pool ready: $WorkerCount zn-ci workers online; interactive runner '$env:RUNNER_NAME' remains separately labeled zn-interactive."
