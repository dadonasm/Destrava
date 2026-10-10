from django.core.management.base import BaseCommand, CommandError

from apps.servidor import auth


class Command(BaseCommand):
    help = "Cria a chave de um técnico (mostrada uma única vez; no disco fica só o hash)."

    def add_arguments(self, parser):
        parser.add_argument("nome")

    def handle(self, *a, **o):
        try:
            chave = auth.nova_chave(o["nome"])
        except ValueError as e:
            raise CommandError(str(e))
        self.stdout.write("Chave de %s (guarde agora, ela não é mostrada de novo):\n\n    %s\n" % (o["nome"].strip(), chave))
