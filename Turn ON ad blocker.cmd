@echo off
title Local Ad Blocker
echo Setting up Local Ad Blocker...
echo.
rem Older versions ran a filtering app. Switch it off if it's there.
python "%~dp0proxy\install.py" deactivate >nul 2>&1
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0pc-wide\windows-ads.ps1"
if errorlevel 1 goto problem
echo.
echo Windows will now ask for permission to block ad servers for every app. Click YES.
powershell -NoProfile -Command "Start-Process powershell -Verb RunAs -Wait -ArgumentList ('-NoProfile -ExecutionPolicy Bypass -File ' + [char]34 + '%~dp0pc-wide\hosts.ps1' + [char]34)"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0pc-wide\hosts.ps1" -Status
if errorlevel 1 goto declined
echo.
echo Last step: add the blocker to your browsers.
echo This is what makes YouTube and websites fast and ad-free, the same way Brave does it.
echo You only do this once per browser.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\load-extension.ps1"
echo.
echo All done. It starts by itself every time you turn on your PC.
echo.
pause
exit /b 0

:declined
echo.
echo It isn't fully on, because Windows permission wasn't given. Run this file again and click YES.
echo.
pause
exit /b 1

:problem
echo.
echo Something didn't finish. Please tell Claude what this window says.
echo.
pause
exit /b 1
