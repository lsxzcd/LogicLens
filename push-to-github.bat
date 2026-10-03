@echo off
setlocal
chcp 65001 >nul

rem ---------------------------------------------------------------
rem 首次把本仓库推送到 GitHub。双击本文件即可，不需要 PATH 里有 git。
rem 推送时会弹出浏览器让你授权 GitHub 账号。
rem ---------------------------------------------------------------

cd /d "%~dp0"

set "GIT="
for /f "delims=" %%D in ('dir /b /ad /o-n "%LOCALAPPDATA%\GitHubDesktop\app-*" 2^>nul') do (
    if not defined GIT if exist "%LOCALAPPDATA%\GitHubDesktop\%%D\resources\app\git\cmd\git.exe" (
        set "GIT=%LOCALAPPDATA%\GitHubDesktop\%%D\resources\app\git\cmd\git.exe"
    )
)
if not defined GIT (
    for /f "delims=" %%G in ('where git 2^>nul') do if not defined GIT set "GIT=%%G"
)
if not defined GIT (
    echo [错误] 找不到 git.exe。
    echo        请安装 Git for Windows，或打开 GitHub Desktop 后再试。
    pause
    exit /b 1
)

echo 使用 git : %GIT%
"%GIT%" --version
echo.

if not exist ".git" (
    echo [错误] 当前目录不是 Git 仓库：%CD%
    pause
    exit /b 1
)

set "REMOTE_URL=https://github.com/LSXZCD/LogicLens.git"

echo 仓库位置 : %CD%
echo 远程地址 : %REMOTE_URL%
echo.
echo 将要推送的提交：
"%GIT%" log --oneline
echo.

rem 幂等地配置 origin：已存在就更新，不重复添加。
"%GIT%" remote get-url origin >nul 2>&1
if errorlevel 1 (
    "%GIT%" remote add origin "%REMOTE_URL%"
    echo 已添加 origin。
) else (
    "%GIT%" remote set-url origin "%REMOTE_URL%"
    echo origin 已存在，已更新地址。
)
echo.

echo ============================================================
echo  即将推送。若弹出浏览器窗口，请点击 Authorize 授权。
echo  若提示输入密码，请填 Personal Access Token（不是登录密码）。
echo ============================================================
echo.
"%GIT%" push -u origin main

if errorlevel 1 (
    echo.
    echo [失败] 推送未完成，请把上面的报错内容发给协助者。
) else (
    echo.
    echo [成功] 已推送到 GitHub。
    "%GIT%" log --oneline -1
    "%GIT%" branch -vv
)

echo.
pause
