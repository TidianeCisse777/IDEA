@echo off
rem Installe le warehouse NeoLab depuis le registre prive GitHub (base deja installee).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dpn0.ps1" %*
pause
