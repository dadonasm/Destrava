"""Liga o Django para os testes do servidor da loja. Sem Django instalado (ex.: Python 3.8 do motor), DJANGO=False
e esses testes se pulam sozinhos; os do motor continuam rodando."""
import os

try:
    import django
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    django.setup()
    from django.test.utils import setup_test_environment
    try:
        setup_test_environment()
    except RuntimeError:
        pass  # já ligado por outro arquivo de teste
    DJANGO = True
except ImportError:
    DJANGO = False
