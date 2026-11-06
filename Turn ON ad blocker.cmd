@echo off
title Local Ad Blocker
echo Setting up Local Ad Blocker. This can take a minute...
echo.
python "%~dp0proxy\install.py" prepare
if errorlevel 1 goto problem
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0pc-wide\windows-ads.ps1"
if errorlevel 1 goto problem
echo.
echo Windows will now ask for permission. Click YES.
powershell -NoProfile -Command "Start-Process powershell -Verb RunAs -Wait -ArgumentList ('-NoProfile -ExecutionPolicy Bypass -File ' + [char]34 + '%~dp0proxy\elevated.ps1' + [char]34 + ' -CaPath ' + [char]34 + '%LOCALAPPDATA%\LocalAdBlocker\ca.cer' + [char]34)"
if errorlevel 1 goto declined
python "%~dp0proxy\install.py" activate
if errorlevel 1 goto declined
echo.
python "%~dp0proxy\install.py" status
if errorlevel 1 goto problem
echo.
echo All done. Close and reopen your browsers.
echo From now on it starts by itself every time you turn on your PC.
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
