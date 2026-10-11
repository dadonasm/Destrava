# -*- coding: utf-8 -*-
"""
Destrava! - Central de Otimizações. Só biblioteca padrão.

Tudo que dá para fazer pelo desempenho e pelo espaço, em Windows, Mac e Linux (Zorin), cada item com:
  ganho explícito  (medido nesta máquina, +N pontos simulados na nota, ou qualitativo com o porquê)
  ônus             (texto curto; a tela mostra ⚠ e o aviso ao passar o mouse)
  volta            (reversível com Desfazer, ou "sem volta")
O técnico escolhe. Vêm marcadas de início só as recomendadas SEM ônus.

Coleta: os trechos de PowerShell daqui entram na coleta do Windows (ficha.PS_COLETA); no Mac e no Linux
coletar_mac() / coletar_linux() rodam junto com a ficha. Tudo fica em ficha["otim"], então uma coleta
exportada reproduz a Central inteira em outro computador.
"""
import base64
import datetime
import hashlib
import json
import os
import plistlib
import re
import shutil
import subprocess
import sys

IS_WIN = os.name == "nt"
IS_MAC = sys.platform == "darwin"
GUID_RE = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
ALTO_DESEMPENHO = "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c"


def _f():
    import ficha  # importado na hora (ficha também importa este módulo)
    return ficha


def _id(prefixo, *partes):
    return prefixo + ":" + hashlib.sha1("|".join(str(p) for p in partes).encode("utf-8")).hexdigest()[:10]


def _gb(b):
    return "%.1f GB" % (b / 1e9) if b >= 1e8 else "%.0f MB" % (b / 1e6)


# ==============================================================================================
# coleta - Windows (entra no PS_COLETA da ficha)
# ==============================================================================================
PS_INI = r"""
function Aprovado($hive,$kind,$nome){ $p="$hive\Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\$kind"; try{ $v=(Get-ItemProperty -Path $p -Name $nome -ErrorAction Stop).$nome; if($v -and ($v[0] % 2) -eq 1){ return $false } }catch{}; return $true }
$ini=@()
foreach($k in @(@('HKCU:','Run','HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'),@('HKLM:','Run','HKLM:\Software\Microsoft\Windows\CurrentVersion\Run'),@('HKLM:','Run32','HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Run'))){
  $it=Get-Item -Path $k[2] -ErrorAction SilentlyContinue
  if($it){ foreach($n in $it.GetValueNames()){ if($n){ $ini+=@{fonte='run';hive=$k[0];kind=$k[1];nome=$n;cmd=[string]$it.GetValue($n);ativo=(Aprovado $k[0] $k[1] $n)} } } }
}
foreach($pa in @(@('HKCU:',[Environment]::GetFolderPath('Startup')),@('HKLM:',[Environment]::GetFolderPath('CommonStartup')))){
  if($pa[1] -and (Test-Path $pa[1])){
    Get-ChildItem $pa[1] -File -Force -ErrorAction SilentlyContinue | Where-Object { $_.Name -ne 'desktop.ini' } | ForEach-Object {
      $alvo=''; if($_.Extension -eq '.lnk'){ try{ $alvo=(New-Object -ComObject WScript.Shell).CreateShortcut($_.FullName).TargetPath }catch{} }
      $ini+=@{fonte='pasta';hive=$pa[0];kind='StartupFolder';nome=$_.Name;cmd=$(if($alvo){$alvo}else{$_.FullName});ativo=(Aprovado $pa[0] 'StartupFolder' $_.Name)}
    }
  }
}
$sad='HKCU:\Software\Classes\Local Settings\Software\Microsoft\Windows\CurrentVersion\AppModel\SystemAppData'
if(Test-Path $sad){ Get-ChildItem $sad -ErrorAction SilentlyContinue | ForEach-Object { $pkg=$_.PSChildName; Get-ChildItem $_.PSPath -ErrorAction SilentlyContinue | ForEach-Object {
  $st=(Get-ItemProperty -Path $_.PSPath -Name State -ErrorAction SilentlyContinue).State
  if($st -ne $null){ $ini+=@{fonte='store';pacote=$pkg;tarefa=$_.PSChildName;nome=($pkg -split '_')[0];cmd=$pkg;ativo=($st -eq 2 -or $st -eq 4);estado=$st} } } } }
$r.ini=$ini
$r.procpath=@(Get-Process | Where-Object { $_.Path } | Group-Object Path | ForEach-Object { @{p=$_.Name;ram=[int64](($_.Group | Measure-Object WorkingSet64 -Sum).Sum)} })
$deg=@{}
Get-WinEvent -FilterHashtable @{LogName='Microsoft-Windows-Diagnostics-Performance/Operational';Id=101;StartTime=(Get-Date).AddDays(-60)} -MaxEvents 300 -ErrorAction SilentlyContinue | ForEach-Object {
  $x=[xml]$_.ToXml(); $d=@{}; foreach($n in $x.Event.EventData.Data){ $d[$n.Name]=$n.'#text' }
  $nm=[string]$d['Name']; if($nm){ $v=[int]$d['DegradationTime']; if(-not $deg.ContainsKey($nm) -or $deg[$nm] -lt $v){ $deg[$nm]=$v } } }
$r.deg=$deg
"""

PS_OTIM = r"""
function V($k,$n){ try{ (Get-ItemProperty -Path $k -Name $n -ErrorAction Stop).$n }catch{ $null } }
$o=@{}
$o.vfx=V 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\VisualEffects' 'VisualFXSetting'
$o.transp=V 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Themes\Personalize' 'EnableTransparency'
$o.anim=V 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced' 'TaskbarAnimations'
$o.plano=((powercfg /getactivescheme) -join ' ')
$o.hiber=V 'HKLM:\SYSTEM\CurrentControlSet\Control\Power' 'HibernateEnabled'
$hf=Get-Item "$env:SystemDrive\hiberfil.sys" -Force -ErrorAction SilentlyContinue; if($hf){ $o.hiberfil=$hf.Length }
foreach($s in 'SysMain','WSearch'){ $sv=Get-Service $s -ErrorAction SilentlyContinue; if($sv){ $o[$s]=@{status=[string]$sv.Status;start=[string]$sv.StartType} } }
$o.bgapps=V 'HKCU:\Software\Microsoft\Windows\CurrentVersion\BackgroundAccessApplications' 'GlobalUserDisabled'
$cdm='HKCU:\Software\Microsoft\Windows\CurrentVersion\ContentDeliveryManager'; $o.cdm=@{}
foreach($n in 'SubscribedContent-338388Enabled','SubscribedContent-338389Enabled','SubscribedContent-353694Enabled','SubscribedContent-353696Enabled','SystemPaneSuggestionsEnabled','SilentInstalledAppsEnabled','SoftLandingEnabled'){ $o.cdm[$n]=V $cdm $n }
$o.gamedvr=V 'HKCU:\System\GameConfigStore' 'GameDVR_Enabled'
$o.appcap=V 'HKCU:\Software\Microsoft\Windows\CurrentVersion\GameDVR' 'AppCaptureEnabled'
$o.domode=V 'HKLM:\SOFTWARE\Policies\Microsoft\Windows\DeliveryOptimization' 'DODownloadMode'
$o.storsense=V 'HKCU:\Software\Microsoft\Windows\CurrentVersion\StorageSense\Parameters\StoragePolicy' '01'
if(Test-Path "$env:SystemDrive\Windows.old"){ $o.winold=(Get-ChildItem "$env:SystemDrive\Windows.old" -Recurse -Force -File -ErrorAction SilentlyContinue | Measure-Object Length -Sum).Sum }
$o.tarefas=@(Get-ScheduledTask -ErrorAction SilentlyContinue | Where-Object { $_.State -ne 'Disabled' -and $_.TaskName -match 'GoogleUpdate|GoogleUpdater|Adobe Acrobat Update|AdobeGCInvoker|MicrosoftEdgeUpdate|CCleaner|Opera scheduled|BraveSoftwareUpdate|DropboxUpdate|ZoomUpdate|Avast' } | ForEach-Object { @{nome=$_.TaskName;pasta=$_.TaskPath} })
$od=$env:OneDrive
if($od -and (Test-Path $od)){ $lim=(Get-Date).AddDays(-90); $tot=[int64]0; $n=0
  Get-ChildItem $od -Recurse -File -Force -ErrorAction SilentlyContinue | Where-Object { -not ($_.Attributes -band 0x400000) -and -not ($_.Attributes -band 0x1000) -and -not ($_.Attributes -band 0x80000) -and $_.LastAccessTime -lt $lim } | ForEach-Object { $tot+=$_.Length; $n++ }
  $o.onedrive=@{pasta=$od;bytes=$tot;arquivos=$n} }
$r.otim=$o
"""


def normalizar_ini_windows(raw):
    """Itens de inicialização iguais aos do Gerenciador de Tarefas (inclusive apps da Store e os já desativados)."""
    out = []
    for e in raw or []:
        if not isinstance(e, dict) or not e.get("nome"):
            continue
        fonte = e.get("fonte", "")
        nome = str(e["nome"])
        if fonte == "store":
            nome = nome.split(".")[-1] or nome  # SpotifyAB.SpotifyMusic -> SpotifyMusic
        elif fonte == "pasta":
            nome = re.sub(r"\.lnk$", "", nome, flags=re.I)
        local = {"run": "%s\\...\\%s" % (e.get("hive", ""), e.get("kind", "")), "pasta": "Pasta Inicializar (%s)" % ("usuário" if e.get("hive") == "HKCU:" else "todos"),
                 "store": "App da Microsoft Store"}.get(fonte, "")
        out.append({"id": _id("ini", fonte, e.get("hive"), e.get("kind"), e.get("nome"), e.get("pacote"), e.get("tarefa")), "nome": nome, "comando": str(e.get("cmd") or ""),
                    "local": local, "usuario": "", "fonte": fonte, "hive": e.get("hive"), "kind": e.get("kind"), "valor": e.get("nome"), "pacote": e.get("pacote"),
                    "tarefa": e.get("tarefa"), "ativo": bool(e.get("ativo", True)), "exe": exe_de(e.get("cmd"))})
    return out


