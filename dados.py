# -*- coding: utf-8 -*-
"""Destrava! - Dados: varredura de espaço, limpeza segura e offload verificado (SHA-256).

Regras de segurança (valem no servidor, não só na tela):
  * só enxerga e mexe dentro da pasta do usuário; sistema, credenciais e perfis ativos são ZONA VERMELHA (bloqueio total);
  * a tela nunca manda caminhos: manda ids da última varredura, e cada item é revalidado antes de agir;
  * limpeza vai para a Lixeira por padrão; apagar de vez só quando o técnico marca explicitamente;
  * offload: copia -> relê o destino e confere o hash -> só então remove o original (da Lixeira, por padrão).
"""
import datetime
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import unicodedata
import urllib.parse

IS_WIN = os.name == "nt"
IS_MAC = sys.platform == "darwin"
HOME = os.path.expanduser("~")
H = {"physical_id": None, "fs_type": None, "user_home": None}
LOCK = threading.Lock()
CHUNK = 4 * 1024 * 1024


def set_helpers(**kw):
    H.update(kw)
    if "user_home" in kw:
        redefinir_usuarios()


def home():
    f = H.get("user_home")
    return f() if f else os.path.expanduser("~")


def base_unidade():
    return 1000.0 if IS_MAC else 1024.0


def fmt(n):
    n = float(n or 0)
    b = base_unidade()
    for u in ("B", "KB", "MB", "GB", "TB"):
        if n < b or u == "TB":
            return ("%.0f %s" % (n, u)) if u == "B" else ("%.1f %s" % (n, u))
        n /= b


def _aloc(st):
    """Tamanho REAL ocupado no disco (blocos alocados). st_size é o tamanho lógico e engana em arquivos esparsos (VMs, Docker), clones e placeholders."""
    bl = getattr(st, "st_blocks", None)
    if bl is not None:
        return min(int(bl) * 512, int(st.st_size)) if st.st_size else 0
    return int(st.st_size)


def _nuvem(st):
    """True se o arquivo é só um 'atalho' da nuvem (iCloud/OneDrive): não ocupa disco e ler baixaria tudo."""
    fl = getattr(st, "st_flags", 0) or 0
    if fl & 0x40000000:  # SF_DATALESS (macOS)
        return True
    fa = getattr(st, "st_file_attributes", 0) or 0
    return bool(fa & (0x400000 | 0x40000 | 0x1000))  # Windows: recall on data access / recall on open / offline


_HL = set()  # (dev, inode) já contados nesta varredura (hard links não contam duas vezes)


def _repetido(st, hl=None):
    hl = _HL if hl is None else hl
    if getattr(st, "st_nlink", 1) > 1:
        k = (st.st_dev, st.st_ino)
        if k in hl:
            return True
        hl.add(k)
    return False


# ----------------------------------------------------------------------------------------------
# zona vermelha (bloqueio total)
# ----------------------------------------------------------------------------------------------
_VERM_SEG = {".ssh", ".gnupg", ".aws", ".azure", ".kube", ".password-store", "keychains", ".git", "credentials", "wallets"}
_VERM_PARTES = ("library/keychains", "library/mail", "library/messages", "library/safari", "library/application support/addressbook",
                "library/containers/com.apple", "library/group containers", ".config/gcloud", "appdata/roaming/microsoft/credentials", "appdata/local/microsoft/credentials",
                "appdata/roaming/microsoft/protect", ".local/share/keyrings", "library/accounts", "library/cookies", "library/preferences")
_VERM_EXT = {".pem", ".key", ".p12", ".pfx", ".kdbx", ".gpg", ".keychain", ".keychain-db", ".ppk"}
_VERM_BIBLIO = (".photoslibrary", ".fcpbundle", ".imovielibrary", ".tvlibrary", ".musiclibrary", ".lrlibrary", ".app")


def _norm(p):
    return os.path.normcase(os.path.abspath(p)).replace("\\", "/")


# ----------------------------------------------------------------------------------------------
# usuários do computador: a varredura passa pela pasta de cada um
# ----------------------------------------------------------------------------------------------
_HOMES = []  # [(usuário, pasta)] da última varredura; o primeiro é quem está usando o computador
SEM_ACESSO = []  # usuários cuja pasta não deu para ler (falta administrador/sudo)
_USR = [""]  # usuário da pasta sendo varrida agora (vai em cada item)


def pastas_usuarios():
    """[(usuário, pasta)] de todos os usuários do computador que dá para ler, começando por quem está usando."""
    atual = os.path.abspath(home())
    out, vistos, sem = [], set(), []

    def add(nome, p):
        k = _norm(p)
        if k in vistos:
            return
        vistos.add(k)
        try:
            os.listdir(p)
        except OSError:
            sem.append(nome)
            return
        out.append((nome, os.path.abspath(p)))
    add(os.path.basename(atual.rstrip("/\\")) or atual, atual)
    if IS_WIN:
        drv = os.path.splitdrive(atual)[0] or os.environ.get("SystemDrive", "C:")
        base, pular = os.path.join(drv + os.sep, "Users"), {"default", "default user", "all users", "defaultapppool"}
    elif IS_MAC:
        base, pular = "/Users", {"shared", "guest"}
    else:
        base, pular = "/home", set()
    try:
        nomes = sorted(os.listdir(base))
    except OSError:
        nomes = []
    for n in nomes:
        p = os.path.join(base, n)
        if n.startswith(".") or n.lower() in pular or re.match(r"^defaultuser\d+$", n, re.I) or os.path.islink(p) or not os.path.isdir(p):
            continue
        add(n, p)
    if not IS_WIN and not IS_MAC and os.path.isdir("/root") and hasattr(os, "geteuid") and os.geteuid() == 0:
        add("root", "/root")
    SEM_ACESSO[:] = sem
    return out


def homes():
    if not _HOMES:
        _HOMES[:] = pastas_usuarios()
    return _HOMES


def redefinir_usuarios():
    del _HOMES[:]


def dono(path):
    """(usuário, pasta do usuário) que contém path, ou (None, None)."""
    p = _norm(path)
    best = (None, None)
    for nome, h in homes():
        hn = _norm(h)
        if (p == hn or p.startswith(hn.rstrip("/") + "/")) and (best[1] is None or len(hn) > len(_norm(best[1]))):
            best = (nome, h)
    return best


def zona_vermelha(path):
    """Motivo do bloqueio (str) ou None se pode ser considerado."""
    p = _norm(path)
    if os.path.islink(path):
        return "atalho/link simbólico: não seguimos"
    _, dh = dono(path)
    if dh is None:
        return "fora das pastas de usuário"
    h = _norm(dh).rstrip("/")
    if p == h:
        return "pasta do usuário (não removemos a pasta inteira)"
    # as regras são em minúsculas: no Mac e no Linux as pastas reais são "Documents", "Library/Keychains"...
    # NFC porque o macOS pode devolver acentos decompostos ("Área de Trabalho")
    rel = unicodedata.normalize("NFC", p[len(h) + 1:]).lower()
    if rel in ("desktop", "documents", "downloads", "pictures", "movies", "music", "videos", "library", "appdata", "área de trabalho", "documentos", "imagens", "vídeos", "música"):
        return "pasta principal do usuário (não removemos a pasta inteira)"
    segs = set(rel.split("/"))
    if segs & _VERM_SEG:
        return "credenciais, chaves ou repositório ativo"
    for parte in _VERM_PARTES:
        if rel == parte or rel.startswith(parte + "/"):
            return "dados de sistema, contas ou credenciais"
    ext = os.path.splitext(rel)[1]
    if ext in _VERM_EXT:
        return "arquivo de chave/credencial"
    if rel.endswith(_VERM_BIBLIO) or any(("/" + b + "/") in ("/" + rel + "/") for b in _VERM_BIBLIO):
        return "biblioteca de um aplicativo (use o próprio aplicativo para gerenciar)"
    if "/login data" in rel or rel.endswith("/cookies") or rel.endswith("/key4.db") or rel.endswith("/logins.json"):
        return "senhas/cookies de navegador"
    return None


