"""Programas instalados: o que a máquina tem, para decidir o que reinstalar depois de formatar.

Para cada programa guarda só nome, versão, fabricante, origem e o identificador de instalador (winget, Homebrew,
apt, Flatpak, Snap) quando existe. Nunca lê chave de licença, senha ou conta.
A leitura do sistema fica em coletar_*; o resto (ler as saídas, agrupar, esconder) são funções puras, testáveis em
qualquer sistema. Mac validado em máquina real; Windows e Linux escritos sobre o mesmo padrão, ainda sem teste real."""
import datetime
import glob
import gzip
import json
import os
import plistlib
import re
import shutil
import subprocess
import sys
import unicodedata

IS_WIN = os.name == "nt"
IS_MAC = sys.platform == "darwin"
VERSAO = 1
CAMPOS = ("nome", "versao", "fabricante", "origem", "id", "arch", "oculto", "motivo")  # nada além disto sai de uma entrada

# o que não faz sentido reinstalar à mão depois de formatar (fica escondido, com "mostrar tudo")
OCULTAR = [
    ("runtime", ["visual c++", "redistributable", "vcredist", ".net framework", ".net runtime", ".net desktop runtime", "windows desktop runtime",
                 "asp.net core", "microsoft .net", "directx", "webview2", "visual studio tools for", "java(tm) se runtime", "java 8 update"]),
    ("atualização", ["update for", "security update", "hotfix for", "service pack", "(kb"]),
    ("driver", ["driver", "chipset", "realtek", "intel(r) management engine", "intel(r) rapid storage", "intel(r) serial io", "intel(r) graphics",
                "intel® graphics", "nvidia physx", "nvidia hd audio", "nvidia graphics", "amd software", "synaptics", "elan touchpad", "conexant",
                "dolby", "bluetooth", "wireless lan", "wi-fi", "killer performance", "thunderbolt", "card reader"]),
    ("componente da fabricante", ["supportassist", "support assistant", "dell update", "dell command", "dell digital delivery", "hp documentation",
                                  "hp system event", "hp support", "lenovo vantage", "lenovo system update", "lenovo service bridge", "asus live update",
                                  "myasus", "armoury crate", "acer care center", "acer quick access", "samsung settings"]),
    ("componente do sistema", ["microsoft update health tools", "windows pc health check", "microsoft edge update", "click-to-run extensibility",
                               "click-to-run localization", "microsoft gameinput", "windows software development kit", "windows sdk addon"]),
]


# ----------------------------------------------------------------------------------------------
# agrupar e esconder
# ----------------------------------------------------------------------------------------------
_ARCH_PAR = re.compile(r"\((?:x64|x86|64[- ]?bits?|32[- ]?bits?|amd64|arm64)\)", re.I)
_ARCH = re.compile(r"(?<![\w-])(?:x64|x86|64[- ]?bits?|32[- ]?bits?|amd64|arm64|win64|win32)(?![\w-])", re.I)
_VER = re.compile(r"\bv?\d+(?:\.\d+)+[a-z0-9-]*", re.I)


def _sem_acento(s):
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def _limpo(nome):
    """Nome sem versão e sem 32/64 bits: "7-Zip 23.01 (x64)" -> "7-Zip"."""
    s = _VER.sub(" ", _ARCH.sub(" ", _ARCH_PAR.sub(" ", nome or "")))
    s = re.sub(r"\s+", " ", s).strip(" -–_,")
    return s or (nome or "").strip()


def chave(nome):
    """Mesmo programa em 32 e 64 bits ou em várias versões cai na mesma chave."""
    return re.sub(r"[^a-z0-9+#]+", " ", _sem_acento(_limpo(nome)).lower()).strip()


def motivo_oculto(nome):
    n = (nome or "").lower()
    for motivo, pads in OCULTAR:
        if any(p in n for p in pads):
            return motivo
    return ""


def _nat(v):
    return [int(x) if x.isdigit() else x for x in re.split(r"(\d+)", v or "")]


def entrada(nome, versao="", fabricante="", origem="", id_="", arch="", motivo=""):
    nome = " ".join(str(nome or "").split())[:120]
    motivo = motivo or motivo_oculto(nome)
    return {"nome": nome, "versao": " ".join(str(versao or "").split())[:40], "fabricante": " ".join(str(fabricante or "").split())[:80],
            "origem": origem, "id": id_ or "", "arch": arch or "", "oculto": bool(motivo), "motivo": motivo}


