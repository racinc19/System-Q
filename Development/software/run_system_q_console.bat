@echo off
cd /d "%~dp0"
echo Launcher: %~f0
echo Starting System Q — prior window exits so this launch always loads current code from disk.
echo Code dir: %cd%
py -3 system_q_console.py
if errorlevel 1 pause
