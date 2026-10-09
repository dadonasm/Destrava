# -*- coding: utf-8 -*-
"""Rodada B: servidor da loja (chave, caminhos, registro encadeado, pacote) e o programa local em modo servidor."""
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
import urllib.error
import urllib.request

import conexao
import ficha
import termo

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WIN10_HD = os.path.join(RAIZ, "tests", "fixtures", "win10_hd.json")


def porta_livre():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


class ServidorReal(unittest.TestCase):
    """Sobe servidor.py num processo à parte, com dados numa pasta temporária."""

    @classmethod
    def setUpClass(cls):
        cls.dados = tempfile.mkdtemp(prefix="destrava_srv_")
        out = subprocess.run([sys.executable, os.path.join(RAIZ, "servidor.py"), "--dados", cls.dados, "--nova-chave", "Técnico Teste"],
                             capture_output=True, text=True, check=True).stdout
        cls.chave = re.search(r"(dtv_\S+)", out).group(1)
        cls.porta = porta_livre()
        cls.url = "http://127.0.0.1:%d" % cls.porta
        cls.proc = subprocess.Popen([sys.executable, os.path.join(RAIZ, "servidor.py"), "--dados", cls.dados, "--porta", str(cls.porta)],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(50):
            try:
                socket.create_connection(("127.0.0.1", cls.porta), 0.2).close()
                break
            except OSError:
                time.sleep(0.1)

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.wait(5)
        shutil.rmtree(cls.dados, ignore_errors=True)

    def req(self, metodo, caminho, corpo=None, chave=None, headers=None):
        h = dict(headers or {})
        if chave is not False:
            h["Authorization"] = "Bearer " + (chave or self.chave)
        rq = urllib.request.Request(self.url + caminho, data=corpo, method=metodo, headers=h)
        try:
            with urllib.request.urlopen(rq, timeout=10) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()


class Servidor(ServidorReal):
    def test_publico_sem_chave(self):
        st, body = self.req("GET", "/", chave=False)
        self.assertEqual(st, 200)
        self.assertIn(("irm http://127.0.0.1:%d/iniciar.ps1" % self.porta).encode(), body)
        st, body = self.req("GET", "/iniciar.sh", chave=False)
        self.assertIn(("SERVIDOR='http://127.0.0.1:%d'" % self.porta).encode(), body)

    def test_https_atras_do_tunel(self):
        st, body = self.req("GET", "/iniciar.ps1", chave=False, headers={"X-Forwarded-Proto": "https", "Host": "destrava.exemplo.com"})
        self.assertIn(b"$Servidor = 'https://destrava.exemplo.com'", body)
        st, _ = self.req("GET", "/iniciar.ps1", chave=False, headers={"Host": "x';Remove-Item C:\\"})
        self.assertEqual(st, 400, "Host esquisito não pode virar código dentro do script")

    def test_sem_chave_ou_chave_errada(self):
        self.assertEqual(self.req("GET", "/pacote/info", chave=False)[0], 401)
        self.assertEqual(self.req("GET", "/api/maquinas", chave="dtv_errada")[0], 401)
        self.assertEqual(self.req("GET", "/api/quem")[0], 200)

    def test_bloqueio_depois_de_muitas_tentativas(self):
        h = {"X-Forwarded-For": "203.0.113.9"}
        codes = [self.req("GET", "/api/quem", chave="dtv_x", headers=h)[0] for _ in range(11)]
        self.assertEqual(codes[-1], 429)
        self.assertEqual(self.req("GET", "/api/quem", headers={"X-Forwarded-For": "203.0.113.10"})[0], 200)

    def test_caminhos_invalidos(self):
        for caminho in ("/api/maquina/DD-AAAA-BBBB/..%2Fchaves.json", "/api/maquina/..%2F..%2Fx/meta.json", "/api/maquina/DD-AAAA-BBBB/x.py",
                        "/api/maquina/DD-AAAA-BBBB/.oculto.json"):
            self.assertEqual(self.req("PUT", caminho, b"{}")[0], 400, caminho)
        self.assertEqual(self.req("PUT", "/api/maquina/DD-AAAA-BBBB/meta.json", b"nao e json")[0], 400)
        self.assertEqual(self.req("PUT", "/api/maquina/DD-AAAA-BBBB/meta.json", b'{"ok":1}')[0], 200)
        self.assertTrue(os.path.isfile(os.path.join(self.dados, "maquinas", "DD-AAAA-BBBB", "meta.json")))

    def test_registro_encadeado_e_numero_de_os(self):
        regs = []
        for _ in range(2):
            st, body = self.req("POST", "/api/log", json.dumps({"evento": "os_registrada", "mid": "DD-OS00-TEST", "os": termo.OS_AUTO, "quando": "2001-01-01 00:00:00"}).encode())
            self.assertEqual(st, 200)
            regs.append(json.loads(body))
        self.assertNotEqual(regs[0]["os"], regs[1]["os"])
        self.assertEqual(regs[0]["tecnico_servidor"], "Técnico Teste")
        self.assertEqual(regs[0]["quando_pc"], "2001-01-01 00:00:00")
        self.assertNotEqual(regs[0]["quando"], "2001-01-01 00:00:00", "a hora que vale é a do servidor")
        st, body = self.req("GET", "/api/log/verificar")
        self.assertTrue(json.loads(body)["ok"])
        st, body = self.req("POST", "/api/log", json.dumps({"evento": "x", "mid": "../../etc"}).encode())
        self.assertEqual(st, 400)

    def test_pacote_so_leva_programa(self):
        st, body = self.req("GET", "/pacote/info")
        info = json.loads(body)
        st, z = self.req("GET", "/pacote/Destrava.zip")
        import hashlib
        import io
        import zipfile
        self.assertEqual(hashlib.sha256(z).hexdigest(), info["sha256"])
        nomes = zipfile.ZipFile(io.BytesIO(z)).namelist()
        self.assertIn("Destrava/dd_backup.py", nomes)
        self.assertIn("Destrava/conexao.py", nomes)
        self.assertIn("Destrava/web/app.html", nomes)
        for n in nomes:
            self.assertFalse(re.match(r"Destrava/(servidor|tests|maquinas|runtimes?|_dev|_cache_servidor|servidor-dados|servidor_web)\b", n), n)
            self.assertNotIn("consentimentos", n)
        # o mesmo zip serve de atualização para quem usa pendrive
        import atualizador
        p = os.path.join(self.dados, "Destrava.zip")
        with open(p, "wb") as fh:
            fh.write(z)
        self.assertEqual(atualizador.inspecionar(p)[1], info["versao"])


class ProgramaEmModoServidor(ServidorReal):
    """O programa local falando com o servidor: nada fica no computador, tudo chega lá."""

    def setUp(self):
        self.cache = tempfile.mkdtemp(prefix="destrava_cache_")
        self._store, self._log = ficha.STORE, termo.LOG
        ficha.STORE = os.path.join(self.cache, "maquinas")
        termo.LOG = os.path.join(self.cache, "consentimentos.log")
        self.con = conexao.Conexao(self.url, self.chave, "teste")
        self.con.testar()
        ficha.SINCRONIA, termo.REMOTO, termo.MODO = self.con, self.con, "servidor"
        ficha.carregar_coleta(WIN10_HD)

    def tearDown(self):
        ficha.SINCRONIA, termo.REMOTO, termo.MODO = None, None, "pendrive"
        ficha.STORE, termo.LOG = self._store, self._log
        ficha.REPLAY.clear()
        ficha._MID.clear()
        ficha._PUXADAS.clear()
        shutil.rmtree(self.cache, ignore_errors=True)

    def test_atendimento_completo(self):
        self.assertEqual(self.con.tecnico, "Técnico Teste")
        mid = ficha.machine_id_cache()
        r = termo.aceitar(mid, "Técnico Teste", "terceiros", "Padaria Pão Quente")
        self.assertTrue(r["status"]["aceito"])
        self.assertFalse(os.path.exists(termo.LOG), "o registro não pode ficar no computador atendido")
        o = termo.registrar_os(mid, "Maria da Padaria", ["ficha", "melhorias"])
        self.assertRegex(o["os"]["os"], r"^OS-\d{8}-\d{2}$")
        termo.exigir(mid, "melhorias")
        f = ficha.coletar()
        ficha.salvar_ficha(f)
        no_srv = os.path.join(self.dados, "maquinas", mid)
        arqs = os.listdir(no_srv)
        self.assertIn("historico.json", arqs)
        self.assertIn("meta.json", arqs)
        self.assertTrue(any(a.startswith("ficha-") for a in arqs))
        self.assertTrue(any(a.startswith("termo-") and a.endswith(".html") for a in arqs))
        self.assertTrue(any(a.startswith("os-") for a in arqs))
        lst = ficha.listar_maquinas()
        self.assertEqual([m["mid"] for m in lst if m["atual"]], [mid])
        # outro computador (cache vazio) enxerga a mesma máquina e o mesmo histórico
        shutil.rmtree(self.cache)
        ficha._PUXADAS.clear()
        self.assertGreaterEqual(len(ficha.hist_get(mid)), 3)
        self.assertTrue(termo.status(mid)["aceito"])

    def test_sem_rede_fica_pendente(self):
        mid = ficha.machine_id_cache()
        termo.aceitar(mid, "Técnico Teste", "terceiros", "Padaria Pão Quente")
        self.con.url = "http://127.0.0.1:%d" % porta_livre()  # servidor "caiu"
        ficha.hist_add(mid, "nota", "anotado sem rede")
        self.assertEqual(self.con.estado()["pendentes"], 1)
        self.assertTrue(termo.status(mid)["aceito"], "sem rede, vale a última leitura do registro")
        self.con.url = self.url  # voltou
        self.assertEqual(self.con.enviar_pendentes(), 0)
        with open(os.path.join(self.dados, "maquinas", mid, "historico.json"), encoding="utf-8") as fh:
            self.assertIn("anotado sem rede", fh.read())


class CodigoDaMaquina(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="destrava_mid_")
        self._store = ficha.STORE
        ficha.STORE = self.tmp

    def tearDown(self):
        ficha.STORE = self._store
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_adaptador_usb_nao_junta_clientes(self):
        usb = "00:e0:4c:68:00:01"
        a = ficha.resolver_mid({"uuid": "UUID-CLIENTE-A-0001", "serial": "", "macs": [usb]})
        ficha.meta_ids(a, {"uuid": "UUID-CLIENTE-A-0001", "serial": "", "macs": [usb]})
        b = ficha.resolver_mid({"uuid": "UUID-CLIENTE-B-0002", "serial": "", "macs": [usb]})
        self.assertNotEqual(a, b)

    def test_sem_uuid_o_mac_ainda_reconhece(self):
        m = "a4:4c:c8:11:22:33"
        a = ficha.resolver_mid({"uuid": "", "serial": "", "macs": [m]}, "PC", "CPU")
        ficha.meta_ids(a, {"uuid": "", "serial": "", "macs": [m, "a4:4c:c8:99:99:99"]})
        self.assertEqual(ficha.resolver_mid({"uuid": "", "serial": "", "macs": ["a4:4c:c8:99:99:99"]}, "PC-NOVO", "CPU"), a)


if __name__ == "__main__":
    unittest.main()