# ----------------------------------------------------------------------------------------------
# alvos conhecidos (zona verde): caches que o sistema/app recria
# ----------------------------------------------------------------------------------------------
def _alvos_verdes(h):
    out = []  # (caminho, titulo, motivo, agrupar_filhos)

    def add(p, t, m, filhos=False):
        if os.path.isdir(p):
            out.append((p, t, m, filhos))
    if IS_MAC:
        add(os.path.join(h, "Movies/CapCut/User Data/Cache"), "Cache do CapCut", "Arquivos temporários de prévia/render que o CapCut recria.")
        add(os.path.join(h, "Movies/CapCut/User Data/Cache/proxy"), "Proxies do CapCut", "Cópias leves de vídeo para edição; são recriadas.")
        add(os.path.join(h, "Library/Caches"), "Cache de aplicativos", "Cada aplicativo recria o seu cache.", True)
        add(os.path.join(h, "Library/Logs"), "Registros (logs) de aplicativos", "Só histórico de funcionamento.", True)
    elif IS_WIN:
        la = os.path.join(h, "AppData", "Local")
        add(os.path.join(la, "CapCut", "User Data", "Cache"), "Cache do CapCut", "Arquivos temporários de prévia/render que o CapCut recria.")
        for nav, rel in (("Chrome", "Google/Chrome/User Data"), ("Edge", "Microsoft/Edge/User Data"), ("Brave", "BraveSoftware/Brave-Browser/User Data")):
            base = os.path.join(la, *rel.split("/"))
            if os.path.isdir(base):
                for perfil in sorted(os.listdir(base)):
                    for sub in ("Cache", "Code Cache", "GPUCache"):
                        add(os.path.join(base, perfil, sub), "Cache do %s (%s)" % (nav, perfil), "Cache de navegação; o navegador recria.")
        add(os.path.join(la, "Microsoft", "Windows", "INetCache"), "Cache de internet do Windows", "Arquivos temporários de navegação.")
        add(os.path.join(la, "CrashDumps"), "Relatórios de falha", "Despejos de memória de programas que travaram.")
        add(os.path.join(la, "D3DSCache"), "Cache de gráficos", "O Windows recria.")
    else:
        add(os.path.join(h, ".cache"), "Cache de aplicativos", "Cada aplicativo recria o seu cache.", True)
        for rel, nome in ((".config/google-chrome", "Chrome"), (".config/chromium", "Chromium"), (".config/BraveSoftware/Brave-Browser", "Brave")):
            base = os.path.join(h, *rel.split("/"))
            if os.path.isdir(base):
                for perfil in sorted(os.listdir(base)):
                    for sub in ("Cache", "Code Cache", "GPUCache"):
                        add(os.path.join(base, perfil, sub), "Cache do %s (%s)" % (nome, perfil), "Cache de navegação; o navegador recria.")
        add(os.path.join(h, ".local/share/CapCut/User Data/Cache"), "Cache do CapCut", "Arquivos temporários de prévia/render que o CapCut recria.")
    if IS_MAC:
        for nav, rel in (("Chrome", "Library/Application Support/Google/Chrome"), ("Edge", "Library/Application Support/Microsoft Edge"), ("Brave", "Library/Application Support/BraveSoftware/Brave-Browser")):
            base = os.path.join(h, *rel.split("/"))
            if os.path.isdir(base):
                for perfil in sorted(os.listdir(base)):
                    for sub in ("Cache", "Code Cache", "GPUCache"):
                        add(os.path.join(base, perfil, sub), "Cache do %s (%s)" % (nav, perfil), "Cache de navegação; o navegador recria.")
    return out


def _pastas_capcut(h):
    bases = []
    if IS_MAC:
        bases += [os.path.join(h, "Movies/CapCut/User Data/Projects")]
    elif IS_WIN:
        bases += [os.path.join(h, "AppData", "Local", "CapCut", "User Data", "Projects")]
    else:
        bases += [os.path.join(h, ".local/share/CapCut/User Data/Projects")]
    out = []
    for b in bases:
        if not os.path.isdir(b):
            continue
        for nome in sorted(os.listdir(b)):
            p = os.path.join(b, nome)
            if os.path.isdir(p):
                if nome.lower().startswith("com.lveditor") or nome.lower().endswith(".draft"):
                    for sub in sorted(os.listdir(p)):
                        q = os.path.join(p, sub)
                        if os.path.isdir(q):
                            out.append(q)
                else:
                    out.append(p)
    return out


# ----------------------------------------------------------------------------------------------
# classificação por tipo
# ----------------------------------------------------------------------------------------------
EXT = {
    "Vídeos": {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".mts", ".wmv", ".mpg", ".mpeg", ".prproj_proxy"},
    "Fotos": {".jpg", ".jpeg", ".png", ".heic", ".raw", ".cr2", ".nef", ".arw", ".dng", ".tif", ".tiff", ".gif", ".bmp", ".webp"},
    "Áudios": {".mp3", ".wav", ".flac", ".aac", ".m4a", ".ogg", ".aiff"},
    "Instaladores e imagens de disco": {".dmg", ".pkg", ".exe", ".msi", ".iso", ".img", ".deb", ".rpm", ".appimage"},
    "Compactados": {".zip", ".rar", ".7z", ".tar", ".gz", ".tgz", ".bz2", ".xz"},
    "Máquinas virtuais": {".vmdk", ".vdi", ".qcow2", ".vhd", ".vhdx", ".vmwarevm", ".ova"},
    "Documentos e projetos": {".pdf", ".psd", ".ai", ".indd", ".prproj", ".aep", ".blend", ".docx", ".xlsx", ".pptx", ".sketch", ".fig", ".drp", ".fcp"},
}
INSTAL = {".dmg", ".pkg", ".exe", ".msi"}
CAT_MIDIA = ("Vídeos", "Fotos", "Áudios")


def categoria(nome):
    e = os.path.splitext(nome.lower())[1]
    for cat, exts in EXT.items():
        if e in exts:
            return cat
    return "Outros"


def _gravacao_tela(nome):
    n = nome.lower()
    return n.endswith((".mov", ".mp4", ".mkv")) and bool(re.match(r"(screen ?recording|gravação de tela|gravacao de tela|captura de tela|screencast|recording)", n))



# ----------------------------------------------------------------------------------------------
# restos de programas que não parecem mais instalados (sempre dependem de aprovação do usuário)
# ----------------------------------------------------------------------------------------------
def _nn(x):
    return re.sub(r"[^a-z0-9]", "", (x or "").lower())


def _apps_instalados():
    nomes = set()

    def add(n):
        n = _nn(n)
        if len(n) >= 3:
            nomes.add(n)
    try:
        if IS_MAC:
            for base in ("/Applications", "/Applications/Utilities", "/System/Applications", "/System/Applications/Utilities", os.path.join(home(), "Applications")):
                for n in (os.listdir(base) if os.path.isdir(base) else []):
                    add(n[:-4] if n.endswith(".app") else n)
        elif IS_WIN:
            r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
                                "$k='HKLM:\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\*','HKLM:\\Software\\WOW6432Node\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\*','HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\*'; "
                                "Get-ItemProperty $k -ErrorAction SilentlyContinue | ForEach-Object { $_.DisplayName }; Get-AppxPackage -ErrorAction SilentlyContinue | ForEach-Object { $_.Name }"],
                               capture_output=True, timeout=90, creationflags=0x08000000)
            for ln in (r.stdout or b"").decode("utf-8", "replace").splitlines():
                add(ln)
            for pf in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)"), os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs")):
                if pf and os.path.isdir(pf):
                    for n in os.listdir(pf):
                        add(n)
        else:
            for base in ("/usr/share/applications", os.path.join(home(), ".local/share/applications"), "/var/lib/flatpak/exports/share/applications", "/var/lib/snapd/desktop/applications"):
                for n in (os.listdir(base) if os.path.isdir(base) else []):
                    add(n.replace(".desktop", ""))
            for base in (os.path.join(home(), ".var/app"), "/snap"):
                for n in (os.listdir(base) if os.path.isdir(base) else []):
                    add(n)
            try:
                with open("/var/lib/dpkg/status", encoding="utf-8", errors="replace") as fh:
                    for ln in fh:
                        if ln.startswith("Package: "):
                            add(ln[9:])
            except OSError:
                pass
    except Exception:
        pass
    return nomes


