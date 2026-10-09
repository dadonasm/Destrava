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

VERSION = "3.1"
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
CATS = {
    "Fotos": ".jpg .jpeg .png .heic .heif .gif .bmp .tif .tiff .webp .raw .cr2 .nef .arw .dng",
    "Videos": ".mp4 .mov .avi .mkv .wmv .3gp .mpg .mpeg .m4v .flv",
    "Audios": ".mp3 .wav .m4a .aac .flac .ogg .opus .wma .amr",
    "Documentos": ".pdf .doc .docx .docm .dotx .xls .xlsx .xlsm .xlsb .ppt .pptx .pps .ppsx .txt .odt .ods .odp .csv .rtf .one",
    "Projetos": ".psd .ai .cdr .indd .dwg .dxf .skp .xcf .svg .prproj .aep",
    "Email_Contatos": ".pst .eml .msg .mbox .vcf",
    "Contas_Senhas": ".kdbx .kdb .pfx .p12",
}
EXT2CAT = {}
for _c, _e in CATS.items():
    for _x in _e.split():
        EXT2CAT[_x] = _c
ARCH = set(".zip .rar .7z .tar .gz .tgz .bz2".split())
IGN_EXT = set(".exe .dll .sys .tmp .temp .log .ini .lnk .url .msi .msp .cab .cat .mui .drv .ocx .cpl .scr .bin .obj .pyc .class "
              ".etl .dmp .cache .ost .crdownload .part .ddpart .so .lock .swp .desktop".split())
IGN_NAME_RE = re.compile(r"^(ntuser.*|desktop\.ini|thumbs\.db|iconcache\.db|pagefile\.sys|hiberfil\.sys|swapfile\.sys|\.ds_store|\.directory)$", re.I)
WA_RE = re.compile(r"(^msgstore.*\.db(\.crypt\d+)?$)|(\.crypt\d+$)", re.I)

IGN_ANY = {"node_modules", ".git", "__pycache__", "$recycle.bin", "system volume information", ".trash", "lost+found", ".thumbnails", ".cache"}
IGN_WIN_ROOT = {"windows", "program files", "program files (x86)", "programdata", "recovery", "config.msi", "msocache", "perflogs", "intel",
                "amd", "nvidia", "documents and settings", "boot", "efi", "users"}
IGN_WIN_USERS = {"default", "default user", "all users", "public documents"}
SILENT_JUNCTIONS = {"application data", "cookies", "local settings", "my documents", "nethood", "printhood", "recent", "sendto", "start menu", "templates"}
IGN_LINUX_HOME = {".cache", ".config", ".local", ".mozilla", ".var", ".steam", ".npm", ".nvm", ".cargo", ".rustup", ".gradle", ".m2", ".wine",
                  ".dbus", ".gvfs", ".thumbnails", "snap", ".snap", ".pki", ".gnome", ".compiz", ".icons", ".themes", ".java", ".nv"}
CLOUD_ATTRS = 0x1000 | 0x40000 | 0x400000  # OFFLINE | RECALL_ON_OPEN | RECALL_ON_DATA_ACCESS
GOOD_FS = {"ntfs", "ntfs3", "fuseblk", "vfat", "exfat", "ext2", "ext3", "ext4", "btrfs", "xfs", "f2fs", "hfsplus", "apfs", "msdos"}
RESERVED = {"con", "prn", "aux", "nul"} | {"com%d" % i for i in range(1, 10)} | {"lpt%d" % i for i in range(1, 10)}
ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


class Cancelled(Exception):
    pass


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
    return "outro", "ERRO: %s" % (e,)


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


def detect_kind(p):
    try:
        names = {n.lower(): n for n in os.listdir(p)}
    except OSError:
        return "folder", []
    if "windows" in names and ("users" in names or "documents and settings" in names):
        users = []
        try:
            for n in sorted(os.listdir(os.path.join(p, names.get("users", "Users")))):
                if os.path.isdir(os.path.join(p, names.get("users", "Users"), n)) and n.lower() not in IGN_WIN_USERS and not re.match(r"^defaultuser\d+$", n, re.I):
                    users.append(n)
        except OSError:
            pass
        return "windows", users
    if "home" in names and "etc" in names and "usr" in names:
        try:
            return "linux", sorted(n for n in os.listdir(os.path.join(p, names["home"])) if os.path.isdir(os.path.join(p, names["home"], n)))
        except OSError:
            return "linux", []
    return "folder", []


