# -*- coding: utf-8 -*-
"""Backup que não deixa nada importante para trás (tipos desconhecidos, dados de apps, bancos de sistemas),
conferência lendo do disco e o Mapa dentro do programa."""
import hashlib
import os
import shutil
import tempfile
import time
import unittest

from nucleo import dd_backup
from nucleo import disco
from nucleo import ficha
from nucleo import mapa


def escreve(p, dados=b"x"):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "wb") as fh:
        fh.write(dados)


def espera(app, fases, limite=30):
    t = time.time()
    while app.phase not in fases and time.time() - t < limite:
        time.sleep(0.05)
    return app.phase


class BackupCompleto(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="destrava_bkp_")
        self.disco = os.path.join(self.tmp, "C")  # um "disco do Windows" de mentira
        j = lambda *p: os.path.join(self.disco, *p)
        os.makedirs(j("Windows"))
        escreve(j("Users", "Ana", "Documents", "contrato.pdf"), b"%PDF contrato")
        escreve(j("Users", "Ana", "Documents", "planilha.xyz"), b"tipo que o programa nao conhece")
        escreve(j("Users", "Ana", "Pictures", "foto.jpg"), b"\xff\xd8\xff" + b"1" * 3000)
        escreve(j("Users", "Ana", "AppData", "Roaming", "Thunderbird", "Profiles", "x.default", "Mail", "Inbox"), b"From: cliente")
        escreve(j("Users", "Ana", "AppData", "Roaming", "Thunderbird", "Profiles", "x.default", "cache2", "lixo"), b"cache")
        escreve(j("Users", "Ana", "AppData", "Local", "Microsoft", "Outlook", "Ana.pst"), b"pst" * 100)
        escreve(j("Users", "Ana", "AppData", "Local", "Temp", "x.tmp"), b"temp")
        escreve(j("Program Files (x86)", "LojaX", "dados", "LOJA.FDB"), b"F" * 70000)
        escreve(j("Program Files", "Microsoft", "x.mdb"), b"M" * 70000)
        escreve(j("ProgramData", "Contab", "pequeno.dbf"), b"d" * 100)
        escreve(j("ProgramData", "Contab", "empresa.dbf"), b"D" * 70000)
        self.dest = os.path.join(self.tmp, "HD_externo")
        os.makedirs(self.dest)
        self._store = ficha.STORE
        ficha.STORE = os.path.join(self.tmp, "maquinas")
        self._dados = dd_backup.DADOS_DIR[0]
        dd_backup.DADOS_DIR[0] = self.tmp  # memória das pastas de origem fora do projeto
        self.app = dd_backup.App()
        self.app.set_config({"sources": [{"path": self.disco, "kind": "windows", "letter": "C"}], "dest": self.dest, "folder": "Backup_Ana", "cliente": "Ana"})

    def tearDown(self):
        dd_backup.DADOS_DIR[0] = self._dados
        ficha.STORE = self._store
        mapa.CANCEL.set()
        mapa.M.update(raiz="", mapa="", meta={}, f=[], partes=[], cert={})
        shutil.rmtree(self.tmp, ignore_errors=True)

    def escanear(self):
        self.app.start_scan()
        self.assertEqual(espera(self.app, ("scanned", "error")), "scanned", self.app.error)
        return {os.path.basename(it.src): it for it in self.app.items}

    def test_nada_importante_fica_para_tras(self):
        it = self.escanear()
        self.assertTrue(it["planilha.xyz"].inc, "tipo desconhecido agora vai junto")
        self.assertEqual(it["Inbox"].cat, "Dados_de_apps")
        self.assertIn("Ana/Dados_de_apps/Thunderbird/x.default/Mail/Inbox", it["Inbox"].rel)
        self.assertNotIn("lixo", it, "cache do Thunderbird não vai")
        self.assertTrue(it["Ana.pst"].inc)
        self.assertNotIn("x.tmp", it, "o resto da AppData continua de fora")
        self.assertEqual(it["LOJA.FDB"].cat, "Sistemas")
        self.assertEqual(it["LOJA.FDB"].rel, "Disco_C/Sistemas/Program Files (x86)/LojaX/dados/LOJA.FDB", "caminho original preservado")
        self.assertIn("empresa.dbf", it)
        self.assertNotIn("x.mdb", it, "pasta de fabricante (Microsoft) é pulada")
        self.assertNotIn("pequeno.dbf", it, "arquivo minúsculo não é banco de dados de sistema")

    def test_backup_mapa_e_conferencia(self):
        self.escanear()
        self.app.start_copy()
        self.assertEqual(espera(self.app, ("copied", "error")), "copied", self.app.error)
        self.app.start_verify("completa")
        self.assertEqual(espera(self.app, ("verified", "error")), "verified", self.app.error)
        cert = self.app.finish()
        self.assertEqual(cert["status"], "sem_falhas")
        self.assertIn(disco.METODO, cert["metodo"])
        r = mapa.carregar(os.path.join(self.dest, "Backup_Ana"))
        self.assertEqual(r["contagem"]["falha"], 0)
        self.assertGreaterEqual(r["contagem"]["ok"], 7)
        a = mapa.arvore("")
        self.assertEqual([p["nome"] for p in a["pastas"]], ["C:"])
        docs = mapa.arvore("C:/Users/Ana/Documents")
        pdf = [x for x in docs["arquivos"] if x["nome"] == "contrato.pdf"][0]
        self.assertTrue(pdf["no_backup"] and pdf["previa"] == "pdf")
        self.assertTrue(mapa.caminho(pdf["i"]).endswith("contrato.pdf"))
        busca = mapa.buscar("loja.fdb")
        self.assertEqual(busca["total"], 1)
        mapa.conferir()
        while mapa.CONF["rodando"]:
            time.sleep(0.05)
        self.assertEqual((mapa.CONF["n_diferentes"] if "n_diferentes" in mapa.CONF else len(mapa.CONF["diferentes"]), len(mapa.CONF["faltando"])), (0, 0))
        # alguém mexeu num arquivo do backup: a conferência acusa
        with open(mapa.caminho(pdf["i"]), "ab") as fh:
            fh.write(b"alterado")
        mapa.conferir()
        while mapa.CONF["rodando"]:
            time.sleep(0.05)
        self.assertEqual(len(mapa.CONF["diferentes"]), 1)

    def test_mapa_guardado_no_registro_da_maquina(self):
        self.escanear()
        self.app.start_copy()
        self.assertEqual(espera(self.app, ("copied", "error")), "copied", self.app.error)
        self.app.start_verify("completa")
        self.assertEqual(espera(self.app, ("verified", "error")), "verified", self.app.error)
        cert = self.app.finish()
        copia = os.path.join(ficha.pasta(ficha.machine_id_cache()), "mapas", cert["codigo"])
        self.assertTrue(os.path.isfile(os.path.join(copia, "Mapa", "dados.js")))
        self.assertTrue(os.path.isfile(os.path.join(copia, "Mapa", "certificado.json")))
        shutil.rmtree(os.path.join(self.dest, "Backup_Ana"))  # disco do backup desligado
        achados = dd_backup.mapas_conhecidos()
        self.assertEqual([m["pasta"] for m in achados if m["codigo"] == cert["codigo"]], [copia], "abre pela cópia do registro")

    def concluir(self):
        self.app.preflight()  # como na tela de Checagens: grava as checagens (inclui "mesmo disco") no certificado
        self.escanear()
        self.app.start_copy()
        self.assertEqual(espera(self.app, ("copied", "error")), "copied", self.app.error)
        self.app.start_verify("completa")
        self.assertEqual(espera(self.app, ("verified", "error")), "verified", self.app.error)
        return self.app.finish()

    def test_retomar_depois_de_reiniciar(self):
        cert = self.concluir()
        mid = ficha.machine_id_cache()
        novo = dd_backup.App()  # programa fechado e aberto de novo: a memória do backup se perdeu
        self.assertEqual(novo.phase, "idle")
        r = novo.retomar(mid)
        self.assertEqual((novo.phase, novo.finished, novo.cert["codigo"], novo.verified_mode), ("done", True, cert["codigo"], "completa"))
        self.assertEqual((r["ok"], r["passo"]), (True, 5), "falta o O que manter: volta nesse passo")
        self.assertEqual(novo.same_disk, self.app.same_disk, "o mesmo disco continua bloqueando a formatação")
        self.assertEqual(novo.dest_root, self.app.dest_root)
        self.assertEqual(novo.retomar(mid)["passo"], 5, "já aberto: não recarrega")
        with self.assertRaises(ValueError):
            novo.retomar("DD-OUTRA-0000")

    def test_retomar_so_com_o_backup_intacto(self):
        self.concluir()
        mid = ficha.machine_id_cache()
        ok = next(it for it in self.app.items if it.status == "ok")
        arq = os.path.join(self.app.dest_root, *ok.rel.split("/"))
        with open(arq, "ab") as fh:
            fh.write(b"mexeram")
        with self.assertRaisesRegex(ValueError, "sumiram ou mudaram"):
            dd_backup.App().retomar(mid)
        shutil.rmtree(os.path.join(self.app.dest_root, "Mapa"))
        with self.assertRaisesRegex(ValueError, "não está conectado"):
            dd_backup.App().retomar(mid)

    def test_mapa_nao_sai_da_pasta_do_backup(self):
        self.escanear()
        self.app.start_copy()
        espera(self.app, ("copied", "error"))
        self.app.start_verify("rapida")
        espera(self.app, ("verified", "error"))
        self.app.finish()
        mapa.carregar(os.path.join(self.dest, "Backup_Ana", "Mapa"))
        fora = [i for i, e in enumerate(mapa.M["f"]) if e[mapa.ST_] != "ok"]
        if fora:
            with self.assertRaises(ValueError):
                mapa.caminho(fora[0])
        mapa.M["f"][0] = list(mapa.M["f"][0])
        mapa.M["f"][0][mapa.D_] = "../../fora.txt"
        mapa.M["f"][0][mapa.ST_] = "ok"
        with self.assertRaises(ValueError):
            mapa.caminho(0)


