# -*- coding: utf-8 -*-
"""
BKP Pro - Ficha da máquina (D&D Technology)
Coleta hardware e desempenho, dá nota, sugere o sistema ideal, propõe melhorias e aplica (com desfazer).
Só biblioteca padrão. Windows usa PowerShell nativo; Linux usa /proc, /sys, dmidecode, lsblk.
Modelo "Outcome as a Service": o produto é o RESULTADO (nota antes -> depois), com prova guardada no pendrive.
"""
import copy
import datetime
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time

IS_WIN = os.name == "nt"
HERE = os.path.dirname(os.path.abspath(__file__))
STORE = os.path.join(HERE, "maquinas")
VERSAO_FICHA = 1


# ----------------------------------------------------------------------------------------------
# utilidades
# ----------------------------------------------------------------------------------------------
def run(cmd, timeout=25, env=None):
    try:
        kw = {}
        if IS_WIN:
            kw["creationflags"] = 0x08000000  # sem janela
        r = subprocess.run(cmd, capture_output=True, timeout=timeout, env=env, **kw)
        return (r.stdout or b"").decode("utf-8", "replace") + ("\n" + (r.stderr or b"").decode("utf-8", "replace") if r.returncode and r.stderr else "")
    except Exception:
        return ""


def run_out(cmd, timeout=25, env=None):
    """Só stdout."""
    try:
        kw = {}
        if IS_WIN:
            kw["creationflags"] = 0x08000000
        r = subprocess.run(cmd, capture_output=True, timeout=timeout, env=env, **kw)
        return (r.stdout or b"").decode("utf-8", "replace")
    except Exception:
        return ""


def aslist(x):
    if x is None:
        return []
    return x if isinstance(x, list) else [x]