def list_sources():
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
    add(home, "Pasta pessoal (%s)" % os.path.basename(home))
    # Windows: sugere letras
    letters = iter("CDEFGHIJ")
    for s in out:
        if s["kind"] == "windows":
            s["letter"] = (os.path.splitdrive(s["path"])[0][:1] if IS_WIN and os.path.splitdrive(s["path"])[0] else next(letters))
    return out


def roots_for_browse():
    res = []
    if IS_WIN:
        for s in list_sources():
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
    __slots__ = ("src", "disp", "size", "mtime", "local", "cat", "act", "motivo", "date", "tags", "inc", "rel",
                 "status", "err", "cause", "sha", "ver", "nuvem")

    def __init__(self):
        self.status = None
        self.err = ""
        self.cause = ""
        self.sha = ""
        self.ver = False
        self.inc = False
        self.nuvem = False


def classify_file(name, size, nuvem):
    low = name.lower()
    ext = os.path.splitext(low)[1]
    if size == 0:
        return "Outros", "ignorar", "Arquivo vazio (0 bytes)"
    if low.startswith("~$") or ext in IGN_EXT or IGN_NAME_RE.match(name):
        return "Outros", "ignorar", "Programa / sistema / temporário"
    if WA_RE.search(name):
        cat, act, mot = "Conversas", "copiar", "Backup de conversas (WhatsApp)"
    elif ext in EXT2CAT:
        cat = EXT2CAT[ext]
        act, mot = "copiar", "Arquivo pessoal (%s)" % cat
    elif ext in ARCH:
        cat, act, mot = "Outros", "copiar", "Arquivo compactado"
    else:
        cat, act, mot = "Outros", "revisar", "Tipo não reconhecido - confira"
    if nuvem:
        if cat in ("Fotos", "Videos", "Audios"):
            mot += " · OneDrive: será baixado"
        else:
            return cat, "ignorar", "OneDrive: só na nuvem (não baixado)"
    return cat, act, mot


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
        self.items = []
        self.ign_dirs = []
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
        return self.phase in ("scanning", "copying", "verifying", "finishing")

    # ------------------------------------------------------------------ config
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
        dest = os.path.abspath(os.path.expanduser(d.get("dest", "")))
        if not d.get("dest") or not os.path.isdir(dest):
            raise ValueError("Escolha uma pasta de destino que exista.")
        folder = safe_seg((d.get("folder") or "").strip() or ("Backup_" + socket.gethostname()))
        self.cfg = {
            "sources": srcs, "dest": dest, "folder": folder,
            "cliente": (d.get("cliente") or "").strip(), "tecnico": (d.get("tecnico") or "").strip(),
            "equip": (d.get("equip") or "").strip() or socket.gethostname(),
        }
        self.dest_root = os.path.join(dest, folder)
        self.mapa_dir = os.path.join(self.dest_root, "Mapa")
        return self.cfg

    # ------------------------------------------------------------------ checagens iniciais
    def preflight(self):
        res = []

        def add(n, t, d):
            res.append({"nivel": n, "titulo": t, "detalhe": d})

        cfg = self.cfg
        if not cfg:
            return [{"nivel": "erro", "titulo": "Configuração incompleta", "detalhe": "Escolha origens e destino."}]
        for s in cfg["sources"]:
            p = s["path"]
            try:
                names = os.listdir(p)
                if not names:
                    add("aviso", "Origem vazia: %s" % p, "Nenhum arquivo encontrado. Se for um disco do Windows, ele pode estar criptografado (BitLocker) ou não montado.")
                else:
                    add("ok", "Origem legível: %s" % p, "Tipo detectado: %s." % {"windows": "instalação do Windows", "linux": "instalação do Linux", "folder": "pasta comum"}.get(s["kind"], s["kind"]))
            except OSError as e:
                add("erro", "Não consigo ler a origem: %s" % p, str(e))
                continue
            if not IS_WIN:
                m = mount_of(p)
                if m:
                    opts = m[3].split(",")
                    if m[2] in ("ntfs", "ntfs3", "fuseblk") and "ro" in opts:
                        add("aviso", "Disco NTFS montado somente leitura", "É seguro para backup. Se faltarem arquivos, o Windows pode ter sido desligado com 'Inicialização rápida' ativa.")
            if s["kind"] == "windows":
                if not os.path.isdir(os.path.join(p, "Users")) and not IS_WIN:
                    add("aviso", "Pasta Users não encontrada", "Confirme se esta é a partição do Windows.")
        # destino
        d = cfg["dest"]
        total, free = disk_usage(d)
        add("ok", "Destino: %s" % d, "%s livres de %s." % (fmt_bytes(free), fmt_bytes(total)))
        fs = fs_type(d)
        if fs in ("vfat", "msdos"):
            add("aviso", "Destino em FAT32", "FAT32 não aceita arquivos acima de 4 GB. Prefira exFAT, NTFS ou ext4.")
        elif fs:
            add("ok", "Sistema de arquivos do destino: %s" % fs, "")
        try:
            os.makedirs(self.dest_root, exist_ok=True)
            tp = os.path.join(self.dest_root, ".dd_teste.tmp")
            blob = os.urandom(1024 * 1024)
            t0 = time.time()
            with open(tp, "wb") as f:
                f.write(blob)
                f.flush()
                os.fsync(f.fileno())
            dt = max(time.time() - t0, 1e-6)
            with open(tp, "rb") as f:
                ok = hashlib.sha256(f.read()).digest() == hashlib.sha256(blob).digest()
            os.remove(tp)
            if ok:
                add("ok", "Teste de gravação e leitura no destino", "Gravou e releu 1 MB sem diferenças (%.0f MB/s)." % (1.0 / dt))
            else:
                add("erro", "O destino devolveu dados diferentes dos gravados", "Não use este dispositivo para backup.")
        except OSError as e:
            add("erro", "Não consigo gravar no destino", str(e))
        # mesmo disco?
        pd = physical_id(d)
        same = [s["path"] for s in cfg["sources"] if pd and physical_id(s["path"]) == pd]
        self.same_disk = bool(same)
        if same:
            add("aviso", "Destino está no MESMO disco físico de uma origem", "Serve para organizar, mas NÃO serve para formatar: a formatação apagaria o backup junto.")
        else:
            add("ok", "Destino em disco diferente das origens", "Pronto para um backup que sobrevive à formatação.")
        # SMART (se existir)
        sm = shutil.which("smartctl")
        if sm and not IS_WIN:
            for s in cfg["sources"]:
                m = mount_of(s["path"])
                pdk = parent_disk(m[0]) if m else None
                if pdk:
                    try:
                        r = subprocess.run([sm, "-H", "/dev/" + pdk], capture_output=True, text=True, timeout=20)
                        line = [x for x in r.stdout.splitlines() if "overall-health" in x or "SMART Health" in x]
                        if line:
                            ok = "PASSED" in line[0] or "OK" in line[0]
                            add("ok" if ok else "erro", "Saúde (SMART) de /dev/%s" % pdk, line[0].strip())
                    except Exception:
                        pass
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
                    if not os.path.isdir(up) or u.lower() in IGN_WIN_USERS or re.match(r"^defaultuser\d+$", u, re.I):
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
                if os.path.isdir(p) and not os.path.islink(p):
                    if low in IGN_WIN_ROOT or low.startswith("$") or low in IGN_ANY:
                        if low != "users":
                            self.add_ign("%s:\\%s" % (letter, n), "Sistema operacional / programas instalados")
                        continue
                    plans.append((p, "Disco_%s/%s" % (letter, n), "%s:\\%s" % (letter, n), "\\", "plain"))
            plans.append((root, "Disco_%s" % letter, "%s:\\" % letter, "\\", "toplevel"))
        elif kind == "linux":
            hp = os.path.join(root, "home")
            for u in sorted(safe_listdir(hp)):
                up = os.path.join(hp, u)
                if os.path.isdir(up):
                    plans.append((up, u, "/home/" + u, "/", "linuxuser"))
            rp = os.path.join(root, "root")
            if os.path.isdir(rp):
                plans.append((rp, "root", "/root", "/", "linuxuser"))
        else:
            base = os.path.basename(root.rstrip("/\\")) or root
            home = os.path.abspath(os.path.expanduser("~"))
            if os.path.abspath(root) == home or os.path.dirname(os.path.abspath(root)) == "/home":
                plans.append((root, base, root, os.sep, "linuxuser"))
            else:
                plans.append((root, ("Disco_" if os.path.ismount(root) else "Pasta_") + base, root, os.sep, "plain"))
        return plans

    def add_ign(self, disp, motivo):
        self.ign_dirs_total += 1
        if len(self.ign_dirs) < 20000:
            self.ign_dirs.append((disp, motivo))

    def dir_ignore(self, name, ctx, parent_is_root):
        low = name.lower()
        if low in IGN_ANY:
            return "Dados de programas / temporários / lixeira"
        if ctx == "winuser" and parent_is_root and low == "appdata":
            return "Dados de programas (AppData) - só os favoritos dos navegadores são copiados"
        if ctx == "linuxuser" and parent_is_root and low in IGN_LINUX_HOME:
            return "Dados de programas / cache do Linux"
        return None

    def walk_plan(self, plan):
        """Gera (real, disp, name, st, local) para cada arquivo; registra pastas ignoradas."""
        real_root, local, disp_root, sep, ctx = plan
        dest_abs = os.path.abspath(self.dest_root) if self.dest_root else None
        stack = [(real_root, disp_root, True)]
        while stack:
            if self.cancel.is_set():
                raise Cancelled()
            rd, dd, is_root = stack.pop()
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
                            why = self.dir_ignore(name, ctx, is_root)
                            if ctx == "winuser" and is_root and name.lower() in SILENT_JUNCTIONS:
                                continue
                            if why:
                                self.add_ign(dd.rstrip(sep) + sep + name, why)
                                continue
                            stack.append((e.path, dd.rstrip(sep) + sep + name, False))
                        elif e.is_file(follow_symlinks=False):
                            st = e.stat(follow_symlinks=False)
                            yield (e.path, dd.rstrip(sep) + sep + name, name, st, local)
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
            it.cat, it.act, it.motivo = "Navegadores", "copiar", "Favoritos do navegador"
            it.date = None
            it.tags = ""
            it.inc = True
            loc = "/".join(safe_seg(x) for x in local.split("/"))
            it.rel = "%s/Outros/Navegadores/%s" % (loc, nm)
            res.append(it)
        return res

    # ------------------------------------------------------------------ varredura
    def start_scan(self):
        with self.lock:
            if self.busy():
                raise Busy("Já existe um processo em andamento.")
            if not self.cfg:
                raise ValueError("Salve a configuração antes de escanear.")
            self.items = []
            self.ign_dirs = []
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

    def make_item(self, real, disp, name, st, local):
        nuvem = bool(getattr(st, "st_file_attributes", 0) & CLOUD_ATTRS) if IS_WIN else False
        cat, act, mot = classify_file(name, st.st_size, nuvem)
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
        it.inc = (act == "copiar")
        it.rel = build_rel(local, cat, date, name, ext)
        return it

    def _scan_thread(self):
        try:
            self.log("Escaneamento iniciado.")
            items = []
            for src in self.cfg["sources"]:
                for plan in self.plan_roots(src):
                    for real, disp, name, st, local in self.walk_plan(plan):
                        it = self.make_item(real, disp, name, st, local)
                        items.append(it)
                        self.scan_info["files"] += 1
                        self.scan_info["bytes"] += st.st_size
                    items.extend(self.bookmark_items(plan))
            self.items = items
            self.phase = "scanned"
            self.log("Escaneamento concluído: %d arquivos, %d pastas ignoradas." % (len(items), self.ign_dirs_total))
        except Cancelled:
            self.phase = "idle"
            self.log("Escaneamento cancelado.")
        except Exception:
            self.error = traceback.format_exc()
            self.phase = "error"
            self.log("ERRO no escaneamento: " + self.error.splitlines()[-1])

    # ------------------------------------------------------------------ seleção e listas
    def matches(self, it, f):
        if f.get("local") not in (None, "") and it.local != f["local"]:
            return False
        if f.get("cat") not in (None, "") and it.cat != f["cat"]:
            return False
        if f.get("act") not in (None, "") and it.act != f["act"]:
            return False
        if f.get("inc") in ("1", 1, True) and not it.inc:
            return False
        if f.get("inc") in ("0", 0, False) and it.inc:
            return False
        if f.get("status") not in (None, ""):
            if self.final_status(it) != f["status"]:
                return False
        q = f.get("q")
        if q and q not in it.disp.lower():
            return False
        return True

    def select(self, d):
        on = bool(d.get("on"))
        n = 0
        if "idx" in d:
            idxs = d["idx"] if isinstance(d["idx"], list) else [d["idx"]]
            for i in idxs:
                if 0 <= i < len(self.items):
                    self.items[i].inc = on
                    n += 1
            return n
        f = dict(d.get("filter") or {})
        if f.get("q"):
            f["q"] = f["q"].lower()
        for it in self.items:
            if self.matches(it, f):
                if not f.get("act") and it.act != "copiar":
                    continue  # chaves de categoria/usuário/busca só mexem no que é pessoal; ignorados/revisar têm botões próprios
                it.inc = on
                n += 1
        return n

    def groups(self):
        g = {}
        cats = {}
        acts = {}
        for it in self.items:
            k = (it.local, it.cat, it.act)
            e = g.get(k)
            if e is None:
                e = g[k] = [0, 0, 0, 0]
            e[0] += 1
            e[1] += it.size
            if it.inc:
                e[2] += 1
                e[3] += it.size
            for dct, key in (((cats, it.cat) if it.act == "copiar" else (None, None)), (acts, it.act)):
                if dct is None:
                    continue
                c = dct.get(key)
                if c is None:
                    c = dct[key] = [0, 0, 0, 0]
                c[0] += 1
                c[1] += it.size
                if it.inc:
                    c[2] += 1
                    c[3] += it.size
        glist = [{"local": k[0], "cat": k[1], "act": k[2], "n": v[0], "bytes": v[1], "sel_n": v[2], "sel_bytes": v[3]} for k, v in g.items()]
        glist.sort(key=lambda x: (x["local"].lower(), x["cat"], x["act"]))
        cl = [{"cat": k, "n": v[0], "bytes": v[1], "sel_n": v[2], "sel_bytes": v[3]} for k, v in cats.items()]
        cl.sort(key=lambda x: -x["bytes"])
        al = {k: {"n": v[0], "bytes": v[1], "sel_n": v[2], "sel_bytes": v[3]} for k, v in acts.items()}
        return {"groups": glist, "cats": cl, "acts": al, "ign_dirs": self.ign_dirs[:600], "ign_dirs_total": self.ign_dirs_total}

    def files(self, q):
        f = {k: (v[0] if isinstance(v, list) else v) for k, v in q.items()}
        if f.get("q"):
            f["q"] = f["q"].lower()
        off = int(f.get("offset", 0))
        lim = min(int(f.get("limit", 200)), 500)
        out = []
        total = 0
        for i, it in enumerate(self.items):
            if self.matches(it, f):
                if total >= off and len(out) < lim:
                    out.append([i, it.disp, it.size, ("%04d-%02d-%02d" % it.date) if it.date else "", it.cat, it.act, 1 if it.inc else 0,
                                it.err or it.motivo, self.final_status(it), it.tags])
                total += 1
        return {"total": total, "rows": out}

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
        return {"sel_n": n, "sel_bytes": b, "free": free, "total": total, "fs": fs, "biggest": big,
                "cabe": b <= free * 0.995, "fat32_problema": fs in ("vfat", "msdos") and big > 4 * 1024 ** 3 - 1}

    def final_status(self, it):
        if it.inc:
            if it.status == "ok":
                return "ok"
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
            queue = [it for it in self.items if it.inc and (it.status is None or (retry_only and it.status == "falha"))]
            self.cancel.clear()
            self.run_ev.set()
            self.cp = {"done_files": 0, "total_files": len(queue), "done_bytes": 0, "total_bytes": sum(i.size for i in queue), "current": "",
                       "errors": 0, "start": time.time()}
            self.phase = "copying"
            self.samples.clear()
            os.makedirs(self.mapa_dir, exist_ok=True)
        threading.Thread(target=self._copy_thread, args=(queue, retry_only), daemon=True).start()

    def _copy_thread(self, queue, retry_only):
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
            except OSError as e:
                cause, msg = classify_err(e)
                last = (cause, msg)
                if cause == "io" and attempt < 2:
                    time.sleep(1.5)
                    continue
                break
        it.status = "falha"
        it.cause, it.err = last
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

    def hash_file(self, path, drop_cache=False):
        h = hashlib.sha256()
        with open(lp(path), "rb") as f:
            if drop_cache and hasattr(os, "posix_fadvise"):
                try:
                    os.posix_fadvise(f.fileno(), 0, 0, os.POSIX_FADV_DONTNEED)
                except OSError:
                    pass
            while True:
                self.check_run()
                b = f.read(CHUNK)
                if not b:
                    break
                h.update(b)
                self.vf["bytes_done"] += len(b)
        return h.hexdigest()

    def _verify_thread(self, targets, mode, sweep):
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
        for src in self.cfg["sources"]:
            for plan in self.plan_roots(src):
                for real, disp, name, st, local in self.walk_plan(plan):
                    it = known.get(disp)
                    if it is None:
                        cat, act, mot = classify_file(name, st.st_size, False)
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
        sumiram = [it.disp for it in self.items if it.disp not in seen and not it.disp.endswith("_Bookmarks.json") and "(favoritos)" not in it.disp]
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
            if st in ("ignorado", "revisar", "desmarcado"):
                k = (st, it.motivo if st != "desmarcado" else "Desmarcado por você na seleção")
                e = agg.setdefault(k, [0, 0])
                e[0] += 1
                e[1] += it.size
        out = [{"situacao": k[0], "motivo": k[1], "n": v[0], "bytes": v[1]} for k, v in agg.items()]
        out.sort(key=lambda x: -x["bytes"])
        return out

    def failures(self):
        out = []
        for i, it in enumerate(self.items):
            if it.inc and it.status == "falha":
                out.append({"idx": i, "disp": it.disp, "size": it.size, "err": it.err, "cause": it.cause})
        return out

    def status(self):
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
        return {
            "phase": self.phase, "paused": not self.run_ev.is_set(), "error": self.error, "scan": self.scan_info, "copy": self.cp, "verify": self.vf,
            "speed": speed, "eta": eta, "log": list(self.logs)[-60:], "cfg": self.cfg, "sweep": self.sweep, "verified_mode": self.verified_mode,
            "n_items": len(self.items), "finished": self.finished, "cert": self.cert, "dest_root": self.dest_root,
            "same_disk": getattr(self, "same_disk", False), "failures": self.failures()[:300] if self.phase in ("copied", "verified", "done") else [],
            "n_failures": sum(1 for it in self.items if it.inc and it.status == "falha"),
        }

    # ------------------------------------------------------------------ mapa e certificado
    def finish(self):
        with self.lock:
            if self.busy():
                raise Busy("Aguarde o processo atual terminar.")
            if self.phase not in ("verified", "done"):
                raise ValueError("Rode a verificação antes de concluir.")
            self.phase = "finishing"
        try:
            self._write_mapa()
            self.phase = "done"
            self.finished = True
            try:
                if FICHA:
                    c = self.cert
                    FICHA.hist_add(FICHA.machine_id_cache(), "backup", "Backup %s: %d arquivos (%s) · código %s" % ("sem falhas" if c["status"] == "sem_falhas" else "com ressalvas", c["copiados"], fmt_bytes(c["bytes"]), c["codigo"]),
                                   {"destino": self.dest_root, "codigo": c["codigo"], "cliente": c.get("cliente", "")})
            except Exception:
                pass
            return self.cert
        except Exception:
            self.error = traceback.format_exc()
            self.phase = "error"
            raise

    def _write_mapa(self):
        os.makedirs(self.mapa_dir, exist_ok=True)
        cfg = self.cfg
        f = []
        c_ok = c_fail = c_left = 0
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
            dst = it.rel if st in ("ok", "falha") else ""
            mot = "" if st == "ok" else (it.err if st == "falha" else (it.motivo if st != "desmarcado" else "Desmarcado por você na seleção"))
            f.append([it.disp, dst, it.cat, it.size, ("%04d-%02d-%02d" % it.date) if it.date else "", st, it.tags, it.local, mot, it.sha, int(it.mtime)])
        sw = self.sweep or {}
        ressalvas = c_fail + int(sw.get("n_novos", 0)) + int(sw.get("n_alterados", 0)) + int(sw.get("n_sumiram", 0))
        status = "sem_falhas" if ressalvas == 0 else "ressalvas"
        meta = {
            "pc": cfg["equip"], "data": datetime.date.today().isoformat(), "raiz": self.dest_root, "dstRel": True,
            "verificacao": "SHA-256 (completa)" if self.verified_mode == "completa" else "Tamanho (rápida)",
            "campos": ["origem", "destino_relativo", "categoria", "tamanho_bytes", "data", "situacao", "etiquetas", "usuario", "motivo", "sha256", "mtime_epoch"],
            "versao": VERSION,
        }
        left = self.left_behind()
        cert = {
            "status": status, "cliente": cfg["cliente"], "tecnico": cfg["tecnico"], "equipamento": cfg["equip"],
            "data": meta["data"], "hora": datetime.datetime.now().strftime("%H:%M"), "metodo": meta["verificacao"],
            "copiados": c_ok, "bytes": b_ok, "falhas": c_fail, "ficaram": c_left, "pastas_ign": self.ign_dirs_total,
            "motivos": left[:12], "sweep": {k: sw.get(k, 0) for k in ("n_novos", "n_alterados", "n_sumiram")},
            "sistema": "%s %s" % (platform.system(), platform.release()), "versao": VERSION,
        }
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
        return True, ""

    def firmware_reboot(self):
        ok, why = self.firmware_gate()
        if not ok:
            raise ValueError(why)
        if sys.platform == "darwin":
            raise ValueError("No Mac este botão não é suportado: reinicie segurando Command+R (Recuperação) ou Option (escolher disco).")
        try:
            if FICHA:
                FICHA.hist_add(FICHA.machine_id_cache(), "formatacao", "Reinício para BIOS/UEFI solicitado para formatar (backup verificado, código %s)" % self.cert.get("codigo", ""))
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
        f = FICHA.coletar(lambda e, p: cb(e, 40 + int(p * 0.6)))
        FICHA.salvar_ficha(f, "depois")
        return {"mid": mid, "aplicadas": res}
    ficha_iniciar("aplicar", fn)


