# -*- coding: utf-8 -*-
"""Backup: lista de programas lida sozinha (sem a análise completa), ícone de cada programa, histórico de backups da
máquina sem eventos repetidos, progresso da medição por bytes e reabrir como administrador pelo próprio programa."""
import copy
import os
import shutil
import tempfile
import unittest
from unittest import mock

from nucleo import dd_backup
from nucleo import ficha
from nucleo import perfil
from nucleo import programas as P

M = "DD-TESTE-00NV"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="destrava_novidades_")
        self._store, self._pasta, self._mid = ficha.STORE, perfil.PASTA, dict(ficha._MID)
        ficha.STORE, perfil.PASTA = os.path.join(self.tmp, "maquinas"), self.tmp
        ficha._MID["v"] = M
        perfil.salvar({"nome": "Marlos"})
        ficha.hist_add(M, "ficha", "Ficha coletada: nota 40", {"nota": 40})

    def tearDown(self):
        ficha.STORE, perfil.PASTA = self._store, self._pasta
        ficha._MID.clear()
        ficha._MID.update(self._mid)
        shutil.rmtree(self.tmp, ignore_errors=True)


class ProgramasSozinhos(Base):
    def test_coleta_so_dos_programas_sem_ficha_nem_historico(self):
        lista = [P.entrada("Spotify", "1.2", "Spotify", "Aplicativos"), P.entrada("git", "2.5", "", "Homebrew (linha de comando)", "brew:git")]
        antes = len(ficha.hist_get(M))
        with mock.patch.object(ficha, "IS_WIN", False), mock.patch.object(P, "coletar", return_value=lista), mock.patch.object(P, "icones", return_value=0) as ic:
            r = ficha.coletar_programas()
        self.assertEqual((r["mid"], r["n"]), (M, 2))
        doc = ficha.programas_de(M)
        self.assertEqual(sorted(g["nome"] for g in doc["itens"]), ["Spotify", "git"])
        self.assertEqual(len(ficha.hist_get(M)), antes, "não é uma análise: nada no histórico")
        self.assertEqual(ficha.listar_fichas(M), [], "nem ficha nova")
        self.assertEqual(ic.call_args[0][1], os.path.join(ficha.pasta(M), "icones"), "os ícones ficam na pasta da máquina")

    def test_titulo_na_ilha(self):
        ft = dict(dd_backup.FT)
        try:
            dd_backup.FT.update(rodando=True, o_que="programas", etapa="Listando", pct=10)
            a = next(x for x in dd_backup.atividades()["atividades"] if x["id"] == "ficha")
            self.assertEqual(a["titulo"], "Lendo os programas instalados")
        finally:
            dd_backup.FT.clear()
            dd_backup.FT.update(ft)


class Icones(unittest.TestCase):
    def test_nome_do_arquivo_do_icone(self):
        self.assertEqual(P.nome_icone("Visual Studio Code"), "visualstudiocode")
        self.assertEqual(P.nome_icone("7-Zip 23.01 (x64)"), P.nome_icone("7-Zip"), "versão e 32/64 bits não mudam o ícone")

    def test_exe_do_display_icon(self):
        self.assertEqual(P.exe_do_icone('"C:\\Program Files\\X\\x.exe",0'), "C:\\Program Files\\X\\x.exe")
        self.assertEqual(P.exe_do_icone("C:\\X\\app.exe,-101"), "C:\\X\\app.exe")
        self.assertEqual(P.exe_do_icone("msiexec /x {123}"), "")

    def test_mac_um_processo_para_todos(self):
        tmp = tempfile.mkdtemp()
        try:
            apps = os.path.join(tmp, "Applications")
            os.makedirs(os.path.join(apps, "Spotify.app"))
            os.makedirs(os.path.join(apps, "Notion.app"))
            dest = os.path.join(tmp, "icones")
            with open(os.path.join(tmp, "x.png"), "wb") as fh:
                fh.write(b"png")
            with mock.patch.object(P, "IS_MAC", True), mock.patch.object(P, "IS_WIN", False), \
                    mock.patch.object(P, "_apps_mac_por_nome", return_value={"spotify": os.path.join(apps, "Spotify.app"), "notion": os.path.join(apps, "Notion.app")}), \
                    mock.patch.object(P, "_rodar", return_value="2\n") as rodar:
                self.assertEqual(P.icones(["Spotify", "Notion", "git"], dest), 2)
            cmd = rodar.call_args[0][0]
            self.assertEqual(cmd[:3], ["osascript", "-l", "JavaScript"])
            self.assertEqual(cmd[4:], [os.path.join(apps, "Spotify.app"), os.path.join(dest, "spotify.png"), os.path.join(apps, "Notion.app"), os.path.join(dest, "notion.png")],
                             "git (sem .app) fica com a inicial")
            self.assertFalse(os.path.exists(os.path.join(dest, ".icones.js")), "o script temporário some")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class HistoricoDeBackups(Base):
    def test_backups_do_mais_novo_ao_mais_antigo(self):
        ficha.hist_add(M, "backup", "Backup sem falhas: 5 arquivos (77,82 KB) · código AAAA-0000", {"destino": "/D/Teste", "codigo": "AAAA-0000"})
        mp = os.path.join(ficha.pasta(M), "mapas", "BBBB-1111", "Mapa")
        os.makedirs(mp)
        open(os.path.join(mp, "Relatorio-backup.pdf"), "wb").close()
        ficha.hist_add(M, "backup", "Backup com ressalvas: 1 arquivos (11,79 MB) · código BBBB-1111",
                       {"destino": "/D/Teste2", "codigo": "BBBB-1111", "status": "ressalvas", "bytes": 12, "copiados": 1})
        b = ficha.backups_de(M)
        self.assertEqual([x["codigo"] for x in b], ["BBBB-1111", "AAAA-0000"])
        self.assertEqual((b[0]["pdf"], b[0]["mapa"], b[0]["copiados"], b[0]["status"]), (True, mp, 1, "ressalvas"))
        self.assertEqual((b[1]["pdf"], b[1]["mapa"], b[1]["copiados"], b[1]["status"]), (False, "", 5, "sem_falhas"), "evento antigo: número e situação lidos do texto")

    def test_receita_marcada_um_por_um_vira_um_evento_so(self):
        doc = P.documento([P.entrada("Spotify", "1"), P.entrada("Notion", "2")], "mac")
        ficha._json_atomico(os.path.join(ficha.pasta(M), "programas.json"), doc)
        ficha.salvar_receita(M, [{"nome": "Spotify"}])
        ficha.salvar_receita(M, [{"nome": "Spotify"}, {"nome": "Notion"}])
        rec = [e for e in ficha.hist_get(M) if e["tipo"] == "receita"]
        self.assertEqual(len(rec), 1)
        self.assertIn("2 programa(s)", rec[0]["resumo"])


