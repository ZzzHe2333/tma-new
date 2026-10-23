@echo off
setlocal
cd /d "%~dp0"
if not exist "logs" mkdir "logs"
echo [%date% %time%] Starting ZzzHe TMA Analysis >> "logs\launcher.log"
"%~dp0ZzzHe TMA Analysis.exe" %* >> "logs\launcher-console.log" 2>&1
set "tma_exit_code=%errorlevel%"
copy /y "%LOCALAPPDATA%\ZzzHeTMA\logs\run-*.jsonl" "logs\" >nul 2>&1
copy /y "%LOCALAPPDATA%\ZzzHeTMA\logs\native-*.log" "logs\" >nul 2>&1
copy /y "%TEMP%\ZzzHeTMA\logs\run-*.jsonl" "logs\" >nul 2>&1
copy /y "%TEMP%\ZzzHeTMA\logs\native-*.log" "logs\" >nul 2>&1
echo [%date% %time%] Exit code: %tma_exit_code% >> "logs\launcher.log"
if not "%tma_exit_code%"=="0" (
  echo Application exited with code %tma_exit_code%.
  echo Please keep this window and the logs folder for diagnostics.
  pause
)
exit /b %tma_exit_code%
