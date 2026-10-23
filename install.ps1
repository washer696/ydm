# Installs or updates YDM on Windows. In PowerShell:
#
#   irm https://raw.githubusercontent.com/washer696/ydm/main/install.ps1 | iex
#
# 1. installs what's missing (Python from python.org, FFmpeg) with winget. Set $env:YDM_NO_DEPS = 1 to skip;
# 2. fetches YDM (the copy next to this script if there is one, else the latest code from GitHub);
# 3. runs install.py, which sets up yt-dlp, deno and the companion app, then opens the extension in Firefox.
# Never calls exit: run with iex, that would close the PowerShell window.

$ErrorActionPreference = "Stop"
$repo = "washer696/ydm"

function Find-Python {
    if (Get-Command py -ErrorAction SilentlyContinue) { return "py" }
    $python = Get-Command python -ErrorAction SilentlyContinue
    # The Microsoft Store build keeps its files where Firefox can't see them; its "python" alias opens the Store.
    if ($python -and $python.Source -notlike "*WindowsApps*") { return $python.Source }
    # Just installed by winget, before the PATH knows about it
    $local = Get-ChildItem "$env:LOCALAPPDATA\Programs\Python\Python3*\python.exe" -ErrorAction SilentlyContinue |
        Sort-Object FullName -Descending | Select-Object -First 1
    if ($local) { return $local.FullName }
    return $null
}

function Update-Path {
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
}

function Install-Package($id, [string[]]$extra = @()) {
    Write-Host "Installing $id..."
    winget install -e --id $id --accept-source-agreements --accept-package-agreements --disable-interactivity @extra
    Update-Path
}

if (-not $env:YDM_NO_DEPS) {
    if (-not (Find-Python)) { Install-Package "Python.Python.3.12" @("--scope", "user") }
    if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) { Install-Package "Gyan.FFmpeg" }
}

$python = Find-Python
if (-not $python) {
    Write-Host "Python is still missing: install it from https://www.python.org, then run this again."
    return
}

$src = $env:YDM_SRC
if (-not $src -and $PSScriptRoot -and (Test-Path (Join-Path $PSScriptRoot "install.py"))) { $src = $PSScriptRoot }
$temp = $null
if (-not $src) {
    $temp = Join-Path ([IO.Path]::GetTempPath()) ("ydm-" + [Guid]::NewGuid())
    New-Item -ItemType Directory -Path $temp | Out-Null
    Write-Host "Downloading YDM..."
    $zip = Join-Path $temp "ydm.zip"
    Invoke-WebRequest "https://github.com/$repo/archive/refs/heads/main.zip" -OutFile $zip -UseBasicParsing
    Expand-Archive $zip -DestinationPath $temp
    $src = (Get-ChildItem $temp -Directory | Select-Object -First 1).FullName
}

try {
    & $python (Join-Path $src "install.py") @args
} finally {
    if ($temp) { Remove-Item $temp -Recurse -Force -ErrorAction SilentlyContinue }
}
