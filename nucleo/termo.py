# -*- coding: utf-8 -*-
"""Destrava! - termo de responsabilidade, OS (ordem de servico), dono da maquina e registro de consentimentos.

Tudo local: nada sai do computador/pendrive. O registro (consentimentos.log) e uma linha JSON por evento,
encadeada por hash (cada linha guarda o hash da anterior) - serve de prova local de que nada foi alterado depois.
Nao e um documento notarial; para uso comercial, revise o texto do termo com um advogado.
"""
import datetime
import hashlib
import html
import json
import os
import re
import socket
import threading

import ficha as FICHA

HERE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(HERE, "consentimentos.log")
TERMO_VERSAO = "1.1"
MODO = "pendrive"  # "servidor" quando o programa roda baixado do servidor da loja (dd_backup --servidor)
REMOTO = None  # conexao.Conexao no modo servidor: o servidor guarda, encadeia e numera o registro
OS_AUTO = "__AUTO__"  # no modo servidor o número da OS é dado pelo servidor (evita número repetido entre técnicos)
ESCOPOS = [
    ("ficha", "Analisar o computador (ficha e nota)", "Só lê e mede. Nada é alterado."),
    ("backup", "Fazer backup dos arquivos", "Copia o que for selecionado para outro disco, com conferência."),
    ("melhorias", "Aplicar melhorias de desempenho", "Ajustes reversíveis de inicialização e efeitos visuais."),
    ("limpeza", "Liberar espaço (Dados)", "Mover arquivos para a Lixeira ou para um disco externo, com conferência."),
    ("formatar", "Formatar o computador", "Só depois de backup verificado em outro disco, com confirmação separada."),
]
ESCOPO_IDS = [e[0] for e in ESCOPOS]

# (título, texto) ou (título, texto no pendrive, texto no modo servidor)
TERMO = [
    ("Para que serve", "O Destrava!, da D&D Technology, é usado para analisar este computador, fazer cópia de segurança, aplicar melhorias de desempenho e, se eu escolher, liberar espaço de armazenamento."),
    ("Só com autorização", "Declaro que o computador é meu ou que tenho autorização expressa de quem é o responsável por ele. Em computador de terceiros, o nome de quem autoriza e o que foi autorizado são registrados na aba OS antes de qualquer ação."),
    ("Só o necessário", "Nada é copiado, alterado ou removido sem uma ação minha e sem confirmação. Copio apenas o que for selecionado para o serviço combinado."),
    ("Onde ficam os dados",
     "O programa não envia dados pela internet e não tem telemetria. Fichas, históricos e registros ficam somente neste pendrive.",
     "Fichas, históricos e registros do serviço são guardados no servidor da D&D Technology e não ficam neste computador. Os arquivos pessoais não são enviados: só o resumo da análise e os registros do serviço."),
    ("Mudanças com volta", "Ajustes de desempenho são reversíveis. Limpeza de espaço envia os arquivos para a Lixeira por padrão; apagar de vez só quando eu marcar isso de forma explícita."),
    ("Sigilo",
     "Arquivos e dados pessoais ou de empresa a que eu tiver acesso serão usados somente para o serviço combinado, sem compartilhamento. Se o dono pedir, os dados da máquina são apagados do pendrive ao final. O registro de autorização (nomes, data e código da máquina) é mantido como prova do serviço.",
     "Arquivos e dados pessoais ou de empresa a que eu tiver acesso serão usados somente para o serviço combinado, sem compartilhamento. Se o dono pedir, os dados da máquina são apagados do servidor ao final. O registro de autorização (nomes, data e código da máquina) é mantido como prova do serviço."),
    ("Formatação", "Só será feita depois de um backup verificado em disco diferente e com uma confirmação separada, no momento certo."),
    ("Responsabilidade", "Sou responsável pelas escolhas que fizer no uso do programa, incluindo conferir o que está selecionado antes de confirmar."),
    ("Registro",
     "Este aceite grava data e hora, meu nome, o código da máquina e a versão do termo no arquivo consentimentos.log, para ficar comprovado quem aceitou o quê.",
     "Este aceite grava data e hora, meu nome, o código da máquina e a versão do termo no registro de consentimentos do servidor, para ficar comprovado quem aceitou o quê."),
]
RODAPE = "Modelo baseado nos princípios da LGPD (finalidade, necessidade e transparência). Antes de usar comercialmente, recomenda-se revisão por advogado."

