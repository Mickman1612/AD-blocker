@echo off
title Local Ad Blocker
echo Turning off the ads built into Windows...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0windows-ads.ps1"
echo.
echo Next, Windows will ask to allow a change to the hosts file. Click Yes.
powershell -NoProfile -Command "Start-Process powershell -Verb RunAs -Wait -ArgumentList ('-NoProfile -ExecutionPolicy Bypass -File ' + [char]34 + '%~dp0hosts.ps1' + [char]34 + '')"
if errorlevel 1 echo You chose not to allow it, so the hosts file was not changed.
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0hosts.ps1" -Status
echo.
echo Close and reopen your browsers and other apps so they pick this up.
pause