def exe_de(cmd):
    """Nome do executável de uma linha de comando ("C:\\x\\OneDrive.exe" /background -> onedrive.exe)."""
    cmd = (cmd or "").strip()
    m = re.match(r'^"([^"]+)"', cmd) or re.match(r"^(.+?\.(?:exe|app|sh|py|bin))\b", cmd, re.I) or re.match(r"^(\S+)", cmd)
    return os.path.basename(m.group(1).replace("\\", "/")).lower() if m else ""


# ==============================================================================================
# coleta - Mac e Linux (roda junto com a ficha)
# ==============================================================================================
def _run(cmd, timeout=30, env=None):
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=timeout, env=env)
        return r.returncode, (r.stdout or b"").decode("utf-8", "replace"), (r.stderr or b"").decode("utf-8", "replace")
    except Exception as e:
        return 1, "", str(e)


def _usuario():
    """(nome, uid, gid, pasta) de quem está usando o computador (quem chamou o sudo, se for o caso)."""
    import pwd
    nome = os.environ.get("SUDO_USER") or ""
    try:
        p = pwd.getpwnam(nome) if nome else pwd.getpwuid(os.getuid())
        return p.pw_name, p.pw_uid, p.pw_gid, p.pw_dir
    except Exception:
        return nome, os.getuid(), os.getgid(), os.path.expanduser("~")


