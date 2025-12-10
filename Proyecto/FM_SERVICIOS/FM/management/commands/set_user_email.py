from django.core.management.base import BaseCommand, CommandParser

from FM.models import User


class Command(BaseCommand):
    help = "Actualiza el email de un usuario: --username <u> --email <e>"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--username", required=True)
        parser.add_argument("--email", required=True)

    def handle(self, *args, **opts):
        username = opts["username"]
        email = opts["email"].strip().lower()
        try:
            u = User.objects.get(username=username)
        except User.DoesNotExist:
            self.stderr.write(self.style.ERROR(f"No existe el usuario '{username}'."))
            return
        u.email = email
        u.save(update_fields=["email"])
        self.stdout.write(self.style.SUCCESS(f"Email de '{username}' actualizado a {email}."))

