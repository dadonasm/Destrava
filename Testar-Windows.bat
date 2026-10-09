@echo off
chcp 65001 >nul
title Destrava! (TESTE) - D&D Technology
rem Teste no proprio computador, sem pendrive: fichas e consentimentos ficam em %USERPROFILE%\Destrava-teste
pushd "%~dp0"
net session >nul 2>&1
if %errorlevel% neq 0 (
  echo Pedindo permissao de administrador...
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)
set "DADOS=%USERPROFILE%\Destrava-teste"
echo Modo de teste: fichas e consentimentos ficam em "%DADOS%".
if exist "runtime\python.exe" (
  "runtime\python.exe" dd_backup.py --dados "%DADOS%"
  goto fim
)
where py >nul 2>&1 && ( py -3 dd_backup.py --dados "%DADOS%" & goto fim )
where python >nul 2>&1 && ( python dd_backup.py --dados "%DADOS%" & goto fim )
echo.
echo Python nao encontrado. Instale em https://www.python.org/downloads/windows/
echo (marque "Add python.exe to PATH") ou coloque o Python portatil em runtime\python.exe.
:fim
popd
echo.
pause
