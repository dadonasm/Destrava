# -*- coding: utf-8 -*-
"""Perfil do técnico: salva só no computador, valida e-mail/telefone, e o certificado leva uma cópia só do que foi marcado."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

from nucleo import mapa
from nucleo import perfil

from tests import test_backup_mapa as tbm

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COMPLETO = {"nome": "Marlos", "empresa": "D&D Technology", "email": "marlos@dd.com.br", "telefone": "(27) 99999-0000",
            "instagram": "@ddtech", "site": "", "facebook": "", "linkedin": "", "outro": "", "no_certificado": ["nome", "instagram"]}


class Perfil(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="destrava_perfil_")
        self._pasta, perfil.PASTA = perfil.PASTA, self.tmp

    def tearDown(self):
        perfil.PASTA = self._pasta
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_sem_perfil_nao_entra_no_certificado(self):
        p = perfil.ler()
        self.assertFalse(p["preenchido"])
        self.assertEqual(p["empresa"], "D&D Technology")
        self.assertEqual(perfil.snapshot(), {})

    def test_salva_e_continua_depois_de_reabrir(self):
        perfil.salvar(COMPLETO)
        cod = "import sys,json;sys.path.insert(0,%r);import perfil;perfil.PASTA=%r;print(json.dumps(perfil.ler()))" % (os.path.join(RAIZ, "nucleo"), self.tmp)
        p = json.loads(subprocess.check_output([sys.executable, "-c", cod]).decode("utf-8"))
        self.assertTrue(p["preenchido"])
        self.assertEqual((p["nome"], p["email"], p["instagram"]), ("Marlos", "marlos@dd.com.br", "@ddtech"))
        self.assertEqual(p["no_certificado"], ["nome", "instagram"])

    def test_certificado_so_com_o_que_foi_marcado(self):
        perfil.salvar(COMPLETO)
        self.assertEqual(perfil.snapshot(), {"nome": "Marlos", "instagram": "@ddtech"})

    def test_validacao(self):
        for campo, valor in (("email", "marlos@"), ("email", "sem arroba.com"), ("telefone", "12345"), ("telefone", "27 9999x0000")):
            with self.assertRaises(ValueError, msg="%s=%s" % (campo, valor)):
                perfil.salvar(dict(COMPLETO, **{campo: valor}))
        with self.assertRaises(ValueError):
            perfil.salvar(dict(COMPLETO, nome="x" * 200))
        self.assertFalse(os.path.exists(perfil.caminho()), "nada é gravado quando a validação falha")
        p = perfil.salvar(dict(COMPLETO, email="", telefone="+55 27 99999-0000", instagram=""))
        self.assertEqual(p["telefone"], "+55 27 99999-0000")

    def test_campos_desconhecidos_nao_entram(self):
        perfil.salvar(dict(COMPLETO, senha="123", no_certificado=["nome", "senha"]))
        with open(perfil.caminho(), encoding="utf-8") as fh:
            d = json.load(fh)
        self.assertNotIn("senha", d)
        self.assertEqual(d["no_certificado"], ["nome"])


class CertificadoComTecnico(unittest.TestCase):
    escanear = tbm.BackupCompleto.escanear

    def setUp(self):
        tbm.BackupCompleto.setUp(self)
        self._pasta, perfil.PASTA = perfil.PASTA, os.path.join(self.tmp, "dados")

    def tearDown(self):
        perfil.PASTA = self._pasta
        tbm.BackupCompleto.tearDown(self)

    def concluir(self):
        self.escanear()
        self.app.start_copy()
        self.assertEqual(tbm.espera(self.app, ("copied", "error")), "copied", self.app.error)
        self.app.start_verify("rapida")
        self.assertEqual(tbm.espera(self.app, ("verified", "error")), "verified", self.app.error)
        self.app.finish()
        with open(os.path.join(self.dest, "Backup_Ana", "Mapa", "certificado.json"), encoding="utf-8") as fh:
            return json.load(fh)["cert"]

    def test_certificado_mostra_so_o_marcado_e_nao_muda_depois(self):
        perfil.salvar(COMPLETO)
        cert = self.concluir()
        self.assertEqual(cert["tecnico_perfil"], {"nome": "Marlos", "instagram": "@ddtech"})
        self.assertEqual(cert["tecnico"], "Marlos")
        self.assertNotIn("marlos@dd.com.br", json.dumps(cert))
        self.assertNotIn("99999", json.dumps(cert))
        perfil.salvar(dict(COMPLETO, nome="Outro Técnico", instagram="@outro"))
        r = mapa.carregar(os.path.join(self.dest, "Backup_Ana"))
        self.assertEqual(r["cert"]["tecnico_perfil"], {"nome": "Marlos", "instagram": "@ddtech"}, "certificado antigo não muda")

    def test_nome_desmarcado_nao_vaza_no_campo_tecnico(self):
        perfil.salvar(dict(COMPLETO, no_certificado=["instagram"]))
        cert = self.concluir()
        self.assertEqual(cert["tecnico_perfil"], {"instagram": "@ddtech"})
        self.assertEqual(cert["tecnico"], "")

    def test_sem_perfil_certificado_igual_ao_antigo(self):
        cert = self.concluir()
        self.assertNotIn("tecnico_perfil", cert)
        self.assertEqual(mapa.carregar(os.path.join(self.dest, "Backup_Ana"))["contagem"]["falha"], 0)


if __name__ == "__main__":
    unittest.main()