_LOCK = threading.Lock()


def clausulas():
    """Cláusulas do termo no modo atual (pendrive ou servidor)."""
    srv = MODO == "servidor"
    return [(c[0], c[2] if srv and len(c) > 2 else c[1]) for c in TERMO]


def termo_texto():
    return "\n".join("%d. %s: %s" % (i + 1, t, c) for i, (t, c) in enumerate(clausulas()))


def termo_hash():
    return hashlib.sha256((TERMO_VERSAO + "\n" + termo_texto()).encode("utf-8")).hexdigest()


# ----------------------------------------------------------------------------------------------
# registro encadeado
# ----------------------------------------------------------------------------------------------
def ler_linhas(path):
    out = []
    try:
        with open(path, encoding="utf-8") as fh:
            for ln in fh:
                ln = ln.strip()
                if ln:
                    try:
                        out.append(json.loads(ln))
                    except ValueError:
                        out.append({"corrompida": ln})
    except OSError:
        pass
    return out


def _ler_log(mid=None):
    """Linhas do registro (no modo servidor, só as da máquina pedida: o filtro por mid é feito lá)."""
    if REMOTO:
        return REMOTO.log_ler(mid)
    return ler_linhas(LOG)


def anexar_linha(path, reg):
    """Encadeia reg no fim do registro em path (hash da linha anterior + conteúdo) e grava. Quem chama segura a trava."""
    linhas = ler_linhas(path)
    prev = linhas[-1].get("hash", "") if linhas else ""
    reg = dict(reg)
    reg.pop("hash", None)
    reg["n"] = len(linhas) + 1
    reg["prev"] = prev
    corpo = json.dumps(reg, ensure_ascii=False, sort_keys=True)
    reg["hash"] = hashlib.sha256((prev + corpo).encode("utf-8")).hexdigest()
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(reg, ensure_ascii=False, sort_keys=True) + "\n")
        fh.flush()
        try:
            os.fsync(fh.fileno())
        except OSError:
            pass
    return reg


def log_add(evento, mid, **dados):
    reg = {"quando": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "evento": evento, "mid": mid, "pc": socket.gethostname()}
    reg.update(dados)
    if REMOTO:
        return REMOTO.log_add(reg)
    with _LOCK:
        return anexar_linha(LOG, reg)


def verificar_linhas(linhas):
    """True se a cadeia de hashes esta integra."""
    prev = ""
    n = 0
    for r in linhas:
        if "corrompida" in r:
            return {"ok": False, "linha": n + 1, "motivo": "linha ilegível"}
        r = dict(r)
        h = r.pop("hash", "")
        if r.get("prev", "") != prev or hashlib.sha256((prev + json.dumps(r, ensure_ascii=False, sort_keys=True)).encode("utf-8")).hexdigest() != h:
            return {"ok": False, "linha": n + 1, "motivo": "linha alterada ou removida"}
        prev = h
        n += 1
    return {"ok": True, "linhas": n}


def log_verificar():
    if REMOTO:
        return REMOTO.log_verificar()
    return verificar_linhas(ler_linhas(LOG))


