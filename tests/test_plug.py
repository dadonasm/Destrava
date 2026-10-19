# -*- coding: utf-8 -*-
"""Abrir rápido: um Destrava.bat que serve no Windows (duplo clique) e no Linux/Mac (sh), na pasta do programa
ou na raiz do pendrive; autorun.inf e Destrava.ico só dão nome e logo ao pendrive."""
import os
import shutil
import struct
import subprocess
import tempfile
import unittest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FALSO = '#!/bin/sh\necho "RODOU $(basename "$(dirname "$0")") $*"\n'


class AbrirRapido(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="destrava_plug_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def roda(self, onde, crlf=False):
        with open(os.path.join(RAIZ, "Destrava.bat"), "rb") as fh:
            b = fh.read()
        if crlf:
            b = b.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
        with open(os.path.join(onde, "Destrava.bat"), "wb") as fh:
            fh.write(b)
        return subprocess.run(["sh", os.path.join(onde, "Destrava.bat"), "x"], capture_output=True, text=True, timeout=20).stdout

    def programa(self, pasta):
        os.makedirs(pasta, exist_ok=True)
        with open(os.path.join(pasta, "Iniciar-Linux.sh"), "w") as fh:
            fh.write(FALSO)

    def test_na_pasta_do_programa(self):
        self.programa(self.tmp)
        self.assertIn("RODOU", self.roda(self.tmp))
        self.assertIn("RODOU", self.roda(self.tmp, crlf=True), "continua funcionando se o arquivo virar CRLF")

    def test_na_raiz_do_pendrive(self):
        self.programa(os.path.join(self.tmp, "BKP-Pro"))
        self.assertIn("RODOU BKP-Pro x", self.roda(self.tmp))

    def test_sem_programa_avisa(self):
        self.assertNotIn("RODOU", self.roda(self.tmp))

    def test_windows_nao_usa_goto_nem_rotulo(self):
        with open(os.path.join(RAIZ, "Destrava.bat"), encoding="utf-8") as fh:
            linhas = fh.read().splitlines()
        cmd = [x for x in linhas if not x.startswith(":;")]
        self.assertEqual(cmd[0], "@echo off")
        self.assertFalse([x for x in cmd if x.lstrip().lower().startswith(("goto", ":"))], "rótulo/goto quebra no cmd com LF")
        self.assertTrue(any("Iniciar-Windows.bat" in x for x in cmd))

    def test_autorun_e_icone(self):
        with open(os.path.join(RAIZ, "autorun.inf"), "rb") as fh:
            a = fh.read().decode("utf-8")
        self.assertIn("[autorun]", a)
        self.assertIn("icon=Destrava.ico", a)
        self.assertNotIn("open=", a.lower(), "open= é ignorado em pendrive e faz antivírus apagar o arquivo")
        with open(os.path.join(RAIZ, "Destrava.ico"), "rb") as fh:
            ico = fh.read()
        self.assertEqual(ico[:4], b"\x00\x00\x01\x00")
        n = struct.unpack("<H", ico[4:6])[0]
        tamanhos = {ico[6 + 16 * i] or 256 for i in range(n)}
        self.assertTrue({16, 32, 48, 256} <= tamanhos)

    def test_vai_no_pacote_e_na_atualizacao(self):
        with open(os.path.join(RAIZ, "apps", "servidor", "pacote.py"), encoding="utf-8") as fh:
            s = fh.read()
        for n in ("Destrava.bat", "Destrava.ico", "autorun.inf"):
            self.assertIn('"%s"' % n, s)
        from nucleo import atualizador
        self.assertTrue(atualizador._is_code("Destrava.ico") and atualizador._is_code("autorun.inf"))


if __name__ == "__main__":
    unittest.main()
