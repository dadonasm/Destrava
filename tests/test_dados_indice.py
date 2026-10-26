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

    def test_blocos_batem_com_o_cockpit(self):
        r = self.consulta()
        ck = dados.RES["cockpit"]
        if ck["aviso"]:
            self.skipTest("cockpit ajustado proporcionalmente neste disco")
        self.assertEqual(r["blocos"]["midias"]["bytes"], ck["midias"])
        self.assertEqual(r["blocos"]["documentos"]["bytes"], ck["documentos"])

    def test_filtrar_por_bloco_e_categoria(self):
        r = self.consulta(bloco="midias")
        self.assertEqual(self.nomes(r), ["foto.jpg", "férias.mp4", "praia.mov"])
        self.assertEqual({c["cat"] for c in r["cats"]}, {"Vídeos", "Fotos"})
        r = self.consulta(bloco="midias", cat="Vídeos", ordem="maior")
        self.assertEqual([x["nome"] for x in r["rows"]], ["férias.mp4", "praia.mov"])

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
        self.assertEqual(e["cockpit"]["midias"], ck["midias"])
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


if __name__ == "__main__":
    unittest.main()
