# Backup route if push-to-github.bat does not work.
#
# Run it from cmd.exe or PowerShell with:
#     powershell -NoProfile -ExecutionPolicy Bypass -File D:\FPGA\push-to-github.ps1
#
# This uses -ExecutionPolicy Bypass so it also works on machines where running
# .ps1 files is restricted. It is ASCII-only for the same reason as the .bat.

$ErrorActionPreference = "Stop"
Set-Location "D:\FPGA"

$git = $null
$candidates = Get-ChildItem (Join-Path $env:LOCALAPPDATA "GitHubDesktop") -Directory -Filter "app-*" -ErrorAction SilentlyContinue |
    Sort-Object Name -Descending |
    ForEach-Object { Join-Path $_.FullName "resources\app\git\cmd\git.exe" }
foreach ($candidate in $candidates) {
    if (Test-Path $candidate) { $git = $candidate; break }
}
if (-not $git) {
    $found = Get-Command git -ErrorAction SilentlyContinue
    if ($found) { $git = $found.Source }
}
if (-not $git) {
    Write-Host "[ERROR] git.exe not found. Open GitHub Desktop once, or install Git for Windows."
    exit 1
}

Write-Host "Using git : $git"
& $git --version
Write-Host ""

if (-not (Test-Path ".git")) {
    Write-Host "[ERROR] Not a git repository: $PWD"
    exit 1
}

$remoteUrl = "https://github.com/lsxzcd/LogicLens.git"
Write-Host "Repo       : $PWD"
Write-Host "Remote URL : $remoteUrl"
Write-Host ""
Write-Host "Commits to be pushed:"
& $git log --oneline
Write-Host ""

& $git remote get-url origin 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    & $git remote add origin $remoteUrl
    Write-Host "Added remote origin."
} else {
    & $git remote set-url origin $remoteUrl
    Write-Host "Remote origin already existed - URL updated."
}
Write-Host ""

Write-Host "============================================================"
Write-Host " Pushing now."
Write-Host " - If a browser window opens, click Authorize."
Write-Host " - If it asks for a password, paste a Personal Access Token"
Write-Host "   (a GitHub PAT, NOT your account password)."
Write-Host "============================================================"
Write-Host ""

& $git push -u origin main
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "[FAILED] The push did not complete. Send the error text above for help."
    exit 1
}

Write-Host ""
Write-Host "[OK] Pushed to GitHub successfully."
& $git log --oneline -1
