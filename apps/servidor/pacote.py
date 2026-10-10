"""O Destrava.zip entregue aos computadores (R4): só arquivos do agente, mesma forma de sempre, SHA-256 estável.

Lista FECHADA: os arquivos de nucleo/ (sem __init__.py e sem o que é só do servidor) vão para a raiz do zip
("nucleo/dd_backup.py" → "Destrava/dd_backup.py"), mais nucleo/web/ e os lançadores/LEIA-ME da raiz do projeto.
Nada de Django, chaves ou dados de cliente: tests/test_pacote.py cobre isso."""
import hashlib
import io
import json
import os
import re
import threading
import zipfile

from django.conf import settings

from nucleo import atualizador

SO_SERVIDOR = {"__init__.py", "baixar_runtimes.py"}
DA_RAIZ = ("Iniciar-Linux.sh", "Iniciar-Windows.bat", "Testar-Windows.bat", "testar-local.sh", "LEIA-ME.txt")
_PACOTE = {"assinatura": None, "zip": b"", "sha256": "", "versao": ""}
_LOCK = threading.Lock()


def arquivos_pacote():
    """[(caminho no disco, nome dentro de Destrava/)]"""
    nuc = str(settings.DESTRAVA_NUCLEO)
    raiz = str(settings.BASE_DIR)
    out = []
    for n in sorted(os.listdir(nuc)):
        if os.path.isfile(os.path.join(nuc, n)) and n not in SO_SERVIDOR and atualizador._is_code(n):
            out.append((os.path.join(nuc, n), n))
    for dp, dns, fns in os.walk(os.path.join(nuc, "web")):
        dns[:] = sorted(d for d in dns if d != "__pycache__")
        for fn in sorted(fns):
            rel = os.path.relpath(os.path.join(dp, fn), nuc).replace("\\", "/")
            if atualizador._is_code(rel):
                out.append((os.path.join(dp, fn), rel))
    for n in DA_RAIZ:
        if os.path.isfile(os.path.join(raiz, n)):
            out.append((os.path.join(raiz, n), n))
    return out


def versao_programa():
    try:
        with open(os.path.join(settings.DESTRAVA_NUCLEO, "dd_backup.py"), encoding="utf-8") as fh:
            m = re.search(r'^VERSION\s*=\s*"([^"]+)"', fh.read(), re.M)
        return m.group(1) if m else "?"
    except OSError:
        return "?"


def pacote():
    """(zip, sha256, versao). Remonta sozinho quando algum arquivo do programa muda."""
    arqs = arquivos_pacote()
    ass = tuple((nome, os.path.getmtime(p), os.path.getsize(p)) for p, nome in arqs)
    with _LOCK:
        if _PACOTE["assinatura"] != ass:
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
                for p, nome in arqs:
                    zi = zipfile.ZipInfo("Destrava/" + nome, date_time=(2020, 1, 1, 0, 0, 0))  # data fixa: mesmo conteúdo, mesmo hash
                    zi.compress_type = zipfile.ZIP_DEFLATED
                    zi.external_attr = (0o755 if nome.endswith(".sh") else 0o644) << 16
                    with open(p, "rb") as fh:
                        z.writestr(zi, fh.read())
            data = buf.getvalue()
            _PACOTE.update(assinatura=ass, zip=data, sha256=hashlib.sha256(data).hexdigest(), versao=versao_programa())
        return _PACOTE["zip"], _PACOTE["sha256"], _PACOTE["versao"]


def runtimes():
    """Pythons fixos baixados por nucleo/baixar_runtimes.py: {nome: {arquivo, sha256, python}} (só os que existem)."""
    base = str(settings.DESTRAVA_RUNTIMES)
    try:
        with open(os.path.join(base, "runtimes.json"), encoding="utf-8") as fh:
            d = json.load(fh)
    except (OSError, ValueError):
        return {}
    return {k: v for k, v in d.items() if re.match(r"^[a-z0-9_-]+$", k) and os.path.isfile(os.path.join(base, os.path.basename(v.get("arquivo", ""))))}


def caminho_runtime(nome):
    rt = runtimes().get(nome)
    return os.path.join(str(settings.DESTRAVA_RUNTIMES), os.path.basename(rt["arquivo"])) if rt else None


ESPERADOS = ("windows-amd64", "mac-arm64", "mac-x86_64", "linux-x86_64")
