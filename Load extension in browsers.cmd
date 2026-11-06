@echo off
title Load the extension
(set /p "=%~dp0extension" <nul) | clip
start "" chrome "chrome://extensions"
start "" msedge "edge://extensions"
echo The extensions page is opening in Chrome and in Edge.
echo The folder to choose is already copied, so you can paste it.
echo.
echo In each browser:
echo   1. Turn on Developer mode.
echo        Chrome: switch at the top right of the page.
echo        Edge: switch in the left sidebar, near the bottom.
echo   2. Click Load unpacked.
echo   3. In the window that opens, click the address bar, press Ctrl+V, press Enter,
echo      then click Select Folder.
echo.
echo A card named Local Ad Blocker should appear.
echo The folder to choose is: %~dp0extension
echo.
pause
