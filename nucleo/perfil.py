"""Perfil do técnico: quem atende. Fica em perfil.json na pasta de dados (fora do git), nunca sai da máquina.

O certificado leva uma CÓPIA só dos campos que o técnico marcou: mudar o perfil depois não altera certificados antigos."""
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
PASTA = HERE  # dd_backup --dados troca este caminho

CAMPOS = [
    ("nome", "Nome"), ("empresa", "Empresa"), ("email", "E-mail"), ("telefone", "Telefone / WhatsApp"),
    ("instagram", "Instagram"), ("site", "Site"), ("facebook", "Facebook"), ("linkedin", "LinkedIn"), ("outro", "Outra rede"),
]
NOMES = [c for c, _ in CAMPOS]
PADRAO = {"empresa": "D&D Technology", "no_certificado": ["nome", "empresa"]}
MAX = 120
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
TEL_RE = re.compile(r"^\+?[\d\s().-]+$")


def caminho():
    return os.path.join(PASTA, "perfil.json")


def ler():
    p = {c: "" for c in NOMES}
    p.update(empresa=PADRAO["empresa"], no_certificado=list(PADRAO["no_certificado"]))
    try:
        with open(caminho(), encoding="utf-8") as fh:
            d = json.load(fh)
    except (OSError, ValueError):
        return dict(p, preenchido=False)
    for c in NOMES:
        if isinstance(d.get(c), str):
            p[c] = d[c]
    if isinstance(d.get("no_certificado"), list):
        p["no_certificado"] = [c for c in d["no_certificado"] if c in NOMES]
    return dict(p, preenchido=bool(p["nome"].strip()))


def validar(d):
    """Devolve o perfil limpo ou levanta ValueError com a mensagem para a tela. Redes sociais nunca bloqueiam."""
    p = {}
    for c, rotulo in CAMPOS:
        v = d.get(c, "")
        if not isinstance(v, str):
            raise ValueError("%s inválido." % rotulo)
        v = " ".join(v.split())
        if len(v) > MAX:
            raise ValueError("%s muito longo (máximo %d letras)." % (rotulo, MAX))
        p[c] = v
    if p["email"] and not EMAIL_RE.match(p["email"]):
        raise ValueError("E-mail inválido. Exemplo: nome@empresa.com.br")
    if p["telefone"]:
        dig = re.sub(r"\D", "", p["telefone"])
        if not TEL_RE.match(p["telefone"]) or not 10 <= len(dig) <= 13:
            raise ValueError("Telefone inválido. Use DDD + número, ex.: (27) 99999-0000")
    marc = d.get("no_certificado", [])
    if not isinstance(marc, list):
        raise ValueError("Lista do certificado inválida.")
    p["no_certificado"] = [c for c in NOMES if c in marc]
    return p


def salvar(d):
    p = validar(d)
    os.makedirs(PASTA, exist_ok=True)
    tmp = caminho() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(p, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, caminho())
    return ler()


def snapshot():
    """Cópia do que vai no certificado (só os campos marcados e preenchidos). Vazio se não houver perfil com nome."""
    p = ler()
    if not p["preenchido"]:
        return {}
    return {c: p[c] for c in NOMES if c in p["no_certificado"] and p[c]}
