# Loads the Git that ships with GitHub Desktop, which has Git Credential
# Manager next to it. Dot-source this before running git in a plain shell:
#
#     . .\scripts\git-env.ps1
#
# The loader also verifies the executable and the credential helper, and prints
# what it found so a failure is obvious instead of silent.

$ErrorActionPreference = "Stop"

$desktopRoot = Join-Path $env:LOCALAPPDATA "GitHubDesktop"
$git = $null

if (Test-Path $desktopRoot) {
    $candidates = Get-ChildItem $desktopRoot -Directory -Filter "app-*" -ErrorAction SilentlyContinue |
        Sort-Object Name -Descending |
        ForEach-Object { Join-Path $_.FullName "resources\app\git\cmd\git.exe" }
    foreach ($candidate in $candidates) {
        if (Test-Path $candidate) { $git = $candidate; break }
    }
}

if (-not $git) {
    # Fall back to a system-wide Git if one is installed.
    $onPath = Get-Command git -ErrorAction SilentlyContinue
    if ($onPath) { $git = $onPath.Source }
}

if (-not $git) {
    throw "No git executable found. Install Git for Windows, or open the repo in GitHub Desktop."
}

$gitDir = Split-Path $git -Parent
if ($env:Path -notlike "*$gitDir*") {
    $env:Path = "$gitDir;$env:Path"
}

Write-Host "git      : $(& $git --version)"
$helper = & $git config --get credential.helper 2>$null
if ($helper) {
    Write-Host "credential helper: $helper"
} else {
    Write-Warning "No credential helper configured; pushing will ask for a username and a Personal Access Token."
}
Write-Host "repo     : D:\FPGA"
& $git -C D:\FPGA status --short --branch
