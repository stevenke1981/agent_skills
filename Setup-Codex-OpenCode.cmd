@echo off
setlocal
set "NAS_SKILLS_SETUP_SCRIPT=%~dp0Setup-Client.ps1"
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "& $env:NAS_SKILLS_SETUP_SCRIPT -Client Codex,OpenCode"
if errorlevel 1 (
  echo Setup failed. Please inspect the error above.
  pause
  exit /b 1
)
echo Setup complete. Restart Codex and OpenCode to discover the NAS library entry.
pause
