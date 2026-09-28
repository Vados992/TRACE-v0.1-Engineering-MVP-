@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0desktop\windows\Connect-Server.ps1" %*
if errorlevel 1 pause
