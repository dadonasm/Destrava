# -*- coding: utf-8 -*-
"""Rodada C: Dados em todos os níveis (explorar, ver, abrir, marcar) e a rota de prévia com Range."""
import os
import shutil
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request

from nucleo import dados


def escreve(p, conteudo=b"x"):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "wb") as fh:
        fh.write(conteudo)


class ComCasa(unittest.TestCase):
    """Uma pasta de usuário de mentira, com o que importa para as regras."""

    def setUp(self):
        self.h = tempfile.mkdtemp(prefix="destrava_casa_")
        j = lambda *p: os.path.join(self.h, *p)
        escreve(j("Documents", "contrato.pdf"), b"%PDF-1.4 teste")
        escreve(j("Pictures", "foto.jpg"), b"\xff\xd8\xff" + b"0" * 5000)
        escreve(j("Movies", "video.mp4"), bytes(range(256)) * 400)
        escreve(j("Downloads", "instalador.exe"), b"MZ")
        escreve(j("Downloads", "pagina.html"), b"<script>alert(1)</script>")
        escreve(j(".ssh", "id_rsa"), b"-----BEGIN KEY-----")
        escreve(j("Library", "Keychains", "login.keychain-db"), b"k")
        escreve(j("Projetos", "grande", "a.bin"), b"0" * 20000)
        dados.set_helpers(user_home=lambda: self.h)
        dados._HOMES[:] = [("teste", self.h)]  # só esta "pessoa": não varre os usuários reais do computador
        self.j = j

    def tearDown(self):
        dados.MEDIR["cancel"].set()
        dados.set_helpers(user_home=None)
        dados.ITENS.clear()
        shutil.rmtree(self.h, ignore_errors=True)

    def espera_medir(self):
        for _ in range(100):
            if not dados.MEDIR["ativo"]:
                return
            time.sleep(0.05)


class Explorar(ComCasa):
    def test_raiz_mostra_os_usuarios(self):
        r = dados.explorar(None)
        self.assertEqual([f["nome"] for f in r["filhos"]], ["teste"])

    def test_entrar_ate_o_arquivo(self):
        r = dados.explorar(dados.no_de(self.h))
        nomes = {f["nome"]: f for f in r["filhos"]}
        self.assertIn("Projetos", nomes)
        self.assertEqual(nomes["Documents"]["zona"], "vermelha", "pasta principal: dá para entrar, não para limpar inteira")
        self.assertTrue(nomes[".ssh"]["credencial"])
        self.espera_medir()
        r = dados.explorar(dados.no_de(self.h))
        proj = [f for f in r["filhos"] if f["nome"] == "Projetos"][0]
        self.assertIsNotNone(proj["bytes"])
        r = dados.explorar(proj["no"])
        self.assertEqual([m["nome"] for m in r["migalhas"]], ["Usuários", "teste", "Projetos"])

    def test_vermelha_da_para_ver_mas_nao_marcar(self):
        kc = dados.no_de(self.j("Library", "Keychains"))
        r = dados.explorar(kc)
        self.assertEqual(r["zona"], "vermelha")
        self.assertFalse(r["filhos"][0]["pode_marcar"])
        self.assertIsNone(r["filhos"][0]["previa"])

    def test_fora_das_pastas_de_usuario(self):
        with self.assertRaises(ValueError):
            dados.caminho_no(dados.no_de(os.path.dirname(self.h)))
        with self.assertRaises(ValueError):
            dados.caminho_no(999999)


class VerEAbrir(ComCasa):
    def test_tipos(self):
        self.assertEqual(dados.tipo_previa(self.j("Pictures", "foto.jpg")), "imagem")
        self.assertEqual(dados.tipo_previa(self.j("Movies", "video.mp4")), "video")
        self.assertEqual(dados.previa(dados.no_de(self.j("Downloads", "pagina.html")))[1], "text/plain; charset=utf-8", "html nunca vira página")
        with self.assertRaises(ValueError):
            dados.previa(dados.no_de(self.j(".ssh", "id_rsa")))
        self.assertFalse(dados.pode_abrir(self.j("Downloads", "instalador.exe")))
        self.assertFalse(dados.pode_abrir(self.j(".ssh", "id_rsa")))
        self.assertTrue(dados.pode_abrir(self.j("Documents", "contrato.pdf")))


class Marcar(ComCasa):
    def test_marcar_subitem_e_selecionar(self):
        with self.assertRaises(ValueError):
            dados.marcar(dados.no_de(self.j("Documents")))
        with self.assertRaises(ValueError):
            dados.marcar(dados.no_de(self.j(".ssh", "id_rsa")))
        i1 = dados.marcar(dados.no_de(self.j("Projetos", "grande")))
        self.assertEqual(dados.marcar(dados.no_de(self.j("Projetos", "grande"))), i1)
        it = dados.ITENS[i1]
        self.assertEqual((it["zona"], it["usuario"], it["tipo"]), ("ambar", "teste", "pasta"))
        self.assertEqual(len(dados._selecionar([i1])), 1)

    def test_id_novo_nao_reaproveita_id_existente(self):
        a = dados.marcar(dados.no_de(self.j("Projetos", "grande", "a.bin")))
        b = dados.marcar(dados.no_de(self.j("Movies", "video.mp4")))
        dados.ITENS.pop(a)
        c = dados.marcar(dados.no_de(self.j("Pictures", "foto.jpg")))
        self.assertNotIn(c, (a, b))
        self.assertEqual(dados.ITENS[b]["titulo"], "video.mp4")

    def test_offload_separa_por_usuario(self):
        self.assertEqual(dados._rel_home(self.j("Movies", "video.mp4")), os.path.join("teste", "Movies", "video.mp4"))


class RotaDePrevia(ComCasa):
    @classmethod
    def setUpClass(cls):
        from nucleo import dd_backup
        from http.server import ThreadingHTTPServer
        cls.dd = dd_backup
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), dd_backup.Handler)
        cls.porta = cls.srv.server_address[1]
        dd_backup.APP.allowed_hosts = {"127.0.0.1:%d" % cls.porta}
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def get(self, caminho, headers=None, token=True):
        url = "http://127.0.0.1:%d%s%st=%s" % (self.porta, caminho, "&" if "?" in caminho else "?", self.dd.APP.token if token else "x")
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers or {}), timeout=10) as r:
                return r.status, dict(r.headers), r.read()
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), e.read()

    def test_video_em_partes(self):
        no = dados.no_de(self.j("Movies", "video.mp4"))
        st, h, b = self.get("/api/dados/ver?no=%d" % no, {"Range": "bytes=10-19"})
        self.assertEqual(st, 206)
        self.assertEqual(b, bytes(range(10, 20)))
        self.assertEqual(h["Content-Range"], "bytes 10-19/102400")
        self.assertIn("sandbox", h["Content-Security-Policy"])
        self.assertEqual(h["X-Content-Type-Options"], "nosniff")
        st, h, b = self.get("/api/dados/ver?no=%d" % no)
        self.assertEqual((st, len(b)), (200, 102400))

    def test_html_vem_como_texto_e_sem_token_nao_vem(self):
        no = dados.no_de(self.j("Downloads", "pagina.html"))
        st, h, b = self.get("/api/dados/ver?no=%d" % no)
        self.assertTrue(h["Content-Type"].startswith("text/plain"))
        self.assertEqual(self.get("/api/dados/ver?no=%d" % no, token=False)[0], 401)
        self.assertEqual(self.get("/api/dados/ver?no=%d" % dados.no_de(self.j(".ssh", "id_rsa")))[0], 400)


if __name__ == "__main__":
    unittest.main()
