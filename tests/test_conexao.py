# -*- coding: utf-8 -*-
"""Contato com o programa: /api/ping e erros internos registrados em erros.log (o que se manda para diagnosticar)."""
import os
import shutil
import tempfile
import unittest

from nucleo import dd_backup


class Conexao(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="destrava_conexao_")
        self._dados = dd_backup.DADOS_DIR[0]
        dd_backup.DADOS_DIR[0] = self.tmp

    def tearDown(self):
        dd_backup.DADOS_DIR[0] = self._dados
        shutil.rmtree(self.tmp, ignore_errors=True)

    def log(self):
        p = os.path.join(self.tmp, "erros.log")
        return open(p, encoding="utf-8").read() if os.path.exists(p) else ""

    def test_ping(self):
        self.assertEqual(dd_backup.Handler.api_get(None, "/api/ping", {}), {"ok": True})

    def test_erro_vai_para_o_log(self):
        try:
            {}["chave_que_nao_existe"]
        except KeyError:
            dd_backup.registrar_erro("GET /api/teste")
        txt = self.log()
        self.assertIn("GET /api/teste", txt)
        self.assertIn("KeyError", txt)

    def test_conexao_fechada_pelo_navegador_nao_suja_o_log(self):
        try:
            raise ConnectionResetError("o navegador fechou")
        except ConnectionResetError:
            dd_backup.registrar_erro("conexão")
        self.assertEqual(self.log(), "")

    def test_fila_de_conexoes_maior(self):
        self.assertGreaterEqual(dd_backup.Servidor.request_queue_size, 64)


if __name__ == "__main__":
    unittest.main()
