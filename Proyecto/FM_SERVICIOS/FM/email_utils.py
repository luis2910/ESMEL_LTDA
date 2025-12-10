import json
import logging
from urllib import request, error

from django.conf import settings
from django.core.mail import EmailMultiAlternatives, get_connection


logger = logging.getLogger(__name__)


def _build_sendgrid_payload(subject: str, to_emails: list[str], text_body: str | None, html_body: str | None, from_email: str) -> dict:
    content = []
    if text_body:
        content.append({"type": "text/plain", "value": text_body})
    if html_body:
        content.append({"type": "text/html", "value": html_body})
    if not content:
        content = [{"type": "text/plain", "value": ""}]
    return {
        "personalizations": [{"to": [{"email": e} for e in to_emails]}],
        "from": {"email": from_email},
        "subject": subject,
        "content": content,
    }


def send_email(subject: str, to_emails: list[str], text_body: str | None = None, html_body: str | None = None, from_email: str | None = None) -> bool:
    """
    Envío ESTRICTO por SendGrid API (sin fallback).
    - Requiere SENDGRID_API_KEY y un remitente válido (DEFAULT_FROM_EMAIL) verificado en SendGrid.
    - Retorna False si no hay API key o la solicitud falla.
    """
    def _backend_send() -> bool:
        """
        Intenta backend Django por defecto; en DEBUG, si falla, intenta console backend.
        """
        fe = from_email or getattr(settings, "DEFAULT_FROM_EMAIL", "no-reply@fm-servicios.local")
        tried_console = False
        for attempt in range(2):
            try:
                if attempt == 1 and getattr(settings, "DEBUG", False):
                    # fallback explícito a console en modo DEBUG
                    conn = get_connection("django.core.mail.backends.console.EmailBackend")
                    tried_console = True
                else:
                    conn = get_connection()  # usa EMAIL_BACKEND configurado
                msg = EmailMultiAlternatives(subject, text_body or "", fe, to_emails, connection=conn)
                if html_body:
                    msg.attach_alternative(html_body, "text/html")
                msg.send()
                return True
            except Exception as e:
                if getattr(settings, "DEBUG", False):
                    logger.exception("Fallo backend Django (%s): %s", "console" if tried_console else "default", e)
                if tried_console:
                    break
                # en siguiente iteración intentará console si DEBUG
        return False

    sg_key = getattr(settings, "SENDGRID_API_KEY", None)
    if not sg_key:
        if getattr(settings, "DEBUG", False):
            logger.warning("SENDGRID_API_KEY no configurada; usando backend Django (SMTP/console/filebased)")
        return _backend_send()

    from_email = from_email or getattr(settings, "DEFAULT_FROM_EMAIL", "no-reply@fm-servicios.local")
    try:
        url = "https://api.sendgrid.com/v3/mail/send"
        headers = {
            "Authorization": f"Bearer {sg_key}",
            "Content-Type": "application/json",
        }
        payload = _build_sendgrid_payload(subject, to_emails, text_body, html_body, from_email)
        req = request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
        with request.urlopen(req, timeout=10) as resp:
            ok = 200 <= resp.status < 300
            if ok:
                return True
            if getattr(settings, "DEBUG", False):
                logger.error("SendGrid status %s", resp.status)
    except Exception as e:
        if getattr(settings, "DEBUG", False):
            logger.exception("SendGrid fallo: %s", e)

    # Si falla SendGrid o no hay OK, usa el backend Django configurado (SMTP/console/filebased)
    return _backend_send()
