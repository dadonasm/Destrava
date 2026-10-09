#!/bin/sh
# Destrava! - teste no proprio computador (Mac/Linux), sem pendrive.
# Fichas e consentimentos ficam em ./_dev (fora do git).   Uso:  sh testar-local.sh   (Linux: sudo sh testar-local.sh)
#   sh testar-local.sh --coleta-salva arquivo.json   reproduz a coleta de outra maquina (acoes so simuladas)
cd "$(dirname "$0")" || exit 1
PY=""
for c in python3 python; do command -v "$c" >/dev/null 2>&1 && PY="$c" && break; done
[ -z "$PY" ] && { echo "Python 3 nao encontrado."; exit 1; }
exec "$PY" dd_backup.py --dados ./_dev "$@"
