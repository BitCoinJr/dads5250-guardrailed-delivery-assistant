@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Start_Demo.ps1"
if errorlevel 1 pause
