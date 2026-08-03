# Builds the standalone NekoMail Windows desktop app.
#
# Usage: run from anywhere; paths are resolved relative to this script.
#   powershell -File build-desktop.ps1
#
# IMPORTANT: run this from a LOCAL DISK checkout, not directly against
# N:\projects\nekomail. Confirmed 2026-08-03: executing native binaries that
# live on that network share (a venv's python.exe, node_modules' esbuild)
# fails or hangs -- `npm install` errors EPERM spawning esbuild.exe, and a
# venv's python.exe just hangs indefinitely. Plain file reads/writes (git,
# editing source) are fine on N: -- it's specifically executing binaries
# from it that doesn't work. If your working copy is on N:, robocopy it to a
# local path first and run this script from there.
#
# Requires: Node.js (frontend build), and a Python venv with
# backend/requirements-desktop.txt installed (create one first if you don't
# have it: python -m venv backend/.venv; backend/.venv/Scripts/pip install
# -r backend/requirements-desktop.txt). Set $env:NEKOMAIL_PYTHON to point at
# a specific python.exe if you don't want the script to guess.

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$frontend = Join-Path $root "frontend"
$backend = Join-Path $root "backend"

Write-Output "== Building frontend =="
Push-Location $frontend
try {
    npm install
    npm run build
} finally {
    Pop-Location
}

Write-Output "== Copying frontend build into backend/app/static =="
$staticDir = Join-Path $backend "app\static"
if (Test-Path $staticDir) {
    Remove-Item -Recurse -Force $staticDir
}
Copy-Item -Recurse (Join-Path $frontend "dist") $staticDir

Write-Output "== Running PyInstaller =="
$python = $env:NEKOMAIL_PYTHON
if (-not $python) {
    $python = Join-Path $backend ".venv\Scripts\python.exe"
}
if (-not (Test-Path $python)) {
    throw "No Python found at $python. Create backend/.venv with requirements-desktop.txt installed, or set `$env:NEKOMAIL_PYTHON."
}

Push-Location $backend
try {
    & $python -m PyInstaller "nekomail-desktop.spec" --noconfirm
} finally {
    Pop-Location
}

$exePath = Join-Path $backend "dist\NekoMail\NekoMail.exe"
Write-Output "== Done: $exePath =="
