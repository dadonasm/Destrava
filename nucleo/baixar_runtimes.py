#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Destrava! - baixa (uma vez) o Python fixo que o servidor entrega a cada computador.

O mesmo Python 3.12.10 em Windows, Mac e Linux: a nota do processador (um teste em Python) fica comparável
entre máquinas. Grava em runtimes/ e anota o SHA-256 de cada arquivo em runtimes/runtimes.json; os scripts
de início conferem esse hash depois de baixar.

    python3 baixar_runtimes.py
"""
import hashlib
import json
import os
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
# o servidor lê de runtimes/ na raiz do projeto (ou de DESTRAVA_RUNTIMES)
DEST = os.environ.get("DESTRAVA_RUNTIMES") or os.path.join(os.path.dirname(HERE), "runtimes")
PY = "3.12.10"
PBS = "20250409"  # versão do python-build-standalone (Mac e Linux) que traz o Python 3.12.10
PBS_URL = "https://github.com/astral-sh/python-build-standalone/releases/download/%s/" % PBS
ALVOS = {
    "windows-amd64": ("python-%s-embed-amd64.zip" % PY, "https://www.python.org/ftp/python/%s/python-%s-embed-amd64.zip" % (PY, PY)),
    "mac-arm64": ("cpython-%s+%s-aarch64-apple-darwin-install_only.tar.gz" % (PY, PBS), None),
    "mac-x86_64": ("cpython-%s+%s-x86_64-apple-darwin-install_only.tar.gz" % (PY, PBS), None),
    "linux-x86_64": ("cpython-%s+%s-x86_64-unknown-linux-gnu-install_only.tar.gz" % (PY, PBS), None),
}


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def baixar(url, destino):
    tmp = destino + ".part"
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Destrava"}), timeout=120) as r, open(tmp, "wb") as fh:
        while True:
            b = r.read(1 << 20)
            if not b:
                break
            fh.write(b)
    os.replace(tmp, destino)


def main():
    os.makedirs(DEST, exist_ok=True)
    print("Conferindo a lista oficial de hashes do python-build-standalone %s..." % PBS)
    with urllib.request.urlopen(urllib.request.Request(PBS_URL + "SHA256SUMS", headers={"User-Agent": "Destrava"}), timeout=60) as r:
        oficiais = {}
        for ln in r.read().decode("utf-8").splitlines():
            partes = ln.split()
            if len(partes) == 2:
                oficiais[partes[1].lstrip("*")] = partes[0].lower()
    saida = {}
    for nome, (arq, url) in ALVOS.items():
        p = os.path.join(DEST, arq)
        if os.path.isfile(p) and os.path.getsize(p) > 0:
            print("%-14s já baixado" % nome)
        else:
            print("%-14s baixando %s..." % (nome, arq))
            baixar(url or PBS_URL + arq, p)
        h = sha256(p)
        if url is None and oficiais.get(arq) != h:
            os.remove(p)
            sys.exit("ERRO: %s não confere com o hash oficial. Apaguei o arquivo; rode de novo." % arq)
        saida[nome] = {"arquivo": arq, "sha256": h, "python": PY, "origem": url or PBS_URL + arq}
    with open(os.path.join(DEST, "runtimes.json"), "w", encoding="utf-8") as fh:
        json.dump(saida, fh, indent=1)
    print("Pronto: %d Pythons em %s" % (len(saida), DEST))


if __name__ == "__main__":
    main()