_ORF_PULAR = {"apple", "addressbook", "clouddocs", "knowledge", "icloud", "dock", "syncservices", "mobilesync", "callhistorydb", "callhistorytransactions", "differentialprivacy", "crashreporter",
              "controlcenter", "fileprovider", "networkserviceproxy", "microsoft", "packages", "temp", "programs", "publishers", "connecteddevicesplatform", "virtualstore", "systemd", "dconf",
              "pulse", "autostart", "fontconfig", "trash", "applications", "icons", "keyrings", "gtk3", "gtk4", "mozilla", "google", "chrome", "chromium", "gnome", "kde", "xdg", "flatpak", "snap",
              "recentdocuments", "sharedlibrary", "nvidia", "intel", "amd", "windows", "wsl", "pip", "npm", "node", "python", "java", "code", "vscode", "jetbrains", "docker", "kubernetes"}


def _orfaos(agora, idle_dias, pular, h):
    if IS_MAC:
        bases = [os.path.join(h, "Library/Application Support")]
    elif IS_WIN:
        bases = [os.path.join(h, "AppData", "Roaming"), os.path.join(h, "AppData", "Local")]
    else:
        bases = [os.path.join(h, ".config"), os.path.join(h, ".local/share")]
    inst = None
    for b in bases:
        if not os.path.isdir(b) or CANCEL.is_set():
            continue
        try:
            nomes = sorted(os.listdir(b))
        except OSError:
            continue
        for nome in nomes:
            if CANCEL.is_set():
                return
            p = os.path.join(b, nome)
            n = _nn(nome)
            if not os.path.isdir(p) or os.path.islink(p) or len(n) < 3 or n in _ORF_PULAR or nome.lower().startswith(("com.apple", "microsoft")) or zona_vermelha(p):
                continue
            if inst is None:
                ST["atual"] = "Conferindo quais programas estão instalados"
                inst = _apps_instalados()
                if not inst:
                    return  # sem lista confiável de programas instalados: não arrisca
            if any((n in i or i in n) for i in inst if len(i) >= 4):
                continue
            ST["atual"] = p
            pular.add(_norm(p))
            b_, n_, ult = tamanho_dir(p, CANCEL)
            ST["arquivos"] += n_
            ST["bytes"] += b_
            dias = int((agora - ult) / 86400) if ult else 9999
            if b_ >= 50 * 1024 * 1024 and dias >= idle_dias:
                _add({"path": p, "tipo": "pasta", "zona": "ambar", "cat": "Restos de programas (provável sem uso)", "titulo": nome,
                      "motivo": "Não encontrei \"%s\" instalado e os dados estão parados há %d dias. Provavelmente o programa não é mais usado, mas só você sabe: confirme." % (nome, dias),
                      "bytes": b_, "arquivos": n_, "ultimo_uso": ult, "pre": False, "orfao": True})


# ----------------------------------------------------------------------------------------------
# estado e varredura
# ----------------------------------------------------------------------------------------------
ST = {"fase": "ocioso", "pct": 0, "arquivos": 0, "pastas": 0, "bytes": 0, "atual": "", "erro": "", "inicio": 0, "bloqueados": 0, "acesso_total": True,
      "acao": {"tipo": "", "feito": 0, "total": 0, "bytes_feito": 0, "bytes_total": 0, "atual": "", "erros": [], "resultado": None, "rodando": False}}
ITENS = {}
RES = {"cockpit": None}
CANCEL = threading.Event()


def reset():
    with LOCK:
        ITENS.clear()
        RES["cockpit"] = None
        ST.update({"fase": "ocioso", "pct": 0, "arquivos": 0, "pastas": 0, "bytes": 0, "atual": "", "erro": "", "bloqueados": 0})
        ST["acao"] = {"tipo": "", "feito": 0, "total": 0, "bytes_feito": 0, "bytes_total": 0, "atual": "", "erros": [], "resultado": None, "rodando": False}


def acesso_total_mac():
    """No macOS, o Terminal só lê algumas pastas (Mail, Safari...) com 'Acesso Total ao Disco'."""
    if not IS_MAC:
        return True
    for rel in ("Library/Safari", "Library/Mail", "Library/Messages"):
        p = os.path.join(home(), rel)
        if os.path.exists(p):
            try:
                os.listdir(p)
                return True
            except PermissionError:
                return False
            except OSError:
                continue
    return True


def tamanho_logico(path):
    """Soma dos tamanhos LÓGICOS (o que ocupa no destino ao copiar; arquivos esparsos viram inteiros)."""
    if os.path.isfile(path):
        return os.path.getsize(path)
    tot = 0
    for dp, dns, fns in os.walk(path):
        for fn in fns:
            try:
                st = os.lstat(os.path.join(dp, fn))
                if not _nuvem(st):
                    tot += st.st_size
            except OSError:
                pass
    return tot


def tamanho_dir(path, cancel=None, hl=None):
    """(bytes, arquivos, ultimo_uso_epoch) de uma pasta, sem seguir links. hl: conjunto de hard links já contados
    (padrão: o da varredura)."""
    hl = _HL if hl is None else hl
    tot = n = 0
    ult = 0
    stack = [path]
    while stack:
        d = stack.pop()
        try:
            with os.scandir(d) as it:
                for e in it:
                    if cancel and cancel.is_set():
                        return tot, n, ult
                    try:
                        if e.is_symlink():
                            continue
                        if e.is_dir(follow_symlinks=False):
                            stack.append(e.path)
                        else:
                            st = e.stat(follow_symlinks=False)
                            if _nuvem(st) or _repetido(st, hl):
                                continue
                            tot += _aloc(st)
                            n += 1
                            ult = max(ult, st.st_mtime, st.st_atime)
                    except OSError:
                        continue
        except OSError:
            continue
    return tot, n, ult


def iniciar_varredura(idle_dias=90, min_mb=100):
    with LOCK:
        if ST["fase"] == "varrendo":
            raise ValueError("A varredura já está rodando.")
        ITENS.clear()
        ST.update({"fase": "varrendo", "pct": 0, "arquivos": 0, "pastas": 0, "bytes": 0, "atual": "", "erro": "", "inicio": time.time(), "bloqueados": 0})
    CANCEL.clear()
    threading.Thread(target=_varrer, args=(int(idle_dias), int(min_mb)), daemon=True).start()


_SEQ = [0]


def _novo_id():
    # contador que só cresce: depois de limpar alguns itens, um item novo não pode herdar o id de outro
    _SEQ[0] += 1
    return _SEQ[0]


def _add(it):
    it.setdefault("usuario", _USR[0])
    it["id"] = _novo_id()
    ITENS[it["id"]] = it
    return it


