@echo off
title Local Ad Blocker
echo Putting the Windows ad settings back...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0windows-ads.ps1" -Undo
echo.
echo Next, Windows will ask to allow a change to the hosts file. Click Yes.
powershell -NoProfile -Command "Start-Process powershell -Verb RunAs -Wait -ArgumentList ('-NoProfile -ExecutionPolicy Bypass -File ' + [char]34 + '%~dp0hosts.ps1' + [char]34 + ' -Off')"
if errorlevel 1 echo You chose not to allow it, so the hosts file was not changed.
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0hosts.ps1" -Status
pause
