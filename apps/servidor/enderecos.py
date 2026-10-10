"""Endereço que os computadores usam para chegar ao servidor (vai dentro dos scripts de início)."""
import re

from django.conf import settings

HOST_RE = re.compile(r"^[A-Za-z0-9.-]{1,253}(:\d{1,5})?$")


def publico(request):
    if settings.DESTRAVA_URL_PUBLICA:
        return settings.DESTRAVA_URL_PUBLICA
    host = request.get_host()  # já validado contra ALLOWED_HOSTS (considera X-Forwarded-Host do túnel)
    if not HOST_RE.match(host):
        raise ValueError("Cabeçalho Host inválido.")
    https = request.is_secure() or '"https"' in request.META.get("HTTP_CF_VISITOR", "")
    return "%s://%s" % ("https" if https else "http", host)