def _varrer_usuario(usr, h, agora, idle_dias, min_b, cat_bytes):
    """Passos 1 a 3 numa pasta de usuário. Devolve os bytes da zona verde encontrados nela."""
    try:
        dev_home = os.stat(h).st_dev
    except OSError:
        dev_home = None
    pular = set()
    verde_bytes = 0
    alvos = _alvos_verdes(h)

    # 1) zona verde: caches conhecidos
    ST["atual"] = "Procurando caches conhecidos"
    ST["pct"] = 3
    for i, (p, tit, mot, filhos) in enumerate(alvos):
        if CANCEL.is_set():
            break
        pular.add(_norm(p))
        ST["atual"] = p
        if filhos:
            try:
                subs = sorted(os.listdir(p))
            except OSError:
                continue
            for s in subs:
                q = os.path.join(p, s)
                if not os.path.isdir(q) or os.path.islink(q):
                    continue
                b, n, ult = tamanho_dir(q, CANCEL)
                ST["arquivos"] += n
                ST["bytes"] += b
                if b >= 20 * 1024 * 1024:
                    _add({"path": q, "tipo": "pasta", "zona": "verde", "cat": "Limpeza imediata", "titulo": "%s › %s" % (tit, s), "motivo": mot, "bytes": b, "arquivos": n, "ultimo_uso": ult, "pre": True})
                    verde_bytes += b
        else:
            b, n, ult = tamanho_dir(p, CANCEL)
            ST["arquivos"] += n
            ST["bytes"] += b
            if b >= 5 * 1024 * 1024:
                _add({"path": p, "tipo": "pasta", "zona": "verde", "cat": "Limpeza imediata", "titulo": tit, "motivo": mot, "bytes": b, "arquivos": n, "ultimo_uso": ult, "pre": True})
                verde_bytes += b
        ST["pct"] = 3 + int(12.0 * (i + 1) / max(1, len(alvos)))

    # 1b) backups de iPhone/iPad (Mac): grandes e muitas vezes esquecidos; mover para HD externo é o caminho
    mb = os.path.join(h, "Library", "Application Support", "MobileSync", "Backup")
    if IS_MAC and os.path.isdir(mb):
        pular.add(_norm(mb))
        try:
            bks = sorted(os.listdir(mb))
        except OSError:
            bks = []
        for d in bks:
            q = os.path.join(mb, d)
            if not os.path.isdir(q) or CANCEL.is_set():
                continue
            info = {}
            try:
                import plistlib
                with open(os.path.join(q, "Info.plist"), "rb") as fh:
                    info = plistlib.load(fh)
            except Exception:
                pass
            b, n, ult = tamanho_dir(q, CANCEL)
            ST["bytes"] += b
            ST["arquivos"] += n
            data = info.get("Last Backup Date")
            _add({"path": q, "tipo": "pasta", "zona": "ambar", "cat": "Backups de iPhone/iPad", "titulo": "Backup de %s" % (info.get("Device Name") or d[:12]),
                  "motivo": "Último backup em %s. Pode ser o único backup do aparelho: prefira mover para um HD externo." % (data.strftime("%d/%m/%Y") if hasattr(data, "strftime") else "?"),
                  "bytes": b, "arquivos": n, "ultimo_uso": ult, "pre": False})

    # 2) projetos CapCut parados (âmbar)
    ST["atual"] = "Procurando projetos do CapCut"
    for q in _pastas_capcut(h):
        if CANCEL.is_set():
            break
        pular.add(_norm(q))
        b, n, ult = tamanho_dir(q, CANCEL)
        ST["bytes"] += b
        ST["arquivos"] += n
        dias = int((agora - ult) / 86400) if ult else 9999
        if dias >= 30 and b >= 20 * 1024 * 1024:
            _add({"path": q, "tipo": "pasta", "zona": "ambar", "cat": "Projetos do CapCut", "titulo": "Projeto CapCut: %s" % os.path.basename(q), "motivo": "Sem edição há %d dias." % dias,
                  "bytes": b, "arquivos": n, "ultimo_uso": ult, "pre": False})
    ST["pct"] = 16
    _orfaos(agora, idle_dias, pular, h)
    ST["pct"] = 20

    # 3) varredura geral por arquivos grandes e parados
    raizes = [h]
    nomes_dl = {"downloads", "transferências"}
    stack = list(raizes)
    visitados = 0
    while stack and not CANCEL.is_set():
        d = stack.pop()
        if _norm(d) in pular:
            continue
        try:
            it = os.scandir(d)
        except PermissionError:
            ST["bloqueados"] += 1
            continue
        except OSError:
            continue
        ST["pastas"] += 1
        em_dl = os.path.basename(d).lower() in nomes_dl and _norm(os.path.dirname(d)) == _norm(h)
        with it:
            for e in it:
                if CANCEL.is_set():
                    break
                try:
                    if e.is_symlink():
                        continue
                    nome = e.name
                    if e.is_dir(follow_symlinks=False):
                        ln = nome.lower()
                        if ln in (".git", "node_modules", ".trash", ".trashes", "$recycle.bin") or ln.endswith(_VERM_BIBLIO) or zona_vermelha(e.path) and ln in _VERM_SEG:
                            if ln.endswith(_VERM_BIBLIO):
                                b, n, ult = tamanho_dir(e.path, CANCEL)
                                ST["bytes"] += b
                                if b >= min_b:
                                    _add({"path": e.path, "tipo": "pasta", "zona": "vermelha", "cat": "Bibliotecas e apps", "titulo": nome, "motivo": zona_vermelha(e.path) or "biblioteca de aplicativo", "bytes": b, "arquivos": n, "ultimo_uso": ult, "pre": False})
                            continue
                        if os.path.basename(os.path.dirname(e.path)).lower() == "library" and ln in ("keychains", "mail", "messages", "safari", "cookies", "preferences"):
                            continue
                        try:
                            if dev_home is not None and e.stat(follow_symlinks=False).st_dev != dev_home:
                                continue  # outro disco/volume montado dentro da pasta: não entra
                        except OSError:
                            continue
                        stack.append(e.path)
                        continue
                    st = e.stat(follow_symlinks=False)
                except PermissionError:
                    ST["bloqueados"] += 1
                    continue
                except OSError:
                    continue
                if _nuvem(st):
                    ST["nuvem_n"] += 1
                    ST["nuvem_bytes"] += st.st_size
                    continue
                if _repetido(st):
                    continue
                tam = _aloc(st)
                ST["arquivos"] += 1
                ST["bytes"] += tam
                ST["atual"] = e.path
                cat = categoria(nome)
                cat_bytes[cat] = cat_bytes.get(cat, 0) + tam
                ult = max(st.st_mtime, st.st_atime)
                dias = int((agora - ult) / 86400)
                ext = os.path.splitext(nome.lower())[1]
                # instaladores residuais em Downloads/Desktop: zona verde
                if ext in INSTAL and tam >= 5 * 1024 * 1024 and dias >= 14 and (em_dl or os.path.basename(d).lower() in ("desktop", "área de trabalho")) and not zona_vermelha(e.path):
                    _add({"path": e.path, "tipo": "arquivo", "zona": "verde", "cat": "Limpeza imediata", "titulo": "Instalador: %s" % nome, "motivo": "Instalador já usado (parado há %d dias)." % dias, "bytes": tam, "arquivos": 1, "logico": st.st_size, "ultimo_uso": ult, "pre": True})
                    verde_bytes += tam
                    continue
                if zona_vermelha(e.path):
                    continue
                if _gravacao_tela(nome) and dias >= 30 and tam >= 20 * 1024 * 1024:
                    _add({"path": e.path, "tipo": "arquivo", "zona": "ambar", "cat": "Gravações de tela", "titulo": nome, "motivo": "Gravação de tela parada há %d dias." % dias, "bytes": tam, "arquivos": 1, "logico": st.st_size, "ultimo_uso": ult, "pre": False})
                elif em_dl and dias >= 90 and tam >= 5 * 1024 * 1024:
                    _add({"path": e.path, "tipo": "arquivo", "zona": "ambar", "cat": "Downloads antigos", "titulo": nome, "motivo": "Baixado e parado há %d dias." % dias, "bytes": tam, "arquivos": 1, "logico": st.st_size, "ultimo_uso": ult, "pre": False})
                elif tam >= min_b and dias >= idle_dias:
                    _add({"path": e.path, "tipo": "arquivo", "zona": "ambar", "cat": cat if cat != "Outros" else "Outros arquivos grandes", "titulo": nome, "motivo": "%s parado há %d dias." % (fmt(tam), dias), "bytes": tam, "arquivos": 1, "logico": st.st_size, "ultimo_uso": ult, "pre": False})
        visitados += 1
        if visitados % 40 == 0:
            ST["pct"] = min(95, 18 + int(77.0 * (1 - 1.0 / (1 + visitados / 3000.0))))
    return verde_bytes


