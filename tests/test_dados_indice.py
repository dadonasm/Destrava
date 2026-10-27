# -*- coding: utf-8 -*-
"""Gerenciamento de dados: índice de arquivos gravado na varredura e as operações (renomear, nova pasta, mover, copiar)."""
import os
import shutil
import tempfile
import time
import unittest
from unittest import mock

from nucleo import dados


def escreve(p, conteudo=b"x"):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "wb") as fh:
        fh.write(conteudo)


class ComIndice(unittest.TestCase):
    """Uma pasta de usuário de mentira, varrida de verdade, com o índice numa pasta temporária."""

    def setUp(self):
        self.h = tempfile.mkdtemp(prefix="destrava_casa_")
        self.idx = tempfile.mkdtemp(prefix="destrava_idx_")
        j = self.j = lambda *p: os.path.join(self.h, *p)
        escreve(j("Movies", "férias.mp4"), b"v" * 40000)
        escreve(j("Movies", "Viagem", "praia.mov"), b"v" * 20000)
        escreve(j("Pictures", "foto.jpg"), b"f" * 9000)
        escreve(j("Documents", "contrato.pdf"), b"%PDF" + b"d" * 7000)
        escreve(j("Documents", "50%_desconto.pdf"), b"%PDF" + b"d" * 3000)
        escreve(j("Projetos", "notas.txt"), b"t" * 5000)
        escreve(j(".ssh", "id_rsa"), b"-----BEGIN KEY-----")
        escreve(j("Projetos", "servidor.pem"), b"-----BEGIN KEY-----")
        self.pu = mock.patch.object(dados, "pastas_usuarios", lambda: [("teste", self.h)])
        self.pu.start()
        dados.set_helpers(user_home=lambda: self.h, indice_dir=self.idx)
        dados.CANCEL.clear()
        dados._varrer(90, 100)
        self.assertEqual(dados.ST["fase"], "pronto", dados.ST.get("erro"))

    def tearDown(self):
        dados.MEDIR["cancel"].set()
        self.pu.stop()
        dados.set_helpers(user_home=None, indice_dir=None)
        dados.ITENS.clear()
        dados.ST["acao"]["rodando"] = False
        shutil.rmtree(self.h, ignore_errors=True)
        shutil.rmtree(self.idx, ignore_errors=True)

    def consulta(self, **kw):
        return dados.indice_consulta(**kw)

    def nomes(self, r):
        return sorted(x["nome"] for x in r["rows"])

    def espera_acao(self):
        for _ in range(200):
            if not dados.ST["acao"]["rodando"]:
                return dados.ST["acao"]
            time.sleep(0.02)
        self.fail("operação não terminou")


