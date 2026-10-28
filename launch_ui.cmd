@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv-explorer\Scripts\python.exe" (
  echo Run setup_ui.cmd first to create the local Python environment.
  pause
  exit /b 1
)
set OMP_NUM_THREADS=1
set MKL_NUM_THREADS=1
set OPENBLAS_NUM_THREADS=1
".venv-explorer\Scripts\python.exe" -m research.post_decision_value.explorer --open
if errorlevel 1 (
  echo Explorer stopped with an error. Check dependencies or whether port 8765 is already in use.
  pause
  exit /b 1
)
