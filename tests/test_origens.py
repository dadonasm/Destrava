# -*- coding: utf-8 -*-
"""Origens sem repetição e identificação do certificado vinda do cadastro."""
import os
import shutil
import tempfile
import unittest

from nucleo import dd_backup
from nucleo import ficha
from nucleo import perfil
from nucleo import termo


class OrigensEIdentificacao(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="destrava_origens_")
        self._salvo = ficha.STORE, termo.LOG, perfil.PASTA, termo.detectar_corporativa
        ficha.STORE, termo.LOG, perfil.PASTA = os.path.join(self.tmp, "maquinas"), os.path.join(self.tmp, "consentimentos.log"), self.tmp
        termo.detectar_corporativa = lambda: {"corporativa": False, "sinais": []}
        self.disco = os.path.join(self.tmp, "C")
        for p in ("Windows", os.path.join("Users", "Ana", "Documents")):
            os.makedirs(os.path.join(self.disco, p))
        self.dest = os.path.join(self.tmp, "HD")
        os.makedirs(self.dest)

    def tearDown(self):
        ficha.STORE, termo.LOG, perfil.PASTA, termo.detectar_corporativa = self._salvo
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_dentro(self):
        self.assertTrue(dd_backup._dentro(os.path.join(self.disco, "Users", "Ana"), self.disco))
        self.assertTrue(dd_backup._dentro(self.disco, self.disco))
        self.assertFalse(dd_backup._dentro(self.disco + "2", self.disco), "C2 não está dentro de C")

    def test_origem_dentro_de_outra_sai(self):
        cfg = dd_backup.App().set_config({"sources": [{"path": self.disco, "kind": "windows"}, {"path": os.path.join(self.disco, "Users", "Ana"), "kind": "folder"}],
                                           "dest": self.dest, "folder": "B"})
        self.assertEqual([s["path"] for s in cfg["sources"]], [os.path.abspath(self.disco)])

    def test_identificacao_vem_do_cadastro(self):
        app = dd_backup.App()
        mid = ficha.machine_id_cache()
        termo.aceitar(mid, "Marlos Dadonas", "terceiros", terceiro_nome="Padaria da Ana")
        ficha.meta_set(mid, nome="Notebook da padaria")
        cfg = app.set_config({"sources": [{"path": self.disco, "kind": "windows"}], "dest": self.dest, "folder": "B",
                              "cliente": "digitado", "tecnico": "digitado", "equip": "digitado"})
        self.assertEqual((cfg["cliente"], cfg["tecnico"], cfg["equip"]), ("Padaria da Ana", "Marlos Dadonas", "Notebook da padaria"))
        perfil.salvar({"nome": "Marlos D&D", "no_certificado": ["nome"]})
        self.assertEqual(app.identificacao()["tecnico"], "Marlos D&D", "o perfil do técnico vale mais que o nome do termo")


if __name__ == "__main__":
    unittest.main()
