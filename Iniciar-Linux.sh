#!/bin/sh
# BKP Pro - Linux/macOS.   Uso:  sudo sh Iniciar-Linux.sh
cd "$(dirname "$0")" || exit 1
PY=""
for c in python3 python; do command -v "$c" >/dev/null 2>&1 && PY="$c" && break; done
[ -z "$PY" ] && { echo "Python 3 nao encontrado. Instale:  sudo apt install python3"; exit 1; }
[ "$(id -u)" != "0" ] && echo "Dica: use  sudo sh Iniciar-Linux.sh  para ler slots de RAM, saude do disco e todos os usuarios."
exec "$PY" dd_backup.py "$@"