# ----------------------------------------------------------------------------------------------
# deteccao de maquina corporativa (melhor esforco)
# ----------------------------------------------------------------------------------------------
def detectar_corporativa():
    sinais = []
    try:
        if FICHA.IS_WIN:
            o = FICHA.ps("$cs=Get-CimInstance Win32_ComputerSystem; $r=@(); if($cs.PartOfDomain){$r+=('dominio:'+$cs.Domain)}; "
                         "$d=(dsregcmd /status 2>$null) -join [char]10; if($d -match 'AzureAdJoined\\s*:\\s*YES'){$r+='azuread'}; "
                         "if($d -match 'MdmUrl\\s*:\\s*\\S'){$r+='mdm'}; ($r -join ';')", 40).strip().splitlines()
            for x in ((o[-1] if o else "").split(";")):
                x = x.strip()
                if x.startswith("dominio:"):
                    sinais.append("Participa de um domínio de rede (%s)" % x[8:])
                elif x == "azuread":
                    sinais.append("Vinculado a uma conta de trabalho/escola (Azure AD)")
                elif x == "mdm":
                    sinais.append("Gerenciado por uma ferramenta de TI (MDM)")
        elif os.uname().sysname == "Darwin":
            o = FICHA.run_out(["profiles", "status", "-type", "enrollment"])
            if re.search(r"MDM enrollment:\s*Yes", o) or re.search(r"Enrolled via DEP:\s*Yes", o):
                sinais.append("Registrado em gerenciamento de dispositivos (MDM)")
            if os.path.isdir("/Library/Managed Preferences") and os.listdir("/Library/Managed Preferences"):
                sinais.append("Tem configurações gerenciadas pela empresa")
            if any(os.path.exists(p) for p in ("/Library/Application Support/JAMF", "/usr/local/jamf", "/Library/Intune", "/Library/Application Support/Microsoft/Intune")):
                sinais.append("Tem agente de gerenciamento (Jamf/Intune)")
            if FICHA.run_out(["dsconfigad", "-show"]).strip():
                sinais.append("Vinculado a um diretório corporativo (Active Directory)")
        else:
            for p, msg in (("/etc/sssd/sssd.conf", "Usa login de rede corporativo (SSSD)"), ("/etc/landscape/client.conf", "Gerenciado por Landscape"), ("/etc/ipa/default.conf", "Registrado em domínio FreeIPA"),
                           ("/etc/krb5.keytab", "Tem credencial de domínio (Kerberos)")):
                if os.path.exists(p):
                    sinais.append(msg)
            if FICHA.run_out(["realm", "list"]).strip():
                sinais.append("Ingressado em um domínio (realm)")
    except Exception:
        pass
    return {"corporativa": bool(sinais), "sinais": sinais}


# ----------------------------------------------------------------------------------------------
# estado do termo e da OS
# ----------------------------------------------------------------------------------------------
def status(mid):
    ult = None
    for r in _ler_log(mid):
        if r.get("mid") == mid and r.get("evento") == "termo_aceito":
            ult = r
    meta = FICHA.meta_ler(mid)
    ok = bool(ult and ult.get("termo_versao") == TERMO_VERSAO and ult.get("termo_hash") == termo_hash())
    return {"aceito": ok, "registro": ult, "dono": meta.get("dono", ""), "terceiro_nome": meta.get("terceiro_nome", ""), "autorizado_por": meta.get("autorizado_por", ""),
            "tecnico": meta.get("tecnico", ""), "corporativa": bool(meta.get("corporativa")), "versao": TERMO_VERSAO}


def os_atual(mid):
    cur = None
    for r in _ler_log(mid):
        if r.get("mid") != mid:
            continue
        if r.get("evento") == "os_registrada":
            cur = r
        elif r.get("evento") == "os_encerrada":
            cur = None
    return cur