class Indice(ComIndice):
    def test_existe_e_conta_os_arquivos(self):
        e = dados.indice_estado()
        self.assertTrue(e["existe"])
        self.assertFalse(e["parcial"])
        self.assertGreaterEqual(e["n"], 6)

    def test_faixas_batem_com_o_cockpit(self):
        r = self.consulta()
        ck = dados.RES["cockpit"]
        if ck["aviso"]:
            self.skipTest("cockpit ajustado proporcionalmente neste disco")
        for fx in ("fotos", "videos", "documentos"):
            self.assertEqual(r["faixas"][fx]["bytes"], ck["faixas_usuario"][fx], fx)
        self.assertFalse(ck["medindo"], "nos testes o disco de verdade não é medido: o resto vai direto para Dados do Sistema")
        self.assertEqual(sum(ck["faixas"].values()), ck["usado"], "as faixas somam o espaço usado")

    def test_filtrar_por_faixa_e_categoria(self):
        r = self.consulta(faixa="fotos|videos")
        self.assertEqual(self.nomes(r), ["foto.jpg", "férias.mp4", "praia.mov"])
        self.assertEqual({c["cat"] for c in r["cats"]}, {"Vídeos", "Fotos"})
        r = self.consulta(faixa="fotos|videos", cat="Vídeos", ordem="maior")
        self.assertEqual([x["nome"] for x in r["rows"]], ["férias.mp4", "praia.mov"])

    def test_colunas_da_lista(self):
        x = [x for x in self.consulta(q="contrato")["rows"]][0]
        self.assertEqual((x["faixa"], x["grupo"], x["sug"], x["tipo_rot"]), ("documentos", "Pessoal", "", "PDF"))
        self.assertGreater(x["criado"], 0)

    def test_filtros_contam_com_os_outros_aplicados(self):
        r = self.consulta(faixa="videos", facetas=True)
        self.assertEqual(r["total"], 2)
        self.assertEqual(r["facetas"]["faixa"].get("fotos"), 1, "a contagem da própria faixa ignora o filtro de faixa")
        self.assertEqual(set(r["facetas"]["tipo"]), {"Vídeo"}, "os outros filtros já contam só os vídeos")
        self.assertEqual(self.consulta(tam="p|m", limit=0)["total"], self.consulta(limit=0)["total"], "tudo aqui é pequeno")
        self.assertEqual(self.consulta(uso="d30", limit=0)["total"], self.consulta(limit=0)["total"], "tudo foi mexido agora")

    def test_busca_sem_acento_e_com_porcentagem(self):
        self.assertEqual(self.nomes(self.consulta(q="ferias")), ["férias.mp4"])
        self.assertEqual(self.nomes(self.consulta(q="50%")), ["50%_desconto.pdf"])
        self.assertEqual(self.nomes(self.consulta(q="_desc")), ["50%_desconto.pdf"])

    def test_pasta_e_trilha(self):
        movies = dados.no_de(self.j("Movies"))
        r = self.consulta(pasta=movies)
        self.assertEqual(self.nomes(r), ["férias.mp4", "praia.mov"])
        self.assertEqual([m["nome"] for m in r["migalhas"]], ["teste", "Movies"])
        r = self.consulta(pasta=movies, visao="pastas")
        self.assertEqual(self.nomes(r), ["férias.mp4"])
        self.assertEqual([p["nome"] for p in r["pastas"]], ["Viagem"])
        self.assertEqual(r["pastas"][0]["bytes"], self.consulta(pasta=dados.no_de(self.j("Movies", "Viagem")))["bytes"])

    def test_raiz_mostra_os_usuarios(self):
        r = self.consulta(visao="pastas")
        self.assertEqual([p["nome"] for p in r["pastas"]], ["teste"])
        self.assertEqual(r["rows"], [])

    def test_credencial_fica_travada(self):
        self.assertEqual(self.consulta(q="id_rsa")["rows"], [], "pasta de credenciais nem é lida")
        r = self.consulta(q="servidor.pem")
        self.assertEqual(len(r["rows"]), 1)
        self.assertFalse(r["rows"][0]["pode_marcar"])
        self.assertIsNone(r["rows"][0]["previa"])


