"""Máquinas (arquivos em servidor-dados/maquinas) e o registro de consentimentos encadeado por hash (R3).
TODO: o LOCK é por processo; para mais de um worker Gunicorn, trocar por lock de arquivo (fcntl.flock)."""
import json
import os
import re
import shutil
import threading
import time

from django.conf import settings

from nucleo import ficha, termo

MID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
ARQ_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,119}\.(json|html)$")
EVENTO_RE = re.compile(r"^[a-z_]{1,40}$")
MAX_ARQ = 10 * 1024 * 1024
MAX_JSON = 256 * 1024
LOCK = threading.Lock()


def store():
    return os.path.join(settings.DESTRAVA_SERVIDOR_DADOS, "maquinas")


def caminho_log():
    return os.path.join(settings.DESTRAVA_SERVIDOR_DADOS, "consentimentos.log")


def preparar():
    """O motor lê e grava por variáveis de módulo: apontá-las para os dados do servidor."""
    os.makedirs(store(), exist_ok=True)
    ficha.STORE = store()
    termo.LOG = caminho_log()


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
    reg["quando"] = time.strftime("%Y-%m-%d %H:%M:%S")
    reg["tecnico_servidor"] = tecnico
    with LOCK:
        if reg["evento"] == "os_registrada" and reg.get("os") == termo.OS_AUTO:
            reg["os"] = termo.proximo_numero_os(termo.ler_linhas(caminho_log()))
        return termo.anexar_linha(caminho_log(), reg)


def log_ler(mid):
    if not MID_RE.match(mid or ""):
        raise ValueError("Informe a máquina.")
    return [r for r in termo.ler_linhas(caminho_log()) if r.get("mid") == mid]


def log_verificar():
    return termo.verificar_linhas(termo.ler_linhas(caminho_log()))


def indice():
    with LOCK:
        return ficha.listar_maquinas(atual="")


def resolver(d):
    ids = d.get("ids") if isinstance(d.get("ids"), dict) else {}
    ids = {"uuid": str(ids.get("uuid") or "")[:100], "serial": str(ids.get("serial") or "")[:100],
           "macs": [str(m)[:17] for m in (ids.get("macs") or [])[:20] if isinstance(m, str)]}
    with LOCK:
        return ficha.resolver_local(ids, str(d.get("host") or "")[:100], str(d.get("cpu") or "")[:200])