def _varrer(idle_dias, min_mb):
    try:
        agora = time.time()
        ST["acesso_total"] = acesso_total_mac()
        min_b = min_mb * 1000 * 1000 if IS_MAC else min_mb * 1024 * 1024
        _HL.clear()
        ST["nuvem_n"] = 0
        ST["nuvem_bytes"] = 0
        redefinir_usuarios()
        usuarios = homes()
        ST["usuarios"] = [u for u, _ in usuarios]
        ST["usuario_atual"] = usuarios[0][0] if usuarios else ""
        ST["sem_acesso"] = list(SEM_ACESSO)
        cat_bytes = {}
        por_usuario = {}
        verde_bytes = 0
        for usr, h in usuarios:
            if CANCEL.is_set():
                break
            _USR[0] = usr
            antes = ST["bytes"]
            verde_bytes += _varrer_usuario(usr, h, agora, idle_dias, min_b, cat_bytes)
            por_usuario[usr] = ST["bytes"] - antes
        h = usuarios[0][1] if usuarios else home()
        # 4) cockpit
        try:
            u = shutil.disk_usage(h)
            total, livre = u.total, u.free
        except OSError:
            total = livre = 0
        usado = max(0, total - livre)
        midia = sum(cat_bytes.get(c, 0) for c in CAT_MIDIA)
        docs = sum(v for k, v in cat_bytes.items() if k not in CAT_MIDIA and k != "Outros")
        limpavel = verde_bytes
        medido = ST["bytes"]  # tudo que foi lido na pasta pessoal, em tamanho real de disco
        apps = max(0, medido - midia - docs - limpavel)  # Library, dados de apps, caches menores, etc.
        aviso = ""
        if medido > usado and usado > 0:
            # nunca mostrar mais do que o disco tem: reduz proporcionalmente e avisa
            f = usado / float(medido)
            midia, docs, apps, limpavel = int(midia * f), int(docs * f), int(apps * f), int(limpavel * f)
            aviso = "A soma dos arquivos lidos passou do espaço usado (clones e compressão do sistema de arquivos). Os valores foram ajustados proporcionalmente: trate como estimativa."
        sistema = max(0, usado - midia - docs - apps - limpavel)
        ambar = sum(i["bytes"] for i in ITENS.values() if i["zona"] == "ambar")
        RES["cockpit"] = {"por_usuario": por_usuario, "total": total, "livre": livre, "usado": usado, "midias": midia, "documentos": docs, "apps": apps, "limpavel": limpavel, "parado": ambar,
                          "sistema": sistema, "medido": medido, "aviso": aviso, "nuvem_n": ST["nuvem_n"], "nuvem_bytes": ST["nuvem_bytes"], "por_tipo": cat_bytes, "base": int(base_unidade())}
        ST["pct"] = 100
        ST["fase"] = "cancelado" if CANCEL.is_set() else "pronto"
        ST["atual"] = ""
    except Exception as e:
        ST["erro"] = "%s: %s" % (type(e).__name__, e)
        ST["fase"] = "erro"


def estado():
    with LOCK:
        d = dict(ST)
        d["acao"] = dict(ST["acao"])
        d["acao"]["erros"] = list(ST["acao"]["erros"][-30:])
    d["cockpit"] = RES["cockpit"]
    d["n_itens"] = len(ITENS)
    return d


def resultado(zona=None, cat=None, q="", offset=0, limit=200, usuario=""):
    base = [i for i in ITENS.values() if not usuario or i.get("usuario") == usuario]
    itens = [i for i in base if (not zona or i["zona"] == zona) and (not cat or i["cat"] == cat) and (not q or q.lower() in i["path"].lower())]
    itens.sort(key=lambda i: -i["bytes"])
    cats = {}
    for i in base:
        c = cats.setdefault((i["zona"], i["cat"]), {"zona": i["zona"], "cat": i["cat"], "n": 0, "bytes": 0})
        c["n"] += 1
        c["bytes"] += i["bytes"]
    agora = time.time()
    rows = [{"id": i["id"], "titulo": i["titulo"], "path": i["path"], "tipo": i["tipo"], "zona": i["zona"], "cat": i["cat"], "motivo": i["motivo"], "bytes": i["bytes"],
             "arquivos": i["arquivos"], "dias": int((agora - i["ultimo_uso"]) / 86400) if i["ultimo_uso"] else None, "pre": i["pre"], "orfao": bool(i.get("orfao")),
             "usuario": i.get("usuario", ""), "no": no_de(i["path"], i.get("usuario")), "previa": tipo_previa(i["path"]) if i["tipo"] == "arquivo" else None,
             "pode_abrir": pode_abrir(i["path"])} for i in itens[offset:offset + limit]]
    return {"rows": rows, "total": len(itens), "usuarios": ST.get("usuarios", []), "cats": sorted(cats.values(), key=lambda c: (-{"verde": 3, "ambar": 2, "vermelha": 1}[c["zona"]], -c["bytes"]))}


def cancelar():
    CANCEL.set()


# ----------------------------------------------------------------------------------------------
# explorar, ver e abrir: qualquer zona, qualquer profundidade, todos os usuários. A tela só manda ids (nós).
# ----------------------------------------------------------------------------------------------
NOS = {}  # id -> {"path", "usuario"}
_NOS_IDX = {}  # caminho normalizado -> id
_TAM = {}  # caminho normalizado -> (bytes, arquivos, ultimo_uso, mtime da pasta) medidos pelo explorador
MEDIR = {"cancel": threading.Event(), "ativo": False}
PREVIA = {
    ".jpg": ("imagem", "image/jpeg"), ".jpeg": ("imagem", "image/jpeg"), ".png": ("imagem", "image/png"), ".gif": ("imagem", "image/gif"),
    ".webp": ("imagem", "image/webp"), ".bmp": ("imagem", "image/bmp"),
    ".mp4": ("video", "video/mp4"), ".m4v": ("video", "video/mp4"), ".mov": ("video", "video/mp4"), ".webm": ("video", "video/webm"),
    ".mp3": ("audio", "audio/mpeg"), ".m4a": ("audio", "audio/mp4"), ".wav": ("audio", "audio/wav"), ".ogg": ("audio", "audio/ogg"),
    ".opus": ("audio", "audio/ogg"), ".flac": ("audio", "audio/flac"), ".aac": ("audio", "audio/aac"),
    ".pdf": ("pdf", "application/pdf"),
}
# texto: sempre como text/plain (html, svg e xml aparecem como código, nunca viram página dentro do programa)
for _x in (".txt", ".csv", ".log", ".md", ".json", ".ini", ".cfg", ".conf", ".yml", ".yaml", ".xml", ".html", ".htm", ".svg", ".srt", ".tsv"):
    PREVIA[_x] = ("texto", "text/plain; charset=utf-8")
SEM_ABRIR = {".exe", ".msi", ".bat", ".cmd", ".ps1", ".vbs", ".vbe", ".js", ".jse", ".wsf", ".hta", ".lnk", ".url", ".scr", ".com", ".pif", ".cpl",
             ".msc", ".reg", ".jar", ".sh", ".command", ".app", ".appimage", ".deb", ".rpm", ".pkg", ".dmg", ".run"}
_CRED_SEG = {".ssh", ".gnupg", ".aws", ".azure", ".kube", ".password-store", "keychains", "credentials", "wallets", "keyrings", "protect"}


def no_de(path, usuario=None):
    k = _norm(path)
    nid = _NOS_IDX.get(k)
    if nid is None:
        nid = len(NOS) + 1
        NOS[nid] = {"path": os.path.abspath(path), "usuario": usuario if usuario is not None else (dono(path)[0] or "")}
        _NOS_IDX[k] = nid
    return nid


def _rel_dono(path):
    _, h = dono(path)
    if not h:
        return None
    return unicodedata.normalize("NFC", _norm(path)[len(_norm(h).rstrip("/")) + 1:]).lower()


def e_credencial(path):
    """Senhas, chaves e cookies: nunca têm prévia nem abrem; só "mostrar na pasta"."""
    rel = _rel_dono(path)
    if rel is None:
        return False
    if set(rel.split("/")) & _CRED_SEG or os.path.splitext(rel)[1] in _VERM_EXT or rel.endswith(".keychain-db"):
        return True
    r = "/" + rel
    return "/login data" in r or r.endswith(("/cookies", "/key4.db", "/logins.json")) or rel.startswith(("library/accounts", "library/cookies"))


