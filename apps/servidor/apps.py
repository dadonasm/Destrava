from django.apps import AppConfig


class ServidorConfig(AppConfig):
    name = "apps.servidor"

    def ready(self):
        from . import armazenamento
        armazenamento.preparar()
