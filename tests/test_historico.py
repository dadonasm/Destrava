# -*- coding: utf-8 -*-
"""Correção do histórico da máquina: o texto muda, o original e quem corrigiu ficam guardados."""
import os
import shutil
import tempfile
import unittest

from nucleo import ficha


class CorrigirHistorico(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="destrava_hist_")
        self._salvo = ficha.STORE
        ficha.STORE = os.path.join(self.tmp, "maquinas")
        self.mid = "DD-TEST-0001"
        ficha.hist_add(self.mid, "nota", "Cliente pediu backup do Outlok", {"tecnico": "Ana"})
        ficha.hist_add(self.mid, "nota", "Segunda nota", {"tecnico": "Ana"})

    def tearDown(self):
        ficha.STORE = self._salvo
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_guarda_o_original(self):
        ficha.hist_corrigir(self.mid, 0, "Cliente pediu backup do Outlook", por="Marlos")
        h = ficha.hist_get(self.mid)
        self.assertEqual(len(h), 2, "nada some e nada é acrescentado")
        self.assertEqual(h[0]["resumo"], "Cliente pediu backup do Outlook")
        c = h[0]["extra"]["corrigido"]
        self.assertEqual((c[0]["original"], c[0]["por"]), ("Cliente pediu backup do Outlok", "Marlos"))
        self.assertEqual(h[0]["extra"]["tecnico"], "Ana")
        ficha.hist_corrigir(self.mid, 0, "Terceira versão", por="Marlos")
        self.assertEqual([x["original"] for x in ficha.hist_get(self.mid)[0]["extra"]["corrigido"]],
                         ["Cliente pediu backup do Outlok", "Cliente pediu backup do Outlook"])

    def test_recusa(self):
        for idx, txt in ((9, "x"), ("a", "x"), (-1, "x"), (1, ""), (1, "Segunda nota")):
            with self.assertRaises(ValueError):
                ficha.hist_corrigir(self.mid, idx, txt)