def tipo_previa(path):
    t = PREVIA.get(os.path.splitext(path)[1].lower())
    return t[0] if t and not e_credencial(path) else None


def pode_abrir(path):
    return not e_credencial(path) and os.path.splitext(path.rstrip("/\\"))[1].lower() not in SEM_ABRIR


def caminho_no(nid):
    """Caminho de um nó, conferido de novo: existe, não é link e está numa pasta de usuário."""
    try:
        n = NOS.get(int(nid))
    except (TypeError, ValueError):
        n = None
    if not n:
        raise ValueError("Item não encontrado; atualize a lista.")
    p = n["path"]
    if not os.path.lexists(p):
        raise ValueError("Já não existe: %s" % p)
    if os.path.islink(p):
        raise ValueError("Atalho/link simbólico: não seguimos.")
    if dono(p)[1] is None:
        raise ValueError("Fora das pastas de usuário.")
    return p


def previa(nid):
    """(caminho, mime, tipo, limite de bytes) para mostrar o arquivo dentro do programa."""
    p = caminho_no(nid)
    if os.path.isdir(p):
        raise ValueError("Pasta não tem prévia: use Entrar.")
    t = PREVIA.get(os.path.splitext(p)[1].lower())
    if not t or e_credencial(p):
        raise ValueError("Sem prévia para este arquivo: use Abrir ou Mostrar na pasta.")
    return p, t[1], t[0], (200 * 1024 if t[0] == "texto" else None)


def _medir_fundo(paths):
    """Mede o tamanho das subpastas em segundo plano; a tela pergunta de novo enquanto 'medindo' for verdadeiro."""
    MEDIR["cancel"].set()
    ev = threading.Event()
    MEDIR["cancel"] = ev
    MEDIR["ativo"] = True

    def work():
        try:
            for p in paths:
                if ev.is_set():
                    return
                try:
                    mt = os.stat(p).st_mtime
                except OSError:
                    continue
                b, n, ult = tamanho_dir(p, ev, set())
                if ev.is_set():
                    return
                _TAM[_norm(p)] = (b, n, ult, mt)
        finally:
            if MEDIR["cancel"] is ev:
                MEDIR["ativo"] = False
    threading.Thread(target=work, daemon=True).start()


def _info_filho(path, nome, st, d, usr, agora, pend):
    k = _norm(path)
    nuvem = False
    if d:
        t = _TAM.get(k)
        tam, ult = (t[0], t[2]) if t and t[3] == st.st_mtime else (None, None)
        if tam is None:
            pend.append(path)
    else:
        nuvem = _nuvem(st)
        tam, ult = (0 if nuvem else _aloc(st)), max(st.st_mtime, st.st_atime)
    mot = zona_vermelha(path)
    return {"no": no_de(path, usr), "nome": nome, "tipo": "pasta" if d else "arquivo", "bytes": tam, "nuvem": nuvem,
            "dias": int((agora - ult) / 86400) if ult else None, "zona": "vermelha" if mot else "", "motivo": mot or "",
            "previa": None if d else tipo_previa(path), "pode_abrir": pode_abrir(path), "pode_marcar": not mot, "credencial": e_credencial(path)}


def explorar(nid=None, item=None, limite=1500):
    """Conteúdo de uma pasta (ou, sem nó, as pastas de cada usuário), maiores primeiro."""
    agora = time.time()
    if item:
        it = ITENS.get(int(item))
        if not it:
            raise ValueError("Item não existe mais; faça a varredura de novo.")
        nid = no_de(it["path"], it.get("usuario"))
    if not nid:
        por_usr = (RES.get("cockpit") or {}).get("por_usuario") or {}
        out, pend = [], []
        for usr, h in homes():
            t = _TAM.get(_norm(h))
            tam = t[0] if t else por_usr.get(usr)
            if tam is None:
                pend.append(h)
            out.append({"no": no_de(h, usr), "nome": usr, "tipo": "pasta", "bytes": tam, "nuvem": False, "dias": None, "zona": "", "motivo": "",
                        "previa": None, "pode_abrir": True, "pode_marcar": False, "credencial": False, "raiz": True})
        if pend:
            _medir_fundo(pend)
        return {"no": 0, "path": "", "migalhas": [], "filhos": out, "total": len(out), "medindo": bool(pend) and MEDIR["ativo"], "sem_acesso": list(SEM_ACESSO)}
    p = caminho_no(nid)
    usr, h = dono(p)
    migalhas = [{"no": 0, "nome": "Usuários"}]
    hn = os.path.abspath(h)
    cur = hn
    migalhas.append({"no": no_de(cur, usr), "nome": usr})
    for parte in [x for x in os.path.relpath(os.path.abspath(p), hn).replace("\\", "/").split("/") if x not in ("", ".")]:
        cur = os.path.join(cur, parte)
        migalhas.append({"no": no_de(cur, usr), "nome": parte})
    if not os.path.isdir(p):
        st = os.lstat(p)
        return {"no": int(nid), "path": p, "migalhas": migalhas, "filhos": [], "total": 0, "medindo": False, "arquivo": _info_filho(p, os.path.basename(p), st, False, usr, agora, [])}
    filhos, pend = [], []
    try:
        with os.scandir(p) as it:
            for e in it:
                try:
                    if e.is_symlink():
                        continue
                    d = e.is_dir(follow_symlinks=False)
                    st = e.stat(follow_symlinks=False)
                except OSError:
                    continue
                filhos.append(_info_filho(e.path, e.name, st, d, usr, agora, pend))
    except PermissionError:
        raise ValueError("Sem permissão para abrir esta pasta (rode como administrador; no Mac, com Acesso Total ao Disco).")
    filhos.sort(key=lambda x: (x["bytes"] is None and x["tipo"] == "pasta", -(x["bytes"] or 0), x["nome"].lower()))
    if pend:
        _medir_fundo(pend)
    return {"no": int(nid), "path": p, "usuario": usr, "zona": "vermelha" if zona_vermelha(p) else "", "migalhas": migalhas,
            "filhos": filhos[:limite], "total": len(filhos), "medindo": bool(pend) and MEDIR["ativo"], "sem_acesso": list(SEM_ACESSO)}


def marcar(nid):
    """Põe um arquivo/pasta achado ao explorar na lista de ações (âmbar). Devolve o id do item."""
    p = caminho_no(nid)
    mot = zona_vermelha(p)
    if mot:
        raise ValueError("Bloqueado (%s)." % mot)
    k = _norm(p)
    for it in ITENS.values():
        if _norm(it["path"]) == k:
            return it["id"]
    usr = NOS[int(nid)]["usuario"]
    if os.path.isdir(p):
        b, n, ult = tamanho_dir(p, None, set())
        it = {"tipo": "pasta"}
    else:
        st = os.lstat(p)
        b, n, ult = _aloc(st), 1, max(st.st_mtime, st.st_atime)
        it = {"tipo": "arquivo", "logico": st.st_size}
    it.update({"path": p, "zona": "ambar", "cat": "Escolhido pelo técnico", "titulo": os.path.basename(p), "motivo": "Marcado por você ao explorar.",
               "bytes": b, "arquivos": n, "ultimo_uso": ult, "pre": False, "usuario": usr, "escolhido": True})
    with LOCK:
        _add(it)
    return it["id"]


# ----------------------------------------------------------------------------------------------
# lixeira
# ----------------------------------------------------------------------------------------------
def _mount_point(p):
    p = os.path.abspath(p)
    while not os.path.ismount(p):
        n = os.path.dirname(p)
        if n == p:
            break
        p = n
    return p


def _unico(dirp, nome):
    base, ext = os.path.splitext(nome)
    cand, i = nome, 1
    while os.path.exists(os.path.join(dirp, cand)):
        i += 1
        cand = "%s %d%s" % (base, i, ext)
    return cand


