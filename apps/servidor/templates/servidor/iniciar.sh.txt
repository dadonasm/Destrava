#!/bin/sh
# Destrava! - iniciar sem pendrive (Mac/Linux), pelo servidor da loja.
# Uso, no Terminal:   curl -fsSL __SERVIDOR__/iniciar.sh | sh
# Baixa o programa e um Python fixo para uma pasta temporaria, roda com sudo, e APAGA tudo ao terminar.
# Fichas, historicos e termos ficam no servidor, nao neste computador.
SERVIDOR='__SERVIDOR__'

if [ ! -r /dev/tty ]; then echo "Rode num Terminal (preciso perguntar a chave)."; exit 1; fi
echo ""
echo "Destrava! - D&D Technology"
printf 'Chave do tecnico: ' > /dev/tty
stty -echo < /dev/tty; read -r CHAVE < /dev/tty; stty echo < /dev/tty; echo > /dev/tty

PASTA=$(mktemp -d "${TMPDIR:-/tmp}/Destrava-XXXXXX") || exit 1
limpar() {
  rm -rf "$PASTA" 2>/dev/null || sudo rm -rf "$PASTA"
  [ -d "$PASTA" ] && echo "Nao consegui apagar $PASTA (apague a pasta)." || echo "Pronto. Os arquivos temporarios do Destrava! foram apagados deste computador."
}
trap limpar EXIT
trap 'exit 130' INT TERM

# a chave vai por arquivo (nunca na linha de comando, que outros usuarios veem)
umask 077
printf 'Authorization: Bearer %s\n' "$CHAVE" > "$PASTA/.h"
printf '%s' "$CHAVE" > "$PASTA/.chave"
CHAVE=""

INFO=$(curl -fsS -H @"$PASTA/.h" "$SERVIDOR/pacote/info?formato=txt") || { echo "Nao consegui entrar: chave errada ou servidor fora do ar."; exit 1; }
campo() { printf '%s\n' "$INFO" | sed -n "s/^$1=//p"; }
if command -v sha256sum >/dev/null 2>&1; then SHA="sha256sum"; else SHA="shasum -a 256"; fi
baixar() {  # url arquivo sha256
  curl -fsS -H @"$PASTA/.h" -o "$2" "$1" || return 1
  [ "$($SHA "$2" | cut -d' ' -f1)" = "$3" ] || { echo "Arquivo corrompido no download: $1"; return 1; }
}

echo "Baixando o Destrava! $(campo versao)..."
baixar "$SERVIDOR/pacote/Destrava.zip" "$PASTA/Destrava.zip" "$(campo sha256)" || exit 1
(cd "$PASTA" && unzip -q Destrava.zip) || { echo "Nao consegui descompactar (falta o unzip?)."; exit 1; }

case "$(uname -s)-$(uname -m)" in
  Darwin-arm64) RT=mac-arm64 ;;
  Darwin-x86_64) RT=mac-x86_64 ;;
  Linux-x86_64) RT=linux-x86_64 ;;
  *) RT="" ;;
esac
PY=""
if [ -n "$RT" ] && [ -n "$(campo "runtime_$RT")" ]; then
  echo "Baixando o Python..."
  baixar "$SERVIDOR/runtime/$RT" "$PASTA/python.tar.gz" "$(campo "runtime_$RT")" || exit 1
  tar -xzf "$PASTA/python.tar.gz" -C "$PASTA" && PY="$PASTA/python/bin/python3"
fi
if [ -z "$PY" ]; then
  if [ "$(uname -s)" = "Darwin" ] && ! xcode-select -p >/dev/null 2>&1; then
    echo "O servidor ainda nao tem o Python para este Mac (rode baixar_runtimes.py no servidor)."; exit 1
  fi
  PY=$(command -v python3) || { echo "Python 3 nao encontrado."; exit 1; }
fi

echo "Abrindo o Destrava! (o sudo pede a senha deste computador)..."
sudo "$PY" "$PASTA/Destrava/dd_backup.py" --servidor "$SERVIDOR" --chave-arquivo "$PASTA/.chave"