class Operacoes(ComIndice):
    def test_renomear_arquivo(self):
        r = dados.renomear(dados.no_de(self.j("Projetos", "notas.txt")), "anotações.txt")
        self.assertTrue(os.path.isfile(self.j("Projetos", "anotações.txt")))
        self.assertEqual(r["nome"], "anotações.txt")
        self.assertEqual(self.nomes(self.consulta(q="anotacoes")), ["anotações.txt"])
        self.assertEqual(self.consulta(q="notas.txt")["rows"], [])

    def test_renomear_pasta_leva_os_filhos_no_indice(self):
        antes = self.consulta(pasta=dados.no_de(self.j("Movies")))["bytes"]
        dados.renomear(dados.no_de(self.j("Movies", "Viagem")), "Praia 2025")
        r = self.consulta(q="praia.mov")
        self.assertEqual(r["rows"][0]["path"], self.j("Movies", "Praia 2025", "praia.mov"))
        self.assertEqual(self.consulta(pasta=dados.no_de(self.j("Movies")))["bytes"], antes)
        self.assertEqual([p["nome"] for p in self.consulta(pasta=dados.no_de(self.j("Movies")), visao="pastas")["pastas"]], ["Praia 2025"])

    def test_renomear_recusa_nome_invalido_conflito_e_bloqueado(self):
        no = dados.no_de(self.j("Documents", "contrato.pdf"))
        for ruim in ("", "..", "a/b", "x" * 300):
            with self.assertRaises(ValueError):
                dados.renomear(no, ruim)
        with self.assertRaises(ValueError):
            dados.renomear(no, "50%_desconto.pdf")
        with self.assertRaises(ValueError):
            dados.renomear(dados.no_de(self.j(".ssh", "id_rsa")), "chave")
        with self.assertRaises(ValueError):
            dados.renomear(dados.no_de(self.j("Documents")), "Docs")  # pasta principal

    def test_nova_pasta(self):
        r = dados.nova_pasta(dados.no_de(self.j("Documents")), "Contratos 2025")
        self.assertTrue(os.path.isdir(self.j("Documents", "Contratos 2025")))
        pastas = self.consulta(pasta=dados.no_de(self.j("Documents")), visao="pastas")["pastas"]
        self.assertIn("Contratos 2025", [p["nome"] for p in pastas])
        with self.assertRaises(ValueError):
            dados.nova_pasta(dados.no_de(self.j("Documents")), "Contratos 2025")
        with self.assertRaises(ValueError):
            dados.nova_pasta(dados.no_de(self.j(".ssh")), "x")
        self.assertTrue(r["no"])

    def test_mover_no_mesmo_disco_e_conflito_nao_sobrescreve(self):
        escreve(self.j("Projetos", "contrato.pdf"), b"outro")
        nos = [dados.no_de(self.j("Documents", "contrato.pdf"))]
        dest = dados.no_de(self.j("Projetos"))
        pf = dados.preflight_destino(nos, dest, "mover")
        self.assertTrue(pf["ok"])
        self.assertEqual(pf["conflitos"], ["contrato.pdf"])
        with self.assertRaises(ValueError):
            dados.mover(nos, dest, "")
        dados.mover(nos, dest, "manter")
        a = self.espera_acao()
        self.assertEqual(a["resultado"]["itens"], 1, a["erros"])
        with open(self.j("Projetos", "contrato.pdf"), "rb") as fh:
            self.assertEqual(fh.read(), b"outro")
        self.assertTrue(os.path.isfile(self.j("Projetos", "contrato 2.pdf")))
        self.assertFalse(os.path.exists(self.j("Documents", "contrato.pdf")))
        self.assertEqual(self.nomes(self.consulta(pasta=dest)), ["contrato 2.pdf", "notas.txt", "servidor.pem"])

    def test_mover_pular_conflito(self):
        escreve(self.j("Projetos", "contrato.pdf"), b"outro")
        nos = [dados.no_de(self.j("Documents", "contrato.pdf"))]
        dados.mover(nos, dados.no_de(self.j("Projetos")), "pular")
        a = self.espera_acao()
        self.assertEqual(a["resultado"]["pulados"], 1)
        self.assertTrue(os.path.isfile(self.j("Documents", "contrato.pdf")))

    def test_copiar_pasta_confere_e_mantem_original(self):
        nos = [dados.no_de(self.j("Movies", "Viagem"))]
        dest = dados.no_de(self.j("Documents"))
        dados.copiar(nos, dest, "")
        a = self.espera_acao()
        self.assertEqual(a["resultado"]["itens"], 1, a["erros"])
        self.assertTrue(os.path.isfile(self.j("Movies", "Viagem", "praia.mov")))
        self.assertEqual(dados.sha256_arquivo(self.j("Documents", "Viagem", "praia.mov")), dados.sha256_arquivo(self.j("Movies", "Viagem", "praia.mov")))
        self.assertEqual(len(self.consulta(q="praia.mov")["rows"]), 2)

    def test_destino_dentro_da_origem_e_mesma_pasta(self):
        movies = dados.no_de(self.j("Movies", "Viagem"))
        self.assertFalse(dados.preflight_destino([movies], movies, "mover")["ok"])
        self.assertFalse(dados.preflight_destino([dados.no_de(self.j("Projetos", "notas.txt"))], dados.no_de(self.j("Projetos")), "mover")["ok"])

    def test_destino_e_origem_bloqueados(self):
        with self.assertRaises(ValueError):
            dados.preflight_destino([dados.no_de(self.j("Projetos", "notas.txt"))], dados.no_de(self.j(".ssh")), "copiar")
        with self.assertRaises(ValueError):
            dados.preflight_destino([dados.no_de(self.j(".ssh", "id_rsa"))], dados.no_de(self.j("Projetos")), "copiar")

    def test_limpar_tira_do_indice(self):
        ids = dados.marcar_nos([dados.no_de(self.j("Projetos", "notas.txt"))])
        dados.limpar(ids, definitivo=True)
        self.espera_acao()
        self.assertEqual(self.consulta(q="notas")["rows"], [])


