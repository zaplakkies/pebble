# Build dist\pebble-agent.exe. Run on Windows from this folder:
#   powershell -ExecutionPolicy Bypass -File build.ps1
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

if (-not (Test-Path .venv-build)) { py -3 -m venv .venv-build }
$py = '.\.venv-build\Scripts\python.exe'
& $py -m pip install --quiet --upgrade pip
& $py -m pip install --quiet -r requirements.txt pyinstaller pytest
if ($LASTEXITCODE) { throw 'pip install failed' }

& $py -m pytest -q
if ($LASTEXITCODE) { throw 'tests failed' }

# --windowed: no console window when started by the scheduled task. The CLI
# commands (install, status) attach to the terminal they were started from.
& $py -m PyInstaller --noconfirm --clean --onefile --windowed --name pebble-agent `
    --hidden-import pystray._win32 --collect-all uiautomation pebble-agent.py
if ($LASTEXITCODE) { throw 'PyInstaller failed' }

Write-Host "`nBuilt $PSScriptRoot\dist\pebble-agent.exe"
