# -*- coding: utf-8 -*-
"""Backup que não deixa nada importante para trás (tipos desconhecidos, dados de apps, bancos de sistemas),
conferência lendo do disco e o Mapa dentro do programa."""
import hashlib
import os
import shutil
import tempfile
import time
import unittest

import dd_backup
import disco
import ficha
import mapa


def escreve(p, dados=b"x"):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "wb") as fh:
        fh.write(dados)


def espera(app, fases, limite=30):
    t = time.time()
    while app.phase not in fases and time.time() - t < limite:
        time.sleep(0.05)
    return app.phase


class BackupCompleto(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="destrava_bkp_")
        self.disco = os.path.join(self.tmp, "C")  # um "disco do Windows" de mentira
        j = lambda *p: os.path.join(self.disco, *p)
        os.makedirs(j("Windows"))
        escreve(j("Users", "Ana", "Documents", "contrato.pdf"), b"%PDF contrato")
        escreve(j("Users", "Ana", "Documents", "planilha.xyz"), b"tipo que o programa nao conhece")
        escreve(j("Users", "Ana", "Pictures", "foto.jpg"), b"\xff\xd8\xff" + b"1" * 3000)
        escreve(j("Users", "Ana", "AppData", "Roaming", "Thunderbird", "Profiles", "x.default", "Mail", "Inbox"), b"From: cliente")
        escreve(j("Users", "Ana", "AppData", "Roaming", "Thunderbird", "Profiles", "x.default", "cache2", "lixo"), b"cache")
        escreve(j("Users", "Ana", "AppData", "Local", "Microsoft", "Outlook", "Ana.pst"), b"pst" * 100)
        escreve(j("Users", "Ana", "AppData", "Local", "Temp", "x.tmp"), b"temp")
        escreve(j("Program Files (x86)", "LojaX", "dados", "LOJA.FDB"), b"F" * 70000)
        escreve(j("Program Files", "Microsoft", "x.mdb"), b"M" * 70000)
        escreve(j("ProgramData", "Contab", "pequeno.dbf"), b"d" * 100)
        escreve(j("ProgramData", "Contab", "empresa.dbf"), b"D" * 70000)
        self.dest = os.path.join(self.tmp, "HD_externo")
        os.makedirs(self.dest)
        self._store = ficha.STORE
        ficha.STORE = os.path.join(self.tmp, "maquinas")
        self.app = dd_backup.App()
        self.app.set_config({"sources": [{"path": self.disco, "kind": "windows", "letter": "C"}], "dest": self.dest, "folder": "Backup_Ana", "cliente": "Ana"})

    def tearDown(self):
        ficha.STORE = self._store
        mapa.CANCEL.set()
        mapa.M.update(raiz="", mapa="", meta={}, f=[], partes=[], cert={})
        shutil.rmtree(self.tmp, ignore_errors=True)

    def escanear(self):
        self.app.start_scan()
        self.assertEqual(espera(self.app, ("scanned", "error")), "scanned", self.app.error)
        return {os.path.basename(it.src): it for it in self.app.items}

    def test_nada_importante_fica_para_tras(self):
        it = self.escanear()
        self.assertTrue(it["planilha.xyz"].inc, "tipo desconhecido agora vai junto")
        self.assertEqual(it["Inbox"].cat, "Dados_de_apps")
        self.assertIn("Ana/Dados_de_apps/Thunderbird/x.default/Mail/Inbox", it["Inbox"].rel)
        self.assertNotIn("lixo", it, "cache do Thunderbird não vai")
        self.assertTrue(it["Ana.pst"].inc)
        self.assertNotIn("x.tmp", it, "o resto da AppData continua de fora")
        self.assertEqual(it["LOJA.FDB"].cat, "Sistemas")
        self.assertEqual(it["LOJA.FDB"].rel, "Disco_C/Sistemas/Program Files (x86)/LojaX/dados/LOJA.FDB", "caminho original preservado")
        self.assertIn("empresa.dbf", it)
        self.assertNotIn("x.mdb", it, "pasta de fabricante (Microsoft) é pulada")
        self.assertNotIn("pequeno.dbf", it, "arquivo minúsculo não é banco de dados de sistema")

    def test_backup_mapa_e_conferencia(self):
        self.escanear()
        self.app.start_copy()
        self.assertEqual(espera(self.app, ("copied", "error")), "copied", self.app.error)
        self.app.start_verify("completa")
        self.assertEqual(espera(self.app, ("verified", "error")), "verified", self.app.error)
        cert = self.app.finish()
        self.assertEqual(cert["status"], "sem_falhas")
        self.assertIn(disco.METODO, cert["metodo"])
        r = mapa.carregar(os.path.join(self.dest, "Backup_Ana"))
        self.assertEqual(r["contagem"]["falha"], 0)
        self.assertGreaterEqual(r["contagem"]["ok"], 7)
        a = mapa.arvore("")
        self.assertEqual([p["nome"] for p in a["pastas"]], ["C:"])
        docs = mapa.arvore("C:/Users/Ana/Documents")
        pdf = [x for x in docs["arquivos"] if x["nome"] == "contrato.pdf"][0]
        self.assertTrue(pdf["no_backup"] and pdf["previa"] == "pdf")
        self.assertTrue(mapa.caminho(pdf["i"]).endswith("contrato.pdf"))
        busca = mapa.buscar("loja.fdb")
        self.assertEqual(busca["total"], 1)
        mapa.conferir()
        while mapa.CONF["rodando"]:
            time.sleep(0.05)
        self.assertEqual((mapa.CONF["n_diferentes"] if "n_diferentes" in mapa.CONF else len(mapa.CONF["diferentes"]), len(mapa.CONF["faltando"])), (0, 0))
        # alguém mexeu num arquivo do backup: a conferência acusa
        with open(mapa.caminho(pdf["i"]), "ab") as fh:
            fh.write(b"alterado")
        mapa.conferir()
        while mapa.CONF["rodando"]:
            time.sleep(0.05)
        self.assertEqual(len(mapa.CONF["diferentes"]), 1)

    def test_mapa_nao_sai_da_pasta_do_backup(self):
        self.escanear()
        self.app.start_copy()
        espera(self.app, ("copied", "error"))
        self.app.start_verify("rapida")
        espera(self.app, ("verified", "error"))
        self.app.finish()
        mapa.carregar(os.path.join(self.dest, "Backup_Ana", "Mapa"))
        fora = [i for i, e in enumerate(mapa.M["f"]) if e[mapa.ST_] != "ok"]
        if fora:
            with self.assertRaises(ValueError):
                mapa.caminho(fora[0])
        mapa.M["f"][0] = list(mapa.M["f"][0])
        mapa.M["f"][0][mapa.D_] = "../../fora.txt"
        mapa.M["f"][0][mapa.ST_] = "ok"
        with self.assertRaises(ValueError):
            mapa.caminho(0)


class LeituraDoDisco(unittest.TestCase):
    def test_mesmo_hash(self):
        fd, p = tempfile.mkstemp()
        os.write(fd, os.urandom(9 * 1024 * 1024 + 123))
        os.close(fd)
        try:
            with open(p, "rb") as fh:
                self.assertEqual(disco.sha256(p), hashlib.sha256(fh.read()).hexdigest())
        finally:
            os.remove(p)


if __name__ == "__main__":
    unittest.main()
