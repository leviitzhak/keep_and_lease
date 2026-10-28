@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (
  echo Install 64-bit Python 3.12 or newer with the Python launcher, then run setup_ui.cmd again.
  pause
  exit /b 1
)
py -3 scripts\setup_explorer.py
if errorlevel 1 (
  echo Setup failed. Read the message above. No training was started.
  pause
  exit /b 1
)
echo Run launch_ui.cmd to open the explorer.
pause
