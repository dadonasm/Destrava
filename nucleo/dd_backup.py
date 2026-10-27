#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
D&D Backup  -  motor + servidor local (Linux, Windows e macOS)
Somos únicos. Somos diferentes. Somos D&D.

Só usa a biblioteca padrão do Python 3.8+. Nada é apagado, movido ou alterado nas origens: só LÊ.

Uso:
    python3 dd_backup.py                      abre a janela no navegador
    python3 dd_backup.py --verificar PASTA    confere o certificado de um Mapa já gerado (pasta Mapa)
    python3 dd_backup.py --rehash PASTA       relê os arquivos do backup e compara com os hashes do mapa
"""
import argparse
import atexit
import collections
import csv
import datetime
import errno
import hashlib
import json
import os
import platform
import re
import secrets
import shutil
import socket
import struct
import subprocess
import sys
import threading
import time
import traceback
import unicodedata
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

# o Python portátil do Windows (embeddable, com arquivo ._pth) não põe a pasta do script no caminho de importação:
# sem isto ficha, termo, dados e atualizador não carregariam
if os.path.dirname(os.path.abspath(__file__)) not in sys.path:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

VERSION = "3.7"
BUILD = "2026-10-27.1"  # igual ao BUILD do app.html: se forem diferentes, o pendrive tem arquivos de versões misturadas
import classe as CLS  # noqa: E402  (tipos de arquivo: a mesma tabela do Gerenciamento)
import disco  # noqa: E402  (conferência lendo do disco, não da memória)
import mapa as MAPA  # noqa: E402
import perfil as PERFIL  # noqa: E402
import programas as PROG  # noqa: E402
try:
    import ficha as FICHA
except Exception:  # o backup continua funcionando mesmo sem a ficha
    FICHA = None
try:
    import termo as TERMO
except Exception:
    TERMO = None
try:
    import dados as DADOS
except Exception:
    DADOS = None
try:
    import atualizador as ATUAL
except Exception:
    ATUAL = None
REC = {"bytes": 0}  # espaço liberado nesta sessão (para o certificado)
IS_WIN = os.name == "nt"
HERE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(HERE, "web")
DADOS_DIR = [HERE]  # onde ficam maquinas/ e consentimentos.log (ao lado do programa, ou --dados)
SERVIDOR = {"con": None, "cache_proprio": False}  # modo servidor (--servidor): conexao.Conexao com o servidor da loja
CHUNK = 4 * 1024 * 1024
MESES = ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"]

# ----------------------------------------------------------------------------------------------
# Regras de classificação
# ----------------------------------------------------------------------------------------------
# a tabela de tipos é a mesma do Gerenciamento de dados (classe.py); aqui só as categorias pessoais do backup
CATS_PESSOAIS = ("Fotos", "Videos", "Audios", "Documentos", "Projetos", "Email_Contatos", "Contas_Senhas")
EXT2CAT = {x: CLS.CLASSES[CLS.POR_EXT[x]]["backup"] for x in CLS.POR_EXT if CLS.CLASSES[CLS.POR_EXT[x]]["backup"] in CATS_PESSOAIS}
ARCH = set(CLS.COMPACTADOS)
TIPO_EXT = CLS.TIPO_EXT  # coluna "Tipo" da lista (a mesma tabela do Gerenciamento)


def nome_de(disp):
    return re.split(r"[\\/]", disp)[-1]


tipo_de = CLS.tipo_de
IGN_EXT = set(".exe .dll .sys .tmp .temp .log .ini .lnk .url .msi .msp .cab .cat .mui .drv .ocx .cpl .scr .bin .obj .pyc .class "
              ".etl .dmp .cache .ost .crdownload .part .ddpart .so .lock .swp .desktop".split())
IGN_NAME_RE = CLS.SISTEMA_NOME
WA_RE = re.compile(r"(^msgstore.*\.db(\.crypt\d+)?$)|(\.crypt\d+$)", re.I)

IGN_ANY = {"__pycache__", "$recycle.bin", "system volume information", ".trash", "lost+found"}
IGN_WIN_ROOT = {"windows", "program files", "program files (x86)", "programdata", "recovery", "config.msi", "msocache", "perflogs", "intel",
                "amd", "nvidia", "documents and settings", "boot", "efi", "users"}
IGN_WIN_USERS = {"default", "default user", "all users", "public documents"}
SILENT_JUNCTIONS = {"application data", "cookies", "local settings", "my documents", "nethood", "printhood", "recent", "sendto", "start menu", "templates"}
CLOUD_ATTRS = 0x1000 | 0x40000 | 0x400000  # OFFLINE | RECALL_ON_OPEN | RECALL_ON_DATA_ACCESS
GOOD_FS = {"ntfs", "ntfs3", "fuseblk", "vfat", "exfat", "ext2", "ext3", "ext4", "btrfs", "xfs", "f2fs", "hfsplus", "apfs", "msdos"}
RESERVED = {"con", "prn", "aux", "nul"} | {"com%d" % i for i in range(1, 10)} | {"lpt%d" % i for i in range(1, 10)}
# dados de apps dentro da pasta do usuário (o resto da AppData não é pessoal): (app, caminho, extensões ou None)
APPS_WIN = [("Thunderbird", "AppData/Roaming/Thunderbird/Profiles", None), ("Outlook", "AppData/Local/Microsoft/Outlook", (".pst",)),
            ("Outlook_Assinaturas", "AppData/Roaming/Microsoft/Signatures", None),
            ("Notas_Autoadesivas", "AppData/Local/Packages/Microsoft.MicrosoftStickyNotes_8wekyb3d8bbwe/LocalState", (".sqlite",))]
APPS_LINUX = [("Evolution", ".local/share/evolution", None)]
APP_PULAR = {"cache", "cache2", "startupcache", "crashes", "minidumps", "shader-cache"}
# bancos de dados de sistemas (loja, contabilidade, PDV) em Program Files e ProgramData
DB_EXT = {".fdb", ".gdb", ".fbk", ".gbk", ".mdb", ".accdb", ".dbf", ".sdf", ".mdf", ".ldf", ".bak"}
SIS_PULAR = {"microsoft", "windows", "common files", "google", "mozilla", "mozilla firefox", "mozilla maintenance service", "adobe", "nvidia", "nvidia corporation",
             "intel", "amd", "package cache", "windowsapps", "windows defender", "windows nt", "windows mail", "windows media player", "windows photo viewer",
             "windows portable devices", "windows security", "windowspowershell", "internet explorer", "microsoft office", "microsoft.net", "reference assemblies",
             "msbuild", "dotnet", "uninstall information", "installshield installation information", "realtek", "java", "docker", "packages", "ssh",
             "usoshared", "usoprivate", "softwaredistribution", "regid.1991-06.com.microsoft"}
# o que antes era "ignorado" agora é listado em categorias próprias, desmarcadas: o técnico decide
PROG_EXT = CLS.exts("backup", "Programas")
CONF_EXT = CLS.exts("backup", "Configuracoes")
# pastas que se recriam sozinhas: listadas como puladas, nunca copiadas
CACHE_DIRS = set(CLS.CACHE_DIRS)
WA_PASTA = re.compile(r"(^|[\\/])whatsapp( (images|video|audio|documents|animated gifs|voice notes|stickers|profile photos))?([\\/]|$)", re.I)
WA_NOME = re.compile(r"^whatsapp (image|video|audio|ptt|document)|^(img|vid|aud|ptt|doc|stk)-\d{8}-wa\d{3,5}", re.I)
# ordem de cópia: o mais importante primeiro (se o disco de origem estiver morrendo, o essencial já foi)
PRIORIDADE = ["Documentos", "Email_Contatos", "Contas_Senhas", "Fotos", "Conversas", "Projetos", "Sistemas", "Dados_de_apps", "Navegadores",
              "Videos", "Audios", "Outros", "Ocultos", "Configuracoes", "Programas", "Temporarios", "Extras", "Nuvem"]
# Modo de cópia, escolhido a cada backup: espelho (tudo como estava), ordenado (tipo e data, com raiz no usuário)
# ou misto (espelhado, e o técnico escolhe na Seleção o que vai ordenado). O espelho fica em Pastas_origem/<Usuário>/…
PASTA_ORIGEM, PASTA_ORIGEM_ANTIGA = "Pastas_origem", "Pastas_mae"
LAYOUT_MODOS = ("espelho", "ordenado", "misto")
LAYOUT_NOME = {"espelho": "Espelho", "ordenado": "Ordenado", "misto": "Misto"}
ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


class Cancelled(Exception):
    pass


class Pulado(Exception):
    """O técnico mandou pular o arquivo em que a cópia travou."""


class Busy(Exception):
    pass


# ----------------------------------------------------------------------------------------------
# Utilitários
# ----------------------------------------------------------------------------------------------
def fmt_bytes(n):
    n = float(n or 0)
    for u in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or u == "TB":
            return ("%d %s" % (n, u)) if u == "B" else ("%.2f %s" % (n, u)).replace(".", ",")
        n /= 1024.0


def lp(p):
    """Caminho longo no Windows."""
    if IS_WIN and len(p) >= 240 and not p.startswith("\\\\?\\"):
        return "\\\\?\\" + os.path.abspath(p)
    return p


def e_link(p):
    """Symlink ou junção: no Windows o os.path.islink não pega junção (ex.: "Todos os Usuários", "Documents and Settings")."""
    try:
        if os.path.islink(p) or (hasattr(os.path, "isjunction") and os.path.isjunction(p)):
            return True
        return IS_WIN and bool(getattr(os.lstat(p), "st_file_attributes", 0) & 0x400)
    except OSError:
        return False


def strip_accents(s):
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def safe_seg(s):
    s = ILLEGAL.sub("_", s).rstrip(" .") or "_"
    if s.split(".")[0].lower() in RESERVED:
        s = "_" + s
    if len(s.encode("utf-8")) > 200:
        b, e = os.path.splitext(s)
        s = b[:150] + e[:20]
    return s


def now_iso():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def classify_err(e):
    en = getattr(e, "errno", None)
    we = getattr(e, "winerror", None)
    if isinstance(e, FileNotFoundError):
        return "sumiu", "ERRO: O arquivo sumiu durante o backup (foi apagado ou movido)"
    if we in (32, 33) or en == errno.ETXTBSY:
        return "em_uso", "ERRO: O arquivo está sendo usado por outro processo"
    if isinstance(e, PermissionError) or en in (errno.EACCES, errno.EPERM) or we == 5:
        return "permissao", "ERRO: Acesso negado (sem permissão de leitura)"
    if en == errno.ENOSPC or we in (112, 39):
        return "espaco", "ERRO: Não há espaço suficiente no destino"
    if en == errno.ENAMETOOLONG or we in (206, 3):
        return "caminho_longo", "ERRO: Caminho longo demais (limite do sistema)"
    if en in (errno.EIO, getattr(errno, "EUCLEAN", -1), errno.ENXIO) or we in (23, 1117):
        return "io", "ERRO: Erro de leitura/gravação (I/O) - possível setor defeituoso no dispositivo"
    if en == errno.EROFS:
        return "somente_leitura", "ERRO: Destino somente leitura"
    if en == errno.EINVAL:  # atalho de aplicativo do Windows (WindowsApps\*_Alias.exe): não é um arquivo de verdade
        return "atalho_app", "ERRO: Atalho de aplicativo do Windows (não é um arquivo de verdade)"
    return "outro", "ERRO: %s" % (e,)


# Falha "esperada": arquivo de programa em uso (navegador aberto, serviços do Windows) fora do que é pessoal. Não é perda de dado da pessoa.
MOTIVO_EM_USO = "Em uso por um programa aberto (%s): normal em pastas de programas, não é arquivo pessoal"
NAO_PESSOAIS = {"Dados_de_apps", "Ocultos", "Temporarios", "Programas", "Configuracoes", "Extras"}
CAUSAS_EM_USO = {"permissao", "em_uso", "atalho_app", "pulado"}
APPEXECLINK = 0x8000001B  # reparse dos atalhos de aplicativo (WindowsApps): abrir dá "Invalid argument"


def falha_esperada(it):
    return it.status == "falha" and it.cat in NAO_PESSOAIS and it.cause in CAUSAS_EM_USO


def eh_admin():
    try:
        if IS_WIN:
            import ctypes
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        return hasattr(os, "geteuid") and os.geteuid() == 0
    except Exception:
        return False


PROGRAMAS_PASTA = (("/microsoft/edge/", "Edge (navegador)"), ("/google/chrome/", "Chrome (navegador)"), ("/bravesoftware/", "Brave (navegador)"),
                   ("/mozilla/firefox/", "Firefox (navegador)"), ("/opera software/", "Opera (navegador)"), ("/microsoft/windowsapps/", "Atalhos de aplicativos do Windows"),
                   ("/comms/", "Windows (Comms)"), ("/microsoft/windows/", "Windows"), ("/packages/", "Aplicativos da Microsoft Store"),
                   ("/microsoft/onedrive/", "OneDrive"), ("/microsoft/teams/", "Teams"), ("/whatsapp", "WhatsApp"), ("/spotify/", "Spotify"))


def programa_de(disp):
    """Nome do programa (ou pasta) a que um arquivo pertence, para agrupar as falhas: "Edge (navegador)", "Windows (Comms)"…"""
    p = str(disp).replace("\\", "/")
    low = p.lower()
    for chave, nome in PROGRAMAS_PASTA:
        if chave in low:
            return nome
    m = re.search(r"/appdata/(?:local|roaming|locallow)/([^/]+)/", p, re.I)
    if m:
        return m.group(1)
    partes = [x for x in p.split("/") if x]
    return partes[-2] if len(partes) >= 2 else "Outras pastas"


# ---------------------------- EXIF (data da foto, JPEG) ----------------------------
def _tiff_date(t):
    if len(t) < 8:
        return None
    bo = "<" if t[:2] == b"II" else (">" if t[:2] == b"MM" else None)
    if not bo:
        return None

    def u16(o):
        return struct.unpack(bo + "H", t[o:o + 2])[0]

    def u32(o):
        return struct.unpack(bo + "I", t[o:o + 4])[0]

    def ifd(off):
        res = {}
        try:
            for k in range(u16(off)):
                e = off + 2 + k * 12
                res[u16(e)] = (u16(e + 2), u32(e + 4), e + 8)
        except struct.error:
            pass
        return res

    def ascii_at(ent):
        typ, c, v = ent
        if typ != 2 or c < 19:
            return None
        o = u32(v) if c > 4 else v
        return t[o:o + 19].decode("ascii", "ignore")

    try:
        i0 = ifd(u32(4))
        cand = []
        if 0x8769 in i0:
            ex = ifd(u32(i0[0x8769][2]))
            for tag in (0x9003, 0x9004):
                if tag in ex:
                    cand.append(ascii_at(ex[tag]))
        if 0x0132 in i0:
            cand.append(ascii_at(i0[0x0132]))
    except (struct.error, IndexError):
        return None
    yl = datetime.date.today().year + 1
    for s in cand:
        if s and re.match(r"\d{4}:\d\d:\d\d \d\d:\d\d:\d\d", s):
            y, mo, d = int(s[:4]), int(s[5:7]), int(s[8:10])
            if 1995 <= y <= yl and 1 <= mo <= 12 and 1 <= d <= 31:
                return (y, mo, d)
    return None


def exif_date(path):
    try:
        with open(lp(path), "rb") as f:
            head = f.read(131072)
    except OSError:
        return None
    if head[:2] != b"\xff\xd8":
        return None
    i, n = 2, len(head)
    while i + 4 <= n:
        if head[i] != 0xFF:
            break
        m = head[i + 1]
        if m == 0xFF:
            i += 1
            continue
        if m in (0xD8, 0x01) or 0xD0 <= m <= 0xD7:
            i += 2
            continue
        if m in (0xD9, 0xDA):
            break
        ln = struct.unpack(">H", head[i + 2:i + 4])[0]
        if m == 0xE1 and head[i + 4:i + 10] == b"Exif\x00\x00":
            return _tiff_date(head[i + 10:i + 2 + ln])
        i += 2 + ln
    return None


FNAME_DATE = re.compile(r"(?<![0-9])((?:19|20)[0-9]{2})([01][0-9])([0-3][0-9])(?![0-9])")


def name_date(name):
    m = FNAME_DATE.search(name)
    if not m:
        return None
    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    try:
        dt = datetime.date(y, mo, d)
    except ValueError:
        return None
    if dt <= datetime.date.today() and y >= 1995:
        return (y, mo, d)
    return None


def stat_date(st):
    t = min(st.st_mtime, st.st_ctime) if IS_WIN else st.st_mtime
    try:
        lt = time.localtime(t)
    except (OverflowError, OSError, ValueError):
        return None
    if lt.tm_year < 1995:
        return None
    return (lt.tm_year, lt.tm_mon, lt.tm_mday)


# ----------------------------------------------------------------------------------------------
# Etiquetas por palavra-chave
# ----------------------------------------------------------------------------------------------
DEFAULT_TAGS = """Fiscal: nota, notas, nfe, danfe, imposto, icms, das, darf, xml, contador
Contratos: contrato, contratos, aditivo, distrato, procuracao
Propostas: proposta, propostas, orcamento, orcamentos, cotacao, pedido
Clientes: cliente, clientes, lojista, tecnico
Financeiro: boleto, extrato, fatura, comprovante, pix, recibo, financeiro
Pessoal: rg, cpf, cnh, certidao, passaporte
WhatsApp: whatsapp, re:\\bwa\\d{4}\\b
"""


def load_tag_rules(path):
    try:
        with open(path, encoding="utf-8") as f:
            txt = f.read()
    except OSError:
        txt = DEFAULT_TAGS
    rules = []
    for line in txt.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        tag, kws = line.split(":", 1)
        tag = tag.strip()
        words, multi, rx = set(), [], []
        for k in kws.split(","):
            k = k.strip()
            if not k:
                continue
            if k.lower().startswith("re:"):
                try:
                    rx.append(re.compile(k[3:], re.I))
                except re.error:
                    pass
                continue
            parts = re.findall(r"[a-z0-9]+", strip_accents(k.lower()))
            if len(parts) == 1:
                words.add(parts[0])
            elif parts:
                multi.append(" ".join(parts))
        if tag:
            rules.append((tag, words, multi, rx))
    return rules


def tag_path(rules, text):
    norm = strip_accents(text.lower())
    toks = re.findall(r"[a-z0-9]+", norm)
    words = set(toks)
    joined = " " + " ".join(toks) + " "
    out = []
    for tag, ws, mw, rx in rules:
        if (ws & words) or any((" " + m + " ") in joined for m in mw) or any(r.search(norm) for r in rx):
            out.append(tag)
    return "|".join(out)


# ----------------------------------------------------------------------------------------------
# Discos, montagens e fontes
# ----------------------------------------------------------------------------------------------
def read_mounts():
    res = []
    try:
        with open("/proc/mounts", encoding="utf-8", errors="replace") as f:
            for line in f:
                p = line.split()
                if len(p) >= 4:
                    mp = re.sub(r"\\([0-7]{3})", lambda m: chr(int(m.group(1), 8)), p[1])
                    res.append((p[0], mp, p[2], p[3]))
    except OSError:
        pass
    return res


def mount_of(path):
    path = os.path.abspath(path)
    best = None
    for dev, mp, fs, opts in read_mounts():
        if path == mp or path.startswith(mp.rstrip("/") + "/") or mp == "/":
            if best is None or len(mp) >= len(best[1]):
                best = (dev, mp, fs, opts)
    return best


def parent_disk(dev, depth=0):
    if not dev.startswith("/dev/") or depth > 4:
        return None
    name = os.path.basename(os.path.realpath(dev))
    sysp = "/sys/class/block/" + name
    if not os.path.exists(sysp):
        return None
    if name.startswith("dm-"):
        try:
            sl = os.listdir(sysp + "/slaves")
            if sl:
                return parent_disk("/dev/" + sl[0], depth + 1)
        except OSError:
            return None
    if os.path.exists(sysp + "/partition"):
        return os.path.basename(os.path.dirname(os.path.realpath(sysp)))
    return name


def physical_id(path):
    """Identificador do disco físico (melhor esforço)."""
    try:
        if IS_WIN:
            return "win:" + os.path.splitdrive(os.path.abspath(path))[0].upper()
        m = mount_of(path)
        if m:
            pd = parent_disk(m[0])
            if pd:
                return "disk:" + pd
            return "dev:" + m[0]
    except Exception:
        pass
    try:
        return "st_dev:%s" % os.stat(path).st_dev
    except OSError:
        return None


def fs_type(path):
    if IS_WIN:
        return None
    m = mount_of(path)
    return m[2] if m else None


def disk_usage(path):
    try:
        u = shutil.disk_usage(path)
        return u.total, u.free
    except OSError:
        return 0, 0


IGN_MAC_USERS = {"shared", "guest", "deleted users"}


def mac_usuarios(ud):
    try:
        return sorted(n for n in os.listdir(ud) if not n.startswith(".") and n.lower() not in IGN_MAC_USERS
                      and os.path.isdir(os.path.join(ud, n)) and not e_link(os.path.join(ud, n)))
    except OSError:
        return []


def detect_kind(p):
    try:
        names = {n.lower(): n for n in os.listdir(p)}
    except OSError:
        return "folder", []
    if "windows" in names and ("users" in names or "documents and settings" in names):
        users = []
        try:
            for n in sorted(os.listdir(os.path.join(p, names.get("users", "Users")))):
                up = os.path.join(p, names.get("users", "Users"), n)
                if os.path.isdir(up) and not e_link(up) and n.lower() not in IGN_WIN_USERS and not re.match(r"^defaultuser\d+$", n, re.I):
                    users.append(n)
        except OSError:
            pass
        return "windows", users
    if "users" in names and ("system" in names or "library" in names):  # volume do macOS: os usuários ficam em /Users (antes do teste de Linux, que também tem etc e usr)
        return "mac", mac_usuarios(os.path.join(p, names["users"]))
    if "home" in names and "etc" in names and "usr" in names:
        try:
            hp = os.path.join(p, names["home"])
            return "linux", sorted(n for n in os.listdir(hp) if os.path.isdir(os.path.join(hp, n)) and not e_link(os.path.join(hp, n)))
        except OSError:
            return "linux", []
    return "folder", []


def _dentro(p, pai):
    """p é pai ou está dentro de pai (mesma regra no Windows, sem diferenciar maiúsculas)."""
    a, b = os.path.normcase(os.path.abspath(p)), os.path.normcase(os.path.abspath(pai))
    try:
        return os.path.commonpath([a, b]) == b
    except ValueError:  # discos diferentes no Windows
        return False


def list_sources(para_origem=True):
    """Discos e pastas para escolher. Como origem, some o disco do próprio programa (o pendrive) e a pasta pessoal que já está dentro de um disco listado."""
    out = []
    seen = set()

    def add(path, label, fs=""):
        path = os.path.abspath(path)
        if path in seen or not os.path.isdir(path):
            return
        seen.add(path)
        kind, users = detect_kind(path)
        total, free = disk_usage(path)
        out.append({"path": path, "label": label, "fs": fs, "kind": kind, "users": users, "total": total, "free": free, "letter": ""})

    if IS_WIN:
        try:
            import ctypes
            mask = ctypes.windll.kernel32.GetLogicalDrives()
            for i in range(26):
                if mask & (1 << i):
                    root = "%s:\\" % chr(65 + i)
                    t = ctypes.windll.kernel32.GetDriveTypeW(root)
                    if t in (2, 3):
                        buf = ctypes.create_unicode_buffer(261)
                        fsb = ctypes.create_unicode_buffer(261)
                        ctypes.windll.kernel32.GetVolumeInformationW(root, buf, 261, None, None, None, fsb, 261)
                        add(root, "%s (%s)" % (buf.value or "Disco local", root[:2]), fsb.value)
        except Exception:
            pass
    elif sys.platform == "darwin":
        try:
            for n in sorted(os.listdir("/Volumes")):
                add(os.path.join("/Volumes", n), n)
        except OSError:
            pass
    else:
        for dev, mp, fs, opts in read_mounts():
            if fs not in GOOD_FS or mp in ("/", "/boot", "/boot/efi") or mp.startswith(("/snap", "/var/snap", "/sys", "/proc", "/dev", "/run/user")):
                continue
            add(mp, os.path.basename(mp) or mp, fs + (" (somente leitura)" if opts.split(",")[0] == "ro" else ""))
    home = os.path.expanduser("~")
    if not (para_origem and any(_dentro(home, s["path"]) for s in out)):
        add(home, "Pasta pessoal (%s)" % os.path.basename(home))
    if para_origem:
        out = [s for s in out if not (_dentro(HERE, s["path"]) and os.path.ismount(s["path"])) or s["kind"] in ("windows", "linux", "mac")]  # o pendrive do programa
    # Windows: sugere letras
    letters = iter("CDEFGHIJ")
    for s in out:
        if s["kind"] == "windows":
            s["letter"] = (os.path.splitdrive(s["path"])[0][:1] if IS_WIN and os.path.splitdrive(s["path"])[0] else next(letters))
    return out


def roots_for_browse():
    res = []
    if IS_WIN:
        for s in list_sources(para_origem=False):
            res.append({"name": s["label"], "path": s["path"]})
    else:
        for p in ("/media", "/mnt", "/run/media", os.path.expanduser("~")):
            if os.path.isdir(p):
                res.append({"name": p, "path": p})
        if sys.platform == "darwin" and os.path.isdir("/Volumes"):
            res.append({"name": "/Volumes", "path": "/Volumes"})
    return res


# ----------------------------------------------------------------------------------------------
# Item
# ----------------------------------------------------------------------------------------------
class Item(object):
    __slots__ = ("raiz", "ctx", "local0", "rel0", "src", "disp", "size", "mtime", "local", "cat", "act", "motivo", "date", "tags", "inc", "rel",
                 "status", "err", "cause", "sha", "ver", "nuvem", "inc0", "quem", "pk", "eleg", "lay")

    def __init__(self):
        self.raiz, self.ctx, self.local0, self.rel0 = "", "", None, None
        self.inc0 = None
        self.status = None
        self.err = ""
        self.cause = ""
        self.sha = ""
        self.ver = False
        self.inc = False
        self.nuvem = False
        self.quem = ""  # usuário/local de origem (antes de o WhatsApp virar "WhatsApp (Ana)")
        self.pk = ""  # pasta de origem a partir do usuário: "Ana/Documents/motorista/cnh"
        self.eleg = False  # entra na escolha espelhar/ordenar (arquivos pessoais; apps, ocultos e sistemas guardam o caminho sempre)
        self.lay = ""  # espelhar | ordenar escolhido no Misto (vazio: vale o modo)


def classify_file(name, size, nuvem):
    """(categoria, ação, motivo, marcado). Tudo é listado; só vem marcado o que é claramente pessoal."""
    low = name.lower()
    ext = os.path.splitext(low)[1]
    if IGN_NAME_RE.match(name):
        return "Temporarios", "ignorar", "Arquivo do sistema em uso (recriado sozinho)", False
    if nuvem:
        tipo = EXT2CAT.get(ext, "Outros")
        return "Nuvem", "copiar", "Só na nuvem (%s): se marcar, baixa e copia" % tipo, False
    if low.startswith("~$") or (ext in IGN_EXT and ext not in PROG_EXT and ext not in CONF_EXT):
        return "Temporarios", "copiar", "Temporário/sistema (recriado sozinho): só se precisar", False
    if ext in PROG_EXT:
        return "Programas", "copiar", "Programa ou instalador: marque se o cliente quiser guardar", False
    if ext in CONF_EXT:
        return "Configuracoes", "copiar", "Configuração, atalho ou registro de programa", False
    if size == 0:
        return "Outros", "copiar", "Arquivo vazio (0 bytes)", False
    if WA_RE.search(name):
        return "Conversas", "copiar", "Backup de conversas (WhatsApp)", True
    if ext in EXT2CAT:
        return EXT2CAT[ext], "copiar", "Arquivo pessoal (%s)" % EXT2CAT[ext], True
    if ext in ARCH:
        return "Outros", "copiar", "Arquivo compactado", True
    return "Outros", "revisar", "Tipo não reconhecido: copiado por segurança, confira", True


def eh_whatsapp(disp, name):
    return bool(WA_RE.search(name) or WA_NOME.search(name) or WA_PASTA.search(os.path.dirname(disp.replace("\\", "/"))))


def _dentro_it(it):
    return it.disp[len(it.raiz):].lstrip("\\/") if it.raiz and it.disp.startswith(it.raiz) else nome_de(it.disp)


def pasta_chave(local, dentro):
    """Pasta de origem a partir do usuário (ou do disco/pasta de origem): o ponto de partida da navegação e do espelho."""
    partes = [x for x in re.split(r"[\\/]", dentro) if x][:-1]
    return "/".join([x for x in (local or "").split("/") if x] + partes)


def rel_espelho(it):
    """Destino no espelho: Pastas_origem/<Usuário>/<caminho como estava a partir da pasta do usuário>."""
    loc = "/".join(safe_seg(x) for x in (it.quem or it.local0 or "").split("/") if x)
    dentro = "/".join(safe_seg(x) for x in re.split(r"[\\/]", _dentro_it(it)) if x)
    return "%s/%s/%s" % (PASTA_ORIGEM, loc, dentro)


def build_rel(local, cat, date, name, ext):
    loc = "/".join(safe_seg(x) for x in local.split("/"))
    if date:
        y, mo, _ = date
        ano, mes = str(y), "%02d - %s" % (mo, MESES[mo - 1])
    else:
        ano, mes = "Sem_data", "Sem_data"
    nm = safe_seg(name)
    if cat == "Outros":
        e = re.sub(r"[^0-9A-Za-z_-]", "_", ext.lstrip(".")).upper() or "sem_extensao"
        return "%s/Outros/%s/%s/%s/%s" % (loc, e, ano, mes, nm)
    return "%s/%s/%s/%s/%s" % (loc, cat, ano, mes, nm)


# ----------------------------------------------------------------------------------------------
# Aplicação / estado
# ----------------------------------------------------------------------------------------------
def _medir_pasta(raiz, parar, ate):
    """(bytes, arquivos, completo) de uma pasta, sem seguir atalhos/junções. O tamanho vem do próprio DirEntry (rápido no Windows)."""
    tot = n = 0
    pilha = [raiz]
    visto = 0
    while pilha:
        if parar.is_set() or time.time() > ate:
            return tot, n, False
        d = pilha.pop()
        try:
            it = os.scandir(lp(d))
        except OSError:
            continue
        with it:
            for e in it:
                try:
                    if e.is_symlink():
                        continue
                    if e.is_dir(follow_symlinks=False):
                        if IS_WIN and getattr(e.stat(follow_symlinks=False), "st_file_attributes", 0) & 0x400:
                            continue
                        pilha.append(e.path)
                    elif e.is_file(follow_symlinks=False):
                        tot += e.stat(follow_symlinks=False).st_size
                        n += 1
                    visto += 1
                    if visto % 500 == 0:
                        time.sleep(0.001)  # cede a vez às requisições da tela
                except OSError:
                    pass
    return tot, n, True


EXPLICA_PASTA = {
    "windows": "O Windows em si. Se reinstala ao formatar.", "program files": "Programas instalados (64 bits). Se reinstalam a partir do instalador.",
    "program files (x86)": "Programas instalados (32 bits). Se reinstalam a partir do instalador.",
    "programdata": "Dados compartilhados de programas (licenças, bancos de alguns sistemas, configurações de todos os usuários).",
    "$recycle.bin": "Lixeira do Windows.", "system volume information": "Pontos de restauração do Windows (protegido, não dá para ler).",
    "recovery": "Partição/arquivos de recuperação do fabricante.", "perflogs": "Registros de desempenho do Windows.", "msocache": "Cópia do instalador do Office.",
    "config.msi": "Restos de instalações em andamento.", "intel": "Arquivos de driver da Intel.", "amd": "Arquivos de driver da AMD.", "nvidia": "Arquivos de driver da NVIDIA.",
    "temp": "Arquivos temporários: o Windows e os programas recriam.", "tmp": "Arquivos temporários: os programas recriam.",
    "inetcache": "Cache da internet (páginas e imagens já vistas).", "cache": "Cache: cópia temporária para abrir mais rápido; se recria sozinho.",
    "cache2": "Cache do navegador; se recria sozinho.", "code cache": "Cache de programas; se recria sozinho.", "gpucache": "Cache da placa de vídeo; se recria sozinho.",
    "node_modules": "Bibliotecas de projetos de programação; se baixam de novo.", "usr": "Programas do Linux.", "var": "Dados variáveis do Linux (logs, caches).",
    "opt": "Programas extras do Linux.", "snap": "Pacotes Snap do Linux.", "boot": "Arquivos de inicialização.", "etc": "Configurações do Linux."}


def explica_pasta(caminho):
    n = os.path.basename(str(caminho).rstrip("\\/")).lower()
    return EXPLICA_PASTA.get(n) or ("Cache: se recria sozinho." if "cache" in n else "Pasta que a varredura não lê por padrão.")


# ---------------------------- antecipar falhas: programas abertos, energia, sono ----------------------------
# processo -> (nome para mostrar, teste do arquivo marcado que esse programa costuma travar)
_ext = lambda *e: (lambda it: os.path.splitext(it.disp.lower())[1] in e)
_pasta = lambda *t: (lambda it: any(x in it.disp.lower().replace("\\", "/") for x in t))
PROGRAMAS_TRAVAM = {
    "msedge.exe": ("Edge", _pasta("/microsoft/edge/")), "chrome.exe": ("Chrome", _pasta("/google/chrome/")), "brave.exe": ("Brave", _pasta("/bravesoftware/")),
    "firefox.exe": ("Firefox", _pasta("/mozilla/firefox/")), "thunderbird.exe": ("Thunderbird", _pasta("/thunderbird/")), "outlook.exe": ("Outlook", _ext(".pst", ".ost")),
    "fbserver.exe": ("Firebird (sistema da loja)", _ext(".fdb", ".gdb")), "fbguard.exe": ("Firebird (sistema da loja)", _ext(".fdb", ".gdb")),
    "excel.exe": ("Excel", _ext(".xls", ".xlsx", ".xlsm")), "winword.exe": ("Word", _ext(".doc", ".docx")), "powerpnt.exe": ("PowerPoint", _ext(".ppt", ".pptx")),
    "msaccess.exe": ("Access", _ext(".mdb", ".accdb")),
    "google chrome": ("Chrome", _pasta("/google/chrome/")), "firefox": ("Firefox", _pasta("/mozilla/firefox/")), "thunderbird": ("Thunderbird", _pasta("/thunderbird/")),
    "microsoft edge": ("Edge", _pasta("/microsoft edge/", "/microsoft/edge/"))}


def processos_abertos():
    """Nomes (minúsculos) dos processos em execução; vazio se não der para listar."""
    try:
        if IS_WIN:
            out = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True, timeout=10, creationflags=0x08000000).stdout
            return {l.split('","')[0].strip('"').lower() for l in out.splitlines() if l.strip()}
        out = subprocess.run(["ps", "-A", "-o", "comm="], capture_output=True, text=True, timeout=10).stdout
        return {os.path.basename(l.strip()).lower() for l in out.splitlines() if l.strip()}
    except Exception:
        return set()


def energia():
    """{"bateria": True se está na bateria, "nivel": % ou None}."""
    try:
        if IS_WIN:
            import ctypes

            class S(ctypes.Structure):
                _fields_ = [("AC", ctypes.c_ubyte), ("Flag", ctypes.c_ubyte), ("Pct", ctypes.c_ubyte), ("R", ctypes.c_ubyte), ("L", ctypes.c_ulong), ("F", ctypes.c_ulong)]
            st = S()
            ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(st))
            return {"bateria": st.AC == 0, "nivel": None if st.Pct == 255 else int(st.Pct)}
        if sys.platform == "darwin":
            out = subprocess.run(["pmset", "-g", "batt"], capture_output=True, text=True, timeout=5).stdout
            m = re.search(r"(\d+)%", out)
            return {"bateria": "Battery Power" in out, "nivel": int(m.group(1)) if m else None}
        base = "/sys/class/power_supply"
        for n in os.listdir(base):
            if n.startswith("AC") or n.startswith("ADP"):
                with open(os.path.join(base, n, "online")) as fh:
                    return {"bateria": fh.read().strip() == "0", "nivel": None}
    except Exception:
        pass
    return {"bateria": False, "nivel": None}


class SemSono(object):
    """Impede a suspensão do computador durante a cópia e a verificação (SetThreadExecutionState no Windows, caffeinate no Mac)."""
    def __init__(self):
        self.proc = None

    def __enter__(self):
        try:
            if IS_WIN:
                import ctypes
                ctypes.windll.kernel32.SetThreadExecutionState(0x80000001)  # CONTINUOUS | SYSTEM_REQUIRED, vale para a thread que chamou
            elif sys.platform == "darwin" and shutil.which("caffeinate"):
                self.proc = subprocess.Popen(["caffeinate", "-i", "-w", str(os.getpid())])
        except Exception:
            pass
        return self

    def __exit__(self, *a):
        try:
            if IS_WIN:
                import ctypes
                ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)
            if self.proc:
                self.proc.terminate()
        except Exception:
            pass


CAUSA_NOME_SRV = {"permissao": "sem permissão de leitura", "em_uso": "em uso por outro programa", "atalho_app": "atalho de aplicativo", "pulado": "pulado por você", "io": "erro de leitura"}
GRUPO_FORA = (("Sistema operacional", "Windows e programas"), ("Sistema Linux", "Sistema e programas"), ("Cache", "Caches e temporários"),
              ("Lixeira", "Lixeira e sistema"))
LINUX_RAIZ_FORA = {"usr", "var", "opt", "snap", "lib", "lib32", "lib64", "libx32", "bin", "sbin", "boot", "etc", "srv"}
_FX_OS = {"windows", "usr", "lib", "lib32", "lib64", "libx32", "bin", "sbin", "boot", "etc", "system"}
_FX_APPS = {"windowsapps", "opt", "snap", "applications"}


def faixa_fora(disp, motivo):
    """Faixa do cockpit de uma pasta que a varredura do backup pulou (medida em segundo plano)."""
    n = re.split(r"[\\/]", disp.rstrip("\\/"))[-1].lower()
    ml = (motivo or "").lower()
    if "cache" in ml or "lixeira" in ml or "temporár" in ml:
        return "caches"
    if n in _FX_OS:
        return "os"
    if n.startswith("program files") or n in _FX_APPS:
        return "apps"
    return "dados"


# ---------------------------- filtros da lista (estilo e-commerce: facetas com contagem) ----------------------------
FAIXAS_DATA = (("d30", 30), ("m6", 182), ("a1", 365), ("a3", 1095), ("antigo", None))
FAIXAS_TAM = (("p", 100 * 1024), ("m", 1024 ** 2), ("g", 10 * 1024 ** 2), ("gg", 100 * 1024 ** 2), ("xg", None))


def faixa_data(date, hoje=None):
    if not date:
        return "sem"
    try:
        dias = ((hoje or datetime.date.today()) - datetime.date(*date)).days
    except (ValueError, TypeError):
        return "sem"
    return next(k for k, lim in FAIXAS_DATA if lim is None or dias <= lim)


def faixa_tam(size):
    return next(k for k, lim in FAIXAS_TAM if lim is None or size < lim)


def chave_local(local):
    partes = (local or "").split("/")
    return "/".join(partes[:2]) if partes[0] in (PASTA_ORIGEM, PASTA_ORIGEM_ANTIGA) else partes[0]


def _data_iso(s):
    try:
        y, m, d = (int(x) for x in str(s).split("-"))
        return (y, m, d)
    except ValueError:
        return None


def parse_filtro(q):
    """Filtro da lista e do "marcar todos". Listas separadas por | (OU dentro do filtro; E entre filtros)."""
    f = {k: (v[0] if isinstance(v, list) else v) for k, v in (q or {}).items()}
    lst = lambda k: [x for x in str(f.get(k) if f.get(k) is not None else "").split("|") if x != ""]
    inc = f.get("inc")
    return {"cat": set(lst("cat")), "grupo": set(lst("grupo")), "tipo": set(lst("tipo")), "status": set(lst("status")), "local": lst("local"), "tag": set(lst("tag")),
            "data": set(lst("data")), "tam": set(lst("tam")), "act": f.get("act") or "",
            "inc": None if inc in (None, "", "todos") else str(inc) in ("1", "True", "true"),
            "dmin": _data_iso(f.get("dmin")), "dmax": _data_iso(f.get("dmax")),
            "smin": int(f["smin"]) if str(f.get("smin") or "").isdigit() else None, "smax": int(f["smax"]) if str(f.get("smax") or "").isdigit() else None,
            "q": str(f.get("q") or "").lower(), "facets": str(f.get("facets") or "") in ("1", "true"),
            "pasta": lst("pasta"), "copia": f.get("copia") if f.get("copia") in ("espelhar", "ordenar") else ""}


class App(object):
    def __init__(self):
        self.token = secrets.token_urlsafe(18)
        self.token_na_pagina = False
        self.allowed_hosts = set()
        self.lock = threading.RLock()
        self.rules = load_tag_rules(os.path.join(HERE, "etiquetas.txt"))
        self.logs = collections.deque(maxlen=500)
        self.reset()

    # ------------------------------------------------------------------ estado
    def reset(self):
        self.phase = "idle"
        self.msg = ""
        self.cfg = {}
        self.parar_medicao()
        self.parar_ensaio()
        self.ensaio = None
        self.medicao = None
        self.alertas = []  # avisos do vigilante e do pré-voo (id, nível, texto, ação, resolvido)
        self.eventos = []  # tudo o que o vigilante avisou durante o backup (vai para o certificado)
        self.falhas_recentes = collections.deque(maxlen=100)
        self.pular = None
        self.item_atual = None
        self.vigia_id = 0
        self.extras = []  # pastas que o técnico incluiu (fora do padrão da varredura)
        self.extras_planos = []  # os planos de varredura delas (a varredura final também repassa)
        self.incl = {}
        self.layout_modo = ""  # escolhido a cada backup, na Seleção
        self.checagens = []
        self.items = []
        self.ign_dirs = []
        self.ign_reais = []
        self.ign_dirs_total = 0
        self.cancel = threading.Event()
        self.run_ev = threading.Event()
        self.run_ev.set()
        self.scan_info = {"files": 0, "dirs": 0, "bytes": 0, "current": ""}
        self.cp = {"done_files": 0, "total_files": 0, "done_bytes": 0, "total_bytes": 0, "current": "", "errors": 0, "start": 0}
        self.vf = {"done": 0, "total": 0, "bytes_done": 0, "bytes_total": 0, "fail": 0, "mode": "", "current": ""}
        self.sweep = None
        self.verified_mode = ""
        self.cert = None
        self.dest_root = ""
        self.mapa_dir = ""
        self.t_start = None
        self.samples = collections.deque(maxlen=40)
        self.session_dsts = set()
        self.error = ""
        self.finished = False

    def log(self, msg):
        line = "%s  %s" % (datetime.datetime.now().strftime("%H:%M:%S"), msg)
        self.logs.append(line)
        try:
            if self.mapa_dir and os.path.isdir(self.mapa_dir):
                with open(os.path.join(self.mapa_dir, "historico.log"), "a", encoding="utf-8") as f:
                    f.write("%s  %s\n" % (now_iso(), msg))
        except OSError:
            pass

    def busy(self):
        return self.phase in ("scanning", "copying", "verifying", "finishing") or bool((getattr(self, "incl", None) or {}).get("rodando"))

    # ------------------------------------------------------------------ config
    def identificacao(self):
        """Cliente, técnico e equipamento do certificado: vêm do cadastro da máquina e do perfil do técnico, nunca digitados no backup."""
        out = {"cliente": "", "tecnico": "", "equip": ""}
        try:
            mid = FICHA.machine_id_cache()
            st = TERMO.status(mid) if TERMO else {}
            out["cliente"] = (st.get("terceiro_nome") or "").strip()
            out["tecnico"] = (PERFIL.ler().get("nome") or st.get("tecnico") or "").strip()
            out["equip"] = (FICHA.nome_exibicao(mid) or "").strip()
        except Exception:
            pass
        return out

    def set_config(self, d):
        if self.busy():
            raise Busy("Aguarde o processo atual terminar.")
        srcs = []
        for s in d.get("sources", []):
            p = os.path.abspath(os.path.expanduser(s.get("path", "")))
            if not os.path.isdir(p):
                raise ValueError("Origem não encontrada: %s" % p)
            kind = s.get("kind") or detect_kind(p)[0]
            srcs.append({"path": p, "kind": kind, "letter": (s.get("letter") or "C").strip()[:1].upper() or "C", "label": s.get("label", "")})
        if not srcs:
            raise ValueError("Escolha pelo menos uma origem.")
        srcs = [s for s in srcs if not any(o is not s and _dentro(s["path"], o["path"]) and s["path"] != o["path"] for o in srcs)]  # pasta dentro de outra origem: já vai junto
        dest = os.path.abspath(os.path.expanduser(d.get("dest", "")))
        if not d.get("dest") or not os.path.isdir(dest):
            raise ValueError("Escolha uma pasta de destino que exista.")
        folder = safe_seg((d.get("folder") or "").strip() or ("Backup_" + socket.gethostname()))
        ident = self.identificacao()
        self.cfg = {
            "sources": srcs, "dest": dest, "folder": folder,
            "cliente": ident["cliente"] or (d.get("cliente") or "").strip(), "tecnico": ident["tecnico"] or (d.get("tecnico") or "").strip(),
            "equip": ident["equip"] or (d.get("equip") or "").strip() or socket.gethostname(),
        }
        self.dest_root = os.path.join(dest, folder)
        self.mapa_dir = os.path.join(self.dest_root, "Mapa")
        return self.cfg

    # ------------------------------------------------------------------ checagens iniciais
    def preflight(self):
        """Confere ORIGEM e DESTINO. Cada problema diz o que é e como resolver; 'erro' bloqueia a cópia."""
        res = []

        def add(n, t, d, solucao=""):
            res.append({"nivel": n, "titulo": t, "detalhe": d, "solucao": solucao})

        cfg = self.cfg
        if not cfg:
            return [{"nivel": "erro", "titulo": "Configuração incompleta", "detalhe": "Escolha origens e destino.", "solucao": "Volte ao passo 1."}]
        # permissões
        adm = (hasattr(os, "geteuid") and os.geteuid() == 0)
        if IS_WIN:
            try:
                import ctypes
                adm = bool(ctypes.windll.shell32.IsUserAnAdmin())
            except Exception:
                adm = False
        if not adm:
            add("aviso", "Sem permissão de administrador", "Pastas de outros usuários e arquivos do sistema podem ficar sem leitura.",
                "Feche e abra o Destrava! como administrador (Windows: Iniciar-Windows.bat; Mac/Linux: com sudo).")
        if sys.platform == "darwin" and DADOS and not DADOS.acesso_total_mac():
            add("aviso", "Mac sem Acesso Total ao Disco", "Mail, Mensagens, Safari e backups do iPhone ficam invisíveis.",
                "Ajustes do Sistema > Privacidade e Segurança > Acesso Total ao Disco: ligue o Terminal e abra o Destrava! de novo.")
        # origem
        for src in cfg["sources"]:
            p = src["path"]
            try:
                names = os.listdir(p)
                if not names:
                    add("aviso", "Origem vazia: %s" % p, "Nenhum arquivo encontrado.", "Se for um disco do Windows, ele pode estar criptografado (BitLocker) ou não montado: veja abaixo.")
                else:
                    add("ok", "Origem legível: %s" % p, "Tipo detectado: %s." % {"windows": "instalação do Windows", "linux": "instalação do Linux", "folder": "pasta comum"}.get(src["kind"], src["kind"]))
            except OSError as e:
                add("erro", "Não consigo ler a origem: %s" % p, str(e), "Rode como administrador; se for disco externo, reconecte.")
                continue
            if not IS_WIN:
                m = mount_of(p)
                if m and m[2] in ("ntfs", "ntfs3", "fuseblk") and "ro" in m[3].split(","):
                    add("aviso", "Disco do Windows montado só para leitura", "É seguro para backup.",
                        "Se faltarem arquivos: ligue o Windows, desative a Inicialização Rápida e desligue segurando Shift.")
            ok, txt = saude_disco(p)
            if ok is False:
                add("erro", "Disco de ORIGEM com defeito (%s)" % p, txt,
                    "Copie primeiro o essencial (a cópia já vai em ordem de importância) e use o computador o mínimo possível. Depois troque o disco; se arquivos falharem, leve a um laboratório de recuperação.")
        for b in bitlocker_trancados():
            add("erro", "Disco criptografado e trancado: %s" % b["onde"], "BitLocker: sem a chave, os arquivos dele não podem ser lidos.",
                "Peça ao cliente a chave de recuperação (48 números; fica na conta Microsoft dele: aka.ms/myrecoverykey) e use 'Destravar com a chave'.")
        escolhidas = {os.path.abspath(x["path"]) for x in cfg["sources"]}
        for d in list_sources():
            usado = (d["total"] or 0) - (d["free"] or 0)
            if os.path.abspath(d["path"]) in escolhidas or usado < 2e9 or (physical_id(d["path"]) and physical_id(d["path"]) == physical_id(cfg["dest"])):
                continue
            if any(os.path.abspath(d["path"]).startswith(e.rstrip(os.sep) + os.sep) or e.startswith(os.path.abspath(d["path"]).rstrip(os.sep) + os.sep) for e in escolhidas):
                continue
            add("aviso", "Disco não escolhido: %s (%s usados)" % (d["label"], fmt_bytes(usado)), "Este disco tem dados e não está na origem.",
                "Se tiver arquivos do cliente, volte ao passo 1 e adicione como origem.")
        # destino
        d = cfg["dest"]
        total, free = disk_usage(d)
        add("ok", "Destino: %s" % d, "%s livres de %s." % (fmt_bytes(free), fmt_bytes(total)))
        fs = fs_type(d)
        if fs in ("vfat", "msdos"):
            add("aviso", "Destino em FAT32", "FAT32 não aceita arquivos acima de 4 GB.", "Se houver arquivos grandes, formate o disco de destino em exFAT (apaga o disco!) ou use outro.")
        try:
            os.makedirs(self.dest_root, exist_ok=True)
            mb, vel = teste_destino(self.dest_root, min(512, int(free / 1048576 * 0.5)))
            self.vel_destino = vel
            add("ok", "Gravou e releu %d MB do disco de destino sem diferenças" % mb, "Gravação %.0f MB/s · leitura do disco (%s)." % (vel, disco.METODO))
            if vel < 8:
                add("aviso", "Destino lento (%.0f MB/s)" % vel, "A cópia vai demorar.", "Use uma porta USB 3 (azul) ou outro disco.")
        except ValueError as e:
            add("erro", "O destino devolveu dados DIFERENTES dos gravados", str(e),
                "Disco ou pendrive com defeito ou com capacidade falsificada. NÃO use para backup: troque por outro.")
        except OSError as e:
            ro = getattr(e, "errno", None) in (errno.EROFS, errno.EACCES, errno.EPERM)
            add("erro", "Não consigo gravar no destino", str(e),
                "Disco em modo somente leitura ou sem permissão: no Windows rode 'chkdsk X: /f'; disco NTFS no Zorin: ligue o Windows, desative a Inicialização Rápida e desligue com Shift." if ro
                else "Reconecte o disco; se repetir, use outro.")
        ok, txt = saude_disco(d)
        if ok is False:
            add("erro", "Disco de DESTINO com defeito", txt, "Não use este disco para backup: troque por outro.")
        pd = physical_id(d)
        same = [s_["path"] for s_ in cfg["sources"] if pd and physical_id(s_["path"]) == pd]
        self.same_disk = bool(same)
        if same:
            add("aviso", "Destino no MESMO disco físico de uma origem", "Serve para organizar, NÃO para formatar: a formatação apagaria o backup.",
                "Para formatar depois, use um disco externo como destino.")
        else:
            add("ok", "Destino em disco diferente das origens", "Pronto para um backup que sobrevive à formatação.")
        self.checagens = res
        return res

    # ------------------------------------------------------------------ planejamento de raízes
    def plan_roots(self, src):
        kind, root, letter = src["kind"], src["path"], src["letter"]
        plans = []
        if kind == "windows":
            names = {n.lower(): n for n in safe_listdir(root)}
            ud = names.get("users")
            if ud:
                for u in sorted(safe_listdir(os.path.join(root, ud))):
                    up = os.path.join(root, ud, u)
                    if not os.path.isdir(up) or e_link(up) or u.lower() in IGN_WIN_USERS or re.match(r"^defaultuser\d+$", u, re.I):
                        continue
                    if u.lower() == "public":
                        local = "Publico"
                    elif re.match(r"^TEMP($|\.)", u, re.I):
                        local = "TEMP/" + u
                    else:
                        local = u
                    plans.append((up, local, "%s:\\Users\\%s" % (letter, u), "\\", "winuser"))
            for n in sorted(safe_listdir(root)):
                p = os.path.join(root, n)
                low = n.lower()
                if os.path.isdir(p) and not e_link(p):
                    if low in IGN_WIN_ROOT or low.startswith("$") or low in IGN_ANY:
                        if low != "users":
                            self.add_ign("%s:\\%s" % (letter, n), "Sistema operacional / programas instalados", p)
                        continue
                    plans.append((p, "Disco_%s/%s" % (letter, n), "%s:\\%s" % (letter, n), "\\", "plain"))
            plans.append((root, "Disco_%s" % letter, "%s:\\" % letter, "\\", "toplevel"))
            for pf in ("program files", "program files (x86)", "programdata"):
                if names.get(pf):
                    plans.append((os.path.join(root, names[pf]), "Disco_%s/Sistemas" % letter, "%s:\\%s" % (letter, names[pf]), "\\", "sistemas"))
        elif kind == "mac":
            ud = os.path.join(root, "Users")
            for u in mac_usuarios(ud):
                plans.append((os.path.join(ud, u), u, "/Users/" + u, "/", "macuser"))
        elif kind == "linux":
            hp = os.path.join(root, "home")
            for u in sorted(safe_listdir(hp)):
                up = os.path.join(hp, u)
                if os.path.isdir(up) and not e_link(up):
                    plans.append((up, u, "/home/" + u, "/", "linuxuser"))
            rp = os.path.join(root, "root")
            if os.path.isdir(rp) and not e_link(rp):
                plans.append((rp, "root", "/root", "/", "linuxuser"))
        else:
            base = os.path.basename(root.rstrip("/\\")) or root
            home = os.path.abspath(os.path.expanduser("~"))
            if sys.platform == "darwin" and (os.path.abspath(root) == home or os.path.dirname(os.path.abspath(root)) == "/Users"):
                plans.append((root, base, root, os.sep, "macuser"))
            elif os.path.abspath(root) == home or os.path.dirname(os.path.abspath(root)) == "/home":
                plans.append((root, base, root, os.sep, "linuxuser"))
            else:
                plans.append((root, ("Disco_" if os.path.ismount(root) else "Pasta_") + base, root, os.sep, "plain"))
        return plans

    def add_ign(self, disp, motivo, real=None):
        self.ign_dirs_total += 1
        if len(self.ign_dirs) < 20000:
            self.ign_dirs.append((disp, motivo))
        if real:  # só o que dá para medir depois (pastas de sistema, caches, lixeira): explica o espaço do disco que não entra
            self.ign_reais.append((real, disp, motivo))

    def dir_ignore(self, name, ctx, parent_is_root):
        low = name.lower()
        if low in IGN_ANY:
            return "Lixeira / sistema"
        if low in CACHE_DIRS:
            return "Cache/temporário (recriado sozinho)"
        if low == "windowsapps":
            return "Atalhos de aplicativos do Windows (não são arquivos de verdade)"
        if ctx == "macuser" and parent_is_root and low == "library":
            return "Dados do macOS e dos apps (não são arquivos pessoais)"
        return None

    def walk_plan(self, plan):
        """Gera (real, disp, name, st, local, marca) para cada arquivo; marca = None | "appdata" | "oculto"."""
        real_root, local, disp_root, sep, ctx = plan
        dest_abs = os.path.abspath(self.dest_root) if self.dest_root else None
        stack = [(real_root, disp_root, True, None)]
        while stack:
            if self.cancel.is_set():
                raise Cancelled()
            rd, dd, is_root, marca = stack.pop()
            try:
                it = os.scandir(lp(rd))
            except OSError as e:
                self.add_ign(dd, "Sem acesso: %s" % (e.strerror or e))
                continue
            self.scan_info["dirs"] += 1
            self.scan_info["current"] = dd
            with it:
                for e in it:
                    try:
                        name = e.name
                        if e.is_symlink():
                            if e.is_dir(follow_symlinks=False) or True:
                                if name.lower() not in SILENT_JUNCTIONS:
                                    if e.is_dir():
                                        self.add_ign(dd.rstrip(sep) + sep + name, "Atalho/junção do sistema (não seguido)")
                            continue
                        if e.is_dir(follow_symlinks=False):
                            if ctx == "toplevel":
                                continue
                            if dest_abs and os.path.abspath(e.path).startswith(dest_abs):
                                continue
                            st = None
                            if IS_WIN:
                                try:
                                    st = e.stat(follow_symlinks=False)
                                    if getattr(st, "st_file_attributes", 0) & 0x400 and name.lower() != "onedrive":
                                        if name.lower() not in SILENT_JUNCTIONS:
                                            self.add_ign(dd.rstrip(sep) + sep + name, "Atalho/junção do sistema (não seguido)")
                                        continue
                                except OSError:
                                    pass
                            if ctx == "sistemas" and is_root and name.lower() in SIS_PULAR:
                                continue
                            why = self.dir_ignore(name, ctx, is_root) if ctx != "extra" else None  # incluída pelo técnico: entra tudo
                            if ctx == "winuser" and is_root and name.lower() in SILENT_JUNCTIONS:
                                continue
                            if why:
                                self.add_ign(dd.rstrip(sep) + sep + name, why, e.path)
                                continue
                            m = marca
                            if not m and ctx == "winuser" and is_root and name.lower() == "appdata":
                                m = "appdata"
                            elif not m and (name.startswith(".") or (IS_WIN and getattr(st, "st_file_attributes", 0) & 2)):
                                m = "oculto"
                            stack.append((e.path, dd.rstrip(sep) + sep + name, False, m))
                        elif e.is_file(follow_symlinks=False):
                            st = e.stat(follow_symlinks=False)
                            if getattr(st, "st_reparse_tag", 0) == APPEXECLINK:  # atalho de aplicativo: não é arquivo de verdade
                                continue
                            if ctx == "sistemas" and (os.path.splitext(name.lower())[1] not in DB_EXT or st.st_size < 65536):
                                continue
                            m = marca or ("oculto" if ctx != "toplevel" and (name.startswith(".") or (IS_WIN and getattr(st, "st_file_attributes", 0) & 2)) else None)
                            yield (e.path, dd.rstrip(sep) + sep + name, name, st, local, m)
                    except OSError as ex:
                        self.add_ign(dd.rstrip(sep) + sep + getattr(e, "name", "?"), "Sem acesso: %s" % (ex.strerror or ex))

    def bookmark_items(self, plan):
        real_root, local, disp_root, sep, ctx = plan
        found = []
        if ctx == "winuser":
            chrome = [("Chrome", "AppData/Local/Google/Chrome/User Data"), ("Edge", "AppData/Local/Microsoft/Edge/User Data"),
                      ("Brave", "AppData/Local/BraveSoftware/Brave-Browser/User Data")]
            ff = "AppData/Roaming/Mozilla/Firefox/Profiles"
        elif ctx == "linuxuser":
            chrome = [("Chrome", ".config/google-chrome"), ("Chromium", ".config/chromium"), ("Edge", ".config/microsoft-edge"),
                      ("Brave", ".config/BraveSoftware/Brave-Browser"), ("ChromeSnap", "snap/chromium/common/chromium")]
            ff = ".mozilla/firefox"
        elif ctx == "macuser":
            chrome = [("Chrome", "Library/Application Support/Google/Chrome"), ("Edge", "Library/Application Support/Microsoft Edge"),
                      ("Brave", "Library/Application Support/BraveSoftware/Brave-Browser")]
            ff = "Library/Application Support/Firefox/Profiles"
        else:
            return found
        for nome, rel in chrome:
            base = os.path.join(real_root, *rel.split("/"))
            for prof in safe_listdir(base):
                if re.match(r"^(Default|Profile \d+)$", prof):
                    p = os.path.join(base, prof, "Bookmarks")
                    if os.path.isfile(p):
                        found.append((p, "%s_%s_Bookmarks.json" % (nome, prof.replace(" ", ""))))
        for ffbase in (ff, "snap/firefox/common/.mozilla/firefox") if ctx == "linuxuser" else (ff,):
            base = os.path.join(real_root, *ffbase.split("/"))
            for prof in safe_listdir(base):
                p = os.path.join(base, prof, "places.sqlite")
                if os.path.isfile(p):
                    found.append((p, "Firefox_%s_places.sqlite" % re.sub(r"[^0-9A-Za-z_-]", "_", prof)))
        res = []
        for p, nm in found:
            try:
                st = os.stat(p)
            except OSError:
                continue
            it = Item()
            it.src = p
            it.disp = disp_root + sep + "(favoritos)" + sep + nm
            it.size, it.mtime, it.local = st.st_size, st.st_mtime, local
            it.quem = it.pk = local
            it.cat, it.act, it.motivo = "Navegadores", "copiar", "Favoritos do navegador"
            it.date = None
            it.tags = ""
            it.inc = True
            loc = "/".join(safe_seg(x) for x in local.split("/"))
            it.rel = "%s/Outros/Navegadores/%s" % (loc, nm)
            res.append(it)
        return res

    def _app_conhecido(self, dentro, ctx):
        """(app, caminho dentro da pasta do app) se o arquivo é de um app cujos dados importam (e-mail, notas)."""
        low = dentro.lower()
        for app, rel, exts in (APPS_WIN if ctx == "winuser" else APPS_LINUX):
            r = rel.lower() + "/"
            if low.startswith(r) and (not exts or low.endswith(exts)):
                return app, dentro[len(r):]
        return None

    # ------------------------------------------------------------------ varredura
    def start_scan(self):
        with self.lock:
            if self.busy():
                raise Busy("Já existe um processo em andamento.")
            if not self.cfg:
                raise ValueError("Salve a configuração antes de escanear.")
            self.parar_medicao()
            self.items = []
            self.extras, self.extras_planos, self.incl = [], [], {}
            self.ign_dirs = []
            self.ign_reais = []
            self.ign_dirs_total = 0
            self.sweep = None
            self.verified_mode = ""
            self.cert = None
            self.finished = False
            self.session_dsts = set()
            self.error = ""
            self.cancel.clear()
            self.run_ev.set()
            self.scan_info = {"files": 0, "dirs": 0, "bytes": 0, "current": ""}
            self.phase = "scanning"
        threading.Thread(target=self._scan_thread, daemon=True).start()

    def make_item(self, real, disp, name, st, local, ctx="", marca=None, raiz=""):
        nuvem = bool(getattr(st, "st_file_attributes", 0) & CLOUD_ATTRS) if IS_WIN else bool(getattr(st, "st_flags", 0) & 0x40000000)
        if ctx == "sistemas":  # caminho original preservado: restaurar é copiar de volta para o mesmo lugar
            it = Item()
            it.src, it.disp, it.size, it.mtime, it.local = real, disp, st.st_size, st.st_mtime, local
            it.cat, it.act, it.motivo, it.date, it.nuvem, it.tags, it.inc = "Sistemas", "copiar", "Banco de dados de sistema · feche o sistema antes do backup", None, nuvem, "", True
            partes = [x for x in re.split(r"[\\/]", disp)[1:] if x]
            it.rel = "/".join([safe_seg(x) for x in local.split("/")] + [safe_seg(x) for x in partes])
            it.inc0 = True
            it.quem, it.pk = local, pasta_chave(local, "/".join(partes))
            return it
        if ctx == "extra":  # pasta que a varredura não lê, incluída pelo técnico: caminho original preservado
            it = Item()
            it.src, it.disp, it.size, it.mtime, it.local = real, disp, st.st_size, st.st_mtime, local
            it.cat, it.act, it.motivo, it.date, it.nuvem, it.tags, it.inc = "Extras", "copiar", "Incluído por você (pasta fora do padrão)", stat_date(st), nuvem, "", True
            it.raiz, it.ctx, it.inc0 = raiz, ctx, True
            partes = [x for x in re.split(r"[\\/]", disp)[1:] if x]
            it.rel = "/".join([safe_seg(x) for x in local.split("/")] + [safe_seg(x) for x in partes])
            it.quem, it.pk = local, pasta_chave(local, "/".join(partes))
            return it
        cat, act, mot, marcado = classify_file(name, st.st_size, nuvem)
        ext = os.path.splitext(name.lower())[1]
        date = None
        if cat == "Fotos" and ext in (".jpg", ".jpeg") and not nuvem:
            date = exif_date(real)
        if not date:
            date = name_date(name) or stat_date(st)
        it = Item()
        it.src, it.disp, it.size, it.mtime, it.local = real, disp, st.st_size, st.st_mtime, local
        it.cat, it.act, it.motivo, it.date, it.nuvem = cat, act, mot, date, nuvem
        it.tags = tag_path(self.rules, disp) if act != "ignorar" else ""
        it.raiz, it.ctx = raiz, ctx
        loc = "/".join(safe_seg(x) for x in local.split("/"))
        dentro = disp[len(raiz):].lstrip("\\/") if raiz and disp.startswith(raiz) else name
        dentro_n = dentro.replace("\\", "/")
        it.quem, it.pk = local, pasta_chave(local, dentro_n)
        segs = lambda t: "/".join(safe_seg(x) for x in t.split("/") if x)
        app = self._app_conhecido(dentro_n, ctx) if ctx in ("winuser", "linuxuser", "macuser") else None
        if app and act != "ignorar":
            cat, act, mot, marcado = "Dados_de_apps", "copiar", "Dados do %s (e-mail, contatos, notas)" % app[0].replace("_", " "), True
            it.rel = "%s/Dados_de_apps/%s/%s" % (loc, app[0], segs(app[1]))
        elif marca == "appdata" and act != "ignorar":
            k = dentro_n.lower().find("appdata/")
            cat, act, mot, marcado = "Dados_de_apps", "copiar", "Dados de programas (AppData): só se o cliente precisar", False
            it.rel = "%s/Dados_de_apps/AppData/%s" % (loc, segs(dentro_n[k + 8:] if k >= 0 else dentro_n))
        elif marca == "oculto" and act != "ignorar" and cat != "Nuvem":
            cat, mot, marcado = "Ocultos", "Arquivo oculto (%s)" % cat, False
            it.rel = "%s/Ocultos/%s" % (loc, segs(dentro_n))
        elif cat != "Nuvem" and eh_whatsapp(disp, name):
            dono = local.split("/")[-1] if ctx in ("winuser", "linuxuser", "macuser") and local else ""
            local = it.local = "WhatsApp (%s)" % dono if dono else "WhatsApp"  # o WhatsApp de cada usuário vira um "usuário" à parte
            mot = "WhatsApp (%s)" % cat
            it.rel = build_rel(local, cat, date, name, ext)
            it.eleg = True
        else:
            it.rel = build_rel(local, cat, date, name, ext)
            it.eleg = True
        it.cat, it.act, it.motivo = cat, act, mot
        it.tags = tag_path(self.rules, disp) if act != "ignorar" else ""
        it.inc = it.inc0 = marcado
        it.local0, it.rel0 = it.local, it.rel
        return it

    # ------------------------------------------------------------------ vigilante durante a cópia e a verificação
    LIMITE_PARADA = 45      # segundos sem nenhum byte novo
    LIMITE_LENTA = 1048576  # bytes/s; abaixo disso por 60 s é lenta

    def alerta(self, id_, nivel, texto, acao="", acoes=()):
        """Cria ou atualiza um aviso (sem repetir o mesmo id); o novo vai para o Registro e para o certificado."""
        for a in self.alertas:
            if a["id"] == id_ and not a.get("resolvido"):
                a.update(texto=texto, acao=acao, acoes=list(acoes), nivel=nivel)
                return a
        a = {"id": id_, "nivel": nivel, "texto": texto, "acao": acao, "acoes": list(acoes), "resolvido": False, "quando": now_iso()}
        self.alertas.append(a)
        self.log("ALERTA: %s %s" % (texto, acao))
        if texto not in [e["texto"] for e in self.eventos]:
            self.eventos.append({"quando": a["quando"], "texto": texto})
        return a

    def resolver(self, id_):
        for a in self.alertas:
            if a["id"] == id_ and not a.get("resolvido"):
                a["resolvido"] = True
                self.log("Resolvido: %s" % a["texto"])

    def iniciar_vigia(self):
        self.vigia_id += 1
        threading.Thread(target=self._vigia, args=(self.vigia_id,), daemon=True).start()

    def _vigia(self, meu):
        ultimo, t_mov, janela, pausou = None, time.time(), collections.deque(maxlen=30), False
        while self.phase in ("copying", "verifying") and self.vigia_id == meu:
            time.sleep(2)
            agora = time.time()
            copiando = self.phase == "copying"
            prog = self.cp["done_bytes"] if copiando else self.vf["bytes_done"]
            em_pausa = not self.run_ev.is_set()
            janela.append((agora, prog))
            if prog != ultimo or em_pausa:
                ultimo, t_mov = prog, agora
            parado = agora - t_mov
            atual = self.cp["current"] if copiando else self.vf["current"]
            adiado = getattr(self, "adiar_parada", 0) > agora
            if parado >= self.LIMITE_PARADA and not adiado:
                self.alerta("parada", "aviso", "%s parada há %d s em %s." % ("A cópia" if copiando else "A conferência", parado, os.path.basename(str(atual)) or "um arquivo"),
                            "Disco travado, arquivo enorme ou leitura ruim. Pode esperar ou pular o arquivo (vale quando o Windows devolver a leitura).", ("pular", "esperar") if copiando else ("esperar",))
            elif parado < 5:
                self.resolver("parada")
            if len(janela) >= 25 and not em_pausa and parado < self.LIMITE_PARADA:
                t0, b0 = janela[0]
                vel = (prog - b0) / max(1, agora - t0)
                resta = (self.cp["total_bytes"] - prog) if copiando else (self.vf["bytes_total"] - prog)
                if vel < self.LIMITE_LENTA and resta > 50 * 1048576:
                    self.alerta("lenta", "aviso", "Velocidade muito baixa (%s/s há 1 minuto)." % fmt_bytes(vel),
                                "Causas comuns: porta USB 2, setor ruim no disco de origem, antivírus lendo cada arquivo ou o computador ocupado.")
                elif vel > 2 * self.LIMITE_LENTA:
                    self.resolver("lenta")
            if copiando and self.dest_root:
                if not os.path.isdir(self.dest_root):
                    self.alerta("destino", "erro", "O destino do backup sumiu (disco ou pendrive desconectado?).", "Reconecte: a cópia retoma sozinha.")
                    if self.run_ev.is_set():
                        self.run_ev.clear()
                        pausou = True
                else:
                    self.resolver("destino")
                    total, livre = disk_usage(self.dest_root)
                    falta = max(0, self.cp["total_bytes"] - self.cp["done_bytes"])
                    if total and livre < falta * 1.02 + 64 * 1048576:
                        self.alerta("espaco", "erro", "O destino está ficando sem espaço: faltam %s e há %s livres." % (fmt_bytes(falta), fmt_bytes(livre)),
                                    "Libere espaço no destino: a cópia está pausada e continua sozinha.")
                        if self.run_ev.is_set():
                            self.run_ev.clear()
                            pausou = True
                    else:
                        self.resolver("espaco")
                    if pausou and not self.run_ev.is_set() and not any(a["id"] in ("destino", "espaco") and not a.get("resolvido") for a in self.alertas):
                        self.run_ev.set()
                        pausou = False
            rec = [k for t, k in self.falhas_recentes if agora - t < 300]
            if len(rec) >= 20:
                k, n = collections.Counter(rec).most_common(1)[0]
                if n >= 20:
                    causa, prog_ = k.split("|", 1)
                    self.alerta("falhas:" + k, "aviso", "%d arquivos de %s falharam seguidos (%s)." % (n, prog_, CAUSA_NOME_SRV.get(causa, causa)),
                                "Se for um programa aberto, feche-o e use Refazer; ou desmarque essa pasta na Seleção.")
        for a in self.alertas:
            if self.vigia_id == meu and a["id"] in ("parada", "lenta"):
                a["resolvido"] = True

    # ------------------------------------------------------------------ antecipar falhas antes da cópia
    def antes_de_copiar(self):
        """Avisos acionáveis antes de começar: programas abertos que travam o que está marcado, bateria, tempo estimado."""
        alertas = []
        abertos = processos_abertos()
        marcados = [it for it in self.items if it.inc]
        vistos = {}
        for proc, (nome, teste) in PROGRAMAS_TRAVAM.items():
            if proc in abertos or any(proc == a.replace(".exe", "") for a in abertos):
                n = sum(1 for it in marcados if teste(it))
                if n and nome not in vistos:
                    vistos[nome] = n
                    alertas.append({"id": "aberto:" + nome, "nivel": "aviso", "texto": "O %s está aberto e %d arquivo(s) marcados dele ficam travados." % (nome, n),
                                    "acao": "Feche o %s e clique em Verificar de novo (ou copie assim mesmo: esses arquivos aparecem como \"em uso\", não como falha)." % nome})
        en = energia()
        if en["bateria"]:
            alertas.append({"id": "bateria", "nivel": "aviso", "texto": "O computador está na bateria%s." % (" (%d%%)" % en["nivel"] if en["nivel"] is not None else ""),
                            "acao": "Ligue na tomada: uma cópia longa pode acabar a bateria no meio."})
        total = sum(it.size for it in marcados)
        vel = getattr(self, "vel_destino", 0) or 0
        seg = int(total / (vel * 1048576)) if vel else 0
        if seg > 7200:
            alertas.append({"id": "tempo", "nivel": "aviso", "texto": "Tempo previsto: cerca de %dh%02dmin (%s a %.0f MB/s)." % (seg // 3600, seg % 3600 // 60, fmt_bytes(total), vel),
                            "acao": "Use uma porta USB 3 (azul) ou outro disco de destino, ou desmarque o que não precisa."})
        return {"alertas": alertas, "estimativa": {"segundos": seg, "bytes": total, "vel": vel}, "energia": en, "abertos": sorted(vistos)}

    def ensaio_leitura(self):
        """Em segundo plano: abre e lê o começo de cada arquivo marcado, para achar antes da cópia o que não dá para ler (em uso, sem permissão)."""
        with self.lock:
            if self.busy():
                raise Busy("Aguarde o processo atual terminar.")
            if not self.items:
                raise ValueError("Escaneie antes.")
            self.parar_ensaio()
            self.ens_parar = threading.Event()
            alvos = [i for i, it in enumerate(self.items) if it.inc and not it.nuvem and it.size > 0]
            self.ensaio = {"rodando": True, "total": len(alvos), "feitos": 0, "problemas": []}
        threading.Thread(target=self._ensaio_thread, args=(alvos, self.ens_parar, self.ensaio), daemon=True).start()
        return {"ok": True, "total": len(alvos)}

    def parar_ensaio(self):
        ev = getattr(self, "ens_parar", None)
        if ev:
            ev.set()

    def _ensaio_thread(self, alvos, parar, ens):
        for n, i in enumerate(alvos):
            if parar.is_set():
                break
            it = self.items[i]
            try:
                with open(lp(it.src), "rb") as fh:
                    fh.read(4096)
            except OSError as e:
                if len(ens["problemas"]) < 50000:
                    ens["problemas"].append((i, classify_err(e)[0]))
            ens["feitos"] = n + 1
            if n % 200 == 199:
                time.sleep(0.001)  # cede a vez
        ens["rodando"] = False

    def ensaio_estado(self, grupo="", off=0, limit=50):
        ens = getattr(self, "ensaio", None)
        if not ens:
            return {"existe": False}
        reais, grupos = [], {}
        for i, causa in list(ens["problemas"]):
            it = self.items[i]
            if not it.inc:
                continue
            if it.cat in NAO_PESSOAIS and causa in CAUSAS_EM_USO:
                k = causa + "|" + programa_de(it.disp)
                g = grupos.setdefault(k, {"chave": k, "causa": causa, "programa": programa_de(it.disp), "n": 0, "bytes": 0, "ex": []})
                g["n"] += 1
                g["bytes"] += it.size
                if len(g["ex"]) < 3:
                    g["ex"].append(it.disp)
            else:
                reais.append((i, causa))
        out = {"existe": True, "rodando": ens["rodando"], "total": ens["total"], "feitos": ens["feitos"], "n_reais": len(reais),
               "reais": [{"disp": self.items[i].disp, "cause": c, "size": self.items[i].size} for i, c in reais[:50]],
               "grupos": sorted(grupos.values(), key=lambda g: -g["n"]), "n_esperadas": sum(g["n"] for g in grupos.values())}
        return out

    # ------------------------------------------------------------------ diagnóstico do próprio programa
    def diagnostico(self):
        pagina = getattr(self, "autoteste_pagina", None) or {}
        testes = autoteste_servidor()
        if pagina.get("faltando"):
            testes.append({"ok": False, "titulo": "A tela perdeu partes", "detalhe": "Faltam: %s" % ", ".join(pagina["faltando"][:12])})
        elif pagina:
            testes.append({"ok": True, "titulo": "Telas e recursos do navegador completos", "detalhe": ""})
        erros = ler_erros(50)
        try:
            livre = shutil.disk_usage(DADOS_DIR[0]).free
        except OSError:
            livre = 0
        return {"versao": VERSION, "build": BUILD, "so": "%s %s" % (platform.system(), platform.release()), "python": platform.python_version(), "admin": eh_admin(),
                "pasta_dados": DADOS_DIR[0], "livre": livre, "testes": testes, "saudavel": all(t["ok"] for t in testes) and not any(a.get("nivel") == "erro" for a in self.alertas_ativas()),
                "erros": erros, "n_erros": len(erros), "alertas": self.alertas_ativas(), "registro": list(self.logs)[-200:], "fase": self.phase}

    def alertas_ativas(self):
        return [a for a in getattr(self, "alertas", []) if not a.get("resolvido")]

    def relatorio(self):
        """Texto único com tudo que o desenvolvedor precisa: sistema, testes, alertas, erros recentes e o Registro. Também grava em Erros/ no pendrive."""
        d = self.diagnostico()
        L = ["RELATÓRIO DO DESTRAVA!  %s" % now_iso(), "Versão %s (build %s) · %s · Python %s · administrador: %s" % (d["versao"], d["build"], d["so"], d["python"], "sim" if d["admin"] else "não"),
             "Pasta de dados: %s (%s livres)" % (d["pasta_dados"], fmt_bytes(d["livre"])), "Fase do backup: %s" % d["fase"], "", "AUTOTESTE"]
        L += ["  [%s] %s%s" % ("ok" if t["ok"] else "FALHOU", t["titulo"], "" if t["ok"] or not t["detalhe"] else " — " + t["detalhe"]) for t in d["testes"]]
        L += ["", "ALERTAS ATIVOS (%d)" % len(d["alertas"])] + ["  [%s] %s" % (a.get("nivel", "?"), a.get("texto", "")) for a in d["alertas"]]
        if self.cfg:
            L += ["", "CONFIGURAÇÃO DO BACKUP", "  origens: %s" % "; ".join("%s (%s)" % (x["path"], x["kind"]) for x in self.cfg.get("sources", [])), "  destino: %s" % self.cfg.get("dest", "")]
        if self.checagens:
            L += ["", "CHECAGENS"] + ["  [%s] %s — %s" % (c.get("nivel"), c.get("titulo"), c.get("detalhe")) for c in self.checagens]
        if self.medicao:
            m = self.medicao
            L += ["", "DISCO: usado %s, pessoal %s, marcado %s, resto %s%s" % (fmt_bytes(m.get("usado", 0)), fmt_bytes(m.get("achado", 0)), fmt_bytes(m.get("marcado", 0)),
                                                                          fmt_bytes(m.get("resto", 0)), " (medição parcial)" if m.get("parcial") else "")]
        L += ["", "ERROS RECENTES (%d, do mais novo ao mais antigo)" % len(d["erros"])]
        for e in d["erros"][:30]:
            L += ["--- %s  %s" % (e["quando"], e["onde"]), e["texto"].rstrip()]
        L += ["", "REGISTRO DO BACKUP (últimas %d linhas)" % len(d["registro"])] + d["registro"]
        txt = "\n".join(L) + "\n"
        arq = ""
        try:
            pasta = os.path.join(DADOS_DIR[0], "Erros")
            os.makedirs(pasta, exist_ok=True)
            arq = os.path.join(pasta, "relatorio-%s.txt" % datetime.datetime.now().strftime("%Y-%m-%d-%H%M"))
            with open(arq, "w", encoding="utf-8") as fh:
                fh.write(txt)
        except OSError:
            arq = ""
        return {"texto": txt, "arquivo": arq}

    # ------------------------------------------------------------------ incluir o que a varredura não lê
    PULA_SEMPRE = {"pagefile.sys", "hiberfil.sys", "swapfile.sys", "dumpstack.log.tmp", "dumpstack.log"}

    def incluir_pastas(self, caminhos):
        """Pastas fora do padrão (Windows, Program Files, caches…) escolhidas pelo técnico: varridas sem filtro e marcadas, com o caminho original."""
        with self.lock:
            if self.busy():
                raise Busy("Aguarde o processo atual terminar.")
            if not self.items or not self.cfg:
                raise ValueError("Escaneie antes de incluir pastas.")
            planos = []
            for c in caminhos or []:
                p = os.path.abspath(str(c))
                if not os.path.isdir(p) or e_link(p):
                    continue
                src = next((x for x in self.cfg["sources"] if _dentro(p, x["path"])), None)
                if not src:
                    raise ValueError("Essa pasta não está em nenhuma origem escolhida: %s" % p)
                if any(_dentro(p, q) for q in self.extras + [pl[0] for pl in planos]):
                    continue
                rel = os.path.relpath(p, src["path"])
                if src["kind"] == "windows":
                    letra = src["letter"] or "C"
                    disp = "%s:\\%s" % (letra, "" if rel == "." else rel.replace("/", "\\"))
                    planos.append((p, "Disco_%s/Extras" % letra, disp.rstrip("\\") or "%s:" % letra, "\\", "extra"))
                else:
                    planos.append((p, "Extras", p, os.sep, "extra"))
            if not planos:
                raise ValueError("Nenhuma pasta nova para incluir.")
            self.incl = {"rodando": True, "arquivos": 0, "bytes": 0, "atual": "", "pastas": [pl[2] for pl in planos], "erro": ""}
            self.cancel.clear()
        threading.Thread(target=self._incluir_thread, args=(planos,), daemon=True).start()
        return {"ok": True, "pastas": self.incl["pastas"]}

    def _incluir_thread(self, planos):
        novos, inc = [], self.incl
        try:
            for plano in planos:
                for real, disp, name, st, local, marca in self.walk_plan(plano):
                    if name.lower() in self.PULA_SEMPRE:
                        continue
                    novos.append(self.make_item(real, disp, name, st, local, "extra", None, plano[2]))
                    inc["arquivos"] += 1
                    inc["bytes"] += st.st_size
                    inc["atual"] = disp
            with self.lock:
                self.items.extend(novos)
                self.extras.extend(pl[0] for pl in planos)
                self.extras_planos.extend(planos)
            self.log("Incluídas no backup: %s (%d arquivos, %s)." % (", ".join(inc["pastas"]), len(novos), fmt_bytes(inc["bytes"])))
        except Cancelled:
            inc["erro"] = "cancelado"
        except Exception as e:
            inc["erro"] = str(e)
            registrar_erro("incluir pastas")
        inc["rodando"] = False

    def tirar_extras(self, caminho):
        with self.lock:
            if self.busy():
                raise Busy("Aguarde o processo atual terminar.")
            p = os.path.abspath(str(caminho))
            self.items = [it for it in self.items if not (it.ctx == "extra" and _dentro(it.src, p))]
            self.extras = [q for q in self.extras if not _dentro(q, p)]
            self.extras_planos = [pl for pl in self.extras_planos if not _dentro(pl[0], p)]
        return {"ok": True}

    # ------------------------------------------------------------------ onde está o resto do disco
    def iniciar_medicao(self):
        """Depois da varredura: mede em segundo plano o que ficou de fora, para explicar o espaço usado do disco."""
        self.parar_medicao()
        self.med_parar = threading.Event()
        alvos = []
        for real, disp, motivo in self.ign_reais:
            if "junção" not in motivo and "Sem acesso" not in motivo:
                alvos.append((os.path.abspath(real), disp, motivo))
        for src in (self.cfg or {}).get("sources", []):
            if src["kind"] == "linux":
                for n in sorted(safe_listdir(src["path"])):
                    p = os.path.join(src["path"], n)
                    if n in LINUX_RAIZ_FORA and os.path.isdir(p) and not e_link(p):
                        alvos.append((os.path.abspath(p), "/" + n, "Sistema Linux / programas instalados"))
        alvos.sort(key=lambda a: len(a[0]))
        unicos = []
        for a in alvos:  # pasta dentro de outra já medida não conta duas vezes
            if not any(_dentro(a[0], u[0]) for u in unicos):
                unicos.append(a)
        discos, vistos = [], set()
        for src in (self.cfg or {}).get("sources", []):
            if src["kind"] in ("windows", "linux", "mac") or os.path.ismount(src["path"]):
                total, livre = disk_usage(src["path"])
                if total and (total, livre) not in vistos:
                    vistos.add((total, livre))
                    discos.append((total, total - livre))
        achado = sum(it.size for it in self.items if it.act != "ignorar")
        sis_lidos = sum(it.size for it in self.items if it.act == "ignorar")  # lidos, mas do sistema (pagefile, thumbs.db…): não contam como pessoais
        dentro_sis = sum(it.size for it in self.items if it.cat == "Sistemas")  # bancos de sistema estão dentro de Program Files, já medido
        self.medicao = {"rodando": True, "pct": 0, "total": sum(d[0] for d in discos), "usado": sum(d[1] for d in discos), "achado": achado,
                        "marcado": sum(it.size for it in self.items if it.inc), "fora": [], "grupos": {"Arquivos do sistema": sis_lidos} if sis_lidos else {}, "resto": 0, "parcial": False,
                        "desconto": dentro_sis}
        self.medicao["regioes"] = {}
        self.medicao["so"] = ""
        raizes = []
        for src in (self.cfg or {}).get("sources", []):
            if src["kind"] == "mac":
                raizes.append((src["path"], "mac"))
            elif src["kind"] in ("windows", "linux"):
                self.medicao["so"] = DADOS.so_nome(src["kind"]) if DADOS else ""
            elif DADOS and _dentro(os.path.expanduser("~"), src["path"]) or DADOS and _dentro(src["path"], os.path.expanduser("~")):
                raizes.append((DADOS.raiz_local(), DADOS.so_local()))  # pasta pessoal deste computador: o disco é o daqui
        if raizes and DADOS:
            self.medicao["so"] = DADOS.so_nome(raizes[0][1])
        threading.Thread(target=self._medir_thread, args=(unicos, self.med_parar, raizes[:1]), daemon=True).start()

    def faixas_disco(self):
        """Faixas do cockpit (as mesmas do Gerenciamento): o que a varredura achou, por categoria, mais o que foi medido fora
        dela (pastas puladas e, no Mac, Applications/System). O que ninguém mediu vira Dados do Sistema quando a medição termina."""
        m = self.medicao or {}
        fx = {k: 0 for k, _, _ in CLS.FAIXAS}
        for it in self.items:
            f = "dados" if it.act == "ignorar" else CLS.BACKUP_FAIXA.get(it.cat, "outros")
            if f:
                fx[f] += it.size
        for x in m.get("fora") or []:
            fx[faixa_fora(x["caminho"], x["motivo"])] += x["bytes"]
        for k, v in (m.get("regioes") or {}).items():
            fx[k] += v
        fx["apps"] = max(0, fx["apps"] - (m.get("desconto") or 0))  # bancos de sistemas já contados como itens (Sistemas), e estão dentro de Program Files
        usado = m.get("usado") or 0
        soma = sum(fx.values())
        resto = max(0, usado - soma)
        if not m.get("rodando"):
            fx["dados"] += resto
            resto = 0
        return {"faixas": fx, "resto": resto, "medindo": bool(m.get("rodando")), "so": m.get("so") or ""}

    def parar_medicao(self):
        ev = getattr(self, "med_parar", None)
        if ev:
            ev.set()

    def _medir_thread(self, alvos, parar, raizes=()):
        m = self.medicao
        ate = time.time() + 240
        for raiz, so in raizes:  # Applications, System… (Mac): não estão em pasta pulada nenhuma
            if not parar.is_set() and DADOS:
                fora, parcial = DADOS.medir_fora(raiz, so, parar, ate)
                m["regioes"] = fora
                m["parcial"] = m["parcial"] or parcial
        for i, (real, disp, motivo) in enumerate(alvos):
            if parar.is_set():
                break
            b, n, ok = _medir_pasta(real, parar, ate)
            if not ok:
                m["parcial"] = True
            if b:
                grupo = next((g for k, g in GRUPO_FORA if k.lower() in motivo.lower()), "Outros pulados")
                m["fora"].append({"caminho": disp, "real": real, "motivo": motivo, "bytes": b, "arquivos": n, "grupo": grupo, "explica": explica_pasta(real)})
                m["grupos"][grupo] = m["grupos"].get(grupo, 0) + b
            m["pct"] = int((i + 1) * 100 / max(1, len(alvos)))
            if time.time() > ate:
                m["parcial"] = True
                break
        if m["grupos"].get("Windows e programas"):
            m["grupos"]["Windows e programas"] = max(0, m["grupos"]["Windows e programas"] - m["desconto"])
        medido = sum(m["grupos"].values())
        m["resto"] = max(0, m["usado"] - m["achado"] - medido) if m["usado"] else 0
        m["fora"].sort(key=lambda x: -x["bytes"])
        m["fora"] = m["fora"][:30]
        m["rodando"] = False

    def _scan_thread(self):
        try:
            self.log("Escaneamento iniciado.")
            items = []
            for src in self.cfg["sources"]:
                for plan in self.plan_roots(src):
                    for real, disp, name, st, local, marca in self.walk_plan(plan):
                        it = self.make_item(real, disp, name, st, local, plan[4], marca, plan[2])
                        items.append(it)
                        self.scan_info["files"] += 1
                        self.scan_info["bytes"] += st.st_size
                    items.extend(self.bookmark_items(plan))
            self.items = items
            for it in items:  # varrer de novo no mesmo backup mantém o modo escolhido (as escolhas pasta a pasta recomeçam)
                self._aplicar_copia(it)
            self.phase = "scanned"
            self.log("Escaneamento concluído: %d arquivos, %d pastas ignoradas." % (len(items), self.ign_dirs_total))
            try:
                self.iniciar_medicao()
            except Exception:
                pass
        except Cancelled:
            self.phase = "idle"
            self.log("Escaneamento cancelado.")
        except Exception:
            self.error = traceback.format_exc()
            self.phase = "error"
            self.log("ERRO no escaneamento: " + self.error.splitlines()[-1])

    # ------------------------------------------------------------------ como copiar (espelho / ordenado / misto)
    def copia_de(self, it):
        """espelhar | ordenar, para os arquivos que entram na escolha. Sem modo escolhido ainda, vale o ordenado (o de sempre)."""
        if it.lay:
            return it.lay
        return "espelhar" if self.layout_modo in ("espelho", "misto") else "ordenar"

    def _aplicar_copia(self, it):
        if not it.eleg:
            return
        it.rel = it.rel0 if self.copia_de(it) == "ordenar" else rel_espelho(it)  # o "local" (usuário) não muda: só onde fica no backup

    def layout_editavel(self):
        return self.phase == "scanned" and not any(it.status for it in self.items)

    def set_modo(self, modo):
        if modo not in LAYOUT_MODOS:
            raise ValueError("Modo inválido.")
        with self.lock:
            if not self.layout_editavel():
                raise Busy("A cópia já começou: o jeito de guardar não muda mais neste backup.")
            self.layout_modo = modo
            for it in self.items:
                it.lay = ""
                self._aplicar_copia(it)
        return self.layout_resumo()

    def copia(self, d):
        """No Misto: espelhar ou ordenar um conjunto (filtro da lista/grade ou linhas). A última ação vale."""
        qual = d.get("copia")
        if qual not in ("espelhar", "ordenar"):
            raise ValueError("Escolha espelhar ou ordenar.")
        with self.lock:
            if self.layout_modo != "misto":
                raise ValueError("Escolha o modo Misto para decidir pasta a pasta.")
            if not self.layout_editavel():
                raise Busy("A cópia já começou: o jeito de guardar não muda mais neste backup.")
            if "idx" in d:
                alvo = [i for i in (d["idx"] if isinstance(d["idx"], list) else [d["idx"]]) if isinstance(i, int) and 0 <= i < len(self.items)]
            else:
                alvo = self.filtrar(parse_filtro(d.get("filter") or {}))[0]
            n = 0
            for i in alvo:
                it = self.items[i]
                if it.eleg:
                    it.lay = qual
                    self._aplicar_copia(it)
                    n += 1
        return {"n": n, "resumo": self.layout_resumo()}

    def _layout_registro(self):
        """O que vai no certificado e no Mapa: o modo e quanto foi espelhado e ordenado (do que foi copiado)."""
        r = self.layout_resumo()
        return {"modo": r["modo"] or "ordenado", "nome": r["nome"] or "Ordenado", "espelhados": r["espelhar"]["n"], "ordenados": r["ordenar"]["n"]}

    def destino(self, i):
        """Onde um arquivo fica no backup em cada jeito de guardar (a prévia da faixa de baixo da Seleção)."""
        if not 0 <= i < len(self.items):
            raise ValueError("Arquivo não encontrado na lista: escaneie de novo.")
        it = self.items[i]
        return {"origem": it.disp, "espelho": rel_espelho(it) if it.eleg else it.rel, "ordenado": it.rel0 if it.eleg else it.rel,
                "atual": it.rel, "copia": self.copia_de(it) if it.eleg else "fixo"}

    def layout_resumo(self):
        """Quanto vai espelhado e quanto ordenado (só o marcado para o backup) e um exemplo real de como fica."""
        r = {"modo": self.layout_modo, "nome": LAYOUT_NOME.get(self.layout_modo, ""), "editavel": self.layout_editavel(),
             "espelhar": {"n": 0, "bytes": 0}, "ordenar": {"n": 0, "bytes": 0}, "fixos": {"n": 0, "bytes": 0}, "exemplo": None}
        melhor = None
        for it in self.items:
            if not it.inc:
                continue
            k = self.copia_de(it) if it.eleg else "fixos"
            r[k]["n"] += 1
            r[k]["bytes"] += it.size
            if it.eleg and it.pk.count("/") >= 2 and (melhor is None or it.pk.count("/") > melhor.pk.count("/") or (it.cat == "Documentos" and melhor.cat != "Documentos")):
                if melhor is None or it.pk.count("/") <= 5:
                    melhor = it
        if melhor is None:
            melhor = next((it for it in self.items if it.eleg and it.inc), None)
        if melhor is not None:
            r["exemplo"] = {"origem": melhor.disp, "espelho": rel_espelho(melhor), "ordenado": melhor.rel0}
        return r

    # ------------------------------------------------------------------ seleção e listas
    def _grupos(self, f):
        """[(nome, ativo, teste(it), valores(it) ou None)]. "valores" alimenta as facetas (contagem por opção)."""
        hoje = datetime.date.today()
        tipo = lambda it: tipo_de(nome_de(it.disp))
        grupo = lambda it: CLS.grupo_backup(it.cat, it.act)
        G = [("cat", bool(f["cat"]), lambda it: it.cat in f["cat"], lambda it: (it.cat,)),
             ("grupo", bool(f["grupo"]), lambda it: grupo(it) in f["grupo"], lambda it: (grupo(it),)),
             ("tipo", bool(f["tipo"]), lambda it: tipo(it) in f["tipo"], lambda it: (tipo(it),)),
             ("status", bool(f["status"]), lambda it: self.final_status(it) in f["status"], lambda it: (self.final_status(it),)),
             ("inc", f["inc"] is not None, lambda it: bool(it.inc) == f["inc"], lambda it: ("1" if it.inc else "0",)),
             ("local", bool(f["local"]), lambda it: any(it.local == v or it.local.startswith(v + "/") for v in f["local"]), lambda it: (chave_local(it.local),)),
             ("tag", bool(f["tag"]), lambda it: bool(f["tag"] & set((it.tags or "").split("|"))), lambda it: tuple(t for t in (it.tags or "").split("|") if t)),
             ("data", bool(f["data"] or f["dmin"] or f["dmax"]),
              lambda it: faixa_data(it.date, hoje) in f["data"] or (bool(f["dmin"] or f["dmax"]) and bool(it.date) and (not f["dmin"] or it.date >= f["dmin"]) and (not f["dmax"] or it.date <= f["dmax"])),
              lambda it: (faixa_data(it.date, hoje),)),
             ("tam", bool(f["tam"] or f["smin"] is not None or f["smax"] is not None),
              lambda it: faixa_tam(it.size) in f["tam"] or ((f["smin"] is not None or f["smax"] is not None) and (f["smin"] is None or it.size >= f["smin"]) and (f["smax"] is None or it.size <= f["smax"])),
              lambda it: (faixa_tam(it.size),)),
             ("act", bool(f["act"]), lambda it: it.act == f["act"], None),
             ("pasta", bool(f["pasta"]), lambda it: any(it.pk == p or it.pk.startswith(p + "/") for p in f["pasta"]), None),
             ("copia", bool(f["copia"]), lambda it: it.eleg and self.copia_de(it) == f["copia"],
              lambda it: (self.copia_de(it) if it.eleg else "fixo",)),
             ("q", bool(f["q"]), lambda it: f["q"] in it.disp.lower() or f["q"] in tipo(it).lower(), None)]
        return G

    def matches(self, it, f):
        f = f if "facets" in f else parse_filtro(f)
        return all(teste(it) for _, ativo, teste, _v in self._grupos(f) if ativo)

    def filtrar(self, f, facetas=False):
        """Índices que passam no filtro e, se pedido, as facetas: cada opção contada com os OUTROS filtros ativos (marcar PDF não zera Imagem)."""
        G = self._grupos(f)
        ativos = [g for g in G if g[1]]
        fac = {g[0]: {} for g in G if g[3]} if facetas else None
        idx = []
        for i, it in enumerate(self.items):
            falhas = [g for g in ativos if not g[2](it)]
            if not falhas:
                idx.append(i)
                contar = [g for g in G if g[3]] if facetas else ()
            elif facetas and len(falhas) == 1 and falhas[0][3]:
                contar = falhas
            else:
                continue
            for g in contar:
                d = fac[g[0]]
                for v in g[3](it):
                    d[v] = d.get(v, 0) + 1
        return idx, fac

    def select(self, d):
        on = bool(d.get("on"))
        n = 0
        if d.get("padrao"):  # volta ao que a varredura marcou sozinha: só o pessoal
            for it in self.items:
                it.inc = bool(it.inc0)
            return len(self.items)
        if "idx" in d:
            idxs = d["idx"] if isinstance(d["idx"], list) else [d["idx"]]
            for i in idxs:
                if 0 <= i < len(self.items):
                    self.items[i].inc = on
                    n += 1
            return n
        f = parse_filtro(d.get("filter") or {})
        for i in self.filtrar(f)[0]:
            it = self.items[i]
            if not f["act"] and it.act != "copiar":
                continue  # chaves de categoria/usuário/busca só mexem no que é pessoal; ignorados/revisar têm botões próprios
            it.inc = on
            n += 1
        return n

    def groups(self):
        g = {}
        cats = {}
        acts = {}
        ex = {}  # até 3 maiores arquivos de cada categoria/ação: exemplos reais desta máquina
        for it in self.items:
            for k in (("cat", it.cat) if it.act == "copiar" else None, ("act", it.act)):
                if k:
                    lst = ex.setdefault(k, [])
                    if len(lst) < 3 or it.size > lst[-1][0]:
                        lst.append((it.size, nome_de(it.disp)))
                        lst.sort(key=lambda x: -x[0])
                        del lst[3:]
            k = (it.local, it.cat, it.act)
            e = g.get(k)
            if e is None:
                e = g[k] = [0, 0, 0, 0, 0, 0]
            e[0] += 1
            e[1] += it.size
            if it.inc:
                e[2] += 1
                e[3] += it.size
            if it.eleg:
                e[4 if self.copia_de(it) == "espelhar" else 5] += 1
            for dct, key in (((cats, it.cat) if it.act == "copiar" else (None, None)), (acts, it.act)):
                if dct is None:
                    continue
                c = dct.get(key)
                if c is None:
                    c = dct[key] = [0, 0, 0, 0, 0, 0]
                c[0] += 1
                c[1] += it.size
                if it.inc:
                    c[2] += 1
                    c[3] += it.size
                if it.eleg:
                    c[4 if self.copia_de(it) == "espelhar" else 5] += 1
        glist = [{"local": k[0], "cat": k[1], "act": k[2], "n": v[0], "bytes": v[1], "sel_n": v[2], "sel_bytes": v[3], "esp": v[4], "ord": v[5]} for k, v in g.items()]
        glist.sort(key=lambda x: (x["local"].lower(), x["cat"], x["act"]))
        exs = lambda k: [n for _, n in ex.get(k, [])]
        cl = [{"cat": k, "n": v[0], "bytes": v[1], "sel_n": v[2], "sel_bytes": v[3], "esp": v[4], "ord": v[5], "ex": exs(("cat", k))} for k, v in cats.items()]
        cl.sort(key=lambda x: -x["bytes"])
        al = {k: {"n": v[0], "bytes": v[1], "sel_n": v[2], "sel_bytes": v[3], "esp": v[4], "ord": v[5], "ex": exs(("act", k))} for k, v in acts.items()}
        return {"groups": glist, "cats": cl, "acts": al, "ign_dirs": self.ign_dirs[:600], "ign_dirs_total": self.ign_dirs_total, "layout_modo": self.layout_modo}

    ORDEM = {"nome": lambda it: nome_de(it.disp).lower(), "tipo": lambda it: (tipo_de(nome_de(it.disp)), nome_de(it.disp).lower()),
             "data": lambda it: it.date or (0, 0, 0), "tamanho": lambda it: it.size, "caminho": lambda it: it.disp.lower(),
             "categoria": lambda it: PRIORIDADE.index(it.cat) if it.cat in PRIORIDADE else len(PRIORIDADE)}

    def files(self, q):
        """Lista do backup: filtro, busca (caminho ou tipo), ordem (ord/dir), página e os totais do filtro. limit=0: só os totais."""
        flt = parse_filtro(q)
        f = {k: (v[0] if isinstance(v, list) else v) for k, v in q.items()}
        off = max(0, int(f.get("offset") or 0))
        lim = max(0, min(int(f.get("limit", 200)), 500))
        idx, fac = self.filtrar(flt, flt["facets"])
        sel = [self.items[i] for i in idx if self.items[i].inc]
        chave = (lambda it: self.final_status(it)) if f.get("ord") == "situacao" else self.ORDEM.get(f.get("ord") or "")
        if chave and lim:
            idx.sort(key=lambda i: chave(self.items[i]), reverse=f.get("dir") == "desc")
        out = []
        for i in idx[off:off + lim]:
            it = self.items[i]
            nome = nome_de(it.disp)
            out.append([i, it.disp, it.size, ("%04d-%02d-%02d" % it.date) if it.date else "", it.cat, it.act, 1 if it.inc else 0,
                        it.err or it.motivo, self.final_status(it), it.tags, nome, tipo_de(nome), it.local,
                        "" if it.nuvem or not DADOS else (DADOS.tipo_previa(it.src) or ""),
                        self.copia_de(it) if it.eleg else "", it.rel, CLS.grupo_backup(it.cat, it.act), int(it.mtime or 0)])
        r = {"total": len(idx), "rows": out, "bytes": sum(self.items[i].size for i in idx), "sel_n": len(sel), "sel_bytes": sum(it.size for it in sel)}
        if str(f.get("pastas") or "") in ("1", "true"):
            r["pastas"] = self.subpastas(idx, (flt["pasta"] or [""])[0])
        if fac is not None:
            r["facets"] = fac
        return r

    def subpastas(self, idx, base=""):
        """Navegação por pasta: partindo dos usuários (raiz) e descendo. Para cada subpasta de base: arquivos, tamanho,
        marcados e quantos vão espelhados/ordenados. idx já vem filtrado (inclusive pela própria base)."""
        pre = base.rstrip("/") + "/" if base else ""
        sub, soltos = {}, {"n": 0, "bytes": 0}
        for i in idx:
            it = self.items[i]
            pk = it.pk or it.local0 or it.local
            if base and pk == base:
                soltos["n"] += 1
                soltos["bytes"] += it.size
                continue
            if pre and not pk.startswith(pre):
                continue
            nome = pk[len(pre):].split("/")[0]
            e = sub.get(nome)
            if e is None:
                e = sub[nome] = {"nome": nome, "chave": pre + nome, "n": 0, "bytes": 0, "sel_n": 0, "sel_bytes": 0, "espelhar": 0, "ordenar": 0}
            e["n"] += 1
            e["bytes"] += it.size
            if it.inc:
                e["sel_n"] += 1
                e["sel_bytes"] += it.size
            if it.eleg:
                e[self.copia_de(it)] += 1
        return {"base": base, "migalhas": [x for x in base.split("/") if x], "pastas": sorted(sub.values(), key=lambda x: -x["bytes"]),
                "soltos": soltos}

    def previa(self, i):
        """Prévia de um arquivo da origem pelo índice da lista: a tela nunca manda caminho. Só na nuvem não abre (baixaria o arquivo)."""
        try:
            i = int(i)
        except (TypeError, ValueError):
            raise ValueError("Arquivo não encontrado.")
        if not 0 <= i < len(self.items):
            raise ValueError("Arquivo não encontrado.")
        it = self.items[i]
        if it.nuvem:
            raise ValueError("Este arquivo está só na nuvem: abrir faria o download.")
        tipo = DADOS.tipo_previa(it.src) if DADOS else None
        if not tipo:
            raise ValueError("Sem prévia para este tipo de arquivo.")
        mime = DADOS.PREVIA[os.path.splitext(it.src.lower())[1]][1]
        return it.src, mime, tipo, (200 * 1024 if tipo == "texto" else None)

    def totals(self):
        n = b = 0
        big = 0
        for it in self.items:
            if it.inc:
                n += 1
                b += it.size
                if it.size > big:
                    big = it.size
        total, free = disk_usage(self.cfg["dest"]) if self.cfg else (0, 0)
        fs = fs_type(self.cfg["dest"]) if self.cfg else None
        cabe = b * 1.02 + 256 * 1024 * 1024 <= free
        return {"sel_n": n, "sel_bytes": b, "free": free, "total": total, "fs": fs, "biggest": big, "cabe": cabe,
                "fat32_problema": fs in ("vfat", "msdos") and big > 4 * 1024 ** 3 - 1,
                "solucao": "" if cabe else "Faltam %s: desmarque categorias (Programas, Ocultos, Vídeos…) ou use um disco maior." % fmt_bytes(b * 1.02 + 256 * 1024 * 1024 - free)}

    def final_status(self, it):
        if it.inc:
            if it.status == "ok":
                return "ok"
            if falha_esperada(it):
                return "em_uso"
            return "falha" if it.status in ("falha",) or self.phase in ("copied", "verified", "done") else "pendente"
        if it.act == "ignorar":
            return "ignorado"
        if it.act == "revisar":
            return "revisar"
        return "desmarcado"

    # ------------------------------------------------------------------ cópia
    def check_run(self):
        if self.cancel.is_set():
            raise Cancelled()
        if not self.run_ev.is_set():
            self.run_ev.wait()
            if self.cancel.is_set():
                raise Cancelled()

    def start_copy(self, retry_only=False):
        with self.lock:
            if self.busy():
                raise Busy("Já existe um processo em andamento.")
            if not self.items:
                raise ValueError("Escaneie antes de copiar.")
            t = self.totals()
            if not t["cabe"]:
                raise ValueError("Não cabe no destino: precisa de %s e há %s livres." % (fmt_bytes(t["sel_bytes"]), fmt_bytes(t["free"])))
            if t["fat32_problema"]:
                raise ValueError("O destino é FAT32 e há arquivos maiores que 4 GB. Use outro destino ou formate em exFAT/NTFS.")
            self.parar_medicao()
            self.parar_ensaio()
            queue = [it for it in self.items if it.inc and (it.status is None or (retry_only and it.status == "falha"))]
            queue.sort(key=lambda it: PRIORIDADE.index(it.cat) if it.cat in PRIORIDADE else len(PRIORIDADE))  # o essencial primeiro
            self.cancel.clear()
            self.run_ev.set()
            self.cp = {"done_files": 0, "total_files": len(queue), "done_bytes": 0, "total_bytes": sum(i.size for i in queue), "current": "",
                       "errors": 0, "start": time.time()}
            self.phase = "copying"
            self.samples.clear()
            os.makedirs(self.mapa_dir, exist_ok=True)
        threading.Thread(target=self._copy_thread, args=(queue, retry_only), daemon=True).start()
        self.iniciar_vigia()

    def _copy_thread(self, queue, retry_only):
        with SemSono():
            self._copy_thread2(queue, retry_only)

    def _copy_thread2(self, queue, retry_only):
        try:
            self.log("%s: %d arquivos (%s)." % ("Refazendo falhas" if retry_only else "Cópia iniciada", len(queue), fmt_bytes(self.cp["total_bytes"])))
            os.makedirs(self.dest_root, exist_ok=True)
            # perfis TEMP agrupados mesmo vazios
            for src in self.cfg["sources"]:
                if src["kind"] == "windows":
                    for n in safe_listdir(os.path.join(src["path"], "Users")):
                        if re.match(r"^TEMP($|\.)", n, re.I):
                            os.makedirs(os.path.join(self.dest_root, "TEMP", safe_seg(n)), exist_ok=True)
            for it in queue:
                self.check_run()
                self.cp["current"] = it.disp
                self.item_atual = it
                self.copy_item(it)
                self.cp["done_files"] += 1
            self.phase = "copied"
            falhas = sum(1 for it in self.items if it.inc and it.status == "falha")
            self.log("Cópia terminou: %d copiados, %d falhas." % (self.cp["done_files"] - falhas, falhas))
        except Cancelled:
            self.phase = "copied"
            self.log("Cópia cancelada. O que já foi copiado continua no destino.")
        except Exception:
            self.error = traceback.format_exc()
            self.phase = "error"
            self.log("ERRO na cópia: " + self.error.splitlines()[-1])

    def dst_of(self, it):
        return os.path.join(self.dest_root, *it.rel.split("/"))

    def copy_item(self, it):
        last = None
        for attempt in range(3):
            try:
                self._do_copy(it)
                return
            except Cancelled:
                raise
            except Pulado:
                last = ("pulado", "ERRO: Você mandou pular este arquivo (a leitura estava travada)")
                break
            except OSError as e:
                cause, msg = classify_err(e)
                last = (cause, msg)
                if cause == "io" and attempt < 2:
                    time.sleep(1.5)
                    continue
                break
        it.status = "falha"
        it.cause, it.err = last
        self.falhas_recentes.append((time.time(), it.cause + "|" + programa_de(it.disp)))
        self.cp["errors"] += 1
        self.cp["done_bytes"] += it.size
        self.log("FALHA: %s -> %s" % (it.disp, it.err))

    def _do_copy(self, it):
        dst = self.dst_of(it)
        os.makedirs(lp(os.path.dirname(dst)), exist_ok=True)
        final = dst
        if os.path.exists(lp(dst)):
            st = os.stat(lp(dst))
            if dst not in self.session_dsts and st.st_size == it.size and abs(st.st_mtime - it.mtime) <= 2:
                it.status = "ok"
                it.err = ""
                self.session_dsts.add(dst)
                self.cp["done_bytes"] += it.size
                return
            base, ext = os.path.splitext(dst)
            n = 1
            while True:
                final = "%s_%d%s" % (base, n, ext)
                if not os.path.exists(lp(final)) and final not in self.session_dsts:
                    break
                n += 1
            it.rel = os.path.relpath(final, self.dest_root).replace(os.sep, "/")
        tmp = final + ".ddpart"
        h = hashlib.sha256()
        total = 0
        try:
            with open(lp(it.src), "rb") as fi, open(lp(tmp), "wb") as fo:
                while True:
                    self.check_run()
                    if self.pular is it:
                        self.pular = None
                        raise Pulado()
                    buf = fi.read(CHUNK)
                    if not buf:
                        break
                    h.update(buf)
                    fo.write(buf)
                    total += len(buf)
                    self.cp["done_bytes"] += len(buf)
                fo.flush()
                os.fsync(fo.fileno())
            os.replace(lp(tmp), lp(final))
        except BaseException:
            try:
                os.remove(lp(tmp))
            except OSError:
                pass
            raise
        try:
            os.utime(lp(final), (it.mtime, it.mtime))
        except OSError:
            pass
        it.sha = h.hexdigest()
        it.size = total
        it.status = "ok"
        it.err = ""
        it.cause = ""
        self.session_dsts.add(final)

    # ------------------------------------------------------------------ verificação
    def start_verify(self, mode, sweep=True):
        with self.lock:
            if self.busy():
                raise Busy("Já existe um processo em andamento.")
            targets = [it for it in self.items if it.inc and it.status == "ok"]
            self.cancel.clear()
            self.run_ev.set()
            self.vf = {"done": 0, "total": len(targets), "bytes_done": 0, "bytes_total": sum(i.size for i in targets) * (2 if mode == "completa" else 0),
                       "fail": 0, "mode": mode, "current": ""}
            self.phase = "verifying"
            self.samples.clear()
        threading.Thread(target=self._verify_thread, args=(targets, mode, sweep), daemon=True).start()
        self.iniciar_vigia()

    def hash_file(self, path, drop_cache=False):
        """drop_cache: lê do DISCO, não da memória (disco.py). É o que vale para conferir o backup."""
        h = hashlib.sha256()
        for b in (disco.blocos(lp(path)) if drop_cache else _ler(lp(path))):
            self.check_run()
            h.update(b)
            self.vf["bytes_done"] += len(b)
        return h.hexdigest()

    def _verify_thread(self, targets, mode, sweep):
        with SemSono():
            self._verify_thread2(targets, mode, sweep)

    def _verify_thread2(self, targets, mode, sweep):
        try:
            self.log("Verificação %s iniciada (%d arquivos)." % (mode, len(targets)))
            try:
                if hasattr(os, "sync"):
                    os.sync()
                if not IS_WIN and os.geteuid() == 0:
                    with open("/proc/sys/vm/drop_caches", "w") as f:
                        f.write("3")
            except Exception:
                pass
            for it in targets:
                self.check_run()
                self.vf["current"] = it.disp
                dst = self.dst_of(it)
                try:
                    st = os.stat(lp(dst))
                    if st.st_size != it.size:
                        raise ValueError("tamanho")
                    if mode == "completa":
                        if not it.sha:
                            it.sha = self.hash_file(it.src)
                        if self.hash_file(dst, True) != it.sha:
                            raise ValueError("hash")
                    it.ver = True
                except ValueError as e:
                    it.status, it.cause = "falha", "divergente"
                    it.err = "ERRO: O arquivo no destino não confere com o original (%s diferente)" % ("tamanho" if str(e) == "tamanho" else "conteúdo/hash")
                    self.vf["fail"] += 1
                    self.log("DIVERGENTE: %s" % it.disp)
                except OSError as e:
                    it.status = "falha"
                    it.cause, it.err = classify_err(e)
                    self.vf["fail"] += 1
                    self.log("FALHA na verificação: %s -> %s" % (it.disp, it.err))
                self.vf["done"] += 1
            self.verified_mode = mode
            if sweep:
                self.phase = "verifying"
                self.vf["current"] = "Varredura final da origem..."
                self._sweep()
            self.phase = "verified"
            self.log("Verificação terminou: %d falhas." % self.vf["fail"])
        except Cancelled:
            self.phase = "copied"
            self.log("Verificação cancelada.")
        except Exception:
            self.error = traceback.format_exc()
            self.phase = "error"
            self.log("ERRO na verificação: " + self.error.splitlines()[-1])

    def _sweep(self):
        """Nova passada na origem: o que apareceu, mudou ou sumiu desde o escaneamento."""
        known = {}
        for it in self.items:
            known[it.disp] = it
        seen = set()
        novos, alterados = [], []
        n_novos = n_alt = 0
        planos = [pl for src in self.cfg["sources"] for pl in self.plan_roots(src)] + list(self.extras_planos)
        for plan in planos:
            for real, disp, name, st, local, _m in self.walk_plan(plan):
                if plan[4] == "extra" and name.lower() in self.PULA_SEMPRE:
                    continue
                it = known.get(disp)
                if it is None:
                    cat, act, mot, _x = classify_file(name, st.st_size, False)
                    if act != "ignorar":
                        n_novos += 1
                        if len(novos) < 500:
                            novos.append([disp, st.st_size, "Arquivo novo (apareceu depois do escaneamento)"])
                    continue
                seen.add(disp)
                if it.inc and (st.st_size != it.size or abs(st.st_mtime - it.mtime) > 2) and it.status == "ok":
                    n_alt += 1
                    if len(alterados) < 500:
                        alterados.append([disp, st.st_size, "Mudou durante o backup (a cópia é a versão do momento em que foi lida)"])
        sumiram = [it.disp for it in self.items if it.disp not in seen and it.cat != "Navegadores"]
        self.sweep = {"novos": novos, "n_novos": n_novos, "alterados": alterados, "n_alterados": n_alt,
                      "sumiram": sumiram[:500], "n_sumiram": len(sumiram), "quando": now_iso()}
        self.log("Varredura final: %d novos, %d alterados, %d sumiram." % (n_novos, n_alt, len(sumiram)))

    def start_retry(self):
        for it in self.items:
            if it.inc and it.status == "falha":
                try:
                    os.remove(lp(self.dst_of(it)))
                except OSError:
                    pass
                it.status = None
                it.ver = False
        queue_exists = any(it.inc and it.status is None for it in self.items)
        if not queue_exists:
            raise ValueError("Não há falhas para refazer.")
        self.start_copy(retry_only=False)

    # ------------------------------------------------------------------ resumo / relatório
    def left_behind(self):
        agg = {}
        for it in self.items:
            st = self.final_status(it)
            if st in ("ignorado", "revisar", "desmarcado", "em_uso"):
                k = (st, MOTIVO_EM_USO % programa_de(it.disp) if st == "em_uso" else it.motivo if st != "desmarcado" else "Desmarcado por você na seleção")
                e = agg.setdefault(k, [0, 0])
                e[0] += 1
                e[1] += it.size
        out = [{"situacao": k[0], "motivo": k[1], "n": v[0], "bytes": v[1]} for k, v in agg.items()]
        out.sort(key=lambda x: -x["bytes"])
        return out

    def failures(self):
        """Só as falhas de verdade; arquivo de programa em uso fora do pessoal vai em falhas_agrupadas()."""
        out = []
        for i, it in enumerate(self.items):
            if it.inc and it.status == "falha" and not falha_esperada(it):
                out.append({"idx": i, "disp": it.disp, "size": it.size, "err": it.err, "cause": it.cause})
        return out

    def falhas_agrupadas(self, grupo="", off=0, limit=50):
        """Falhas de verdade (pessoais) e as esperadas agrupadas por causa e programa, com página de arquivos de um grupo."""
        reais, grupos = [], {}
        for i, it in enumerate(self.items):
            if not (it.inc and it.status == "falha"):
                continue
            if not falha_esperada(it):
                reais.append(i)
                continue
            k = it.cause + "|" + programa_de(it.disp)
            g = grupos.setdefault(k, {"chave": k, "causa": it.cause, "programa": programa_de(it.disp), "n": 0, "bytes": 0, "idx": []})
            g["n"] += 1
            g["bytes"] += it.size
            g["idx"].append(i)
        linha = lambda i: {"idx": i, "disp": self.items[i].disp, "size": self.items[i].size, "err": self.items[i].err, "cause": self.items[i].cause,
                           "cat": self.items[i].cat}
        gl = sorted(grupos.values(), key=lambda g: -g["n"])
        out = {"admin": eh_admin(), "n_reais": len(reais), "n_esperadas": sum(g["n"] for g in gl), "bytes_esperadas": sum(g["bytes"] for g in gl),
               "grupos": [dict({k: v for k, v in g.items() if k != "idx"}, ex=[linha(i) for i in g["idx"][:3]]) for g in gl]}
        if grupo == "reais":
            out["pagina"] = [linha(i) for i in reais[off:off + limit]]
        elif grupo in grupos:
            out["pagina"] = [linha(i) for i in grupos[grupo]["idx"][off:off + limit]]
        else:
            out["pagina"] = [linha(i) for i in reais[:limit]]
        return out

    def desmarcar_esperadas(self, grupo=""):
        """Tira do backup os arquivos em uso de um grupo (ou de todos): ficam registrados como não escolhidos."""
        n = 0
        for it in self.items:
            if it.inc and falha_esperada(it) and (not grupo or it.cause + "|" + programa_de(it.disp) == grupo):
                it.inc = False
                n += 1
        return {"n": n}

    def _ritmo(self):
        """Velocidade (bytes/s nos últimos ~10 s) e tempo restante da cópia ou da verificação."""
        now = time.time()
        speed, eta = 0, 0
        if self.phase == "copying":
            cur = self.cp["done_bytes"]
            self.samples.append((now, cur))
        elif self.phase == "verifying":
            cur = self.vf["bytes_done"]
            self.samples.append((now, cur))
        else:
            cur = 0
        if self.samples and self.phase in ("copying", "verifying"):
            t0, b0 = self.samples[0]
            for s in self.samples:
                if now - s[0] <= 10:
                    t0, b0 = s
                    break
            if now - t0 > 0.5:
                speed = max(0, (cur - b0) / (now - t0))
            tot = self.cp["total_bytes"] if self.phase == "copying" else self.vf["bytes_total"]
            if speed > 0 and tot:
                eta = max(0, (tot - cur) / speed)
        return speed, eta

    def andamento(self):
        """Resumo leve do backup para a ilha do topo (sem log nem lista de falhas). None quando nada está rodando."""
        ph = self.phase
        if ph not in FASE_BACKUP:
            return None
        speed, eta = self._ritmo()
        a = {"id": "backup", "titulo": FASE_BACKUP[ph], "fase": ph, "tela": "backup", "pausado": not self.run_ev.is_set(),
             "velocidade": speed, "eta": eta, "pct": None, "detalhe": "", "info": ""}
        if ph == "scanning":
            a.update(detalhe=self.scan_info["current"], info="%d arquivos achados" % self.scan_info["files"])
        elif ph == "copying":
            c = self.cp
            a.update(pct=_pct(c["done_bytes"], c["total_bytes"]), detalhe=c["current"], info="%d de %d arquivos" % (c["done_files"], c["total_files"]))
        elif ph == "verifying":
            v = self.vf
            a.update(pct=_pct(v["bytes_done"], v["bytes_total"]) if v["bytes_total"] else _pct(v["done"], v["total"]), detalhe=v["current"],
                     info="%d de %d arquivos" % (v["done"], v["total"]))
        return a

    def status(self):
        speed, eta = self._ritmo()
        return {
            "phase": self.phase, "paused": not self.run_ev.is_set(), "error": self.error, "scan": self.scan_info, "copy": self.cp, "verify": self.vf,
            "speed": speed, "eta": eta, "log": list(self.logs)[-60:], "cfg": self.cfg, "sweep": self.sweep, "verified_mode": self.verified_mode,
            "n_items": len(self.items), "finished": self.finished, "cert": self.cert, "dest_root": self.dest_root,
            "same_disk": getattr(self, "same_disk", False), "failures": self.failures()[:300] if self.phase in ("copied", "verified", "done") else [],
            "n_failures": sum(1 for it in self.items if it.inc and it.status == "falha" and not falha_esperada(it)),
            "n_em_uso": sum(1 for it in self.items if it.inc and falha_esperada(it)), "admin": eh_admin(), "alertas": self.alertas_ativas(),
        }

    # ------------------------------------------------------------------ mapa e certificado
    def finish(self):
        with self.lock:
            if self.busy():
                raise Busy("Aguarde o processo atual terminar.")
            if self.phase not in ("verified", "done") and not (SU["ligado"] and self.phase == "copied"):
                raise ValueError("Rode a verificação antes de concluir.")
            if self.phase == "copied":
                self.log("SUPERUSUÁRIO: verificação pulada; o certificado sai como não verificado.")
            self.phase = "finishing"
        try:
            self._write_mapa()
            self.phase = "done"
            self.finished = True
            try:
                if FICHA:
                    c = self.cert
                    guardado = self._guardar_mapa(c["codigo"])
                    FICHA.hist_add(FICHA.machine_id_cache(), "backup", "Backup %s: %d arquivos (%s) · código %s" % ("sem falhas" if c["status"] == "sem_falhas" else "com ressalvas", c["copiados"], fmt_bytes(c["bytes"]), c["codigo"]),
                                   {"destino": self.dest_root, "codigo": c["codigo"], "cliente": c.get("cliente", ""), "status": c["status"], "bytes": c["bytes"],
                                    "tecnico": c.get("tecnico", ""), "tecnico_perfil": c.get("tecnico_perfil") or {}, "mapa_registro": guardado})
            except Exception:
                pass
            return self.cert
        except Exception:
            self.error = traceback.format_exc()
            self.phase = "error"
            raise

    def retomar(self, mid):
        """Volta ao backup que ficou parado (programa fechado depois da verificação): recarrega o certificado do Mapa e
        só segue se o disco do backup está conectado e os arquivos continuam lá, com o mesmo tamanho."""
        if not FICHA or mid != FICHA.machine_id_cache():
            raise ValueError("Só dá para retomar o backup da máquina em que o Destrava! está aberto.")
        rec = lambda: 6 if FICHA.receita_valida(mid) else 5
        with self.lock:
            if self.phase in ("verified", "done") and self.cert and self.cert.get("maquina_id") == mid:
                return {"ok": True, "passo": rec() if self.phase == "done" else 5, "codigo": self.cert.get("codigo", "")}
            if self.busy():
                raise Busy("Já existe um processo em andamento.")
            ultimo = next((h for h in reversed(FICHA.hist_get(mid)) if h.get("tipo") == "backup"), None)
            if not ultimo:
                raise ValueError("Esta máquina não tem backup registrado para retomar.")
            x = ultimo.get("extra") or {}
            mp = os.path.join(x.get("destino") or "", "Mapa")
            if not os.path.isfile(os.path.join(mp, "dados.js")):
                raise ValueError("O disco do backup não está conectado (ou a pasta mudou): %s. Conecte o disco e tente de novo, ou encerre como incompleto e refaça o backup." % (x.get("destino") or "caminho não registrado"))
            with open(os.path.join(mp, "dados.js"), encoding="utf-8") as fh:
                d = json.loads(fh.read().strip()[len("window.BKP="):].rstrip(";"))
            with open(os.path.join(mp, "certificado.json"), encoding="utf-8") as fh:
                cert = json.load(fh)["cert"]
            meta, raiz = d.get("meta") or {}, os.path.dirname(mp)
            ruins = []
            for e in d.get("f") or []:
                if e[5] != "ok":
                    continue
                try:
                    if os.stat(lp(os.path.join(raiz, *str(e[1]).split("/")))).st_size != e[3]:
                        ruins.append(e[1])
                except OSError:
                    ruins.append(e[1])
            if ruins:
                raise ValueError("%d arquivo(s) do backup sumiram ou mudaram (ex.: %s). Não é seguro formatar: encerre como incompleto e refaça o backup." % (len(ruins), ruins[0]))
            self.reset()
            self.dest_root, self.mapa_dir, self.cert = raiz, mp, cert
            self.checagens = meta.get("checagens") or []
            self.layout_modo = (meta.get("layout") or {}).get("modo") or self.layout_modo
            self.verified_mode = "completa" if str(meta.get("verificacao", "")).startswith("SHA-256") else "rapida"
            self.same_disk = any(str(c.get("titulo", "")).startswith("Destino no MESMO disco") for c in self.checagens)
            self.phase, self.finished = "done", True
            self.log("Backup retomado do Mapa guardado (código %s): %d arquivos conferidos." % (cert.get("codigo", ""), sum(1 for e in d.get("f") or [] if e[5] == "ok")))
        return {"ok": True, "passo": rec(), "codigo": cert.get("codigo", "")}

    def _guardar_mapa(self, codigo):
        """Cópia do Mapa no registro da máquina (pendrive), para abrir mesmo sem o disco do backup."""
        try:
            raiz = os.path.join(FICHA.pasta(FICHA.machine_id_cache()), "mapas", safe_seg(codigo or now_iso().replace(":", "-")))
            shutil.copytree(self.mapa_dir, os.path.join(raiz, "Mapa"), dirs_exist_ok=True)
            return raiz
        except Exception as e:
            self.log("Aviso: não consegui guardar a cópia do Mapa no registro da máquina (%s)." % e)
            return ""

    def _write_mapa(self):
        os.makedirs(self.mapa_dir, exist_ok=True)
        cfg = self.cfg
        f = []
        c_ok = c_fail = c_left = n_uso = b_uso = 0
        b_ok = 0
        for it in self.items:
            st = self.final_status(it)
            if st == "pendente":
                st = "falha"
                it.err = it.err or "ERRO: Não chegou a ser copiado"
            if st == "ok":
                c_ok += 1
                b_ok += it.size
            elif st == "falha":
                c_fail += 1
            else:
                c_left += 1
                if st == "em_uso":
                    n_uso += 1
                    b_uso += it.size
            dst = it.rel if st in ("ok", "falha") else ""
            mot = "" if st == "ok" else (it.err if st == "falha" else MOTIVO_EM_USO % programa_de(it.disp) if st == "em_uso" else
                                          (it.motivo if st != "desmarcado" else "Desmarcado por você na seleção"))
            f.append([it.disp, dst, it.cat, it.size, ("%04d-%02d-%02d" % it.date) if it.date else "", st, it.tags, it.local, mot, it.sha, int(it.mtime),
                      it.cause if st == "falha" else ("nao_escolhido" if st == "desmarcado" else "em_uso_esperado" if st == "em_uso" else "")])
        sw = self.sweep or {}
        ressalvas = c_fail + int(sw.get("n_novos", 0)) + int(sw.get("n_alterados", 0)) + int(sw.get("n_sumiram", 0))
        status = "sem_falhas" if ressalvas == 0 else "ressalvas"
        meta = {
            "pc": cfg["equip"], "data": datetime.date.today().isoformat(), "raiz": self.dest_root, "dstRel": True,
            "verificacao": ("SHA-256 (completa, %s)" % disco.METODO) if self.verified_mode == "completa" else "Tamanho (rápida)" if self.verified_mode else "Não verificado (pulado no modo Superusuário)",
            "campos": ["origem", "destino_relativo", "categoria", "tamanho_bytes", "data", "situacao", "etiquetas", "usuario", "motivo", "sha256", "mtime_epoch", "causa"],
            "checagens": self.checagens, "maes": sorted({"/".join(it.rel.split("/")[:2]) for it in self.items if it.inc and it.rel.startswith(PASTA_ORIGEM + "/")}),
            "layout": self._layout_registro(),
            "ign_dirs": self.ign_dirs[:300], "ign_dirs_total": self.ign_dirs_total,
            "versao": VERSION,
        }
        left = self.left_behind()
        cert = {
            "status": status, "cliente": cfg["cliente"], "tecnico": cfg["tecnico"], "equipamento": cfg["equip"],
            "data": meta["data"], "hora": datetime.datetime.now().strftime("%H:%M"), "metodo": meta["verificacao"],
            "copiados": c_ok, "bytes": b_ok, "falhas": c_fail, "ficaram": c_left, "pastas_ign": self.ign_dirs_total, "layout": meta["layout"],
            "nao_copiados_em_uso": {"n": n_uso, "bytes": b_uso}, "eventos": list(self.eventos)[:30],
            "motivos": left[:12], "sweep": {k: sw.get(k, 0) for k in ("n_novos", "n_alterados", "n_sumiram")},
            "sistema": "%s %s" % (platform.system(), platform.release()), "versao": VERSION,
        }
        tp = PERFIL.snapshot()
        if tp:
            cert["tecnico_perfil"] = tp
            cert["tecnico"] = cert["tecnico"] or tp.get("nome", "")
        try:  # "O que manter" feito antes de concluir: o certificado lista os programas a reinstalar (só nomes, sem versão)
            rec = FICHA.receita_valida(FICHA.machine_id_cache()) if FICHA else None
            if rec:
                cert["programas_resumo"] = {"n": len(rec["itens"]), "nomes": [i["nome"] for i in rec["itens"]]}
        except Exception:
            pass
        try:
            if FICHA and TERMO:
                mid = FICHA.machine_id_cache()
                st = TERMO.status(mid)
                osr = TERMO.os_atual(mid) or {}
                cert.update({"maquina_id": mid, "maquina_nome": FICHA.nome_exibicao(mid), "dono": st.get("dono", ""), "dono_nome": st.get("terceiro_nome", ""),
                             "os": osr.get("os", ""), "autorizou": osr.get("cliente", ""), "recuperado_bytes": REC["bytes"]})
        except Exception:
            pass
        meta["cert"] = cert
        body = "window.BKP=" + json.dumps({"meta": meta, "f": f}, ensure_ascii=False, separators=(",", ":")) + ";"
        dados = os.path.join(self.mapa_dir, "dados.js")
        with open(dados, "w", encoding="utf-8") as fh:
            fh.write(body)
        code = hashlib.sha256(body.encode("utf-8")).hexdigest()[:16].upper()
        cert["codigo"] = "-".join(code[i:i + 4] for i in range(0, 16, 4))
        meta["cert"] = cert
        body = "window.BKP=" + json.dumps({"meta": meta, "f": f}, ensure_ascii=False, separators=(",", ":")) + ";"
        # o código é calculado sobre os dados SEM o próprio código; gravamos também o hash do arquivo final
        with open(dados, "w", encoding="utf-8") as fh:
            fh.write(body)
        cert["base_hash"] = hashlib.sha256(body.encode("utf-8")).hexdigest()
        with open(os.path.join(self.mapa_dir, "certificado.json"), "w", encoding="utf-8") as fh:
            json.dump({"codigo": cert["codigo"], "dados_js_sha256": cert["base_hash"], "cert": cert}, fh, ensure_ascii=False, indent=1)
        with open(os.path.join(self.mapa_dir, "Relatorio.csv"), "w", encoding="utf-8-sig", newline="") as fh:
            w = csv.writer(fh, delimiter=";")
            w.writerow(["Situacao", "Categoria", "Etiquetas", "Tamanho_bytes", "Data", "Origem", "Destino_relativo", "Motivo", "SHA256"])
            for r in f:
                w.writerow([r[5], r[2], r[6], r[3], r[4], r[0], r[1], r[8], r[9]])
        for nm in ("visualizador.html", "logo.js"):
            shutil.copyfile(os.path.join(WEB, nm), os.path.join(self.mapa_dir, nm))
        try:
            shutil.copyfile(os.path.join(HERE, "etiquetas.txt"), os.path.join(self.mapa_dir, "etiquetas.txt"))
        except OSError:
            pass
        # inventário de programas do Windows
        progs = []
        for src in cfg["sources"]:
            if src["kind"] == "windows":
                for pf in ("Program Files", "Program Files (x86)"):
                    for n in sorted(safe_listdir(os.path.join(src["path"], pf))):
                        progs.append("%s:\\%s\\%s" % (src["letter"], pf, n))
        if progs:
            with open(os.path.join(self.mapa_dir, "programas_instalados.txt"), "w", encoding="utf-8") as fh:
                fh.write("Programas encontrados nas pastas Program Files (nomes das pastas)\n\n" + "\n".join(progs) + "\n")
        with open(os.path.join(self.mapa_dir, "LEIA-ME_CLAUDE.txt"), "w", encoding="utf-8") as fh:
            fh.write(LEIAME)
        self.cert = cert
        self.log("Mapa e certificado gerados em %s (código %s)." % (self.mapa_dir, cert["codigo"]))

    # ------------------------------------------------------------------ formatação
    def firmware_gate(self):
        if not self.cert:
            return False, "Conclua o backup e gere o certificado primeiro."
        if self.cert["status"] != "sem_falhas":
            return False, "O certificado tem ressalvas. Resolva as falhas (ou refaça) antes de formatar."
        if getattr(self, "same_disk", False):
            return False, "O backup está no mesmo disco físico de uma origem. Formatar apagaria o backup."
        if self.verified_mode != "completa":
            return False, "Faça a verificação COMPLETA (SHA-256 lido do disco) antes de formatar."
        if FICHA and not FICHA.receita_valida(FICHA.machine_id_cache()):
            return False, "Falta a etapa “O que manter”: escolha os programas a reinstalar (ou confirme que não vai manter nenhum)."
        return True, ""

    def firmware_reboot(self, forcar=False):
        ok, why = self.firmware_gate()
        if not ok:
            if not (forcar and SU["ligado"]):
                raise ValueError(why)
            self.log("SUPERUSUÁRIO: formatação liberada apesar do bloqueio: %s" % why)
            try:
                if FICHA:
                    FICHA.hist_add(FICHA.machine_id_cache(), "superusuario", "Bloqueio de formatar ignorado no modo Superusuário: %s" % why)
            except Exception:
                pass
        if sys.platform == "darwin":
            raise ValueError("No Mac este botão não é suportado: reinicie segurando Command+R (Recuperação) ou Option (escolher disco).")
        try:
            if FICHA:
                FICHA.hist_add(FICHA.machine_id_cache(), "formatacao", "Reinício para BIOS/UEFI solicitado para formatar (%s, código %s)" % ("backup verificado" if ok else "liberado pelo Superusuário", (self.cert or {}).get("codigo", "")))
        except Exception:
            pass
        if os.environ.get("DD_TEST"):
            return {"ok": True, "simulado": True}
        if IS_WIN:
            subprocess.Popen(["shutdown", "/r", "/fw", "/t", "15"])
        else:
            cmd = "systemctl reboot --firmware-setup"
            if hasattr(os, "geteuid") and os.geteuid() != 0:
                cmd = "sudo -n " + cmd
            subprocess.Popen(["sh", "-c", "sleep 8; " + cmd])
        return {"ok": True, "uefi": (os.path.exists("/sys/firmware/efi") if not IS_WIN else None)}


def _ler(p):
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(CHUNK), b""):
            yield b


def teste_destino(pasta, mb):
    """Grava mb MB em blocos únicos (pega disco falsificado que 'dá a volta'), relê DO DISCO e compara. (MB, MB/s)"""
    mb = max(16, (int(mb) // 4) * 4)
    base = os.urandom(4 * 1024 * 1024)
    arqs = [os.path.join(pasta, ".dd_teste_%d.tmp" % i) for i in range(4)]
    por, hashes = mb // 4, []
    t0 = time.time()
    try:
        for n, a in enumerate(arqs):
            h = hashlib.sha256()
            with open(a, "wb") as f:
                for k in range(por // 4):
                    blk = struct.pack(">QQ", n, k) + base[16:]
                    f.write(blk)
                    h.update(blk)
                f.flush()
                os.fsync(f.fileno())
            hashes.append(h.hexdigest())
        vel = mb / max(time.time() - t0, 1e-6)
        for a, h in zip(arqs, hashes):
            if disco.sha256(a) != h:
                raise ValueError("Releitura de %s não confere com o que foi gravado." % os.path.basename(a))
        return mb, vel
    finally:
        for a in arqs:
            try:
                os.remove(a)
            except OSError:
                pass


def saude_disco(path):
    """(True|False|None, texto) da saúde do disco que contém path (SMART/estado do Windows). None = não deu para ler."""
    try:
        if IS_WIN:
            letra = os.path.splitdrive(os.path.abspath(path))[0][:1]
            r = subprocess.run(["powershell", "-NoProfile", "-Command", "$d=Get-Partition -DriveLetter %s | Get-Disk | Get-PhysicalDisk; \"$($d.HealthStatus)|$($d.OperationalStatus)\"" % letra],
                               capture_output=True, text=True, timeout=30, creationflags=0x08000000)
            st = r.stdout.strip()
            if not st or st == "|":
                return None, "não informado"
            return (st.startswith("Healthy")), "Windows informa: %s" % st.replace("|", ", ")
        if sys.platform == "darwin":
            r = subprocess.run(["diskutil", "info", path], capture_output=True, text=True, timeout=20)
            m = re.search(r"SMART Status:\s*(.+)", r.stdout)
            if not m or "Not Supported" in m.group(1):
                return None, "não informado"
            return ("Verified" in m.group(1)), "SMART: %s" % m.group(1).strip()
        sm = shutil.which("smartctl")
        mt = mount_of(path)
        pdk = parent_disk(mt[0]) if mt else None
        if sm and pdk:
            r = subprocess.run([sm, "-H", "/dev/" + pdk], capture_output=True, text=True, timeout=20)
            linha = [x for x in r.stdout.splitlines() if "overall-health" in x or "SMART Health" in x]
            if linha:
                return ("PASSED" in linha[0] or "OK" in linha[0]), linha[0].strip()
    except Exception:
        pass
    return None, "não informado"


BITLOCKER_CHAVE = re.compile(r"^\d{6}(-\d{6}){7}$")


def bitlocker_trancados():
    """[{onde}] discos criptografados com BitLocker ainda trancados."""
    out = []
    try:
        if IS_WIN:
            r = subprocess.run(["powershell", "-NoProfile", "-Command", "Get-BitLockerVolume | Where-Object { $_.LockStatus -eq 'Locked' } | ForEach-Object { $_.MountPoint }"],
                               capture_output=True, text=True, timeout=30, creationflags=0x08000000)
            out = [{"onde": x.strip()} for x in r.stdout.splitlines() if re.match(r"^[A-Z]:$", x.strip())]
        elif shutil.which("lsblk"):
            d = json.loads(subprocess.run(["lsblk", "-J", "-o", "NAME,FSTYPE,MOUNTPOINT"], capture_output=True, text=True, timeout=20).stdout or "{}")
            pilha = list(d.get("blockdevices", []))
            while pilha:
                b = pilha.pop()
                pilha.extend(b.get("children") or [])
                if (b.get("fstype") or "").lower() == "bitlocker" and not b.get("mountpoint"):
                    out.append({"onde": "/dev/" + b["name"]})
    except Exception:
        pass
    return out


def destravar_bitlocker(onde, chave):
    """Destrava com a chave de recuperação. Windows: manage-bde. Linux: dislocker (montado só para leitura)."""
    chave = (chave or "").strip()
    if not BITLOCKER_CHAVE.match(chave):
        raise ValueError("A chave de recuperação tem 48 números em 8 grupos (ex.: 123456-123456-…).")
    if onde not in [b["onde"] for b in bitlocker_trancados()]:
        raise ValueError("Esse disco não está na lista de criptografados trancados.")
    if IS_WIN:
        r = subprocess.run(["manage-bde", "-unlock", onde, "-RecoveryPassword", chave], capture_output=True, text=True, timeout=120, creationflags=0x08000000)
        if r.returncode != 0:
            raise ValueError("O Windows recusou a chave: %s" % (r.stdout + r.stderr).strip()[-200:])
        return {"ok": True, "onde": onde}
    if not shutil.which("dislocker"):
        raise ValueError("Falta o programa dislocker neste Linux: conecte à internet e rode  sudo apt install dislocker  (ou destrave pelo próprio Windows).")
    nome = os.path.basename(onde)
    meio, ponto = "/mnt/destrava-bl-%s" % nome, "/media/destrava-bitlocker-%s" % nome
    os.makedirs(meio, exist_ok=True)
    os.makedirs(ponto, exist_ok=True)
    r = subprocess.run(["dislocker", "-V", onde, "-p" + chave, "--", meio], capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        raise ValueError("A chave não abriu o disco: %s" % (r.stdout + r.stderr).strip()[-200:])
    r = subprocess.run(["mount", "-o", "loop,ro", os.path.join(meio, "dislocker-file"), ponto], capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        raise ValueError("Destravou, mas não consegui montar: %s" % r.stderr.strip()[-200:])
    return {"ok": True, "onde": onde, "pasta": ponto}


def safe_listdir(p):
    try:
        return os.listdir(p)
    except OSError:
        return []


LEIAME = """D&D Technology - MAPA DO BACKUP
=================================
Este diretório (Mapa) descreve, arquivo por arquivo, ONDE CADA COISA ESTAVA e ONDE FICOU no backup.

