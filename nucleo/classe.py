# -*- coding: utf-8 -*-
"""Tipos de arquivo: uma tabela só para o Backup e o Gerenciamento de dados.

Cada classe junta as extensões e o que ela vira em cada lado:
  - "backup": a categoria do backup (e a pasta no modo Ordenado). None = o backup não tem categoria própria para ela
    e segue a regra dele (compactado, tipo não reconhecido…);
  - "dados":  o rótulo no Gerenciamento de dados (a coluna cat do índice);
  - "faixa":  a faixa do cockpit do disco (igual nas duas telas);
  - "ico":    o ícone (o mesmo que a tela usa para a categoria do backup).
Além da extensão, dois eixos valem para os dois lados:
  - FAIXAS: o que é o dado (Fotos, Vídeos, …, Apps instalados, Caches, Dados do Sistema, OS), como o Ajustes do Mac;
  - GRUPOS: o que fazer com ele (Pessoal, Dados de programas, Cache temporário, Instaladores, Sistema, Só na nuvem, Bloqueado).
Antes de 2026-10-27 cada módulo tinha a sua tabela e 78 extensões divergiam."""
import os
import re

CLASSES = {
    "fotos": {"ext": ".jpg .jpeg .png .heic .heif .gif .bmp .tif .tiff .webp .raw .cr2 .nef .arw .dng",
              "backup": "Fotos", "dados": "Fotos", "faixa": "fotos", "ico": "🖼️"},
    "videos": {"ext": ".mp4 .mov .avi .mkv .wmv .3gp .mpg .mpeg .m4v .flv .webm .mts .prproj_proxy",
               "backup": "Videos", "dados": "Vídeos", "faixa": "videos", "ico": "🎬"},
    "audios": {"ext": ".mp3 .wav .m4a .aac .flac .ogg .opus .wma .amr .aiff",
               "backup": "Audios", "dados": "Áudios", "faixa": "audios", "ico": "🎵"},
    "documentos": {"ext": ".pdf .doc .docx .docm .dotx .xls .xlsx .xlsm .xlsb .ppt .pptx .pps .ppsx .txt .odt .ods .odp .csv .rtf .one",
                   "backup": "Documentos", "dados": "Documentos e projetos", "faixa": "documentos", "ico": "📄"},
    "projetos": {"ext": ".psd .ai .cdr .indd .dwg .dxf .skp .xcf .svg .prproj .aep .blend .sketch .fig .drp .fcp",
                 "backup": "Projetos", "dados": "Documentos e projetos", "faixa": "documentos", "ico": "📐"},
    "email": {"ext": ".pst .eml .msg .mbox .vcf", "backup": "Email_Contatos", "dados": "E-mails e contatos", "faixa": "documentos", "ico": "✉️"},
    "senhas": {"ext": ".kdbx .kdb .pfx .p12", "backup": "Contas_Senhas", "dados": "Contas e senhas", "faixa": "documentos", "ico": "🔑"},
    "instaladores": {"ext": ".exe .msi .msp .appimage .deb .rpm .dmg .pkg .apk",
                     "backup": "Programas", "dados": "Instaladores e imagens de disco", "faixa": "outros", "ico": "⚙️"},
    "scripts": {"ext": ".jar .bat .cmd .ps1 .vbs", "backup": "Programas", "dados": "Outros", "faixa": "outros", "ico": "⚙️"},
    "imagens_disco": {"ext": ".iso .img", "backup": None, "dados": "Instaladores e imagens de disco", "faixa": "outros", "ico": "💿"},
    "compactados": {"ext": ".zip .rar .7z .tar .gz .tgz .bz2 .xz", "backup": None, "dados": "Compactados", "faixa": "outros", "ico": "🗜️"},
    "maquinas_virtuais": {"ext": ".vmdk .vdi .qcow2 .vhd .vhdx .vmwarevm .ova", "backup": None, "dados": "Máquinas virtuais", "faixa": "outros", "ico": "🖥️"},
    "configuracoes": {"ext": ".ini .log .lnk .url .desktop .cfg .conf .reg", "backup": "Configuracoes", "dados": "Outros", "faixa": "dados", "ico": "🛠️"},
}
# o backup trata compactado à parte ("Arquivo compactado": vai marcado, na pasta Outros), mas usa a mesma lista
COMPACTADOS = frozenset(CLASSES["compactados"]["ext"].split())

