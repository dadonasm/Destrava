# -*- coding: utf-8 -*-
"""BKP Pro - Dados: varredura de espaço, limpeza segura e offload verificado (SHA-256).

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
import urllib.parse

IS_WIN = os.name == "nt"
IS_MAC = sys.platform == "darwin"
HOME = os.path.expanduser("~")
H = {"physical_id": None, "fs_type": None, "user_home": None}
LOCK = threading.Lock()
CHUNK = 4 * 1024 * 1024


def set_helpers(**kw):
    H.update(kw)


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


def _repetido(st):
    if getattr(st, "st_nlink", 1) > 1:
        k = (st.st_dev, st.st_ino)
        if k in _HL:
            return True
        _HL.add(k)
    return False


# ----------------------------------------------------------------------------------------------
# zona vermelha (bloqueio total)
# ----------------------------------------------------------------------------------------------
_VERM_SEG = {".ssh", ".gnupg", ".aws", ".azure", ".kube", ".password-store", "keychains", ".git", "credentials", "wallets"}
_VERM_PARTES = ("library/keychains", "library/mail", "library/messages", "library/safari", "library/application support/addressbook", "library/application support/mobilesync",
                "library/containers/com.apple", "library/group containers", ".config/gcloud", "appdata/roaming/microsoft/credentials", "appdata/local/microsoft/credentials",
                "appdata/roaming/microsoft/protect", ".local/share/keyrings", "library/accounts", "library/cookies", "library/preferences")
_VERM_EXT = {".pem", ".key", ".p12", ".pfx", ".kdbx", ".gpg", ".keychain", ".keychain-db", ".ppk"}
_VERM_BIBLIO = (".photoslibrary", ".fcpbundle", ".imovielibrary", ".tvlibrary", ".musiclibrary", ".lrlibrary", ".app")


def _norm(p):
    return os.path.normcase(os.path.abspath(p)).replace("\\", "/")


def zona_vermelha(path):
    """Motivo do bloqueio (str) ou None se pode ser considerado."""
    h = _norm(home())
    p = _norm(path)
    if os.path.islink(path):
        return "atalho/link simbólico: não seguimos"
    if p == h or not (p == h or p.startswith(h + "/")):
        return "fora da sua pasta de usuário"
    rel = p[len(h) + 1:]
    if rel in ("desktop", "documents", "downloads", "pictures", "movies", "music", "videos", "library", "appdata", "área de trabalho", "documentos", "imagens", "vídeos", "música"):
        return "pasta principal do usuário (não removemos a pasta inteira)"
    segs = set(rel.split("/"))
    if segs & _VERM_SEG:
        return "credenciais, chaves ou repositório ativo"
    for parte in _VERM_PARTES:
        if rel == parte or rel.startswith(parte + "/"):
            return "dados de sistema, contas ou credenciais"
    ext = os.path.splitext(p)[1]
    if ext in _VERM_EXT:
        return "arquivo de chave/credencial"
    if rel.endswith(_VERM_BIBLIO) or any(("/" + b + "/") in ("/" + rel + "/") for b in _VERM_BIBLIO):
        return "biblioteca de um aplicativo (use o próprio aplicativo para gerenciar)"
    if "/login data" in p or p.endswith("/cookies") or p.endswith("/key4.db") or p.endswith("/logins.json"):
        return "senhas/cookies de navegador"
    return None


# ----------------------------------------------------------------------------------------------
# alvos conhecidos (zona verde): caches que o sistema/app recria
# ----------------------------------------------------------------------------------------------
def _alvos_verdes():
    h = home()
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
        la = os.environ.get("LOCALAPPDATA") or os.path.join(h, "AppData", "Local")
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


def _pastas_capcut():
    h = home()
    bases = []
    if IS_MAC:
        bases += [os.path.join(h, "Movies/CapCut/User Data/Projects")]
    elif IS_WIN:
        la = os.environ.get("LOCALAPPDATA") or os.path.join(h, "AppData", "Local")
        bases += [os.path.join(la, "CapCut", "User Data", "Projects")]
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


def _orfaos(agora, idle_dias, pular):
    h = home()
    if IS_MAC:
        bases = [os.path.join(h, "Library/Application Support")]
    elif IS_WIN:
        bases = [os.environ.get("APPDATA") or os.path.join(h, "AppData", "Roaming"), os.environ.get("LOCALAPPDATA") or os.path.join(h, "AppData", "Local")]
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


def tamanho_dir(path, cancel=None):
    """(bytes, arquivos, ultimo_uso_epoch) de uma pasta, sem seguir links."""
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
                            if _nuvem(st) or _repetido(st):
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


def _novo_id():
    return len(ITENS) + 1


def _add(it):
    it["id"] = _novo_id()
    ITENS[it["id"]] = it
    return it


def _varrer(idle_dias, min_mb):
    try:
        agora = time.time()
        h = home()
        ST["acesso_total"] = acesso_total_mac()
        min_b = min_mb * 1000 * 1000 if IS_MAC else min_mb * 1024 * 1024
        _HL.clear()
        ST["nuvem_n"] = 0
        ST["nuvem_bytes"] = 0
        try:
            dev_home = os.stat(h).st_dev
        except OSError:
            dev_home = None
        alvos = _alvos_verdes()
        pular = set()
        cat_bytes = {}
        verde_bytes = 0

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

        # 2) projetos CapCut parados (âmbar)
        ST["atual"] = "Procurando projetos do CapCut"
        for q in _pastas_capcut():
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
        _orfaos(agora, idle_dias, pular)
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
        RES["cockpit"] = {"total": total, "livre": livre, "usado": usado, "midias": midia, "documentos": docs, "apps": apps, "limpavel": limpavel, "parado": ambar,
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


def resultado(zona=None, cat=None, q="", offset=0, limit=200):
    itens = [i for i in ITENS.values() if (not zona or i["zona"] == zona) and (not cat or i["cat"] == cat) and (not q or q.lower() in i["path"].lower())]
    itens.sort(key=lambda i: -i["bytes"])
    cats = {}
    for i in ITENS.values():
        c = cats.setdefault((i["zona"], i["cat"]), {"zona": i["zona"], "cat": i["cat"], "n": 0, "bytes": 0})
        c["n"] += 1
        c["bytes"] += i["bytes"]
    agora = time.time()
    rows = [{"id": i["id"], "titulo": i["titulo"], "path": i["path"], "tipo": i["tipo"], "zona": i["zona"], "cat": i["cat"], "motivo": i["motivo"], "bytes": i["bytes"],
             "arquivos": i["arquivos"], "dias": int((agora - i["ultimo_uso"]) / 86400) if i["ultimo_uso"] else None, "pre": i["pre"], "orfao": bool(i.get("orfao"))} for i in itens[offset:offset + limit]]
    return {"rows": rows, "total": len(itens), "cats": sorted(cats.values(), key=lambda c: (-{"verde": 3, "ambar": 2, "vermelha": 1}[c["zona"]], -c["bytes"]))}


def cancelar():
    CANCEL.set()


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
    h = home()
    uid = os.getuid()
    base = os.path.join(os.environ.get("XDG_DATA_HOME") or os.path.join(h, ".local", "share"), "Trash")
    try:
        mesmo = os.stat(path).st_dev == os.stat(h).st_dev
    except OSError:
        mesmo = True
    if not mesmo:
        base = os.path.join(_mount_point(path), ".Trash-%d" % uid)
    fdir, idir = os.path.join(base, "files"), os.path.join(base, "info")
    os.makedirs(fdir, exist_ok=True)
    os.makedirs(idir, exist_ok=True)
    nome = _unico(fdir, os.path.basename(path))
    with open(os.path.join(idir, nome + ".trashinfo"), "w", encoding="utf-8") as fh:
        fh.write("[Trash Info]\nPath=%s\nDeletionDate=%s\n" % (urllib.parse.quote(os.path.abspath(path)), datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")))
    destino = os.path.join(fdir, nome)
    try:
        os.rename(path, destino)
    except OSError:
        shutil.move(path, destino)
    return destino


def _lixeira_mac(path):
    t = os.path.join(home(), ".Trash")
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
    h = os.path.abspath(home())
    p = os.path.abspath(p)
    return os.path.relpath(p, h) if p.startswith(h) else os.path.basename(p)


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
