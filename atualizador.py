# -*- coding: utf-8 -*-
"""BKP Pro - atualizador offline.

Troca SÓ os arquivos do programa. Seus registros nunca são tocados:
  maquinas/ (fichas, históricos, termos, OS), consentimentos.log, runtime/ e _versoes/ ficam exatamente como estão.
Antes de trocar, guarda uma cópia da versão atual em _versoes/ (dá para voltar com um clique).
Sem internet: você baixa o BKP-Pro.zip novo e o programa encontra (Downloads, Área de Trabalho, pendrive) ou você o escolhe.
"""
import datetime
import hashlib
import os
import re
import shutil
import sys
import tempfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
VERSOES = os.path.join(HERE, "_versoes")
EXT_OK = {".py", ".html", ".js", ".svg", ".txt", ".sh", ".bat", ".png", ".css", ".md", ".command", ".json"}
DIRS_DADOS = {"maquinas", "runtime", "_versoes", "_novo_tmp"}
ARQ_DADOS = {"consentimentos.log"}
ARQ_CONFIG = {"etiquetas.txt"}  # o técnico pode ter editado: a nova vai ao lado, como .novo.txt
MAX_ZIP = 300 * 1024 * 1024


def _vkey(v):
    return tuple(int(x) if x.isdigit() else 0 for x in re.split(r"[.\-]", v or "0"))


def _is_code(rel):
    rel = rel.replace("\\", "/")
    top = rel.split("/")[0]
    if top in DIRS_DADOS or rel in ARQ_DADOS or rel.startswith("."):
        return False
    return os.path.splitext(rel)[1].lower() in EXT_OK


def _seguro(nome):
    n = nome.replace("\\", "/")
    return not (n.startswith("/") or ".." in n.split("/") or re.match(r"^[A-Za-z]:", n))


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def inspecionar(zpath):
    """(prefixo, versao, arquivos_de_codigo) de um zip do BKP Pro; levanta ValueError se não for válido."""
    if not os.path.isfile(zpath):
        raise ValueError("Arquivo não encontrado.")
    if os.path.getsize(zpath) > MAX_ZIP:
        raise ValueError("Arquivo grande demais para ser o BKP Pro.")
    try:
        z = zipfile.ZipFile(zpath)
    except zipfile.BadZipFile:
        raise ValueError("Esse arquivo não é um .zip válido.")
    with z:
        nomes = [n for n in z.namelist() if not n.endswith("/")]
        if any(not _seguro(n) for n in nomes):
            raise ValueError("O zip tem caminhos inseguros. Não vou usar.")
        cand = sorted([n for n in nomes if n.replace("\\", "/").endswith("dd_backup.py")], key=lambda n: n.count("/"))
        if not cand:
            raise ValueError("Isso não parece ser o BKP Pro (não achei dd_backup.py).")
        pref = cand[0].replace("\\", "/")[:-len("dd_backup.py")]
        for obrig in ("ficha.py", "web/app.html"):
            if (pref + obrig) not in [n.replace("\\", "/") for n in nomes]:
                raise ValueError("Zip incompleto (falta %s)." % obrig)
        src = z.read(cand[0]).decode("utf-8", "replace")
        m = re.search(r'^VERSION\s*=\s*"([^"]+)"', src, re.M)
        if not m:
            raise ValueError("Não consegui ler a versão dentro do zip.")
        arqs = [n for n in nomes if n.replace("\\", "/").startswith(pref) and _is_code(n.replace("\\", "/")[len(pref):])]
        return pref, m.group(1), arqs


def procurar(versao_atual):
    """Procura BKP-Pro*.zip nos lugares usuais. Devolve os válidos, mais novos primeiro."""
    home = os.path.expanduser("~")
    pastas = [os.path.join(home, "Downloads"), os.path.join(home, "Transferências"), os.path.join(home, "Desktop"), os.path.join(home, "Área de Trabalho"), os.path.dirname(HERE), HERE]
    vistos, out = set(), []
    for d in pastas:
        try:
            nomes = os.listdir(d)
        except OSError:
            continue
        for n in nomes:
            p = os.path.join(d, n)
            if p in vistos or not re.match(r"(?i)^bkp[-_ ]?pro.*\.zip$", n):
                continue
            vistos.add(p)
            try:
                pref, v, arqs = inspecionar(p)
            except ValueError:
                continue
            out.append({"caminho": p, "nome": n, "versao": v, "mais_nova": _vkey(v) > _vkey(versao_atual), "igual": v == versao_atual,
                        "quando": datetime.datetime.fromtimestamp(os.path.getmtime(p)).strftime("%Y-%m-%d %H:%M"), "mtime": os.path.getmtime(p)})
    out.sort(key=lambda x: (_vkey(x["versao"]), x["mtime"]), reverse=True)
    return out


def versoes_salvas():
    out = []
    try:
        for n in sorted(os.listdir(VERSOES), reverse=True):
            if os.path.isdir(os.path.join(VERSOES, n)):
                out.append({"nome": n, "versao": n.split("_")[0]})
    except OSError:
        pass
    return out