Arquivos
  visualizador.html   abra com duplo clique (Chrome, Edge ou Firefox). Funciona offline.
  dados.js            o índice completo:  window.BKP = { meta:{...}, f:[ [...], [...] ] }
  Relatorio.csv       o mesmo índice em planilha (separador ; , UTF-8)
  certificado.json    código e números do certificado
  historico.log       registro do que foi feito
  etiquetas.txt       regras de etiquetas por palavra-chave usadas neste backup
  programas_instalados.txt   (se a origem era Windows) nomes das pastas em Program Files

Como o backup foi guardado (meta.layout.modo e o certificado dizem qual)
  Espelho   cada pasta como estava:  Pastas_origem/<Usuário>/<caminho a partir da pasta do usuário>
  Ordenado  por tipo e data:         <Usuário>/<Categoria>/<Ano>/<Mês>/<arquivo>
  Misto     espelhado, e o técnico escolheu o que ia ordenado (os dois formatos acima, lado a lado)
  Dados de programas, ocultos e sistemas guardam sempre o caminho original.
  No visualizador, "Agrupar por: Tipo e data" mostra tudo por Categoria > Ano > Mês, qualquer que seja o modo.

Campos de cada item de f (nesta ordem; meta.campos repete isto)
  0 origem            caminho ORIGINAL do arquivo na máquina (ex.: C:\\Users\\Maria\\Desktop\\x.docx)
  1 destino_relativo  caminho dentro da pasta do backup (separador /). Vazio se não foi copiado.
                      Caminho completo = (pasta do backup) + "/" + destino_relativo. A pasta do backup é a
                      pasta que CONTÉM esta pasta Mapa.
  2 categoria         Fotos, Videos, Audios, Documentos, Projetos, Email_Contatos, Conversas, Contas_Senhas, Outros, Navegadores
  3 tamanho_bytes
  4 data              AAAA-MM-DD usada para organizar (foto: data da foto; senão data no nome; senão data do arquivo)
  5 situacao          ok | falha | ignorado | revisar | desmarcado
                        ok          copiado e verificado
                        falha       tentou copiar e não conseguiu (veja o motivo)
                        ignorado    não é conteúdo pessoal (programa, sistema, temporário) - não copiado
                        revisar     tipo não reconhecido - não copiado
                        desmarcado  o técnico desmarcou na seleção - não copiado
  6 etiquetas         etiquetas por palavra-chave separadas por |  (ex.: Fiscal|Clientes)
  7 usuario           usuário/local de origem (ex.: Maria, Publico, Disco_D/Clientes)
  8 motivo            explicação para tudo que não for ok
  9 sha256            hash SHA-256 do conteúdo no momento da cópia (vazio se não copiado)
 10 mtime_epoch       data de modificação original (segundos desde 1970)

