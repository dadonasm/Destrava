# -*- coding: utf-8 -*-
"""Painel da Home: estado vazio, números que batem com os arquivos, pendências e modo compacto."""
import datetime
import json
import os
import shutil
import tempfile
import unittest

from nucleo import ficha
from nucleo import perfil

A, B, C = "DD-TESTE-000A", "DD-TESTE-000B", "DD-TESTE-000C"
GB = 1024 ** 3


class Painel(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="destrava_painel_")
        self._store, self._pasta = ficha.STORE, perfil.PASTA
        ficha.STORE, perfil.PASTA = os.path.join(self.tmp, "maquinas"), self.tmp

    def tearDown(self):
        ficha.STORE, perfil.PASTA = self._store, self._pasta
        shutil.rmtree(self.tmp, ignore_errors=True)

    def historico(self, mid, eventos):
        os.makedirs(ficha.pasta(mid), exist_ok=True)
        with open(os.path.join(ficha.pasta(mid), "historico.json"), "w", encoding="utf-8") as fh:
            json.dump([{"quando": q, "tipo": t, "resumo": r, "extra": x} for q, t, r, x in eventos], fh)

    def tres_maquinas(self):
        # A: 40 → 70 com 2 melhorias, 3 GB limpos, backup de 100 GB, entregue
        ficha.hist_add(A, "ficha", "Ficha coletada: nota 40", {"nota": 40})
        ficha.hist_add(A, "otimizacao", "Melhorias aplicadas: 2 de 2", {"itens": ["x", "y"]})
        ficha.hist_add(A, "ficha_depois", "Ficha após melhorias: nota 70", {"nota": 70})
        ficha.hist_add(A, "limpeza", "Lixeira esvaziada", {"bytes": 3 * GB})
        ficha.hist_add(A, "backup", "Backup sem falhas: 10 arquivos (100,00 GB) · código X", {"status": "sem_falhas", "bytes": 100 * GB})
        ficha.marcar_etapa(A, "entregue")
        # B: 50 → 45 com 1 melhoria; backup antigo (tamanho só no texto) e ainda não entregue
        self.historico(B, [("2026-09-01 10:00", "ficha", "Ficha coletada: nota 50", {"nota": 50}),
                           ("2026-09-01 10:30", "otimizacao", "Melhorias aplicadas: 1 de 3", {"itens": ["z"]}),
                           ("2026-09-01 10:40", "ficha_depois", "Ficha após melhorias: nota 45", {"nota": 45}),
                           ("2026-09-01 12:00", "backup", "Backup sem falhas: 5 arquivos (10,00 GB) · código Y", {})])
        # C: só o termo
        ficha.hist_add(C, "termo", "Termo aceito", {"tecnico": "Marlos"})

    def test_sem_maquinas_e_vazio(self):
        p = ficha.painel_resumo("")
        self.assertEqual(p["maquinas"], 0)
        self.assertEqual((p["nota"]["n"], p["otimizacao"]["taxa"], p["espaco"], p["pendencias"], p["ultimas"]), (0, None, 0, [], []))

    def test_numeros_batem_com_os_arquivos(self):
        self.tres_maquinas()
        p = ficha.painel_resumo("", datetime.datetime.now())
        self.assertEqual((p["maquinas"], p["em_andamento"]), (3, 2))
        self.assertEqual((p["concluidos"], p["concluidos_mes"], p["maquinas_concluidas"]), (1, 1, 1))
        self.assertEqual(p["nota"], {"n": 2, "antes": 45.0, "depois": 57.5})
        self.assertEqual(p["otimizacao"], {"n": 2, "subiu": 1, "taxa": 50, "pontos": 12.5}, "só A subiu: (30 + -5) / 2")
        self.assertEqual((p["espaco"], p["espaco_maquinas"]), (3 * GB, 1))
        self.assertEqual((p["protegido"], p["backups"], p["backup_maquinas"]), (110 * GB, 2, 2), "o backup antigo entra pelo tamanho do texto")
        self.assertEqual([x["mid"] for x in p["ultimas"]][-1], B, "a mais antiga por último")

    def test_concluido_de_outro_mes_nao_conta_no_mes(self):
        self.tres_maquinas()
        p = ficha.painel_resumo("", datetime.datetime.now() + datetime.timedelta(days=40))
        self.assertEqual((p["concluidos"], p["concluidos_mes"]), (1, 0))

    def test_pendencia_de_backup_sem_entrega(self):
        self.tres_maquinas()
        self.assertEqual([(x["mid"], x["pendencia"]) for x in ficha.painel_resumo("")["pendencias"]], [(B, "Backup feito e ainda não entregue")])
        ficha.marcar_etapa(B, "entregue")
        self.assertEqual(ficha.painel_resumo("")["pendencias"], [])

    def test_compacto_na_primeira_maquina_do_dia(self):
        self.historico(B, [("2026-09-01 10:00", "ficha", "Ficha coletada: nota 50", {"nota": 50})])
        ficha.hist_add(C, "termo", "Termo aceito")
        self.assertTrue(ficha.painel_resumo(C)["compacto"], "só a máquina atual mexeu hoje")
        self.assertFalse(ficha.painel_resumo(B)["compacto"], "outra máquina já foi atendida hoje")


if __name__ == "__main__":
    unittest.main()