class UltimaVarredura(ComIndice):
    def reinicia(self):
        """O que sobra depois de fechar e abrir o programa: só o índice no disco."""
        dados.ITENS.clear()
        dados.RES["cockpit"] = None
        dados.ST["fase"] = "ocioso"

    def test_volta_depois_de_reiniciar(self):
        ck = dict(dados.RES["cockpit"])
        ids = sorted(dados.ITENS)
        self.reinicia()
        e = dados.estado()
        self.assertEqual(e["fase"], "pronto")
        self.assertEqual(e["cockpit"]["faixas"], ck["faixas"])
        self.assertEqual(sorted(dados.ITENS), ids)
        self.assertGreater(e["indice"]["quando"], 0)
        self.assertEqual(e["indice"]["idle_dias"], 90)
        novo = dados.marcar(dados.no_de(self.j("Projetos", "notas.txt")))
        self.assertNotIn(novo, ids, "item novo não herda id de item restaurado")

    def test_mexidas_e_esquecer(self):
        self.assertEqual(dados.indice_estado()["mexidas"], 0)
        dados.renomear(dados.no_de(self.j("Projetos", "notas.txt")), "n2.txt")
        dados.nova_pasta(dados.no_de(self.j("Projetos")), "Nova")
        self.assertEqual(dados.indice_estado()["mexidas"], 2)
        dados.reset()
        self.assertEqual(dados.estado()["fase"], "ocioso")
        self.assertFalse(dados.estado()["indice"]["existe"])

    def test_parcial_volta_como_cancelado(self):
        c = dados._idx_con()
        c.execute("UPDATE meta SET v='1' WHERE k='parcial'")
        c.commit()
        c.close()
        self.reinicia()
        self.assertEqual(dados.estado()["fase"], "cancelado")


class Panorama(ComIndice):
    def test_maiores_e_pasta_dominante(self):
        escreve(self.j("Projetos", "grande", "sub", "pesado.bin"), b"p" * 300000)
        dados._varrer(90, 100)
        r = dados.indice_panorama()
        self.assertEqual(r["arquivos"][0]["nome"], "pesado.bin")
        self.assertEqual(r["pastas"][0]["path"], self.j("Projetos", "grande", "sub"), "desce até onde o peso se concentra")
        self.assertEqual(r["arquivos"][0]["pasta_no"], dados.no_de(self.j("Projetos", "grande", "sub")))
        self.assertEqual(r["parados"], [], "nada de 50 MB nesta casa de teste")

    def test_sem_indice(self):
        dados.reset()
        self.assertEqual(dados.indice_panorama()["pastas"], [])


class Trancados(ComIndice):
    def setUp(self):
        super().setUp()
        self.od = self.j("Library", "Group Containers", "UBF8T346G9.OneDriveSyncClientSuite", "OneDrive.noindex", "OneDrive", "video.mov")
        escreve(self.od, b"v" * 9000)
        escreve(self.j("Library", "Group Containers", "com.exemplo", "dados.bin"), b"d" * 3000)
        os.makedirs(self.j("Library", "CloudStorage", "OneDrive-Teste"))
        dados._varrer(90, 100)

    def test_onedrive_explica_e_aponta_a_pasta(self):
        x = self.consulta(q="video.mov")["rows"][0]
        self.assertFalse(x["pode_marcar"])
        self.assertIn("OneDrive", x["motivo"])
        self.assertEqual(dados.caminho_no(x["ajuda_no"]), self.j("Library", "CloudStorage", "OneDrive-Teste"))

    def test_outro_app_tem_motivo_proprio(self):
        x = self.consulta(q="dados.bin")["rows"][0]
        self.assertFalse(x["pode_marcar"])
        self.assertTrue(x["motivo"].startswith("Dados internos de aplicativos"))
        self.assertIsNone(x["ajuda_no"])

    def test_indice_antigo_ganha_o_motivo_novo(self):
        c = dados._idx_con()
        c.execute("UPDATE arq SET zona='dados de sistema, contas ou credenciais' WHERE zona<>''")
        c.commit()
        c.close()
        self.assertIn("OneDrive", self.consulta(q="video.mov")["rows"][0]["motivo"])


