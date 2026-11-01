@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PY=python
if exist ".venv\Scripts\python.exe" set PY=.venv\Scripts\python.exe
echo 请确认 NapCat 已启动，且 OneBot11 WS 端口为 3001。
"%PY%" main.py
pause