def organizar(entradas):
    """Agrupa duplicados (32/64 bits, várias versões, a mesma coisa vista em dois lugares). Um grupo só fica escondido
    se todas as variantes forem escondidas. Os visíveis vêm primeiro, em ordem alfabética."""
    grupos = {}
    for e in entradas:
        if not e.get("nome"):
            continue
        k = chave(e["nome"])
        g = grupos.setdefault(k, {"nome": _limpo(e["nome"]), "versoes": [], "fabricante": "", "origens": [], "ids": {}, "arch": [],
                                  "oculto": True, "motivo": "", "variantes": 0})
        g["variantes"] += 1
        if e.get("versao") and e["versao"] not in g["versoes"]:
            g["versoes"].append(e["versao"])
        g["fabricante"] = g["fabricante"] or e.get("fabricante", "")
        if e.get("origem") and e["origem"] not in g["origens"]:
            g["origens"].append(e["origem"])
        if e.get("id") and ":" in e["id"]:
            tipo, _, val = e["id"].partition(":")
            g["ids"].setdefault(tipo, val)
        if e.get("arch") and e["arch"] not in g["arch"]:
            g["arch"].append(e["arch"])
        if e.get("oculto"):
            g["motivo"] = g["motivo"] or e.get("motivo", "")
        else:
            g["oculto"] = False
    out = []
    for g in grupos.values():
        g["versoes"].sort(key=_nat)
        g["arch"].sort()
        if not g["oculto"]:
            g["motivo"] = ""
        out.append(g)
    return sorted(out, key=lambda g: (g["oculto"], g["nome"].lower()))


def visiveis(grupos, tudo=False):
    """O que a tela mostra: por padrão sem runtimes, drivers e componentes; tudo=True ("mostrar tudo") devolve a lista inteira."""
    return list(grupos) if tudo else [g for g in grupos if not g["oculto"]]


def documento(entradas, familia):
    """O que vai para maquinas/<código>/programas.json: a lista completa detectada, já agrupada."""
    itens = organizar(entradas)
    return {"versao": VERSAO, "quando": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"), "familia": familia,
            "total": len(itens), "visiveis": sum(1 for g in itens if not g["oculto"]), "com_instalador": sum(1 for g in itens if g["ids"] and not g["oculto"]),
            "itens": itens}


def resumo(doc):
    if not doc:
        return None
    return {k: doc.get(k) for k in ("quando", "familia", "total", "visiveis", "com_instalador")}


# ----------------------------------------------------------------------------------------------
# Windows: chaves de desinstalação (lidas no PowerShell da ficha) + winget list, se existir
# ----------------------------------------------------------------------------------------------
PS_PROGS = r"""
$r.progs=@(Get-ItemProperty 'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*','HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*','HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*' -ErrorAction SilentlyContinue | Where-Object {$_.DisplayName} | ForEach-Object { @{n=$_.DisplayName;v=$_.DisplayVersion;p=$_.Publisher;k=$_.PSChildName;s=[int]$_.SystemComponent;pk=$_.ParentKeyName;w=[bool]($_.PSPath -match 'WOW6432Node');u=[bool]($_.PSPath -match 'HKEY_CURRENT_USER')} })
$r.appx=@(Get-AppxPackage -ErrorAction SilentlyContinue | Where-Object {-not $_.IsFramework -and $_.SignatureKind -eq 'Store' -and -not $_.NonRemovable} | ForEach-Object { @{n=$_.Name;v=$_.Version.ToString();p=$_.Publisher} })
"""


def ler_winget(texto):
    """Tabela do `winget list` (em inglês ou português): {nome: id} só do que veio do winget ou da Microsoft Store.
    As colunas saem das posições do cabeçalho; nome cortado ("…") é guardado sem o "…" para casar pelo começo."""
    linhas = [ln.split("\r")[-1].rstrip() for ln in (texto or "").splitlines()]
    i = next((n for n, ln in enumerate(linhas) if n and re.fullmatch(r"-{10,}", ln.strip())), None)
    if i is None:
        return {}
    cab = linhas[i - 1]
    ini = [m.start() for m in re.finditer(r"\S+", cab)]
    if len(ini) < 3:
        return {}
    out = {}
    for ln in linhas[i + 1:]:
        if not ln.strip():
            continue
        col = [ln[a:b].strip() for a, b in zip(ini, ini[1:] + [None])]
        nome, id_ = col[0], col[1]
        fonte = col[-1].lower() if len(ini) >= 4 else ""
        if not nome or not id_ or id_.endswith("…") or id_.startswith(("ARP\\", "MSIX\\")) or fonte not in ("winget", "msstore"):
            continue
        out[nome] = ("winget:" if fonte == "winget" else "msstore:") + id_
    return out


