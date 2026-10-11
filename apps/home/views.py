from django.shortcuts import render

from apps.servidor import enderecos, pacote


def home(request):
    """Página pública do servidor. Só o que o técnico precisa para começar e o estado do servidor:
    nada de máquinas, clientes ou técnicos (é página aberta)."""
    _, sha, versao = pacote.pacote()
    rts = pacote.runtimes()
    lista = [{"nome": n, "ok": n in rts} for n in pacote.ESPERADOS]
    return render(request, "home/home.html", {"servidor": enderecos.publico(request), "versao": versao, "sha_curto": sha[:12],
                                              "runtimes": lista, "falta_runtime": not all(r["ok"] for r in lista)})
