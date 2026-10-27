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

    def test_mac_usuarios_em_users(self):
        mac = os.path.join(self.tmp, "Macintosh HD")
        for p in ("System", "Library", "etc", "usr", "home", os.path.join("Users", "Shared"), os.path.join("Users", ".localized"),
                  os.path.join("Users", "ana", "Documents"), os.path.join("Users", "ana", "Library", "Caches")):
            os.makedirs(os.path.join(mac, p), exist_ok=True)
        for rel in (("Users", "ana", "Documents", "nota.txt"), ("Users", "ana", "Library", "Caches", "lixo.bin")):
            with open(os.path.join(mac, *rel), "w") as fh:
                fh.write("x")
        self.assertEqual(dd_backup.detect_kind(mac), ("mac", ["ana"]), "volume do macOS não é Linux, mesmo com etc/usr/home")
        app = dd_backup.App()
        planos = app.plan_roots({"kind": "mac", "path": mac, "letter": ""})
        self.assertEqual([(p[1], p[2], p[4]) for p in planos], [("ana", "/Users/ana", "macuser")])
        achados = [x[1] for x in app.walk_plan(planos[0])]
        self.assertEqual(achados, ["/Users/ana/Documents/nota.txt"], "Library do usuário fica de fora")
        self.assertIn(("/Users/ana/Library", "Dados do macOS e dos apps (não são arquivos pessoais)"), app.ign_dirs)
        self.assertEqual(dd_backup.detect_kind(self.disco)[0], "windows")


if __name__ == "__main__":
    unittest.main()


class DestinoDepois(OrigensEIdentificacao):
    """A Seleção vem primeiro: escaneia só com a origem; o destino é exigido nas Checagens e na cópia."""

    def test_origem_sem_destino(self):
        app = dd_backup.App()
        cfg = app.set_config({"sources": [{"path": self.disco, "kind": "windows"}]})
        self.assertEqual(cfg["dest"], "")
        self.assertEqual(app.dest_root, "")
        t = app.totals()
        self.assertIsNone(t["cabe"])
        self.assertEqual(t["solucao"], "")
        self.assertEqual(app.preflight()[0]["titulo"], "Falta o destino")
        app.items = [dd_backup.Item()]
        with self.assertRaises(ValueError):
            app.start_copy()
        app.set_config({"sources": [{"path": self.disco, "kind": "windows"}], "dest": self.dest, "folder": "B"})
        self.assertEqual(app.dest_root, os.path.join(self.dest, "B"))

    def test_destino_dentro_da_origem_sai_da_lista(self):
        app = dd_backup.App()
        app.set_config({"sources": [{"path": self.disco, "kind": "windows"}]})
        dentro, fora = dd_backup.Item(), dd_backup.Item()
        dentro.src = os.path.join(self.disco, "Backups", "B", "x.txt")
        fora.src = os.path.join(self.disco, "Users", "Ana", "Documents", "a.txt")
        app.items = [dentro, fora]
        os.makedirs(os.path.join(self.disco, "Backups"))
        app.set_config({"sources": [{"path": self.disco, "kind": "windows"}], "dest": os.path.join(self.disco, "Backups"), "folder": "B"})
        self.assertEqual(app.items, [fora])
