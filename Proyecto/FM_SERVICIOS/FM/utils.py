from django.core.mail import send_mail
from django.conf import settings

def enviar_cotizacion_por_correo(cotizacion):
    asunto = f"Nueva cotización: {cotizacion.servicio.nombre}"
    mensaje = f"""
Nueva cotización enviada.

Usuario: {cotizacion.usuario.username}
Servicio: {cotizacion.servicio.nombre}
Título: {cotizacion.titulo}
Descripción: {cotizacion.descripcion}
Fecha: {cotizacion.fecha_creacion.strftime('%Y-%m-%d %H:%M')}
"""
    destinatarios = ['tucorreo@ejemplo.com']  # ← Cambia esto
    send_mail(asunto, mensaje, settings.DEFAULT_FROM_EMAIL, destinatarios)

