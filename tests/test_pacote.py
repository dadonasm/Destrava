# -*- coding: utf-8 -*-
"""R4: o Destrava.zip só leva o agente, com a forma de sempre (requisito de segurança)."""
import hashlib
import io
import os
import tempfile
import unittest
import zipfile

from tests._django import DJANGO


@unittest.skipUnless(DJANGO, "Django não instalado")
class Pacote(unittest.TestCase):
    def setUp(self):
        from apps.servidor import pacote
        self.pacote = pacote
        self.z, self.sha, self.ver = pacote.pacote()
        self.nomes = zipfile.ZipFile(io.BytesIO(self.z)).namelist()

    def test_so_o_agente(self):
        self.assertTrue(all(n.startswith("Destrava/") for n in self.nomes))
        for n in ("dd_backup.py", "ficha.py", "mapa.py", "disco.py", "conexao.py", "etiquetas.txt", "web/app.html", "Iniciar-Windows.bat", "LEIA-ME.txt"):
            self.assertIn("Destrava/" + n, self.nomes, n)
        proibidos = ("manage.py", "config/", "apps/", "nucleo/", "chaves.json", "servidor-dados", "Dockerfile", "requirements.txt", "pyproject.toml",
                     "__init__.py", "baixar_runtimes.py", "tests/", "static/", ".secret_key", "consentimentos.log", "maquinas/", "runtimes")
        for n in self.nomes:
            for p in proibidos:
                self.assertNotIn(p, n[len("Destrava/"):], n)

    def test_forma_e_hash_estavel(self):
        zi = {i.filename: i for i in zipfile.ZipFile(io.BytesIO(self.z)).infolist()}
        self.assertEqual(zi["Destrava/dd_backup.py"].date_time, (2020, 1, 1, 0, 0, 0))
        self.assertEqual(zi["Destrava/Iniciar-Linux.sh"].external_attr >> 16, 0o755)
        self.assertEqual(self.pacote.pacote()[1], self.sha)
        self.assertEqual(hashlib.sha256(self.z).hexdigest(), self.sha)
        self.assertEqual(self.ver, "3.1")

    def test_serve_de_atualizacao_do_pendrive(self):
        from nucleo import atualizador
        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as fh:
            fh.write(self.z)
        try:
            self.assertEqual(atualizador.inspecionar(fh.name)[1], self.ver)
        finally:
            os.remove(fh.name)


if __name__ == "__main__":
    unittest.main()
