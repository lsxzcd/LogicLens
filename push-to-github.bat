@echo off
rem ============================================================
rem  Push this repository to GitHub through the local proxy.
rem
rem  Why this exists: github.com is unreachable directly on this
rem  network, but a local proxy is running (the Windows system proxy
rem  is set to 127.0.0.1:7897). git does not read the Windows system
rem  proxy, so it must be told about it explicitly.
rem
rem  ASCII only on purpose: cmd.exe reads .bat using the OEM code
rem  page, so non-English text would be mangled.
rem ============================================================
setlocal
cd /d "%~dp0"

rem ---- Change these if your client uses different settings ----
set "PROXY_HOST=127.0.0.1"
set "PROXY_PORT=7897"
rem Use socks5 instead of http if your client exposes a SOCKS port.
set "PROXY_SCHEME=http"
rem -------------------------------------------------------------

set "GIT="
call :find_git
if not defined GIT (
    echo [ERROR] git.exe not found. Open GitHub Desktop once, then retry.
    echo.
    pause
    exit /b 1
)

echo Using git   : %GIT%
"%GIT%" --version
echo.

if not exist ".git" (
    echo [ERROR] Not a git repository: %CD%
    pause
    exit /b 1
)

call :port_listening %PROXY_PORT%
if errorlevel 1 (
    echo [ERROR] Nothing is listening on port %PROXY_PORT%.
    echo         Start your proxy client and enable its system proxy, then retry.
    echo         If your client uses a different port, edit this file:
    echo             set "PROXY_PORT=..."
    echo.
    pause
    exit /b 1
)
echo Proxy port %PROXY_PORT% is listening. Good.
echo.

set "PROXY_URL=%PROXY_SCHEME%://%PROXY_HOST%:%PROXY_PORT%"
echo Configuring git to use %PROXY_URL%
"%GIT%" config --global http.proxy  "%PROXY_URL%"
"%GIT%" config --global https.proxy "%PROXY_URL%"
rem GitHub Desktop ships a minimal git without the 'less' pager.
"%GIT%" config --global core.pager cat
echo.

set "REMOTE_URL=https://github.com/LSXZCD/LogicLens.git"
"%GIT%" remote get-url origin >nul 2>&1
if errorlevel 1 (
    "%GIT%" remote add origin "%REMOTE_URL%"
    echo Added remote origin.
) else (
    "%GIT%" remote set-url origin "%REMOTE_URL%"
    echo Remote origin already configured - URL updated.
)
echo.

echo Commits to be pushed:
"%GIT%" --no-pager log --oneline
echo.

echo ============================================================
echo  Pushing now via the proxy.
echo  - If a browser window opens, click Authorize.
echo  - If it asks for a password, paste a Personal Access Token
echo    (a GitHub PAT, NOT your account password).
echo ============================================================
echo.

"%GIT%" push -u origin main
if errorlevel 1 goto failed

echo.
echo [OK] Pushed to GitHub successfully.
"%GIT%" --no-pager log --oneline -1
echo.
pause
exit /b 0

:failed
echo.
echo [FAILED] The push did not complete.
echo.
echo Things to try, in order:
echo   1. Confirm the proxy client is running and that your browser can
echo      open github.com.
echo   2. If your client exposes SOCKS instead, edit this file and set
echo      PROXY_SCHEME=socks5 with that port.
echo   3. Confirm the remote URL:  git remote -v
echo   4. Send the error text above for help.
echo.
pause
exit /b 1

:find_git
for %%V in (3.6.0 3.5.3 3.5.2 3.5.1 3.5.0 3.4.19 3.4.18) do (
    if not defined GIT if exist "%LOCALAPPDATA%\GitHubDesktop\app-%%V\resources\app\git\cmd\git.exe" (
        set "GIT=%LOCALAPPDATA%\GitHubDesktop\app-%%V\resources\app\git\cmd\git.exe"
    )
)
if defined GIT exit /b 0
for /f "delims=" %%G in ('where git 2^>nul') do (
    if not defined GIT set "GIT=%%G"
)
if defined GIT exit /b 0
if exist "C:\Program Files\Git\cmd\git.exe" set "GIT=C:\Program Files\Git\cmd\git.exe"
exit /b 0

:port_listening
rem %1 = port. errorlevel 0 when a listener exists on that port.
netstat -ano | findstr /R /C:":%~1 " | findstr /C:"LISTENING" >nul 2>&1
exit /b %errorlevel%
