# -*- coding: utf-8 -*-
"""Destrava! - o Mapa do backup dentro do programa, como gestão de arquivos.

Navega como era na máquina (pastas originais), mostra o que ficou para trás e por quê, abre ou mostra os
arquivos DO BACKUP (caminho conferido dentro da pasta do backup) e confere a integridade relendo do disco.
A tela só manda o número da linha do Mapa, nunca um caminho.
"""
import json
import os
import re
import threading

import disco

S_, D_, C_, Z_, T_, ST_, G_, U_, M_, H_ = range(10)  # campos de cada linha (meta.campos)
M = {"raiz": "", "mapa": "", "meta": {}, "f": [], "partes": [], "cert": {}}
CONF = {"rodando": False, "feitos": 0, "total": 0, "ok": 0, "diferentes": [], "faltando": [], "fim": False, "erro": ""}
LOCK = threading.Lock()
CANCEL = threading.Event()
_CRED = {".kdbx", ".kdb", ".pfx", ".p12", ".pem", ".key", ".gpg", ".ppk"}


def achar_mapa(pasta):
    """Pasta Mapa (com dados.js) a partir da pasta do backup, da própria pasta Mapa ou de um arquivo dela."""
    p = os.path.abspath(os.path.expanduser(pasta or ""))
    for c in (p, os.path.join(p, "Mapa"), os.path.dirname(p)):
        if os.path.isfile(os.path.join(c, "dados.js")):
            return c
    raise ValueError("Não achei o Mapa (pasta Mapa com dados.js) em %s." % p)


def carregar(pasta):
    mp = achar_mapa(pasta)
    with open(os.path.join(mp, "dados.js"), encoding="utf-8") as fh:
        txt = fh.read().strip()
    if not txt.startswith("window.BKP="):
        raise ValueError("O dados.js deste Mapa não é do Destrava!.")
    d = json.loads(txt[len("window.BKP="):].rstrip(";"))
    cert = {}
    try:
        with open(os.path.join(mp, "certificado.json"), encoding="utf-8") as fh:
            cert = json.load(fh)
    except (OSError, ValueError):
        pass
    meta = d.get("meta") or {}
    f = d.get("f") or []
    CANCEL.set()
    with LOCK:
        M.update(raiz=os.path.dirname(mp) if meta.get("dstRel", True) else (meta.get("raiz") or os.path.dirname(mp)), mapa=mp, meta=meta, f=f,
                 partes=[[p for p in re.split(r"[\\/]", str(e[S_])) if p] for e in f], cert=cert)
        CONF.update(rodando=False, feitos=0, total=0, ok=0, diferentes=[], faltando=[], fim=False, erro="")
    return resumo()


def _exige():
    if not M["mapa"]:
        raise ValueError("Abra um Mapa primeiro.")


def resumo():
    _exige()
    c = {"ok": 0, "falha": 0, "fora": 0, "bytes": 0}
    cats = {}
    for e in M["f"]:
        st = e[ST_]
        if st == "ok":
            c["ok"] += 1
            c["bytes"] += e[Z_] or 0
        elif st == "falha":
            c["falha"] += 1
        else:
            c["fora"] += 1
        cats[e[C_]] = cats.get(e[C_], 0) + 1
    ce = M["meta"].get("cert") or {}
    return {"raiz": M["raiz"], "mapa": M["mapa"], "codigo": M["cert"].get("codigo") or ce.get("codigo", ""), "cert": ce, "pc": M["meta"].get("pc", ""),
            "data": M["meta"].get("data", ""), "verificacao": M["meta"].get("verificacao", ""), "contagem": c, "categorias": cats,
            "usuarios": sorted({str(e[U_]) for e in M["f"] if e[U_]}), "raiz_existe": os.path.isdir(M["raiz"])}


def _destino(e):
    return os.path.join(M["raiz"], *str(e[D_]).split("/")) if e[D_] else ""


def _linha(i, e):
    nome = (M["partes"][i] or ["?"])[-1]
    ext = os.path.splitext(nome.lower())[1]
    no_backup = e[ST_] == "ok" and bool(e[D_]) and os.path.isfile(_destino(e))
    import dados
    t = dados.PREVIA.get(ext)
    cred = ext in _CRED or e[C_] == "Contas_Senhas"
    return {"i": i, "nome": nome, "origem": e[S_], "destino": e[D_], "cat": e[C_], "bytes": e[Z_], "data": e[T_], "situacao": e[ST_], "etiquetas": e[G_],
            "usuario": e[U_], "motivo": e[M_], "no_backup": no_backup, "previa": t[0] if (t and no_backup and not cred) else None,
            "pode_abrir": no_backup and not cred and ext not in dados.SEM_ABRIR}


