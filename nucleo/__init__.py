"""O motor do Destrava!: o agente que roda na máquina do cliente. Só biblioteca padrão (R1 do PROMPT-DJANGO.md).

Os módulos daqui se importam pelo nome de topo (`import ficha`), porque no pendrive e no Destrava.zip eles ficam
soltos numa mesma pasta. Para o servidor (Django) e os testes usarem `from nucleo import ficha` sem criar uma
SEGUNDA cópia de cada módulo (nucleo.ficha diferente de ficha, com STORE/LOG divergentes):
  1. esta pasta entra no sys.path;
  2. cada `nucleo.<nome>` passa a ser o MESMO módulo de topo (sys.modules);
  3. `__path__` vazio: `import nucleo.ficha` nunca carrega o arquivo de novo por fora deste mapeamento.
Não é dependência externa e não muda nenhum módulo do motor.
"""
import importlib
import os
import sys

_AQUI = os.path.dirname(os.path.abspath(__file__))
if _AQUI not in sys.path:
    sys.path.insert(0, _AQUI)
__path__ = []

LEVES = ("disco", "atualizador", "otimizacoes", "ficha", "termo", "dados", "mapa", "conexao")
for _nome in LEVES:
    sys.modules[__name__ + "." + _nome] = importlib.import_module(_nome)


def __getattr__(nome):
    """dd_backup (pesado: cria o App e lê etiquetas) só carrega quando alguém pede."""
    if nome in LEVES or nome == "dd_backup":
        mod = importlib.import_module(nome)
        sys.modules[__name__ + "." + nome] = mod
        return mod
    raise AttributeError(nome)