def _como_usuario(cmd, sessao=False):
    """Roda como o usuário logado (não como root): defaults, gsettings, brew e osascript são por usuário."""
    nome, uid, _, casa = _usuario()
    env = dict(os.environ, HOME=casa)
    if sessao and not IS_MAC:
        env.update(XDG_RUNTIME_DIR="/run/user/%d" % uid, DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/%d/bus" % uid)
    if hasattr(os, "geteuid") and os.geteuid() == 0 and nome and nome != "root" and shutil.which("sudo"):
        extra = ["XDG_RUNTIME_DIR=" + env["XDG_RUNTIME_DIR"], "DBUS_SESSION_BUS_ADDRESS=" + env["DBUS_SESSION_BUS_ADDRESS"]] if sessao and not IS_MAC else []
        return ["sudo", "-u", nome, "env", "HOME=" + casa] + extra + cmd, env
    return cmd, env


def _run_usuario(cmd, timeout=60, sessao=False):
    c, env = _como_usuario(cmd, sessao)
    return _run(c, timeout, env)


def _tam_dir(p):
    try:
        import dados
        return dados.tamanho_dir(p, None, set())[0]
    except Exception:
        return 0


def coletar_mac():
    """(inicialização com ativos e desativados, dados para a Central). Melhor esforço: cada leitura é independente."""
    nome, uid, _, casa = _usuario()
    ini, o = [], {}
    # itens de login (pede permissão de Automação na primeira vez)
    rc, out, _ = _run_usuario(["osascript", "-l", "JavaScript", "-e", 'var s=Application("System Events");JSON.stringify(s.loginItems().map(function(i){return {nome:i.name(),path:i.path()}}))'], 20)
    try:
        for li in json.loads(out) if rc == 0 else []:
            ini.append({"id": _id("ini", "login", li.get("nome")), "nome": li.get("nome", "?"), "comando": li.get("path", ""), "local": "Itens de login", "usuario": nome,
                        "fonte": "login", "ativo": True, "arquivo": li.get("path", ""), "exe": os.path.basename(li.get("path", "")).lower()})
    except ValueError:
        pass
    # agentes em segundo plano (LaunchAgents do usuário e de todos)
    rc, out, _ = _run(["launchctl", "print-disabled", "gui/%d" % uid], 10)
    desligados = set(re.findall(r'"([^"]+)"\s*=>\s*(?:disabled|true)', out))
    for base in (os.path.join(casa, "Library", "LaunchAgents"), "/Library/LaunchAgents"):
        try:
            nomes = sorted(os.listdir(base))
        except OSError:
            continue
        for n in nomes:
            if not n.endswith(".plist") or n.startswith("com.apple."):
                continue
            p = os.path.join(base, n)
            try:
                with open(p, "rb") as fh:
                    pl = plistlib.load(fh)
            except Exception:
                continue
            label = pl.get("Label") or n[:-6]
            prog = pl.get("Program") or ((pl.get("ProgramArguments") or [""])[0])
            ini.append({"id": _id("ini", "agente", p), "nome": label, "comando": prog, "local": base.replace(casa, "~"), "usuario": nome, "fonte": "agente",
                        "ativo": label not in desligados and not pl.get("Disabled"), "arquivo": p, "label": label, "exe": os.path.basename(str(prog)).lower()})
    # visual
    o["movimento"] = {}
    for k in ("reduceMotion", "reduceTransparency"):
        rc, out, _ = _run_usuario(["defaults", "read", "com.apple.universalaccess", k], 10)
        o["movimento"][k] = out.strip() if rc == 0 else None
    # espaço purgável e instantâneos do Time Machine
    rc, out, _ = _run(["osascript", "-l", "JavaScript", "-e", 'ObjC.import("Foundation");var u=$.NSURL.fileURLWithPath("/");var k=["NSURLVolumeAvailableCapacityForImportantUsageKey","NSURLVolumeAvailableCapacityKey"];var r=u.resourceValuesForKeysError(k,null);JSON.stringify([r.objectForKey(k[0]).js,r.objectForKey(k[1]).js])'], 15)
    try:
        imp, disp = json.loads(out)
        o["purgavel"] = max(0, int(imp) - int(disp))
    except (ValueError, TypeError):
        o["purgavel"] = None
    rc, out, _ = _run(["tmutil", "listlocalsnapshots", "/"], 15)
    o["snapshots"] = len(re.findall(r"com\.apple\.TimeMachine\.", out))
    # backups de iPhone/iPad
    mb = os.path.join(casa, "Library", "Application Support", "MobileSync", "Backup")
    try:
        bks = []
        for d in sorted(os.listdir(mb)):
            p = os.path.join(mb, d)
            if not os.path.isdir(p):
                continue
            info = {}
            try:
                with open(os.path.join(p, "Info.plist"), "rb") as fh:
                    info = plistlib.load(fh)
            except Exception:
                pass
            data = info.get("Last Backup Date")
            bks.append({"nome": info.get("Device Name") or d[:12], "data": data.strftime("%Y-%m-%d") if hasattr(data, "strftime") else "", "bytes": _tam_dir(p), "path": p})
        o["iphone"] = bks
    except PermissionError:
        o["iphone"] = "sem_acesso"
    except OSError:
        o["iphone"] = []
    # iCloud Drive baixado no Mac
    o["icloud"] = _tam_dir(os.path.join(casa, "Library", "Mobile Documents")) if os.path.isdir(os.path.join(casa, "Library", "Mobile Documents")) else 0
    # ferramentas de desenvolvimento (só se existirem)
    dd = os.path.join(casa, "Library", "Developer", "Xcode", "DerivedData")
    o["xcode"] = {"path": dd, "bytes": _tam_dir(dd)} if os.path.isdir(dd) else None
    o["brew"] = None
    if shutil.which("brew") or os.path.exists("/opt/homebrew/bin/brew"):
        rc, out, _ = _run_usuario([shutil.which("brew") or "/opt/homebrew/bin/brew", "--cache"], 20)
        if rc == 0 and os.path.isdir(out.strip()):
            o["brew"] = {"path": out.strip(), "bytes": _tam_dir(out.strip())}
    raw = os.path.join(casa, "Library", "Containers", "com.docker.docker", "Data", "vms", "0", "data", "Docker.raw")
    try:
        st = os.stat(raw)
        o["docker"] = {"bytes": getattr(st, "st_blocks", 0) * 512 or st.st_size}
    except OSError:
        o["docker"] = None
    # Spotlight em discos externos
    vols = []
    for v in sorted(os.listdir("/Volumes")) if os.path.isdir("/Volumes") else []:
        p = os.path.join("/Volumes", v)
        if os.path.ismount(p) and os.path.realpath(p) != "/":
            rc, out, _ = _run(["mdutil", "-s", p], 10)
            vols.append({"vol": p, "ligado": "enabled" in out.lower()})
    o["spotlight"] = vols
    return ini, o


def coletar_linux(live=False):
    o = {"live": live}
    if live:
        return o
    nome, uid, _, casa = _usuario()
    o["zram_ativo"] = os.path.exists("/sys/block/zram0") and "zram" in _run(["swapon", "--show"], 10)[1]
    try:
        with open("/proc/sys/vm/swappiness") as fh:
            o["swappiness"] = int(fh.read().strip())
    except (OSError, ValueError):
        o["swappiness"] = None
    o["zramctl"] = bool(shutil.which("zramctl")) and bool(shutil.which("systemctl"))
    if shutil.which("gsettings"):
        rc, out, _ = _run_usuario(["gsettings", "get", "org.gnome.desktop.interface", "enable-animations"], 10, sessao=True)
        o["animacoes"] = out.strip() if rc == 0 else None
    o["tracker"] = None
    if shutil.which("systemctl"):
        rc, out, _ = _run_usuario(["systemctl", "--user", "is-enabled", "tracker-miner-fs-3.service"], 10, sessao=True)
        o["tracker"] = out.strip() or None
        o["fstrim"] = _run(["systemctl", "is-enabled", "fstrim.timer"], 10)[1].strip()
    o["apt_cache"] = sum(os.path.getsize(os.path.join("/var/cache/apt/archives", n)) for n in os.listdir("/var/cache/apt/archives") if n.endswith(".deb")) if os.path.isdir("/var/cache/apt/archives") else 0
    m = re.search(r"([\d.]+)([KMGT])", _run(["journalctl", "--disk-usage"], 15)[1]) if shutil.which("journalctl") else None
    o["journal"] = int(float(m.group(1)) * {"K": 1e3, "M": 1e6, "G": 1e9, "T": 1e12}[m.group(2)]) if m else 0
    o["flatpak"] = bool(shutil.which("flatpak"))
    if shutil.which("apt-get"):
        o["autoremove"] = len(re.findall(r"^Remv ", _run(["apt-get", "-s", "autoremove"], 60)[1], re.M))
    return o


# ==============================================================================================
# sugestões
# ==============================================================================================
def _ram_de(e, f):
    """MB de memória que o programa usa agora (processos com o mesmo executável)."""
    exe = (e.get("exe") or "").lower()
    if not exe:
        return 0
    tot = 0
    for p in (f.get("otim") or {}).get("procpath") or []:
        if os.path.basename(str(p.get("p", "")).replace("\\", "/")).lower() == exe:
            tot += int(p.get("ram") or 0)
    if tot:
        return round(tot / 1048576.0)
    base = re.sub(r"\.(exe|app)$", "", exe)
    for x in f.get("pesados") or []:
        if str(x.get("nome", "")).lower() in (exe, base):
            return int(x.get("ram_mb") or 0)
    return 0


def _deg_de(e, f):
    """Segundos que o programa atrasou o boot (medido pelo próprio Windows, evento 101), se houver."""
    deg = (f.get("otim") or {}).get("deg") or {}
    exe = (e.get("exe") or "").lower()
    for k, v in deg.items():
        if str(k).lower() == exe:
            return round(int(v) / 1000.0, 1)
    return 0


def _livre_pct(f):
    vs = [v for v in f.get("volumes") or [] if v.get("tam_gb")]
    v = max(vs, key=lambda x: x["tam_gb"]) if vs else None
    return (v["livre_gb"] * 100.0 / v["tam_gb"]) if v else None


def _sug(id_, categoria, titulo, detalhe, ganho, acao=None, onus=None, reversivel=True, recomendado=False, por_que="", efeito=None, botao=None, estado="", aplicavel=None, item=None):
    aplic = bool(acao) if aplicavel is None else aplicavel
    return {"id": id_, "categoria": categoria, "titulo": titulo, "detalhe": detalhe, "ganho": ganho, "acao": acao, "onus": onus, "reversivel": reversivel,
            "recomendado": recomendado, "por_que": por_que, "efeito": efeito or {}, "botao": botao, "estado": estado, "aplicavel": aplic,
            "marcado": bool(recomendado and aplic and not onus), "item": item}


def _ganho(texto, origem="qualitativo", nivel="baixo", valor=None, unidade=""):
    return {"texto": texto, "origem": origem, "nivel": nivel, "valor": valor, "unidade": unidade}


ONUS_INI = {
    "manter": "Pode desligar som, touchpad, antivírus ou outro recurso do computador. Só desative se souber o que é.",
    "opcional": "Deixa de sincronizar ou avisar sozinho até alguém abrir o programa (ex.: OneDrive, WhatsApp).",
    "revisar": "Não reconheci este programa: confira o que é antes de desativar.",
}


def sugestoes_inicio(f):
    fam = (f.get("so") or {}).get("familia")
    if (f.get("so") or {}).get("live"):
        return []
    F = _f()
    out = []
    todos = f.get("inicializacao_todos")
    if todos is None:  # ficha antiga (antes da 3.1): só os ativos, no formato antigo
        todos = []
        for e in f.get("inicializacao") or []:
            loc = e.get("local", "")
            run = fam == "windows" and bool(re.match(r"HK(LM|CU|U)", loc, re.I)) and bool(re.search(r"\\Run$", loc))
            todos.append(dict(e, ativo=True, exe=exe_de(e.get("comando")), fonte="run" if run else ("" if fam == "windows" else e.get("fonte", "")),
                              hive="HKLM:" if loc.upper().startswith("HKLM") else "HKCU:", kind="Run32" if "WOW6432NODE" in loc.upper() else "Run", valor=e.get("nome")))
    for e in todos:
        nivel = F.classificar_inicio(e)
        e["nivel"] = nivel
        ram = _ram_de(e, f)
        deg = _deg_de(e, f)
        fonte = e.get("fonte")
        if fam == "windows":
            pode = fonte in ("run", "pasta", "store")
            sem = "Item de serviço ou política: desative pelo próprio programa." if not pode else ""
        elif fam == "mac":
            pode, sem = fonte in ("login", "agente"), ""
        else:
            pode, sem = bool(e.get("arquivo")), ""
        acao = {"tipo": "inicio", "ligar": not e.get("ativo", True), "item": {k: e.get(k) for k in ("nome", "fonte", "hive", "kind", "valor", "pacote", "tarefa", "arquivo", "label", "local", "usuario", "comando")}} if pode else None
        partes = []
        if ram >= 5:
            partes.append("libera ~%d MB de memória" % ram)
        if deg:
            partes.append("−%.1f s no boot (medido pelo Windows)" % deg)
        if not partes:
            partes.append("um programa a menos ao ligar")
        efeito = {"inicio_remover": [e.get("nome")], "ram_livre_mb": ram, "boot_s": -deg}
        if e.get("ativo", True):
            out.append(_sug(e.get("id") or _id("ini", fam, e.get("nome"), e.get("local")), "Inicialização", "Não iniciar com o sistema: %s" % e.get("nome"),
                            ((e.get("comando") or "")[:140] + (("  · " + sem) if sem else "")),
                            _ganho(" · ".join(partes), "medido" if (ram >= 5 or deg) else "qualitativo", "médio" if (ram >= 200 or deg >= 2) else "baixo", ram, "MB"),
                            acao, ONUS_INI.get(nivel), True, nivel == "dispensavel", "Programa que não precisa abrir sozinho." if nivel == "dispensavel" else "",
                            efeito, estado="ativo", item=dict(e, ram_mb=ram, boot_s=deg)))
        else:
            out.append(_sug((e.get("id") or _id("ini", fam, e.get("nome"))) + ":ligar", "Inicialização", "Voltar a iniciar com o sistema: %s" % e.get("nome"),
                            (e.get("comando") or "")[:140], _ganho("está desativado", "qualitativo"), acao, None, True, False, "", {}, estado="desativado",
                            item=dict(e, ram_mb=ram, boot_s=deg)))
    return out


def sugestoes_windows(f, extra):
    o = f.get("otim") or {}
    ram = (f.get("ram") or {}).get("total_gb") or 0
    hd = ((_f().disco_principal(f) or {}).get("tipo") == "HDD")
    bateria = bool(f.get("bateria"))
    livre = _livre_pct(f)
    gpu_int = any(re.search(r"Intel|UHD|HD Graphics|Vega|Radeon\(TM\) Graphics", g.get("nome", ""), re.I) for g in f.get("gpu") or [])
    out = []
    # visual
    if o and (o.get("vfx") != 3 or o.get("transp") != 0 or o.get("anim") != 0):
        out.append(_sug("win.visual", "Visual", "Efeitos visuais: ajustar para melhor desempenho",
                        "Desliga transparência, animações, sombras e esmaecimentos (mantém as fontes suaves). Vale depois de sair e entrar na conta.",
                        _ganho("mais fluidez em máquina com vídeo integrado ou pouca memória", nivel="médio" if (ram <= 8.2 or gpu_int) else "baixo"),
                        {"tipo": "win_visual"}, "Visual mais simples: sem transparência e sem animações.", True, ram <= 8.2 or gpu_int,
                        "Pouca memória ou vídeo integrado." if (ram <= 8.2 or gpu_int) else ""))
    elif not o and (ram <= 8.2 or gpu_int):  # ficha antiga, sem a coleta nova: o ajuste de antes
        out.append(_sug("win.visual", "Visual", "Reduzir efeitos visuais (transparência e animações)", "Libera GPU/CPU em máquinas simples. Vale após sair e entrar de novo na conta.",
                        _ganho("mais fluidez em máquina simples", nivel="baixo"), {"tipo": "win_visual"}, "Visual mais simples: sem transparência e sem animações.", True, True))
    # temporários
    tmb = extra.get("tam_temp_mb")
    if tmb and tmb > 200:
        out.append(_sug("win.temp", "Espaço", "Limpar arquivos temporários (%s)" % _gb(tmb * 1048576), "Apaga só temporários com mais de 3 dias da pasta Temp do usuário. Não mexe em documentos.",
                        _ganho("libera até %s" % _gb(tmb * 1048576), "medido", "médio" if tmb > 2000 else "baixo", round(tmb / 1024.0, 1), "GB"),
                        {"tipo": "win_temp"}, "Sem volta: os temporários são apagados.", False, tmb > 800, efeito={"espaco_gb": tmb / 1024.0}))
    # plano de energia
    plano = str(o.get("plano") or "")
    if plano and ALTO_DESEMPENHO not in plano.lower():
        out.append(_sug("win.energia", "Energia", "Plano de energia: alto desempenho", "O processador não reduz a velocidade para economizar energia.",
                        _ganho("resposta mais rápida em processador fraco", nivel="médio"), {"tipo": "win_energia"},
                        "No notebook, a bateria dura menos e ele esquenta mais." if bateria else "Consome um pouco mais de energia.", True, not bateria,
                        "Computador de mesa (sem bateria)." if not bateria else ""))
    # hibernação
    if o.get("hiberfil") and o.get("hiber") != 0:
        b = int(o["hiberfil"])
        out.append(_sug("win.hiber", "Espaço", "Desligar a hibernação", "Apaga o hiberfil.sys (do tamanho de boa parte da memória).",
                        _ganho("libera %s" % _gb(b), "medido", "médio" if b > 4e9 else "baixo", round(b / 1e9, 1), "GB"), {"tipo": "win_hiber"},
                        "Sem hibernar e sem Inicialização Rápida: o boot a frio fica alguns segundos mais lento. Em troca, o backup pelo Zorin lê o disco sem problema.",
                        True, (livre is not None and livre < 15) or hd, "Pouco espaço livre ou disco HD." if ((livre is not None and livre < 15) or hd) else "",
                        efeito={"espaco_gb": b / 1e9}))
    # serviços
    for svc, tit, det, onus in (("SysMain", "Desligar o SysMain (pré-carregamento)", "Em HD com pouca memória, ele deixa o disco a 100% logo depois de ligar.", "Alguns programas podem abrir um pouco mais devagar."),
                                ("WSearch", "Desligar a indexação da pesquisa", "Em HD, a indexação disputa o disco com tudo o que você abre.", "A busca de arquivos (e do Outlook) fica mais lenta.")):
        sv = o.get(svc) or {}
        if sv and str(sv.get("start", "")).lower() != "disabled":
            rec = hd and (svc == "WSearch" or ram <= 4.2)
            out.append(_sug("win." + svc.lower(), "Sistema", tit, det, _ganho("menos disco ocupado em segundo plano", nivel="médio" if hd else "baixo"),
                            {"tipo": "win_servico", "servico": svc}, onus, True, rec, "Disco HD%s." % (" com até 4 GB de memória" if svc == "SysMain" else "") if rec else "",
                            efeito={"disco_mb_s": 1.1} if rec else {}))
    # registro: apps em segundo plano, dicas/anúncios, Game Bar, P2P, Sensor de Armazenamento
    if o and o.get("bgapps") != 1:
        out.append(_sug("win.bgapps", "Segundo plano", "Apps da Store em segundo plano", "Impede os apps da Microsoft Store de rodar escondidos.",
                        _ganho("menos memória e processador usados em segundo plano", nivel="baixo"), {"tipo": "win_reg", "chave": "bgapps"},
                        "Apps da Store param de atualizar e avisar em segundo plano.", True, ram <= 8.2, "Até 8 GB de memória." if ram <= 8.2 else ""))
    if o and any(v != 0 for v in (o.get("cdm") or {}).values()):
        out.append(_sug("win.dicas", "Segundo plano", "Dicas, sugestões e anúncios do Windows", "Desliga as sugestões do menu Iniciar e a instalação automática de apps patrocinados.",
                        _ganho("menos apps instalados sozinhos e menos avisos", nivel="baixo"), {"tipo": "win_reg", "chave": "dicas"}, None, True, True, "Sem efeito colateral."))
    if o and (o.get("gamedvr") != 0 or o.get("appcap") != 0):
        out.append(_sug("win.gamedvr", "Segundo plano", "Gravação de jogos (Xbox Game Bar)", "Desliga a captura em segundo plano do Game Bar.",
                        _ganho("menos processador e vídeo usados durante jogos", nivel="baixo"), {"tipo": "win_reg", "chave": "gamedvr"},
                        "Deixa de gravar jogos pelo Game Bar.", True, gpu_int, "Vídeo integrado." if gpu_int else ""))
    if o and o.get("domode") != 0:
        out.append(_sug("win.p2p", "Segundo plano", "Otimização de Entrega (atualizações em P2P)", "O Windows para de enviar atualizações para outros computadores.",
                        _ganho("menos internet e disco usados em segundo plano", nivel="baixo"), {"tipo": "win_reg", "chave": "p2p"}, None, True, False))
    if o and o.get("storsense") != 1:
        out.append(_sug("win.sensor", "Espaço", "Ligar o Sensor de Armazenamento", "O Windows passa a limpar temporários sozinho quando o espaço aperta.",
                        _ganho("evita que o disco encha de novo", nivel="baixo"), {"tipo": "win_reg", "chave": "sensor"},
                        "Itens com mais de 30 dias na Lixeira passam a ser apagados sozinhos.", True, livre is not None and livre < 25))
    # tarefas de atualizadores
    tar = o.get("tarefas") or []
    if tar:
        out.append(_sug("win.tarefas", "Segundo plano", "Atualizadores automáticos (%d tarefa%s agendada%s)" % (len(tar), "s" if len(tar) > 1 else "", "s" if len(tar) > 1 else ""),
                        ", ".join(t.get("nome", "?") for t in tar[:6]), _ganho("menos programas acordando sozinhos", nivel="baixo"),
                        {"tipo": "win_tarefas", "tarefas": tar}, "Esses programas deixam de se atualizar sozinhos: atualize de vez em quando.", True, False))
    # disco e limpeza do sistema
    out.append(_sug("win.disco", "Disco", "Desfragmentar o HD" if hd else "Otimizar o SSD (TRIM)", "Roda a otimização do próprio Windows em segundo plano.",
                    _ganho("leitura mais rápida em HD fragmentado" if hd else "mantém o SSD rápido", nivel="médio" if hd else "baixo"), {"tipo": "win_otimizar_disco"},
                    "Pode demorar (no HD, horas) e deixa o disco ocupado enquanto roda." if hd else None, None, hd, "Disco HD." if hd else ""))
    if livre is not None and livre < 25:
        out.append(_sug("win.dism", "Espaço", "Limpar componentes antigos do Windows Update", "Remove versões antigas de componentes que o Windows guarda depois de atualizar.",
                        _ganho("o Windows mostra quanto liberou ao terminar (em geral alguns GB)", nivel="médio"), {"tipo": "win_dism"},
                        "Demora e não dá mais para desinstalar atualizações antigas.", False, livre < 15))
    if o.get("winold"):
        b = int(o["winold"])
        out.append(_sug("win.winold", "Espaço", "Remover a instalação anterior do Windows (Windows.old)", "Sobra da última atualização grande do Windows.",
                        _ganho("libera %s" % _gb(b), "medido", "alto" if b > 10e9 else "médio", round(b / 1e9, 1), "GB"), {"tipo": "win_winold"},
                        "Não dá mais para voltar à versão anterior do Windows.", False, livre is not None and livre < 20, efeito={"espaco_gb": b / 1e9}))
    od = o.get("onedrive") or {}
    if od.get("bytes", 0) >= 5e8:
        b = int(od["bytes"])
        out.append(_sug("win.onedrive", "Espaço", "OneDrive: deixar só na nuvem o que está parado", "%d arquivo(s) sem uso há 90 dias saem do disco e continuam no OneDrive." % od.get("arquivos", 0),
                        _ganho("libera %s" % _gb(b), "medido", "alto" if b > 10e9 else "médio", round(b / 1e9, 1), "GB"), {"tipo": "win_onedrive", "pasta": od.get("pasta")},
                        "Abrir esses arquivos depois precisa de internet (eles baixam de novo).", False, livre is not None and livre < 20, efeito={"espaco_gb": b / 1e9}))
    return out


def sugestoes_mac(f, extra):
    o = f.get("otim") or {}
    ram = (f.get("ram") or {}).get("total_gb") or 0
    out = []
    mv = o.get("movimento") or {}
    if mv and (mv.get("reduceMotion") not in ("1",) or mv.get("reduceTransparency") not in ("1",)):
        out.append(_sug("mac.movimento", "Visual", "Reduzir movimento e transparência", "Menos animações e menos efeito de vidro nas janelas e no Dock.",
                        _ganho("mais fluidez em Mac com pouca memória ou vídeo Intel", nivel="médio" if ram <= 8.2 else "baixo"), {"tipo": "mac_movimento"},
                        "Visual mais simples. Pode pedir permissão de Acessibilidade.", True, ram <= 8.2, "Até 8 GB de memória." if ram <= 8.2 else ""))
    purg = o.get("purgavel") or 0
    if o.get("snapshots"):
        out.append(_sug("mac.snapshots", "Espaço", "Apagar instantâneos locais do Time Machine (%d)" % o["snapshots"], "Cópias locais que o Time Machine guarda no próprio disco.",
                        _ganho("libera até %s (espaço purgável)" % _gb(purg), "medido", "médio", round(purg / 1e9, 1), "GB"), {"tipo": "mac_snapshots"},
                        "Perde os pontos de restauração locais (o backup no disco externo continua).", False, purg > 5e9, efeito={"espaco_gb": purg / 1e9}))
    elif purg >= 1e9:
        out.append(_sug("mac.purgavel", "Espaço", "Espaço purgável: %s" % _gb(purg), "O macOS libera sozinho (caches do iCloud e do sistema) quando um programa precisa de espaço.",
                        _ganho("%s que o macOS libera sozinho" % _gb(purg), "medido"), None, None, True, False, aplicavel=False))
    ip = o.get("iphone")
    if ip == "sem_acesso":
        out.append(_sug("mac.iphone", "Espaço", "Backups de iPhone/iPad", "Sem permissão para ler: dê Acesso Total ao Disco ao Terminal e analise de novo.",
                        _ganho("não medido"), None, None, True, False, aplicavel=False))
    elif ip:
        tot = sum(b.get("bytes", 0) for b in ip)
        out.append(_sug("mac.iphone", "Espaço", "Backups de iPhone/iPad (%d)" % len(ip), "; ".join("%s (%s, %s)" % (b["nome"], b.get("data") or "?", _gb(b.get("bytes", 0))) for b in ip),
                        _ganho("até %s" % _gb(tot), "medido", "alto" if tot > 20e9 else "médio", round(tot / 1e9, 1), "GB"), None,
                        "Pode ser o único backup do aparelho: prefira mover para um HD externo.", True, tot > 5e9, efeito={"espaco_gb": tot / 1e9},
                        botao={"texto": "Mover em Dados", "nav": "dados"}, aplicavel=False))
    if (o.get("icloud") or 0) >= 1e9:
        b = o["icloud"]
        out.append(_sug("mac.icloud", "Espaço", "iCloud Drive baixado neste Mac: %s" % _gb(b),
                        "No Finder, clique com o botão direito numa pasta do iCloud Drive e escolha Remover Download; ou ative Otimizar Armazenamento do Mac nos Ajustes.",
                        _ganho("até %s" % _gb(b), "medido", "médio", round(b / 1e9, 1), "GB"), None, "Abrir esses arquivos depois precisa de internet.", True, False,
                        botao={"texto": "Abrir Ajustes > Armazenamento", "abrir": "ajustes_armazenamento"}, aplicavel=False))
    out.append(_sug("mac.armazenamento", "Espaço", "Recomendações do macOS (Mensagens, Fotos, Mail)", "Anexos antigos do Mensagens, Fotos em alta resolução e anexos do Mail: o próprio macOS sugere o que remover.",
                    _ganho("o macOS mostra quanto cada um ocupa"), None, None, True, False, botao={"texto": "Abrir Ajustes > Armazenamento", "abrir": "ajustes_armazenamento"}, aplicavel=False))
    x = o.get("xcode")
    if x and x.get("bytes", 0) >= 5e8:
        out.append(_sug("mac.xcode", "Espaço", "Xcode: dados derivados (%s)" % _gb(x["bytes"]), "Compilações intermediárias que o Xcode refaz quando precisa. Vão para a Lixeira.",
                        _ganho("libera %s" % _gb(x["bytes"]), "medido", "médio", round(x["bytes"] / 1e9, 1), "GB"), {"tipo": "mac_lixeira", "path": x["path"]},
                        "O Xcode recompila os projetos na próxima vez.", True, False, efeito={"espaco_gb": x["bytes"] / 1e9}))
    b = o.get("brew")
    if b and b.get("bytes", 0) >= 2e8:
        out.append(_sug("mac.brew", "Espaço", "Homebrew: instaladores antigos (%s)" % _gb(b["bytes"]), "brew cleanup remove downloads e versões antigas que o Homebrew guarda.",
                        _ganho("libera até %s" % _gb(b["bytes"]), "medido", "baixo", round(b["bytes"] / 1e9, 1), "GB"), {"tipo": "mac_cmd", "cmd": "brew"},
                        None, False, True, "Sem efeito colateral.", efeito={"espaco_gb": b["bytes"] / 1e9}))
    d = o.get("docker")
    if d and d.get("bytes", 0) >= 2e9:
        out.append(_sug("mac.docker", "Espaço", "Docker: limpar o que não está em uso (ocupa %s)" % _gb(d["bytes"]), "docker system prune: containers parados, redes sem uso e cache de build.",
                        _ganho("o Docker mostra quanto liberou ao terminar"), {"tipo": "mac_cmd", "cmd": "docker"},
                        "Apaga containers parados e o cache de build do Docker.", False, False))
    for v in o.get("spotlight") or []:
        if v.get("ligado"):
            out.append(_sug(_id("mac.spotlight", v["vol"]), "Disco", "Spotlight no disco externo %s" % os.path.basename(v["vol"]), "Para de indexar este disco.",
                            _ganho("menos disco ocupado quando ele está conectado"), {"tipo": "mac_spotlight", "vol": v["vol"]},
                            "A busca do Spotlight deixa de achar arquivos desse disco.", True, False))
    return out


def sugestoes_linux(f, extra):
    o = f.get("otim") or {}
    if (f.get("so") or {}).get("live") or o.get("live"):
        return [_sug("lin.live", "Sistema", "Otimizações do Zorin/Linux", "No modo Live nada fica gravado: rode com o sistema instalado.", _ganho("—"), None, None, True, False, aplicavel=False)]
    ram = (f.get("ram") or {}).get("total_gb") or 0
    hd = ((_f().disco_principal(f) or {}).get("tipo") == "HDD")
    out = []
    if o.get("zramctl") and not o.get("zram_ativo"):
        out.append(_sug("lin.zram", "Memória", "Memória comprimida (zram)", "Cria uma área de troca dentro da própria memória, comprimida. Evita usar o disco quando a memória enche.",
                        _ganho("≈ +25 a 50% de memória efetiva (estimado; depende do que está aberto)", "estimado", "alto" if ram <= 4.2 else "médio", round(ram * 0.35, 1), "GB"),
                        {"tipo": "lin_zram"}, "Usa um pouco do processador para comprimir a memória.", True, ram <= 4.2 or hd, "Até 4 GB de memória ou disco HD." if (ram <= 4.2 or hd) else "",
                        efeito={"ram_livre_mb": ram * 0.3 * 1024}))
    if o.get("animacoes") == "true":
        out.append(_sug("lin.animacoes", "Visual", "Desligar animações do GNOME", "Janelas abrem e fecham sem animação.", _ganho("mais fluidez em vídeo fraco", nivel="médio" if ram <= 4.2 else "baixo"),
                        {"tipo": "lin_animacoes"}, "Visual mais simples.", True, ram <= 4.2))
    if o.get("tracker") in ("enabled", "static", "indirect", "alias"):
        out.append(_sug("lin.tracker", "Disco", "Desligar o indexador de arquivos (Tracker)", "Em HD, o indexador disputa o disco com tudo o que você abre.",
                        _ganho("menos disco ocupado em segundo plano", nivel="médio" if hd else "baixo"), {"tipo": "lin_tracker"}, "A busca de arquivos no menu fica mais lenta.", True, hd))
    if not hd and o.get("fstrim") not in ("enabled", None, ""):
        out.append(_sug("lin.fstrim", "Disco", "TRIM semanal no SSD", "Liga a manutenção semanal que mantém o SSD rápido.", _ganho("mantém o SSD rápido"), {"tipo": "lin_fstrim"}, None, True, True, "Sem efeito colateral."))
    if (o.get("apt_cache") or 0) >= 1e8:
        b = o["apt_cache"]
        out.append(_sug("lin.apt", "Espaço", "Instaladores baixados pelo apt (%s)" % _gb(b), "Pacotes .deb que já foram instalados.", _ganho("libera %s" % _gb(b), "medido", "baixo", round(b / 1e9, 1), "GB"),
                        {"tipo": "lin_cmd", "cmd": "apt_clean"}, None, False, True, "Sem efeito colateral.", efeito={"espaco_gb": b / 1e9}))
    if (o.get("journal") or 0) >= 3e8:
        b = o["journal"]
        out.append(_sug("lin.journal", "Espaço", "Registros do sistema (%s)" % _gb(b), "Mantém só os 200 MB mais recentes.", _ganho("libera até %s" % _gb(max(0, b - 2e8)), "medido", "baixo"),
                        {"tipo": "lin_cmd", "cmd": "journal"}, "Apaga registros antigos do sistema (só úteis para diagnóstico).", False, False, efeito={"espaco_gb": max(0, b - 2e8) / 1e9}))
    if o.get("flatpak"):
        out.append(_sug("lin.flatpak", "Espaço", "Flatpak: bibliotecas sem uso", "Remove bibliotecas (runtimes) que nenhum app instalado usa mais.", _ganho("o sistema mostra quanto liberou ao terminar"),
                        {"tipo": "lin_cmd", "cmd": "flatpak"}, None, False, False))
    if o.get("autoremove"):
        out.append(_sug("lin.autoremove", "Espaço", "Pacotes sem uso (%d)" % o["autoremove"], "Pacotes instalados como dependência que nada mais usa.", _ganho("o sistema mostra quanto liberou ao terminar"),
                        {"tipo": "lin_cmd", "cmd": "autoremove"}, "Remove pacotes que o sistema acha que não são mais usados: confira a lista antes.", False, False))
    return out


def sugestoes(f, extra=None):
    """Todas as sugestões para a ficha f (Inicialização + o catálogo do sistema dela)."""
    extra = extra or {}
    fam = (f.get("so") or {}).get("familia")
    out = sugestoes_inicio(f)
    if fam == "windows":
        out += sugestoes_windows(f, extra)
    elif fam == "mac":
        out += sugestoes_mac(f, extra)
    elif fam == "linux":
        out += sugestoes_linux(f, extra)
    esp = extra.get("limpavel_bytes")
    lv = _livre_pct(f)
    if not (f.get("so") or {}).get("live") and (esp or (lv is not None and lv < 25)):
        out.append(_sug("dados", "Espaço", "Liberar espaço: caches, downloads e arquivos parados",
                        "A aba Dados mostra o que dá para limpar sem risco e o que está parado, com ver/abrir antes de decidir.",
                        _ganho("%s limpáveis sem risco agora" % _gb(esp), "medido", "médio", round(esp / 1e9, 1), "GB") if esp else _ganho("%.0f%% livre no disco" % lv, "medido", "médio" if lv < 15 else "baixo"),
                        None, None, True, bool(esp and esp > 1e9) or (lv is not None and lv < 15), "Pouco espaço livre." if (lv is not None and lv < 15) else "",
                        efeito={"espaco_gb": esp / 1e9} if esp else {}, botao={"texto": "Abrir Dados", "nav": "dados"}, aplicavel=False))
    return out


def simular(f, efeitos):
    """Nota estimada se os efeitos forem aplicados (mesmo cálculo da nota real)."""
    return _f().pontuar(com_efeitos(f, efeitos))["geral"]


def com_efeitos(f, efeitos):
    """Cópia da ficha como ficaria com os efeitos aplicados (menos programas ao ligar, memória livre, espaço...)."""
    import copy
    g = copy.deepcopy(f)
    m = g.setdefault("medidas", {})
    tira = set()
    ram_mb = boot = esp = 0.0
    fator_disco = 1.0
    for e in efeitos:
        tira.update(e.get("inicio_remover") or [])
        ram_mb += e.get("ram_livre_mb") or 0
        boot += e.get("boot_s") or 0
        esp += e.get("espaco_gb") or 0
        fator_disco = max(fator_disco, e.get("disco_mb_s") or 1.0)
    if tira:
        g["inicializacao"] = [x for x in g.get("inicializacao") or [] if x.get("nome") not in tira]
    r = g.get("ram") or {}
    if ram_mb and r.get("livre_gb") is not None:
        r["livre_gb"] = min(r.get("total_gb") or 0, r["livre_gb"] + ram_mb / 1024.0)
    if m.get("boot_s") and boot:
        m["boot_s"] = max(5.0, m["boot_s"] + boot)
    if fator_disco > 1 and m.get("disco_mb_s"):
        m["disco_mb_s"] = m["disco_mb_s"] * fator_disco
    if esp:
        vs = [v for v in g.get("volumes") or [] if v.get("tam_gb")]
        if vs:
            v = max(vs, key=lambda x: x["tam_gb"])
            v["livre_gb"] = min(v["tam_gb"], v["livre_gb"] + esp)
    return g


def com_pontos(f, sug):
    """Acrescenta '+N pontos' (simulado) ao ganho de cada sugestão e devolve o resumo da Central."""
    base = _f().pontuar(f)["geral"]
    for s in sug:
        if s["efeito"] and s.get("estado") != "desativado":
            d = simular(f, [s["efeito"]]) - base
            s["pontos"] = d
            if d > 0:
                s["ganho"]["texto"] += " · +%d ponto%s na nota" % (d, "s" if d > 1 else "")
        else:
            s["pontos"] = 0
    rec = [s for s in sug if s["recomendado"] and s.get("estado") != "desativado"]
    total = simular(f, [s["efeito"] for s in rec if s["efeito"]]) - base if rec else 0
    return {"n": len(rec), "pontos": max(0, total), "base": base, "aplicaveis": sum(1 for s in sug if s["aplicavel"] and s.get("estado") != "desativado")}


# ==============================================================================================
# aplicar e desfazer
# ==============================================================================================
def _ps(script, env=None, timeout=90):
    return _f().ps(script, timeout, _f()._ps_env(**(env or {})))


def _ps_json(script, env=None, timeout=90):
    out = _ps(script, env, timeout)
    i = out.find("{")
    try:
        return json.loads(out[i:]) if i >= 0 else None
    except ValueError:
        return None


def _ps_fundo(script):
    """PowerShell em segundo plano, sem esperar (tarefas longas: desfragmentar, DISM, OneDrive)."""
    enc = base64.b64encode(("$ErrorActionPreference='SilentlyContinue'; " + script).encode("utf-16-le")).decode("ascii")
    subprocess.Popen(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden", "-EncodedCommand", enc],
                     creationflags=0x00000008 | 0x08000000, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


PS_REG = r"""
$itens = $env:BKP_REG | ConvertFrom-Json
$prev = @()
foreach($i in $itens){
  $old = $null; $existe = $false
  try{ $old = (Get-ItemProperty -Path $i.k -Name $i.n -ErrorAction Stop).($i.n); $existe = $true }catch{}
  if($old -is [byte[]]){ $old = @($old | ForEach-Object { [int]$_ }) }
  $prev += @{k=$i.k; n=$i.n; t=$i.t; v=$old; existe=$existe}
  if($i.v -eq $null){ Remove-ItemProperty -Path $i.k -Name $i.n -ErrorAction SilentlyContinue }
  else{
    if(-not (Test-Path $i.k)){ New-Item -Path $i.k -Force | Out-Null }
    $val = $i.v; if($i.t -eq 'Binary'){ $val = [byte[]]@($i.v) }
    Set-ItemProperty -Path $i.k -Name $i.n -Value $val -Type $i.t
  }
}
@{ok=$true; prev=@($prev)} | ConvertTo-Json -Compress -Depth 5
"""
_ADV = r"HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced"
REG = {  # (chave, valor, novo, tipo)
    "visual": [(r"HKCU:\Software\Microsoft\Windows\CurrentVersion\Themes\Personalize", "EnableTransparency", 0, "DWord"), (_ADV, "TaskbarAnimations", 0, "DWord"),
               (r"HKCU:\Control Panel\Desktop\WindowMetrics", "MinAnimate", "0", "String"), (_ADV, "ListviewShadow", 0, "DWord"),
               (r"HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\VisualEffects", "VisualFXSetting", 3, "DWord"),
               (r"HKCU:\Control Panel\Desktop", "UserPreferencesMask", [0x90, 0x12, 0x03, 0x80, 0x10, 0x00, 0x00, 0x00], "Binary"),
               (r"HKCU:\Control Panel\Desktop", "FontSmoothing", "2", "String")],
    "bgapps": [(r"HKCU:\Software\Microsoft\Windows\CurrentVersion\BackgroundAccessApplications", "GlobalUserDisabled", 1, "DWord"),
               (r"HKLM:\SOFTWARE\Policies\Microsoft\Windows\AppPrivacy", "LetAppsRunInBackground", 2, "DWord")],
    "dicas": [(r"HKCU:\Software\Microsoft\Windows\CurrentVersion\ContentDeliveryManager", n, 0, "DWord") for n in
              ("SubscribedContent-338388Enabled", "SubscribedContent-338389Enabled", "SubscribedContent-353694Enabled", "SubscribedContent-353696Enabled",
               "SystemPaneSuggestionsEnabled", "SilentInstalledAppsEnabled", "SoftLandingEnabled")],
    "gamedvr": [(r"HKCU:\System\GameConfigStore", "GameDVR_Enabled", 0, "DWord"), (r"HKCU:\Software\Microsoft\Windows\CurrentVersion\GameDVR", "AppCaptureEnabled", 0, "DWord")],
    "p2p": [(r"HKLM:\SOFTWARE\Policies\Microsoft\Windows\DeliveryOptimization", "DODownloadMode", 0, "DWord")],
    "sensor": [(r"HKCU:\Software\Microsoft\Windows\CurrentVersion\StorageSense\Parameters\StoragePolicy", "01", 1, "DWord")],
}


def _reg_aplicar(itens):
    j = _ps_json(PS_REG, {"reg": json.dumps([{"k": k, "n": n, "v": v, "t": t} for k, n, v, t in itens])})
    if not j or not j.get("ok"):
        return False, "O Windows não respondeu.", None
    prev = j.get("prev") or []
    return True, "Feito (reversível).", {"tipo": "win_reg", "prev": prev if isinstance(prev, list) else [prev]}


def _reg_desfazer(u):
    itens = [{"k": p["k"], "n": p["n"], "v": p.get("v") if p.get("existe") else None, "t": p.get("t") or "DWord"} for p in u.get("prev") or []]
    j = _ps_json(PS_REG, {"reg": json.dumps(itens)})
    return bool(j and j.get("ok"))


PS_INI_SET = r"""
$p = $env:BKP_HIVE + '\Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\' + $env:BKP_KIND
if(-not (Test-Path $p)){ New-Item -Path $p -Force | Out-Null }
$prev = $null; try{ $prev = (Get-ItemProperty -Path $p -Name $env:BKP_NOME -ErrorAction Stop).($env:BKP_NOME) }catch{}
if($prev -is [byte[]]){ $prev = @($prev | ForEach-Object { [int]$_ }) }
$v = [byte[]](0,0,0,0,0,0,0,0,0,0,0,0); $v[0] = [byte][int]$env:BKP_FLAG
if($env:BKP_FLAG -eq '3'){ [Array]::Copy([BitConverter]::GetBytes((Get-Date).ToFileTime()), 0, $v, 4, 8) }
Set-ItemProperty -Path $p -Name $env:BKP_NOME -Value $v -Type Binary
$ok = ((Get-ItemProperty -Path $p -Name $env:BKP_NOME).($env:BKP_NOME)[0] -eq [byte][int]$env:BKP_FLAG)
@{ok=$ok; prev=$prev} | ConvertTo-Json -Compress
"""
PS_STORE_SET = r"""
$p = 'HKCU:\Software\Classes\Local Settings\Software\Microsoft\Windows\CurrentVersion\AppModel\SystemAppData\' + $env:BKP_PACOTE + '\' + $env:BKP_TAREFA
$prev = (Get-ItemProperty -Path $p -Name State -ErrorAction Stop).State
Set-ItemProperty -Path $p -Name State -Value ([int]$env:BKP_ESTADO) -Type DWord
@{ok=((Get-ItemProperty -Path $p -Name State).State -eq [int]$env:BKP_ESTADO); prev=$prev} | ConvertTo-Json -Compress
"""


def _inicio(acao):
    """Liga ou desliga um item de inicialização pelo mesmo método do Gerenciador de Tarefas / Ajustes."""
    it = acao.get("item") or {}
    ligar = bool(acao.get("ligar"))
    fonte = it.get("fonte")
    if IS_WIN and fonte in ("run", "pasta"):
        j = _ps_json(PS_INI_SET, {"hive": it.get("hive"), "kind": it.get("kind"), "nome": it.get("valor"), "flag": 2 if ligar else 3})
        if not j or not j.get("ok"):
            return False, "Não consegui gravar a configuração.", None
        return True, "Feito (reversível).", {"tipo": "startup_win", "hive": it.get("hive"), "kind": it.get("kind"), "nome": it.get("valor"), "prev": j.get("prev")}
    if IS_WIN and fonte == "store":
        j = _ps_json(PS_STORE_SET, {"pacote": it.get("pacote"), "tarefa": it.get("tarefa"), "estado": 2 if ligar else 1})
        if not j or not j.get("ok"):
            return False, "Não consegui mudar o app da Store.", None
        return True, "Feito (reversível).", {"tipo": "store_win", "pacote": it.get("pacote"), "tarefa": it.get("tarefa"), "prev": j.get("prev")}
    if IS_MAC and fonte == "agente":
        _, uid, _, _ = _usuario()
        dom = "gui/%d" % uid
        if ligar:
            _run(["launchctl", "enable", "%s/%s" % (dom, it.get("label"))])
            _run(["launchctl", "bootstrap", dom, it.get("arquivo")])
        else:
            _run(["launchctl", "bootout", dom, it.get("arquivo")])
            rc, _, err = _run(["launchctl", "disable", "%s/%s" % (dom, it.get("label"))])
            if rc != 0:
                return False, "O macOS recusou: %s" % err.strip()[:120], None
        return True, "Feito (reversível).", {"tipo": "agente_mac", "label": it.get("label"), "arquivo": it.get("arquivo"), "ligou": ligar}
    if IS_MAC and fonte == "login":
        if ligar:
            return False, "Para recolocar, use Desfazer ou Ajustes > Geral > Itens de Início.", None
        nome = (it.get("nome") or "").replace("\\", "\\\\").replace('"', '\\"')
        rc, _, err = _run_usuario(["osascript", "-e", 'tell application "System Events" to delete login item "%s"' % nome], 20)
        if rc != 0:
            return False, "O macOS recusou (permita o controle do System Events): %s" % err.strip()[:120], None
        return True, "Feito (reversível).", {"tipo": "login_mac", "nome": it.get("nome"), "path": it.get("arquivo")}
    if not IS_WIN and not IS_MAC and it.get("arquivo"):
        if ligar:
            return _linux_religar(it)
        return _f()._startup_linux(it)
    return False, "Não suportado neste sistema.", None


def _linux_religar(it):
    p = os.path.join(_f().user_home(), ".config", "autostart", it.get("arquivo"))
    try:
        with open(p, encoding="utf-8", errors="replace") as fh:
            prev = fh.read()
    except OSError:
        return False, "Não achei o atalho de inicialização.", None
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(re.sub(r"(?m)^Hidden\s*=\s*true\s*\n?", "", prev))
    return True, "Feito (reversível).", {"tipo": "startup_linux", "path": p, "prev": prev}


def _win_servico(acao):
    j = _ps_json(r"""$s = Get-Service $env:BKP_SVC -ErrorAction Stop
$prev = @{start=[string]$s.StartType; status=[string]$s.Status}
Set-Service $env:BKP_SVC -StartupType Disabled; Stop-Service $env:BKP_SVC -Force -ErrorAction SilentlyContinue
@{ok=((Get-Service $env:BKP_SVC).StartType -eq 'Disabled'); prev=$prev} | ConvertTo-Json -Compress""", {"svc": acao["servico"]})
    if not j or not j.get("ok"):
        return False, "O Windows não deixou mudar o serviço.", None
    return True, "Desligado (reversível).", {"tipo": "win_servico", "servico": acao["servico"], "prev": j.get("prev")}


def _win_servico_desfazer(u):
    pv = u.get("prev") or {}
    j = _ps_json(r"""Set-Service $env:BKP_SVC -StartupType $env:BKP_START
if($env:BKP_STATUS -eq 'Running'){ Start-Service $env:BKP_SVC -ErrorAction SilentlyContinue }
@{ok=([string](Get-Service $env:BKP_SVC).StartType -eq $env:BKP_START)} | ConvertTo-Json -Compress""",
                 {"svc": u["servico"], "start": pv.get("start") or "Automatic", "status": pv.get("status") or "Running"})
    return bool(j and j.get("ok"))


def _win_energia(acao):
    j = _ps_json(r"""$re = '[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}'
$prev = [regex]::Match(((powercfg /getactivescheme) -join ' '), $re).Value
$hp = '8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c'
if(-not ((powercfg /list) -join ' ').ToLower().Contains($hp)){ $m = [regex]::Match(((powercfg -duplicatescheme $hp) -join ' '), $re); if($m.Success){ $hp = $m.Value } }
powercfg /setactive $hp | Out-Null
@{ok=((powercfg /getactivescheme) -join ' ').ToLower().Contains($hp.ToLower()); prev=$prev} | ConvertTo-Json -Compress""")
    if not j or not j.get("ok"):
        return False, "O Windows não aceitou o plano de alto desempenho.", None
    return True, "Plano trocado (reversível).", {"tipo": "win_energia", "prev": j.get("prev")}


def _win_cmd_ok(script, env=None):
    j = _ps_json(script, env)
    return bool(j and j.get("ok"))


def _livre():
    try:
        return shutil.disk_usage(os.environ.get("SystemDrive", "C:") + "\\" if IS_WIN else "/").free
    except OSError:
        return 0


def _mede(fn):
    """Roda uma limpeza e diz quanto espaço voltou de verdade."""
    antes = _livre()
    ok, msg, u = fn()
    if ok:
        d = _livre() - antes
        if d > 5e7:
            msg = "Liberou %s. %s" % (_gb(d), msg)
    return ok, msg, u


def aplicar(acao):
    """(ok, mensagem, registro para desfazer ou None)."""
    t = acao.get("tipo")
    F = _f()
    if t == "inicio":
        return _inicio(acao)
    if t == "win_visual":
        return _reg_aplicar(REG["visual"])
    if t == "win_reg":
        return _reg_aplicar(REG[acao["chave"]])
    if t == "win_temp":
        return _mede(F._temp_win)
    if t == "win_energia":
        return _win_energia(acao)
    if t == "win_hiber":
        return _mede(lambda: (True, "Hibernação desligada (reversível).", {"tipo": "win_hiber"}) if _win_cmd_ok(
            "powercfg /h off | Out-Null; @{ok=((Get-ItemProperty 'HKLM:\\SYSTEM\\CurrentControlSet\\Control\\Power').HibernateEnabled -eq 0)} | ConvertTo-Json -Compress")
            else (False, "O Windows não desligou a hibernação.", None))
    if t == "win_servico":
        return _win_servico(acao)
    if t == "win_tarefas":
        feitas = []
        for tr in acao.get("tarefas") or []:
            if _win_cmd_ok("Disable-ScheduledTask -TaskName $env:BKP_NOME -TaskPath $env:BKP_PASTA | Out-Null; @{ok=$true} | ConvertTo-Json -Compress", {"nome": tr.get("nome"), "pasta": tr.get("pasta")}):
                feitas.append(tr)
        if not feitas:
            return False, "O Windows não deixou desativar as tarefas.", None
        return True, "%d tarefa(s) desativada(s) (reversível)." % len(feitas), {"tipo": "win_tarefas", "tarefas": feitas}
    if t == "win_otimizar_disco":
        _ps_fundo("defrag.exe $env:SystemDrive /O")
        return True, "Otimização do disco iniciada em segundo plano (pode demorar).", None
    if t == "win_dism":
        _ps_fundo("Dism.exe /Online /Cleanup-Image /StartComponentCleanup")
        return True, "Limpeza iniciada em segundo plano. O espaço aparece na próxima análise.", None
    if t == "win_winold":
        _ps_fundo("cleanmgr.exe /autoclean")
        return True, "Remoção iniciada em segundo plano (Limpeza de Disco do Windows).", None
    if t == "win_onedrive":
        _ps_fundo("$lim=(Get-Date).AddDays(-90); Get-ChildItem '%s' -Recurse -File -Force | Where-Object { -not ($_.Attributes -band 0x400000) -and -not ($_.Attributes -band 0x1000) "
                  "-and -not ($_.Attributes -band 0x80000) -and $_.LastAccessTime -lt $lim } | ForEach-Object { attrib.exe +U -P $_.FullName }" % str(acao.get("pasta", "")).replace("'", "''"))
        return True, "O OneDrive está liberando os arquivos em segundo plano.", None
    if t == "mac_movimento":
        prev = {}
        for k in ("reduceMotion", "reduceTransparency"):
            rc, out, _ = _run_usuario(["defaults", "read", "com.apple.universalaccess", k], 10)
            prev[k] = out.strip() if rc == 0 else None
            rc, _, err = _run_usuario(["defaults", "write", "com.apple.universalaccess", k, "-bool", "true"], 10)
            if rc != 0:
                return False, "O macOS recusou (dê permissão de Acessibilidade ao Terminal): %s" % err.strip()[:100], None
        return True, "Feito (reversível).", {"tipo": "mac_movimento", "prev": prev}
    if t == "mac_snapshots":
        return _mede(lambda: (True, "Instantâneos locais apagados.", None) if _run(["tmutil", "deletelocalsnapshots", "/"], 300)[0] == 0
                     else (False, "O macOS recusou (precisa de administrador).", None))
    if t == "mac_lixeira":
        import dados
        try:
            dados._lixeira_mac(acao["path"])
        except OSError as e:
            return False, str(e), None
        return True, "Foi para a Lixeira (o espaço volta ao esvaziar).", None
    if t == "mac_cmd":
        cmd = {"brew": [shutil.which("brew") or "/opt/homebrew/bin/brew", "cleanup", "-s"], "docker": [shutil.which("docker") or "docker", "system", "prune", "-f"]}[acao["cmd"]]
        rc, out, err = _run_usuario(cmd, 900)
        m = re.search(r"(?:Total reclaimed space|freed approximately):?\s*([\d.,]+\s*[kKMGT]?B)", out)
        return (rc == 0), ("Liberou %s." % m.group(1) if m else ("Feito." if rc == 0 else "Falhou: %s" % err.strip()[:120])), None
    if t == "mac_spotlight":
        rc, _, err = _run(["mdutil", "-i", "off", acao["vol"]], 60)
        return (rc == 0), ("Indexação desligada (reversível)." if rc == 0 else "Falhou: %s" % err.strip()[:120]), ({"tipo": "mac_spotlight", "vol": acao["vol"]} if rc == 0 else None)
    if t == "lin_zram":
        return _lin_zram()
    if t == "lin_animacoes":
        rc, out, _ = _run_usuario(["gsettings", "get", "org.gnome.desktop.interface", "enable-animations"], 10, sessao=True)
        rc2, _, err = _run_usuario(["gsettings", "set", "org.gnome.desktop.interface", "enable-animations", "false"], 10, sessao=True)
        return (rc2 == 0), ("Feito (reversível)." if rc2 == 0 else "Falhou: %s" % err.strip()[:120]), ({"tipo": "lin_animacoes", "prev": out.strip() or "true"} if rc2 == 0 else None)
    if t == "lin_tracker":
        rc, _, err = _run_usuario(["systemctl", "--user", "mask", "--now", "tracker-miner-fs-3.service"], 30, sessao=True)
        return (rc == 0), ("Feito (reversível)." if rc == 0 else "Falhou: %s" % err.strip()[:120]), ({"tipo": "lin_tracker"} if rc == 0 else None)
    if t == "lin_fstrim":
        rc, _, err = _run(["systemctl", "enable", "--now", "fstrim.timer"], 30)
        return (rc == 0), ("Feito (reversível)." if rc == 0 else "Falhou: %s" % err.strip()[:120]), ({"tipo": "lin_fstrim"} if rc == 0 else None)
    if t == "lin_cmd":
        cmd = {"apt_clean": ["apt-get", "clean"], "journal": ["journalctl", "--vacuum-size=200M"], "flatpak": ["flatpak", "uninstall", "--unused", "-y", "--noninteractive"],
               "autoremove": ["apt-get", "-y", "autoremove"]}[acao["cmd"]]
        return _mede(lambda: (lambda r: (r[0] == 0, "Feito." if r[0] == 0 else "Falhou: %s" % r[2].strip()[:120], None))(_run(cmd, 900)))
    return False, "Ação desconhecida.", None


ZRAM_SCRIPT = """#!/bin/sh
# Destrava!: memoria comprimida (zram) do tamanho de metade da RAM
case "$1" in
  start)
    modprobe zram || exit 1
    T=$(awk '/MemTotal/{print $2}' /proc/meminfo)
    Z=$(zramctl --find --size "$((T / 2))K" --algorithm zstd 2>/dev/null || zramctl --find --size "$((T / 2))K") || exit 1
    mkswap "$Z" >/dev/null && swapon -p 100 "$Z" && echo "$Z" > /run/destrava-zram ;;
  stop)
    Z=$(cat /run/destrava-zram 2>/dev/null) && swapoff "$Z" && zramctl --reset "$Z" ;;
esac
"""
ZRAM_UNIDADE = """[Unit]
Description=Destrava! memoria comprimida (zram)
After=local-fs.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/local/sbin/destrava-zram start
ExecStop=/usr/local/sbin/destrava-zram stop

[Install]
WantedBy=multi-user.target
"""
ZRAM_SH = "/usr/local/sbin/destrava-zram"
ZRAM_ARQ = "/etc/systemd/system/destrava-zram.service"
SYSCTL_ARQ = "/etc/sysctl.d/99-destrava-zram.conf"


def _lin_zram():
    try:
        with open("/proc/sys/vm/swappiness") as fh:
            prev = fh.read().strip()
        os.makedirs(os.path.dirname(ZRAM_SH), exist_ok=True)
        with open(ZRAM_SH, "w") as fh:
            fh.write(ZRAM_SCRIPT)
        os.chmod(ZRAM_SH, 0o755)
        with open(ZRAM_ARQ, "w") as fh:
            fh.write(ZRAM_UNIDADE)
        with open(SYSCTL_ARQ, "w") as fh:
            fh.write("# Destrava!: com zram, o sistema pode usar a memória comprimida antes do disco\nvm.swappiness=150\n")
    except OSError as e:
        return False, "Precisa de sudo: %s" % e, None
    _run(["systemctl", "daemon-reload"])
    rc, _, err = _run(["systemctl", "enable", "--now", "destrava-zram.service"], 60)
    if rc != 0:
        return False, "Falhou: %s" % err.strip()[:120], None
    _run(["sysctl", "-p", SYSCTL_ARQ])
    return True, "Memória comprimida ligada (reversível).", {"tipo": "lin_zram", "swappiness": prev}


def desfazer(u):
    """True se voltou como estava. Tipos antigos (startup_win, startup_linux, visual_win, simulado) continuam valendo."""
    t = u.get("tipo")
    F = _f()
    if t == "simulado":
        return True
    if t in ("startup_linux", "startup_win", "visual_win"):
        return F._desfazer_um(u)
    if t == "store_win":
        j = _ps_json(PS_STORE_SET, {"pacote": u.get("pacote"), "tarefa": u.get("tarefa"), "estado": u.get("prev") if u.get("prev") is not None else 2})
        return bool(j and j.get("ok"))
    if t == "win_reg":
        return _reg_desfazer(u)
    if t == "win_servico":
        return _win_servico_desfazer(u)
    if t == "win_energia":
        return _win_cmd_ok("powercfg /setactive $env:BKP_G | Out-Null; @{ok=((powercfg /getactivescheme) -join ' ').ToLower().Contains($env:BKP_G.ToLower())} | ConvertTo-Json -Compress", {"g": u.get("prev")})
    if t == "win_hiber":
        return _win_cmd_ok("powercfg /h on | Out-Null; @{ok=((Get-ItemProperty 'HKLM:\\SYSTEM\\CurrentControlSet\\Control\\Power').HibernateEnabled -eq 1)} | ConvertTo-Json -Compress")
    if t == "win_tarefas":
        return all(_win_cmd_ok("Enable-ScheduledTask -TaskName $env:BKP_NOME -TaskPath $env:BKP_PASTA | Out-Null; @{ok=$true} | ConvertTo-Json -Compress",
                               {"nome": tr.get("nome"), "pasta": tr.get("pasta")}) for tr in u.get("tarefas") or [])
    if t == "agente_mac":
        return _inicio({"ligar": not u.get("ligou"), "item": {"fonte": "agente", "label": u.get("label"), "arquivo": u.get("arquivo")}})[0]
    if t == "login_mac":
        p = (u.get("path") or "").replace("\\", "\\\\").replace('"', '\\"')
        return _run_usuario(["osascript", "-e", 'tell application "System Events" to make login item at end with properties {path:"%s", hidden:false}' % p], 20)[0] == 0
    if t == "mac_movimento":
        ok = True
        for k, v in (u.get("prev") or {}).items():
            if v is None:  # não existia: apaga (apagar o que não existe dá erro e não importa)
                _run_usuario(["defaults", "delete", "com.apple.universalaccess", k], 10)
            elif _run_usuario(["defaults", "write", "com.apple.universalaccess", k, "-bool", "true" if v == "1" else "false"], 10)[0] != 0:
                ok = False
        return ok
    if t == "mac_spotlight":
        return _run(["mdutil", "-i", "on", u["vol"]], 60)[0] == 0
    if t == "lin_zram":
        _run(["systemctl", "disable", "--now", "destrava-zram.service"], 60)
        for p in (ZRAM_ARQ, SYSCTL_ARQ, ZRAM_SH):
            try:
                os.remove(p)
            except OSError:
                pass
        _run(["systemctl", "daemon-reload"])
        _run(["sysctl", "-w", "vm.swappiness=%s" % (u.get("swappiness") or 60)])
        return not os.path.exists(ZRAM_ARQ)
    if t == "lin_animacoes":
        return _run_usuario(["gsettings", "set", "org.gnome.desktop.interface", "enable-animations", u.get("prev") or "true"], 10, sessao=True)[0] == 0
    if t == "lin_tracker":
        ok = _run_usuario(["systemctl", "--user", "unmask", "tracker-miner-fs-3.service"], 30, sessao=True)[0] == 0
        _run_usuario(["systemctl", "--user", "start", "tracker-miner-fs-3.service"], 30, sessao=True)
        return ok
    if t == "lin_fstrim":
        return _run(["systemctl", "disable", "--now", "fstrim.timer"], 30)[0] == 0
    return False


def abrir_ajustes(qual):
    """Botões de recomendação manual (só abre a tela certa do sistema; não muda nada)."""
    if IS_MAC and qual == "ajustes_armazenamento":
        _run_usuario(["open", "x-apple.systempreferences:com.apple.settings.Storage"], 10)
        return True
    return False
