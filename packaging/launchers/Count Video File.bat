@echo off
setlocal
cd /d "%~dp0"
title Count Chests In A Video
if not exist "Fortnite Visual Chest Counter.exe" (
  echo Could not find "Fortnite Visual Chest Counter.exe" next to this file.
  echo Please extract the WHOLE zip file first ^(right-click the zip, "Extract All"^), then try again.
  echo.
  pause
  exit /b 1
)
if "%~1"=="" (
  echo To count the chests in a recorded gameplay video:
  echo   drag the video file and drop it ONTO this file ^("Count Video File.bat"^).
  echo.
  echo This does not change your live counter.
  echo.
  pause
  exit /b 0
)
"%~dp0Fortnite Visual Chest Counter.exe" video "%~1"
echo.
echo Press any key to close this window.
pause >nul
