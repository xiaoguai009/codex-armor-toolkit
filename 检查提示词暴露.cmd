@echo off
setlocal DisableDelayedExpansion
chcp 65001 >nul
if not exist "%~dp0小怪破甲安装器.exe" goto missing
"%~dp0小怪破甲安装器.exe" --privacy-check %*
set "result=%errorlevel%"
if not defined XIAOGUAI_NO_PAUSE pause
endlocal & exit /b %result%
:missing
echo 找不到同目录的小怪破甲安装器.exe，请先完整解压。
if not defined XIAOGUAI_NO_PAUSE pause
endlocal & exit /b 2
