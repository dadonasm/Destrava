# -*- coding: utf-8 -*-
"""Ilha do topo: /api/atividades junta o que está rodando (análise, backup, Dados, conferência, envios) e como cada um terminou."""
import copy
import unittest

from nucleo import dd_backup
from nucleo import dados
from nucleo import mapa


class Atividades(unittest.TestCase):
    def setUp(self):
        self._app, self._ft = dd_backup.APP, dict(dd_backup.FT)
        self._st, self._conf, self._con = copy.deepcopy(dados.ST), copy.deepcopy(mapa.CONF), dd_backup.SERVIDOR["con"]
        self.app = dd_backup.App()
        self.app.run_ev.set()
        dd_backup.APP = self.app

    def tearDown(self):
        dd_backup.APP = self._app
        dd_backup.FT.clear()
        dd_backup.FT.update(self._ft)
        dados.ST.clear()
        dados.ST.update(self._st)
        mapa.CONF.clear()
        mapa.CONF.update(self._conf)
        dd_backup.SERVIDOR["con"] = self._con

    def ids(self):
        return [a["id"] for a in dd_backup.atividades()["atividades"]]

    def item(self, id_):
        return next(a for a in dd_backup.atividades()["atividades"] if a["id"] == id_)

    def test_nada_rodando(self):
        self.assertEqual(dd_backup.atividades()["atividades"], [])

    def test_analise_e_melhorias(self):
        dd_backup.FT.update(rodando=True, etapa="Medindo disco", pct=55, o_que="coletar")
        self.assertEqual((self.item("ficha")["titulo"], self.item("ficha")["pct"], self.item("ficha")["tela"]), ("Analisando a máquina", 55, "home"))
        dd_backup.FT.update(o_que="aplicar")
        self.assertEqual(self.item("ficha")["titulo"], "Aplicando melhorias")

    def test_backup_em_cada_fase(self):
        self.app.phase = "scanning"
        self.app.scan_info.update(files=120, current="C:/Users/Ana")
        b = self.item("backup")
        self.assertEqual((b["titulo"], b["pct"], b["info"], b["fase"]), ("Escaneando para o backup", None, "120 arquivos achados", "scanning"))
        self.app.phase = "copying"
        self.app.cp.update(done_bytes=50, total_bytes=200, done_files=1, total_files=4, current="Ana/Fotos/a.jpg")
        b = self.item("backup")
        self.assertEqual((b["pct"], b["info"], b["detalhe"], b["pausado"]), (25, "1 de 4 arquivos", "Ana/Fotos/a.jpg", False))
        self.app.run_ev.clear()
        self.assertTrue(self.item("backup")["pausado"])
        self.app.phase = "verifying"
        self.app.vf.update(done=3, total=4, bytes_done=0, bytes_total=0)  # verificação rápida: sem bytes, conta arquivos
        self.assertEqual(self.item("backup")["pct"], 75)
        self.app.phase = "copied"
        self.assertNotIn("backup", self.ids(), "entre as etapas nada está rodando")

    def test_dados_conferencia_e_envios(self):
        dados.ST.update(fase="varrendo", pct=40, arquivos=900, atual="/Users/ana/Downloads")
        self.assertEqual((self.item("dados")["titulo"], self.item("dados")["pct"]), ("Procurando o que pesa", 40))
        dados.ST.update(fase="pronto")
        dados.ST["acao"] = dict(dados.ST["acao"], rodando=True, tipo="limpar", feito=2, total=8, bytes_feito=10, bytes_total=40, atual="x.tmp")
        self.assertEqual((self.item("dados")["titulo"], self.item("dados")["pct"], self.item("dados")["info"]), ("Limpando arquivos", 25, "2 de 8"))
        mapa.CONF.update(rodando=True, feitos=5, total=20)
        self.assertEqual((self.item("conferencia")["pct"], self.item("conferencia")["tela"]), (25, "mapas"))

        class Con(object):
            pendentes = {("DD-1", "historico.json"): "/tmp/x"}
        dd_backup.SERVIDOR["con"] = Con()
        self.assertEqual(self.item("envio")["info"], "1 pendente(s)")
        self.assertEqual(self.ids(), ["dados", "conferencia", "envio"])

    def test_como_terminou(self):
        dd_backup.FT.update(rodando=False, erro="Sem permissão")
        mapa.CONF.update(rodando=False, diferentes=["a"], faltando=[])
        self.app.phase, self.app.error = "error", "Traceback"
        fim = dd_backup.atividades()["fim"]
        self.assertEqual((fim["ficha"]["erro"], fim["conferencia"]["diferentes"], fim["backup"]), ("Sem permissão", 1, {"fase": "error", "erro": True}))


if __name__ == "__main__":
    unittest.main()
