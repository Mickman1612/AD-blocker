@echo off
title Local Ad Blocker
echo Turning off Local Ad Blocker...
echo.
python "%~dp0proxy\install.py" deactivate
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0pc-wide\windows-ads.ps1" -Undo
echo.
echo Windows will now ask for permission. Click YES.
powershell -NoProfile -Command "Start-Process powershell -Verb RunAs -Wait -ArgumentList ('-NoProfile -ExecutionPolicy Bypass -File ' + [char]34 + '%~dp0proxy\elevated.ps1' + [char]34 + ' -CaPath ' + [char]34 + '%LOCALAPPDATA%\LocalAdBlocker\ca.cer' + [char]34 + ' -Off')"
if errorlevel 1 goto declined
python "%~dp0proxy\install.py" forget
echo.
echo It's off, and everything it added has been removed. Close and reopen your browsers.
echo.
pause
exit /b 0

:declined
echo.
echo The filtering app is off, but the certificate and ad server list weren't removed, because
echo Windows permission wasn't given. Run this file again and click YES.
echo.
pause
exit /b 1