def _lixeira_linux(path):
    """Lixeira do DONO do arquivo (rodando com sudo, cada usuário recebe na própria lixeira)."""
    h = dono(path)[1] or home()
    try:
        st_h = os.stat(h)
    except OSError:
        st_h = None
    uid = st_h.st_uid if st_h else os.getuid()
    xdg = os.environ.get("XDG_DATA_HOME") if _norm(h) == _norm(home()) else None
    base = os.path.join(xdg or os.path.join(h, ".local", "share"), "Trash")
    try:
        mesmo = os.stat(path).st_dev == os.stat(h).st_dev
    except OSError:
        mesmo = True
    if not mesmo:
        base = os.path.join(_mount_point(path), ".Trash-%d" % uid)
    fdir, idir = os.path.join(base, "files"), os.path.join(base, "info")
    novos = [d for d in (os.path.dirname(base), base, fdir, idir) if not os.path.isdir(d)]
    os.makedirs(fdir, exist_ok=True)
    os.makedirs(idir, exist_ok=True)
    nome = _unico(fdir, os.path.basename(path))
    info = os.path.join(idir, nome + ".trashinfo")
    with open(info, "w", encoding="utf-8") as fh:
        fh.write("[Trash Info]\nPath=%s\nDeletionDate=%s\n" % (urllib.parse.quote(os.path.abspath(path)), datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")))
    if st_h and hasattr(os, "geteuid") and os.geteuid() == 0:
        for d in novos + [info]:  # criados como root: devolve ao dono, senão ele não consegue esvaziar
            try:
                os.chown(d, st_h.st_uid, st_h.st_gid)
            except OSError:
                pass
    destino = os.path.join(fdir, nome)
    try:
        os.rename(path, destino)
    except OSError:
        shutil.move(path, destino)
    return destino


def _lixeira_mac(path):
    t = os.path.join(dono(path)[1] or home(), ".Trash")  # lixeira do dono do arquivo
    try:
        if os.stat(path).st_dev == os.stat(t).st_dev:
            destino = os.path.join(t, _unico(t, os.path.basename(path)))
            os.rename(path, destino)
            return destino
    except OSError:
        pass
    r = subprocess.run(["osascript", "-e", 'tell application "Finder" to delete POSIX file "%s"' % os.path.abspath(path).replace("\\", "\\\\").replace('"', '\\"')], capture_output=True, timeout=120)
    if r.returncode != 0 or os.path.exists(path):
        raise OSError("O Finder não conseguiu mover para a Lixeira: " + (r.stderr or b"").decode("utf-8", "replace").strip()[:160])
    return "Lixeira"


def _lixeira_win_lote(paths):
    """Envia vários itens à Lixeira num único PowerShell. Retorna {path: erro|None}."""
    import tempfile
    lst = tempfile.NamedTemporaryFile("w", delete=False, suffix=".txt", encoding="utf-8")
    lst.write("\n".join(paths))
    lst.close()
    script = ("Add-Type -AssemblyName Microsoft.VisualBasic; Get-Content -LiteralPath '%s' -Encoding UTF8 | ForEach-Object { $p=$_; try { "
              "if (Test-Path -LiteralPath $p -PathType Container) { [Microsoft.VisualBasic.FileIO.FileSystem]::DeleteDirectory($p,'OnlyErrorDialogs','SendToRecycleBin') } "
              "else { [Microsoft.VisualBasic.FileIO.FileSystem]::DeleteFile($p,'OnlyErrorDialogs','SendToRecycleBin') }; 'OK|'+$p } catch { 'ERR|'+$p+'|'+$_.Exception.Message } }" % lst.name.replace("'", "''"))
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script], capture_output=True, timeout=1800, creationflags=0x08000000)
        out = (r.stdout or b"").decode("utf-8", "replace").splitlines()
    finally:
        try:
            os.remove(lst.name)
        except OSError:
            pass
    res = {p: "Não confirmado pelo Windows" for p in paths}
    for ln in out:
        if ln.startswith("OK|"):
            res[ln[3:]] = None
        elif ln.startswith("ERR|"):
            pp = ln.split("|", 2)
            if len(pp) == 3:
                res[pp[1]] = pp[2]
    return res


def _para_lixeira(path):
    if IS_MAC:
        return _lixeira_mac(path)
    return _lixeira_linux(path)


def _remover_definitivo(path):
    if os.path.isdir(path) and not os.path.islink(path):
        shutil.rmtree(path)
    else:
        os.remove(path)


def esvaziar_lixeira():
    """Esvazia a Lixeira do usuário (ação separada e confirmada na tela)."""
    antes = 0
    if IS_WIN:
        subprocess.run(["powershell", "-NoProfile", "-Command", "Clear-RecycleBin -Force -ErrorAction SilentlyContinue"], capture_output=True, timeout=600, creationflags=0x08000000)
        return {"ok": True}
    if IS_MAC:
        t = os.path.join(home(), ".Trash")
        try:
            antes = sum(tamanho_dir(os.path.join(t, n))[0] if os.path.isdir(os.path.join(t, n)) else os.path.getsize(os.path.join(t, n)) for n in os.listdir(t))
        except OSError:
            pass
        subprocess.run(["osascript", "-e", 'tell application "Finder" to empty the trash'], capture_output=True, timeout=600)
        return {"ok": True, "bytes": antes}
    base = os.path.join(os.environ.get("XDG_DATA_HOME") or os.path.join(home(), ".local", "share"), "Trash")
    for sub in ("files", "info"):
        d = os.path.join(base, sub)
        if os.path.isdir(d):
            for n in os.listdir(d):
                p = os.path.join(d, n)
                if sub == "files":
                    antes += tamanho_dir(p)[0] if os.path.isdir(p) else os.path.getsize(p)
                try:
                    _remover_definitivo(p)
                except OSError:
                    pass
    return {"ok": True, "bytes": antes}


# ----------------------------------------------------------------------------------------------
# ações: limpar e offload
# ----------------------------------------------------------------------------------------------
def _selecionar(ids, confirma_orfaos=True):
    itens = []
    for i in ids:
        it = ITENS.get(int(i))
        if not it:
            raise ValueError("Item %s não existe mais; faça a varredura de novo." % i)
        if it["zona"] == "vermelha":
            raise ValueError("Zona vermelha: bloqueado.")
        mot = zona_vermelha(it["path"])
        if mot:
            raise ValueError("Bloqueado (%s): %s" % (mot, it["path"]))
        if not os.path.lexists(it["path"]):
            raise ValueError("Já não existe: %s" % it["path"])
        itens.append(it)
    if not itens:
        raise ValueError("Nada selecionado.")
    if not confirma_orfaos and any(i.get("orfao") for i in itens):
        raise ValueError("ORFAOS")
    return itens


def _acao_iniciar(tipo, itens):
    with LOCK:
        if ST["acao"]["rodando"] or ST["fase"] == "varrendo":
            raise ValueError("Há outra operação em andamento.")
        ST["acao"] = {"tipo": tipo, "feito": 0, "total": len(itens), "bytes_feito": 0, "bytes_total": sum(i["bytes"] for i in itens), "atual": "", "erros": [], "resultado": None, "rodando": True}
    CANCEL.clear()


def limpar(ids, definitivo=False, depois=None, confirma_orfaos=False):
    itens = _selecionar(ids, confirma_orfaos)
    _acao_iniciar("limpar", itens)
    threading.Thread(target=_limpar_thread, args=(itens, bool(definitivo), depois), daemon=True).start()