def _casar(nome, wg, prefixo=False):
    """Acha o id do winget para um nome: igual, ou começo igual quando o winget cortou o nome. prefixo: apps da Store,
    cujo nome do pacote ("WhatsAppDesktop") costuma ser o nome do winget ("WhatsApp") com algo depois."""
    k = chave(nome).replace(" ", "")
    for n, i in wg.items():
        if chave(n.rstrip("…")).replace(" ", "") == k:
            return i
    for n, i in wg.items():
        c = chave(n.rstrip("…")).replace(" ", "")
        if (n.endswith("…") or prefixo) and len(c) >= 6 and k.startswith(c):
            return i
    return ""


def de_windows(progs, appx=None, winget_txt=""):
    wg = ler_winget(winget_txt)
    out = []
    for p in progs or []:
        nome = p.get("n") or ""
        if not nome:
            continue
        motivo = "componente do sistema" if (p.get("s") or p.get("pk")) else ""
        origem = "Windows (usuário)" if p.get("u") else "Windows"
        out.append(entrada(nome, p.get("v"), p.get("p"), origem, _casar(nome, wg), "32" if p.get("w") else ("" if p.get("u") else "64"), motivo))
    for a in appx or []:
        pacote = str(a.get("n") or "")
        if not pacote:
            continue
        nome = pacote.split(".", 1)[-1] if "." in pacote else pacote
        cn = re.search(r"CN=([^,]+)", str(a.get("p") or ""))
        cn = cn.group(1).strip() if cn and not re.fullmatch(r"[0-9A-Fa-f-]{30,}", cn.group(1).strip()) else ""  # CN de loja costuma ser só um GUID
        out.append(entrada(nome, a.get("v"), cn, "Microsoft Store", _casar(nome, wg, True), "",
                           "vem com o sistema" if pacote.startswith("Microsoft.") else ""))
    return out


def winget_list():
    """Só se o winget existir. Sem aceitar termos por ninguém: se ele pedir confirmação, a resposta é vazia e seguimos sem ids."""
    exe = shutil.which("winget")
    return _rodar([exe, "list"], 90) if exe else ""


# ----------------------------------------------------------------------------------------------
# Mac: pastas .app (versão e fabricante do Info.plist) + Homebrew
# ----------------------------------------------------------------------------------------------
def _fabricante_mac(info):
    c = str(info.get("NSHumanReadableCopyright") or "")
    c = re.sub(r"(?i)copyright|©|\(c\)|all rights reserved\.?|todos os direitos reservados\.?", " ", c)
    c = re.sub(r"\b\d{4}(?:\s*[-–]\s*\d{4})?\b", " ", c)
    c = re.sub(r"\s+", " ", c).strip(" .,;-–")
    if c and len(c) <= 60:
        return c
    partes = str(info.get("CFBundleIdentifier") or "").split(".")
    return partes[1].capitalize() if len(partes) > 2 and partes[0] in ("com", "org", "net", "io", "br", "de") else ""


def _apps_em(base):
    for n in sorted(os.listdir(base)) if os.path.isdir(base) else []:
        p = os.path.join(base, n)
        if n.endswith(".app"):
            yield p
        elif os.path.isdir(p) and not n.startswith(".") and n != "Utilities":
            for m in sorted(os.listdir(p)):  # um nível: "Adobe Photoshop 2024/Adobe Photoshop 2024.app"
                if m.endswith(".app"):
                    yield os.path.join(p, m)


def de_mac(bases):
    out = []
    for base in bases:
        for app in _apps_em(base):
            try:
                with open(os.path.join(app, "Contents", "Info.plist"), "rb") as fh:
                    info = plistlib.load(fh)
            except Exception:
                info = {}
            loja = os.path.exists(os.path.join(app, "Contents", "_MASReceipt"))
            bid = str(info.get("CFBundleIdentifier") or "")
            motivo = ("atalho de site (Safari)" if bid.startswith("com.apple.Safari.WebApp") else
                      "vem com o sistema" if bid.startswith("com.apple.") and not loja else "")
            out.append(entrada(os.path.basename(app)[:-4], info.get("CFBundleShortVersionString") or info.get("CFBundleVersion"), _fabricante_mac(info),
                               "App Store" if loja else "Aplicativos", "", "", motivo))
    return out


