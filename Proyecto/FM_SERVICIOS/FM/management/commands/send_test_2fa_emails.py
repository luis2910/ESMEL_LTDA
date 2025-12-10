from django.core.management.base import BaseCommand, CommandParser
from django.conf import settings

from FM.models import User
from FM.email_utils import send_email


TEMPLATE_SUBJECT = "Prueba de envío 2FA - FM SERVICIOS"
TEMPLATE_TEXT = (
    "Hola {name},\n\n"
    "Este es un correo de prueba para verificar la configuración de envío de correos.\n"
    "Si recibes este mensaje, el sistema puede enviar correos correctamente.\n\n"
    "— FM SERVICIOS"
)
TEMPLATE_HTML = (
    "<p>Hola {name},</p>"
    "<p>Este es un correo de <strong>prueba</strong> para verificar la configuración de envío de correos.</p>"
    "<p>Si recibes este mensaje, el sistema puede enviar correos correctamente.</p>"
    "<p>— FM SERVICIOS</p>"
)


class Command(BaseCommand):
    help = "Envía un correo de prueba a todos los usuarios con email (o a uno específico)."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--username", dest="username", help="Enviar solo a este username", default=None)
        parser.add_argument("--limit", dest="limit", type=int, help="Máximo de usuarios a procesar", default=None)
        parser.add_argument("--dry-run", dest="dry_run", action="store_true", help="No envía, solo lista los destinatarios")

    def handle(self, *args, **options):
        username = options.get("username")
        limit = options.get("limit")
        dry = options.get("dry_run")

        qs = User.objects.filter(is_active=True).exclude(email__isnull=True).exclude(email="").order_by("id")
        if username:
            qs = qs.filter(username=username)
        if limit:
            qs = qs[:limit]

        total = qs.count()
        if total == 0:
            self.stdout.write(self.style.WARNING("No hay usuarios con email para enviar."))
            return

        self.stdout.write(f"Procesando {total} usuario(s)...")
        sent = 0
        for u in qs:
            name = u.get_full_name() or u.username
            subject = TEMPLATE_SUBJECT
            text_body = TEMPLATE_TEXT.format(name=name)
            html_body = TEMPLATE_HTML.format(name=name)
            if dry:
                self.stdout.write(f"DRY-RUN: {u.username} <{u.email}>")
                continue
            ok = send_email(subject, [u.email], text_body=text_body, html_body=html_body, from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', None))
            if ok:
                sent += 1
                self.stdout.write(self.style.SUCCESS(f"OK: {u.username} <{u.email}>"))
            else:
                self.stdout.write(self.style.ERROR(f"FALLO: {u.username} <{u.email}>"))

        if not dry:
            self.stdout.write(self.style.SUCCESS(f"Envío completado. {sent}/{total} enviados."))

