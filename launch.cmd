@echo off
cd /d "%~dp0"
if exist "%~dp0.venv\Scripts\python.exe" (
  "%~dp0.venv\Scripts\python.exe" "%~dp0run.py" %*
) else (
  python "%~dp0run.py" %*
)
if errorlevel 1 (
  echo.
  echo Application startup failed. See the error above.
  pause
)