# ----------------------------------------------------------------------------------------------
# Servidor HTTP local
# ----------------------------------------------------------------------------------------------
APP = App()


def dados_depois(tipo):
    """Callback chamado quando uma ação de Dados termina: registra no histórico da máquina e no log."""
    def cb(res):
        try:
            mid = FICHA.machine_id_cache()
            moved = int(res.get("bytes_lixeira") or 0) + int(res.get("bytes_removidos") or 0) + int(res.get("bytes_movidos") or 0)
            REC["bytes"] += int(res.get("bytes_removidos") or 0)
            if tipo == "limpar":
                resumo = "Limpeza de dados: %d item(ns), %s %s" % (res["itens"], fmt_bytes(moved), "removidos de vez" if res["modo"] == "definitivo" else "enviados para a Lixeira")
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
            if not APP.mapa_dir or not os.path.isdir(APP.mapa_dir):
                self.send_error(404)
                return
            nm = os.path.basename(path[6:])
            if nm not in ("visualizador.html", "dados.js", "logo.js", "Relatorio.csv", "certificado.json"):
                self.send_error(404)
                return
            return self._static(APP.mapa_dir, nm)
        if not path.startswith("/api/"):
            self.send_error(404)
            return
        if not self._auth(q):
            return self._json({"erro": "não autorizado"}, 401)
        if path == "/api/dados/ver":  # <img>/<video> não mandam cabeçalho: o token vem em ?t=
            try:
                arq, mime, tipo, limite = DADOS.previa((q.get("no") or [""])[0])
            except ValueError as e:
                return self._json({"erro": str(e)}, 400)
            return self._arquivo(arq, mime, limite, pagina=(tipo == "pdf"))
        try:
            return self._json(self.api_get(path, q))
        except Exception as e:
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
            return self._json(self.api_post(u.path, body))
        except PermissionError as e:
            if TERMO and isinstance(e, TERMO.SemPermissao):
                cod = str(e)
                if cod == "termo":
                    return self._json({"erro": "Aceite o termo de responsabilidade para continuar.", "codigo": "termo"}, 403)
                esc = cod.split(":", 1)[1] if ":" in cod else ""
                nm = {k: v for k, v, _ in TERMO.ESCOPOS}.get(esc, esc)
                return self._json({"erro": "Máquina de terceiros: falta a autorização do cliente para “%s”. Registre na aba OS." % nm, "codigo": "os", "escopo": esc}, 403)
            return self._json({"erro": str(e)}, 403)
        except (Busy, ValueError) as e:
            return self._json({"erro": str(e)}, 400)
        except Exception as e:
            if type(e).__name__ in ("SemConexao", "ErroServidor"):
                return self._json({"erro": str(e)}, 503)
            APP.log("ERRO interno: %s" % e)
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
        if path == "/api/totals":
            return APP.totals()
        if path == "/api/ficha/estado":
            return dict(FT)
        if path in ("/api/ficha/atual", "/api/maquina"):
            if not FICHA:
                raise ValueError("Módulo da ficha ausente (ficha.py).")
            mid = (q.get("mid") or [""])[0] or FICHA.machine_id_cache()
            v = FICHA.visao(mid)
            return {"mid": mid, "atual": mid == FICHA.machine_id_cache(), "visao": v, "pode_desfazer": FICHA.pode_desfazer(mid), "aplicadas": FICHA.aplicadas(mid), "root": FICHA.is_root() or FICHA.simulando(),
                    "win": FICHA.familia_atual() == "windows", "simulacao": FICHA.simulando()}
        if path == "/api/maquinas":
            return {"maquinas": FICHA.listar_maquinas() if FICHA else [], "pendrive": DADOS_DIR[0]}
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
        if path == "/api/mkdir":
            p = os.path.join(os.path.abspath(os.path.expanduser(b.get("path", ""))), safe_seg(b.get("name", "")))
            os.makedirs(p, exist_ok=True)
            return {"path": p}
        if path == "/api/preflight":
            return {"checks": APP.preflight()}
        if path == "/api/scan":
            self.exigir("backup")
            APP.start_scan()
            return {"ok": True}
        if path == "/api/select":
            return {"n": APP.select(b)}
        if path == "/api/copy":
            self.exigir("backup")
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
            return {"ok": ok, "motivo": why}
        if path == "/api/firmware":
            if not b.get("confirmo"):
                raise ValueError("Confirmação ausente.")
            self.exigir("formatar")
            if TERMO and TERMO.status(FICHA.machine_id_cache()).get("dono") == "terceiros" and (b.get("digitou") or "").strip().upper() != "FORMATAR":
                raise ValueError("Máquina de terceiros: digite FORMATAR para confirmar.")
            return APP.firmware_reboot()
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
        if path == "/api/dados/marcar":
            return {"id": DADOS.marcar(b.get("no"))}
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


def usar_pasta_dados(p):
    """Fichas, históricos e consentimentos em outra pasta (testes no próprio computador sem misturar com o pendrive)."""
    p = os.path.abspath(os.path.expanduser(p))
    os.makedirs(p, exist_ok=True)
    DADOS_DIR[0] = p
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
    usar_pasta_dados(cache)
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


def serve(port=0, open_browser=True, host="127.0.0.1", token_na_pagina=False):
    srv = ThreadingHTTPServer((host, port), Handler)
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
