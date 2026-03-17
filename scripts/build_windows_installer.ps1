param(
    [Parameter(Mandatory = $true)]
    [string]$AppVersion,
    [string]$IsccPath
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

$issScript = Join-Path $repoRoot "installer\mtu-desktop-user.iss"
if (-not (Test-Path $issScript)) {
    throw "Inno Setup script not found: $issScript"
}

if (-not (Test-Path "dist\mtu-desktop")) {
    throw "Expected dist\\mtu-desktop output was not found. Build the desktop app first using scripts/build_windows_exe.ps1."
}

$resolvedIscc = $IsccPath
if (-not $resolvedIscc) {
    $candidates = @(
        "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        "C:\Program Files\Inno Setup 6\ISCC.exe"
    )

    $resolvedIscc = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
}

if (-not $resolvedIscc) {
    throw "ISCC.exe not found. Install Inno Setup 6 or pass -IsccPath."
}

Write-Host "Building per-user installer with Inno Setup..."

$hasSigningEnv =
    -not [string]::IsNullOrWhiteSpace($env:WINDOWS_CERT_BASE64) -and
    -not [string]::IsNullOrWhiteSpace($env:WINDOWS_CERT_PASSWORD)
$enableSigning = if ($hasSigningEnv) { 1 } else { 0 }

if ($enableSigning -eq 1) {
    Write-Host "Signing is enabled for installer build."
}
else {
    Write-Host "Signing is disabled for installer build (certificate env vars are missing)."
}

$isccArgs = @(
    "/DMyAppVersion=$AppVersion"
    "/DEnableSigning=$enableSigning"
    $issScript
)

& $resolvedIscc @isccArgs

if ($LASTEXITCODE -ne 0) {
    if ($enableSigning -eq 1) {
        Write-Warning "Signed Inno Setup build failed with exit code $LASTEXITCODE. Retrying without signing."
        & $resolvedIscc "/DMyAppVersion=$AppVersion" "/DEnableSigning=0" $issScript
    }

    if ($LASTEXITCODE -ne 0) {
        throw "Inno Setup build failed with exit code $LASTEXITCODE"
    }
}

Write-Host "Installer build complete. See dist\\ROSEA-MTU-v$AppVersion-setup-user.exe"
