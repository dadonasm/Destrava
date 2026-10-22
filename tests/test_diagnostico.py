# -*- coding: utf-8 -*-
"""Diagnóstico dentro do sistema: erros.log legível, erros da tela, relatório, autoteste e BUILD igual no programa e na página."""
import os
import re
import shutil
import tempfile
import unittest

from nucleo import dd_backup

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class Diagnostico(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="destrava_diag_")
        self._dados = dd_backup.DADOS_DIR[0]
        dd_backup.DADOS_DIR[0] = self.tmp
        dd_backup._TELA_VISTOS.clear()

    def tearDown(self):
        dd_backup.DADOS_DIR[0] = self._dados
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_build_igual_no_programa_e_na_pagina(self):
        with open(os.path.join(RAIZ, "nucleo", "web", "app.html"), encoding="utf-8") as fh:
            pagina = re.search(r'const BUILD="([^"]+)"', fh.read()).group(1)
        self.assertEqual(pagina, dd_backup.BUILD, "ao mudar a versão, mude nos dois")

    def test_erros_log_legivel(self):
        try:
            {}["x"]
        except KeyError:
            dd_backup.registrar_erro("GET /api/teste")
        dd_backup.registrar_erro_tela("x is not defined", "at draw3 (app.html:10)", "backup:2")
        erros = dd_backup.ler_erros()
        self.assertEqual([e["onde"] for e in erros], ["TELA backup:2", "GET /api/teste"], "mais novo primeiro")
        self.assertIn("KeyError", erros[1]["resumo"])
        self.assertIn("x is not defined", erros[0]["texto"])

    def test_erro_da_tela_nao_repete_e_tem_limite(self):
        self.assertTrue(dd_backup.registrar_erro_tela("falhou", "pilha"))
        self.assertFalse(dd_backup.registrar_erro_tela("falhou", "pilha"))
        for i in range(300):
            dd_backup.registrar_erro_tela("erro %d" % i)
        self.assertLessEqual(len(dd_backup.ler_erros(500)), 200)

    def test_rotacao_do_log(self):
        with open(os.path.join(self.tmp, "erros.log"), "w", encoding="utf-8") as fh:
            fh.write("x" * (1024 * 1024 + 10))
        dd_backup._gravar_erro("depois", "novo")
        self.assertTrue(os.path.exists(os.path.join(self.tmp, "erros.log.1")))
        self.assertEqual([e["onde"] for e in dd_backup.ler_erros()], ["depois"])

    def test_autoteste_e_relatorio(self):
        app = dd_backup.App()
        d = app.diagnostico()
        self.assertTrue(d["saudavel"], [t for t in d["testes"] if not t["ok"]])
        self.assertEqual(d["build"], dd_backup.BUILD)
        app.autoteste_pagina = {"build": dd_backup.BUILD, "faltando": ["drawDados"]}
        d = app.diagnostico()
        self.assertFalse(d["saudavel"])
        self.assertIn("drawDados", [t for t in d["testes"] if not t["ok"]][0]["detalhe"])
        app.log("linha do registro")
        r = app.relatorio()
        self.assertIn("RELATÓRIO DO DESTRAVA!", r["texto"])
        self.assertIn("linha do registro", r["texto"])
        self.assertTrue(os.path.isfile(r["arquivo"]) and os.path.basename(os.path.dirname(r["arquivo"])) == "Erros")

    def test_autoteste_pega_versoes_misturadas(self):
        antes = dd_backup.BUILD
        try:
            dd_backup.BUILD = "0000-00-00.0"
            falhou = [t for t in dd_backup.autoteste_servidor() if not t["ok"]]
            self.assertTrue(any("mesma versão" in t["titulo"] for t in falhou))
        finally:
            dd_backup.BUILD = antes

    def test_pasta_de_dados_sem_gravar_e_apontada(self):
        dd_backup.DADOS_DIR[0] = os.path.join(self.tmp, "nao_existe", "sub")
        falhou = [t for t in dd_backup.autoteste_servidor() if not t["ok"]]
        self.assertTrue(any("não grava" in t["titulo"] for t in falhou))


if __name__ == "__main__":
    unittest.main()
