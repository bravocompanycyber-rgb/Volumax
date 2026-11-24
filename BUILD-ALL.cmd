@echo off
rem Double-click to build everything. Arguments are passed through (e.g. BUILD-ALL.cmd --targets modern-x64)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0BUILD-ALL.ps1" %*
echo.
pause
