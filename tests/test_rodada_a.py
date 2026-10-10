# -*- coding: utf-8 -*-
"""Rodada A: coleta salva (reproduzir outra máquina), pasta de dados, termo por modo e normalização do Windows."""
import os
import shutil
import tempfile
import unittest

from nucleo import dados
from nucleo import ficha
from nucleo import termo

AQUI = os.path.dirname(os.path.abspath(__file__))
WIN10_HD = os.path.join(AQUI, "fixtures", "win10_hd.json")


class ComPastaTemporaria(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="destrava_teste_")
        self._store, self._log = ficha.STORE, termo.LOG
        ficha.STORE = os.path.join(self.tmp, "maquinas")
        termo.LOG = os.path.join(self.tmp, "consentimentos.log")

    def tearDown(self):
        ficha.STORE, termo.LOG = self._store, self._log
        ficha.REPLAY.clear()
        ficha.ULTIMA.clear()
        ficha._MID.clear()
        termo.MODO = "pendrive"
        shutil.rmtree(self.tmp, ignore_errors=True)


class NormalizarWindows(unittest.TestCase):
    def setUp(self):
        import json
        with open(WIN10_HD, encoding="utf-8") as fh:
            d = json.load(fh)
        self.f = ficha.normalizar_windows(d["raw"], d["medidas"])

    def test_hardware(self):
        f = self.f
        self.assertEqual(f["so"]["familia"], "windows")
        self.assertTrue(f["so"]["nome"].startswith("Windows 10"))
        self.assertAlmostEqual(f["ram"]["total_gb"], 3.91, places=1)
        self.assertEqual(f["ram"]["slots_total"], 2)
        self.assertEqual(f["discos"][0]["tipo"], "HDD")
        self.assertEqual(f["cpu"]["nucleos"], 2)
        self.assertEqual(f["bateria"]["saude_pct"], 55)

    def test_medidas_e_inicializacao(self):
        f = self.f
        self.assertEqual(f["medidas"]["boot_s"], 98.5)
        self.assertEqual(len(f["inicializacao"]), 5, "só os ativos (o Adobe está desativado)")
        self.assertEqual(f["pesados"][0]["nome"], "chrome")

    def test_nota(self):
        p = ficha.pontuar(self.f)
        self.assertTrue(0 <= p["geral"] <= 100)
        self.assertEqual({i["id"] for i in p["itens"]}, {"cpu", "ram", "disco", "resposta", "boot", "inicio", "espaco"})
        self.assertEqual(p["cobertura"], 100)


class ColetaSalva(ComPastaTemporaria):
    def test_reproduz_windows_e_simula(self):
        ficha.carregar_coleta(WIN10_HD)
        self.assertTrue(ficha.simulando())
        self.assertEqual(ficha.familia_atual(), "windows")
        f = ficha.coletar()
        self.assertEqual(f["host"], "PC-RECEPCAO")
        self.assertEqual(f["mid"], ficha.machine_id_cache(), "o código da máquina reproduzida tem que bater, senão a ficha fica só leitura")
        ficha.salvar_ficha(f)
        from nucleo import otimizacoes
        sug = {d["id"]: d for d in otimizacoes.sugestoes(f)}
        self.assertIn("win.visual", sug)
        res = ficha.aplicar(f["mid"], ["win.visual"], f)
        self.assertTrue(res[0]["ok"])
        self.assertIn("Simulado", res[0]["msg"])
        self.assertEqual(ficha.pode_desfazer(f["mid"]), 1)
        self.assertEqual(ficha.desfazer(f["mid"]), 1)

    def test_exportar_e_ler_de_volta(self):
        ficha.carregar_coleta(WIN10_HD)
        f = ficha.coletar()
        ficha.REPLAY.clear()
        ficha.ULTIMA.update(familia="windows", host=f["host"], cpu=f["cpu"]["modelo"], ids=f["ids"], ficha=f, raw={"x": 1}, medidas={})
        arq = ficha.exportar_coleta(os.path.join(self.tmp, "coleta.json"), "3.1")
        d = ficha.carregar_coleta(arq)
        self.assertEqual(d["host"], "PC-RECEPCAO")
        self.assertEqual(d["ids"]["serial"], "5BQ4ZJ1")

    def test_arquivo_invalido(self):
        p = os.path.join(self.tmp, "x.json")
        with open(p, "w") as fh:
            fh.write('{"qualquer": 1}')
        with self.assertRaises(ValueError):
            ficha.carregar_coleta(p)
        self.assertFalse(ficha.simulando())


class PastaDeDados(ComPastaTemporaria):
    def test_dados_ficam_na_pasta_escolhida(self):
        from nucleo import dd_backup
        alvo = os.path.join(self.tmp, "outra")
        dd_backup.usar_pasta_dados(alvo)
        self.assertEqual(ficha.STORE, os.path.join(alvo, "maquinas"))
        self.assertEqual(termo.LOG, os.path.join(alvo, "consentimentos.log"))
        ficha.hist_add("DD-TESTE-0001", "nota", "teste")
        self.assertTrue(os.path.isfile(os.path.join(alvo, "maquinas", "DD-TESTE-0001", "historico.json")))


class TermoPorModo(unittest.TestCase):
    def tearDown(self):
        termo.MODO = "pendrive"

    def test_texto_e_selo_mudam_com_o_modo(self):
        self.assertEqual(termo.TERMO_VERSAO, "1.1")
        termo.MODO = "pendrive"
        txt_p, h_p = termo.termo_texto(), termo.termo_hash()
        termo.MODO = "servidor"
        txt_s, h_s = termo.termo_texto(), termo.termo_hash()
        self.assertIn("neste pendrive", txt_p)
        self.assertIn("servidor da D&D Technology", txt_s)
        self.assertNotEqual(h_p, h_s)
        self.assertIn("Destrava!", txt_s)
        self.assertEqual(len(termo.clausulas()), len(termo.TERMO))


class ZonaVermelha(unittest.TestCase):
    def setUp(self):
        self.h = tempfile.mkdtemp(prefix="destrava_home_")
        dados.set_helpers(user_home=lambda: self.h)

    def tearDown(self):
        dados.set_helpers(user_home=None)
        shutil.rmtree(self.h, ignore_errors=True)

    def test_regras(self):
        j = lambda *p: os.path.join(self.h, *p)
        self.assertIsNone(dados.zona_vermelha(j("Documents", "contrato.pdf")))
        self.assertIsNotNone(dados.zona_vermelha(j(".ssh", "id_rsa")))
        self.assertIsNotNone(dados.zona_vermelha(j("Downloads", "certificado.pfx")))
        self.assertIsNotNone(dados.zona_vermelha(j("Documents")))
        self.assertIsNotNone(dados.zona_vermelha(os.path.dirname(self.h)))

    def test_maiusculas_e_acentos_do_mac(self):
        import unicodedata
        j = lambda *p: os.path.join(self.h, *p)
        self.assertIsNotNone(dados.zona_vermelha(j("Library", "Keychains", "login.keychain-db")))
        self.assertIsNotNone(dados.zona_vermelha(j("Library", "Mail", "V10", "x.emlx")))
        self.assertIsNotNone(dados.zona_vermelha(j("Desktop")))
        self.assertIsNotNone(dados.zona_vermelha(j(unicodedata.normalize("NFD", "Área de Trabalho"))))
        self.assertIsNotNone(dados.zona_vermelha(j("Downloads", "CHAVE.PEM")))
        self.assertIsNone(dados.zona_vermelha(j("Library", "Caches", "com.spotify.client")))


if __name__ == "__main__":
    unittest.main()