def _arquivos_programa():
    out = []
    for dp, dns, fns in os.walk(HERE):
        rel_dir = os.path.relpath(dp, HERE).replace("\\", "/")
        if rel_dir == ".":
            rel_dir = ""
        dns[:] = [d for d in dns if (rel_dir + "/" + d).strip("/").split("/")[0] not in DIRS_DADOS and d != "__pycache__"]
        for fn in fns:
            rel = (rel_dir + "/" + fn).strip("/")
            if _is_code(rel):
                out.append(rel)
    return out


def versao_disco(padrao=""):
    """Versão dos arquivos que estão no disco agora (pode ser mais nova que a do processo, se acabou de atualizar)."""
    try:
        with open(os.path.join(HERE, "dd_backup.py"), encoding="utf-8") as fh:
            m = re.search(r'^VERSION\s*=\s*"([^"]+)"', fh.read(), re.M)
        return m.group(1) if m else padrao
    except OSError:
        return padrao


def _guardar_atual(versao):
    base = "%s_%s" % (versao, datetime.datetime.now().strftime("%Y%m%d-%H%M%S"))
    nome, i = base, 1
    while os.path.exists(os.path.join(VERSOES, nome)):
        i += 1
        nome = "%s-%d" % (base, i)
    dest = os.path.join(VERSOES, nome)
    for rel in _arquivos_programa():
        d = os.path.join(dest, rel)
        os.makedirs(os.path.dirname(d), exist_ok=True)
        shutil.copy2(os.path.join(HERE, rel), d)
    # mantém só as 5 mais recentes
    antigas = sorted([n for n in os.listdir(VERSOES) if os.path.isdir(os.path.join(VERSOES, n))])
    for n in antigas[:-5]:
        shutil.rmtree(os.path.join(VERSOES, n), ignore_errors=True)
    return nome


def _chmod_exec(p):
    if p.endswith((".sh", ".command")):
        try:
            os.chmod(p, 0o755)
        except OSError:
            pass


def aplicar(zpath, versao_atual):
    """Troca o programa pela versão do zip. Retorna um relatório; em caso de erro, restaura a versão atual."""
    versao_atual = versao_disco(versao_atual)
    pref, nova, arqs = inspecionar(zpath)
    zhash = sha256(zpath)
    os.makedirs(VERSOES, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="_novo_tmp", dir=HERE)
    try:
        with zipfile.ZipFile(zpath) as z:
            for n in arqs:
                rel = n.replace("\\", "/")[len(pref):]
                d = os.path.join(tmp, rel)
                os.makedirs(os.path.dirname(d), exist_ok=True)
                with z.open(n) as src, open(d, "wb") as out:
                    shutil.copyfileobj(src, out)
        for dp, _, fns in os.walk(tmp):  # confere se todo .py compila antes de trocar qualquer coisa
            for fn in fns:
                if fn.endswith(".py"):
                    with open(os.path.join(dp, fn), encoding="utf-8") as fh:
                        compile(fh.read(), fn, "exec")
        guardada = _guardar_atual(versao_atual)
        trocados, novos, config_nova = 0, 0, []
        try:
            for dp, _, fns in os.walk(tmp):
                for fn in fns:
                    rel = os.path.relpath(os.path.join(dp, fn), tmp).replace("\\", "/")
                    destino = os.path.join(HERE, rel)
                    if rel in ARQ_CONFIG and os.path.exists(destino):
                        novo = os.path.splitext(destino)[0] + ".novo.txt"
                        os.replace(os.path.join(dp, fn), novo)
                        config_nova.append(os.path.basename(novo))
                        continue
                    existia = os.path.exists(destino)
                    os.makedirs(os.path.dirname(destino), exist_ok=True)
                    os.replace(os.path.join(dp, fn), destino)
                    _chmod_exec(destino)
                    trocados += 1 if existia else 0
                    novos += 0 if existia else 1
        except Exception:
            _restaurar(os.path.join(VERSOES, guardada))
            raise
        return {"de": versao_atual, "para": nova, "trocados": trocados, "novos": novos, "guardada": guardada, "zip_sha256": zhash, "config_nova": config_nova}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _restaurar(pasta):
    for dp, _, fns in os.walk(pasta):
        for fn in fns:
            rel = os.path.relpath(os.path.join(dp, fn), pasta)
            d = os.path.join(HERE, rel)
            os.makedirs(os.path.dirname(d), exist_ok=True)
            shutil.copy2(os.path.join(dp, fn), d)
            _chmod_exec(d)


def reverter(nome, versao_atual):
    versao_atual = versao_disco(versao_atual)
    pasta = os.path.join(VERSOES, os.path.basename(nome))
    if not os.path.isdir(pasta):
        raise ValueError("Versão guardada não encontrada.")
    guardada = _guardar_atual(versao_atual)
    _restaurar(pasta)
    return {"de": versao_atual, "para": nome.split("_")[0], "guardada": guardada}


def reiniciar_processo():
    """Abre uma nova instância do programa (mesmos argumentos, mesmos privilégios) e encerra esta."""
    import subprocess
    cmd = [sys.executable, os.path.join(HERE, "dd_backup.py")] + sys.argv[1:]
    kw = {}
    if os.name == "nt":
        kw["creationflags"] = 0x00000008 | 0x00000200
    else:
        kw["start_new_session"] = True
    subprocess.Popen(cmd, cwd=HERE, stdin=subprocess.DEVNULL, **kw)