def aceitar(mid, responsavel, dono, terceiro_nome="", autorizado_por="", confirma_particular=False):
    responsavel = (responsavel or "").strip()
    if len(responsavel) < 3:
        raise ValueError("Digite seu nome completo para aceitar o termo.")
    if dono not in ("particular", "terceiros"):
        raise ValueError("Informe se a máquina é particular ou de terceiros.")
    det = detectar_corporativa()
    if dono == "particular" and os_atual(mid):
        raise ValueError("Há uma OS aberta nesta máquina. Encerre a OS antes de marcá-la como particular.")
    if dono == "particular" and det["corporativa"] and not confirma_particular:
        raise ValueError("Esta máquina parece corporativa. Para marcar como particular, confirme explicitamente que ela é sua.")
    if dono == "terceiros" and len((terceiro_nome or "").strip()) < 2:
        raise ValueError("Informe o nome do dono (cliente, empresa ou pessoa).")
    FICHA.meta_set(mid, dono=dono, terceiro_nome=(terceiro_nome or "").strip(), autorizado_por=(autorizado_por or "").strip(), tecnico=responsavel, corporativa=det["corporativa"])
    reg = log_add("termo_aceito", mid, responsavel=responsavel, dono=dono, terceiro_nome=(terceiro_nome or "").strip(), autorizado_por=(autorizado_por or "").strip(),
                  corporativa=det["corporativa"], sinais=det["sinais"], confirmou_particular_em_corporativa=bool(confirma_particular and det["corporativa"]),
                  termo_versao=TERMO_VERSAO, termo_hash=termo_hash())
    arq = doc_termo(mid, reg)
    FICHA.hist_add(mid, "termo", "Termo de responsabilidade aceito por %s (%s)" % (responsavel, "particular" if dono == "particular" else "terceiros: " + (terceiro_nome or "").strip()))
    return {"status": status(mid), "documento": arq}


def proximo_numero_os(linhas):
    hoje = datetime.date.today().strftime("%Y%m%d")
    n = 1 + sum(1 for r in linhas if r.get("evento") == "os_registrada" and str(r.get("os", "")).startswith("OS-" + hoje))
    return "OS-%s-%02d" % (hoje, n)


def registrar_os(mid, cliente, escopos, tecnico=""):
    st = status(mid)
    if not st["aceito"]:
        raise PermissionError("termo")
    cliente = (cliente or "").strip()
    if len(cliente) < 3:
        raise ValueError("Digite o nome de quem autoriza o serviço.")
    esc = [e for e in ESCOPO_IDS if e in (escopos or [])]
    if not esc:
        raise ValueError("Marque pelo menos um serviço autorizado.")
    reg = log_add("os_registrada", mid, os=OS_AUTO if REMOTO else proximo_numero_os(ler_linhas(LOG)), cliente=cliente, escopos=esc, tecnico=tecnico or st.get("tecnico", ""),
                  termo_versao=TERMO_VERSAO, termo_hash=termo_hash())
    arq = doc_os(mid, reg)
    FICHA.hist_add(mid, "os", "%s registrada: %s autorizou %s" % (reg.get("os"), cliente, ", ".join(esc)))
    return {"os": reg, "documento": arq}


def encerrar_os(mid, apagar_dados=False):
    atual = os_atual(mid)
    if not atual:
        raise ValueError("Não há OS aberta para esta máquina.")
    log_add("os_encerrada", mid, os=atual.get("os"), dados_apagados=bool(apagar_dados))
    if apagar_dados:
        FICHA.apagar_maquina(mid)
    else:
        FICHA.hist_add(mid, "os", "%s encerrada" % atual.get("os"))
    return {"ok": True}


class SemPermissao(PermissionError):
    pass


def exigir(mid, escopo=None):
    """Chamada pelo servidor antes de qualquer ação que lê, altera ou apaga."""
    st = status(mid)
    if not st["aceito"]:
        raise SemPermissao("termo")
    if escopo and st["dono"] == "terceiros":
        o = os_atual(mid)
        if not o or escopo not in (o.get("escopos") or []):
            raise SemPermissao("os:" + escopo)
    return st


# ----------------------------------------------------------------------------------------------
# documentos imprimiveis (HTML -> "Salvar como PDF" no navegador)
# ----------------------------------------------------------------------------------------------
_CSS = ("body{font:15px/1.5 Georgia,serif;color:#1b1b1f;max-width:760px;margin:30px auto;padding:0 24px}"
        "h1{font:700 22px system-ui,sans-serif;margin:0}.tag{font:12px system-ui,sans-serif;letter-spacing:2px;color:#9a7418}"
        "hr{border:0;border-top:2px solid #c9a227;margin:14px 0 18px}h2{font:700 15px system-ui,sans-serif;margin:14px 0 2px}p{margin:2px 0 6px}"
        ".box{border:1px solid #cfcfd6;border-radius:8px;padding:10px 14px;margin:12px 0;font:14px system-ui,sans-serif}"
        ".sig{margin-top:34px;font:13px system-ui,sans-serif;color:#555}.sm{font:11px system-ui,sans-serif;color:#777;margin-top:18px}"
        "@media print{body{margin:0}}")


