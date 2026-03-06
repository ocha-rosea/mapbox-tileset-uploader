param(
    [Parameter(Mandatory = $true)]
    [string[]]$FilePath,
    [switch]$AllowFailure,
    [string]$TimestampUrl = "http://timestamp.digicert.com"
)

$ErrorActionPreference = "Stop"

function Get-SignToolPath {
    $candidates = Get-ChildItem "C:\Program Files (x86)\Windows Kits\10\bin\*\x64\signtool.exe" -ErrorAction SilentlyContinue |
        Sort-Object FullName -Descending

    return ($candidates | Select-Object -First 1).FullName
}

function Stop-WithError {
    param([string]$Message)

    if ($AllowFailure) {
        Write-Warning $Message
        exit 0
    }

    throw $Message
}

$certBase64 = $env:WINDOWS_CERT_BASE64
$certPassword = $env:WINDOWS_CERT_PASSWORD

if ([string]::IsNullOrWhiteSpace($certBase64) -or [string]::IsNullOrWhiteSpace($certPassword)) {
    Write-Host "Skipping signing: WINDOWS_CERT_BASE64 or WINDOWS_CERT_PASSWORD not configured."
    exit 0
}

$signtool = Get-SignToolPath
if ([string]::IsNullOrWhiteSpace($signtool)) {
    Stop-WithError -Message "signtool.exe not found; skipping signing."
}

$certPath = Join-Path $env:TEMP "codesign-$(Get-Random).pfx"

try {
    [IO.File]::WriteAllBytes($certPath, [Convert]::FromBase64String($certBase64))

    foreach ($item in $FilePath) {
        if (-not (Test-Path $item)) {
            Stop-WithError -Message "Signing target not found: $item"
            continue
        }

        $target = (Resolve-Path $item).Path
        $signArgs = @(
            "sign"
            "/fd", "SHA256"
            "/f", $certPath
            "/p", $certPassword
            "/tr", $TimestampUrl
            "/td", "SHA256"
            $target
        )

        & $signtool @signArgs

        if ($LASTEXITCODE -ne 0) {
            Stop-WithError -Message "Signing failed for $target with exit code $LASTEXITCODE"
        }

        Write-Host "Signed: $target"
    }
}
catch {
    Stop-WithError -Message ("Signing failed: " + $_.Exception.Message)
}
finally {
    if (Test-Path $certPath) {
        Remove-Item $certPath -Force -ErrorAction SilentlyContinue
    }
}
