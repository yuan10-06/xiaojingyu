@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist "logs" mkdir "logs"
".venv\Scripts\python.exe" main.py >> "logs\bot.out.log" 2>> "logs\bot.err.log"