def arvore(pasta="", limite=2000):
    """Como era na máquina: subpastas (com totais) e arquivos de uma pasta original."""
    _exige()
    pre = [p for p in (pasta or "").split("/") if p]
    n = len(pre)
    pastas, arqs = {}, []
    for i, ps in enumerate(M["partes"]):
        if len(ps) <= n or ps[:n] != pre:
            continue
        e = M["f"][i]
        if len(ps) == n + 1:
            arqs.append(_linha(i, e))
            continue
        a = pastas.setdefault(ps[n], {"nome": ps[n], "n": 0, "bytes": 0, "ok": 0, "falha": 0, "fora": 0})
        a["n"] += 1
        a["bytes"] += e[Z_] or 0
        a["ok" if e[ST_] == "ok" else "falha" if e[ST_] == "falha" else "fora"] += 1
    arqs.sort(key=lambda x: x["nome"].lower())
    return {"pasta": "/".join(pre), "migalhas": pre, "pastas": sorted(pastas.values(), key=lambda a: -a["bytes"]), "arquivos": arqs[:limite], "total_arquivos": len(arqs)}


def buscar(q="", situacao="", cat="", usuario="", offset=0, limite=300):
    """Busca por nome, pasta, etiqueta ou motivo. situacao 'fora' = tudo que não foi copiado (ignorado, revisar, desmarcado)."""
    _exige()
    q = (q or "").lower().strip()
    out = []
    total = 0
    for i, e in enumerate(M["f"]):
        st = e[ST_]
        if situacao == "fora" and st in ("ok", "falha"):
            continue
        if situacao and situacao != "fora" and st != situacao:
            continue
        if (cat and e[C_] != cat) or (usuario and e[U_] != usuario):
            continue
        if q and q not in ("%s %s %s %s" % (e[S_], e[D_], e[G_], e[M_])).lower():
            continue
        if offset <= total < offset + limite:
            out.append(_linha(i, e))
        total += 1
    return {"linhas": out, "total": total}


def caminho(i):
    """Arquivo no backup, conferido: copiado, existe e está DENTRO da pasta do backup."""
    _exige()
    try:
        e = M["f"][int(i)]
    except (ValueError, TypeError, IndexError):
        raise ValueError("Linha do Mapa inválida.")
    if e[ST_] != "ok" or not e[D_]:
        raise ValueError("Este arquivo não foi copiado: %s" % (e[M_] or e[ST_]))
    p = _destino(e)
    raiz = os.path.realpath(M["raiz"])
    if not os.path.realpath(p).startswith(raiz.rstrip(os.sep) + os.sep):
        raise ValueError("Caminho fora da pasta do backup.")
    if not os.path.isfile(p):
        raise ValueError("Não está no backup (o disco do backup está conectado?): %s" % p)
    return p


def previa(i):
    p = caminho(i)
    linha = _linha(int(i), M["f"][int(i)])
    if not linha["previa"]:
        raise ValueError("Sem prévia para este arquivo: use Abrir ou Mostrar na pasta.")
    import dados
    t = dados.PREVIA[os.path.splitext(p.lower())[1]]
    return p, t[1], t[0], (200 * 1024 if t[0] == "texto" else None)


def conferir():
    """Relê do disco cada arquivo copiado e compara o SHA-256 com o do Mapa (em segundo plano)."""
    _exige()
    with LOCK:
        if CONF["rodando"]:
            raise ValueError("A conferência já está rodando.")
        alvos = [(i, e) for i, e in enumerate(M["f"]) if e[ST_] == "ok" and e[D_] and e[H_]]
        CONF.update(rodando=True, feitos=0, total=len(alvos), ok=0, diferentes=[], faltando=[], fim=False, erro="", metodo=disco.METODO)
    CANCEL.clear()

    def work():
        try:
            for i, e in alvos:
                if CANCEL.is_set():
                    break
                p = _destino(e)
                if not os.path.isfile(p):
                    CONF["faltando"].append(e[S_])
                elif disco.sha256(p) != e[H_]:
                    CONF["diferentes"].append(e[S_])
                else:
                    CONF["ok"] += 1
                CONF["feitos"] += 1
        except Exception as ex:
            CONF["erro"] = str(ex)
        finally:
            CONF["rodando"] = False
            CONF["fim"] = not CANCEL.is_set()
    threading.Thread(target=work, daemon=True).start()
    return estado_conferencia()


def estado_conferencia():
    d = {k: (v[:200] if isinstance(v, list) else v) for k, v in CONF.items()}
    d["n_diferentes"], d["n_faltando"] = len(CONF["diferentes"]), len(CONF["faltando"])
    return d
