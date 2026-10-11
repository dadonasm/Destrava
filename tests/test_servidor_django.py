# -*- coding: utf-8 -*-
"""Servidor da loja em Django: o contrato HTTP (R2) igual ao do servidor antigo, e o agente de verdade falando com ele."""
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest

from tests._django import DJANGO

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WIN10_HD = os.path.join(RAIZ, "tests", "fixtures", "win10_hd.json")

if DJANGO:
    from django.test import Client, SimpleTestCase, override_settings

    from apps.servidor import armazenamento, auth
    from nucleo import termo
else:
    SimpleTestCase = unittest.TestCase


@unittest.skipUnless(DJANGO, "Django não instalado (só o motor é testado aqui)")
class Contrato(SimpleTestCase):
    def setUp(self):
        self.dados = tempfile.mkdtemp(prefix="destrava_srv_")
        self.ov = override_settings(DESTRAVA_SERVIDOR_DADOS=self.dados, ALLOWED_HOSTS=["localhost", "destrava.exemplo.com"], DESTRAVA_URL_PUBLICA="")
        self.ov.enable()
        armazenamento.preparar()
        auth.FALHAS.clear()
        self.chave = auth.nova_chave("Técnico Teste")
        self.c = Client(HTTP_HOST="localhost")
        self.A = {"HTTP_AUTHORIZATION": "Bearer " + self.chave}

    def tearDown(self):
        self.ov.disable()
        armazenamento.preparar()
        shutil.rmtree(self.dados, ignore_errors=True)

    def j(self, r):
        return json.loads(r.content)

    def test_publico_sem_chave_e_cabecalhos(self):
        r = self.c.get("/iniciar.sh")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"SERVIDOR='http://localhost'", r.content)
        self.assertTrue(r["Content-Type"].startswith("text/plain"))
        self.assertEqual((r["Cache-Control"], r["X-Content-Type-Options"]), ("no-store", "nosniff"))
        self.assertIn(b"$Servidor = 'http://localhost'", self.c.get("/iniciar.ps1").content)

    def test_https_atras_do_tunel_e_host_malicioso(self):
        r = self.c.get("/iniciar.ps1", HTTP_HOST="destrava.exemplo.com", HTTP_X_FORWARDED_PROTO="https")
        self.assertIn(b"$Servidor = 'https://destrava.exemplo.com'", r.content)
        r = self.c.get("/iniciar.ps1", HTTP_HOST="destrava.exemplo.com", HTTP_CF_VISITOR='{"scheme":"https"}')
        self.assertIn(b"https://destrava.exemplo.com", r.content)
        self.assertEqual(self.c.get("/iniciar.ps1", HTTP_HOST="x';Remove-Item C:\\").status_code, 400)

    def test_chave(self):
        self.assertEqual(self.c.get("/pacote/info").status_code, 401)
        r = self.c.get("/api/maquinas", HTTP_AUTHORIZATION="Bearer dtv_errada")
        self.assertEqual((r.status_code, self.j(r)), (401, {"erro": "Chave de técnico inválida."}))
        r = self.c.get("/api/quem", **self.A)
        self.assertEqual(self.j(r), {"tecnico": "Técnico Teste", "versao": "3.1"})

    def test_bloqueio_por_ip(self):
        h = {"HTTP_X_FORWARDED_FOR": "203.0.113.9"}
        codes = [self.c.get("/api/quem", HTTP_AUTHORIZATION="Bearer dtv_x", **h).status_code for _ in range(11)]
        self.assertEqual(codes[-1], 429)
        self.assertEqual(self.j(self.c.get("/api/quem", **dict(self.A, **h)))["erro"], "Muitas tentativas com chave errada. Espere alguns minutos.")
        self.assertEqual(self.c.get("/api/quem", HTTP_CF_CONNECTING_IP="203.0.113.10", **self.A).status_code, 200)

    def test_maquinas_e_caminhos(self):
        put = lambda u, d: self.c.put(u, data=d, content_type="application/octet-stream", **self.A)
        for u in ("/api/maquina/DD-AAAA-BBBB/..%2Fchaves.json", "/api/maquina/..%2F..%2Fx/meta.json", "/api/maquina/DD-AAAA-BBBB/x.py", "/api/maquina/DD-AAAA-BBBB/.oculto.json"):
            self.assertEqual(put(u, b"{}").status_code, 400, u)
        self.assertEqual(put("/api/maquina/DD-AAAA-BBBB/meta.json", b"nao e json").status_code, 400)
        self.assertEqual(put("/api/maquina/DD-AAAA-BBBB/grande.html", b"x" * (armazenamento.MAX_ARQ + 1)).status_code, 400)
        self.assertEqual(self.j(put("/api/maquina/DD-AAAA-BBBB/meta.json", b'{"nome":"PC"}')), {"ok": True})
        self.assertEqual(self.j(self.c.get("/api/maquina/DD-AAAA-BBBB", **self.A))["arquivos"], {"meta.json": '{"nome":"PC"}'})
        self.assertEqual(self.j(self.c.delete("/api/maquina/DD-AAAA-BBBB", **self.A)), {"ok": True})
        self.assertFalse(os.path.exists(os.path.join(self.dados, "maquinas", "DD-AAAA-BBBB")))
        self.assertEqual(self.c.get("/api/maquina/..", **self.A).status_code, 400)

    def test_registro_encadeado(self):
        post = lambda d: self.c.post("/api/log", data=json.dumps(d), content_type="application/json", **self.A)
        regs = [self.j(post({"evento": "os_registrada", "mid": "DD-OS00-TEST", "os": termo.OS_AUTO, "quando": "2001-01-01 00:00:00",
                             "hash": "falso", "prev": "falso", "n": 99, "tecnico_servidor": "outro"})) for _ in range(2)]
        self.assertNotEqual(regs[0]["os"], regs[1]["os"])
        self.assertEqual(regs[0]["tecnico_servidor"], "Técnico Teste", "campo reservado vindo do cliente é descartado")
        self.assertEqual((regs[0]["n"], regs[1]["n"]), (1, 2))
        self.assertEqual(regs[0]["quando_pc"], "2001-01-01 00:00:00")
        self.assertNotEqual(regs[0]["quando"], "2001-01-01 00:00:00")
        self.assertTrue(self.j(self.c.get("/api/log/verificar", **self.A))["ok"])
        self.assertEqual(len(self.j(self.c.get("/api/log?mid=DD-OS00-TEST", **self.A))["linhas"]), 2)
        self.assertEqual(post({"evento": "x", "mid": "../../etc"}).status_code, 400)
        self.assertEqual(self.c.post("/api/log", data="{nao json", content_type="application/json", **self.A).status_code, 400)
        self.assertEqual(self.c.get("/api/log", **self.A).status_code, 400)

    def test_pacote_e_runtime(self):
        r = self.c.get("/pacote/info?formato=txt", **self.A)
        self.assertRegex(r.content.decode(), r"^versao=3\.1\nsha256=[0-9a-f]{64}\n")
        r = self.c.get("/pacote/Destrava.zip", **self.A)
        self.assertEqual((r["Content-Type"], r["Content-Disposition"]), ("application/zip", 'attachment; filename="Destrava.zip"'))
        self.assertEqual(self.c.get("/runtime/nao-existe", **self.A).status_code, 404)

    def test_resolver_e_indice(self):
        r = self.c.post("/api/resolver", data=json.dumps({"ids": {"uuid": "UUID-1234-ABCD"}, "host": "PC"}), content_type="application/json", **self.A)
        self.assertRegex(self.j(r)["mid"], r"^DD-[A-Z0-9]{4}-[A-Z0-9]{4}$")
        self.assertEqual(self.j(self.c.get("/api/maquinas", **self.A)), {"maquinas": []})

    def test_home_publica_sem_dados(self):
        os.makedirs(os.path.join(self.dados, "maquinas", "DD-CLIE-NTE1"), exist_ok=True)
        r = self.c.get("/")
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        self.assertIn("irm http://localhost/iniciar.ps1 | iex", html)
        self.assertIn("curl -fsSL http://localhost/iniciar.sh | sh", html)
        self.assertIn("3.1", html)
        self.assertNotIn("DD-CLIE-NTE1", html)
        self.assertNotIn("Técnico Teste", html)

    def test_healthz_e_404(self):
        self.assertEqual(self.j(self.c.get("/healthz")), {"ok": True})
        self.assertEqual(self.j(self.c.get("/nada")), {"erro": "rota desconhecida"})


