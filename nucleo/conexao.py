# -*- coding: utf-8 -*-
"""Destrava! - conexão com o servidor da loja (modo servidor). Só biblioteca padrão.

O programa continua rodando NESTE computador (precisa ler hardware e discos); o servidor guarda as fichas,
os históricos e o registro de consentimentos. Gravações que falham por falta de rede ficam numa fila e são
reenviadas sozinhas; a tela mostra quantas estão pendentes.
"""
import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request


class SemConexao(Exception):
    pass


class ErroServidor(Exception):
    def __init__(self, msg, status=0):
        Exception.__init__(self, msg)
        self.status = status


class Conexao(object):
    def __init__(self, url, chave, versao=""):
        url = (url or "").strip().rstrip("/")
        if not re.match(r"^https?://[^/\s]+(/[^\s]*)?$", url):
            raise ValueError("Endereço do servidor inválido: %s" % url)
        self.url = url
        self._chave = chave
        self.versao = versao
        self.tecnico = ""
        self.pendentes = {}  # (mid, nome) -> caminho local; o arquivo é lido de novo a cada tentativa
        self._log_cache = {}  # mid -> linhas do registro lidas por último
        self._lock = threading.Lock()
        self._fio = None

    # ------------------------------------------------------------------ HTTP
    def _req(self, metodo, caminho, corpo=None, tipo="application/json", timeout=30):
        h = {"Authorization": "Bearer " + self._chave, "User-Agent": "Destrava/%s" % self.versao}
        if corpo is not None:
            h["Content-Type"] = tipo
        rq = urllib.request.Request(self.url + caminho, data=corpo, method=metodo, headers=h)
        try:
            with urllib.request.urlopen(rq, timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            try:
                msg = json.loads(e.read().decode("utf-8")).get("erro") or ""
            except Exception:
                msg = ""
            if e.code >= 500:
                raise SemConexao(msg or "O servidor respondeu com erro %d." % e.code)
            raise ErroServidor(msg or "O servidor recusou o pedido (%d)." % e.code, e.code)
        except (urllib.error.URLError, OSError) as e:
            raise SemConexao("Sem conexão com o servidor (%s)." % getattr(e, "reason", e))

    def _json(self, metodo, caminho, obj=None, timeout=30):
        corpo = None if obj is None else json.dumps(obj, ensure_ascii=False).encode("utf-8")
        return json.loads(self._req(metodo, caminho, corpo, timeout=timeout).decode("utf-8") or "null")

    # ------------------------------------------------------------------ entrada
    def testar(self):
        """Confere chave e conexão; guarda o nome do técnico dono da chave."""
        r = self._json("GET", "/api/quem")
        self.tecnico = r.get("tecnico", "")
        return r

    def resolver(self, ids, host, cpu):
        return self._json("POST", "/api/resolver", {"ids": ids, "host": host, "cpu": cpu})["mid"]

    # ------------------------------------------------------------------ máquinas
    def indice(self):
        return self._json("GET", "/api/maquinas")["maquinas"]

    def baixar_maquina(self, mid, pasta_local):
        r = self._json("GET", "/api/maquina/" + urllib.parse.quote(mid, safe=""))
        arqs = r.get("arquivos") or {}
        if not arqs:
            return 0
        os.makedirs(pasta_local, exist_ok=True)
        for nome, txt in arqs.items():
            nome = os.path.basename(nome)
            if (mid, nome) in self.pendentes:
                continue  # a versão local ainda não enviada é a mais nova
            with open(os.path.join(pasta_local, nome), "w", encoding="utf-8") as fh:
                fh.write(txt)
        return len(arqs)

    def enviar(self, mid, nome, caminho):
        with self._lock:
            self.pendentes[(mid, nome)] = caminho
        self._enviar_um(mid, nome)
        if self.pendentes:
            self._reenviar_depois()

    def _enviar_um(self, mid, nome):
        with self._lock:
            caminho = self.pendentes.get((mid, nome))
        if not caminho:
            return True
        try:
            with open(caminho, "rb") as fh:
                dados = fh.read()
        except OSError:
            with self._lock:
                self.pendentes.pop((mid, nome), None)  # o arquivo local sumiu (ex.: máquina apagada)
            return True
        try:
            self._req("PUT", "/api/maquina/%s/%s" % (urllib.parse.quote(mid, safe=""), urllib.parse.quote(nome, safe="")), dados, "application/octet-stream")
        except SemConexao:
            return False
        except ErroServidor:
            pass  # recusado de vez (nome inválido, grande demais): não adianta repetir
        with self._lock:
            if self.pendentes.get((mid, nome)) == caminho:
                self.pendentes.pop((mid, nome), None)
        return True

    def _reenviar_depois(self):
        with self._lock:
            if self._fio and self._fio.is_alive():
                return

            def laco():
                while self.pendentes:
                    time.sleep(15)
                    for mid, nome in list(self.pendentes):
                        if not self._enviar_um(mid, nome):
                            break
            self._fio = threading.Thread(target=laco, daemon=True)
            self._fio.start()

    def enviar_pendentes(self):
        """Uma tentativa já (ao encerrar). Devolve quantas continuam pendentes."""
        for mid, nome in list(self.pendentes):
            if not self._enviar_um(mid, nome):
                break
        return len(self.pendentes)

    def apagar(self, mid):
        with self._lock:
            for k in [k for k in self.pendentes if k[0] == mid]:
                self.pendentes.pop(k, None)
        self._json("DELETE", "/api/maquina/" + urllib.parse.quote(mid, safe=""))

    # ------------------------------------------------------------------ registro de consentimentos
    def log_add(self, reg):
        """Aceitar termo e registrar OS exigem conexão: a prova fica no servidor, com a hora dele."""
        r = self._json("POST", "/api/log", reg)
        if r.get("mid") in self._log_cache:
            self._log_cache[r["mid"]].append(r)
        return r

    def log_ler(self, mid=None):
        """Sem rede, devolve a última leitura desta máquina: o atendimento continua com o que já foi autorizado."""
        try:
            linhas = self._json("GET", "/api/log" + ("?mid=" + urllib.parse.quote(mid) if mid else ""))["linhas"]
        except SemConexao:
            if mid in self._log_cache:
                return list(self._log_cache[mid])
            raise
        if mid:
            self._log_cache[mid] = list(linhas)
        return linhas

    def log_verificar(self):
        return self._json("GET", "/api/log/verificar")

    def estado(self):
        return {"url": self.url, "tecnico": self.tecnico, "pendentes": len(self.pendentes)}
