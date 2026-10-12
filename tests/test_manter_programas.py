# -*- coding: utf-8 -*-
"""O que manter: receita.json com a escolha, formatação só depois dela, e "Programas a reinstalar" no certificado."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

from nucleo import ficha
from nucleo import mapa
from nucleo import perfil
from nucleo import programas as P

from tests import test_backup_mapa as tbm

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(AQUI)
M = "DD-TESTE-00RM"
CINCO = ["7-Zip", "Google Chrome", "Microsoft 365 Apps para Grandes Empresas - pt-br", "Adobe Acrobat Reader DC", "AnyDesk"]


def com_programas(mid):
    with open(os.path.join(AQUI, "fixtures", "win10_programas.json"), encoding="utf-8") as fh:
        d = json.load(fh)
    os.makedirs(ficha.pasta(mid), exist_ok=True)
    with open(os.path.join(ficha.pasta(mid), "programas.json"), "w", encoding="utf-8") as fh:
        json.dump(P.documento(P.de_windows(d["progs"], d["appx"], d["winget"]), "windows"), fh)


class Receita(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="destrava_manter_")
        self._store, self._pasta = ficha.STORE, perfil.PASTA
        ficha.STORE, perfil.PASTA = os.path.join(self.tmp, "maquinas"), self.tmp
        perfil.salvar({"nome": "Marlos"})
        ficha.hist_add(M, "ficha", "Ficha coletada: nota 40", {"nota": 40})
        com_programas(M)

    def tearDown(self):
        ficha.STORE, perfil.PASTA = self._store, self._pasta
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_cinco_programas_gravados_e_relidos(self):
        escolha = [{"nome": n, "nota": ""} for n in CINCO]
        escolha[4]["nota"] = "  licença   do cliente  "
        escolha.append({"nome": "Programa que não existe"})
        escolha.append({"nome": "Google Chrome", "instalador": "winget:Coisa.Falsa"})
        ficha.salvar_receita(M, escolha)
        cod = ("import sys,json;sys.path.insert(0,%r);import ficha;ficha.STORE=%r;print(json.dumps(ficha.receita_de(%r)))"
               % (os.path.join(RAIZ, "nucleo"), ficha.STORE, M))
        r = json.loads(subprocess.check_output([sys.executable, "-c", cod]).decode("utf-8"))
        self.assertEqual([i["nome"] for i in r["itens"]], CINCO, "reabrindo: os 5, sem repetir e sem nome desconhecido")
        self.assertEqual((r["tecnico"], len(r["quando"]), r["nenhum"]), ("Marlos", 16, False))
        it = {i["nome"]: i for i in r["itens"]}
        self.assertEqual((it["Google Chrome"]["instalador"], it["Google Chrome"]["automatico"]), ("winget:Google.Chrome", True), "o id vem do programas.json, não da tela")
        self.assertEqual((it["AnyDesk"]["automatico"], it["AnyDesk"]["nota"]), (False, "licença do cliente"))
        self.assertEqual(ficha.hist_get(M)[-1]["tipo"], "receita")
        self.assertTrue(ficha.receita_valida(M))

    def test_lista_vazia_so_com_confirmacao(self):
        with self.assertRaises(ValueError):
            ficha.salvar_receita(M, [])
        self.assertIsNone(ficha.receita_de(M))
        r = ficha.salvar_receita(M, [], nenhum=True)
        self.assertEqual((r["nenhum"], r["itens"]), (True, []))
        self.assertFalse(ficha.salvar_receita(M, [{"nome": "7-Zip"}], nenhum=True)["nenhum"], "marcou algum: não é 'nenhum'")

    def test_formatada_so_depois_do_que_manter(self):
        with self.assertRaises(ValueError):
            ficha.marcar_etapa(M, "formatada", confirmar=True)
        ficha.salvar_receita(M, [], nenhum=True)
        self.assertEqual(ficha.marcar_etapa(M, "formatada", confirmar=True)["registro"]["etapa"], "formatada")

    def test_receita_de_servico_antigo_nao_libera(self):
        ficha.salvar_receita(M, [{"nome": "7-Zip"}])
        arq = os.path.join(ficha.pasta(M), "receita.json")
        with open(arq, encoding="utf-8") as fh:
            r = json.load(fh)
        with open(arq, "w", encoding="utf-8") as fh:
            json.dump(dict(r, quando="2026-01-05 10:00"), fh)  # feita num atendimento de janeiro
        self.assertIsNone(ficha.receita_valida(M), "o serviço atual começou depois dela")
        ficha.marcar_etapa(M, "entregue")
        self.assertIsNone(ficha.receita_valida(M), "depois de entregue, só uma receita nova libera")
        with self.assertRaises(ValueError):
            ficha.marcar_etapa(M, "formatada", confirmar=True)

    def test_sugestao_pre_marcada(self):
        doc = P.com_sugestao(ficha.programas_de(M))
        rec = {g["nome"]: g["categoria"] for g in doc["itens"] if g["recomendado"]}
        self.assertEqual(rec, {"Google Chrome": "navegador", "Microsoft Edge": "navegador", "Microsoft 365 Apps para Grandes Empresas - pt-br": "escritório",
                               "Adobe Acrobat Reader DC": "leitor de PDF"})
        self.assertEqual(P.categoria("Avast Cleanup Premium"), "", "nunca sugerir 'limpador'")
        self.assertEqual(P.categoria("Avast Free Antivirus"), "antivírus")
        self.assertEqual(P.categoria("Ask Toolbar for Firefox"), "", "barra de ferramentas nunca")
        self.assertFalse(next(g for g in doc["itens"] if g["nome"] == "Microsoft Edge Update")["recomendado"], "escondido não é sugerido")

    def test_sem_senha_nem_chave_nos_arquivos(self):
        ficha.salvar_receita(M, [{"nome": "AnyDesk", "nota": "x", "senha": "123", "chave": "ABCDE-12345"}])
        with open(os.path.join(ficha.pasta(M), "receita.json"), encoding="utf-8") as fh:
            r = json.load(fh)
        self.assertEqual(set(r), {"versao", "quando", "tecnico", "nenhum", "itens"})
        self.assertEqual(set(r["itens"][0]), {"nome", "fabricante", "versao", "instalador", "automatico", "nota"})
        self.assertNotIn("ABCDE", json.dumps(r))
        with open(os.path.join(ficha.pasta(M), "programas.json"), encoding="utf-8") as fh:
            txt = fh.read().lower()
        for proibido in ("senha", "password", "licen", "serial", "productid", "chave"):
            self.assertNotIn(proibido, txt)


class Certificado(unittest.TestCase):
    escanear = tbm.BackupCompleto.escanear

    def setUp(self):
        tbm.BackupCompleto.setUp(self)
        self._pasta, perfil.PASTA = perfil.PASTA, os.path.join(self.tmp, "dados")
        self._mid = ficha._MID.get("v")
        ficha._MID["v"] = M
        ficha.hist_add(M, "ficha", "Ficha coletada: nota 40", {"nota": 40})
        com_programas(M)

    def tearDown(self):
        perfil.PASTA = self._pasta
        ficha._MID.pop("v", None)
        if self._mid:
            ficha._MID["v"] = self._mid
        tbm.BackupCompleto.tearDown(self)

    def backup(self):
        self.escanear()
        self.app.start_copy()
        self.assertEqual(tbm.espera(self.app, ("copied", "error")), "copied", self.app.error)
        self.app.start_verify("completa")
        self.assertEqual(tbm.espera(self.app, ("verified", "error")), "verified", self.app.error)
        self.app.same_disk = False

    def test_certificado_lista_os_programas_e_formatar_libera(self):
        self.backup()
        ficha.salvar_receita(M, [{"nome": n} for n in CINCO])  # etapa O que manter, antes de concluir
        self.app.finish()
        self.assertEqual(self.app.firmware_gate(), (True, ""))
        r = mapa.carregar(os.path.join(self.dest, "Backup_Ana"))
        self.assertEqual(r["cert"]["programas_resumo"], {"n": 5, "nomes": CINCO})
        self.assertNotIn("120.0", json.dumps(r["cert"]["programas_resumo"]), "sem versões no certificado")

    def test_pular_a_etapa_certificado_como_antes_e_formatar_bloqueado(self):
        self.backup()
        self.app.finish()
        self.assertNotIn("programas_resumo", mapa.carregar(os.path.join(self.dest, "Backup_Ana"))["cert"])
        ok, por = self.app.firmware_gate()
        self.assertFalse(ok)
        self.assertIn("O que manter", por)
        ficha.salvar_receita(M, [], nenhum=True)  # feita depois, pela ficha da máquina
        self.assertEqual(self.app.firmware_gate(), (True, ""))


if __name__ == "__main__":
    unittest.main()