class EscolhaTotal(BackupCompleto):
    """Tudo listado, escolha por categoria, pastas-mãe, WhatsApp, checagens com solução e certificado."""

    def setUp(self):
        BackupCompleto.setUp(self)
        j = lambda *p: os.path.join(self.disco, *p)
        escreve(j("Users", "Ana", "Downloads", "instalador.exe"), b"MZ" * 50)
        escreve(j("Users", "Ana", "Documents", "config.ini"), b"[x]")
        escreve(j("Users", "Ana", ".segredo", "anotacao.txt"), b"oculto")
        escreve(j("Users", "Ana", "AppData", "Local", "AppQualquer", "dados.dat"), b"app")
        escreve(j("Users", "Ana", "Pictures", "WhatsApp", "IMG-20240105-WA0001.jpg"), b"\xff\xd8\xff" + b"w" * 500)
        escreve(j("Users", "Ana", "Downloads", "WhatsApp Image 2024-02-03 at 10.11.12.jpeg"), b"\xff\xd8\xff" + b"v" * 500)
        for i, nome in enumerate(("nota_fiscal_jan.pdf", "contrato_cliente.docx", "orcamento_loja.xlsx", "boleto.pdf")):
            escreve(j("Users", "Ana", "Documents", "Wefix", "Clientes" if i % 2 else "Fiscal", nome), b"trabalho %d" % i)
        for i in range(3):
            escreve(j("Users", "Ana", "Documents", "Fotos da praia", "f%d.jpg" % i), b"\xff\xd8\xff" + b"p" * 100)

    def test_tudo_listado_e_escolha(self):
        it = self.escanear()
        self.assertEqual((it["instalador.exe"].cat, it["instalador.exe"].inc), ("Programas", False))
        self.assertEqual((it["config.ini"].cat, it["config.ini"].inc), ("Configuracoes", False))
        self.assertEqual((it["anotacao.txt"].cat, it["anotacao.txt"].inc), ("Ocultos", False))
        self.assertEqual((it["dados.dat"].cat, it["dados.dat"].inc), ("Dados_de_apps", False))
        self.assertTrue(it["contrato.pdf"].inc, "pessoal vem marcado")
        wa = it["IMG-20240105-WA0001.jpg"]
        self.assertEqual(wa.local, "WhatsApp")
        self.assertTrue(wa.rel.startswith("WhatsApp/Fotos/2024/01 - Janeiro/"))
        self.assertEqual(it["WhatsApp Image 2024-02-03 at 10.11.12.jpeg"].local, "WhatsApp")
        self.assertEqual(self.app.select({"filter": {"cat": "Programas"}, "on": True}), 1)
        self.assertTrue(it["instalador.exe"].inc)

    def test_pastas_de_origem(self):
        it = self.escanear()
        sug = {x["nome"]: x for x in self.app.sugestoes_maes()}
        self.assertIn("Wefix", sug)
        self.assertGreater(sug["Wefix"]["pct"], sug["Fotos da praia"]["pct"], "trabalho pontua mais que pasta pessoal")
        self.assertIn("nome próprio", sug["Wefix"]["motivos"])
        self.assertEqual((sug["Wefix"]["auto"], sug["Fotos da praia"]["auto"]), (True, False))
        self.assertEqual(it["contrato_cliente.docx"].rel, "Pastas_origem/Wefix/Clientes/contrato_cliente.docx", "já vem separada da pasta da Ana")
        self.assertEqual(it["contrato_cliente.docx"].local, "Pastas_origem/Wefix")
        self.app.set_maes([])
        self.assertTrue(it["contrato_cliente.docx"].rel.startswith("Ana/Documentos/"), "desmarcar devolve ao lugar")

    def test_memoria_das_pastas_de_origem(self):
        self.escanear()
        self.app.set_maes([])  # o técnico desfez a separação automática da Wefix
        self.app._lembrar_origens()
        self.assertEqual(dd_backup.memoria_origens()["wefix"]["recusada"], 1)
        outro = dd_backup.App()
        outro.set_config({"sources": [{"path": self.disco, "kind": "windows", "letter": "C"}], "dest": self.dest, "folder": "B2", "cliente": "Ana"})
        outro.start_scan()
        self.assertEqual(espera(outro, ("scanned", "error")), "scanned", outro.error)
        w = next(x for x in outro.sugestoes_maes() if x["nome"] == "Wefix")
        self.assertEqual((w["auto"], w["marcada"]), (False, False), "recusada antes: não marca sozinha")
        self.assertIn("você não quis separar antes", w["motivos"])
        outro.set_maes([w["chave"]])
        outro._lembrar_origens()
        outro._lembrar_origens()
        w = next(x for x in outro.sugestoes_maes() if x["nome"] == "Wefix")
        self.assertTrue(w["auto"] and "você já separou em outra máquina" in w["motivos"], "aceita mais vezes: volta a marcar sozinha")

    def test_destino_falsificado_bloqueia_com_solucao(self):
        import unittest.mock as um
        with um.patch.object(disco, "sha256", return_value="0" * 64):
            ch = self.app.preflight()
        erro = [c for c in ch if c["nivel"] == "erro"]
        self.assertTrue(erro and "DIFERENTES" in erro[0]["titulo"] and "troque" in erro[0]["solucao"])
        ok = [c for c in self.app.preflight() if "Gravou e releu" in c["titulo"]]
        self.assertTrue(ok)

    def test_formatar_so_com_verificacao_completa_e_certificado(self):
        self.escanear()
        self.app.preflight()
        self.app.start_copy()
        espera(self.app, ("copied", "error"))
        self.app.start_verify("rapida")
        espera(self.app, ("verified", "error"))
        self.app.finish()
        self.app.same_disk = False  # aqui origem e destino são pastas do mesmo disco; isola a regra da verificação completa
        ok, por = self.app.firmware_gate()
        self.assertFalse(ok)
        self.assertIn("COMPLETA", por)
        mapa.carregar(os.path.join(self.dest, "Backup_Ana"))
        c = mapa.certificado()
        nao = [g for g in c["grupos"] if g["causa"] == "nao_escolhido"]
        self.assertTrue(nao and "novo backup" in nao[0]["resolver"])
        self.assertTrue(any("Gravou e releu" in x["titulo"] for x in c["checagens"]))


class LeituraDoDisco(unittest.TestCase):
    def test_mesmo_hash(self):
        fd, p = tempfile.mkstemp()
        os.write(fd, os.urandom(9 * 1024 * 1024 + 123))
        os.close(fd)
        try:
            with open(p, "rb") as fh:
                self.assertEqual(disco.sha256(p), hashlib.sha256(fh.read()).hexdigest())
        finally:
            os.remove(p)


if __name__ == "__main__":
    unittest.main()
