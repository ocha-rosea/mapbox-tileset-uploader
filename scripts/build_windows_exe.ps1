param(
    [switch]$OneFile,
    [string]$PythonPath
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

$python = if ($PythonPath) { $PythonPath } else { Join-Path $repoRoot ".venv\Scripts\python.exe" }
if (-not (Test-Path $python)) {
        throw "Python not found at $python. Provide -PythonPath or create/populate .venv first."
}

$pyInfoJson = & $python -c "import json,sys,pathlib; p=pathlib.Path(sys.prefix); bp=str(getattr(sys,'base_prefix','')); be=str(getattr(sys,'_base_executable','')); marker=' '.join([sys.version,bp,be]).lower(); print(json.dumps({'executable':sys.executable,'prefix':sys.prefix,'base_prefix':bp,'base_executable':be,'version':sys.version,'has_conda_meta':(p/'conda-meta').exists(),'looks_conda':(('conda' in marker) or ('anaconda' in marker) or (p/'conda-meta').exists())}))"
$pyInfo = $pyInfoJson | ConvertFrom-Json

if ($pyInfo.looks_conda) {
        throw @"
Conda-based Python detected at:
    $($pyInfo.executable)

This commonly produces broken Tkinter executables (DLL load errors) with PyInstaller.
Use a non-conda CPython interpreter (python.org) and pass it via -PythonPath.

Example:
    scripts/build_windows_exe.ps1 -PythonPath C:\\Users\\<you>\\mtu-winbuild\\Scripts\\python.exe
"@
}

Write-Host "Installing build/runtime dependencies..."
& $python -m pip install --upgrade pip | Out-Null
& $python -m pip install -e .[windows-build] mapbox-tilesets | Out-Null

Write-Host "Building MTU desktop executable with PyInstaller..."
$distMode = if ($OneFile) { "--onefile" } else { "--onedir" }

& $python -m PyInstaller `
    --noconfirm `
    --clean `
    --windowed `
    $distMode `
    --name mtu-desktop `
    --paths src `
    --hidden-import mapbox_tilesets.scripts.cli `
    --hidden-import tkintermapview `
    --collect-all tkintermapview `
    src/mtu/ui_main.py

Write-Host "Build complete. Output is in .\dist\mtu-desktop\ (or .\dist\mtu-desktop.exe for onefile)."
