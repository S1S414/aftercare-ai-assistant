@echo off
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" storage_manager.py
) else if exist ".venv-acceptance\Scripts\python.exe" (
  ".venv-acceptance\Scripts\python.exe" storage_manager.py
) else (
  echo Python environment missing. Create .venv using the README instructions.
  pause
  exit /b 1
)
if errorlevel 1 pause
