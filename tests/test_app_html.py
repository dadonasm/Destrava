# -*- coding: utf-8 -*-
"""A página única não pode perder funções nem globais usados pela navegação (um corte errado já apagou a aba Dados)."""
import os
import re
import tempfile
import unittest

from nucleo import dd_backup

APP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "nucleo", "web", "app.html")


class PaginaInteira(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(APP, encoding="utf-8") as fh:
            cls.js = "\n".join(re.findall(r"<script>(.*?)</script>", fh.read(), re.S))
        cls.definidos = set(re.findall(r"^(?:async )?function ([A-Za-z0-9_]+)", cls.js, re.M)) | \
            set(re.findall(r"^\s*(?:const|let) ([A-Za-z0-9_]+)", cls.js, re.M)) | \
            set(re.findall(r"^let [A-Za-z0-9_]+=[^;]*;\s*const ([A-Za-z0-9_]+)", cls.js, re.M))

    def test_toda_tela_do_nav_existe(self):
        nav = re.search(r"^function nav\(v,arg\)\{.*?^\}", self.js, re.M | re.S).group(0)
        chamadas = set(re.findall(r"(draw[A-Za-z0-9_]*)\(", nav))
        self.assertTrue({"drawHome", "drawDados", "drawMaq", "drawOS", "drawPerfil", "drawMapas"} <= chamadas)
        self.assertEqual(sorted(chamadas - self.definidos), [], "tela chamada pelo menu sem função definida")

    def test_globais_das_telas_existem(self):
        self.assertEqual(sorted({"DS", "DT", "ZN", "LST", "MP", "STNOME", "CATORD", "CATNAME", "IC"} - self.definidos), [])

    def test_funcoes_chamadas_existem(self):
        chamadas = set(re.findall(r"\b((?:draw|lst|dados|mq|ilha)[A-Z][A-Za-z0-9_]*)\(", self.js))
        self.assertEqual(sorted(chamadas - self.definidos), [], "função chamada que não existe na página")


class Juncao(unittest.TestCase):
    def test_link_de_pasta_e_pasta_comum(self):
        tmp = tempfile.mkdtemp(prefix="destrava_link_")
        real, link = os.path.join(tmp, "real"), os.path.join(tmp, "Todos os Usuários")
        os.makedirs(real)
        try:
            os.symlink(real, link, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("sem permissão para criar link")
        self.assertTrue(dd_backup.e_link(link))
        self.assertFalse(dd_backup.e_link(real))
        self.assertFalse(dd_backup.e_link(os.path.join(tmp, "nao_existe")))


if __name__ == "__main__":
    unittest.main()