class GrupoESugestao(ComIndice):
    """Grupo e Sugestão de varredura gravados no índice: o filtro da gaveta no lugar da aba Sugestão."""

    def setUp(self):
        ComIndice.setUp(self)
        j = self.j
        escreve(j(".Trash", "velho.zip"), b"z" * 3000)
        escreve(j(".cache", "app", "c.bin"), b"c" * 2000)
        escreve(j("Downloads", "setup.dmg"), b"d" * 9000)
        dados._varrer(90, 100)

    def linha(self, nome):
        r = self.consulta(q=nome)["rows"]
        self.assertTrue(r, nome)
        return r[0]

    def test_cada_arquivo_tem_grupo_e_sugestao(self):
        self.assertEqual((self.linha(".Trash")["faixa"], self.linha(".Trash")["grupo"], self.linha(".Trash")["sug"]), ("caches", "Bloqueado", "nao_recomendado"))
        c = self.linha("c.bin")
        self.assertEqual((c["faixa"], c["grupo"]), ("caches", "Cache temporário"))
        self.assertEqual(self.linha("setup.dmg")["grupo"], "Instaladores")
        r = self.consulta(sug="nao_recomendado", facetas=True)
        self.assertIn(".Trash", self.nomes(r))
        self.assertIn("nao_recomendado", r["facetas"]["sug"])

    def test_indice_antigo_pede_varredura_nova(self):
        import sqlite3
        c = sqlite3.connect(dados._idx_arquivo())
        c.execute("PRAGMA user_version=1")
        c.commit()
        c.close()
        e = dados.indice_estado()
        self.assertEqual((e["existe"], e["antigo"]), (False, True))


