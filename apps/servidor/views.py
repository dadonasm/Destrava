"""Contrato HTTP do servidor da loja (R2 do PROMPT-DJANGO.md): mesmas rotas, corpos JSON e códigos do servidor antigo.
Só HTTP aqui; regras ficam em auth, armazenamento, pacote e enderecos."""
import functools
import json
import logging
import os

from django.conf import settings
from django.http import FileResponse, HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from . import armazenamento as ARM
from . import auth, enderecos, pacote

log = logging.getLogger("destrava")
MODELOS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates", "servidor")


def _erro(msg, code):
    return JsonResponse({"erro": msg}, status=code, json_dumps_params={"ensure_ascii": False})


def _json(obj):
    return JsonResponse(obj, safe=False, json_dumps_params={"ensure_ascii": False})


def api(view):
    """ValueError → 400 com a mensagem; qualquer outro erro → 500 genérico (o detalhe vai só para o log)."""
    @functools.wraps(view)
    def envolve(request, *a, **kw):
        try:
            return view(request, *a, **kw)
        except ValueError as e:
            return _erro(str(e), 400)
        except Exception:
            log.exception("erro em %s %s", request.method, request.path)
            return _erro("Erro interno do servidor.", 500)
    return csrf_exempt(envolve)


def exige_tecnico(view):
    """Authorization: Bearer <chave>. Injeta request.tecnico. Bloqueia o IP depois de várias tentativas erradas."""
    @functools.wraps(view)
    def envolve(request, *a, **kw):
        ip = auth.ip_do_pedido(request)
        if auth.bloqueado(ip):
            return _erro("Muitas tentativas com chave errada. Espere alguns minutos.", 429)
        cab = request.META.get("HTTP_AUTHORIZATION", "")
        nome = auth.autenticar(cab[7:].strip() if cab.startswith("Bearer ") else "")
        if not nome:
            auth.registrar_falha(ip)
            return _erro("Chave de técnico inválida.", 401)
        request.tecnico = nome
        return view(request, *a, **kw)
    return envolve


def _corpo(request, limite):
    try:
        n = int(request.META.get("CONTENT_LENGTH") or 0)
    except ValueError:
        n = -1
    if n < 0 or n > limite:
        raise ValueError("Conteúdo grande demais.")
    return request.body if n else b""


def _corpo_json(request):
    return json.loads(_corpo(request, ARM.MAX_JSON).decode("utf-8") or "{}")


def nao_encontrado(request, exception=None):
    return _erro("rota desconhecida", 404)


def erro_interno(request):
    return _erro("Erro interno do servidor.", 500)


def healthz(request):
    """Para o healthcheck do Docker: não toca em dados."""
    return JsonResponse({"ok": True})


@api
@require_http_methods(["GET", "HEAD"])
def script(request, nome):
    """iniciar.sh / iniciar.ps1: texto cru (cheio de $ e {}), só o __SERVIDOR__ é trocado. Nunca pelo engine de template."""
    with open(os.path.join(MODELOS, nome + ".txt"), encoding="utf-8") as fh:
        txt = fh.read().replace("__SERVIDOR__", enderecos.publico(request))
    return HttpResponse(txt, content_type="text/plain; charset=utf-8")


@api
@require_http_methods(["GET", "HEAD"])
@exige_tecnico
def quem(request):
    return _json({"tecnico": request.tecnico, "versao": pacote.pacote()[2]})


@api
@require_http_methods(["GET", "HEAD"])
@exige_tecnico
def pacote_info(request):
    _, sha, ver = pacote.pacote()
    rts = pacote.runtimes()
    if request.GET.get("formato") == "txt":  # para o iniciar.sh, que não tem leitor de JSON
        linhas = ["versao=" + ver, "sha256=" + sha] + ["runtime_%s=%s" % (k, v.get("sha256", "")) for k, v in sorted(rts.items())]
        return HttpResponse("\n".join(linhas) + "\n", content_type="text/plain; charset=utf-8")
    return _json({"versao": ver, "sha256": sha, "runtimes": {k: {"sha256": v.get("sha256", ""), "python": v.get("python", "")} for k, v in rts.items()}})


@api
@require_http_methods(["GET", "HEAD"])
@exige_tecnico
def pacote_zip(request):
    r = HttpResponse(pacote.pacote()[0], content_type="application/zip")
    r["Content-Disposition"] = 'attachment; filename="Destrava.zip"'
    return r


@api
@require_http_methods(["GET", "HEAD"])
@exige_tecnico
def runtime(request, nome):
    p = pacote.caminho_runtime(nome)
    if not p:
        return _erro("Python para %s ainda não foi baixado no servidor (rode baixar_runtimes.py)." % nome, 404)
    return FileResponse(open(p, "rb"), content_type="application/octet-stream")


@api
@require_http_methods(["GET", "HEAD"])
@exige_tecnico
def maquinas(request):
    return _json({"maquinas": ARM.indice()})


@api
@require_http_methods(["GET", "HEAD", "DELETE"])
@exige_tecnico
def maquina(request, mid):
    if request.method == "DELETE":
        ARM.apagar_maquina(mid)
        return _json({"ok": True})
    return _json({"arquivos": ARM.arquivos_maquina(mid)})


@api
@require_http_methods(["PUT"])
@exige_tecnico
def maquina_arquivo(request, mid, arquivo):
    ARM.gravar_arquivo(mid, arquivo, _corpo(request, ARM.MAX_ARQ))
    return _json({"ok": True})


@api
@require_http_methods(["GET", "HEAD", "POST"])
@exige_tecnico
def log_view(request):
    if request.method == "POST":
        return _json(ARM.log_add(_corpo_json(request), request.tecnico))
    return _json({"linhas": ARM.log_ler(request.GET.get("mid", ""))})


@api
@require_http_methods(["GET", "HEAD"])
@exige_tecnico
def log_verificar(request):
    return _json(ARM.log_verificar())


@api
@require_http_methods(["POST"])
@exige_tecnico
def resolver(request):
    d = _corpo_json(request)
    return _json({"mid": ARM.resolver(d if isinstance(d, dict) else {})})
