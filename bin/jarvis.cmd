@echo off
rem jarvis.cmd — тонкая обёртка, чтобы можно было набирать просто "jarvis" из cmd.exe и PowerShell
rem (Windows не запускает .ps1 напрямую по имени файла без расширения из PATH).
setlocal
set "SCRIPT_DIR=%~dp0"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%jarvis.ps1" %*
exit /b %ERRORLEVEL%
