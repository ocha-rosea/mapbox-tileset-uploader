param(
    [Parameter(Mandatory = $true)]
    [string]$FilePath
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$signScript = Join-Path $repoRoot "scripts\sign_windows_artifacts.ps1"

if (-not (Test-Path $signScript)) {
    Write-Warning "Signing helper not found: $signScript"
    exit 0
}

# Inno Setup expects this hook to succeed unless signing must be hard-fail.
& $signScript -FilePath $FilePath -AllowFailure
exit $LASTEXITCODE
