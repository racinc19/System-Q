@echo off
cd /d "%~dp0"
echo Opens System Q, moves scopes one at a time, saves VISIBLE_NAV_PROOF_*.png on Desktop + this folder.
py -3 visible_nav_proof_capture.py
if errorlevel 1 pause
