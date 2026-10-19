:; # Destrava! - D&D Technology.  Windows: duplo clique.  Linux/Mac: sudo sh Destrava.bat
:; d=$(cd "$(dirname "$0")" && pwd); for p in "$d" "$d"/*/; do [ -f "$p/Iniciar-Linux.sh" ] && exec sh "$p/Iniciar-Linux.sh" "$@"; done; echo "Nao achei o Iniciar-Linux.sh perto deste arquivo."; exit 1 #
@echo off
if exist "%~dp0Iniciar-Windows.bat" ( call "%~dp0Iniciar-Windows.bat" %* & exit /b )
for /d %%D in ("%~dp0*") do if exist "%%~fD\Iniciar-Windows.bat" ( call "%%~fD\Iniciar-Windows.bat" %* & exit /b )
echo Nao achei o Iniciar-Windows.bat perto deste arquivo.
pause
