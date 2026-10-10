"""Chaves dos técnicos (só o hash fica no disco) e bloqueio de IP por tentativas erradas. Mesmo formato de antes."""
import hashlib
import json
import os
import secrets
import time

from django.conf import settings


def _agora():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _arq():
    return os.path.join(settings.DESTRAVA_SERVIDOR_DADOS, "chaves.json")


def ler_chaves():
    try:
        with open(_arq(), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return []


def _gravar(lst):
    os.makedirs(settings.DESTRAVA_SERVIDOR_DADOS, exist_ok=True)
    tmp = _arq() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(lst, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, _arq())
    try:
        os.chmod(_arq(), 0o600)
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
    _gravar(lst)
    return chave


def revogar(nome):
    lst = ler_chaves()
    novo = [c for c in lst if c.get("nome") != nome]
    _gravar(novo)
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


FALHAS = {}  # ip -> [tentativas erradas, desde]  (1 worker: vale para o servidor inteiro)
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


def ip_do_pedido(request):
    """Atrás do túnel da Cloudflare o IP real vem em CF-Connecting-IP; senão X-Forwarded-For; senão o da conexão."""
    m = request.META
    return (m.get("HTTP_CF_CONNECTING_IP") or m.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip() or m.get("REMOTE_ADDR", ""))[:64]
