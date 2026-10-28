@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (
  echo Install 64-bit Python with its launcher, then run setup_ui.cmd again.
  echo Use Python 3.12 or 3.13 on Snapdragon ARM. Intel/AMD also supports 3.14.
  pause
  exit /b 1
)
for %%V in (3.13 3.12 3.14) do (
  py -%%V scripts\setup_explorer.py --check >nul 2>nul
  if not errorlevel 1 (
    set "EXPLORER_PYTHON_VERSION=%%V"
    goto install
  )
)
echo No supported 64-bit Python found. Snapdragon: native ARM64 Python 3.12/3.13.
echo Intel/AMD: x64 Python 3.12, 3.13 or 3.14. Install its Python launcher too.
pause
exit /b 1
:install
py -%EXPLORER_PYTHON_VERSION% scripts\setup_explorer.py
if errorlevel 1 (
  echo Setup failed. Read the message above. No training was started.
  pause
  exit /b 1
)
echo Run launch_ui.cmd to open the explorer.
pause
