@echo off
title Load the extension
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0..\tools\load-extension.ps1"
echo.
pause
