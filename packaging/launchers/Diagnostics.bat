@echo off
setlocal
cd /d "%~dp0"
title Chest Counter Diagnostics
if not exist "Fortnite Visual Chest Counter.exe" (
  echo Could not find "Fortnite Visual Chest Counter.exe" next to this file.
  echo Please extract the WHOLE zip file first ^(right-click the zip, "Extract All"^), then try again.
  echo.
  pause
  exit /b 1
)
"%~dp0Fortnite Visual Chest Counter.exe" diagnostics
echo.
echo Press any key to close this window.
pause >nul