POR_EXT = {}
for _k, _c in CLASSES.items():
    for _x in _c["ext"].split():
        if _x in POR_EXT:
            raise ValueError("extensão repetida em classe.py: %s (%s e %s)" % (_x, POR_EXT[_x], _k))
        POR_EXT[_x] = _k

# ---- faixas do cockpit do disco: a ordem é a da barra; Livre não é faixa (é o que sobra) ----
FAIXAS = (("fotos", "Fotos", "#5aa9ff"), ("videos", "Vídeos", "#a78bfa"), ("audios", "Áudios", "#f472b6"), ("documentos", "Documentos", "#3fb27f"),
          ("outros", "Outros arquivos", "#9aa4b5"), ("apps", "Apps instalados", "#22b8cf"), ("caches", "Caches e temporários", "#e8a33d"),
          ("dados", "Dados do Sistema", "#6b7280"), ("os", "OS", "#3b4252"))
FAIXA_NOME = {k: n for k, n, _ in FAIXAS}
# faixas que existem dentro das pastas dos usuários (o índice soma por pasta); apps, os e o resto vêm da medição fora delas
FAIXAS_USUARIO = ("fotos", "videos", "audios", "documentos", "outros", "apps", "caches", "dados")

# ---- grupos: o que fazer com o arquivo (coluna "Grupo" e filtro nas duas telas) ----
GRUPOS = (("Pessoal", "O que a pessoa criou ou guardou: vai no backup e não se limpa sem perguntar."),
          ("Dados de programas", "Dados e configurações dos programas: só se o cliente precisar."),
          ("Cache temporário", "O sistema e os programas recriam sozinhos."),
          ("Instaladores", "Instaladores e imagens de disco: depois de usados, costumam sobrar."),
          ("Sistema", "Arquivos do sistema em uso ou recriados sozinhos."),
          ("Só na nuvem", "Estão na nuvem e não ocupam espaço aqui: o programa não baixa nem mexe."),
          ("Bloqueado", "Protegidos (credenciais, bibliotecas, em uso): só para ver."))

# pastas que se recriam sozinhas (o backup lista como puladas e nunca copia; no Gerenciamento contam como cache)
CACHE_DIRS = frozenset({"cache", "cache2", "code cache", "gpucache", "grshadercache", "shadercache", "temp", "tmp", "inetcache", "crashdumps",
                        "d3dscache", "webcache", "service worker", "cachestorage", "startupcache", "minidumps", "node_modules", ".cache", ".thumbnails",
                        ".npm", ".nvm", ".cargo", ".rustup", ".gradle", ".m2", ".steam", "snap", ".snap"})
PASTAS_CACHE = CACHE_DIRS | {"caches", "logs", ".trash", ".trashes", "$recycle.bin"}
# arquivos do sistema que aparecem nas pastas (o backup não leva; no Gerenciamento são do grupo Sistema)
SISTEMA_NOME = re.compile(r"^(ntuser.*|desktop\.ini|thumbs\.db|iconcache\.db|pagefile\.sys|hiberfil\.sys|swapfile\.sys|\.ds_store|\.directory)$", re.I)

# coluna "Tipo" das listas (e a busca por tipo): o que a pessoa reconhece, não a extensão
TIPO_EXT = {}
for _t, _e in (("PDF", ".pdf"), ("Word", ".doc .docx .docm .dotx"), ("Documento", ".odt .rtf"), ("Planilha", ".xls .xlsx .xlsm .xlsb .ods .csv"),
               ("Apresentação", ".ppt .pptx .pps .ppsx .odp"), ("Texto", ".txt .md"), ("OneNote", ".one"), ("E-mail", ".pst .eml .msg .mbox"),
               ("Contato", ".vcf"), ("Compactado", " ".join(sorted(COMPACTADOS)))):
    for _x in _e.split():
        TIPO_EXT[_x] = _t
TIPO_CLASSE = {"fotos": "Imagem", "videos": "Vídeo", "audios": "Áudio"}

