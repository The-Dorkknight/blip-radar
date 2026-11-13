@echo off
rem Blip - double-click launcher (Windows). Starts the radar simulator and opens
rem the phone UI in your browser. No hardware needed. Close this window to stop.
rem Required Notice: Copyright Matthew Armstrong (https://github.com/The-Dorkknight)
rem Licensed under the PolyForm Noncommercial License 1.0.0. No warranty.
cd /d "%~dp0"
where py >nul 2>nul && (set PY=py -3) || (where python >nul 2>nul && (set PY=python) || (echo Python 3 is not installed. Get it from https://www.python.org/downloads/ and tick "Add python.exe to PATH". & pause & exit /b 1))
echo Blip flasher + simulator - if the browser does not appear, open the address printed below.
%PY% tools\sim_radar.py %*
if errorlevel 1 pause