def ler_brew(casks_txt, formulas_txt, pedidas_txt):
    """`brew list --cask --versions`, `brew list --formula --versions` e `brew leaves`: casks (apps) e fórmulas pedidas pelo usuário."""
    def pares(t):
        for ln in (t or "").splitlines():
            p = ln.split()
            if p:
                yield p[0], (p[-1] if len(p) > 1 else "")
    casks = list(pares(casks_txt))
    pedidas = {ln.strip() for ln in (pedidas_txt or "").splitlines() if ln.strip()}
    formulas = [(n, v) for n, v in pares(formulas_txt) if n in pedidas]
    return casks, formulas


def com_brew(entradas, casks, formulas):
    """Cask que casa com um .app vira o identificador dele; o resto entra como item próprio do Homebrew."""
    por = {chave(e["nome"]).replace(" ", ""): e for e in entradas}
    for nome, ver in casks:
        e = por.get(re.sub(r"[^a-z0-9+#]", "", nome.lower()))
        if e:
            e["id"] = e["id"] or "brew:" + nome
        else:
            entradas.append(entrada(nome, ver, "", "Homebrew", "brew:" + nome))
    for nome, ver in formulas:
        entradas.append(entrada(nome, ver, "", "Homebrew (linha de comando)", "brew:" + nome))
    return entradas


def coletar_mac():
    h = _home()
    out = de_mac(["/Applications", "/Applications/Utilities", os.path.join(h, "Applications")])
    brew = shutil.which("brew") or next((b for b in ("/opt/homebrew/bin/brew", "/usr/local/bin/brew") if os.path.exists(b)), "")
    if brew:
        pre = ["sudo", "-u", os.environ["SUDO_USER"]] if os.geteuid() == 0 and os.environ.get("SUDO_USER") else []
        if os.geteuid() != 0 or pre:  # o Homebrew se recusa a rodar como root
            casks, formulas = ler_brew(_rodar(pre + [brew, "list", "--cask", "--versions"], 30), _rodar(pre + [brew, "list", "--formula", "--versions"], 30),
                                       _rodar(pre + [brew, "leaves", "--installed-on-request"], 30) or _rodar(pre + [brew, "leaves"], 30))
            com_brew(out, casks, formulas)
    return out


# ----------------------------------------------------------------------------------------------
# Linux (Zorin/Ubuntu): apt instalado à mão, Flatpak, Snap; rpm onde não há dpkg
# ----------------------------------------------------------------------------------------------
def ler_desktop(path):
    """Name= e NoDisplay= de um atalho .desktop (só a seção principal)."""
    nome, esconde = "", False
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            sec = ""
            for ln in fh:
                ln = ln.strip()
                if ln.startswith("["):
                    sec = ln
                elif sec == "[Desktop Entry]":
                    if ln.startswith("Name=") and not nome:
                        nome = ln[5:].strip()
                    elif ln.lower() in ("nodisplay=true", "hidden=true"):
                        esconde = True
    except OSError:
        pass
    return nome, esconde


def ler_pacotes_status(texto):
    """Pacotes de um arquivo no formato do dpkg (Package:), ex. /var/log/installer/initial-status.gz."""
    return {ln[9:].strip().split(":")[0] for ln in (texto or "").splitlines() if ln.startswith("Package: ")}


def ler_auto(texto):
    """/var/lib/apt/extended_states: pacotes que entraram como dependência (Auto-Installed: 1)."""
    auto, pac = set(), ""
    for ln in (texto or "").splitlines():
        if ln.startswith("Package: "):
            pac = ln[9:].strip()
        elif ln.strip() == "Auto-Installed: 1" and pac:
            auto.add(pac)
    return auto


def de_dpkg(query_txt, auto, iniciais, desktops):
    """query_txt: `dpkg-query -W -f '${Package}\\t${Version}\\t${db:Status-Abbrev}\\n'`.
    desktops: {pacote: [nomes dos atalhos]}. Aparece o que tem janela e foi instalado à mão depois do sistema."""
    out = []
    for ln in (query_txt or "").splitlines():
        p = ln.split("\t")
        if len(p) < 3 or not p[2].startswith("ii"):
            continue
        pac, ver = p[0].split(":")[0], p[1]
        nomes = desktops.get(pac) or []
        if pac in auto:
            motivo = "dependência"
        elif not nomes:
            motivo = "sem janela (linha de comando ou biblioteca)"
        elif pac in iniciais:
            motivo = "vem com o sistema"
        else:
            motivo = ""
        out.append(entrada(nomes[0] if len(nomes) == 1 else pac, ver, "", "apt", "apt:" + pac, "", motivo))
    return out


