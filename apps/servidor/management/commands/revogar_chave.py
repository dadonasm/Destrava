from django.core.management.base import BaseCommand

from apps.servidor import auth


class Command(BaseCommand):
    help = "Apaga a chave de um técnico."

    def add_arguments(self, parser):
        parser.add_argument("nome")

    def handle(self, *a, **o):
        self.stdout.write("Chaves removidas: %d" % auth.revogar(o["nome"]))
