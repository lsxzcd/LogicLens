@echo off
rem ============================================================
rem  First push of this repository to GitHub.
rem  Just double-click this file. It finds git by itself, so you
rem  do NOT need git on PATH.
rem
rem  ASCII only on purpose: cmd.exe reads .bat files using the
rem  OEM code page, so non-English text would be mangled.
rem ============================================================
setlocal
cd /d "%~dp0"

set "GIT="
call :find_git
if not defined GIT (
    echo.
    echo [ERROR] git.exe not found.
    echo         Open GitHub Desktop once, or install Git for Windows.
    echo.
    pause
    exit /b 1
)

echo Using git : %GIT%
"%GIT%" --version
echo.

if not exist ".git" (
    echo [ERROR] Not a git repository: %CD%
    pause
    exit /b 1
)

set "REMOTE_URL=https://github.com/LSXZCD/LogicLens.git"

echo Repo       : %CD%
echo Remote URL : %REMOTE_URL%
echo.
echo Commits to be pushed:
"%GIT%" log --oneline
echo.

"%GIT%" remote get-url origin >nul 2>&1
if errorlevel 1 (
    "%GIT%" remote add origin "%REMOTE_URL%"
    echo Added remote origin.
) else (
    "%GIT%" remote set-url origin "%REMOTE_URL%"
    echo Remote origin already existed - URL updated.
)
echo.

echo ============================================================
echo  Pushing now.
echo  - If a browser window opens, click Authorize.
echo  - If it asks for a password, paste a Personal Access Token
echo    (a GitHub PAT, NOT your account password).
echo ============================================================
echo.

"%GIT%" push -u origin main
if errorlevel 1 goto failed

echo.
echo [OK] Pushed to GitHub successfully.
"%GIT%" log --oneline -1
echo.
pause
exit /b 0

:failed
echo.
echo [FAILED] The push did not complete.
echo Send the error text above for help.
echo.
pause
exit /b 1

:find_git
if exist "%LOCALAPPDATA%\GitHubDesktop\app-3.5.2\resources\app\git\cmd\git.exe" (
    set "GIT=%LOCALAPPDATA%\GitHubDesktop\app-3.5.2\resources\app\git\cmd\git.exe"
    exit /b 0
)
if exist "%LOCALAPPDATA%\GitHubDesktop\app-3.4.19\resources\app\git\cmd\git.exe" (
    set "GIT=%LOCALAPPDATA%\GitHubDesktop\app-3.4.19\resources\app\git\cmd\git.exe"
    exit /b 0
)
for /f "delims=" %%G in ('where git 2^>nul') do (
    set "GIT=%%G"
    exit /b 0
)
if exist "C:\Program Files\Git\cmd\git.exe" set "GIT=C:\Program Files\Git\cmd\git.exe"
exit /b 0