def ler_flatpak(texto):
    """`flatpak list --app --columns=application,name,version,origin` (separado por tab)."""
    out = []
    for ln in (texto or "").splitlines():
        p = ln.split("\t")
        if len(p) >= 2 and "." in p[0]:
            out.append(entrada(p[1] or p[0], p[2] if len(p) > 2 else "", "", "Flatpak" + (" (%s)" % p[3] if len(p) > 3 and p[3] else ""), "flatpak:" + p[0]))
    return out


def ler_snap(texto):
    """`snap list`: Name Version Rev Tracking Publisher Notes. Bases e o próprio snapd ficam escondidos."""
    out = []
    for ln in (texto or "").splitlines()[1:]:
        p = ln.split()
        if len(p) < 5:
            continue
        nome, notas = p[0], (p[5] if len(p) > 5 else "")
        base = notas in ("base", "snapd", "core") or re.match(r"^(core\d*|snapd|bare|gtk-common-themes|gnome-\d|kde-frameworks|mesa-)", nome)
        out.append(entrada(nome, p[1], p[4].rstrip("✓*").strip("*"), "Snap", "snap:" + nome, "", "runtime" if base else ""))
    return out


def _desktops_dpkg():
    """{pacote: [Name dos atalhos visíveis]} a partir de /var/lib/dpkg/info/*.list (sem chamar o dpkg uma vez por arquivo)."""
    out = {}
    for lst in glob.glob("/var/lib/dpkg/info/*.list"):
        pac = os.path.basename(lst)[:-5].split(":")[0]
        try:
            with open(lst, encoding="utf-8", errors="replace") as fh:
                for ln in fh:
                    ln = ln.strip()
                    if ln.startswith("/usr/share/applications/") and ln.endswith(".desktop"):
                        nome, esconde = ler_desktop(ln)
                        if nome and not esconde:
                            out.setdefault(pac, []).append(nome)
        except OSError:
            pass
    return out


def coletar_linux():
    out = []
    if shutil.which("dpkg-query"):
        try:
            with open("/var/lib/apt/extended_states", encoding="utf-8", errors="replace") as fh:
                auto = ler_auto(fh.read())
        except OSError:
            auto = set()
        try:
            with gzip.open("/var/log/installer/initial-status.gz", "rt", encoding="utf-8", errors="replace") as fh:
                iniciais = ler_pacotes_status(fh.read())
        except OSError:
            iniciais = set()
        out += de_dpkg(_rodar(["dpkg-query", "-W", "-f", "${Package}\t${Version}\t${db:Status-Abbrev}\n"], 60), auto, iniciais, _desktops_dpkg())
    elif shutil.which("rpm"):
        com_janela = set(_rodar(["rpm", "-qf", "--qf", "%{NAME}\n"] + glob.glob("/usr/share/applications/*.desktop"), 60).split())
        for ln in _rodar(["rpm", "-qa", "--qf", "%{NAME}\t%{VERSION}\t%{VENDOR}\n"], 60).splitlines():
            p = ln.split("\t")
            if len(p) >= 2:
                out.append(entrada(p[0], p[1], p[2] if len(p) > 2 else "", "rpm", "rpm:" + p[0], "",
                                   "" if p[0] in com_janela else "sem janela (linha de comando ou biblioteca)"))
    if shutil.which("flatpak"):
        out += ler_flatpak(_rodar(["flatpak", "list", "--app", "--columns=application,name,version,origin"], 60))
    if shutil.which("snap"):
        out += ler_snap(_rodar(["snap", "list"], 60))
    vistos = {chave(e["nome"]) for e in out}
    for d in sorted(glob.glob(os.path.join(_home(), ".local/share/applications/*.desktop"))):  # AppImage e afins
        nome, esconde = ler_desktop(d)
        if nome and not esconde and chave(nome) not in vistos:
            out.append(entrada(nome, "", "", "atalho do usuário"))
    return out


# ----------------------------------------------------------------------------------------------
def coletar():
    """Esta máquina (Mac ou Linux). No Windows a lista vem do PowerShell da ficha (PS_PROGS) e do winget_list()."""
    try:
        return coletar_mac() if IS_MAC else ([] if IS_WIN else coletar_linux())
    except Exception:
        return []


def _home():
    u = os.environ.get("SUDO_USER")
    return os.path.expanduser("~" + u) if u and hasattr(os, "geteuid") and os.geteuid() == 0 else os.path.expanduser("~")


def _rodar(cmd, timeout):
    try:
        r = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, timeout=timeout, creationflags=0x08000000 if IS_WIN else 0)
        return (r.stdout or b"").decode("utf-8", "replace")
    except Exception:
        return ""


def ler(pasta):
    try:
        with open(os.path.join(pasta, "programas.json"), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None
