@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Setup-Client.ps1" -Client Codex
if errorlevel 1 (
  echo Setup failed. Please inspect the error above.
  pause
  exit /b 1
)
echo Setup complete. Restart Codex to discover the NAS library entry.
pause
