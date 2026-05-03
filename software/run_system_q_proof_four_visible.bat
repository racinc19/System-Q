@echo off
cd /d "%~dp0"
echo Launches System Q, brings it to front, waits so you SEE each jump, saves 4 PNGs + animated GIF on Desktop.
set SYSTEM_Q_AGENT_VISIBLE_MS=2800
set SYSTEM_Q_AGENT_LEAD_MS=3400
set SYSTEM_Q_AGENT_GIF_MS=2000
py -3 system_q_console.py --agent-proof=all
if errorlevel 1 pause
