@echo off
title BrainN - GanFanYu
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Python venv not found in %~dp0.venv
    pause
    exit /b 1
)
".venv\Scripts\python.exe" main.py %*
echo.
echo [Bot exited] See logs\brainn.log for details.
pause