# categorias do backup -> faixa e grupo (as do backup que não vêm da extensão)
BACKUP_FAIXA = {"Fotos": "fotos", "Videos": "videos", "Audios": "audios", "Documentos": "documentos", "Projetos": "documentos", "Email_Contatos": "documentos",
                "Contas_Senhas": "documentos", "Conversas": "documentos", "Navegadores": "documentos", "Outros": "outros", "Programas": "outros",
                "Extras": "outros", "Temporarios": "caches", "Dados_de_apps": "dados", "Ocultos": "dados", "Configuracoes": "dados", "Sistemas": "apps",
                "Nuvem": None}
BACKUP_GRUPO = {"Temporarios": "Cache temporário", "Programas": "Instaladores", "Dados_de_apps": "Dados de programas", "Ocultos": "Dados de programas",
                "Configuracoes": "Dados de programas", "Sistemas": "Dados de programas", "Nuvem": "Só na nuvem"}


def ext_de(nome):
    return os.path.splitext(nome.lower())[1]


def classe(nome):
    """A chave da classe pela extensão do nome, ou None."""
    return POR_EXT.get(ext_de(nome))


def exts(lado, valor):
    """Extensões cujo destino em `lado` ("backup" ou "dados") é `valor`."""
    return {x for k, c in CLASSES.items() if c[lado] == valor for x in c["ext"].split()}


def tipo_de(nome):
    ext = ext_de(nome)
    return TIPO_EXT.get(ext) or TIPO_CLASSE.get(POR_EXT.get(ext, "")) or (ext[1:].upper() if ext else "Arquivo")


def contexto(partes):
    """De onde o arquivo é, pelas pastas acima dele (a partir da pasta do usuário): "cache", "dados", "apps" ou ""."""
    low = [p.lower() for p in partes if p]
    if any(p in PASTAS_CACHE for p in low):
        return "cache"
    if low and (low[0] in ("library", "appdata") or low[0].startswith(".")):
        return "dados"
    if low and low[0] == "applications":
        return "apps"
    return ""


def faixa_arquivo(nome, ctx=""):
    """Faixa do cockpit de um arquivo: o lugar manda (cache, dados de programa, apps) e, fora disso, a extensão."""
    if ctx == "cache":
        return "caches"
    if ctx in ("dados", "apps"):
        return ctx
    if SISTEMA_NOME.match(nome):
        return "dados"
    k = classe(nome)
    return CLASSES[k]["faixa"] if k else "outros"


def grupo_arquivo(nome, ctx="", trava=False, nuvem=False):
    """Grupo de um arquivo, na ordem de prioridade: Bloqueado, Só na nuvem, Cache, Instaladores, Dados de programas, Sistema, Pessoal."""
    if trava:
        return "Bloqueado"
    if nuvem:
        return "Só na nuvem"
    if ctx == "cache":
        return "Cache temporário"
    k = classe(nome)
    if k in ("instaladores", "imagens_disco"):
        return "Instaladores"
    if ctx in ("dados", "apps") or k == "configuracoes":
        return "Dados de programas"
    if SISTEMA_NOME.match(nome):
        return "Sistema"
    return "Pessoal"


def grupo_backup(cat, act=""):
    """Grupo de um arquivo do backup, pela categoria dele (e "ignorar" = arquivo do sistema)."""
    if act == "ignorar":
        return "Sistema"
    return BACKUP_GRUPO.get(cat, "Pessoal")


def para_tela():
    """O que a tela precisa (/api/classes): ícone, faixa e grupo de cada categoria, as faixas e os grupos."""
    out = {"backup": {}, "dados": {}, "faixas": [{"k": k, "nome": n, "cor": c} for k, n, c in FAIXAS], "grupos": [{"nome": n, "explica": e} for n, e in GRUPOS]}
    for c in CLASSES.values():
        if c["backup"]:
            out["backup"].setdefault(c["backup"], {"ico": c["ico"]})
        out["dados"].setdefault(c["dados"], {"ico": c["ico"], "faixa": c["faixa"]})
    out["dados"]["Outros"] = {"ico": "📦", "faixa": "outros"}  # scripts, configurações e o que não tem classe
    for cat, fx in BACKUP_FAIXA.items():
        out["backup"].setdefault(cat, {})
        out["backup"][cat].update(faixa=fx, grupo=grupo_backup(cat))
    return out