def _doc_base(titulo, corpo, mid):
    return ("<!doctype html><html lang='pt-BR'><meta charset='utf-8'><title>%s</title><style>%s</style><body>"
            "<div class='tag'>D&amp;D TECHNOLOGY · DESTRAVA!</div><h1>%s</h1><hr>%s"
            "<p class='sm'>Documento gerado localmente. Código da máquina %s. Para guardar em PDF: imprimir e escolher “Salvar como PDF”.</p></body></html>") % (
        html.escape(titulo), _CSS, html.escape(titulo), corpo, html.escape(mid))


def _salvar_doc(mid, prefixo, corpo, titulo):
    d = FICHA.pasta(mid)
    os.makedirs(d, exist_ok=True)
    nome = "%s-%s.html" % (prefixo, datetime.datetime.now().strftime("%Y%m%d-%H%M%S"))
    p = os.path.join(d, nome)
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(_doc_base(titulo, corpo, mid))
    FICHA._gravou(p)
    return p


def doc_termo(mid, reg):
    c = "".join("<h2>%d. %s</h2><p>%s</p>" % (i + 1, html.escape(t), html.escape(x)) for i, (t, x) in enumerate(clausulas()))
    c += ("<div class='box'><b>Aceito por:</b> %s<br><b>Máquina:</b> %s (%s)<br><b>Situação:</b> %s%s<br><b>Data e hora:</b> %s<br><b>Termo:</b> versão %s · selo %s</div>" % (
        html.escape(reg.get("responsavel", "")), html.escape(mid), html.escape(reg.get("pc", "")),
        "máquina particular" if reg.get("dono") == "particular" else "máquina de terceiros — dono: " + html.escape(reg.get("terceiro_nome", "")),
        ("<br><b>Autorizado por:</b> " + html.escape(reg["autorizado_por"])) if reg.get("autorizado_por") else "",
        html.escape(reg.get("quando", "")), html.escape(reg.get("termo_versao", "")), html.escape(reg.get("termo_hash", "")[:16])))
    c += "<p class='sm'>%s</p>" % html.escape(RODAPE)
    return _salvar_doc(mid, "termo", c, "Termo de responsabilidade pelo uso do software")


def doc_os(mid, reg):
    nomes = {e[0]: e[1] for e in ESCOPOS}
    c = "<div class='box'><b>%s</b><br>Cliente: %s<br>Equipamento: %s (%s)<br>Técnico: %s<br>Data e hora: %s</div>" % (
        html.escape(reg.get("os", "")), html.escape(reg.get("cliente", "")), html.escape(FICHA.nome_exibicao(mid)), html.escape(mid), html.escape(reg.get("tecnico", "")), html.escape(reg.get("quando", "")))
    c += "<p>Eu, <b>%s</b>, autorizo a realização dos serviços marcados abaixo neste equipamento:</p><ul>%s</ul>" % (
        html.escape(reg.get("cliente", "")), "".join("<li>%s</li>" % html.escape(nomes.get(e, e)) for e in reg.get("escopos", [])))
    c += "<p>Não autorizado: qualquer serviço não marcado acima. Os dados do equipamento ficam apenas no pendrive do técnico e podem ser apagados ao final, a meu pedido.</p>"
    c += "<div class='sig'>Registro de autorização por nome, sem outros documentos pessoais.<br>Assinatura (opcional, se impresso): ________________________________</div>"
    return _salvar_doc(mid, "os", c, "Ordem de serviço e autorização")