class Medicao(unittest.TestCase):
    def test_progresso_por_bytes(self):
        app, salvo = dd_backup.App(), dd_backup.APP
        dd_backup.APP = app
        try:
            gb = 1000 ** 3
            app.medicao = {"rodando": True, "pct": 0, "usado": 200 * gb, "achado": 25 * gb, "grupos": {}, "medido_sis": 40 * gb}
            a = next(x for x in dd_backup.atividades()["atividades"] if x["id"] == "medicao")
            self.assertEqual(a["pct"], 22, "40 de 175 GB medidos, mesmo com a contagem por passos em 0")
            app.medicao["medido_sis"] = 10 * gb
            a = next(x for x in dd_backup.atividades()["atividades"] if x["id"] == "medicao")
            self.assertEqual(a["pct"], 22, "não recua")
            app.medicao["medido_sis"] = 500 * gb
            a = next(x for x in dd_backup.atividades()["atividades"] if x["id"] == "medicao")
            self.assertEqual(a["pct"], 95, "só chega a 100% quando termina")
        finally:
            dd_backup.APP = salvo


class Administrador(unittest.TestCase):
    def test_mac_pede_a_senha_do_sistema(self):
        r = mock.Mock(returncode=0, stderr=b"")
        with mock.patch.object(dd_backup, "IS_WIN", False), mock.patch.object(dd_backup.sys, "platform", "darwin"), \
                mock.patch.object(dd_backup.subprocess, "run", return_value=r) as run:
            self.assertTrue(dd_backup.reabrir_como_admin(["--dados", "/tmp/x"]))
        cmd = run.call_args[0][0]
        self.assertEqual(cmd[:2], ["osascript", "-e"])
        self.assertIn("with administrator privileges", cmd[2])
        self.assertIn("--elevado", cmd[2], "a instância nova não pede de novo")
        self.assertIn("SUDO_USER=", cmd[2], "o navegador e os arquivos continuam abrindo como o usuário")

    def test_cancelar_a_senha_nao_fecha_o_programa(self):
        r = mock.Mock(returncode=1, stderr=b"execution error: User canceled. (-128)")
        with mock.patch.object(dd_backup, "IS_WIN", False), mock.patch.object(dd_backup.sys, "platform", "darwin"), \
                mock.patch.object(dd_backup.subprocess, "run", return_value=r):
            with self.assertRaises(dd_backup.Negado):
                dd_backup.reabrir_como_admin(["--dados", "/tmp/x"])

    def test_preferencia_abrir_sempre(self):
        tmp, salvo = tempfile.mkdtemp(), dd_backup.DADOS_DIR[0]
        dd_backup.DADOS_DIR[0] = tmp
        try:
            self.assertFalse(dd_backup.cfg_local().get("sempre_admin"))
            dd_backup.cfg_local_set(sempre_admin=True)
            self.assertTrue(dd_backup.cfg_local()["sempre_admin"])
        finally:
            dd_backup.DADOS_DIR[0] = salvo
            shutil.rmtree(tmp, ignore_errors=True)

    def test_preflight_so_avisa_quando_faz_diferenca(self):
        app = dd_backup.App()
        app.cfg = {"dest": tempfile.gettempdir(), "sources": []}
        with mock.patch.object(dd_backup, "eh_admin", return_value=False):
            self.assertFalse([c for c in app.preflight() if c.get("acao") == "elevar"], "sem pasta ilegível: nada de aviso")
            app.ign_dirs = [("/Users/outro", "Sem acesso: Permission denied")]
            c = [c for c in app.preflight() if c.get("acao") == "elevar"]
            self.assertEqual(len(c), 1)
            self.assertIn("1 pasta", c[0]["titulo"])


if __name__ == "__main__":
    unittest.main()