class VarreduraCompleta(unittest.TestCase):
    """Disco de mentira: raiz com sistema (núcleo e programas) e uma pasta de usuário dentro dela."""

    def setUp(self):
        self.r = tempfile.mkdtemp(prefix="destrava_raiz_")
        self.idx = tempfile.mkdtemp(prefix="destrava_idx_")
        r = self.j = lambda *p: os.path.join(self.r, *p)
        self.h = r("Users", "ana")
        escreve(r("System", "Library", "kernel"), b"k" * 30000)
        escreve(r("Applications", "X.app", "Contents", "x"), b"a" * 50000)
        escreve(r("Library", "Caches", "c.db"), b"c" * 7000)
        escreve(r("opt", "ferramenta", "bin"), b"o" * 3000)
        escreve(r("System", "Volumes", "Data", "Users", "ana", "foto.jpg"), b"f" * 90000)
        escreve(r("Users", "ana", "Pictures", "foto.jpg"), b"f" * 9000)
        escreve(r("Users", "ana", "proj", ".git", "objects", "o1"), b"g" * 4000)
        escreve(r("Users", "ana", "proj", "node_modules", "lib", "i.js"), b"n" * 6000)
        escreve(r("Users", "ana", "Documents", "a.txt"), b"t" * 2000)
        os.link(r("Users", "ana", "Documents", "a.txt"), r("Users", "ana", "Documents", "b.txt"))
        os.symlink(r("Applications"), r("Users", "ana", "atalho"))
        self.pu = mock.patch.object(dados, "pastas_usuarios", lambda: [("ana", self.h)])
        self.pu.start()
        dados.set_helpers(user_home=lambda: self.h, indice_dir=self.idx, raiz_sistema=self.r, so_sistema="mac")
        dados.DESBLOQ.clear()
        dados.CANCEL.clear()
        dados._varrer(90, 100)
        self.assertEqual(dados.ST["fase"], "pronto", dados.ST.get("erro"))

    def tearDown(self):
        self.pu.stop()
        dados.set_helpers(user_home=None, indice_dir=None, raiz_sistema=None, so_sistema=None)
        dados.ITENS.clear()
        dados.DESBLOQ.clear()
        shutil.rmtree(self.r, ignore_errors=True)
        shutil.rmtree(self.idx, ignore_errors=True)

    def linha(self, caminho):
        k = os.path.realpath(caminho)
        for r in dados.indice_consulta(limit=1000)["rows"]:
            if os.path.realpath(r["path"]) == k or r["path"] == caminho:
                return r
        self.fail("não está no índice: %s" % caminho)

    def test_sistema_no_indice_e_travado(self):
        k = self.linha(self.j("System", "Library", "kernel"))
        self.assertEqual((k["usuario"], k["faixa"], k["grupo"], k["trava"]), ("Sistema", "os", "Sistema", "nucleo_so"))
        self.assertFalse(k["pode_marcar"])
        a = self.linha(self.j("Applications", "X.app", "Contents", "x"))
        self.assertEqual((a["faixa"], a["trava"]), ("apps", "protegido"))
        self.assertEqual(self.linha(self.j("Library", "Caches", "c.db"))["faixa"], "caches")
        nomes = [r["path"] for r in dados.indice_consulta(limit=1000)["rows"]]
        self.assertFalse([p for p in nomes if "Volumes" in p], "/System/Volumes (o disco das pessoas) não conta duas vezes")
        self.assertEqual(sum(1 for p in nomes if p.endswith("foto.jpg")), 1)

    def test_pulados_agora_aparecem(self):
        g = self.linha(self.j("Users", "ana", "proj", ".git"))
        self.assertEqual((g["tipo"], g["grupo"], g["bytes"] >= 4000, g["pode_marcar"]), ("pasta", "Bloqueado", True, False))
        n = self.linha(self.j("Users", "ana", "proj", "node_modules"))
        self.assertEqual((n["grupo"], n["trava"], n["bytes"] >= 6000), ("Bloqueado", "protegido", True))
        nomes = [r["path"] for r in dados.indice_consulta(limit=1000)["rows"]]
        self.assertFalse([p for p in nomes if "objects" in p or "i.js" in p], "sem ler por dentro")
        at = self.linha(self.j("Users", "ana", "atalho"))
        self.assertEqual((at["tipo"], at["bytes"], at["trava"]), ("atalho", 0, "fixo"))
        hl = sorted(self.linha(self.j("Users", "ana", "Documents", x))["bytes"] for x in ("a.txt", "b.txt"))
        self.assertEqual(hl[0], 0, "hard link conta o espaço uma vez só")
        self.assertGreater(hl[1], 0)

    def test_cockpit_completo(self):
        ck = dados.RES["cockpit"]
        self.assertTrue(ck["completa"])
        self.assertFalse(ck["medindo"])
        self.assertGreaterEqual(ck["faixas"]["apps"], 50000)
        self.assertGreaterEqual(ck["faixas"]["os"], 30000)
        self.assertGreater(ck["por_usuario"]["Sistema"], 0)
        raiz = dados.indice_consulta(visao="pastas", limit=0)
        self.assertEqual(sorted(p["nome"] for p in raiz["pastas"]), ["Sistema", "ana"])
        self.assertIn("Sistema", raiz["usuarios"])
        pan = dados.indice_panorama()
        self.assertFalse([x for x in pan["arquivos"] if x["usuario"] == "Sistema"], "o painel inicial é sobre o que dá para liberar")

    def test_desbloquear(self):
        no = lambda *p: dados.no_de(self.j(*p))
        nm = no("Users", "ana", "proj", "node_modules")
        r = dados.desbloquear(nm)
        self.assertTrue(r["precisa_confirmar"])
        self.assertIn("dependências", r["risco"])
        with self.assertRaises(ValueError):
            dados.marcar(nm)
        r = dados.desbloquear(nm, True)
        self.assertTrue(r["liberado"])
        row = self.linha(self.j("Users", "ana", "proj", "node_modules"))
        self.assertEqual((row["liberado"], row["pode_marcar"]), (True, True))
        self.assertTrue(dados.marcar(nm))
        with self.assertRaises(ValueError, msg="núcleo do sistema nunca destrava"):
            dados.desbloquear(no("System", "Library", "kernel"), True)
        with self.assertRaises(ValueError, msg="atalho é regra fixa"):
            dados.desbloquear(no("Users", "ana", "atalho"), True)
        dados.bloquear(nm)
        with self.assertRaises(ValueError):
            dados.marcar(nm)
        self.assertTrue(dados.desbloquear(no("Applications", "X.app"), True)["liberado"], "programas fora das pastas: destrava com confirmação")
        for raiz in (self.r, self.h):
            with self.assertRaises(ValueError, msg="o disco ou o usuário inteiro não destrava de uma vez"):
                dados.desbloquear(dados.no_de(raiz), True)