def ps(script, timeout=60, env=None):
    full = "[Console]::OutputEncoding=[Text.Encoding]::UTF8; $ErrorActionPreference='SilentlyContinue'; " + script
    return run_out(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", full], timeout=timeout, env=env)


def ps_json(script, timeout=90):
    out = ps(script, timeout)
    i = out.find("{")
    if i < 0:
        return None
    try:
        return json.loads(out[i:])
    except ValueError:
        return None


def rd(path, default=""):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read().strip()
    except OSError:
        return default


def is_root():
    return (not IS_WIN) and hasattr(os, "geteuid") and os.geteuid() == 0


def user_home():
    if not IS_WIN and is_root() and os.environ.get("SUDO_USER"):
        try:
            import pwd
            return pwd.getpwnam(os.environ["SUDO_USER"]).pw_dir
        except Exception:
            pass
    return os.path.expanduser("~")


def interp(x, pts):
    if x <= pts[0][0]:
        return pts[0][1]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if x <= x1:
            return y0 + (y1 - y0) * (x - x0) / float(x1 - x0)
    return pts[-1][1]


def safe_name(s):
    return re.sub(r"[^0-9A-Za-z_-]+", "_", s).strip("_") or "maquina"


# ----------------------------------------------------------------------------------------------
# medições (iguais em qualquer sistema)
# ----------------------------------------------------------------------------------------------
def med_cpu():
    best = None
    for _ in range(3):
        t = time.perf_counter()
        s = 0
        for i in range(1500000):
            s += (i * i) % 7
        d = (time.perf_counter() - t) * 1000
        best = d if best is None else min(best, d)
    return round(best, 1)


def med_resposta():
    cmd = ["cmd", "/c", "exit", "0"] if IS_WIN else ["true"]
    kw = {"creationflags": 0x08000000} if IS_WIN else {}
    ts = []
    for _ in range(9):
        t = time.perf_counter()
        try:
            subprocess.run(cmd, capture_output=True, timeout=10, **kw)
        except Exception:
            continue
        ts.append((time.perf_counter() - t) * 1000)
    if not ts:
        return None
    ts.sort()
    return round(ts[len(ts) // 2], 1)


def _fstype(path):
    try:
        best = ("", "")
        for line in open("/proc/mounts", encoding="utf-8", errors="replace"):
            p = line.split()
            if len(p) > 2 and (path == p[1] or path.startswith(p[1].rstrip("/") + "/") or p[1] == "/"):
                if len(p[1]) >= len(best[0]):
                    best = (p[1], p[2])
        return best[1]
    except OSError:
        return ""


def med_disco_dd(dev):
    """Leitura sequencial direta (O_DIRECT) de 128 MB do disco. Somente leitura: não altera nada."""
    if IS_WIN or not shutil.which("dd") or not is_root() or not os.path.exists(dev):
        return None
    out = run(["dd", "if=" + dev, "of=/dev/null", "bs=1M", "count=128", "skip=512", "iflag=direct"], timeout=60)
    m = re.search(r"([\d.,]+)\s*(kB|MB|GB)/s", out)
    if not m:
        return None
    v = float(m.group(1).replace(",", "."))
    return round(v * {"kB": 0.001, "MB": 1, "GB": 1000}[m.group(2)], 1)


def med_disco_escrita(live=False):
    """Escrita sequencial de 96 MB com fsync + 150 arquivos pequenos, numa pasta temporária do disco do sistema."""
    base = None
    for cand in ([tempfile.gettempdir()] if IS_WIN else ["/var/tmp", tempfile.gettempdir()]):
        if os.path.isdir(cand) and os.access(cand, os.W_OK):
            if _fstype(cand) in ("tmpfs", "ramfs", "overlay") and not IS_WIN:
                continue
            base = cand
            break
    if not base:
        return None, None
    d = tempfile.mkdtemp(prefix="bkppro_", dir=base)
    try:
        blk = os.urandom(1024 * 1024)
        t = time.perf_counter()
        with open(os.path.join(d, "seq.bin"), "wb") as f:
            for _ in range(96):
                f.write(blk)
            f.flush()
            os.fsync(f.fileno())
        mbs = 96.0 / max(time.perf_counter() - t, 1e-6)
        t = time.perf_counter()
        for i in range(150):
            with open(os.path.join(d, "s%d.dat" % i), "wb") as f:
                f.write(blk[:4096])
        for i in range(150):
            os.remove(os.path.join(d, "s%d.dat" % i))
        ms = (time.perf_counter() - t) * 1000 / 150.0
        return round(mbs, 1), round(ms, 2)
    except OSError:
        return None, None
    finally:
        shutil.rmtree(d, ignore_errors=True)


# ----------------------------------------------------------------------------------------------
# coleta - Linux
# ----------------------------------------------------------------------------------------------
def _live_linux():
    c = rd("/proc/cmdline")
    return bool(re.search(r"\b(casper|boot=live|live-media|rd\.live)\b", c)) or os.path.isdir("/cdrom/casper")


def _parse_dmidecode(txt):
    slots = []
    for blk in txt.split("\n\n"):
        if "Memory Device" not in blk or "Array Handle" not in blk and "Locator" not in blk:
            continue
        g = lambda k: (re.search(r"^\s*" + k + r":\s*(.+)$", blk, re.M) or [None, ""])[1].strip()
        size = g("Size")
        m = re.match(r"(\d+)\s*(MB|GB)", size)
        gb = 0
        if m:
            gb = int(m.group(1)) / (1024.0 if m.group(2) == "MB" else 1.0)
        spd = re.search(r"(\d+)", g("Configured Memory Speed") or g("Configured Clock Speed") or g("Speed"))
        slots.append({"local": g("Locator") or "?", "gb": round(gb, 1), "tipo": g("Type") if gb else "", "mhz": int(spd.group(1)) if (spd and gb) else 0})
    return slots


def _systemd_boot(txt):
    m = re.search(r"=\s*(?:(\d+)min\s*)?([\d.]+)s", txt)
    if not m:
        m = re.search(r"Startup finished in .*=\s*(?:(\d+)min\s*)?([\d.]+)s", txt)
    if not m:
        return None
    return round(int(m.group(1) or 0) * 60 + float(m.group(2)), 1)


def _parse_desktop(path):
    d = {}
    try:
        for line in open(path, encoding="utf-8", errors="replace"):
            if "=" in line and not line.startswith("#") and not line.startswith("["):
                k, v = line.split("=", 1)
                d.setdefault(k.strip(), v.strip())
    except OSError:
        pass
    return d


def coletar_linux(cb):
    live = _live_linux()
    f = {"so": {"familia": "linux", "live": live}, "maquina": {}, "cpu": {}, "ram": {}, "discos": [], "volumes": [], "gpu": [], "bateria": None, "medidas": {}, "inicializacao": [], "pesados": []}
    cb("Lendo hardware", 5)
    osr = {}
    for line in rd("/etc/os-release").splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            osr[k] = v.strip('"')
    f["so"].update({"nome": osr.get("PRETTY_NAME", "Linux"), "versao": os.uname().release, "arch": os.uname().machine,
                    "uefi": os.path.isdir("/sys/firmware/efi"), "tpm": ("2.0" if rd("/sys/class/tpm/tpm0/tpm_version_major") == "2" else (rd("/sys/class/tpm/tpm0/tpm_version_major") and "1.2") or None)})
    sb = None
    for p in os.listdir("/sys/firmware/efi/efivars") if os.path.isdir("/sys/firmware/efi/efivars") else []:
        if p.startswith("SecureBoot-"):
            try:
                sb = open("/sys/firmware/efi/efivars/" + p, "rb").read()[-1:] == b"\x01"
            except OSError:
                pass
    f["so"]["secure_boot"] = sb
    dmi = "/sys/class/dmi/id/"
    f["maquina"] = {"fabricante": rd(dmi + "sys_vendor"), "modelo": rd(dmi + "product_name"), "bios": rd(dmi + "bios_version")}
    uuid = rd(dmi + "product_uuid") or rd("/etc/machine-id")
    # CPU
    ci = rd("/proc/cpuinfo")
    model = (re.search(r"model name\s*:\s*(.+)", ci) or re.search(r"Hardware\s*:\s*(.+)", ci) or [0, "CPU desconhecida"])[1].strip()
    threads = len(re.findall(r"^processor\s*:", ci, re.M)) or (os.cpu_count() or 1)
    pairs = set(re.findall(r"physical id\s*:\s*(\d+)\s*\n(?:.*\n)*?core id\s*:\s*(\d+)", ci))
    mhz = re.search(r"cpu MHz\s*:\s*([\d.]+)", ci)
    f["cpu"] = {"modelo": re.sub(r"\s+", " ", model), "nucleos": len(pairs) or threads, "threads": threads, "mhz": int(float(mhz.group(1))) if mhz else 0}
    # RAM
    mi = rd("/proc/meminfo")
    tot = int((re.search(r"MemTotal:\s*(\d+)", mi) or [0, 0])[1]) / 1048576.0
    av = int((re.search(r"MemAvailable:\s*(\d+)", mi) or [0, 0])[1]) / 1048576.0
    slots = []
    if is_root() and shutil.which("dmidecode"):
        slots = _parse_dmidecode(run_out(["dmidecode", "-t", "memory"]))
    f["ram"] = {"total_gb": round(tot, 2), "livre_gb": round(av, 2), "slots_total": len(slots), "slots": slots}
    # discos
    cb("Lendo discos", 15)
    big = None
    try:
        lj = json.loads(run_out(["lsblk", "-J", "-b", "-o", "NAME,TYPE,ROTA,SIZE,MODEL,TRAN,RM,MOUNTPOINT"]) or "{}")
    except ValueError:
        lj = {}
    for d in lj.get("blockdevices", []):
        if d.get("type") != "disk" or str(d.get("rm")) in ("1", "True", "true") or d.get("name", "").startswith(("loop", "zram", "ram")) or int(d.get("size") or 0) < 4e9:
            continue
        tran = (d.get("tran") or "").lower()
        rota = str(d.get("rota")) in ("1", "True", "true")
        tipo = "NVMe" if (tran == "nvme" or d["name"].startswith("nvme")) else ("HDD" if rota else "SSD")
        saude = "desconhecida"
        if is_root() and shutil.which("smartctl"):
            o = run(["smartctl", "-H", "/dev/" + d["name"]], timeout=20)
            saude = "OK" if re.search(r"PASSED|OK$", o, re.M) else ("FALHA" if "FAILED" in o else "desconhecida")
        disc = {"nome": (d.get("model") or d["name"]).strip(), "dev": "/dev/" + d["name"], "tipo": tipo, "tam_gb": round(int(d.get("size") or 0) / 1e9, 1), "saude": saude}
        f["discos"].append(disc)
        if big is None or disc["tam_gb"] > big["tam_gb"]:
            big = disc
    try:
        for line in open("/proc/mounts", encoding="utf-8", errors="replace"):
            p = line.split()
            if len(p) > 2 and p[0].startswith("/dev/") and p[2] in ("ext4", "ext3", "btrfs", "xfs", "ntfs", "ntfs3", "fuseblk", "vfat", "exfat", "f2fs") and not p[1].startswith(("/boot", "/snap")):
                try:
                    u = shutil.disk_usage(p[1])
                    if u.total < 2e9:
                        continue
                    f["volumes"].append({"id": p[1], "tam_gb": round(u.total / 1e9, 1), "livre_gb": round(u.free / 1e9, 1)})
                except OSError:
                    pass
    except OSError:
        pass
    # GPU
    for line in run_out(["lspci", "-mm"]).splitlines():
        if re.search(r"VGA|3D controller|Display controller", line):
            parts = re.findall(r'"([^"]*)"', line)
            if len(parts) >= 3:
                f["gpu"].append({"nome": (parts[1] + " " + parts[2]).strip(), "vram_gb": 0})
    # bateria
    for b in sorted(os.listdir("/sys/class/power_supply")) if os.path.isdir("/sys/class/power_supply") else []:
        if b.startswith("BAT"):
            base = "/sys/class/power_supply/" + b + "/"
            full = rd(base + "energy_full") or rd(base + "charge_full")
            des = rd(base + "energy_full_design") or rd(base + "charge_full_design")
            try:
                f["bateria"] = {"carga": int(rd(base + "capacity") or 0), "saude_pct": round(int(full) * 100.0 / int(des)) if full and des else None}
            except ValueError:
                pass
            break
    # medições
    m = f["medidas"]
    cb("Medindo processador", 30)
    m["cpu_ms"] = med_cpu()
    cb("Medindo disco", 45)
    mbs = med_disco_dd(big["dev"]) if big else None
    metodo = "leitura direta (somente leitura)"
    arq = None
    if mbs is None and not live:
        mbs, arq = med_disco_escrita()
        metodo = "escrita em pasta temporária"
    elif mbs is None:
        metodo = "não medido"
    m["disco_mb_s"], m["disco_metodo"], m["arquivos_ms"] = mbs, metodo, arq
    cb("Medindo tempo de resposta", 60)
    m["resposta_ms"] = med_resposta()
    try:
        m["uptime_h"] = round(float(rd("/proc/uptime").split()[0]) / 3600.0, 1)
    except (ValueError, IndexError):
        m["uptime_h"] = None
    m["boot_s"] = None
    if not live and shutil.which("systemd-analyze"):
        m["boot_s"] = _systemd_boot(run_out(["systemd-analyze"], timeout=20))
    # processos
    cb("Lendo processos", 75)
    agg = {}
    n = 0
    for pid in os.listdir("/proc"):
        if pid.isdigit():
            st = rd("/proc/%s/status" % pid)
            nm = (re.search(r"^Name:\s*(.+)$", st, re.M) or [0, ""])[1]
            rss = (re.search(r"^VmRSS:\s*(\d+)", st, re.M) or [0, 0])[1]
            if nm:
                n += 1
                a = agg.setdefault(nm, [0, 0])
                a[0] += int(rss)
                a[1] += 1
    m["processos"] = n
    f["pesados"] = [{"nome": k, "ram_mb": round(v[0] / 1024.0), "instancias": v[1]} for k, v in sorted(agg.items(), key=lambda kv: -kv[1][0])[:20]]
    # inicialização (autostart gráfico)
    if not live:
        seen = {}
        for dr in (os.path.join(user_home(), ".config/autostart"), "/etc/xdg/autostart"):
            if os.path.isdir(dr):
                for fn in sorted(os.listdir(dr)):
                    if fn.endswith(".desktop"):
                        d = _parse_desktop(os.path.join(dr, fn))
                        if fn in seen or d.get("Hidden", "").lower() == "true":
                            seen.setdefault(fn, None)
                            continue
                        seen[fn] = True
                        if d.get("X-GNOME-Autostart-enabled", "true").lower() == "false":
                            continue
                        f["inicializacao"].append({"nome": d.get("Name", fn), "comando": d.get("Exec", ""), "local": os.path.join(dr, fn), "usuario": "", "arquivo": fn})
    # pacotes
    cb("Contando programas", 88)
    cnt = run_out(["dpkg-query", "-W", "-f", "${Package}\n"]).count("\n") if shutil.which("dpkg-query") else (run_out(["rpm", "-qa"]).count("\n") if shutil.which("rpm") else None)
    m["prog_instalados"] = cnt
    f["uuid"] = uuid
    return f


def coletar_mac(cb):
    """macOS (para testes e para Macs de clientes). Melhor esforço: cada leitura é independente."""
    def sc(*a):
        return run_out(list(a), timeout=20).strip()
    f = {"so": {"familia": "mac", "live": False}, "maquina": {}, "cpu": {}, "ram": {}, "discos": [], "volumes": [], "gpu": [], "bateria": None, "medidas": {}, "inicializacao": [], "pesados": []}
    cb("Lendo hardware", 8)
    ver = sc("sw_vers", "-productVersion")
    f["so"].update({"nome": "macOS " + ver, "versao": sc("uname", "-r"), "arch": os.uname().machine, "uefi": True, "secure_boot": None, "tpm": None})
    f["maquina"] = {"fabricante": "Apple", "modelo": sc("sysctl", "-n", "hw.model"), "bios": ""}
    hw = sc("system_profiler", "SPHardwareDataType")
    mn = re.search(r"Model Name:\s*(.+)", hw)
    ch = re.search(r"Chip:\s*(.+)", hw)
    if mn:
        f["maquina"]["nome_comercial"] = mn.group(1).strip() + ((" (" + ch.group(1).strip() + ")") if ch else "")
    brand = sc("sysctl", "-n", "machdep.cpu.brand_string") or ("Apple Silicon" if os.uname().machine == "arm64" else "CPU")
    ncpu = int(sc("sysctl", "-n", "hw.ncpu") or os.cpu_count() or 1)
    phys = int(sc("sysctl", "-n", "hw.physicalcpu") or ncpu)
    f["cpu"] = {"modelo": brand, "nucleos": phys, "threads": ncpu, "mhz": 0}
    tot = int(sc("sysctl", "-n", "hw.memsize") or 0) / 1073741824.0
    vm = sc("vm_stat")
    ps_ = int((re.search(r"page size of (\d+)", vm) or [0, 16384])[1])
    free_p = sum(int((re.search(k + r":\s+(\d+)", vm) or [0, 0])[1]) for k in ("Pages free", "Pages inactive", "Pages speculative"))
    f["ram"] = {"total_gb": round(tot, 2), "livre_gb": round(free_p * ps_ / 1073741824.0, 2), "slots_total": 0, "slots": []}
    try:
        u = shutil.disk_usage("/")
        f["discos"] = [{"nome": "Disco interno", "dev": "/", "tipo": "SSD", "tam_gb": round(u.total / 1e9, 1), "saude": "desconhecida"}]
        f["volumes"] = [{"id": "/", "tam_gb": round(u.total / 1e9, 1), "livre_gb": round(u.free / 1e9, 1)}]
    except OSError:
        pass
    gp = sc("system_profiler", "SPDisplaysDataType")
    for m in re.finditer(r"Chipset Model:\s*(.+)", gp):
        f["gpu"].append({"nome": m.group(1).strip(), "vram_gb": 0})
    cb("Medindo processador", 30)
    m = f["medidas"]
    m["cpu_ms"] = med_cpu()
    cb("Medindo disco", 45)
    mbs, arq = med_disco_escrita()
    m.update({"disco_mb_s": mbs, "disco_metodo": "escrita em pasta temporária", "arquivos_ms": arq})
    cb("Medindo tempo de resposta", 65)
    m["resposta_ms"] = med_resposta()
    bt = re.search(r"sec = (\d+)", sc("sysctl", "-n", "kern.boottime"))
    m["uptime_h"] = round((time.time() - int(bt.group(1))) / 3600.0, 1) if bt else None
    m["boot_s"] = None
    cb("Lendo processos", 80)
    agg = {}
    n = 0
    for line in run_out(["ps", "-axo", "rss=,comm="], timeout=20).splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) == 2 and parts[0].isdigit():
            nm = os.path.basename(parts[1])
            a = agg.setdefault(nm, [0, 0])
            a[0] += int(parts[0])
            a[1] += 1
            n += 1
    m["processos"] = n
    f["pesados"] = [{"nome": k, "ram_mb": round(v[0] / 1024.0), "instancias": v[1]} for k, v in sorted(agg.items(), key=lambda kv: -kv[1][0])[:20]]
    m["prog_instalados"] = len([x for x in os.listdir("/Applications") if x.endswith(".app")]) if os.path.isdir("/Applications") else None
    f["uuid"] = identificadores().get("uuid") or sc("sysctl", "-n", "hw.model")
    return f


# ----------------------------------------------------------------------------------------------
# coleta - Windows (PowerShell nativo)
# ----------------------------------------------------------------------------------------------
PS_COLETA = r"""
$r=@{}
$r.cs=Get-CimInstance Win32_ComputerSystem | Select-Object Manufacturer,Model,TotalPhysicalMemory
$r.uuid=(Get-CimInstance Win32_ComputerSystemProduct).UUID
$r.bios=Get-CimInstance Win32_BIOS | Select-Object SMBIOSBIOSVersion
$r.cpu=Get-CimInstance Win32_Processor | Select-Object Name,NumberOfCores,NumberOfLogicalProcessors,MaxClockSpeed
$r.mem=@(Get-CimInstance Win32_PhysicalMemory | Select-Object DeviceLocator,Capacity,Speed,ConfiguredClockSpeed,SMBIOSMemoryType)
$r.memarr=Get-CimInstance Win32_PhysicalMemoryArray | Select-Object MemoryDevices
$r.pd=@(Get-PhysicalDisk | Select-Object FriendlyName,MediaType,BusType,Size,HealthStatus)
$r.ld=@(Get-CimInstance Win32_LogicalDisk -Filter "DriveType=3" | Select-Object DeviceID,Size,FreeSpace)
$r.gpu=@(Get-CimInstance Win32_VideoController | Select-Object Name,AdapterRAM)
$o=Get-CimInstance Win32_OperatingSystem
$r.os=@{caption=$o.Caption;version=$o.Version;build=$o.BuildNumber;arch=$o.OSArchitecture;free=$o.FreePhysicalMemory;total=$o.TotalVisibleMemorySize;boot=$o.LastBootUpTime.ToString('s')}
$r.nproc=@(Get-Process).Count
$r.procs=@(Get-Process | Group-Object ProcessName | ForEach-Object { @{n=$_.Name;ram=[int64](($_.Group|Measure-Object WorkingSet64 -Sum).Sum);c=$_.Count} } | Sort-Object {$_.ram} -Descending | Select-Object -First 20)
$r.start=@(Get-CimInstance Win32_StartupCommand | Select-Object Name,Command,Location,User)
$r.nprog=@(Get-ItemProperty 'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*','HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*' | Where-Object {$_.DisplayName -and -not $_.SystemComponent}).Count
$e=Get-WinEvent -FilterHashtable @{LogName='Microsoft-Windows-Diagnostics-Performance/Operational';Id=100} -MaxEvents 1
if($e){$x=[xml]$e.ToXml();$d=@{};foreach($n in $x.Event.EventData.Data){$d[$n.Name]=$n.'#text'};$r.bootev=@{boot=$d['BootTime'];main=$d['MainPathBootTime'];when=$e.TimeCreated.ToString('s')}}
$t=Get-CimInstance -Namespace root\cimv2\Security\MicrosoftTpm -ClassName Win32_Tpm
if($t){$r.tpm=@{ver=$t.SpecVersion}}
$u=$true;$sb=$false
try{$sb=[bool](Confirm-SecureBootUEFI)}catch{if($_.Exception.Message -match 'not supported'){$u=$false}}
$r.uefi=$u;$r.sb=$sb
$b=Get-CimInstance Win32_Battery | Select-Object EstimatedChargeRemaining
if($b){$r.bat=@{charge=$b.EstimatedChargeRemaining}
$ds=Get-CimInstance -Namespace root\wmi -ClassName BatteryStaticData | Select-Object -First 1
$fc=Get-CimInstance -Namespace root\wmi -ClassName BatteryFullChargedCapacity | Select-Object -First 1
if($ds -and $fc){$r.bat.design=$ds.DesignedCapacity;$r.bat.full=$fc.FullChargedCapacity}}
$r | ConvertTo-Json -Depth 5 -Compress
"""

MEMTIPO = {20: "DDR", 21: "DDR2", 24: "DDR3", 26: "DDR4", 34: "DDR5", 27: "LPDDR", 28: "LPDDR2", 29: "LPDDR3", 30: "LPDDR4", 35: "LPDDR5"}


def normalizar_windows(raw, med):
    """Converte a saída do PowerShell (dict) em ficha. Separado do subprocess para ser testável."""
    cs = raw.get("cs") or {}
    osr = raw.get("os") or {}
    cpu = aslist(raw.get("cpu"))
    cpu0 = cpu[0] if cpu else {}
    f = {"so": {"familia": "windows", "live": False, "nome": (osr.get("caption") or "Windows").replace("Microsoft ", "").strip(), "versao": "%s (build %s)" % (osr.get("version", ""), osr.get("build", "")),
                "arch": osr.get("arch", ""), "uefi": bool(raw.get("uefi")), "secure_boot": bool(raw.get("sb")), "tpm": ((raw.get("tpm") or {}).get("ver") or "").split(",")[0].strip() or None},
         "maquina": {"fabricante": cs.get("Manufacturer", ""), "modelo": cs.get("Model", ""), "bios": (raw.get("bios") or {}).get("SMBIOSBIOSVersion", "")},
         "cpu": {"modelo": re.sub(r"\s+", " ", str(cpu0.get("Name", "CPU desconhecida"))).strip(), "nucleos": sum(int(c.get("NumberOfCores") or 0) for c in cpu) or None,
                 "threads": sum(int(c.get("NumberOfLogicalProcessors") or 0) for c in cpu) or None, "mhz": int(cpu0.get("MaxClockSpeed") or 0)},
         "discos": [], "volumes": [], "gpu": [], "bateria": None, "medidas": dict(med), "inicializacao": [], "pesados": [], "uuid": raw.get("uuid") or ""}
    tot = int(osr.get("total") or 0) / 1048576.0 or int(cs.get("TotalPhysicalMemory") or 0) / 1073741824.0
    fr = int(osr.get("free") or 0) / 1048576.0
    slots = []
    for m in aslist(raw.get("mem")):
        spd = int(m.get("ConfiguredClockSpeed") or m.get("Speed") or 0)
        slots.append({"local": m.get("DeviceLocator", "?"), "gb": round(int(m.get("Capacity") or 0) / 1073741824.0, 1), "tipo": MEMTIPO.get(int(m.get("SMBIOSMemoryType") or 0), ""), "mhz": spd})
    ma = raw.get("memarr")
    nslots = sum(int(x.get("MemoryDevices") or 0) for x in aslist(ma)) if ma else len(slots)
    f["ram"] = {"total_gb": round(tot, 2), "livre_gb": round(fr, 2), "slots_total": max(nslots, len(slots)), "slots": slots}
    for d in aslist(raw.get("pd")):
        mt = str(d.get("MediaType") or "")
        bt = str(d.get("BusType") or "")
        tipo = "NVMe" if "NVMe" in bt or bt == "17" else ("SSD" if "SSD" in mt else ("HDD" if "HDD" in mt else "SSD" if mt in ("4",) else "HDD" if mt in ("3",) else "desconhecido"))
        f["discos"].append({"nome": d.get("FriendlyName", "Disco"), "tipo": tipo, "tam_gb": round(int(d.get("Size") or 0) / 1e9, 1), "saude": "OK" if str(d.get("HealthStatus")) in ("Healthy", "0") else (str(d.get("HealthStatus") or "desconhecida"))})
    for v in aslist(raw.get("ld")):
        f["volumes"].append({"id": v.get("DeviceID", "?"), "tam_gb": round(int(v.get("Size") or 0) / 1e9, 1), "livre_gb": round(int(v.get("FreeSpace") or 0) / 1e9, 1)})
    for g in aslist(raw.get("gpu")):
        f["gpu"].append({"nome": g.get("Name", "GPU"), "vram_gb": round(int(g.get("AdapterRAM") or 0) / 1073741824.0, 1)})
    b = raw.get("bat")
    if b:
        sp = None
        if b.get("design") and b.get("full"):
            sp = round(int(b["full"]) * 100.0 / int(b["design"]))
        f["bateria"] = {"carga": b.get("charge"), "saude_pct": sp}
    m = f["medidas"]
    be = raw.get("bootev") or {}
    try:
        m["boot_s"] = round(int(be.get("boot")) / 1000.0, 1) if be.get("boot") else None
    except (TypeError, ValueError):
        m["boot_s"] = None
    try:
        bt = datetime.datetime.fromisoformat(osr.get("boot"))
        m["uptime_h"] = round((datetime.datetime.now() - bt).total_seconds() / 3600.0, 1)
    except (TypeError, ValueError):
        m["uptime_h"] = None
    m["processos"] = raw.get("nproc")
    m["prog_instalados"] = raw.get("nprog")
    f["pesados"] = [{"nome": p.get("n", "?"), "ram_mb": round(int(p.get("ram") or 0) / 1048576.0), "instancias": p.get("c", 1)} for p in aslist(raw.get("procs"))]
    for s in aslist(raw.get("start")):
        f["inicializacao"].append({"nome": s.get("Name", "?"), "comando": s.get("Command", ""), "local": s.get("Location", ""), "usuario": s.get("User", "")})
    return f


def coletar_windows(cb):
    cb("Lendo hardware e programas (PowerShell)", 10)
    raw = ps_json(PS_COLETA, timeout=120) or {}
    cb("Medindo processador", 40)
    med = {"cpu_ms": med_cpu()}
    cb("Medindo disco", 55)
    mbs, arq = med_disco_escrita()
    med.update({"disco_mb_s": mbs, "disco_metodo": "escrita em pasta temporária", "arquivos_ms": arq})
    cb("Medindo tempo de resposta", 80)
    med["resposta_ms"] = med_resposta()
    cb("Organizando", 92)
    return normalizar_windows(raw, med)


def coletar(cb=None):
    cb = cb or (lambda e, p: None)
    f = coletar_windows(cb) if IS_WIN else (coletar_mac(cb) if sys.platform == "darwin" else coletar_linux(cb))
    f["host"] = socket.gethostname()
    f["quando"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    f["versao_ficha"] = VERSAO_FICHA
    f["ids"] = identificadores()
    f["mid"] = resolver_mid(f["ids"], f["host"], (f.get("cpu") or {}).get("modelo", ""))
    migrar_legado(f["mid"])
    cb("Pronto", 100)
    return f


# ----------------------------------------------------------------------------------------------
# identidade da máquina: código estável por hardware (DD-XXXX-XXXX), independente do nome do PC
# ----------------------------------------------------------------------------------------------
_GENERICO = re.compile(r"^(0+|f+|[0f-]+|03000200-0400-0500-0006-000700080009|not (specified|settable|present|applicable)|to be filled.*|default string|none|unknown|system serial number|123456789.*)$", re.I)
_MID = {}


def _id_valido(s):
    s = (s or "").strip()
    return len(s) >= 6 and not _GENERICO.match(s)


def _macs_linux():
    out, base = [], "/sys/class/net"
    try:
        nomes = sorted(os.listdir(base))
    except OSError:
        return out
    for n in nomes:
        if not os.path.exists(os.path.join(base, n, "device")) or n.startswith(("docker", "veth", "br-", "virbr", "tun", "tap")):
            continue
        m = rd(os.path.join(base, n, "address")).strip().lower()
        if re.fullmatch(r"([0-9a-f]{2}:){5}[0-9a-f]{2}", m) and m != "00:00:00:00:00:00":
            out.append(m)
    return out


def identificadores(refazer=False):
    """UUID de hardware, serial e MACs físicos: o que sobrevive a trocar o nome do PC ou formatar."""
    if "ids" in _MID and not refazer:
        return _MID["ids"]
    ids = {"uuid": "", "serial": "", "macs": []}
    try:
        if IS_WIN:
            o = ps("$u=(Get-CimInstance Win32_ComputerSystemProduct).UUID; $s=(Get-CimInstance Win32_BIOS).SerialNumber; "
                   "$m=(Get-NetAdapter -Physical -ErrorAction SilentlyContinue | ForEach-Object {$_.MacAddress}) -join ','; \"$u|$s|$m\"", 30).strip().splitlines()
            parts = (o[-1] if o else "").split("|")
            if len(parts) >= 3:
                ids["uuid"], ids["serial"] = parts[0].strip(), parts[1].strip()
                ids["macs"] = [x.strip().lower().replace("-", ":") for x in parts[2].split(",") if x.strip()]
        elif sys.platform == "darwin":
            o = run_out(["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"])
            u = re.search(r'"IOPlatformUUID"\s*=\s*"([^"]+)"', o)
            sn = re.search(r'"IOPlatformSerialNumber"\s*=\s*"([^"]+)"', o)
            ids["uuid"], ids["serial"] = (u.group(1) if u else ""), (sn.group(1) if sn else "")
            e = re.search(r"ether\s+([0-9a-f:]{17})", run_out(["ifconfig", "en0"]))
            if e:
                ids["macs"] = [e.group(1).lower()]
        else:
            ids["uuid"] = rd("/sys/class/dmi/id/product_uuid")
            ids["serial"] = rd("/sys/class/dmi/id/product_serial") or rd("/sys/class/dmi/id/board_serial")
            ids["macs"] = _macs_linux()
    except Exception:
        pass
    if not _id_valido(ids["uuid"]):
        ids["uuid"] = ""
    if not _id_valido(ids["serial"]):
        ids["serial"] = ""
    ids["macs"] = sorted(set(ids["macs"]))
    _MID["ids"] = ids
    return ids


def _hash_id(base):
    alf = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    n = int.from_bytes(hashlib.sha256(base.encode("utf-8")).digest()[:8], "big")
    s = "".join(alf[(n >> (5 * i)) & 31] for i in range(8))
    return "DD-%s-%s" % (s[:4], s[4:])


def _mids_conhecidos():
    try:
        return [d for d in os.listdir(STORE) if os.path.isdir(os.path.join(STORE, d))]
    except OSError:
        return []


def resolver_mid(ids, host="", cpu=""):
    """Reaproveita o código de uma máquina já conhecida (mesmo UUID/serial/MAC) ou cria um novo."""
    for mid in _mids_conhecidos():
        mi = (meta_ler(mid).get("ids") or {})
        if ids.get("uuid") and ids["uuid"] == mi.get("uuid"):
            return mid
        if ids.get("serial") and ids["serial"] == mi.get("serial"):
            return mid
        if set(ids.get("macs") or []) & set(mi.get("macs") or []):
            return mid
    base = ids.get("uuid") or ids.get("serial") or ((ids.get("macs") or [""])[0]) or (host + cpu)
    return _hash_id(base)


def _mid_legado():
    """Fórmula antiga (nome-do-pc + hash), só para migrar históricos já gravados no pendrive."""
    host = socket.gethostname()
    if IS_WIN:
        uuid, cpu = ps("(Get-CimInstance Win32_ComputerSystemProduct).UUID", 20).strip(), ""
    elif sys.platform == "darwin":
        uuid, cpu = run_out(["sysctl", "-n", "kern.uuid"]).strip(), ""
    else:
        uuid = rd("/sys/class/dmi/id/product_uuid") or rd("/etc/machine-id")
        ci = rd("/proc/cpuinfo")
        cpu = re.sub(r"\s+", " ", (re.search(r"model name\s*:\s*(.+)", ci) or [0, ""])[1].strip())
    base = uuid if uuid and uuid.strip("0-") else host + cpu
    return safe_name(host)[:24] + "-" + hashlib.sha256(base.encode("utf-8")).hexdigest()[:6]


def migrar_legado(mid_novo):
    try:
        velho = _mid_legado()
    except Exception:
        return
    if velho == mid_novo:
        return
    dv, dn = pasta(velho), pasta(mid_novo)
    if not os.path.isdir(dv):
        return
    os.makedirs(dn, exist_ok=True)
    for nome in os.listdir(dv):
        a, b = os.path.join(dv, nome), os.path.join(dn, nome)
        if nome == "historico.json":
            try:
                h = hist_get(velho) + hist_get(mid_novo)
                h.sort(key=lambda x: x.get("quando", ""))
                with open(b, "w", encoding="utf-8") as fh:
                    json.dump(h, fh, ensure_ascii=False, indent=1)
            except Exception:
                pass
            os.remove(a)
        elif os.path.exists(b):
            os.replace(a, b + ".antigo")
        else:
            os.replace(a, b)
    try:
        os.rmdir(dv)
    except OSError:
        pass


def machine_id(f=None):
    f = f or {}
    ids = f.get("ids") or identificadores()
    return resolver_mid(ids, f.get("host") or socket.gethostname(), (f.get("cpu") or {}).get("modelo", ""))


def machine_id_rapido():
    """Código da máquina sem coletar a ficha inteira (para gravar histórico do backup)."""
    ids = identificadores()
    cpu = ""
    if not (ids.get("uuid") or ids.get("serial") or ids.get("macs")):
        ci = rd("/proc/cpuinfo")
        cpu = re.sub(r"\s+", " ", (re.search(r"model name\s*:\s*(.+)", ci) or [0, ""])[1].strip()) or (run_out(["sysctl", "-n", "machdep.cpu.brand_string"]).strip() if sys.platform == "darwin" else "")
    mid = resolver_mid(ids, socket.gethostname(), cpu)
    migrar_legado(mid)
    return mid


# ----------------------------------------------------------------------------------------------
# pontuação
# ----------------------------------------------------------------------------------------------
PESOS = {"cpu": 0.18, "ram": 0.18, "disco": 0.22, "resposta": 0.09, "boot": 0.13, "inicio": 0.09, "espaco": 0.11}


def _nota_cpu(ms):
    return interp(ms, [(150, 100), (300, 88), (600, 65), (1200, 38), (2500, 14), (5000, 4)])


def _nota_ram_gb(gb):
    return interp(gb, [(0.5, 3), (1, 8), (2, 22), (3, 35), (4, 50), (6, 65), (8, 80), (12, 92), (16, 100)])


def _nota_ram_livre(livre_gb):
    return interp(livre_gb, [(0.3, 5), (0.8, 25), (1.5, 45), (2.5, 62), (4, 80), (8, 100)])


def _nota_disco_mb(mbs):
    return interp(mbs, [(10, 8), (40, 28), (80, 48), (150, 68), (300, 85), (500, 95), (1500, 100)])


def _nota_arquivos(ms):
    return interp(-ms, [(-30, 5), (-10, 20), (-3, 45), (-1, 70), (-0.3, 100)])


def _nota_boot(s):
    return interp(s, [(10, 100), (20, 90), (35, 72), (60, 48), (90, 25), (150, 6)])


def _nota_inicio(n):
    return interp(n, [(3, 100), (6, 85), (10, 65), (16, 40), (25, 18), (40, 5)])


def _nota_resposta(ms, win):
    pts = [(40, 100), (80, 82), (150, 60), (300, 35), (600, 10)] if win else [(6, 100), (15, 82), (40, 58), (100, 30), (250, 8)]
    return interp(ms, pts)


# Faixas únicas: o mesmo corte vale para nome, cor, velocímetro e troféu.
FAIXAS = [(25, "Crítica", 1), (50, "Fraca", 2), (75, "Regular", 3), (95, "Muito boa", 4), (100, "Excelente", 5)]
TROFEUS = {1: "Ábaco de Pedra", 2: "Era das Válvulas", 3: "PC Bege", 4: "Notebook Fino", 5: "A Pera"}


def nivel(n):
    for lim, _, nv in FAIXAS:
        if n <= lim:
            return nv
    return 5


def classe(n):
    return FAIXAS[nivel(n) - 1][1]


def trofeu(n):
    nv = nivel(n)
    return {"nivel": nv, "nome": TROFEUS[nv], "classe": FAIXAS[nv - 1][1]}


def volume_principal(f):
    vs = [v for v in f.get("volumes", []) if v.get("tam_gb")]
    return max(vs, key=lambda v: v["tam_gb"]) if vs else None


def nota_espaco(f):
    """(nota, texto) do espaço livre no maior volume, ou None."""
    v = volume_principal(f)
    if not v:
        return None
    pct = v["livre_gb"] * 100.0 / v["tam_gb"]
    n = interp(pct, [(3, 5), (8, 25), (15, 50), (25, 75), (40, 95), (60, 100)])
    if v["livre_gb"] < 10:
        n = min(n, 30)
    return n, "%.0f GB livres de %.0f GB (%.0f%%)" % (v["livre_gb"], v["tam_gb"], pct)


def disco_principal(f):
    ds = f.get("discos") or []
    if not ds:
        return None
    return sorted(ds, key=lambda d: -(d.get("tam_gb") or 0))[0]


def pior_livre_pct(f):
    vs = [v for v in f.get("volumes", []) if v.get("tam_gb")]
    if not vs:
        return None
    return min(v["livre_gb"] * 100.0 / v["tam_gb"] for v in vs)


def pontuar(f):
    m = f.get("medidas") or {}
    win = (f.get("so") or {}).get("familia") == "windows"
    itens = []

    def add(i, nome, txt, nota):
        if nota is not None:
            itens.append({"id": i, "nome": nome, "valor": txt, "nota": int(round(max(0, min(100, nota)))), "peso": PESOS[i]})

    if m.get("cpu_ms") is not None:
        cpu = f.get("cpu", {})
        add("cpu", "Processador", "%s núcleos · teste %.2f s" % (cpu.get("nucleos") or "?", m["cpu_ms"] / 1000.0), _nota_cpu(m["cpu_ms"]))
    ram = f.get("ram", {})
    if ram.get("total_gb"):
        n = _nota_ram_gb(ram["total_gb"])
        if not (f.get("so") or {}).get("live") and ram.get("livre_gb") is not None:
            n = 0.6 * n + 0.4 * _nota_ram_livre(ram["livre_gb"])
        add("ram", "Memória", "%.1f GB · livre agora %.1f GB" % (ram["total_gb"], ram.get("livre_gb") or 0), n)
    d = disco_principal(f)
    if d or m.get("disco_mb_s") is not None:
        base = {"NVMe": 95, "SSD": 85, "HDD": 32}.get((d or {}).get("tipo"), 50)
        parts = []
        if m.get("disco_mb_s") is not None:
            parts.append(_nota_disco_mb(m["disco_mb_s"]))
        if m.get("arquivos_ms") is not None:
            parts.append(_nota_arquivos(m["arquivos_ms"]))
        n = sum(parts) / len(parts) if parts else base
        if parts:
            n = 0.75 * n + 0.25 * base
        lv = pior_livre_pct(f)
        if lv is not None and lv < 10:
            n -= 15
        if d and d.get("saude") == "FALHA":
            n = min(n, 15)
        add("disco", "Disco", "%s%s" % ((d or {}).get("tipo", "?"), (" · %.0f MB/s" % m["disco_mb_s"]) if m.get("disco_mb_s") is not None else ""), n)
    if m.get("resposta_ms") is not None:
        add("resposta", "Tempo de resposta", "%.0f ms para abrir um processo" % m["resposta_ms"], _nota_resposta(m["resposta_ms"], win))
    if m.get("boot_s") is not None:
        add("boot", "Inicialização do sistema", "%.0f s até ficar pronto" % m["boot_s"], _nota_boot(m["boot_s"]))
    if f.get("inicializacao") is not None and not (f.get("so") or {}).get("live") and (m.get("boot_s") is not None or f.get("inicializacao")):
        n = len(f["inicializacao"])
        add("inicio", "Programas ao ligar", "%d programas iniciam com o sistema" % n, _nota_inicio(n))
    ne = nota_espaco(f)
    if ne:
        add("espaco", "Espaço livre", ne[1], ne[0])
    tw = sum(i["peso"] for i in itens) or 1
    geral = int(round(sum(i["nota"] * i["peso"] for i in itens) / tw)) if itens else 0
    return {"itens": itens, "geral": geral, "classe": classe(geral), "trofeu": trofeu(geral), "cobertura": round(tw * 100)}


# ----------------------------------------------------------------------------------------------
# sistema ideal e cenários
# ----------------------------------------------------------------------------------------------
PERFIS = [
    {"id": "win11", "nome": "Windows 11", "familia": "windows", "ram_idle": 3.2, "ram_min": 4, "boot": {"HDD": 110, "SSD": 17, "NVMe": 12}, "resp": 62, "programas": True},
    {"id": "win10", "nome": "Windows 10", "familia": "windows", "ram_idle": 2.4, "ram_min": 2, "boot": {"HDD": 85, "SSD": 15, "NVMe": 11}, "resp": 66, "programas": True},
    {"id": "zorin_core", "nome": "Zorin OS Core", "familia": "linux", "ram_idle": 1.5, "ram_min": 4, "boot": {"HDD": 45, "SSD": 11, "NVMe": 9}, "resp": 88, "programas": False},
    {"id": "zorin_lite", "nome": "Zorin OS Lite", "familia": "linux", "ram_idle": 0.8, "ram_min": 1, "boot": {"HDD": 35, "SSD": 9, "NVMe": 8}, "resp": 92, "programas": False},
    {"id": "mint_xfce", "nome": "Linux Mint XFCE", "familia": "linux", "ram_idle": 0.9, "ram_min": 2, "boot": {"HDD": 38, "SSD": 10, "NVMe": 8}, "resp": 90, "programas": False},
    {"id": "lubuntu", "nome": "Lubuntu", "familia": "linux", "ram_idle": 0.6, "ram_min": 1, "boot": {"HDD": 33, "SSD": 9, "NVMe": 8}, "resp": 93, "programas": False},
]


def _geracao_cpu(modelo):
    """(marca, geração) de nomes tipo 'Core i5-7200U' / 'Ryzen 5 2500U'. Heurística."""
    m = re.search(r"i[3579]-(\d{4,5})", modelo)
    if m:
        n = m.group(1)
        return "intel", int(n[:2]) if len(n) == 5 else int(n[0])
    m = re.search(r"Ryzen\s*\d\s*(?:PRO\s*)?(\d)(\d{3})", modelo, re.I)
    if m:
        return "amd", int(m.group(1))
    return None, None


def _compat_win11(f):
    prob = []
    so = f.get("so", {})
    if so.get("familia") == "windows" or True:
        if not so.get("uefi"):
            prob.append("BIOS em modo Legacy (precisa UEFI)")
        if so.get("familia") == "windows" and so.get("secure_boot") is False and so.get("uefi"):
            prob.append("Secure Boot desligado (pode ser só ativar na BIOS)")
        if so.get("familia") == "windows" and not so.get("tpm"):
            prob.append("sem TPM 2.0 detectado")
        elif so.get("tpm") and not str(so["tpm"]).startswith("2"):
            prob.append("TPM %s (precisa 2.0)" % so["tpm"])
    if (f.get("ram") or {}).get("total_gb", 0) < 3.7:
        prob.append("menos de 4 GB de RAM")
    d = disco_principal(f)
    if d and d.get("tam_gb", 999) < 60:
        prob.append("disco menor que 64 GB")
    marca, ger = _geracao_cpu(f.get("cpu", {}).get("modelo", ""))
    if marca == "intel" and ger and ger < 8:
        prob.append("processador Intel de %dª geração (Windows 11 oficial pede 8ª ou mais nova)" % ger)
    if marca == "amd" and ger and ger < 2:
        prob.append("processador AMD Ryzen antigo (pede Ryzen 2000 ou mais novo)")
    return prob


def _notas_projetadas(f, perfil, disco_tipo=None, ram_gb=None):
    """Nota estimada do sistema recém-instalado (sem bloat) nesta máquina."""
    m = f.get("medidas") or {}
    d = disco_principal(f) or {}
    tipo = disco_tipo or d.get("tipo") or "HDD"
    tot = ram_gb if ram_gb is not None else (f.get("ram") or {}).get("total_gb", 4)
    itens = []

    def add(i, n):
        itens.append((PESOS[i], max(0, min(100, n))))

    if m.get("cpu_ms") is not None:
        add("cpu", _nota_cpu(m["cpu_ms"]))
    add("ram", 0.6 * _nota_ram_gb(tot) + 0.4 * _nota_ram_livre(max(0.0, tot - perfil["ram_idle"])))
    base = {"NVMe": 95, "SSD": 85, "HDD": 36}.get(tipo, 50)
    if perfil["familia"] == "windows" and tipo == "HDD":
        base -= 10
    add("disco", base)
    add("resposta", perfil["resp"] - (14 if tipo == "HDD" else 0))
    add("boot", _nota_boot(perfil["boot"].get(tipo, 60)))
    add("inicio", 100)
    ne = nota_espaco(f)
    if ne:
        add("espaco", ne[0])
    tw = sum(p for p, _ in itens)
    return int(round(sum(p * n for p, n in itens) / tw))


def sistema_ideal(f):
    out = []
    tot = (f.get("ram") or {}).get("total_gb", 0)
    for p in PERFIS:
        motivos, ok = [], True
        if tot + 0.3 < p["ram_min"]:
            ok = False
            motivos.append("RAM abaixo do mínimo (%d GB)" % p["ram_min"])
        if p["id"] == "win11":
            pr = _compat_win11(f)
            if pr:
                ok = False
                motivos += pr
        if p["id"] == "win10":
            motivos.append("Suporte gratuito da Microsoft terminou em 14/10/2025 (só atualizações pagas ESU)")
        nota = _notas_projetadas(f, p)
        atual_win = (f.get("so") or {}).get("familia") == "windows"
        out.append({"id": p["id"], "nome": p["nome"], "familia": p["familia"], "nota": nota, "compativel": ok, "motivos": motivos,
                    "mantem_programas": p["programas"], "obs": "Mantém os programas Windows do cliente" if p["programas"] else "Pode exigir trocar/alternativas para programas Windows (Office, sistemas de loja, etc.)"})
    comp = [o for o in out if o["compativel"]]
    if comp:
        best = max(comp, key=lambda o: o["nota"])
        best["melhor_nota"] = True
        win = [o for o in comp if o["mantem_programas"]]
        if win:
            max(win, key=lambda o: o["nota"])["melhor_windows"] = True
    out.sort(key=lambda o: (not o["compativel"], -o["nota"]))
    return out


# ----------------------------------------------------------------------------------------------
# dicas e ações
# ----------------------------------------------------------------------------------------------
BLOAT = re.compile(r"spotify|teams|skype|discord|adobe.*(updater|acrobat|collab|genuine)|ccxprocess|creative cloud|jusched|java.*update|itunes|ipod|apple|steam|epic ?games|origin|ubisoft|riot|battle\.?net|zoom|webex|xbox|gamebar|cortana|yourphone|phoneexperience|hp ?(jumpstart|support|helper|odd)|dell ?(support|update|command)|lenovo ?(vantage|hotkey)|armoury|acer ?(care|quick)|mcafee|norton|avast|ccleaner|bonjour|quicktime|real ?player|winamp|torrent|bit ?comet|ask ?toolbar|babylon|conduit|opera ?(browser)? ?assistant|google ?update|onenote.*quick|ms ?office.*(startup|upload)|nitro|foxit.*(reader)?.*update|gotomeeting|dropbox ?update|msi ?(dragon|true ?color|center)", re.I)
OPCIONAL = re.compile(r"onedrive|dropbox|google ?drive|icloud|whatsapp|telegram|anydesk|teamviewer", re.I)
MANTER = re.compile(r"security|defender|antivirus|windows ?security|realtek|audio|touchpad|synaptics|elan|nvidia|igfx|intel.*graphics|rtk|bluetooth|wacom|fingerprint|backup|brightness|trackpoint|ctf|ime|input", re.I)


def classificar_inicio(e):
    s = (e.get("nome", "") + " " + e.get("comando", ""))
    if MANTER.search(s):
        return "manter"
    if BLOAT.search(s):
        return "dispensavel"
    if OPCIONAL.search(s):
        return "opcional"
    return "revisar"


def _id(prefixo, txt):
    return prefixo + ":" + hashlib.sha1(txt.encode("utf-8")).hexdigest()[:8]


def dicas(f, tam_temp_mb=None):
    out = []
    so = f.get("so", {})
    win = so.get("familia") == "windows"
    live = so.get("live")
    ram = f.get("ram", {})
    d = disco_principal(f) or {}
    tot = ram.get("total_gb", 0)

    def tip(i, titulo, det, ganho, aplicavel=False, acao=None, risco="nenhum", marcado=False, tipo="melhoria"):
        out.append({"id": i, "titulo": titulo, "detalhe": det, "ganho": ganho, "aplicavel": aplicavel, "acao": acao, "risco": risco, "marcado": marcado, "tipo": tipo})

    if d.get("saude") == "FALHA":
        tip("smart", "Disco com defeito: faça o backup AGORA", "O autodiagnóstico (SMART) do disco acusou falha. Qualquer uso pode piorar. Priorize o backup antes de qualquer outra coisa.", "crítico", tipo="alerta")
    if d.get("tipo") == "HDD":
        tip("ssd", "Trocar o HDD por um SSD", "É a melhoria que mais muda a sensação de velocidade (boot e abertura de programas). Hardware: precisa de compra e instalação.", "alto")
    slots_total, slots = ram.get("slots_total") or 0, ram.get("slots") or []
    usados = [s for s in slots if s.get("gb")]
    livres = max(0, slots_total - len(usados)) if slots_total else 0
    if tot and tot <= 4.2:
        if livres:
            tip("ram_add", "Adicionar memória RAM (há %d slot livre)" % livres, "Máquina com %.0f GB. Colocar um pente compatível leva a 8 GB ou mais." % tot, "alto")
        elif slots_total:
            tip("ram_troca", "Trocar o(s) pente(s) de RAM por maiores", "Máquina com %.0f GB e sem slot livre." % tot, "alto")
        else:
            tip("ram_add", "Ampliar a memória RAM", "Máquina com %.0f GB. (Slots não lidos: rode como administrador/root para ver.)" % tot, "alto")
    if len(usados) == 1 and slots_total >= 2 and tot < 16:
        tip("dual", "Colocar um segundo pente igual (dual channel)", "Com 2 pentes iguais a memória trabalha em dois canais e fica mais rápida, principalmente com vídeo integrado.", "médio")
    lv = pior_livre_pct(f)
    if lv is not None and lv < 15:
        tip("espaco", "Pouco espaço livre no disco (%.0f%%)" % lv, "Disco quase cheio deixa tudo lento. Libere espaço ou mova arquivos para outro disco (o backup já resolve isso).", "médio")
    b = f.get("bateria") or {}
    if b.get("saude_pct") is not None and b["saude_pct"] < 60:
        tip("bateria", "Bateria desgastada (%s%% da original)" % b["saude_pct"], "A bateria segura bem menos que a nova. Troca devolve a autonomia.", "médio")
    up = (f.get("medidas") or {}).get("uptime_h")
    if up and up > 24 * 14 and not live:
        tip("reiniciar", "Máquina ligada há %.0f dias sem reiniciar" % (up / 24.0), "Reiniciar libera memória e conclui atualizações pendentes.", "baixo")
    n = (f.get("medidas") or {}).get("prog_instalados")
    if n and n > 90 and win:
        tip("programas", "Muitos programas instalados (%d)" % n, "Revise com o cliente e desinstale o que não usa.", "médio")
    if win and so.get("nome", "").startswith("Windows 10"):
        tip("win10", "Windows 10 sem suporte gratuito", "A Microsoft encerrou as atualizações gratuitas em 14/10/2025. Considere Windows 11 (se a máquina aceitar) ou um Linux leve. Veja 'Sistema ideal'.", "médio", tipo="alerta")
    # ações aplicáveis
    if not live:
        for e in f.get("inicializacao", []):
            nv = classificar_inicio(e)
            e["nivel"] = nv
            if nv in ("manter",):
                continue
            ap = False
            acao = {"tipo": "startup_off", "nome": e.get("nome"), "local": e.get("local"), "arquivo": e.get("arquivo"), "usuario": e.get("usuario")}
            if win:
                loc = e.get("local", "")
                ap = bool(re.match(r"HK(LM|CU|U)", loc, re.I)) and bool(re.search(r"\\Run$", loc))
            else:
                ap = bool(e.get("arquivo"))
            tip(_id("startup", (e.get("nome") or "") + (e.get("local") or "")), "Não iniciar com o sistema: %s" % e.get("nome"), (e.get("comando") or "")[:140] + ("" if ap else "  (item de pasta/serviço: desative manualmente)"),
                "médio" if nv == "dispensavel" else "baixo", ap, acao if ap else None, "baixo", marcado=(nv == "dispensavel" and ap), tipo="inicio")
        if win:
            gpu_int = any(re.search(r"Intel|UHD|HD Graphics|Vega|Radeon\(TM\) Graphics", g.get("nome", ""), re.I) for g in f.get("gpu", []))
            if tot <= 8.2 or gpu_int:
                tip("visual", "Reduzir efeitos visuais (transparência e animações)", "Desliga transparência e animações do Windows. Libera GPU/CPU em máquinas simples. Vale após sair e entrar de novo na conta.", "baixo", True, {"tipo": "visual"}, "baixo", marcado=True, tipo="visual")
            if tam_temp_mb and tam_temp_mb > 800:
                tip("temp", "Limpar arquivos temporários (%.1f GB)" % (tam_temp_mb / 1024.0), "Apaga só arquivos temporários com mais de 3 dias da pasta Temp do usuário. Não mexe em documentos.", "baixo", True, {"tipo": "temp"}, "baixo", marcado=True, tipo="limpeza")
    return out


def tamanho_temp_mb(limite=20000):
    if not IS_WIN:
        return None
    base = tempfile.gettempdir()
    tot = 0
    n = 0
    for dp, _, fs in os.walk(base):
        for fn in fs:
            n += 1
            if n > limite:
                return tot / 1048576.0
            try:
                tot += os.path.getsize(os.path.join(dp, fn))
            except OSError:
                pass
    return tot / 1048576.0


# ----------------------------------------------------------------------------------------------
# cenários ("e se...") e análise final
# ----------------------------------------------------------------------------------------------
def cenarios(f, dl):
    base = pontuar(f)["geral"]
    out = []
    # otimizar
    g = copy.deepcopy(f)
    marc = {e.get("nome") for e in dl if e["tipo"] == "inicio" and e["marcado"] and e.get("acao")}
    g["inicializacao"] = [e for e in g.get("inicializacao", []) if e.get("nome") not in {x["acao"]["nome"] for x in dl if x["tipo"] == "inicio" and x["marcado"] and x.get("acao")}]
    if g["medidas"].get("boot_s"):
        g["medidas"]["boot_s"] = round(g["medidas"]["boot_s"] * (0.85 if len(g["inicializacao"]) < len(f.get("inicializacao", [])) else 1), 1)
    n_otim = pontuar(g)["geral"]
    if n_otim > base:
        out.append({"id": "otimizar", "nome": "Aplicar as otimizações marcadas", "nota": n_otim, "delta": n_otim - base, "tipo": "software"})
    d = disco_principal(f) or {}
    if d.get("tipo") == "HDD":
        h = copy.deepcopy(g)
        h["discos"] = [dict(x, tipo="SSD") for x in h["discos"]]
        h["medidas"].update({"disco_mb_s": 450, "arquivos_ms": 0.4})
        if h["medidas"].get("boot_s"):
            h["medidas"]["boot_s"] = round(min(h["medidas"]["boot_s"], 25), 1)
        if h["medidas"].get("resposta_ms"):
            h["medidas"]["resposta_ms"] = round(h["medidas"]["resposta_ms"] * 0.6, 1)
        out.append({"id": "ssd", "nome": "Otimizar + trocar HDD por SSD", "nota": pontuar(h)["geral"], "delta": pontuar(h)["geral"] - base, "tipo": "hardware"})
        g2 = h
    else:
        g2 = g
    tot = (f.get("ram") or {}).get("total_gb", 0)
    if tot and tot < 7.5:
        r = copy.deepcopy(g2)
        r["ram"]["total_gb"] = 8.0
        r["ram"]["livre_gb"] = max(r["ram"].get("livre_gb", 0), 8.0 - (tot - (f["ram"].get("livre_gb") or 0)))
        out.append({"id": "ram8", "nome": "Tudo acima + subir para 8 GB de RAM" if d.get("tipo") == "HDD" else "Otimizar + subir para 8 GB de RAM", "nota": pontuar(r)["geral"], "delta": pontuar(r)["geral"] - base, "tipo": "hardware"})
    return base, out


def analise(f, tam_temp_mb=None):
    dl = dicas(f, tam_temp_mb)
    base, cen = cenarios(f, dl)
    p = pontuar(f)
    pes = [x for x in f.get("pesados", []) if x["ram_mb"] >= 300 or (f["ram"].get("total_gb") and x["ram_mb"] / 1024.0 >= 0.1 * f["ram"]["total_gb"])]
    ini = f.get("inicializacao", [])
    for e in ini:
        e.setdefault("nivel", classificar_inicio(e))
    return {"nota": p, "cenarios": cen, "sistemas": sistema_ideal(f), "dicas": dl, "pesados_n": len(pes), "pesados_limite": "≥ 300 MB ou ≥ 10% da RAM",
            "inicio_n": len(ini), "inicio_dispensavel": sum(1 for e in ini if e["nivel"] == "dispensavel")}


# ----------------------------------------------------------------------------------------------
# armazenamento no pendrive (pasta maquinas/)
# ----------------------------------------------------------------------------------------------
def pasta(mid):
    return os.path.join(STORE, safe_name(mid))


def _json_atomico(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def meta_ler(mid):
    try:
        with open(os.path.join(pasta(mid), "meta.json"), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def meta_set(mid, **kw):
    os.makedirs(pasta(mid), exist_ok=True)
    m = meta_ler(mid)
    m.update({k: v for k, v in kw.items() if v is not None})
    m.setdefault("codigo", mid)
    m.setdefault("criado", datetime.datetime.now().strftime("%Y-%m-%d %H:%M"))
    _json_atomico(os.path.join(pasta(mid), "meta.json"), m)
    return m


def meta_ids(mid, ids):
    """Guarda (e une) os identificadores de hardware, para reconhecer a máquina mesmo trocando nome, disco ou sistema."""
    m = meta_ler(mid)
    a = m.get("ids") or {"uuid": "", "serial": "", "macs": []}
    novo = {"uuid": a.get("uuid") or ids.get("uuid", ""), "serial": a.get("serial") or ids.get("serial", ""),
            "macs": sorted(set(a.get("macs") or []) | set(ids.get("macs") or []))}
    meta_set(mid, ids=novo)


MODELOS_MAC = {
    "Mac14,2": "MacBook Air (M2, 2022)", "Mac14,15": 'MacBook Air 15" (M2, 2023)', "Mac15,12": 'MacBook Air 13" (M3, 2024)', "Mac15,13": 'MacBook Air 15" (M3, 2024)',
    "Mac14,7": 'MacBook Pro 13" (M2, 2022)', "Mac14,5": 'MacBook Pro 14" (M2 Max, 2023)', "Mac14,9": 'MacBook Pro 14" (M2 Pro, 2023)', "Mac14,6": 'MacBook Pro 16" (M2 Max, 2023)', "Mac14,10": 'MacBook Pro 16" (M2 Pro, 2023)',
    "MacBookAir10,1": "MacBook Air (M1, 2020)", "MacBookPro17,1": 'MacBook Pro 13" (M1, 2020)', "MacBookPro18,3": 'MacBook Pro 14" (M1 Pro, 2021)', "MacBookPro18,4": 'MacBook Pro 14" (M1 Max, 2021)',
    "MacBookPro18,1": 'MacBook Pro 16" (M1 Pro, 2021)', "MacBookPro18,2": 'MacBook Pro 16" (M1 Max, 2021)', "Macmini9,1": "Mac mini (M1, 2020)", "Mac14,3": "Mac mini (M2, 2023)",
    "iMac21,1": 'iMac 24" (M1, 2021)', "iMac21,2": 'iMac 24" (M1, 2021)', "MacBookAir9,1": "MacBook Air (Intel, 2020)", "MacBookAir8,1": "MacBook Air (Intel, 2018)",
}


def modelo_comercial(f):
    mq = (f or {}).get("maquina") or {}
    if mq.get("nome_comercial"):
        return mq["nome_comercial"]
    if (f or {}).get("so", {}).get("familia") == "mac" and mq.get("modelo") in MODELOS_MAC:
        return MODELOS_MAC[mq["modelo"]]
    return ((mq.get("fabricante") or "") + " " + (mq.get("modelo") or "")).strip() or (f or {}).get("host", "")


def nome_exibicao(mid, f=None):
    return meta_ler(mid).get("nome") or modelo_comercial(f or {}) or mid


def salvar_ficha(f, fase="antes"):
    d = pasta(f["mid"])
    os.makedirs(d, exist_ok=True)
    f = dict(f, fase=fase)
    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    with open(os.path.join(d, "ficha-%s-%s.json" % (ts, fase)), "w", encoding="utf-8") as fh:
        json.dump(f, fh, ensure_ascii=False, indent=1)
    meta_ids(f["mid"], f.get("ids") or {})
    p = pontuar(f)
    hist_add(f["mid"], "ficha" if fase == "antes" else "ficha_depois", "Ficha %s: nota %d (%s)" % ("coletada" if fase == "antes" else "após melhorias", p["geral"], p["classe"]),
             {"nota": p["geral"], "fase": fase, "arquivo": "ficha-%s-%s.json" % (ts, fase), "trofeu": p["trofeu"]["nivel"]})
    return f


def fichas_info(mid):
    out = []
    for n in listar_fichas(mid):
        f = ler_ficha(mid, n)
        if not f:
            continue
        p = pontuar(f)
        out.append({"arquivo": n, "quando": f.get("quando", ""), "fase": f.get("fase", "antes"), "nota": p["geral"], "classe": p["classe"], "nivel": p["trofeu"]["nivel"], "cobertura": p["cobertura"]})
    return out


def _lista_nomes(f):
    return sorted({(e.get("nome") or "") for e in (f.get("inicializacao") or []) if e.get("nome")})


def comparar(mid, a, b):
    """Diferença entre duas análises (a = referência, b = comparada). Sempre diz o que mudou, ou que nada mudou."""
    fa, fb = ler_ficha(mid, a), ler_ficha(mid, b)
    if not fa or not fb:
        raise ValueError("Análise não encontrada.")
    pa, pb = pontuar(fa), pontuar(fb)
    ia = {i["id"]: i for i in pa["itens"]}
    ib = {i["id"]: i for i in pb["itens"]}
    itens = []
    for k in PESOS:
        x, y = ia.get(k), ib.get(k)
        if not x and not y:
            continue
        itens.append({"id": k, "nome": (x or y)["nome"], "a": x["nota"] if x else None, "b": y["nota"] if y else None,
                      "delta": (y["nota"] - x["nota"]) if x and y else None, "va": x["valor"] if x else "não medido", "vb": y["valor"] if y else "não medido"})
    mudancas = []

    def cmp(rot, va, vb):
        if va != vb:
            mudancas.append({"rotulo": rot, "a": "—" if va in (None, "") else str(va), "b": "—" if vb in (None, "") else str(vb)})
    cmp("Memória (GB)", (fa.get("ram") or {}).get("total_gb"), (fb.get("ram") or {}).get("total_gb"))
    cmp("Processador", (fa.get("cpu") or {}).get("modelo"), (fb.get("cpu") or {}).get("modelo"))
    cmp("Sistema", ((fa.get("so") or {}).get("nome", "") + " " + (fa.get("so") or {}).get("versao", "")).strip(), ((fb.get("so") or {}).get("nome", "") + " " + (fb.get("so") or {}).get("versao", "")).strip())
    cmp("Discos", ", ".join("%s %s GB" % (d.get("tipo"), d.get("tam_gb")) for d in fa.get("discos") or []), ", ".join("%s %s GB" % (d.get("tipo"), d.get("tam_gb")) for d in fb.get("discos") or []))
    va, vb = volume_principal(fa), volume_principal(fb)
    cmp("Espaço livre (GB)", va and va.get("livre_gb"), vb and vb.get("livre_gb"))
    cmp("Programas instalados", (fa.get("medidas") or {}).get("prog_instalados"), (fb.get("medidas") or {}).get("prog_instalados"))
    cmp("Processos em execução", (fa.get("medidas") or {}).get("processos"), (fb.get("medidas") or {}).get("processos"))
    na, nb = set(_lista_nomes(fa)), set(_lista_nomes(fb))
    return {"a": {"arquivo": a, "quando": fa.get("quando"), "fase": fa.get("fase"), "nota": pa["geral"], "classe": pa["classe"], "nivel": pa["trofeu"]["nivel"]},
            "b": {"arquivo": b, "quando": fb.get("quando"), "fase": fb.get("fase"), "nota": pb["geral"], "classe": pb["classe"], "nivel": pb["trofeu"]["nivel"]},
            "delta": pb["geral"] - pa["geral"], "itens": itens, "mudancas": mudancas, "inicio_entrou": sorted(nb - na), "inicio_saiu": sorted(na - nb),
            "mesma_cobertura": pa["cobertura"] == pb["cobertura"], "nada_mudou": (pa["geral"] == pb["geral"] and not mudancas and na == nb and all((i["delta"] in (0, None)) for i in itens))}


def apagar_maquina(mid):
    """Remove do pendrive tudo desta máquina (fichas, histórico, desfazer). O registro de consentimento fica."""
    import shutil as _sh
    d = pasta(mid)
    if os.path.isdir(d):
        _sh.rmtree(d)
    return True


def listar_fichas(mid):
    d = pasta(mid)
    if not os.path.isdir(d):
        return []
    return sorted(x for x in os.listdir(d) if x.startswith("ficha-") and x.endswith(".json"))


def ler_ficha(mid, nome):
    try:
        with open(os.path.join(pasta(mid), os.path.basename(nome)), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def hist_add(mid, tipo, resumo, extra=None):
    d = pasta(mid)
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, "historico.json")
    try:
        h = json.load(open(p, encoding="utf-8"))
    except (OSError, ValueError):
        h = []
    h.append({"quando": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"), "tipo": tipo, "resumo": resumo, "extra": extra or {}})
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(h, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, p)


def hist_get(mid):
    try:
        return json.load(open(os.path.join(pasta(mid), "historico.json"), encoding="utf-8"))
    except (OSError, ValueError):
        return []


def visao(mid):
    """Tudo que a Home precisa para uma máquina: ficha 'antes' mais antiga útil, a mais recente, análise e histórico."""
    nomes = listar_fichas(mid)
    if not nomes:
        return None
    fichas = [ler_ficha(mid, n) for n in nomes]
    fichas = [x for x in fichas if x]
    if not fichas:
        return None
    antes = next((x for x in fichas if x.get("fase") == "antes"), fichas[0])
    ultima = fichas[-1]
    tm = tamanho_temp_mb() if (mid == machine_id_cache()) else None
    a = analise(ultima, tm)
    out = {"mid": mid, "antes": {"quando": antes["quando"], "nota": pontuar(antes)["geral"], "classe": pontuar(antes)["classe"]},
           "ultima": ultima, "analise": a, "historico": hist_get(mid), "n_fichas": len(fichas), "fase_ultima": ultima.get("fase", "antes"),
           "meta": meta_ler(mid), "nome": nome_exibicao(mid, ultima), "modelo": modelo_comercial(ultima), "fichas": fichas_info(mid)}
    if len(fichas) > 1:
        ant = pontuar(fichas[-2])["geral"]
        out["variacao"] = pontuar(ultima)["geral"] - ant
    if ultima is not antes:
        out["depois"] = {"quando": ultima["quando"], "nota": pontuar(ultima)["geral"], "classe": pontuar(ultima)["classe"]}
    return out


def machine_id_cache():
    if "v" not in _MID:
        _MID["v"] = machine_id_rapido()
    return _MID["v"]


def listar_maquinas():
    out = []
    if not os.path.isdir(STORE):
        return out
    for mid in sorted(os.listdir(STORE)):
        nomes = listar_fichas(mid)
        if not nomes:
            continue
        ult = ler_ficha(mid, nomes[-1]) or {}
        p = pontuar(ult) if ult else {"geral": 0, "classe": "", "trofeu": {"nivel": 1}}
        mt = meta_ler(mid)
        out.append({"mid": mid, "nome": nome_exibicao(mid, ult), "host": ult.get("host", mid), "modelo": modelo_comercial(ult),
                    "quando": ult.get("quando", ""), "nota": p["geral"], "classe": p["classe"], "nivel": p["trofeu"]["nivel"], "eventos": len(hist_get(mid)),
                    "analises": len(nomes), "dono": mt.get("dono", ""), "terceiro_nome": mt.get("terceiro_nome", ""), "atual": mid == machine_id_cache()})
    return out


# ----------------------------------------------------------------------------------------------
# aplicar / desfazer
# ----------------------------------------------------------------------------------------------
def _undo_path(mid):
    return os.path.join(pasta(mid), "desfazer.json")


def _undo_load(mid):
    try:
        return json.load(open(_undo_path(mid), encoding="utf-8"))
    except (OSError, ValueError):
        return []


def _undo_save(mid, lst):
    os.makedirs(pasta(mid), exist_ok=True)
    json.dump(lst, open(_undo_path(mid), "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def _ps_env(**kw):
    e = dict(os.environ)
    for k, v in kw.items():
        e["BKP_" + k.upper()] = str(v if v is not None else "")
    return e


def _startup_win(acao):
    loc = acao.get("local") or ""
    nome = acao.get("nome") or ""
    if re.match(r"HKLM", loc, re.I):
        hive = "HKLM:"
    elif re.match(r"HKU\\", loc, re.I) or re.match(r"HKCU", loc, re.I):
        hive = "HKCU:"
        if re.match(r"HKU\\", loc, re.I):
            sid = ps("[System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value", 15).strip()
            if sid and sid.lower() not in loc.lower():
                return False, "Pertence a outro usuário do Windows: desative com ele logado.", None
    else:
        return False, "Local não suportado.", None
    kind = "Run32" if re.search(r"WOW6432Node", loc, re.I) else "Run"
    script = r"""
$p=$env:BKP_HIVE+'\Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\'+$env:BKP_KIND
if(-not (Test-Path $p)){New-Item -Path $p -Force | Out-Null}
$prev=$null; try{$prev=(Get-ItemProperty -Path $p -Name $env:BKP_NAME -ErrorAction Stop).($env:BKP_NAME)}catch{}
Set-ItemProperty -Path $p -Name $env:BKP_NAME -Value ([byte[]](3,0,0,0,0,0,0,0,0,0,0,0)) -Type Binary
$ok=(Get-ItemProperty -Path $p -Name $env:BKP_NAME).($env:BKP_NAME)[0] -eq 3
@{ok=$ok;prev=$prev} | ConvertTo-Json -Compress
"""
    out = ps(script, 30, _ps_env(hive=hive, kind=kind, name=nome))
    try:
        j = json.loads(out[out.find("{"):])
    except ValueError:
        return False, "O Windows não respondeu.", None
    if not j.get("ok"):
        return False, "Não consegui gravar a configuração.", None
    return True, "Desativado (reversível).", {"tipo": "startup_win", "hive": hive, "kind": kind, "nome": nome, "prev": j.get("prev")}


def _startup_linux(acao):
    fn = acao.get("arquivo")
    dr = os.path.join(user_home(), ".config", "autostart")
    os.makedirs(dr, exist_ok=True)
    p = os.path.join(dr, fn)
    prev = None
    if os.path.exists(p):
        prev = open(p, encoding="utf-8", errors="replace").read()
        txt = prev.rstrip("\n") + "\nHidden=true\n"
    else:
        txt = "[Desktop Entry]\nType=Application\nName=%s\nHidden=true\n" % (acao.get("nome") or fn)
    open(p, "w", encoding="utf-8").write(txt)
    return True, "Desativado (reversível).", {"tipo": "startup_linux", "path": p, "prev": prev}


def _visual_win():
    script = r"""
$r=@{}
$k1='HKCU:\Software\Microsoft\Windows\CurrentVersion\Themes\Personalize'
$k2='HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced'
$k3='HKCU:\Control Panel\Desktop\WindowMetrics'
function G($k,$n){try{(Get-ItemProperty -Path $k -Name $n -ErrorAction Stop).$n}catch{$null}}
$r.t=G $k1 'EnableTransparency'; $r.a=G $k2 'TaskbarAnimations'; $r.m=G $k3 'MinAnimate'
if(-not (Test-Path $k1)){New-Item $k1 -Force|Out-Null}
Set-ItemProperty -Path $k1 -Name 'EnableTransparency' -Value 0 -Type DWord
Set-ItemProperty -Path $k2 -Name 'TaskbarAnimations' -Value 0 -Type DWord
Set-ItemProperty -Path $k3 -Name 'MinAnimate' -Value '0' -Type String
$r | ConvertTo-Json -Compress
"""
    out = ps(script, 30)
    try:
        j = json.loads(out[out.find("{"):])
    except ValueError:
        return False, "O Windows não respondeu.", None
    return True, "Efeitos reduzidos (vale após sair e entrar na conta).", {"tipo": "visual_win", "prev": j}


def _temp_win():
    base = tempfile.gettempdir()
    lim = time.time() - 3 * 86400
    n = tot = 0
    for dp, _, fs in os.walk(base):
        for fn in fs:
            p = os.path.join(dp, fn)
            try:
                if os.path.getmtime(p) < lim:
                    s = os.path.getsize(p)
                    os.remove(p)
                    n += 1
                    tot += s
            except OSError:
                pass
    return True, "Removidos %d arquivos (%.0f MB)." % (n, tot / 1048576.0), None


def aplicar(mid, ids, ficha):
    """Aplica as dicas marcadas. Retorna lista de resultados; guarda como desfazer."""
    dl = {d["id"]: d for d in dicas(ficha, tamanho_temp_mb())}
    undo = _undo_load(mid)
    res = []
    for i in ids:
        d = dl.get(i)
        if not d or not d.get("aplicavel") or not d.get("acao"):
            res.append({"id": i, "ok": False, "msg": "Ação indisponível."})
            continue
        a = d["acao"]
        try:
            if a["tipo"] == "startup_off":
                ok, msg, u = _startup_win(a) if IS_WIN else _startup_linux(a)
            elif a["tipo"] == "visual" and IS_WIN:
                ok, msg, u = _visual_win()
            elif a["tipo"] == "temp" and IS_WIN:
                ok, msg, u = _temp_win()
            else:
                ok, msg, u = False, "Não suportado neste sistema.", None
        except Exception as e:
            ok, msg, u = False, "Erro: %s" % e, None
        if ok and u:
            undo.append(dict(u, quando=datetime.datetime.now().strftime("%Y-%m-%d %H:%M"), titulo=d["titulo"]))
        res.append({"id": i, "titulo": d["titulo"], "ok": ok, "msg": msg})
    _undo_save(mid, undo)
    okn = sum(1 for r in res if r["ok"])
    hist_add(mid, "otimizacao", "Melhorias aplicadas: %d de %d" % (okn, len(res)), {"itens": [r.get("titulo") for r in res if r["ok"]]})
    return res


def desfazer(mid):
    undo = _undo_load(mid)
    n = 0
    for u in reversed(undo):
        try:
            if u["tipo"] == "startup_linux":
                if u.get("prev") is None:
                    os.remove(u["path"])
                else:
                    open(u["path"], "w", encoding="utf-8").write(u["prev"])
                n += 1
            elif u["tipo"] == "startup_win" and IS_WIN:
                bytes_ = u.get("prev")
                script = r"""
$p=$env:BKP_HIVE+'\Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\'+$env:BKP_KIND
if($env:BKP_PREV){Set-ItemProperty -Path $p -Name $env:BKP_NAME -Value ([byte[]]($env:BKP_PREV -split ',')) -Type Binary}else{Remove-ItemProperty -Path $p -Name $env:BKP_NAME}
"""
                ps(script, 30, _ps_env(hive=u["hive"], kind=u["kind"], name=u["nome"], prev=",".join(str(x) for x in bytes_) if bytes_ else ""))
                n += 1
            elif u["tipo"] == "visual_win" and IS_WIN:
                pv = u.get("prev") or {}
                script = r"""
function S($k,$n,$v,$t){if($v -eq $null){Remove-ItemProperty -Path $k -Name $n -ErrorAction SilentlyContinue}else{Set-ItemProperty -Path $k -Name $n -Value $v -Type $t}}
S 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Themes\Personalize' 'EnableTransparency' $env:BKP_T 'DWord'
S 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced' 'TaskbarAnimations' $env:BKP_A 'DWord'
S 'HKCU:\Control Panel\Desktop\WindowMetrics' 'MinAnimate' $env:BKP_M 'String'
"""
                ps(script, 30, _ps_env(t=pv.get("t") if pv.get("t") is not None else "", a=pv.get("a") if pv.get("a") is not None else "", m=pv.get("m") if pv.get("m") is not None else ""))
                n += 1
        except Exception:
            pass
    _undo_save(mid, [])
    if n:
        hist_add(mid, "desfazer", "Melhorias desfeitas: %d" % n)
    return n


def pode_desfazer(mid):
    return len(_undo_load(mid))
