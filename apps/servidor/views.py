from django.http import JsonResponse


def healthz(request):
    """Para o healthcheck do Docker: não toca em dados."""
    return JsonResponse({"ok": True})
