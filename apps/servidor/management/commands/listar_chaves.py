from django.core.management.base import BaseCommand

from apps.servidor import auth


class Command(BaseCommand):
    help = "Lista os técnicos que têm chave."

    def handle(self, *a, **o):
        for c in auth.ler_chaves():
            self.stdout.write("%-30s criada em %s" % (c.get("nome"), c.get("criada")))
