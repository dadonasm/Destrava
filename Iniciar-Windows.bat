@echo off
chcp 65001 >nul
title Destrava! - D&D Technology
cd /d "%~dp0"
net session >nul 2>&1
if %errorlevel% neq 0 (
  echo Pedindo permissao de administrador...
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)
if exist "runtime\python.exe" (
  "runtime\python.exe" dd_backup.py
  goto fim
)
where py >nul 2>&1 && ( py -3 dd_backup.py & goto fim )
where python >nul 2>&1 && ( python dd_backup.py & goto fim )
echo.
echo Python nao encontrado. Faca UMA vez: baixe "Windows embeddable package (64-bit)" em
echo https://www.python.org/downloads/windows/  e extraia DENTRO da pasta "runtime" deste pendrive.
echo (o arquivo python.exe deve ficar em runtime\python.exe)
:fim
echo.
pause
