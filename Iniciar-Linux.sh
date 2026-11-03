#!/bin/sh
# Destrava! - Linux/macOS.   Uso:  sudo sh Iniciar-Linux.sh
cd "$(dirname "$0")" || exit 1
PY=""
for c in python3 python; do command -v "$c" >/dev/null 2>&1 && PY="$c" && break; done
[ -z "$PY" ] && { echo "Python 3 nao encontrado. Instale:  sudo apt install python3"; exit 1; }
# como administrador ja na abertura (le todos os usuarios, slots de RAM e saude do disco); DESTRAVA_SEM_ADM=1 abre sem
if [ "$(id -u)" != "0" ] && [ -z "$DESTRAVA_SEM_ADM" ] && command -v sudo >/dev/null 2>&1; then
  echo "Pedindo a senha de administrador (para abrir sem: DESTRAVA_SEM_ADM=1 sh Iniciar-Linux.sh)"
  exec sudo sh "$0" "$@"
fi
# no projeto o programa fica em nucleo/ (os dados continuam aqui, em maquinas/); no pendrive fica tudo nesta pasta
[ -f nucleo/dd_backup.py ] && exec "$PY" nucleo/dd_backup.py --dados . "$@"
exec "$PY" dd_backup.py "$@"
