@echo off
rem Met a jour le warehouse NeoLab installe (code, vues, fiches MCP), sans reinstaller. -Auto : a chaque session.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dpn0.ps1" %*
pause