def _limpar_thread(itens, definitivo, depois):
    a = ST["acao"]
    ok = nlixo = 0
    b_lixo = b_def = 0
    try:
        if IS_WIN and not definitivo:
            res = _lixeira_win_lote([i["path"] for i in itens])
            for it in itens:
                e = res.get(it["path"])
                a["feito"] += 1
                if e:
                    a["erros"].append("%s: %s" % (it["path"], e))
                else:
                    ok += 1
                    b_lixo += it["bytes"]
                    ITENS.pop(it["id"], None)
        else:
            for it in itens:
                if CANCEL.is_set():
                    break
                a["atual"] = it["path"]
                try:
                    if definitivo:
                        _remover_definitivo(it["path"])
                        b_def += it["bytes"]
                    else:
                        _para_lixeira(it["path"])
                        b_lixo += it["bytes"]
                    ok += 1
                    ITENS.pop(it["id"], None)
                except Exception as e:
                    a["erros"].append("%s: %s" % (it["path"], e))
                a["feito"] += 1
                a["bytes_feito"] += it["bytes"]
        a["resultado"] = {"itens": ok, "falhas": len(a["erros"]), "bytes_lixeira": b_lixo, "bytes_removidos": b_def, "modo": "definitivo" if definitivo else "lixeira"}
    except Exception as e:
        a["erros"].append("%s: %s" % (type(e).__name__, e))
        a["resultado"] = {"itens": ok, "falhas": len(a["erros"]), "bytes_lixeira": b_lixo, "bytes_removidos": b_def, "modo": "definitivo" if definitivo else "lixeira"}
    finally:
        a["rodando"] = False
        if depois:
            try:
                depois(a["resultado"])
            except Exception:
                pass


def sha256_arquivo(p, cancel=None):
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        while True:
            b = fh.read(CHUNK)
            if not b:
                break
            h.update(b)
            if cancel and cancel.is_set():
                raise InterruptedError("cancelado")
    return h.hexdigest()


def _copiar_verificado(src, dst, cancel):
    """Copia com hash durante a leitura, relê o destino e confere. Retorna hash."""
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    tmp = dst + ".ddpart"
    h = hashlib.sha256()
    try:
        with open(src, "rb") as a, open(tmp, "wb") as b:
            while True:
                buf = a.read(CHUNK)
                if not buf:
                    break
                h.update(buf)
                b.write(buf)
                if cancel.is_set():
                    raise InterruptedError("cancelado")
            b.flush()
            os.fsync(b.fileno())
        try:
            shutil.copystat(src, tmp)
        except OSError:
            pass
        if sha256_arquivo(tmp, cancel) != h.hexdigest():
            raise IOError("A cópia não confere com o original (hash diferente).")
        os.replace(tmp, dst)
        return h.hexdigest()
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def preflight_offload(ids, dest, confirma_orfaos=False):
    itens = _selecionar(ids, confirma_orfaos)
    dest = os.path.abspath(os.path.expanduser(dest or ""))
    erros = []
    if not dest or not os.path.isdir(dest):
        erros.append("Escolha uma pasta de destino que exista.")
    else:
        try:
            t = os.path.join(dest, ".dd_teste_%d" % os.getpid())
            with open(t, "w") as fh:
                fh.write("x")
            os.remove(t)
        except OSError:
            erros.append("Não consigo gravar nesse destino (somente leitura ou sem permissão).")
        precisa = sum(i.get("logico") or tamanho_logico(i["path"]) for i in itens)
        livre = shutil.disk_usage(dest).free
        if livre < precisa * 1.02 + 50 * 1024 * 1024:
            erros.append("Não cabe: precisa de %s e o destino tem %s livres." % (fmt(precisa), fmt(livre)))
        pid = H.get("physical_id")
        if pid and not os.environ.get("DD_TEST_MESMO_DISCO"):
            try:
                if pid(dest) and pid(dest) == pid(home()):
                    erros.append("O destino está no MESMO disco do computador. Escolha um disco externo, senão não há ganho de espaço nem segurança.")
            except Exception:
                pass
        fs = (H.get("fs_type") or (lambda p: ""))(dest) or ""
        if fs.lower() in ("vfat", "fat32", "msdos", "fat") and any(i["bytes"] >= 4 * 1024 ** 3 for i in itens):
            erros.append("O destino é FAT32 e há item com mais de 4 GB.")
    return {"ok": not erros, "erros": erros, "bytes": sum(i["bytes"] for i in itens), "itens": len(itens)}


def offload(ids, dest, definitivo=False, depois=None, confirma_orfaos=False):
    pf = preflight_offload(ids, dest, confirma_orfaos)
    if not pf["ok"]:
        raise ValueError(" ".join(pf["erros"]))
    itens = _selecionar(ids, confirma_orfaos)
    _acao_iniciar("offload", itens)
    threading.Thread(target=_offload_thread, args=(itens, os.path.abspath(os.path.expanduser(dest)), bool(definitivo), depois), daemon=True).start()


def _rel_home(p):
    """Caminho no destino do offload: <usuário>/<caminho dentro da pasta dele> (usuários não se misturam)."""
    usr, h = dono(p)
    p = os.path.abspath(p)
    if not h:
        return os.path.basename(p)
    return os.path.join(re.sub(r"[^0-9A-Za-z_. -]+", "_", usr or "usuario"), os.path.relpath(p, os.path.abspath(h)))


def _offload_thread(itens, dest, definitivo, depois):
    a = ST["acao"]
    raiz = os.path.join(dest, "Offload_%s_%s" % (re.sub(r"[^0-9A-Za-z_-]+", "_", socket.gethostname()), datetime.date.today().strftime("%Y-%m-%d")))
    manifesto = []
    ok = 0
    b_ok = 0
    try:
        os.makedirs(raiz, exist_ok=True)
        for it in itens:
            if CANCEL.is_set():
                break
            a["atual"] = it["path"]
            rel = _rel_home(it["path"])
            alvo = os.path.join(raiz, rel)
            try:
                arqs = []
                if it["tipo"] == "pasta":
                    for dp, dns, fns in os.walk(it["path"]):
                        dns[:] = [d for d in dns if not os.path.islink(os.path.join(dp, d))]
                        for fn in fns:
                            fp = os.path.join(dp, fn)
                            if not os.path.islink(fp):
                                arqs.append(fp)
                    os.makedirs(alvo, exist_ok=True)
                else:
                    arqs = [it["path"]]
                feitos = []
                for fp in arqs:
                    sub = os.path.relpath(fp, it["path"]) if it["tipo"] == "pasta" else None
                    dst = os.path.join(alvo, sub) if sub else alvo
                    hh = _copiar_verificado(fp, dst, CANCEL)
                    feitos.append({"origem": fp, "destino": dst, "sha256": hh, "bytes": os.path.getsize(dst)})
                    a["bytes_feito"] += feitos[-1]["bytes"]
                # só remove o original depois de TUDO verificado
                if definitivo:
                    _remover_definitivo(it["path"])
                elif IS_WIN:
                    r = _lixeira_win_lote([it["path"]]).get(it["path"])
                    if r:
                        raise OSError(r)
                else:
                    _para_lixeira(it["path"])
                manifesto.append({"item": it["path"], "destino": alvo, "arquivos": feitos, "quando": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "original": "apagado" if definitivo else "na Lixeira"})
                ok += 1
                b_ok += it["bytes"]
                ITENS.pop(it["id"], None)
            except InterruptedError:
                a["erros"].append("Cancelado em: " + it["path"])
                break
            except Exception as e:
                a["erros"].append("%s: %s (o original foi mantido)" % (it["path"], e))
            a["feito"] += 1
        if manifesto:
            mp = os.path.join(raiz, "offload.json")
            antigo = []
            try:
                antigo = json.load(open(mp, encoding="utf-8"))
            except (OSError, ValueError):
                pass
            with open(mp, "w", encoding="utf-8") as fh:
                json.dump(antigo + manifesto, fh, ensure_ascii=False, indent=1)
        a["resultado"] = {"itens": ok, "falhas": len(a["erros"]), "bytes_movidos": b_ok, "destino": raiz, "modo": "definitivo" if definitivo else "lixeira"}
    except Exception as e:
        a["erros"].append("%s: %s" % (type(e).__name__, e))
        a["resultado"] = {"itens": ok, "falhas": len(a["erros"]), "bytes_movidos": b_ok, "destino": raiz, "modo": "definitivo" if definitivo else "lixeira"}
    finally:
        a["rodando"] = False
        if depois:
            try:
                depois(a["resultado"])
            except Exception:
                pass
