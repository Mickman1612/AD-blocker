@echo off
title Local Ad Blocker
echo Turning on Local Ad Blocker...
echo.
python "%~dp0proxy\install.py" prepare
if errorlevel 1 goto problem
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0pc-wide\windows-ads.ps1"
if errorlevel 1 goto problem
echo.
echo Windows will ask for permission. Click YES.
powershell -NoProfile -Command "Start-Process powershell -Verb RunAs -Wait -ArgumentList ('-NoProfile -ExecutionPolicy Bypass -File ' + [char]34 + '%~dp0proxy\elevated.ps1' + [char]34 + ' -CaPath ' + [char]34 + '%LOCALAPPDATA%\LocalAdBlocker\ca.cer' + [char]34)"
python "%~dp0proxy\install.py" activate
if errorlevel 1 goto declined
echo.
python "%~dp0proxy\install.py" status
if errorlevel 1 goto problem
echo.
echo Ad blocker is ON for this whole PC. It starts by itself every time you turn on your PC.
echo Close and reopen your browsers. This window closes in 10 seconds.
timeout /t 10 >nul
exit /b 0

:declined
echo.
echo It isn't on, because Windows permission wasn't given. Run this file again and click YES.
echo.
pause
exit /b 1

:problem
echo.
echo Something didn't finish. Please tell Claude what this window says.
echo.
pause
exit /b 1