def porta_livre():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


@unittest.skipUnless(DJANGO, "Django não instalado")
class AgenteContraDjango(unittest.TestCase):
    """O agente de verdade (conexao.py) contra o Django rodando em OUTRO processo (eles não podem dividir os globais do motor)."""

    @classmethod
    def setUpClass(cls):
        cls.dados = tempfile.mkdtemp(prefix="destrava_dj_")
        env = dict(os.environ, DESTRAVA_SERVIDOR_DADOS=cls.dados, DJANGO_SETTINGS_MODULE="config.settings")
        out = subprocess.run([sys.executable, "manage.py", "nova_chave", "Técnico Teste"], cwd=RAIZ, env=env, capture_output=True, text=True, check=True).stdout
        cls.chave = re.search(r"(dtv_\S+)", out).group(1)
        cls.porta = porta_livre()
        cls.url = "http://127.0.0.1:%d" % cls.porta
        cls.proc = subprocess.Popen([sys.executable, "manage.py", "runserver", "127.0.0.1:%d" % cls.porta, "--noreload"], cwd=RAIZ, env=env,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(100):
            try:
                socket.create_connection(("127.0.0.1", cls.porta), 0.2).close()
                break
            except OSError:
                time.sleep(0.1)

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.wait(10)
        shutil.rmtree(cls.dados, ignore_errors=True)

    def setUp(self):
        from nucleo import conexao, ficha, termo
        self.ficha, self.termo = ficha, termo
        self.cache = tempfile.mkdtemp(prefix="destrava_cache_")
        self._store, self._log = ficha.STORE, termo.LOG
        ficha.STORE, termo.LOG = os.path.join(self.cache, "maquinas"), os.path.join(self.cache, "consentimentos.log")
        self.con = conexao.Conexao(self.url, self.chave, "teste")
        self.con.testar()
        ficha.SINCRONIA, termo.REMOTO, termo.MODO = self.con, self.con, "servidor"
        ficha.carregar_coleta(WIN10_HD)

    def tearDown(self):
        f, t = self.ficha, self.termo
        f.SINCRONIA, t.REMOTO, t.MODO = None, None, "pendrive"
        f.STORE, t.LOG = self._store, self._log
        f.REPLAY.clear()
        f._MID.clear()
        f._PUXADAS.clear()
        shutil.rmtree(self.cache, ignore_errors=True)

    def test_atendimento_completo_e_sem_rede(self):
        f, t = self.ficha, self.termo
        mid = f.machine_id_cache()
        self.assertTrue(t.aceitar(mid, "Técnico Teste", "terceiros", "Padaria Pão Quente")["status"]["aceito"])
        self.assertFalse(os.path.exists(t.LOG), "o registro não pode ficar no computador atendido")
        self.assertRegex(t.registrar_os(mid, "Maria da Padaria", ["ficha", "melhorias"])["os"]["os"], r"^OS-\d{8}-\d{2}$")
        f.salvar_ficha(f.coletar())
        arqs = os.listdir(os.path.join(self.dados, "maquinas", mid))
        for prefixo in ("historico.json", "meta.json", "ficha-", "termo-", "os-"):
            self.assertTrue(any(a.startswith(prefixo) for a in arqs), prefixo)
        self.assertEqual([m["mid"] for m in f.listar_maquinas() if m["atual"]], [mid])
        self.assertTrue(t.log_verificar()["ok"], "cadeia de hashes íntegra")
        # sem rede: fica pendente e vai quando voltar
        self.con.url = "http://127.0.0.1:%d" % porta_livre()
        f.hist_add(mid, "nota", "anotado sem rede")
        self.assertEqual(self.con.estado()["pendentes"], 1)
        self.con.url = self.url
        self.assertEqual(self.con.enviar_pendentes(), 0)
        with open(os.path.join(self.dados, "maquinas", mid, "historico.json"), encoding="utf-8") as fh:
            self.assertIn("anotado sem rede", fh.read())


if __name__ == "__main__":
    unittest.main()
