@echo off
rem Double-clic : installe le warehouse NeoLab sous Windows (voir LISEZMOI.md).
chcp 65001 >nul
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0installer_windows.ps1" %*
echo.
pause