Como pedir ajuda ao Claude no futuro
  Envie este LEIA-ME e o Relatorio.csv (ou dados.js) e pergunte, por exemplo:
  "onde estava o arquivo contrato_silva.pdf?" ou "liste tudo que ficou para trás e por quê".

Conferir a autenticidade do certificado
  python3 dd_backup.py --verificar <esta pasta Mapa>
  python3 dd_backup.py --rehash <esta pasta Mapa>      (relê o backup e compara cada arquivo com o hash guardado)

Somos únicos. Somos diferentes. Somos D&D.
"""


# ----------------------------------------------------------------------------------------------
# Ficha da máquina (Destrava!)
# ----------------------------------------------------------------------------------------------
FT = {"rodando": False, "etapa": "", "pct": 0, "erro": "", "o_que": "", "resultado": None}
FT_LOCK = threading.Lock()


def ficha_iniciar(alvo, fn):
    with FT_LOCK:
        if FT["rodando"]:
            raise Busy("A ficha já está rodando.")
        FT.update({"rodando": True, "etapa": "Começando", "pct": 0, "erro": "", "o_que": alvo, "resultado": None})

    def cb(e, p):
        FT["etapa"], FT["pct"] = e, p

    def work():
        try:
            FT["resultado"] = fn(cb)
        except Exception:
            FT["erro"] = traceback.format_exc().splitlines()[-1]
        finally:
            FT["rodando"] = False
            FT["pct"] = 100

    threading.Thread(target=work, daemon=True).start()


FASE_BACKUP = {"scanning": "Escaneando para o backup", "copying": "Copiando o backup", "verifying": "Conferindo o backup",
               "finishing": "Gerando o Mapa e o certificado"}


def _pct(a, b):
    return max(0, min(100, int(a * 100 / b))) if b else None


def atividades():
    """O que está rodando agora, para a ilha do topo: só lê o estado que cada processo já mantém.
    fim: como cada fonte terminou da última vez (a tela usa na hora em que uma atividade some, para dizer se deu certo)."""
    out = []
    if FT["rodando"]:
        out.append({"id": "ficha", "titulo": "Aplicando melhorias" if FT["o_que"] == "aplicar" else "Analisando a máquina", "detalhe": FT["etapa"],
                    "pct": FT["pct"], "tela": "home"})
    bk = APP.andamento()
    if bk:
        out.append(bk)
    dst = DADOS.ST if DADOS else {}
    ac = dst.get("acao") or {}
    if ac.get("rodando"):
        out.append({"id": "dados", "titulo": {"limpar": "Limpando arquivos", "offload": "Movendo para outro disco", "mover": "Movendo arquivos", "copiar": "Copiando arquivos"}.get(ac.get("tipo"), "Organizando arquivos"),
                    "detalhe": ac.get("atual", ""), "pct": _pct(ac.get("bytes_feito", 0), ac.get("bytes_total", 0)) if ac.get("bytes_total") else _pct(ac.get("feito", 0), ac.get("total", 0)),
                    "info": "%d de %d" % (ac.get("feito", 0), ac.get("total", 0)), "tela": "dados"})
    elif dst.get("fase") == "varrendo":
        out.append({"id": "dados", "titulo": "Procurando o que pesa", "detalhe": dst.get("atual", ""), "pct": dst.get("pct"),
                    "info": "%d arquivos" % dst.get("arquivos", 0), "tela": "dados"})
    en = getattr(APP, "ensaio", None) or {}
    if en.get("rodando"):
        out.append({"id": "ensaio", "titulo": "Ensaiando a leitura dos arquivos", "pct": _pct(en.get("feitos", 0), en.get("total", 0)),
                    "info": "%d de %d" % (en.get("feitos", 0), en.get("total", 0)), "detalhe": "Só lê o começo de cada arquivo marcado", "tela": "backup"})
    inc = APP.incl or {}
    if inc.get("rodando"):
        out.append({"id": "incluir", "titulo": "Incluindo pastas no backup", "pct": None, "detalhe": inc.get("atual", ""),
                    "info": "%d arquivos (%s)" % (inc.get("arquivos", 0), fmt_bytes(inc.get("bytes", 0))), "tela": "backup"})
    md = APP.medicao or {}
    if md.get("rodando"):
        feito = sum(md.get("grupos", {}).values())
        out.append({"id": "medicao", "titulo": "Medindo o restante do disco", "pct": md.get("pct", 0), "detalhe": "Windows, programas e caches: só para explicar o espaço usado",
                    "info": "%s medidos" % fmt_bytes(feito), "tela": "backup"})
    cf = MAPA.CONF
    if cf.get("rodando"):
        out.append({"id": "conferencia", "titulo": "Conferindo o backup no disco", "pct": _pct(cf.get("feitos", 0), cf.get("total", 0)),
                    "info": "%d de %d" % (cf.get("feitos", 0), cf.get("total", 0)), "tela": "mapas"})
    con = SERVIDOR["con"]
    if con and getattr(con, "pendentes", None):
        out.append({"id": "envio", "titulo": "Enviando ao servidor", "pct": None, "info": "%d pendente(s)" % len(con.pendentes), "tela": ""})
    fim = {"ficha": {"erro": FT["erro"]}, "backup": {"fase": APP.phase, "erro": bool(APP.error)},
           "dados": {"fase": dst.get("fase", ""), "erros": len(ac.get("erros") or [])},
           "conferencia": {"diferentes": len(cf.get("diferentes") or []), "faltando": len(cf.get("faltando") or []), "erro": cf.get("erro", "")},
           "medicao": {"parcial": bool(md.get("parcial")), "feita": bool(md) and not md.get("rodando")},
           "incluir": {"erro": inc.get("erro", ""), "feita": bool(inc) and not inc.get("rodando")}}
    return {"atividades": out, "fim": fim, "alertas": APP.alertas_ativas()}


def ficha_coletar(fase):
    def fn(cb):
        f = FICHA.coletar(cb)
        FICHA.salvar_ficha(f, fase)
        return {"mid": f["mid"]}
    ficha_iniciar("coletar", fn)


def ficha_aplicar(ids):
    mid = FICHA.machine_id_cache()
    v = FICHA.visao(mid)
    if not v:
        raise ValueError("Colete a ficha antes de aplicar melhorias.")

    def fn(cb):
        cb("Aplicando melhorias", 10)
        res = FICHA.aplicar(mid, ids, v["ultima"])
        cb("Medindo de novo para provar o resultado", 40)
        f = FICHA.coletar(lambda e, p: cb(e, 40 + int(p * 0.6)), programas=False)
        FICHA.salvar_ficha(f, "depois")
        return {"mid": mid, "aplicadas": res}
    ficha_iniciar("aplicar", fn)


# ----------------------------------------------------------------------------------------------
# Servidor HTTP local
# ----------------------------------------------------------------------------------------------
APP = App()
# Modo Superusuário (ligado na engrenagem): abre qualquer etapa e pula travas do fluxo. Tudo o que ele faz vai para o registro.
SU = {"ligado": False}
SU_CAMPOS_CERT = (("cliente", "Cliente"), ("tecnico", "Técnico"), ("equipamento", "Equipamento"), ("data", "Data"), ("hora", "Hora"), ("status", "Situação"))


def exigir_su():
    if not SU["ligado"]:
        raise ValueError("Ligue o modo Superusuário em Configurações para fazer isto.")


def modelo_rapido():
    """Modelo comercial sem ficha (máquina ainda não analisada): Mac pelo hw.model, Linux pelo DMI. No Windows fica vazio
    (pedir ao WMI demora): a ficha preenche depois."""
    try:
        if sys.platform == "darwin":
            m = subprocess.run(["sysctl", "-n", "hw.model"], capture_output=True, text=True, timeout=3).stdout.strip()
            return FICHA.MODELOS_MAC.get(m, m) if FICHA else m
        if not IS_WIN:
            ler = lambda n: open("/sys/class/dmi/id/" + n, encoding="utf-8", errors="replace").read().strip()
            return (ler("sys_vendor") + " " + ler("product_name")).strip()
    except Exception:
        pass
    return ""


def identidade(para="dados", app=None):
    """Quem é esta máquina para o cabeçalho do cockpit: nome, modelo, dono (particular ou cliente) e as contas do sistema."""
    host = socket.gethostname()
    if sys.platform == "darwin":  # o nome que a pessoa deu ao Mac ("MacBook Air de Ana"), não o de rede ("…local")
        try:
            host = subprocess.run(["scutil", "--get", "ComputerName"], capture_output=True, text=True, timeout=3).stdout.strip() or host
        except Exception:
            pass
    out = {"host": host, "nome": host, "modelo": "", "dono": "", "dono_nome": "", "tecnico": "", "contas": []}
    try:
        mid = FICHA.machine_id_cache()
        meta = FICHA.meta_ler(mid)
        fichas = FICHA.listar_fichas(mid)
        ult = FICHA.ler_ficha(mid, fichas[-1]) if fichas else None
        out["modelo"] = (FICHA.modelo_comercial(ult) if ult else "") or modelo_rapido()
        if out["modelo"] == host:
            out["modelo"] = modelo_rapido()
        out["nome"] = meta.get("nome") or host
        st = TERMO.status(mid) if TERMO else {}
        out.update(dono=st.get("dono", ""), dono_nome=st.get("terceiro_nome", ""), tecnico=(PERFIL.ler().get("nome") or st.get("tecnico") or "").strip())
    except Exception:
        out["modelo"] = out["modelo"] or modelo_rapido()
    eu = os.path.basename(FICHA.user_home() if FICHA else os.path.expanduser("~"))
    nomes = []
    if para == "backup":
        for src in ((app or APP).cfg or {}).get("sources", []):
            nomes += detect_kind(src["path"])[1] if src["kind"] in ("windows", "linux", "mac") else [os.path.basename(src["path"].rstrip("/\\"))]
    elif DADOS:
        nomes = [u for u, _ in DADOS.homes()]
    vistos = set()
    for n in nomes:
        if n and n not in vistos:
            vistos.add(n)
            out["contas"].append({"nome": n, "em_uso": n == eu})
    return out


def su_estado():
    a = APP
    return {"ligado": SU["ligado"], "admin": eh_admin(), "so": "mac" if sys.platform == "darwin" else "windows" if IS_WIN else "linux",
            "phase": a.phase, "layout_modo": a.layout_modo, "layout_editavel": a.layout_editavel(), "verified_mode": a.verified_mode,
            "mapa_dir": a.mapa_dir if os.path.isfile(os.path.join(a.mapa_dir or "", "certificado.json")) else ""}


def su_certificado_ler():
    exigir_su()
    cj = os.path.join(APP.mapa_dir or "", "certificado.json")
    if not os.path.isfile(cj):
        raise ValueError("Ainda não há certificado gerado neste backup.")
    with open(cj, encoding="utf-8") as fh:
        c = json.load(fh)["cert"]
    return {"campos": [{"id": k, "nome": n, "valor": c.get(k, "")} for k, n in SU_CAMPOS_CERT], "editado": c.get("editado") or [], "codigo": c.get("codigo", "")}


def su_certificado_salvar(b):
    """Corrige campos do certificado já emitido. Guarda cópia .bak dos originais e deixa a edição marcada no próprio
    certificado (o código original não muda), para o cliente e o --verificar enxergarem que houve correção manual."""
    exigir_su()
    mp = APP.mapa_dir or ""
    cj, dj = os.path.join(mp, "certificado.json"), os.path.join(mp, "dados.js")
    if not (os.path.isfile(cj) and os.path.isfile(dj)):
        raise ValueError("Ainda não há certificado gerado neste backup.")
    with open(cj, encoding="utf-8") as fh:
        cjson = json.load(fh)
    with open(dj, encoding="utf-8") as fh:
        dados = json.loads(fh.read().strip()[len("window.BKP="):].rstrip(";"))
    cert, mudou = cjson["cert"], {}
    for k, _ in SU_CAMPOS_CERT:
        if k not in b:
            continue
        v = str(b[k]).strip()[:200]
        if k == "status" and v not in ("sem_falhas", "ressalvas"):
            raise ValueError("Situação inválida.")
        if v != str(cert.get(k, "")):
            mudou[k] = {"antes": cert.get(k, ""), "depois": v}
            cert[k] = v
    if not mudou:
        return {"ok": True, "mudou": 0}
    for p in (cj, dj):
        bak = p + ".bak"
        if not os.path.exists(bak):  # guarda só o original emitido
            shutil.copyfile(p, bak)
    cert.setdefault("editado", []).append({"quando": now_iso(), "por": "superusuário", "campos": mudou})
    dados.setdefault("meta", {})["cert"] = cert
    body = "window.BKP=" + json.dumps(dados, ensure_ascii=False, separators=(",", ":")) + ";"
    with open(dj, "w", encoding="utf-8") as fh:
        fh.write(body)
    cert["base_hash"] = hashlib.sha256(body.encode("utf-8")).hexdigest()
    cjson.update({"cert": cert, "dados_js_sha256": cert["base_hash"]})
    with open(cj, "w", encoding="utf-8") as fh:
        json.dump(cjson, fh, ensure_ascii=False, indent=1)
    if APP.cert and APP.cert.get("codigo") == cert.get("codigo"):
        APP.cert = cert
    APP.log("SUPERUSUÁRIO: certificado %s editado (%s)." % (cert.get("codigo", ""), ", ".join(mudou)))
    return {"ok": True, "mudou": len(mudou)}


def dados_depois(tipo):
    """Callback chamado quando uma ação de Dados termina: registra no histórico da máquina e no log."""
    def cb(res):
        try:
            mid = FICHA.machine_id_cache()
            moved = int(res.get("bytes_lixeira") or 0) + int(res.get("bytes_removidos") or 0) + int(res.get("bytes_movidos") or 0)
            REC["bytes"] += int(res.get("bytes_removidos") or 0)
            if tipo == "limpar":
                resumo = "Limpeza de dados: %d item(ns), %s %s" % (res["itens"], fmt_bytes(moved), "removidos de vez" if res["modo"] == "definitivo" else "enviados para a Lixeira")
            elif tipo in ("mover", "copiar"):
                moved = int(res.get("bytes") or 0)
                resumo = "%s: %d item(ns), %s para %s" % ("Arquivos movidos" if tipo == "mover" else "Arquivos copiados", res["itens"], fmt_bytes(moved), res.get("destino", ""))
            else:
                resumo = "Offload: %d item(ns), %s copiados e conferidos para %s" % (res["itens"], fmt_bytes(moved), res.get("destino", ""))
            FICHA.hist_add(mid, "limpeza", resumo, {"bytes": moved, "modo": res["modo"], "falhas": res["falhas"]})
            TERMO.log_add("dados_" + tipo, mid, itens=res["itens"], bytes=moved, modo=res["modo"], falhas=res["falhas"])
        except Exception:
            pass
    return cb


if DADOS and FICHA:
    DADOS.set_helpers(physical_id=physical_id, fs_type=fs_type, user_home=FICHA.user_home)
MIME = {".html": "text/html; charset=utf-8", ".js": "application/javascript; charset=utf-8", ".svg": "image/svg+xml", ".csv": "text/csv; charset=utf-8",
        ".json": "application/json", ".png": "image/png", ".txt": "text/plain; charset=utf-8", ".log": "text/plain; charset=utf-8"}


class Handler(BaseHTTPRequestHandler):
    server_version = "DDBackup/" + VERSION

    def log_message(self, *a):
        pass

    def _host_ok(self):
        return self.headers.get("Host", "") in APP.allowed_hosts

    def _json(self, obj, code=200):
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _baixar(self, data, mime, nome):
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Disposition", 'attachment; filename="%s"' % nome)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _static(self, base, name, troca=None):
        name = os.path.basename(name)
        p = os.path.join(base, name)
        if not name or not os.path.isfile(p):
            self.send_error(404)
            return
        with open(p, "rb") as fh:
            data = fh.read()
        for a, b in (troca or {}).items():
            data = data.replace(a, b)
        self.send_response(200)
        self.send_header("Content-Type", MIME.get(os.path.splitext(name)[1].lower(), "application/octet-stream"))
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _arquivo(self, path, mime, limite=None, pagina=False):
        """Envia um arquivo do cliente para a prévia. Nunca vira página do programa: nosniff e CSP sandbox."""
        tam = os.path.getsize(lp(path))
        if limite:
            tam = min(tam, limite)
        ini, fim, code = 0, max(0, tam - 1), 200
        m = re.match(r"^bytes=(\d*)-(\d*)$", (self.headers.get("Range") or "").strip())
        if m and tam and not limite and (m.group(1) or m.group(2)):
            a, b = m.groups()
            if a:
                ini, fim = int(a), min(int(b), tam - 1) if b else tam - 1
            else:
                ini = max(0, tam - int(b))
            if ini > fim:
                self.send_response(416)
                self.send_header("Content-Range", "bytes */%d" % tam)
                self.end_headers()
                return
            code = 206
        n = fim - ini + 1 if tam else 0
        self.send_response(code)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(n))
        self.send_header("Accept-Ranges", "bytes")
        if code == 206:
            self.send_header("Content-Range", "bytes %d-%d/%d" % (ini, fim, tam))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Disposition", "inline")
        if not pagina:
            self.send_header("Content-Security-Policy", "sandbox; default-src 'none'; img-src 'self'; media-src 'self'; style-src 'unsafe-inline'")
        self.end_headers()
        try:
            with open(lp(path), "rb") as fh:
                fh.seek(ini)
                while n > 0:
                    b = fh.read(min(CHUNK, n))
                    if not b:
                        break
                    self.wfile.write(b)
                    n -= len(b)
        except (BrokenPipeError, ConnectionResetError):
            pass  # o navegador cancela pedidos de vídeo o tempo todo (ao avançar)

    def _auth(self, q):
        tok = self.headers.get("X-DD-Token") or (q.get("t") or [""])[0]
        return secrets.compare_digest(tok, APP.token)

    def do_GET(self):
        if not self._host_ok():
            self.send_error(403)
            return
        u = urlparse(self.path)
        q = parse_qs(u.query)
        path = u.path
        if path in ("/", "/index.html"):
            # no Docker o endereço é só http://localhost:8080 (sem #token): a página já vem com o token
            tok = APP.token if APP.token_na_pagina else ""
            return self._static(WEB, "app.html", {b"__DD_TOKEN__": tok.encode("ascii")})
        if path.startswith("/web/"):
            return self._static(WEB, path[5:])
        if path.startswith("/mapa/"):
            pasta = MAPA.M["mapa"] or APP.mapa_dir  # o Mapa aberto em "Mapas" (ou o do backup desta sessão)
            nm = os.path.basename(path[6:])
            if nm in ("visualizador.html", "logo.js"):
                return self._static(WEB, nm)  # sempre a tela atual, não a cópia guardada no Mapa
            if not pasta or not os.path.isdir(pasta) or nm not in ("dados.js", "Relatorio.csv", "certificado.json"):
                self.send_error(404)
                return
            return self._static(pasta, nm)
        if not path.startswith("/api/"):
            self.send_error(404)
            return
        if not self._auth(q):
            return self._json({"erro": "não autorizado"}, 401)
        if path == "/api/mapa/ver":
            try:
                arq, mime, tipo, limite = MAPA.previa((q.get("i") or [""])[0])
            except ValueError as e:
                return self._json({"erro": str(e)}, 400)
            return self._arquivo(arq, mime, limite, pagina=(tipo == "pdf"))
        if path == "/api/files/ver":  # prévia na lista do backup, só pelo índice (o token vem em ?t=, como em /api/dados/ver)
            try:
                arq, mime, tipo, limite = APP.previa((q.get("i") or [""])[0])
            except ValueError as e:
                return self._json({"erro": str(e)}, 400)
            return self._arquivo(arq, mime, limite, pagina=(tipo == "pdf"))
        if path == "/api/dados/ver":  # <img>/<video> não mandam cabeçalho: o token vem em ?t=
            try:
                arq, mime, tipo, limite = DADOS.previa((q.get("no") or [""])[0])
            except ValueError as e:
                return self._json({"erro": str(e)}, 400)
            return self._arquivo(arq, mime, limite, pagina=(tipo == "pdf"))
        try:
            return self._json(self.api_get(path, q))
        except Exception as e:
            if not isinstance(e, (ValueError, Busy, PermissionError, KeyError)):
                registrar_erro("GET " + path)
            return self._json({"erro": str(e)}, 400)

    def do_POST(self):
        if not self._host_ok():
            self.send_error(403)
            return
        u = urlparse(self.path)
        if not self._auth(parse_qs(u.query)):
            return self._json({"erro": "não autorizado"}, 401)
        n = int(self.headers.get("Content-Length", 0) or 0)
        body = {}
        if u.path != "/api/atualizar/enviar":
            try:
                body = json.loads(self.rfile.read(n).decode("utf-8") or "{}") if n else {}
            except ValueError:
                body = {}
        try:
            if u.path == "/api/atualizar/enviar":
                return self._json(self.upload_zip(n, parse_qs(u.query)))
            if u.path == "/api/maquinas/exportar":  # só códigos vêm da tela; a planilha volta como download
                mids = body.get("mids")
                dados = FICHA.exportar_csv([str(m) for m in mids] if isinstance(mids, list) else None)
                return self._baixar(dados, "text/csv; charset=utf-8", "maquinas-%s.csv" % time.strftime("%Y-%m-%d"))
            return self._json(self.api_post(u.path, body))
        except PermissionError as e:
            if TERMO and isinstance(e, TERMO.SemPermissao):
                cod = str(e)
                if cod == "termo":
                    return self._json({"erro": "Aceite o termo de responsabilidade para continuar.", "codigo": "termo"}, 403)
            return self._json({"erro": str(e)}, 403)
        except (Busy, ValueError) as e:
            return self._json({"erro": str(e)}, 400)
        except Exception as e:
            if type(e).__name__ in ("SemConexao", "ErroServidor"):
                return self._json({"erro": str(e)}, 503)
            APP.log("ERRO interno: %s" % e)
            registrar_erro("POST " + self.path.split("?")[0])
            return self._json({"erro": "Erro interno: %s" % e}, 500)

    # ---------------------------------------------------------------- permissões e upload
    def exigir(self, escopo=None):
        if TERMO and FICHA:
            TERMO.exigir(FICHA.machine_id_cache(), escopo)

    def upload_zip(self, n, q):
        if not ATUAL:
            raise ValueError("Atualizador ausente.")
        if SERVIDOR["con"]:
            raise ValueError("No modo servidor o programa já vem atualizado do servidor.")
        if n <= 0 or n > ATUAL.MAX_ZIP:
            raise ValueError("Arquivo inválido ou grande demais.")
        dest = os.path.join(HERE, "_novo_upload.zip")
        rest = n
        with open(dest, "wb") as fh:
            while rest > 0:
                b = self.rfile.read(min(1 << 20, rest))
                if not b:
                    break
                fh.write(b)
                rest -= len(b)
        pref, v, arqs = ATUAL.inspecionar(dest)
        return {"caminho": dest, "versao": v, "arquivos": len(arqs), "sha256": ATUAL.sha256(dest)}

    # ---------------------------------------------------------------- rotas
    def api_get(self, path, q):
        if path == "/api/perfil":
            return {"perfil": PERFIL.ler(), "campos": PERFIL.CAMPOS, "certificado": PERFIL.snapshot()}
        if path == "/api/termo":
            mid = FICHA.machine_id_cache()
            return {"mid": mid, "host": socket.gethostname(), "nome": FICHA.nome_exibicao(mid), "status": TERMO.status(mid), "corporativa": TERMO.detectar_corporativa(),
                    "clausulas": TERMO.clausulas(), "rodape": TERMO.RODAPE, "versao": TERMO.TERMO_VERSAO, "selo": TERMO.termo_hash()[:16],
                    "escopos": [{"id": a, "nome": b, "desc": c} for a, b, c in TERMO.ESCOPOS], "os": TERMO.os_atual(mid), "log": TERMO.log_verificar()}
        if path == "/api/ficha/lista":
            mid = (q.get("mid") or [""])[0] or FICHA.machine_id_cache()
            return {"mid": mid, "fichas": FICHA.fichas_info(mid), "historico": FICHA.hist_get(mid)}
        if path == "/api/ficha/comparar":
            mid = (q.get("mid") or [""])[0] or FICHA.machine_id_cache()
            return FICHA.comparar(mid, (q.get("a") or [""])[0], (q.get("b") or [""])[0])
        if path == "/api/permissoes":
            if FICHA and FICHA.simulando():  # coleta salva: as permissões são as da máquina reproduzida
                fam = FICHA.familia_atual()
                return {"mac": fam == "mac", "win": fam == "windows", "linux": fam == "linux", "root": True, "admin": True, "acesso_total": True, "simulacao": True}
            mac = sys.platform == "darwin"
            adm = False
            if IS_WIN:
                try:
                    import ctypes
                    adm = bool(ctypes.windll.shell32.IsUserAnAdmin())
                except Exception:
                    adm = False
            return {"mac": mac, "win": IS_WIN, "linux": (not mac and not IS_WIN), "root": FICHA.is_root() if FICHA else False, "admin": adm,
                    "acesso_total": DADOS.acesso_total_mac() if DADOS else True}
        if path == "/api/dados/estado":
            return DADOS.estado()
        if path == "/api/dados/resultado":
            g = lambda k: (q.get(k) or [""])[0]
            return DADOS.resultado(g("zona"), g("cat"), g("q"), int(g("offset") or 0), int(g("limit") or 200), g("usuario"))
        if path == "/api/dados/panorama":
            self.exigir(None)
            return DADOS.indice_panorama((q.get("usuario") or [""])[0])
        if path == "/api/dados/indice":
            self.exigir(None)
            g = lambda k: (q.get(k) or [""])[0]
            return DADOS.indice_consulta(faixa=g("faixa") or g("bloco"), cat=g("cat"), pasta=g("pasta") or None, usuario=g("usuario"), q=g("q"), ordem=g("ordem") or "maior",
                                         offset=int(g("offset") or 0), limit=int(g("limit") if g("limit") != "" else 200), visao=g("visao") or "arquivos",
                                         grupo=g("grupo"), sug=g("sug"), tipo=g("tipo"), tam=g("tam"), uso=g("uso"), facetas=g("facetas") in ("1", "true"))
        if path == "/api/mapa/lista":
            return {"mapas": mapas_conhecidos(), "aberto": MAPA.resumo() if MAPA.M["mapa"] else None}
        if path == "/api/mapa/arvore":
            return MAPA.arvore((q.get("pasta") or [""])[0])
        if path == "/api/mapa/buscar":
            g = lambda k: (q.get(k) or [""])[0]
            return MAPA.buscar(g("q"), g("situacao"), g("cat"), g("usuario"), int(g("offset") or 0))
        if path == "/api/mapa/conferencia":
            return MAPA.estado_conferencia()
        if path == "/api/layout":
            return APP.layout_resumo()
        if path == "/api/identidade":
            return identidade((q.get("para") or ["dados"])[0])
        if path == "/api/classes":
            return CLS.para_tela()
        if path == "/api/destino":
            return APP.destino(int((q.get("i") or ["-1"])[0]))
        if path == "/api/su":
            return su_estado()
        if path == "/api/su/certificado":
            return su_certificado_ler()
        if path == "/api/mapa/certificado":
            return MAPA.certificado()
        if path == "/api/dados/explorar":
            self.exigir(None)
            g = lambda k: (q.get(k) or [""])[0]
            return DADOS.explorar(g("no") or None, g("item") or None)
        if path == "/api/atualizar/procurar":
            if SERVIDOR["con"]:  # no modo servidor o programa já vem na versão do servidor
                return {"versao": VERSION, "encontrados": [], "salvas": [], "servidor": True}
            return {"versao": VERSION, "encontrados": ATUAL.procurar(VERSION), "salvas": ATUAL.versoes_salvas()}
        if path == "/api/info":
            return {"host": socket.gethostname(), "os": "%s %s" % (platform.system(), platform.release()), "win": IS_WIN, "versao": VERSION,
                    "home": os.path.expanduser("~"), "uefi": (os.path.exists("/sys/firmware/efi") if not IS_WIN else None),
                    "simulacao": bool(FICHA and FICHA.simulando()), "dados": DADOS_DIR[0],
                    "servidor": SERVIDOR["con"].estado() if SERVIDOR["con"] else None}
        if path == "/api/sources":
            return {"sources": list_sources()}
        if path == "/api/ls":
            p = (q.get("path") or [""])[0]
            if not p:
                return {"path": "", "parent": "", "dirs": roots_for_browse(), "free": 0, "total": 0, "fs": ""}
            p = os.path.abspath(os.path.expanduser(p))
            dirs = []
            for n in sorted(safe_listdir(p), key=lambda s: s.lower()):
                fp = os.path.join(p, n)
                if os.path.isdir(fp) and not n.startswith("."):
                    dirs.append({"name": n, "path": fp})
            total, free = disk_usage(p)
            parent = os.path.dirname(p)
            kind, users = detect_kind(p)
            return {"path": p, "parent": parent if parent != p else "", "dirs": dirs, "free": free, "total": total, "fs": fs_type(p) or "", "kind": kind, "users": users}
        if path == "/api/status":
            return APP.status()
        if path == "/api/groups":
            return APP.groups()
        if path == "/api/files":
            return APP.files(q)
        if path == "/api/ping":
            return {"ok": True}
        if path == "/api/diagnostico":
            return APP.diagnostico()
        if path == "/api/diagnostico/relatorio":
            return APP.relatorio()
        if path == "/api/ensaio":
            return APP.ensaio_estado()
        if path == "/api/falhas":
            g = lambda k, d="": (q.get(k) or [d])[0]
            return APP.falhas_agrupadas(g("grupo"), int(g("off", "0") or 0), min(200, int(g("limit", "50") or 50)))
        if path == "/api/medicao":
            return dict(APP.medicao or {}, incluidas=list(APP.extras), incl=dict(APP.incl), **(APP.faixas_disco() if APP.medicao else {}))
        if path == "/api/totals":
            return APP.totals()
        if path == "/api/ficha/estado":
            return dict(FT)
        if path in ("/api/ficha/atual", "/api/maquina"):
            if not FICHA:
                raise ValueError("Módulo da ficha ausente (ficha.py).")
            mid = (q.get("mid") or [""])[0] or FICHA.machine_id_cache()
            v = FICHA.visao(mid)
            out = {"mid": mid, "atual": mid == FICHA.machine_id_cache(), "visao": v, "pode_desfazer": FICHA.pode_desfazer(mid), "aplicadas": FICHA.aplicadas(mid), "root": FICHA.is_root() or FICHA.simulando(),
                   "win": FICHA.familia_atual() == "windows", "simulacao": FICHA.simulando()}
            if path == "/api/maquina":  # Ficha completa: registro (etapas, contato) e a linha do tempo inteira
                reg = FICHA.linha_registro(mid, FICHA.machine_id_cache())
                if reg:
                    rec = FICHA.receita_de(mid)
                    out["registro"] = dict(reg, etapas=FICHA.ETAPAS, receita=rec and {"n": len(rec.get("itens") or []), "automaticos": sum(1 for i in rec.get("itens") or [] if i.get("automatico")),
                                                                                     "quando": rec.get("quando", ""), "tecnico": rec.get("tecnico", ""), "valida": bool(FICHA.receita_valida(mid))}, historico=[dict(e, etapa=FICHA.etapa_do_evento(e) or "") for e in FICHA.hist_get(mid)])
            return out
        if path == "/api/programas":
            mid = (q.get("mid") or [""])[0] or FICHA.machine_id_cache()
            return {"mid": mid, "programas": PROG.com_sugestao(FICHA.programas_de(mid)), "receita": FICHA.receita_de(mid), "receita_valida": bool(FICHA.receita_valida(mid))}
        if path == "/api/atividades":
            return atividades()
        if path == "/api/painel":
            return FICHA.painel_resumo(FICHA.machine_id_cache()) if FICHA else {"maquinas": 0}
        if path == "/api/maquinas":
            return {"maquinas": FICHA.listar_maquinas() if FICHA else [], "pendrive": DADOS_DIR[0], "etapas": FICHA.ETAPAS if FICHA else []}
        if path == "/api/left":
            return {"left": APP.left_behind(), "ign_dirs": APP.ign_dirs[:1000], "ign_dirs_total": APP.ign_dirs_total}
        raise ValueError("rota desconhecida")

    def api_post(self, path, b):
        if path.startswith("/api/atualizar/") and SERVIDOR["con"]:
            raise ValueError("No modo servidor o programa já vem atualizado do servidor.")
        if path == "/api/encerrar":
            return encerrar_servidor(bool(b.get("descartar")))
        if path == "/api/config":
            return {"cfg": APP.set_config(b)}
        if path == "/api/perfil":
            return {"perfil": PERFIL.salvar(b), "certificado": PERFIL.snapshot()}
        if path == "/api/mkdir":
            p = os.path.join(os.path.abspath(os.path.expanduser(b.get("path", ""))), safe_seg(b.get("name", "")))
            os.makedirs(p, exist_ok=True)
            return {"path": p}
        if path == "/api/identificacao":
            return APP.identificacao()
        if path == "/api/preflight":
            return {"checks": APP.preflight()}
        if path == "/api/scan":
            self.exigir("backup")
            APP.start_scan()
            return {"ok": True}
        if path == "/api/select":
            return {"n": APP.select(b)}
        if path == "/api/su":
            SU["ligado"] = bool(b.get("ligado"))
            APP.log("Modo Superusuário %s." % ("ligado" if SU["ligado"] else "desligado"))
            return su_estado()
        if path == "/api/su/certificado":
            return su_certificado_salvar(b)
        if path == "/api/copy":
            self.exigir("backup")
            if not APP.layout_modo:
                if not SU["ligado"]:
                    raise ValueError("Escolha como guardar este backup (Espelho, Ordenado ou Misto) na Seleção antes de copiar.")
                APP.set_modo("espelho")
                APP.log("SUPERUSUÁRIO: cópia iniciada sem escolher o jeito de guardar; usado Espelho.")
            APP.start_copy()
            return {"ok": True}
        if path == "/api/retry":
            self.exigir("backup")
            APP.start_retry()
            return {"ok": True}
        if path == "/api/verify":
            mode = b.get("mode", "completa")
            APP.start_verify("completa" if mode == "completa" else "rapida", True)
            return {"ok": True}
        if path == "/api/pause":
            APP.run_ev.clear()
            return {"ok": True}
        if path == "/api/resume":
            APP.run_ev.set()
            return {"ok": True}
        if path == "/api/cancel":
            APP.cancel.set()
            APP.run_ev.set()
            return {"ok": True}
        if path == "/api/finish":
            return {"cert": APP.finish()}
        if path == "/api/open_mapa":
            p = os.path.join(APP.mapa_dir, "visualizador.html")
            if not os.path.isfile(p):
                raise ValueError("O mapa ainda não foi gerado.")
            open_in_browser("file://" + p.replace("\\", "/") if IS_WIN is False else "file:///" + p.replace("\\", "/"))
            return {"ok": True}
        if path == "/api/firmware_gate":
            ok, why = APP.firmware_gate()
            return {"ok": ok, "motivo": why, "falta_receita": bool(FICHA and not FICHA.receita_valida(FICHA.machine_id_cache()))}
        if path == "/api/firmware":
            if not b.get("confirmo"):
                raise ValueError("Confirmação ausente.")
            self.exigir("formatar")
            if TERMO and TERMO.status(FICHA.machine_id_cache()).get("dono") == "terceiros" and (b.get("digitou") or "").strip().upper() != "FORMATAR":
                raise ValueError("Máquina de terceiros: digite FORMATAR para confirmar.")
            return APP.firmware_reboot(bool(b.get("forcar")))
        if path == "/api/ficha/coletar":
            self.exigir("ficha")
            ficha_coletar("antes" if b.get("fase") != "depois" else "depois")
            return {"ok": True}
        if path == "/api/ficha/aplicar":
            if not b.get("confirmo"):
                raise ValueError("Confirmação ausente.")
            self.exigir("melhorias")
            ids = [str(x) for x in b.get("ids", [])]
            if b.get("medir") is False:  # interruptor da tabela de inicialização: aplica na hora, sem medir de novo
                mid = FICHA.machine_id_cache()
                v = FICHA.visao(mid)
                if not v:
                    raise ValueError("Colete a ficha antes de aplicar melhorias.")
                return {"aplicadas": FICHA.aplicar(mid, ids, v["ultima"])}
            ficha_aplicar(ids)
            return {"ok": True}
        if path == "/api/ficha/exportar":
            arq = FICHA.exportar_coleta(versao_programa=VERSION)
            abrir_no_sistema(arq, revelar=True)
            return {"arquivo": arq}
        if path == "/api/ficha/desfazer":
            self.exigir("melhorias")
            return {"desfeitos": FICHA.desfazer(FICHA.machine_id_cache(), [str(x) for x in b.get("ids") or []] or None)}
        if path == "/api/ficha/abrir_ajustes":
            import otimizacoes
            return {"ok": otimizacoes.abrir_ajustes(str(b.get("qual", "")))}
        if path == "/api/hist":
            FICHA.hist_add(FICHA.machine_id_cache(), str(b.get("tipo", "nota"))[:20], str(b.get("resumo", ""))[:300])
            return {"ok": True}
        if path == "/api/termo/aceitar":
            return TERMO.aceitar(FICHA.machine_id_cache(), b.get("responsavel", ""), b.get("dono", ""), b.get("terceiro_nome", ""), b.get("autorizado_por", ""), bool(b.get("confirma_particular")))
        if path == "/api/os/registrar":
            return TERMO.registrar_os(FICHA.machine_id_cache(), b.get("cliente", ""), b.get("escopos", []))
        if path == "/api/os/encerrar":
            mid = FICHA.machine_id_cache()
            if b.get("apagar_dados") and (b.get("digitou") or "").strip().upper() != "APAGAR":
                raise ValueError("Digite APAGAR para confirmar a remoção dos dados desta máquina do pendrive.")
            return TERMO.encerrar_os(mid, bool(b.get("apagar_dados")))
        if path == "/api/doc/abrir":
            mid = FICHA.machine_id_cache()
            nome = os.path.basename(b.get("arquivo", ""))
            if not nome and b.get("tipo") in ("termo", "os"):
                cand = sorted(x for x in (os.listdir(FICHA.pasta(mid)) if os.path.isdir(FICHA.pasta(mid)) else []) if x.startswith(b["tipo"] + "-") and x.endswith(".html"))
                nome = cand[-1] if cand else ""
            pth = os.path.join(FICHA.pasta(mid), nome)
            if not re.match(r"^(termo|os)-[0-9-]+\.html$", nome) or not os.path.isfile(pth):
                raise ValueError("Documento não encontrado.")
            open_in_browser("file:///" + pth.replace("\\", "/").lstrip("/"))
            return {"ok": True}
        if path == "/api/maquina/nome":
            mid = b.get("mid") or FICHA.machine_id_cache()
            nome = str(b.get("nome", "")).strip()[:60]
            FICHA.meta_set(mid, nome=nome)
            return {"nome": FICHA.nome_exibicao(mid)}
        if path == "/api/erro_tela":
            return {"ok": registrar_erro_tela(b.get("mensagem", ""), b.get("pilha", ""), b.get("tela", ""))}
        if path == "/api/autoteste":
            APP.autoteste_pagina = {"build": str(b.get("build") or ""), "faltando": [str(x)[:80] for x in (b.get("faltando") or [])][:50]}
            return {"ok": True}
        if path == "/api/alerta/acao":
            ac = str(b.get("acao") or "")
            if ac == "pular" and APP.item_atual is not None:
                APP.pular = APP.item_atual
                APP.log("Você mandou pular: %s" % APP.item_atual.disp)
            elif ac == "esperar":
                APP.adiar_parada = time.time() + 180
                APP.resolver("parada")
            return {"ok": True}
        if path == "/api/antes_de_copiar":
            return APP.antes_de_copiar()
        if path == "/api/ensaio/iniciar":
            return APP.ensaio_leitura()
        if path == "/api/falhas/desmarcar":
            return APP.desmarcar_esperadas(str(b.get("grupo") or ""))
        if path == "/api/incluir":
            return APP.incluir_pastas(b.get("caminhos") or [])
        if path == "/api/incluir/tirar":
            return APP.tirar_extras(b.get("caminho") or "")
        if path == "/api/backup/retomar":
            self.exigir("backup")
            return APP.retomar(str(b.get("mid") or FICHA.machine_id_cache()))
        if path == "/api/maquina/etapa":
            r = FICHA.marcar_etapa(str(b.get("mid") or ""), str(b.get("etapa") or ""), bool(b.get("confirmar")))
            if b.get("etapa") == "encerrada" and APP.phase in ("verified", "done") and not APP.busy():
                APP.reset()  # o passo a passo daquele backup não fica aberto depois de encerrado
            return r
        if path == "/api/maquina/receita":
            mid = str(b.get("mid") or "") or FICHA.machine_id_cache()
            return {"receita": FICHA.salvar_receita(mid, b.get("itens"), bool(b.get("nenhum")))}
        if path == "/api/maquina/registro":
            return {"registro": FICHA.salvar_contato(str(b.get("mid") or ""), b.get("telefone", ""), b.get("email", ""), b.get("observacoes", ""), b.get("dono_nome"))}
        if path == "/api/maquina/apagar":
            mid = b.get("mid") or ""
            if not mid or (b.get("digitou") or "").strip().upper() != "APAGAR":
                raise ValueError("Digite APAGAR para confirmar.")
            if mid == FICHA.machine_id_cache() and TERMO.os_atual(mid):
                raise ValueError("Encerre a OS desta máquina primeiro.")
            TERMO.log_add("dados_apagados", mid, motivo="pedido do técnico")
            FICHA.apagar_maquina(mid)
            return {"ok": True}
        if path == "/api/permissoes/abrir":
            if sys.platform == "darwin":
                subprocess.Popen(["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles"])
            return {"ok": True}
        if path == "/api/dados/varrer":
            self.exigir(None)
            DADOS.iniciar_varredura(int(b.get("idle_dias", 90)), int(b.get("min_mb", 100)))
            return {"ok": True}
        if path == "/api/dados/cancelar":
            DADOS.cancelar()
            return {"ok": True}
        if path == "/api/dados/abrir":
            self.exigir(None)
            cam = DADOS.caminho_no(b.get("no"))
            revelar = b.get("modo") == "pasta"
            if not revelar and not DADOS.pode_abrir(cam):
                raise ValueError("Por segurança este arquivo não abre daqui (programa, script, atalho ou senha). Use Mostrar na pasta.")
            if not abrir_no_sistema(cam, revelar):
                raise ValueError("O sistema não conseguiu abrir.")
            return {"ok": True}
        if path == "/api/layout":
            return APP.set_modo(b.get("modo", ""))
        if path == "/api/layout/copia":
            return APP.copia(b)
        if path == "/api/bitlocker":
            self.exigir("backup")
            return destravar_bitlocker(str(b.get("onde", "")), str(b.get("chave", "")))
        if path == "/api/mapa/abrir":
            self.exigir(None)
            return MAPA.carregar(b.get("pasta", ""))
        if path == "/api/mapa/arquivo":
            cam = MAPA.caminho(b.get("i"))
            revelar = b.get("modo") == "pasta"
            if not revelar and not DADOS.pode_abrir(cam):
                raise ValueError("Por segurança este arquivo não abre daqui. Use Mostrar na pasta.")
            if not abrir_no_sistema(cam, revelar):
                raise ValueError("O sistema não conseguiu abrir.")
            return {"ok": True}
        if path == "/api/mapa/conferir":
            return MAPA.conferir()
        if path == "/api/mapa/offline":
            p = os.path.join(MAPA.M["mapa"], "visualizador.html")
            if not os.path.isfile(p):
                raise ValueError("Abra um Mapa primeiro.")
            open_in_browser("file:///" + p.replace("\\", "/").lstrip("/"))
            return {"ok": True}
        if path == "/api/dados/marcar":
            return {"id": DADOS.marcar(b.get("no"))}
        if path == "/api/dados/marcar_nos":
            return {"ids": DADOS.marcar_nos(b.get("nos") or [])}
        if path == "/api/dados/renomear":
            self.exigir("limpeza")
            return DADOS.renomear(b.get("no"), b.get("nome", ""))
        if path == "/api/dados/nova_pasta":
            self.exigir("limpeza")
            return DADOS.nova_pasta(b.get("no"), b.get("nome", ""))
        if path == "/api/dados/preflight_destino":
            self.exigir("limpeza")
            return DADOS.preflight_destino(b.get("nos") or [], b.get("destino"), b.get("modo", "mover"))
        if path in ("/api/dados/mover", "/api/dados/copiar"):
            self.exigir("limpeza")
            tipo = path.rsplit("/", 1)[1]
            getattr(DADOS, tipo)(b.get("nos") or [], b.get("destino"), b.get("resolucao", ""), dados_depois(tipo))
            return {"ok": True}
        if path == "/api/dados/reset":
            DADOS.reset()
            return {"ok": True}
        if path == "/api/dados/preflight":
            self.exigir("limpeza")
            return DADOS.preflight_offload(b.get("ids", []), b.get("dest", ""), bool(b.get("confirma_orfaos")))
        if path == "/api/dados/limpar":
            if not b.get("confirmo"):
                raise ValueError("Confirmação ausente.")
            self.exigir("limpeza")
            DADOS.limpar(b.get("ids", []), bool(b.get("definitivo")), dados_depois("limpar"), bool(b.get("confirma_orfaos")))
            return {"ok": True}
        if path == "/api/dados/offload":
            if not b.get("confirmo"):
                raise ValueError("Confirmação ausente.")
            self.exigir("limpeza")
            DADOS.offload(b.get("ids", []), b.get("dest", ""), bool(b.get("definitivo")), dados_depois("offload"), bool(b.get("confirma_orfaos")))
            return {"ok": True}
        if path == "/api/dados/esvaziar_lixeira":
            if not b.get("confirmo"):
                raise ValueError("Confirmação ausente.")
            self.exigir("limpeza")
            r = DADOS.esvaziar_lixeira()
            REC["bytes"] += int(r.get("bytes") or 0)
            FICHA.hist_add(FICHA.machine_id_cache(), "limpeza", "Lixeira esvaziada (%s liberados)" % fmt_bytes(r.get("bytes") or 0), {"bytes": r.get("bytes") or 0})
            return r
        if path == "/api/atualizar/aplicar":
            cam = b.get("caminho", "")
            r = ATUAL.aplicar(cam, VERSION)
            try:
                TERMO.log_add("atualizacao", FICHA.machine_id_cache(), de=r["de"], para=r["para"], zip_sha256=r["zip_sha256"])
                FICHA.hist_add(FICHA.machine_id_cache(), "atualizacao", "Programa atualizado de %s para %s (registros mantidos)" % (r["de"], r["para"]))
            except Exception:
                pass
            if os.path.basename(cam) == "_novo_upload.zip":
                try:
                    os.remove(cam)
                except OSError:
                    pass
            return r
        if path == "/api/atualizar/reverter":
            r = ATUAL.reverter(b.get("nome", ""), VERSION)
            try:
                TERMO.log_add("atualizacao", FICHA.machine_id_cache(), de=r["de"], para=r["para"], reversao=True)
            except Exception:
                pass
            return r
        if path == "/api/atualizar/reiniciar":
            def _go():
                time.sleep(1.2)
                ATUAL.reiniciar_processo()
                time.sleep(0.8)
                os._exit(0)
            threading.Thread(target=_go, daemon=True).start()
            return {"ok": True}
        if path == "/api/reset":
            if APP.busy():
                raise Busy("Aguarde o processo atual terminar.")
            APP.reset()
            return {"ok": True}
        raise ValueError("rota desconhecida")


def _como_usuario(cmd):
    """Rodando com sudo (Linux/Mac): executa como quem chamou, não como root."""
    if not IS_WIN and hasattr(os, "geteuid") and os.geteuid() == 0 and os.environ.get("SUDO_USER") and shutil.which("sudo"):
        return ["sudo", "-u", os.environ["SUDO_USER"]] + cmd
    return cmd


def abrir_no_sistema(path, revelar=False):
    """Abre o arquivo no programa padrão ou, com revelar, mostra ele selecionado na pasta."""
    path = os.path.abspath(path)
    try:
        if IS_WIN:
            # pelo explorer.exe o pedido vai para o Explorer já aberto: o arquivo abre SEM privilégio de administrador
            subprocess.Popen('explorer.exe /select,"%s"' % path if revelar else 'explorer.exe "%s"' % path)
        elif sys.platform == "darwin":
            subprocess.Popen(_como_usuario(["open", "-R", path] if revelar else ["open", path]), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            alvo = os.path.dirname(path) if revelar and not os.path.isdir(path) else path
            subprocess.Popen(_como_usuario(["xdg-open", alvo]), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except OSError:
        return False


def encerrar_servidor(descartar=False):
    con = SERVIDOR["con"]
    if not con:
        raise ValueError("Encerrar por aqui só existe no modo servidor.")
    if APP.busy():
        raise Busy("Aguarde o processo atual terminar.")
    pend = con.enviar_pendentes()
    if pend and not descartar:
        return {"ok": False, "pendentes": pend}

    def _go():
        time.sleep(0.8)
        if SERVIDOR["cache_proprio"]:
            shutil.rmtree(DADOS_DIR[0], ignore_errors=True)
        os._exit(0)
    threading.Thread(target=_go, daemon=True).start()
    return {"ok": True}


def mapas_conhecidos():
    """Backups desta máquina (histórico) e o desta sessão, com o Mapa ainda acessível."""
    out, vistos = [], set()

    def add(destino, quando, codigo, cliente):
        mp = os.path.join(destino or "", "Mapa")
        k = os.path.normcase(os.path.abspath(mp))
        if destino and k not in vistos and os.path.isfile(os.path.join(mp, "dados.js")):
            vistos.add(k)
            out.append({"pasta": destino, "quando": quando, "codigo": codigo, "cliente": cliente})
            return True
        return False
    if APP.dest_root:
        add(APP.dest_root, "esta sessão", (APP.cert or {}).get("codigo", ""), APP.cfg.get("cliente", "") if APP.cfg else "")
    try:
        for h in reversed(FICHA.hist_get(FICHA.machine_id_cache())):
            x = h.get("extra") or {}
            if h.get("tipo") == "backup":
                if not add(x.get("destino"), h.get("quando", ""), x.get("codigo", ""), x.get("cliente", "")):
                    add(x.get("mapa_registro"), h.get("quando", ""), x.get("codigo", ""), (x.get("cliente") or "") + " (cópia no registro)")
    except Exception:
        pass
    return out


def usar_pasta_dados(p):
    """Fichas, históricos e consentimentos em outra pasta (testes no próprio computador sem misturar com o pendrive)."""
    p = os.path.abspath(os.path.expanduser(p))
    os.makedirs(p, exist_ok=True)
    DADOS_DIR[0] = p
    PERFIL.PASTA = p
    if FICHA:
        FICHA.STORE = os.path.join(p, "maquinas")
    if TERMO:
        TERMO.LOG = os.path.join(p, "consentimentos.log")


def conectar_servidor(url, chave_arquivo=None, dados=None):
    """Modo servidor: o programa roda aqui, mas fichas, históricos e termos ficam no servidor da loja.
    maquinas/ vira um cache temporário, apagado ao encerrar."""
    import conexao
    chave = os.environ.pop("DESTRAVA_CHAVE", "")  # fora do ambiente: os programas que abrimos (PowerShell etc.) não herdam
    if chave_arquivo:
        try:
            with open(chave_arquivo, encoding="utf-8") as fh:
                chave = fh.read().strip()
        finally:
            try:
                os.remove(chave_arquivo)
            except OSError:
                pass
    if not chave:
        import getpass
        chave = getpass.getpass("Chave do técnico: ").strip()
    con = conexao.Conexao(url, chave, VERSION)
    try:
        con.testar()
    except Exception as e:
        print("Não consegui entrar no servidor %s: %s" % (url, e), flush=True)
        sys.exit(2)
    proprio = not dados
    cache = dados or os.path.join(HERE, "_cache_servidor")
    if proprio:
        shutil.rmtree(cache, ignore_errors=True)  # nunca reaproveita dados de outra sessão
        atexit.register(shutil.rmtree, cache, True)
    pasta_perfil = PERFIL.PASTA
    usar_pasta_dados(cache)
    if proprio:
        PERFIL.PASTA = pasta_perfil  # o perfil é deste computador: não vai para o cache que se apaga ao sair
    FICHA.SINCRONIA = con
    TERMO.REMOTO = con
    TERMO.MODO = "servidor"
    SERVIDOR.update(con=con, cache_proprio=proprio)
    FICHA._garantir(FICHA.machine_id_cache())
    print("Conectado ao servidor %s como %s." % (con.url, con.tecnico or "?"), flush=True)
    return con


def open_in_browser(url):
    # rodando com sudo: abre o navegador como o usuário que chamou (navegadores recusam rodar como root)
    if not IS_WIN and hasattr(os, "geteuid") and os.geteuid() == 0 and os.environ.get("SUDO_USER") and shutil.which("sudo"):
        for opener in ("xdg-open", "open"):
            if shutil.which(opener):
                try:
                    subprocess.Popen(["sudo", "-u", os.environ["SUDO_USER"], opener, url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    return True
                except OSError:
                    pass
    try:
        if webbrowser.open(url):
            return True
    except Exception:
        pass
    for cmd in (("xdg-open", url), ("open", url)):
        if shutil.which(cmd[0]):
            try:
                subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return True
            except OSError:
                pass
    return False


def _erros_log():
    return os.path.join(DADOS_DIR[0], "erros.log")


def _gravar_erro(onde, texto):
    """Uma entrada no erros.log (rotaciona em 1 MB e guarda a anterior em erros.log.1)."""
    try:
        p = _erros_log()
        if os.path.exists(p) and os.path.getsize(p) > 1024 * 1024:
            os.replace(p, p + ".1")
        with open(p, "a", encoding="utf-8") as fh:
            fh.write("%s  v%s  %s\n%s\n" % (now_iso(), VERSION, onde, texto))
    except Exception:
        pass


def registrar_erro(onde):
    """Grava o erro em andamento (com o traceback) em erros.log, na pasta de dados: é o que se manda para diagnosticar."""
    if isinstance(sys.exc_info()[1], (ConnectionError, TimeoutError)):  # navegador fechou ou cancelou a chamada: normal
        return
    _gravar_erro(onde, traceback.format_exc())


_TELA_VISTOS = collections.OrderedDict()


def registrar_erro_tela(mensagem, pilha="", tela=""):
    """Erro da página (JavaScript) vindo do navegador: no máximo 200 por sessão e sem repetir o mesmo."""
    chave = (str(mensagem)[:200], str(pilha)[:200])
    if chave in _TELA_VISTOS or len(_TELA_VISTOS) >= 200:
        return False
    _TELA_VISTOS[chave] = 1
    _gravar_erro("TELA %s" % (str(tela)[:60] or "?"), "%s\n%s" % (str(mensagem)[:500], str(pilha)[:1500]))
    return True


def ler_erros(n=50):
    """As últimas n entradas do erros.log: [{quando, onde, resumo, texto}], da mais nova para a mais antiga."""
    try:
        with open(_erros_log(), encoding="utf-8", errors="replace") as fh:
            txt = fh.read()
    except OSError:
        return []
    blocos = re.split(r"(?m)^(?=\d{4}-\d\d-\d\d \d\d:\d\d:\d\d  v)", txt)
    out = []
    for b in blocos:
        m = re.match(r"(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)  v\S+  (.*)\n", b)
        if not m:
            continue
        linhas = [x for x in b[m.end():].splitlines() if x.strip()]
        resumo = next((x.strip() for x in reversed(linhas) if not x.startswith(" ")), linhas[-1].strip() if linhas else "")
        out.append({"quando": m.group(1), "onde": m.group(2).strip(), "resumo": resumo[:300], "texto": b[m.end():][:3000]})
    return out[-n:][::-1]


def autoteste_servidor():
    """Verificações rápidas do próprio programa na abertura: [{ok, titulo, detalhe}]."""
    r = []
    add = lambda ok, t, d="": r.append({"ok": bool(ok), "titulo": t, "detalhe": d})
    add(sys.version_info >= (3, 8), "Python %d.%d.%d" % sys.version_info[:3], "O programa precisa do Python 3.8 ou mais novo.")
    pasta = DADOS_DIR[0]
    try:
        tmp = os.path.join(pasta, ".dd_teste_%d" % os.getpid())
        with open(tmp, "w") as fh:
            fh.write("x")
        os.remove(tmp)
        livre = shutil.disk_usage(pasta).free
        add(livre > 50 * 1024 * 1024, "Pasta de dados grava (%s livres)" % fmt_bytes(livre), "Fichas e registros ficam aqui: %s" % pasta)
    except OSError as e:
        add(False, "A pasta de dados não grava", "%s (%s). O pendrive pode estar só para leitura ou cheio." % (pasta, e))
    add(2024 <= datetime.date.today().year <= 2100, "Relógio do computador plausível (%s)" % datetime.date.today().isoformat(), "Data errada estraga as fichas e os certificados.")
    try:
        with open(os.path.join(WEB, "app.html"), encoding="utf-8") as fh:
            m = re.search(r'const BUILD="([^"]+)"', fh.read())
        pagina = m.group(1) if m else ""
        add(pagina == BUILD, "Programa e tela na mesma versão (%s)" % BUILD, "A tela é da versão %s e o programa da %s: copie a pasta do programa inteira de novo." % (pagina or "?", BUILD))
    except OSError:
        add(False, "Não achei a tela do programa (web/app.html)", "A pasta web está incompleta.")
    return r


class Servidor(ThreadingHTTPServer):
    """Fila de conexões maior (o navegador abre várias ao mesmo tempo) e erros de requisição registrados em erros.log."""
    request_queue_size = 128

    def handle_error(self, request, client_address):
        registrar_erro("conexão de %s" % (client_address[0] if client_address else "?"))


def serve(port=0, open_browser=True, host="127.0.0.1", token_na_pagina=False):
    srv = Servidor((host, port), Handler)
    p = srv.server_address[1]
    APP.allowed_hosts = {"127.0.0.1:%d" % p, "localhost:%d" % p}
    APP.token_na_pagina = token_na_pagina
    url = "http://localhost:%d/" % p if token_na_pagina else "http://127.0.0.1:%d/#%s" % (p, APP.token)
    print("DD_URL=%s" % url, flush=True)
    print("\nDestrava! rodando. Se o navegador não abrir sozinho, copie o endereço acima.\nPara encerrar: Ctrl+C nesta janela%s.\n" % (" ou o botão Encerrar" if SERVIDOR["con"] else ""), flush=True)
    if open_browser:
        open_in_browser(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()


# ----------------------------------------------------------------------------------------------
# Modos de linha de comando
# ----------------------------------------------------------------------------------------------
def cli_verificar(pasta):
    pasta = os.path.abspath(pasta)
    cj = os.path.join(pasta, "certificado.json")
    dj = os.path.join(pasta, "dados.js")
    try:
        with open(cj, encoding="utf-8") as f:
            c = json.load(f)
        with open(dj, "rb") as f:
            h = hashlib.sha256(f.read()).hexdigest()
    except OSError as e:
        print("Não consegui ler os arquivos do Mapa:", e)
        return 2
    if h == c.get("dados_js_sha256"):
        print("OK  - dados.js é idêntico ao do momento do certificado.")
        print("Certificado %s | %s | %s" % (c.get("codigo"), c["cert"].get("equipamento"), c["cert"].get("data")))
        for e in c["cert"].get("editado") or []:
            print("AVISO - editado manualmente (%s) em %s: %s" % (e.get("por", ""), e.get("quando", ""), ", ".join(e.get("campos") or {})))
        return 0
    print("ALERTA - o dados.js foi ALTERADO depois de o certificado ser emitido.")
    return 1


def cli_rehash(pasta):
    pasta = os.path.abspath(pasta)
    raiz = os.path.dirname(pasta)
    with open(os.path.join(pasta, "dados.js"), encoding="utf-8") as f:
        txt = f.read()
    data = json.loads(txt[len("window.BKP="):].rstrip(";"))
    ok = bad = miss = 0
    for r in data["f"]:
        if r[5] != "ok" or not r[1] or not r[9]:
            continue
        p = os.path.join(raiz, *r[1].split("/"))
        if not os.path.exists(lp(p)):
            miss += 1
            print("FALTANDO:", r[1])
            continue
        h = hashlib.sha256()
        with open(lp(p), "rb") as f:
            for b in iter(lambda: f.read(CHUNK), b""):
                h.update(b)
        if h.hexdigest() == r[9]:
            ok += 1
        else:
            bad += 1
            print("DIFERENTE:", r[1])
    print("Conferidos OK: %d | diferentes: %d | faltando: %d" % (ok, bad, miss))
    return 0 if bad == 0 and miss == 0 else 1


def main():
    ap = argparse.ArgumentParser(description="D&D Backup")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=0)
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--token-na-pagina", action="store_true", help="entrega o token junto com a página (Docker; publique a porta só em 127.0.0.1)")
    ap.add_argument("--verificar", metavar="PASTA_MAPA")
    ap.add_argument("--rehash", metavar="PASTA_MAPA")
    ap.add_argument("--dados", metavar="PASTA", default=os.environ.get("DESTRAVA_DADOS"), help="onde guardar fichas e consentimentos (padrão: ao lado do programa)")
    ap.add_argument("--exportar-coleta", metavar="ARQUIVO", help="analisa esta máquina, grava a coleta em ARQUIVO e sai")
    ap.add_argument("--coleta-salva", metavar="ARQUIVO", help="reproduz uma coleta exportada; as ações só são simuladas")
    ap.add_argument("--servidor", metavar="URL", help="roda pelo servidor da loja: fichas, históricos e termos ficam lá")
    ap.add_argument("--chave-arquivo", metavar="ARQUIVO", help=argparse.SUPPRESS)
    a = ap.parse_args()
    if a.verificar:
        sys.exit(cli_verificar(a.verificar))
    if a.rehash:
        sys.exit(cli_rehash(a.rehash))
    if a.dados:
        usar_pasta_dados(a.dados)
    if a.exportar_coleta:
        FICHA.coletar(lambda e, p: print("  %3d%%  %s" % (p, e), flush=True))
        print("Coleta gravada em", FICHA.exportar_coleta(a.exportar_coleta, VERSION))
        return
    if a.servidor:
        conectar_servidor(a.servidor, a.chave_arquivo, a.dados)
    if a.coleta_salva:
        FICHA.carregar_coleta(a.coleta_salva)
        print("SIMULAÇÃO: reproduzindo a coleta de %s (%s). Nada é alterado neste computador." % (FICHA.REPLAY.get("host", "?"), FICHA.familia_atual()), flush=True)
    serve(a.port, not a.no_browser, a.host, a.token_na_pagina)


if __name__ == "__main__":
    main()