class MedirFora(unittest.TestCase):
    def test_apps_os_e_dados_de_um_disco(self):
        raiz = tempfile.mkdtemp(prefix="destrava_disco_")
        try:
            escreve(os.path.join(raiz, "Applications", "X.app", "Contents", "x"), b"a" * 50000)
            escreve(os.path.join(raiz, "System", "Library", "s"), b"s" * 30000)
            escreve(os.path.join(raiz, "Library", "Caches", "l"), b"l" * 20000)
            escreve(os.path.join(raiz, "Users", "ana", "foto.jpg"), b"f" * 90000)
            escreve(os.path.join(raiz, "System", "Volumes", "Data", "Users", "ana", "foto.jpg"), b"f" * 90000)
            import threading
            progs = []
            out, estimadas = dados.medir_fora(raiz, "mac", threading.Event(), 30, progs.append)
            self.assertEqual(estimadas, [])
            pcts = [p["pct"] for p in progs]
            self.assertEqual(pcts, sorted(pcts), "o progresso só sobe")
            self.assertEqual((pcts[0], pcts[-1]), (0, 100))
            self.assertIn("/Applications", [p["atual"] for p in progs], "mostra a região que está lendo")
            self.assertGreater(len(set(pcts)), 2, "sobe a cada região, não fica parado em 0%")
            self.assertGreaterEqual(out["apps"], 50000)
            self.assertGreaterEqual(out["os"], 30000)
            self.assertLess(out["os"], 90000, "/System/Volumes/Data é o disco das pessoas: não conta como sistema")
            self.assertGreaterEqual(out["dados"], 20000)
            self.assertLess(out["apps"] + out["os"] + out["dados"], 200000, "a pasta dos usuários não entra")
            ck = {"usado": 1000000, "faixas_usuario": {"fotos": 90000}}
            dados._aplicar_fora(ck, out)
            self.assertEqual(sum(ck["faixas"].values()), 1000000, "o que ninguém mediu vira Dados do Sistema")
        finally:
            shutil.rmtree(raiz, ignore_errors=True)

    def test_prazo_por_regiao(self):
        import threading
        raiz = tempfile.mkdtemp(prefix="destrava_disco_")
        try:
            for i in range(300):
                escreve(os.path.join(raiz, "System", "d%d" % i, "s"), b"s" * 10)
            escreve(os.path.join(raiz, "Applications", "X.app", "x"), b"a" * 5000)
            out, estimadas = dados.medir_fora(raiz, "mac", threading.Event(), 0)
            self.assertEqual(estimadas, ["/Applications", "/System"], "cada região estoura o próprio prazo e as outras seguem")
            out, estimadas = dados.medir_fora(raiz, "mac", threading.Event(), 30)
            self.assertEqual(estimadas, [])
            self.assertGreaterEqual(out["apps"], 5000)
        finally:
            shutil.rmtree(raiz, ignore_errors=True)

    def test_medicao_unica_guardada(self):
        import threading
        raiz = tempfile.mkdtemp(prefix="destrava_disco_")
        salvo = dict(dados.FORA)
        try:
            escreve(os.path.join(raiz, "Applications", "X.app", "x"), b"a" * 5000)
            dados.FORA.update(ultimo=None, rodando=False)
            u = dados.medicao_fora(raiz, "mac", threading.Event())
            self.assertGreaterEqual(u["fora"]["apps"], 5000)
            escreve(os.path.join(raiz, "Applications", "Y.app", "y"), b"b" * 5000)
            self.assertIs(dados.medicao_fora(raiz, "mac", threading.Event()), u, "reabrir a tela não mede de novo")
            u["quando"] -= dados.FORA_IDADE + 1
            self.assertGreaterEqual(dados.medicao_fora(raiz, "mac", threading.Event())["fora"]["apps"], 10000, "velha: mede de novo")
            ev = threading.Event()
            ev.set()
            dados.FORA.update(ultimo={"quando": 0})  # a guardada está velha
            self.assertIsNone(dados.medicao_fora(raiz, "mac", ev), "parada não guarda resultado")
            self.assertFalse(dados.FORA["rodando"])
        finally:
            dados.FORA.update(salvo)
            shutil.rmtree(raiz, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
