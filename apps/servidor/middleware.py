class SemCache:
    """Nenhuma resposta do servidor da loja vai para cache e nenhuma é 'adivinhada' pelo navegador (R2)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        r = self.get_response(request)
        if not request.path.startswith("/static/"):
            r["Cache-Control"] = "no-store"
        r["X-Content-Type-Options"] = "nosniff"
        return r
