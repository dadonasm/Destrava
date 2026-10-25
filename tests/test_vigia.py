# -*- coding: utf-8 -*-
"""Vigilante durante a cópia: parada, lenta, destino sumido, falta de espaço e falhas iguais (com relógio simulado)."""
import os
import shutil
import tempfile
import time
import unittest
import unittest.mock as um

from nucleo import dd_backup


class Relogio(object):
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t

    def dorme(self, s):
        self.t += s


class Vigia(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="destrava_vigia_")
        self.app = dd_backup.App()
        self.app.phase = "copying"
        self.app.dest_root = self.tmp
        self.app.cp.update(done_bytes=100, total_bytes=10 * 1048576 * 100, current="C:\\Users\\Ana\\Videos\\filme_gigante.mkv")
        self.app.vigia_id = 1

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def roda(self, passos, durante=None):
        rel, vistos = Relogio(), []

        def dorme(s):
            rel.dorme(s)
            vistos.append(sorted(a["id"] for a in self.app.alertas_ativas()))
            if durante:
                durante(len(vistos), rel)
            if len(vistos) >= passos:
                self.app.phase = "copied"
        with um.patch.object(dd_backup.time, "time", rel), um.patch.object(dd_backup.time, "sleep", dorme):
            self.app._vigia(1)
        return vistos

    def test_parada_avisa_e_espera_ou_pula(self):
        vistos = self.roda(30)
        self.assertNotIn("parada", vistos[10])
        self.assertIn("parada", vistos[28], "45 s sem nenhum byte novo")
        a = next(a for a in self.app.alertas if a["id"] == "parada")
        self.assertIn("filme_gigante.mkv", a["texto"])
        self.assertEqual(a["acoes"], ["pular", "esperar"])

    def test_andando_nao_avisa(self):
        def anda(n, rel):
            self.app.cp["done_bytes"] += 50 * 1048576
        vistos = self.roda(40, anda)
        self.assertTrue(all(v == [] for v in vistos))

    def test_lenta(self):
        def devagar(n, rel):
            self.app.cp["done_bytes"] += 2000  # ~1 KB/s
        vistos = self.roda(40, devagar)
        self.assertIn("lenta", vistos[-1])
        self.assertNotIn("parada", vistos[-1])

    def test_destino_sumiu_pausa_e_retoma_sozinho(self):
        gone = os.path.join(self.tmp, "sumiu")
        self.app.dest_root = gone
        self.app.run_ev.set()

        def volta(n, rel):
            if n == 3:
                os.makedirs(gone)
        vistos = self.roda(6, volta)
        self.assertIn("destino", vistos[1])
        self.assertNotIn("destino", vistos[4], "voltou: o aviso some")
        self.assertTrue(self.app.run_ev.is_set(), "retomou sozinho")

    def test_sem_espaco_pausa_antes_de_falhar(self):
        self.app.run_ev.set()
        with um.patch.object(dd_backup, "disk_usage", return_value=(10 * 1048576, 1048576)):
            vistos = self.roda(3)
        self.assertIn("espaco", vistos[1])
        self.assertFalse(self.app.run_ev.is_set(), "pausou")

    def test_muitas_falhas_iguais(self):
        agora = 1000.0
        for _ in range(25):
            self.app.falhas_recentes.append((agora, "permissao|Edge (navegador)"))
        vistos = self.roda(3)
        self.assertTrue(any(i.startswith("falhas:permissao|Edge") for i in vistos[1]))
        self.assertTrue(any("Edge" in e["texto"] for e in self.app.eventos), "fica para o certificado")

    def test_pular_arquivo_marca_falha_pulado(self):
        arq = os.path.join(self.tmp, "origem.bin")
        with open(arq, "wb") as fh:
            fh.write(b"x" * 100)
        it = dd_backup.Item()
        it.src, it.disp, it.size, it.mtime, it.cat, it.act, it.inc, it.rel = arq, arq, 100, 0, "Videos", "copiar", True, "Disco_C/x/origem.bin"
        self.app.dest_root = os.path.join(self.tmp, "destino")
        self.app.pular = it
        self.app.copy_item(it)
        self.assertEqual((it.status, it.cause), ("falha", "pulado"))
        self.assertFalse(dd_backup.falha_esperada(it), "pular um vídeo pessoal continua sendo falha de verdade")
        self.assertFalse(os.path.exists(os.path.join(self.app.dest_root, "Disco_C", "x", "origem.bin.ddpart")))


if __name__ == "__main__":
    unittest.main()
