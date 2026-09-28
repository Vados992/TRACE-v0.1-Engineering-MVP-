@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0desktop\windows\Stop.ps1" %*
if errorlevel 1 pause
