param(
  [Parameter(Mandatory = $true)]
  [string]$ReleaseRoot,

  [Parameter(Mandatory = $true)]
  [string]$ExpectedPublishers
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$root = [System.IO.Path]::GetFullPath($ReleaseRoot)
if (-not (Test-Path -LiteralPath $root -PathType Container)) {
  throw "Windows release root does not exist: $root"
}

$publishers = @(
  $ExpectedPublishers -split ';' |
    ForEach-Object { [string]$_.Trim() } |
    Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
)
if ($publishers.Count -eq 0) {
  throw 'At least one trusted Windows signing publisher is required.'
}

$appExecutable = Join-Path $root 'win-unpacked\ZN.exe'
if (-not (Test-Path -LiteralPath $appExecutable -PathType Leaf)) {
  throw "Packaged ZN executable is missing: $appExecutable"
}

$installers = @(
  Get-ChildItem -LiteralPath $root -File |
    Where-Object { $_.Extension -in @('.exe', '.msi') } |
    ForEach-Object { $_.FullName }
)
if ($installers.Count -eq 0) {
  throw "No Windows installer artifacts were found under $root"
}

$targets = @($appExecutable) + $installers
$verified = 0
foreach ($target in $targets) {
  $signature = Get-AuthenticodeSignature -LiteralPath $target
  if ($signature.Status -ne 'Valid') {
    throw "Authenticode signature is not valid for $target (status=$($signature.Status))"
  }
  if ($null -eq $signature.SignerCertificate) {
    throw "Authenticode signature has no signer certificate for $target"
  }

  $publisher = [string]$signature.SignerCertificate.GetNameInfo(
    [System.Security.Cryptography.X509Certificates.X509NameType]::SimpleName,
    $false
  )
  $publisher = $publisher.Trim()
  if ([string]::IsNullOrWhiteSpace($publisher)) {
    throw "Authenticode signer has no publisher name for $target"
  }

  $trusted = $false
  foreach ($expected in $publishers) {
    if ($publisher -ieq $expected) {
      $trusted = $true
      break
    }
  }
  if (-not $trusted) {
    throw "Unexpected Authenticode publisher for $target: $publisher"
  }

  $thumbprint = [string]$signature.SignerCertificate.Thumbprint
  Write-Host "Verified Authenticode: $([System.IO.Path]::GetFileName($target)) publisher=$publisher thumbprint=$thumbprint"
  $verified += 1
}

if ($verified -lt 2) {
  throw "Expected to verify the packaged app and at least one installer; verified=$verified"
}
Write-Host "Verified $verified Windows release artifacts against the configured publisher allowlist."
