#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Destrava! - servidor da loja. Só biblioteca padrão do Python.

Entrega o programa (e um Python fixo) para rodar em qualquer computador SEM pendrive e guarda as fichas,
os históricos e o registro de consentimentos de todas as máquinas atendidas. O programa continua rodando
no computador atendido (precisa ler hardware e discos); só o pacote e os dados passam pelo servidor.

    python3 servidor.py --nova-chave "Nome do técnico"    cria uma chave de acesso (mostrada uma única vez)
    python3 servidor.py --listar-chaves                   lista os técnicos com chave
    python3 servidor.py --revogar "Nome do técnico"       apaga a chave desse técnico
    python3 servidor.py [--host 0.0.0.0] [--porta 8080]    sobe o servidor
"""
import argparse
import datetime
import hashlib
import io
import json
import os
import re
import secrets
import shutil
import sys
import threading
import time
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
from nucleo import atualizador, ficha, termo  # noqa: E402

DADOS = os.path.abspath(os.environ.get("DESTRAVA_SERVIDOR_DADOS") or os.path.join(HERE, "servidor-dados"))
RUNTIMES = os.path.join(HERE, "runtimes")
MODELOS = os.path.join(HERE, "servidor_web")
MID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
ARQ_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,119}\.(json|html)$")
EVENTO_RE = re.compile(r"^[a-z_]{1,40}$")
HOST_RE = re.compile(r"^[A-Za-z0-9.-]{1,253}(:\d{1,5})?$")
MAX_ARQ = 10 * 1024 * 1024
MAX_JSON = 256 * 1024
SO_SERVIDOR = {"servidor.py", "baixar_runtimes.py"}  # ficam fora do pacote entregue aos computadores
LOCK = threading.Lock()


def _agora():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def store():
    return os.path.join(DADOS, "maquinas")


def caminho_log():
    return os.path.join(DADOS, "consentimentos.log")


def preparar():
    os.makedirs(store(), exist_ok=True)
    ficha.STORE = store()
    termo.LOG = caminho_log()


# ----------------------------------------------------------------------------------------------
# chaves dos técnicos (só o hash fica no disco)
# ----------------------------------------------------------------------------------------------
def _arq_chaves():
    return os.path.join(DADOS, "chaves.json")


def ler_chaves():
    try:
        with open(_arq_chaves(), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return []


def _gravar_chaves(lst):
    os.makedirs(DADOS, exist_ok=True)
    tmp = _arq_chaves() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(lst, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, _arq_chaves())
    try:
        os.chmod(_arq_chaves(), 0o600)
    except OSError:
        pass


def _hash_chave(sal, chave):
    return hashlib.sha256((sal + chave).encode("utf-8")).hexdigest()


def nova_chave(nome):
    nome = (nome or "").strip()
    if len(nome) < 2:
        raise ValueError("Informe o nome do técnico.")
    lst = [c for c in ler_chaves() if c.get("nome") != nome]
    chave = "dtv_" + secrets.token_urlsafe(24)
    sal = secrets.token_hex(8)
    lst.append({"nome": nome, "sal": sal, "hash": _hash_chave(sal, chave), "criada": _agora()})
    _gravar_chaves(lst)
    return chave


def revogar(nome):
    lst = ler_chaves()
    novo = [c for c in lst if c.get("nome") != nome]
    _gravar_chaves(novo)
    return len(lst) - len(novo)


def autenticar(chave):
    """Nome do técnico dono da chave, ou None. Compara todas as chaves em tempo constante."""
    if not chave or len(chave) > 200:
        return None
    achou = None
    for c in ler_chaves():
        if secrets.compare_digest(_hash_chave(c.get("sal", ""), chave), c.get("hash", "")):
            achou = c.get("nome")
    return achou


FALHAS = {}  # ip -> [tentativas erradas, desde]
JANELA, LIMITE = 600, 10


def bloqueado(ip):
    f = FALHAS.get(ip)
    if not f:
        return False
    if time.time() - f[1] > JANELA:
        FALHAS.pop(ip, None)
        return False
    return f[0] >= LIMITE


def registrar_falha(ip):
    f = FALHAS.get(ip)
    if not f or time.time() - f[1] > JANELA:
        FALHAS[ip] = [1, time.time()]
    else:
        f[0] += 1


# ----------------------------------------------------------------------------------------------
# pacote do programa (montado a partir dos arquivos desta pasta; nunca leva dados)
# ----------------------------------------------------------------------------------------------
_PACOTE = {"assinatura": None, "zip": b"", "sha256": "", "versao": ""}


def arquivos_pacote():
    """Só arquivos de programa: os da raiz (exceto os do servidor) e a pasta web/. Lista fechada de propósito:
    servidor-dados/, maquinas/, runtimes/ e tests/ moram nesta mesma pasta e não podem ir junto."""
    out = []
    for n in sorted(os.listdir(HERE)):
        if os.path.isfile(os.path.join(HERE, n)) and n not in SO_SERVIDOR and atualizador._is_code(n):
            out.append(n)
    for n in sorted(os.listdir(os.path.join(HERE, "nucleo"))):
        if os.path.isfile(os.path.join(HERE, "nucleo", n)) and n not in SO_SERVIDOR | {"__init__.py"} and atualizador._is_code(n):
            out.append("nucleo/" + n)
    for dp, dns, fns in os.walk(os.path.join(HERE, "nucleo", "web")):
        dns[:] = sorted(d for d in dns if d != "__pycache__")
        for fn in sorted(fns):
            rel = os.path.relpath(os.path.join(dp, fn), HERE).replace("\\", "/")
            if atualizador._is_code(rel):
                out.append(rel)
    return out


def versao_programa():
    try:
        with open(os.path.join(HERE, "nucleo", "dd_backup.py"), encoding="utf-8") as fh:
            m = re.search(r'^VERSION\s*=\s*"([^"]+)"', fh.read(), re.M)
        return m.group(1) if m else "?"
    except OSError:
        return "?"


def pacote():
    """(zip, sha256, versao). Remonta sozinho quando algum arquivo do programa muda."""
    arqs = arquivos_pacote()
    ass = tuple((a, os.path.getmtime(os.path.join(HERE, a)), os.path.getsize(os.path.join(HERE, a))) for a in arqs)
    with LOCK:
        if _PACOTE["assinatura"] != ass:
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
                for a in arqs:
                    zi = zipfile.ZipInfo("Destrava/" + (a[len("nucleo/"):] if a.startswith("nucleo/") else a), date_time=(2020, 1, 1, 0, 0, 0))  # data fixa: mesmo conteúdo, mesmo hash
                    zi.compress_type = zipfile.ZIP_DEFLATED
                    zi.external_attr = (0o755 if a.endswith(".sh") else 0o644) << 16
                    with open(os.path.join(HERE, a), "rb") as fh:
                        z.writestr(zi, fh.read())
            data = buf.getvalue()
            _PACOTE.update(assinatura=ass, zip=data, sha256=hashlib.sha256(data).hexdigest(), versao=versao_programa())
        return _PACOTE["zip"], _PACOTE["sha256"], _PACOTE["versao"]


def runtimes():
    """Pythons fixos baixados por baixar_runtimes.py: {nome: {arquivo, sha256, python}} (só os que existem)."""
    try:
        with open(os.path.join(RUNTIMES, "runtimes.json"), encoding="utf-8") as fh:
            d = json.load(fh)
    except (OSError, ValueError):
        return {}
    return {k: v for k, v in d.items() if re.match(r"^[a-z0-9_-]+$", k) and os.path.isfile(os.path.join(RUNTIMES, os.path.basename(v.get("arquivo", ""))))}


# ----------------------------------------------------------------------------------------------
# máquinas e registro de consentimentos
# ----------------------------------------------------------------------------------------------
def pasta_maquina(mid):
    if not MID_RE.match(mid or ""):
        raise ValueError("Código de máquina inválido.")
    return os.path.join(store(), mid)


def arquivos_maquina(mid):
    d = pasta_maquina(mid)
    out = {}
    if os.path.isdir(d):
        for n in sorted(os.listdir(d)):
            if ARQ_RE.match(n) and os.path.isfile(os.path.join(d, n)):
                with open(os.path.join(d, n), encoding="utf-8", errors="replace") as fh:
                    out[n] = fh.read()
    return out


def gravar_arquivo(mid, nome, dados):
    if not ARQ_RE.match(nome or ""):
        raise ValueError("Nome de arquivo inválido.")
    if len(dados) > MAX_ARQ:
        raise ValueError("Arquivo grande demais.")
    if nome.endswith(".json"):
        try:
            json.loads(dados.decode("utf-8"))
        except ValueError:
            raise ValueError("JSON inválido.")
    d = pasta_maquina(mid)
    with LOCK:
        os.makedirs(d, exist_ok=True)
        tmp = os.path.join(d, "." + nome + ".tmp")
        with open(tmp, "wb") as fh:
            fh.write(dados)
        os.replace(tmp, os.path.join(d, nome))


def apagar_maquina(mid):
    d = pasta_maquina(mid)
    with LOCK:
        if os.path.isdir(d):
            shutil.rmtree(d)


def log_add(reg, tecnico):
    """Grava no registro do servidor: ele encadeia o hash, usa a HORA DELE e numera as OS (sem repetir entre técnicos)."""
    if not isinstance(reg, dict) or not EVENTO_RE.match(str(reg.get("evento", ""))) or not MID_RE.match(str(reg.get("mid", ""))):
        raise ValueError("Registro inválido.")
    reg = {k: v for k, v in reg.items() if k not in ("n", "prev", "hash", "tecnico_servidor", "quando_pc")}
    reg["quando_pc"] = str(reg.get("quando", ""))[:40]
    reg["quando"] = _agora()
    reg["tecnico_servidor"] = tecnico
    with LOCK:
        if reg["evento"] == "os_registrada" and reg.get("os") == termo.OS_AUTO:
            reg["os"] = termo.proximo_numero_os(termo.ler_linhas(caminho_log()))
        return termo.anexar_linha(caminho_log(), reg)


def log_ler(mid):
    if not MID_RE.match(mid or ""):
        raise ValueError("Informe a máquina.")
    return [r for r in termo.ler_linhas(caminho_log()) if r.get("mid") == mid]


def indice():
    with LOCK:
        return ficha.listar_maquinas(atual="")


def resolver(d):
    ids = d.get("ids") if isinstance(d.get("ids"), dict) else {}
    ids = {"uuid": str(ids.get("uuid") or "")[:100], "serial": str(ids.get("serial") or "")[:100],
           "macs": [str(m)[:17] for m in (ids.get("macs") or [])[:20] if isinstance(m, str)]}
    with LOCK:
        return ficha.resolver_local(ids, str(d.get("host") or "")[:100], str(d.get("cpu") or "")[:200])


# ----------------------------------------------------------------------------------------------
# HTTP
# ----------------------------------------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    server_version = "DestravaServidor"

    def log_message(self, fmt, *a):
        sys.stdout.write("%s %s %s\n" % (_agora(), self._ip(), fmt % a))
        sys.stdout.flush()

    def _ip(self):
        # atrás do túnel da Cloudflare o IP real vem neste cabeçalho
        return (self.headers.get("CF-Connecting-IP") or self.headers.get("X-Forwarded-For", "").split(",")[0].strip() or self.client_address[0])[:64]

    def _envia(self, code, data, tipo, extra=None):
        self.send_response(code)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def _json(self, obj, code=200):
        self._envia(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def _corpo(self, limite):
        n = int(self.headers.get("Content-Length") or 0)
        if n < 0 or n > limite:
            raise ValueError("Conteúdo grande demais.")
        return self.rfile.read(n) if n else b""

    def _publico(self):
        """Endereço que os computadores usam para chegar aqui (vai dentro dos scripts de início)."""
        fixo = os.environ.get("DESTRAVA_URL_PUBLICA", "").strip().rstrip("/")
        if fixo:
            return fixo
        host = self.headers.get("Host", "")
        if not HOST_RE.match(host):
            raise ValueError("Cabeçalho Host inválido.")
        https = self.headers.get("X-Forwarded-Proto", "").lower() == "https" or '"https"' in self.headers.get("CF-Visitor", "")
        proto = "https" if https else "http"
        return "%s://%s" % (proto, host)

    def _modelo(self, nome, tipo):
        with open(os.path.join(MODELOS, nome), encoding="utf-8") as fh:
            txt = fh.read().replace("__SERVIDOR__", self._publico())
        self._envia(200, txt.encode("utf-8"), tipo)

    def _tecnico(self):
        ip = self._ip()
        if bloqueado(ip):
            self._json({"erro": "Muitas tentativas com chave errada. Espere alguns minutos."}, 429)
            return None
        auth = self.headers.get("Authorization", "")
        nome = autenticar(auth[7:].strip() if auth.startswith("Bearer ") else "")
        if not nome:
            registrar_falha(ip)
            self._json({"erro": "Chave de técnico inválida."}, 401)
            return None
        return nome

    def _rota(self):
        u = urlparse(self.path)
        return u.path, parse_qs(u.query)

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        path, q = self._rota()
        try:
            if path == "/":
                return self._modelo("pagina.html", "text/html; charset=utf-8")
            if path == "/iniciar.ps1":
                return self._modelo("iniciar.ps1", "text/plain; charset=utf-8")
            if path == "/iniciar.sh":
                return self._modelo("iniciar.sh", "text/plain; charset=utf-8")
            tec = self._tecnico()
            if not tec:
                return
            if path == "/api/quem":
                return self._json({"tecnico": tec, "versao": pacote()[2]})
            if path == "/pacote/info":
                _, sha, ver = pacote()
                rts = runtimes()
                if (q.get("formato") or [""])[0] == "txt":  # para o iniciar.sh, que não tem leitor de JSON
                    linhas = ["versao=" + ver, "sha256=" + sha] + ["runtime_%s=%s" % (k, v.get("sha256", "")) for k, v in sorted(rts.items())]
                    return self._envia(200, ("\n".join(linhas) + "\n").encode("utf-8"), "text/plain; charset=utf-8")
                return self._json({"versao": ver, "sha256": sha, "runtimes": {k: {"sha256": v.get("sha256", ""), "python": v.get("python", "")} for k, v in rts.items()}})
            if path == "/pacote/Destrava.zip":
                return self._envia(200, pacote()[0], "application/zip", {"Content-Disposition": 'attachment; filename="Destrava.zip"'})
            if path.startswith("/runtime/"):
                return self._runtime(path[len("/runtime/"):])
            if path == "/api/maquinas":
                return self._json({"maquinas": indice()})
            if path.startswith("/api/maquina/"):
                return self._json({"arquivos": arquivos_maquina(unquote(path[len("/api/maquina/"):]))})
            if path == "/api/log":
                return self._json({"linhas": log_ler((q.get("mid") or [""])[0])})
            if path == "/api/log/verificar":
                return self._json(termo.verificar_linhas(termo.ler_linhas(caminho_log())))
            return self._json({"erro": "rota desconhecida"}, 404)
        except ValueError as e:
            return self._json({"erro": str(e)}, 400)
        except Exception as e:
            self.log_message("ERRO %s", e)
            return self._json({"erro": "Erro interno do servidor."}, 500)

    def _runtime(self, nome):
        rt = runtimes().get(nome)
        if not rt:
            return self._json({"erro": "Python para %s ainda não foi baixado no servidor (rode baixar_runtimes.py)." % nome}, 404)
        p = os.path.join(RUNTIMES, os.path.basename(rt["arquivo"]))
        tam = os.path.getsize(p)
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(tam))
        self.end_headers()
        if self.command == "HEAD":
            return
        with open(p, "rb") as fh:
            shutil.copyfileobj(fh, self.wfile, 1024 * 1024)

    def do_POST(self):
        path, _ = self._rota()
        try:
            tec = self._tecnico()
            if not tec:
                return
            corpo = json.loads(self._corpo(MAX_JSON).decode("utf-8") or "{}")
            if path == "/api/log":
                return self._json(log_add(corpo, tec))
            if path == "/api/resolver":
                return self._json({"mid": resolver(corpo if isinstance(corpo, dict) else {})})
            return self._json({"erro": "rota desconhecida"}, 404)
        except ValueError as e:
            return self._json({"erro": str(e)}, 400)
        except Exception as e:
            self.log_message("ERRO %s", e)
            return self._json({"erro": "Erro interno do servidor."}, 500)

    def do_PUT(self):
        path, _ = self._rota()
        try:
            tec = self._tecnico()
            if not tec:
                return
            partes = path.split("/")
            if len(partes) != 5 or partes[1:3] != ["api", "maquina"]:
                return self._json({"erro": "rota desconhecida"}, 404)
            gravar_arquivo(unquote(partes[3]), unquote(partes[4]), self._corpo(MAX_ARQ))
            return self._json({"ok": True})
        except ValueError as e:
            return self._json({"erro": str(e)}, 400)
        except Exception as e:
            self.log_message("ERRO %s", e)
            return self._json({"erro": "Erro interno do servidor."}, 500)

    def do_DELETE(self):
        path, _ = self._rota()
        try:
            tec = self._tecnico()
            if not tec:
                return
            if not path.startswith("/api/maquina/"):
                return self._json({"erro": "rota desconhecida"}, 404)
            apagar_maquina(unquote(path[len("/api/maquina/"):]))
            return self._json({"ok": True})
        except ValueError as e:
            return self._json({"erro": str(e)}, 400)
        except Exception as e:
            self.log_message("ERRO %s", e)
            return self._json({"erro": "Erro interno do servidor."}, 500)


def main():
    global DADOS
    ap = argparse.ArgumentParser(description="Destrava! - servidor da loja")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--porta", type=int, default=8080)
    ap.add_argument("--dados", metavar="PASTA", help="onde guardar máquinas, consentimentos e chaves (padrão: servidor-dados/)")
    ap.add_argument("--nova-chave", metavar="NOME")
    ap.add_argument("--listar-chaves", action="store_true")
    ap.add_argument("--revogar", metavar="NOME")
    a = ap.parse_args()
    if a.dados:
        DADOS = os.path.abspath(a.dados)
    if a.nova_chave:
        chave = nova_chave(a.nova_chave)
        print("Chave de %s (guarde agora, ela não é mostrada de novo):\n\n    %s\n" % (a.nova_chave.strip(), chave))
        return
    if a.listar_chaves:
        for c in ler_chaves():
            print("%-30s criada em %s" % (c.get("nome"), c.get("criada")))
        return
    if a.revogar:
        print("Chaves removidas: %d" % revogar(a.revogar))
        return
    preparar()
    if not ler_chaves():
        print("Atenção: nenhuma chave criada ainda. Crie com:  python3 servidor.py --nova-chave \"Seu nome\"")
    _, sha, ver = pacote()
    print("Destrava! servidor: programa %s (%s), %d Python(s) prontos, dados em %s" % (ver, sha[:12], len(runtimes()), DADOS), flush=True)
    srv = ThreadingHTTPServer((a.host, a.porta), Handler)
    srv.daemon_threads = True
    print("Ouvindo em http://%s:%d" % (a.host, a.porta), flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
