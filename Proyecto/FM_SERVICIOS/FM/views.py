from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth import update_session_auth_hash
from django.core.validators import validate_email
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import timezone
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.conf import settings
from django.urls import reverse
from django.http import JsonResponse, HttpResponse
from django.core.files.base import ContentFile
from django.views.decorators.csrf import csrf_exempt
import os
from django.utils.http import url_has_allowed_host_and_scheme
import logging
import re
from django.utils.crypto import get_random_string
import calendar
import secrets
import json
from transbank.webpay.webpay_plus.transaction import Transaction
from transbank.common.integration_type import IntegrationType
from transbank.common.integration_commerce_codes import IntegrationCommerceCodes
from transbank.common.integration_api_keys import IntegrationApiKeys
from transbank.common.options import WebpayOptions
from uuid import uuid4
from datetime import datetime, timedelta, time
from decimal import Decimal, InvalidOperation
from django.contrib.auth.hashers import make_password, check_password
from django.utils.text import slugify
from io import BytesIO

from django.db import models

from .models import (
    Servicio,
    ServicioImagen,
    Cotizacion,
    CotizacionItem,
    User,
    Documento,
    PasswordResetCode,
    LoginCode,
    VisitaTecnica,
    Trabajo,
    Tecnico,
    Region,
    Comuna,
    Insumo,
)
from .forms import (
    RegistroForm, LoginForm, Login2FACodeForm, CotizacionForm, ContactoForm, DocumentoForm,
    PasswordCodeRequestForm, PasswordCodeVerifyForm,
    ProfileForm, CompanyForm, PasswordByQuestionForm, DocumentoEditForm, ServicioForm,
    CHILE_REGIONES, CHILE_REGIONES_DICT,
)
from .email_utils import send_email

ADMIN_ACCESS_CODE = "3420"
SIGNATURE = "\n\nSaludos,\nFM Servicios Generales"
TECHNICIAN_ACCESS_CODE = "3421"
TECHNICIAN_ACCOUNTS = {
    "juan": {
        "slug": "tecnico-juan-perez",
        "email": "lcjbasket00@gmail.com",
        "code": TECHNICIAN_ACCESS_CODE,
        "nombre": "Juan Perez",
    },
}

SERVICE_TECH_MAP = {}
FIXED_PRICE = Decimal("50000")

TECHNICOS_PREDEF = []  # Se eliminan tecnicos predefinidos; usar solo los creados en BD
logger = logging.getLogger(__name__)
_supabase_cached_client = None
_supabase_client_error = False
_DEFAULT_TAG_SEPARATOR = ","


def _safe_storage_path(title: str | None, filename: str | None, prefix: str | None = None) -> str:
    """
    Construye una ruta segura (sin espacios ni tildes) para Supabase Storage.
    Genera un único nivel (opcionalmente con prefijo) para evitar árboles profundos.
    """
    base_slug = slugify(title or "documento") or "documento"
    stem, ext = os.path.splitext(filename or "")
    stem_slug = slugify(stem) or "archivo"
    ext = ext if ext else ".bin"
    uid = uuid4().hex[:6]
    safe_name = f"{base_slug}_{uid}{ext}"
    parts = [p.strip("/") for p in (prefix, safe_name) if p]
    return "/".join(parts)


def _supabase_client():
    """
    Devuelve un cliente de Supabase si las variables SUPABASE_URL y SUPABASE_KEY están configuradas
    y la librería está instalada. Retorna None en caso contrario para mantener compatibilidad.
    """
    global _supabase_cached_client, _supabase_client_error
    if _supabase_cached_client or _supabase_client_error:
        return _supabase_cached_client
    url = getattr(settings, "SUPABASE_URL", "") or os.environ.get("SUPABASE_URL", "")
    key = getattr(settings, "SUPABASE_KEY", "") or os.environ.get("SUPABASE_KEY", "")
    if not url or not key:
        _supabase_client_error = True
        return None
    try:
        from supabase import create_client  # type: ignore
    except Exception:
        _supabase_client_error = True
        return None
    try:
        _supabase_cached_client = create_client(url, key)
    except Exception:
        _supabase_client_error = True
        _supabase_cached_client = None
    return _supabase_cached_client


def _supabase_upload(file_or_bytes, *, bucket=None, path=None, content_type=None):
    """
    Sube un archivo o bytes a Supabase Storage. Retorna {"url": ..., "path": ...} o None si falla.
    """
    client = _supabase_client()
    if not client or file_or_bytes is None:
        if not client:
            logger.warning("Supabase no está configurado o el cliente no se pudo crear.")
        return None
    bucket_name = bucket or getattr(settings, "SUPABASE_BUCKET_DOCUMENTOS", "documentos")
    # path debe ser relativo al bucket (no incluir el nombre del bucket)
    target_path = (path or f"uploads/{uuid4().hex}").strip("/")
    data = None
    try:
        if hasattr(file_or_bytes, "read"):
            data = file_or_bytes.read()
            try:
                file_or_bytes.seek(0)
            except Exception:
                pass
        elif isinstance(file_or_bytes, (bytes, bytearray)):
            data = bytes(file_or_bytes)
    except Exception:
        data = None
    if not data:
        logger.warning("Supabase upload: sin datos para subir.")
        return None

    ctype = content_type
    if not ctype and hasattr(file_or_bytes, "content_type"):
        ctype = getattr(file_or_bytes, "content_type", None) or None
    file_options = {"upsert": "true", "content-type": ctype or "application/octet-stream"}

    try:
        client.storage.from_(bucket_name).upload(target_path, data, file_options=file_options)
        public_url = client.storage.from_(bucket_name).get_public_url(target_path)
        return {"url": public_url, "path": target_path, "bucket": bucket_name}
    except Exception as exc:  # pragma: no cover - solo logging de soporte opcional
        logger.warning("Supabase upload failed: %s", exc)
        return None


def _normalize_tags(raw: str | None) -> str:
    tags = []
    for chunk in (raw or "").split(_DEFAULT_TAG_SEPARATOR):
        clean = chunk.strip()
        if not clean:
            continue
        if clean.lower() not in [t.lower() for t in tags]:
            tags.append(clean)
    return ", ".join(tags)


def _supabase_delete(path: str | None, *, bucket=None) -> bool:
    client = _supabase_client()
    if not client or not path:
        return False
    bucket_name = bucket or getattr(settings, "SUPABASE_BUCKET_DOCUMENTOS", "documentos")
    try:
        client.storage.from_(bucket_name).remove([path])
        return True
    except Exception as exc:  # pragma: no cover
        logger.warning("Supabase delete failed: %s", exc)
        return False


def _rut_es_valido(rut: str) -> bool:
    """
    Valida un RUT chileno (8 dígitos + DV num/K), permitiendo puntos y guion. Calcula DV.
    """
    if not rut:
        return False
    try:
        _normalize_rut_strict(rut)
        return True
    except Exception:
        return False


def _telefono_es_valido(telefono: str) -> bool:
    """
    Valida teléfono Chile: +56 y 9 dígitos (total 11 con prefijo).
    """
    try:
        _normalize_phone_strict(telefono)
        return True
    except Exception:
        return False

def _normalize_rut_strict(raw: str) -> str:
    clean = re.sub(r"[^0-9kK]", "", raw or "")
    if len(clean) != 9:
        raise ValueError("RUT invalido")
    cuerpo, dv = clean[:-1], clean[-1].upper()
    if not cuerpo.isdigit() or len(cuerpo) != 8 or not (dv.isdigit() or dv == "K"):
        raise ValueError("RUT invalido")
    factors = [2, 3, 4, 5, 6, 7]
    s = 0
    for i, d in enumerate(reversed(cuerpo)):
        s += int(d) * factors[i % len(factors)]
    mod = 11 - (s % 11)
    dv_calc = "0" if mod == 11 else "K" if mod == 10 else str(mod)
    if dv != dv_calc:
        raise ValueError("RUT invalido")
    return f"{cuerpo}-{dv}"

def _normalize_phone_strict(raw: str) -> str:
    digits = re.sub(r"\D", "", raw or "")
    if not digits:
        raise ValueError("Telefono invalido")
    if digits.startswith("56"):
        digits = digits
    elif digits.startswith("0"):
        digits = "56" + digits.lstrip("0")
    else:
        digits = "56" + digits
    if len(digits) != 11 or not digits.startswith("56"):
        raise ValueError("Telefono invalido")
    return f"+{digits}"


def _invoice_items_from_cotizacion(cot):
    """
    Retorna un desglose de trabajos e insumos en formato dict.
    - Trabajos: líneas que comienzan con "Trabajo:" o el resto si no hay prefijo.
    - Insumos: líneas que comienzan con "Insumo:".
    """
    trabajos = []
    insumos = []
    try:
        for it in cot.items.all():
            desc_raw = (it.descripcion or "").strip()
            lower = desc_raw.lower()
            bucket = insumos if lower.startswith("insumo") else trabajos
            clean_desc = re.sub(r"^(trabajo|insumo)\s*:\s*", "", desc_raw, flags=re.IGNORECASE) or desc_raw or "-"
            bucket.append(
                {
                    "codigo": "INS" if bucket is insumos else "TRAB",
                    "descripcion": clean_desc,
                    "cantidad": float(it.cantidad or 1),
                    "precio": float(it.precio_unit or 0),
                }
            )
    except Exception:
        trabajos = []
        insumos = []

    neto_trab = sum((i["cantidad"] or 0) * (i["precio"] or 0) for i in trabajos)
    neto_insumos = sum((i["cantidad"] or 0) * (i["precio"] or 0) for i in insumos)

    total_gross = float(cot.presupuesto_estimado or 0)
    neto_est = (total_gross / 1.19) if total_gross else float(cot.total_items or 0)

    if not trabajos and not insumos:
        desc = cot.asunto or (cot.servicio.titulo if getattr(cot, "servicio", None) else "Servicio contratado")
        base_net = neto_est if neto_est > 0 else float(cot.total_items or FIXED_PRICE)
        trabajos.append({"codigo": "TRAB", "descripcion": desc, "cantidad": 1.0, "precio": base_net})

    return {"trabajos": trabajos, "insumos": insumos}


def _build_invoice_pdf_bytes(cot) -> bytes:
    """
    Genera un PDF simple de factura desde la cotización.
    Requiere reportlab (agregado a requirements.txt).
    """
    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.units import mm
        from reportlab.pdfgen import canvas
    except Exception:
        return b""

    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter

    def draw_text(x, y, text, size=9, bold=False):
        font = "Helvetica-Bold" if bold else "Helvetica"
        c.setFont(font, size)
        c.drawString(x, y, str(text))

    def fmt_clp(val: float) -> str:
        try:
            return f"${int(round(val)):,}".replace(",", ".")
        except Exception:
            return f"${val}"

    # Paleta
    accent = (0 / 255, 19 / 255, 93 / 255)
    soft = (245 / 255, 247 / 255, 255 / 255)
    gray_txt = (64 / 255, 70 / 255, 79 / 255)

    # Background suave
    c.setFillColorRGB(*soft)
    c.roundRect(10 * mm, 15 * mm, width - 20 * mm, height - 30 * mm, 8, fill=1, stroke=0)
    c.setFillColorRGB(0, 0, 0)  # reset

    # Encabezado banda
    c.setFillColorRGB(*accent)
    c.roundRect(10 * mm, height - 45 * mm, width - 20 * mm, 28 * mm, 8, fill=1, stroke=0)
    c.setFillColorRGB(1, 1, 1)

    # Encabezado empresa y logo
    logo_path = os.path.join(settings.BASE_DIR, "FM", "static", "menu", "img", "logo.jpeg")
    if os.path.exists(logo_path):
        try:
            c.drawImage(logo_path, 16 * mm, height - 40 * mm, width=24 * mm, preserveAspectRatio=True, mask="auto")
        except Exception:
            pass
    c.setFillColorRGB(1, 1, 1)
    draw_text(42 * mm, height - 23 * mm, "FM SERVICIOS GENERALES LIMITADA", size=12, bold=True)
    draw_text(42 * mm, height - 28 * mm, "Giro: Servicios de mantenimiento y reparación")
    draw_text(42 * mm, height - 33 * mm, "Dirección: Santiago, Chile")
    draw_text(42 * mm, height - 38 * mm, f"Email: {getattr(settings, 'DEFAULT_FROM_EMAIL', 'info@fm-servicios.cl')}")
    draw_text(width - 70 * mm, height - 23 * mm, "FACTURA ELECTRONICA", size=12, bold=True)
    draw_text(width - 60 * mm, height - 32 * mm, f"N° {cot.id}", size=11, bold=True)
    c.setFillColorRGB(0, 0, 0)
    trabajo_desc = cot.asunto or (cot.servicio.titulo if getattr(cot, "servicio", None) else "Servicio contratado")

    # Datos cliente
    base_y = height - 62 * mm
    label_x = 20 * mm
    value_x = 60 * mm
    c.setFillColorRGB(*gray_txt)
    draw_text(label_x, base_y + 5 * mm, "Datos del cliente", size=10, bold=True)
    c.setFillColorRGB(0, 0, 0)
    draw_text(label_x, base_y, "CLIENTE:", bold=True)
    draw_text(value_x, base_y, cot.usuario.get_full_name() or cot.usuario.username)
    draw_text(label_x, base_y - 6 * mm, "CORREO:", bold=True)
    draw_text(value_x, base_y - 6 * mm, cot.usuario.email or "-")
    draw_text(label_x, base_y - 12 * mm, "REGION/COMUNA:", bold=True)
    draw_text(value_x, base_y - 12 * mm, f"{cot.region or '-'} / {cot.comuna or '-'}")
    draw_text(label_x, base_y - 18 * mm, "DIRECCION:", bold=True)
    draw_text(value_x, base_y - 18 * mm, cot.lugar_servicio or "-")
    draw_text(label_x, base_y - 24 * mm, "FECHA:", bold=True)
    draw_text(value_x, base_y - 24 * mm, timezone.localdate().strftime("%d/%m/%Y"))

    c.setFillColorRGB(*gray_txt)
    draw_text(120 * mm, base_y + 5 * mm, "Servicio", size=10, bold=True)
    c.setFillColorRGB(0, 0, 0)
    draw_text(120 * mm, base_y, "TRABAJO / SERVICIO:", bold=True)
    draw_text(155 * mm, base_y, trabajo_desc)

    breakdown = _invoice_items_from_cotizacion(cot)
    trabajos = breakdown.get("trabajos") or []
    insumos = breakdown.get("insumos") or []

    # Sección trabajos
    start_y = base_y - 40 * mm
    c.setFillColorRGB(*gray_txt)
    draw_text(20 * mm, start_y, "Trabajos", size=10, bold=True)
    c.setFillColorRGB(0, 0, 0)
    draw_text(20 * mm, start_y - 6 * mm, "Codigo", bold=True)
    draw_text(40 * mm, start_y - 6 * mm, "Descripcion", bold=True)
    draw_text(122 * mm, start_y - 6 * mm, "Cantidad", bold=True)
    draw_text(142 * mm, start_y - 6 * mm, "Precio", bold=True)
    draw_text(162 * mm, start_y - 6 * mm, "Valor", bold=True)
    y = start_y - 12 * mm

    neto = 0.0
    for item in trabajos:
        qty = float(item.get("cantidad") or 1)
        price = float(item.get("precio") or 0)
        val = qty * price
        neto += val
        draw_text(20 * mm, y, item.get("codigo") or "-")
        draw_text(40 * mm, y, item.get("descripcion") or "-")
        draw_text(124 * mm, y, f"{qty:.2f}".rstrip("0").rstrip("."))
        draw_text(142 * mm, y, fmt_clp(price))
        draw_text(162 * mm, y, fmt_clp(val))
        y -= 6 * mm

    # Sección insumos
    y -= 4 * mm
    c.setFillColorRGB(*gray_txt)
    draw_text(20 * mm, y, "Insumos", size=10, bold=True)
    c.setFillColorRGB(0, 0, 0)
    y -= 6 * mm
    draw_text(20 * mm, y, "Codigo", bold=True)
    draw_text(40 * mm, y, "Descripcion", bold=True)
    draw_text(122 * mm, y, "Cantidad", bold=True)
    draw_text(142 * mm, y, "Precio", bold=True)
    draw_text(162 * mm, y, "Valor", bold=True)
    y -= 6 * mm

    if insumos:
        for item in insumos:
            qty = float(item.get("cantidad") or 1)
            price = float(item.get("precio") or 0)
            val = qty * price
            neto += val
            draw_text(20 * mm, y, item.get("codigo") or "-")
            draw_text(40 * mm, y, item.get("descripcion") or "-")
            draw_text(124 * mm, y, f"{qty:.2f}".rstrip("0").rstrip("."))
            draw_text(142 * mm, y, fmt_clp(price))
            draw_text(162 * mm, y, fmt_clp(val))
            y -= 6 * mm
    else:
        draw_text(40 * mm, y, "Sin insumos declarados", size=9)
        y -= 6 * mm

    # Ajustamos montos al total efectivamente pagado (guardado en presupuesto_estimado).
    iva = round(neto * 0.19)
    total_calc = neto + iva
    total_paid = float(cot.presupuesto_estimado or 0) or total_calc
    if abs(total_paid - total_calc) > 1:
        neto = round(total_paid / 1.19)
        iva = total_paid - neto
    total = total_paid or total_calc

    # Resumen visual
    summary_y = y - 10 * mm
    if summary_y < 82 * mm:
        summary_y = 82 * mm
    summary_bg = (246 / 255, 248 / 255, 255 / 255)
    c.setFillColorRGB(*summary_bg)
    c.roundRect(118 * mm, summary_y - 26 * mm, 70 * mm, 36 * mm, 8, fill=1, stroke=0)
    c.setFillColorRGB(*accent)
    draw_text(122 * mm, summary_y + 6 * mm, "Resumen de pago", size=10, bold=True)
    draw_text(122 * mm, summary_y, "MONTO NETO", size=9, bold=False)
    draw_text(178 * mm, summary_y, fmt_clp(neto))
    draw_text(122 * mm, summary_y - 6 * mm, "I.V.A. 19%", size=9, bold=False)
    draw_text(178 * mm, summary_y - 6 * mm, fmt_clp(iva))
    draw_text(122 * mm, summary_y - 14 * mm, "TOTAL PAGADO", size=10, bold=True)
    draw_text(176 * mm, summary_y - 14 * mm, fmt_clp(total), size=10, bold=True)

    # Nota visual para administrador
    c.setFillColorRGB(*gray_txt)
    draw_text(20 * mm, summary_y - 10 * mm, "Detalle generado automáticamente para registro interno.", size=8)
    c.setFillColorRGB(0, 0, 0)

    c.showPage()
    c.save()
    return buffer.getvalue()


def _mask_email(addr: str) -> str:
    addr = (addr or '').strip()
    at = addr.find('@')
    if at <= 1:
        return addr
    local = addr[:at]
    domain = addr[at:]
    if len(local) <= 2:
        return local[0] + '*' * max(0, len(local) - 1) + domain
    return local[0] + '***' + local[-1] + domain

def _with_signature(message: str) -> str:
    message = (message or "").rstrip()
    if message.endswith("FM Servicios Generales"):
        return message
    return f"{message}{SIGNATURE}"


def _format_clp(value) -> str:
    try:
        val_int = int(Decimal(value))
        return f"{val_int:,}".replace(",", ".")
    except Exception:
        return "-"

# ---------- Páginas públicas ----------
# Public: landing y catálogo
def inicio(request):
    destacados = Servicio.objects.filter(publicado=True).order_by("orden")[:6]
    return render(request, "menu/index.html", {"destacados": destacados})

def nosotros(request):
    return render(request, "menu/nosotros.html")

def _find_tecnico_by_slug(slug: str):
    if not slug:
        return None
    obj = Tecnico.objects.filter(slug=slug, activo=True).first()
    if not obj:
        return None
    return {
        "slug": obj.slug,
        "nombre": f"{obj.nombre} {obj.apellido or ''}".strip(),
        "especialidad": obj.especialidad or (obj.servicio.titulo if getattr(obj, "servicio", None) else "Tecnico"),
        "email": obj.correo,
    }

def _get_tecnico_account(user):
    if not user:
        return None
    # Si el usuario tiene rol de tecnico, usa su correo/rut para buscar el tecnico activo
    try:
        if getattr(user, "rol", "") == User.Rol.TECNICO:
            tec_obj = (
                Tecnico.objects.filter(activo=True, correo__iexact=getattr(user, "email", "")).first()
                or (Tecnico.objects.filter(activo=True, rut=getattr(user, "rut", "")).first() if getattr(user, "rut", "") else None)
            )
            if tec_obj:
                return {
                    "slug": tec_obj.slug,
                    "code": TECHNICIAN_ACCESS_CODE,
                    "nombre": f"{tec_obj.nombre} {tec_obj.apellido or ''}".strip(),
                    "especialidad": tec_obj.especialidad or (tec_obj.servicio.titulo if getattr(tec_obj, "servicio", None) else "Tecnico"),
                    "email": (tec_obj.correo or "").strip().lower(),
                }
    except Exception:
        pass

    username = (getattr(user, "username", "") or "").strip().lower()
    email = (getattr(user, "email", "") or "").strip().lower()
    for key, data in TECHNICIAN_ACCOUNTS.items():
        key_norm = (key or "").strip().lower()
        email_norm = (data.get("email") or "").strip().lower()
        if username == key_norm or (email and email_norm and email == email_norm):
            slug = data.get("slug")
            base_info = _find_tecnico_by_slug(slug)
            return {
                "slug": slug,
                "code": data.get("code") or TECHNICIAN_ACCESS_CODE,
                "nombre": data.get("nombre") or (base_info.get("nombre") if base_info else ""),
                "especialidad": base_info.get("especialidad") if base_info else "",
                "email": email_norm or email,
            }
    return None

def _get_tecnico_for_service(nombre: str):
    norm = (nombre or "").strip().lower()
    if norm:
        for keyword, slug in SERVICE_TECH_MAP.items():
            if keyword in norm:
                info = _find_tecnico_by_slug(slug)
                if info:
                    return info
    obj = Tecnico.objects.filter(activo=True).order_by("nombre", "apellido", "id").first()
    return (
        {
            "slug": obj.slug,
            "nombre": f"{obj.nombre} {obj.apellido or ''}".strip(),
            "especialidad": obj.especialidad or (obj.servicio.titulo if getattr(obj, "servicio", None) else "Tecnico"),
            "email": obj.correo,
        }
        if obj
        else None
    )

def _region_choices():
    try:
        regiones = Region.objects.all().order_by("nombre")
        if regiones:
            return [("", "Selecciona region")] + [(r.nombre, r.nombre) for r in regiones]
    except Exception:
        pass
    return [("", "Selecciona region")] + [(r, r) for r, _ in CHILE_REGIONES]

def _regiones_json():
    try:
        data = {}
        regiones = Region.objects.prefetch_related("comunas").all()
        if regiones:
            for reg in regiones:
                data[reg.nombre] = [c.nombre for c in reg.comunas.all()]
            return json.dumps(data)
    except Exception:
        pass
    return json.dumps(CHILE_REGIONES_DICT)

def _agendar_visita(
    tecnico_info,
    cliente,
    fecha,
    hora=None,
    direccion="-",
    notas="",
    cotizacion=None,
    correo=None,
    region=None,
    comuna=None,
):
    if not tecnico_info or not tecnico_info.get("slug"):
        raise ValueError("No hay tecnicos activos disponibles. Crea al menos uno desde el panel de admin.")
    return VisitaTecnica.objects.create(
        tecnico_slug=tecnico_info["slug"],
        tecnico_nombre=tecnico_info["nombre"],
        cliente=cliente,
        correo=correo,
        region=region,
        comuna=comuna,
        fecha=fecha,
        hora=hora,
        direccion=direccion or "-",
        notas=notas or "-",
        cotizacion=cotizacion,
    )

def _tecnico_tiene_conflicto(tecnico_slug, fecha, hora, exclude_id=None) -> bool:
    if not (tecnico_slug and fecha and hora):
        return False
    ventana_inicio = datetime.combine(fecha, hora) - timedelta(hours=3)
    ventana_fin = datetime.combine(fecha, hora) + timedelta(hours=3)
    visitas = VisitaTecnica.objects.filter(
        tecnico_slug=tecnico_slug,
        fecha__gte=ventana_inicio.date(),
        fecha__lte=ventana_fin.date(),
    )
    if exclude_id:
        visitas = visitas.exclude(pk=exclude_id)
    for v in visitas:
        if not v.hora:
            continue
        dt = datetime.combine(v.fecha, v.hora)
        if ventana_inicio <= dt <= ventana_fin:
            return True
    return False

def _crear_cotizacion_para_visita_manual(
    cliente: str,
    correo: str,
    servicio_nombre: str,
    direccion: str,
    region: str | None,
    comuna: str | None,
    notas: str,
    fecha_dt,
    hora_dt,
):
    """
    Genera una cotizacion aceptada para registrar la visita manual en el flujo de autorizacion de pago.
    Debe crearse siempre aunque no exista usuario (se genera uno temporal con el correo o uno aleatorio).
    """
    def _rand_pass():
        return get_random_string(12)

    user_target = None
    correo = (correo or "").strip()
    if correo:
        user_target = User.objects.filter(email__iexact=correo).first()
    # Crear usuario temporal si no existe
    if not user_target:
        base_username = slugify(cliente or (correo.split("@")[0] if correo else "")) or "visita"
        username = base_username
        counter = 1
        while User.objects.filter(username=username).exists():
            username = f"{base_username}-{counter}"
            counter += 1
        tmp_email = correo or f"{username}-{uuid4().hex[:6]}@visita.fm"
        tmp_pass = _rand_pass()
        user_target = User.objects.create_user(username=username, email=tmp_email, password=tmp_pass)
        if cliente:
            parts = cliente.split(" ", 1)
            user_target.first_name = parts[0]
            if len(parts) > 1:
                user_target.last_name = parts[1]
        try:
            user_target.rol = User.Rol.CLIENTE
        except Exception:
            pass
        user_target.save()

    servicio_obj = Servicio.objects.filter(titulo__iexact=servicio_nombre).first() if servicio_nombre else None
    fecha_hora_txt = fecha_dt.strftime("%d/%m/%Y") if fecha_dt else "-"
    if hora_dt:
        fecha_hora_txt = f"{fecha_hora_txt} {hora_dt.strftime('%H:%M')}"
    detalle = [
        "Visita agendada manualmente desde agenda interna.",
        f"Cliente: {cliente}",
        f"Fecha/Hora: {fecha_hora_txt}",
        f"Servicio: {servicio_nombre or '-'}",
        f"Direccion: {direccion or '-'}",
        f"Region/Comuna: {(region or '-')}/{(comuna or '-')}",
    ]
    if notas:
        detalle.append(f"Notas: {notas}")
    try:
        return Cotizacion.objects.create(
            usuario=user_target,
            servicio=servicio_obj,
            asunto=servicio_nombre or "Visita tecnica",
            mensaje="\n".join(detalle),
            lugar_servicio=direccion or "-",
            region=region or None,
            comuna=comuna or None,
            estado=Cotizacion.Estado.ACEPTADA,
            resuelto_en=timezone.now(),
        )
    except Exception as exc:
        # Intento final con correo aleatorio para no perder el registro
        logger.exception("No se pudo crear cotizacion para visita manual (reintentando): %s", exc)
        fallback_email = f"visita-{uuid4().hex[:8]}@fm.tmp"
        user_fallback = User.objects.create_user(username=f"visita-{uuid4().hex[:6]}", email=fallback_email, password=_rand_pass())
        return Cotizacion.objects.create(
            usuario=user_fallback,
            servicio=servicio_obj,
            asunto=servicio_nombre or "Visita tecnica",
            mensaje="\n".join(detalle),
            lugar_servicio=direccion or "-",
            region=region or None,
            comuna=comuna or None,
            estado=Cotizacion.Estado.ACEPTADA,
            resuelto_en=timezone.now(),
        )

def _enviar_correo_visita_agendada(cliente, correo, fecha_dt, hora_dt, tecnico_info, direccion, region, comuna, notas):
    if not correo:
        return
    hora_txt = hora_dt.strftime("%H:%M") if hora_dt else "10:00"
    cuerpo = (
        "Hola {nombre},\n\n"
        "Agendamos una visita t�cnica con los siguientes datos:\n"
        "- Fecha: {fecha}\n"
        "- Hora: {hora} (nuestro horario es de 08:00 a 20:00)\n"
        "- T�cnico asignado: {tecnico}\n"
        "- Direccion: {direccion}\n"
        "- Regi�n/Comuna: {region}/{comuna}\n\n"
        "Notas: {notas}\n\n"
        "Saludos,\nFM Servicios Generales"
    ).format(
        nombre=cliente or "cliente",
        fecha=fecha_dt.strftime("%d/%m/%Y"),
        hora=hora_txt,
        tecnico=tecnico_info["nombre"],
        direccion=direccion or "-",
        region=region or "-",
        comuna=comuna or "-",
        notas=notas or "-",
    )
    try:
        send_email(
            "Visita t�cnica agendada",
            [correo],
            text_body=_with_signature(cuerpo),
            from_email=settings.DEFAULT_FROM_EMAIL,
        )
    except Exception:
        logger.exception("No se pudo enviar correo de visita manual")

def _enviar_correo_pago_autorizado(cot, total, request):
    correo = (cot.usuario.email or "").strip() if cot.usuario else ""
    if not correo:
        return
    monto_txt = f"${int(total):,}".replace(",", ".")
    pay_url = request.build_absolute_uri(reverse("cotizacion_pagar", args=[cot.pk]))
    texto = [
        f"Hola {cot.usuario.get_full_name() or cot.usuario.username},",
        "",
        f"Autorizamos el pago de tu Cotizacion #{cot.id}.",
        f"Monto total: {monto_txt}",
        f"Servicio: {(cot.servicio.titulo if cot.servicio else cot.asunto) or '-'}",
        f"Ubicacion: {cot.region or '-'} / {cot.comuna or '-'}",
        "",
        f"Puedes pagar directamente en este enlace: {pay_url}",
        "",
        "Saludos,",
        "FM Servicios Generales",
    ]
    html = f"""
    <p>Hola {cot.usuario.get_full_name() or cot.usuario.username},</p>
    <p>Autorizamos el pago de tu Cotizacion #{cot.id}.</p>
    <ul style="color:#111827;">
      <li><strong>Monto total:</strong> {monto_txt}</li>
      <li><strong>Servicio:</strong> {(cot.servicio.titulo if cot.servicio else cot.asunto) or '-'}</li>
      <li><strong>Ubicacion:</strong> {(cot.region or '-')}/{(cot.comuna or '-')}</li>
    </ul>
    <p>
      <a href="{pay_url}" style="display:inline-block;padding:12px 18px;background:#00135d;color:#fff;font-weight:700;text-decoration:none;border-radius:8px;">
        Pagar ahora
      </a>
    </p>
    <p>Si el botón no funciona, copia y pega este enlace en tu navegador:<br>{pay_url}</p>
    """
    try:
        send_email(
            f"Pago autorizado - Cotizacion #{cot.id}",
            [correo],
            text_body=_with_signature("\n".join(texto)),
            html_body=_with_signature(html.replace("\n", "")),
            from_email=settings.DEFAULT_FROM_EMAIL,
        )
    except Exception:
        logger.exception("No se pudo enviar correo de pago autorizado")

def _schedule_visit_for_cot(cot, fecha=None, hora=None):
    servicio_nombre = (cot.servicio.titulo if cot.servicio else cot.asunto) or ""
    tecnico_info = _get_tecnico_for_service(servicio_nombre)
    cliente = cot.usuario.get_full_name() or cot.usuario.username
    fecha_prog = fecha or (timezone.localdate() + timedelta(days=1))
    hora_prog = hora or time(10, 0)
    direccion = cot.lugar_servicio or "-"
    notas = (cot.mensaje or "").strip() or f"Cotizacion #{cot.id}"
    return _agendar_visita(
        tecnico_info,
        cliente,
        fecha_prog,
        hora_prog,
        direccion=direccion,
        notas=notas,
        cotizacion=cot,
        correo=cot.usuario.email,
        region=cot.region,
        comuna=cot.comuna,
    )

def _split_points(text):
    points = []
    for raw in (text or "").splitlines():
        clean = (raw or "").strip()
        if not clean:
            continue
        clean = clean.lstrip("•*- ").strip()
        if clean:
            points.append(clean)
    return points

def servicios_list(request):
    servicios = Servicio.objects.filter(publicado=True).order_by("orden","titulo")
    for servicio in servicios:
        servicio.point_list = _split_points(servicio.contenido_md)
    return render(request, "menu/servicios.html", {"servicios": servicios})


# ---------- CRUD Servicios (solo admin/staff) ----------
# Admin: gestion de servicios
@login_required
def servicios_admin_list(request):
    if not (request.user.is_staff or request.user.is_superuser):
        messages.warning(request, "No tienes permiso para gestionar servicios.")
        return redirect("servicios")
    servicios = Servicio.objects.all().order_by("orden", "titulo")
    return render(request, "menu/servicios_admin_list.html", {"servicios": servicios})


@login_required
def servicio_crear(request):
    if not (request.user.is_staff or request.user.is_superuser):
        messages.warning(request, "No tienes permiso para gestionar servicios.")
        return redirect("servicios")
    if request.method == 'POST':
        form = ServicioForm(request.POST)
        if form.is_valid():
            servicio = form.save()
            imagenes = request.FILES.getlist("imagenes")
            for idx, img in enumerate(imagenes):
                ServicioImagen.objects.create(servicio=servicio, imagen=img, orden=idx)
            messages.success(request, "Servicio creado.")
            return redirect('servicios_admin_crud')
    else:
        form = ServicioForm()
    return render(request, 'menu/servicios_admin_form.html', {'form': form, 'modo': 'crear', 'imagenes': []})


@login_required
def servicio_editar(request, pk: int):
    if not (request.user.is_staff or request.user.is_superuser):
        messages.warning(request, "No tienes permiso para gestionar servicios.")
        return redirect("servicios")
    s = get_object_or_404(Servicio, pk=pk)
    if request.method == 'POST':
        form = ServicioForm(request.POST, instance=s)
        if form.is_valid():
            servicio = form.save()
            imagenes = request.FILES.getlist("imagenes")
            offset = servicio.imagenes.count()
            for idx, img in enumerate(imagenes):
                ServicioImagen.objects.create(servicio=servicio, imagen=img, orden=offset + idx)
            messages.success(request, "Servicio actualizado.")
            return redirect('servicios_admin_crud')
    else:
        form = ServicioForm(instance=s)
    return render(
        request,
        'menu/servicios_admin_form.html',
        {'form': form, 'modo': 'editar', 'servicio': s, 'imagenes': s.imagenes.all()},
    )


@login_required
def servicio_eliminar(request, pk: int):
    if not (request.user.is_staff or request.user.is_superuser):
        messages.warning(request, "No tienes permiso para gestionar servicios.")
        return redirect("servicios")
    s = get_object_or_404(Servicio, pk=pk)
    if request.method == 'POST':
        titulo = s.titulo
        s.delete()
        messages.success(request, f"Servicio '{titulo}' eliminado.")
        return redirect('servicios_admin_crud')
    return redirect('servicios_admin_crud')

def servicio_detalle(request, slug):
    s = get_object_or_404(Servicio, slug=slug, publicado=True)
    return render(request, "menu/servicio_detalle.html", {"servicio": s})

def contacto(request):
    if not request.user.is_authenticated:
        messages.info(request, "Inicia sesión o regístrate para enviar una solicitud.")
        login_url = reverse("login")
        return redirect(f"{login_url}?next={request.path}")
    if request.method == "POST":
        form = ContactoForm(request.POST)
        if form.is_valid():
            contacto = form.save()
            target_user = request.user if request.user.is_authenticated else None
            if not target_user:
                email = (form.cleaned_data.get("email") or "").strip().lower()
                if email:
                    target_user = User.objects.filter(email__iexact=email).first()
                if not target_user:
                    base_username = slugify(form.cleaned_data.get("nombre") or email.split("@")[0] if email else "") or "contacto"
                    username = base_username
                    counter = 1
                    while User.objects.filter(username=username).exists():
                        username = f"{base_username}-{counter}"
                        counter += 1
                    temp_email = email or f"{username}-{uuid4().hex[:6]}@contact.fm"
                    temp_pass = User.objects.make_random_password()
                    target_user = User.objects.create_user(username=username, email=temp_email, password=temp_pass)
                    target_user.first_name = form.cleaned_data.get("nombre") or ""
                    target_user.last_name = form.cleaned_data.get("apellido") or ""
                    try:
                        target_user.rol = User.Rol.CLIENTE
                    except Exception:
                        pass
                    target_user.save()

            lugar_servicio = (form.cleaned_data.get("lugar_servicio") or "").strip()
            region = (form.cleaned_data.get("region") or "").strip()
            comuna = (form.cleaned_data.get("comuna") or "").strip()
            visita_programada = None
            try:
                servicio = None
                tipo_serv = form.cleaned_data.get("tipo_servicio")
                if tipo_serv:
                    servicio = Servicio.objects.filter(titulo__iexact=tipo_serv).first()
                detalles = [
                    f"Teléfono: {form.cleaned_data.get('telefono') or '-'}",
                    f"Lugar: {form.cleaned_data.get('lugar_servicio') or '-'}",
                    f"Región/Comuna: {(form.cleaned_data.get('region') or '-')}/{(form.cleaned_data.get('comuna') or '-')}",
                ]
                cuerpo = (form.cleaned_data.get("mensaje") or "").strip()
                mensaje = "\n".join(detalles) + ("\n\n" + cuerpo if cuerpo else "")
                if target_user:
                    cot = Cotizacion.objects.create(
                        usuario=target_user,
                        servicio=servicio,
                        asunto=form.cleaned_data.get("asunto"),
                        mensaje=mensaje,
                        lugar_servicio=lugar_servicio or None,
                        region=region or None,
                        comuna=comuna or None,
                    )
                    if comuna.lower() == "cabo de hornos":
                        cot.estado = Cotizacion.Estado.RECHAZADA
                        cot.motivo_rechazo = "No contamos con cobertura en Cabo de Hornos."
                        cot.resuelto_en = timezone.now()
                        cot.save(update_fields=["estado", "motivo_rechazo", "resuelto_en"])
                    else:
                        visita_programada = _schedule_visit_for_cot(cot)
            except Exception:
                visita_programada = None

            # Aviso por correo al usuario
            correo_usuario = (form.cleaned_data.get("email") or "").strip()
            if correo_usuario:
                comuna = (form.cleaned_data.get("comuna") or "").strip()
                if comuna.lower() == "cabo de hornos":
                    cuerpo_usuario = (
                        "Hola {nombre},\n\n"
                        "Recibimos tu solicitud, pero actualmente no contamos con cobertura en Cabo de Hornos.\n"
                        "Si deseas coordinar un servicio en otra Ubicacion, escríbenos nuevamente.\n\n"
                        "Gracias por considerar a FM Servicios Generales."
                    ).format(nombre=form.cleaned_data.get("nombre") or "cliente")
                else:
                    fecha_visita = visita_programada.fecha.strftime("%d/%m/%Y") if visita_programada else "Por definir"
                    hora_visita = visita_programada.hora.strftime("%H:%M") if visita_programada and visita_programada.hora else "10:00"
                    tecnico_nombre = visita_programada.tecnico_nombre if visita_programada else "Uno de nuestros tecnicos"
                    cuerpo_usuario = (
                        "Hola {nombre},\n\n"
                        "Recibimos tu solicitud correctamente y la estamos revisando. "
                        "Pronto enviaremos la Cotizacion formal.\n\n"
                        "Gracias por contactarnos."
                    ).format(
                        nombre=form.cleaned_data.get("nombre") or "cliente",
                    )
                try:
                    send_email(
                        "Hemos recibido tu solicitud",
                        [correo_usuario],
                        text_body=_with_signature(cuerpo_usuario),
                        from_email=settings.DEFAULT_FROM_EMAIL,
                    )
                except Exception:
                    pass

            # Aviso al administrador
            destino_admin = (
                getattr(settings, "CONTACT_NOTIFICATION_EMAIL", None)
                or getattr(settings, "DEFAULT_NOTIFICATION_EMAIL", None)
                or getattr(settings, "DEFAULT_FROM_EMAIL", None)
            )
            if destino_admin:
                cuerpo_admin = (
                    "Nuevo contacto recibido:\n\n"
                    "Nombre: {nombre} {apellido}\n"
                    "Correo: {correo}\n"
                    "Teléfono: {telefono}\n"
                    "Asunto: {asunto}\n"
                    "Servicio: {servicio}\n"
                    "Lugar: {lugar}\n"
                    "Ubicacion: {region}/{comuna}\n"
                    "Mensaje:\n{mensaje}"
                ).format(
                    nombre=form.cleaned_data.get("nombre") or "-",
                    apellido=form.cleaned_data.get("apellido") or "",
                    correo=correo_usuario or "-",
                    telefono=form.cleaned_data.get("telefono") or "-",
                    asunto=form.cleaned_data.get("asunto") or "-",
                    servicio=form.cleaned_data.get("tipo_servicio") or "-",
                    lugar=form.cleaned_data.get("lugar_servicio") or "-",
                    region=form.cleaned_data.get("region") or "-",
                    comuna=form.cleaned_data.get("comuna") or "-",
                    mensaje=form.cleaned_data.get("mensaje") or "-",
                )
                try:
                    send_email(
                        "Nuevo contacto recibido",
                        [destino_admin],
                        text_body=_with_signature(cuerpo_admin),
                        from_email=settings.DEFAULT_FROM_EMAIL,
                    )
                except Exception:
                    pass

            messages.success(request, "!Gracias! Recibimos tu mensaje.")
            return redirect("contacto")
    else:
        initial = {}
        if request.user.is_authenticated:
            initial = {
                "nombre": getattr(request.user, "first_name", "") or "",
                "apellido": getattr(request.user, "last_name", "") or "",
                "email": getattr(request.user, "email", "") or "",
                "telefono": getattr(request.user, "telefono", "") or "",
            }
        form = ContactoForm(initial=initial)
    # Refrescar opciones de región desde BD (si existen) y pasar comunas en JSON
    try:
        regiones_db = list(Region.objects.all().order_by("nombre"))
    except Exception:
        regiones_db = []
    if regiones_db:
        region_choices = [("", "Selecciona region")] + [(r.nombre, r.nombre) for r in regiones_db]
        form.fields["region"].choices = region_choices
    regiones_json = _regiones_json()
    return render(request, "menu/contacto.html", {"form": form, "regiones_json": regiones_json})

# ---------- Auth ----------
# Registro/login con 2FA y recuperación
def registro_view(request):
    if request.method == "POST":
        form = RegistroForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            try:
                user.tipo_usuario = User.TipoUsuario.PERSONA
            except Exception:
                pass
            # asegurar rol CLIENTE para nuevos registros
            try:
                user.rol = User.Rol.CLIENTE
            except Exception:
                pass
            # marcar consentimiento si viene el checkbox
            if form.cleaned_data.get("acepta_privacidad"):
                user.acepta_privacidad_at = timezone.now()
            user.email = form.cleaned_data["email"].lower()
            user.telefono = form.cleaned_data.get("telefono")
            user.rut = form.cleaned_data.get("rut")
            user.fecha_nacimiento = form.cleaned_data.get("fecha_nacimiento")
            user.acepta_boletin = False
            # Pregunta y respuesta de recuperación (desde campos dinámicos del form)
            sq = (form.cleaned_data.get("security_question") or "").strip()
            sa = (form.cleaned_data.get("security_answer") or "").strip().lower()
            user.security_question = sq or None
            user.security_answer_hash = make_password(sa) if sa else None
            user.save()
            messages.success(request, "Cuenta creada. Inicia sesión.")
            return redirect("login")
            # Mostrar errores de validación para entender por qué no guarda
            for field, errs in form.errors.items():
                for err in errs:
                    messages.error(request, f"{field}: {err}")
    else:
        form = RegistroForm()
    return render(request, "menu/registro.html", {"form": form})

def login_view(request):
    if request.method == "POST":
        post_data = request.POST.copy()
        raw_ident = (post_data.get("username") or "").strip()
        if raw_ident:
            try:
                user_match = User.objects.filter(models.Q(email__iexact=raw_ident) | models.Q(username__iexact=raw_ident)).order_by("date_joined", "id").first()
                if user_match:
                    post_data["username"] = user_match.username
            except Exception:
                pass
        form = LoginForm(request, data=post_data)
        if form.is_valid():
            user = form.get_user()

            # Superusuario: solo requiere el código maestro interno
            if user.is_superuser:
                request.session['login_2fa_user_id'] = user.id
                request.session['login_2fa_mode'] = 'admin'
                request.session.pop('login_2fa_code_id', None)
                request.session.pop('login_2fa_last_sent_at', None)
                request.session.pop('login_2fa_debug_code', None)
                messages.info(request, "Ingresa tu código especial de administrador para continuar.")
                return redirect("login_2fa_verify")

            tecnico_account = _get_tecnico_account(user)
            if tecnico_account:
                request.session['login_2fa_user_id'] = user.id
                request.session['login_2fa_mode'] = 'tech'
                request.session['login_2fa_tech_slug'] = tecnico_account.get("slug")
                request.session.pop('login_2fa_code_id', None)
                request.session.pop('login_2fa_last_sent_at', None)
                request.session.pop('login_2fa_debug_code', None)
                messages.info(request, "Ingresa tu codigo especial de tecnico para continuar.")
                return redirect("login_2fa_verify")

            # Validar correo destino del usuario autenticado
            target_email = (user.email or '').strip().lower()
            try:
                validate_email(target_email)
            except DjangoValidationError:
                messages.error(request, "Tu cuenta no tiene un correo valido configurado. Actualiza tu perfil o contacta soporte.")
                return redirect("login")

            # Generar Código 2FA por correo
            try:
                LoginCode.objects.filter(user=user, used=False).update(used=True)
            except Exception:
                pass
            code = f"{secrets.randbelow(1_000_000):06d}"
            token = secrets.token_urlsafe(24)
            expires_at = timezone.now() + timedelta(minutes=10)
            lc = LoginCode.objects.create(user=user, code=code, token=token, expires_at=expires_at)

            # Guardar en sesión para verificación posterior
            request.session['login_2fa_user_id'] = user.id
            request.session['login_2fa_code_id'] = lc.id
            request.session['login_2fa_last_sent_at'] = timezone.now().timestamp()
            request.session['login_2fa_mode'] = 'email'

            # Enviar correo con Código y enlace "Sí, soy yo"
            context = {
                "user": user,
                "code": code,
                "minutes": 10,
                "approve_url": request.build_absolute_uri(
                    f"/login/approve/{token}/"
                ),
                "site_name": "FM SERVICIOS GENERALES",
            }
            subject = render_to_string("registration/login_2fa_subject.txt", context).strip()
            text_body = render_to_string("registration/login_2fa_email.txt", context)
            text_body = _with_signature(text_body)
            html_body = render_to_string("registration/login_2fa_email.html", context)
            ok_api = send_email(subject, [target_email], text_body=text_body, html_body=html_body, from_email=settings.DEFAULT_FROM_EMAIL)

            # En desarrollo sin proveedor configurado, mostrar Código en pantalla
            try:
                has_api = bool(getattr(settings, 'RESEND_API_KEY', None) or getattr(settings, 'SENDGRID_API_KEY', None))
                is_smtp = settings.EMAIL_BACKEND == 'django.core.mail.backends.smtp.EmailBackend'
                if settings.DEBUG and not (has_api or is_smtp):
                    request.session['login_2fa_debug_code'] = code
            except Exception:
                pass

            if ok_api:
                messages.info(request, f"Enviamos el código de verificación a { _mask_email(target_email) }.")
            else:
                messages.error(request, "No fue posible enviar el código. Revisa la configuración de correo.")
            return redirect("login_2fa_verify")
        else:
            # Credenciales inválidas u otro error de autenticación
            messages.error(request, "Usuario o contraseña incorrectos. Inténtalo nuevamente.")
    else:
        form = LoginForm(request)
    return render(request, "menu/login.html", {"form": form})


def login_2fa_verify(request):
    uid = request.session.get('login_2fa_user_id')
    mode = request.session.get('login_2fa_mode', 'email')
    code_id = request.session.get('login_2fa_code_id')
    is_admin_mode = mode == 'admin'
    is_tech_mode = mode == 'tech'
    if not uid or ((not is_admin_mode and not is_tech_mode) and not code_id):
        messages.error(request, "sesión de verificación no encontrada. Intenta iniciar sesión nuevamente.")
        return redirect('login')
    try:
        user = User.objects.get(id=uid)
    except User.DoesNotExist:
        messages.error(request, "Usuario no encontrado.")
        return redirect('login')

    # Cooldown para reenvío (solo para modo correo)
    cooldown = 10
    remaining = 0
    if not is_admin_mode and not is_tech_mode:
        last_sent = request.session.get('login_2fa_last_sent_at')
        now_ts = timezone.now().timestamp()
        if last_sent:
            delta = int(cooldown - (now_ts - float(last_sent)))
            remaining = max(0, delta)

    form = Login2FACodeForm()

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'resend':
            if is_admin_mode or is_tech_mode:
                messages.warning(request, "Este acceso solo permite el código especial. No se envían correos.")
            else:
                if remaining > 0:
                    messages.warning(request, f"Espera {remaining}s para reenviar el código.")
                else:
                    try:
                        LoginCode.objects.filter(user=user, used=False).update(used=True)
                    except Exception:
                        pass
                    code = f"{secrets.randbelow(1_000_000):06d}"
                    token = secrets.token_urlsafe(24)
                    expires_at = timezone.now() + timedelta(minutes=10)
                    lc = LoginCode.objects.create(user=user, code=code, token=token, expires_at=expires_at)

                    request.session['login_2fa_code_id'] = lc.id
                    request.session['login_2fa_last_sent_at'] = timezone.now().timestamp()

                    context = {
                        "user": user,
                        "code": code,
                        "minutes": 10,
                        "approve_url": request.build_absolute_uri(
                            f"/login/approve/{token}/"
                        ),
                        "site_name": "FM SERVICIOS GENERALES",
                    }
                    subject = render_to_string("registration/login_2fa_subject.txt", context).strip()
                    text_body = render_to_string("registration/login_2fa_email.txt", context)
                    text_body = _with_signature(text_body)
                    html_body = render_to_string("registration/login_2fa_email.html", context)
                    target_email = (user.email or '').strip().lower()
                    ok_api = send_email(subject, [target_email], text_body=text_body, html_body=html_body, from_email=settings.DEFAULT_FROM_EMAIL)
                    if ok_api:
                        messages.success(request, "Nuevo código enviado.")
                    else:
                        messages.error(request, "No fue posible enviar el código. Revisa la configuración de correo.")

                    try:
                        has_api = bool(getattr(settings, 'RESEND_API_KEY', None) or getattr(settings, 'SENDGRID_API_KEY', None))
                        is_smtp = settings.EMAIL_BACKEND == 'django.core.mail.backends.smtp.EmailBackend'
                        if settings.DEBUG and not (has_api or is_smtp):
                            request.session['login_2fa_debug_code'] = code
                    except Exception:
                        pass

                last_sent = request.session.get('login_2fa_last_sent_at')
                if last_sent:
                    delta = int(cooldown - (timezone.now().timestamp() - float(last_sent)))
                    remaining = max(0, delta)

        else:
            form = Login2FACodeForm(request.POST)
            if form.is_valid():
                code = form.cleaned_data['code'].strip()
                if is_admin_mode:
                    if code == ADMIN_ACCESS_CODE:
                        login(request, user)
                        messages.success(request, f"Bienvenido, {user.get_full_name() or user.username}.")
                        request.session.pop('login_2fa_user_id', None)
                        request.session.pop('login_2fa_code_id', None)
                        request.session.pop('login_2fa_last_sent_at', None)
                        request.session.pop('login_2fa_mode', None)
                        request.session.pop('login_2fa_tech_slug', None)
                        return redirect('index')
                    messages.error(request, "Código inválido.")
                elif is_tech_mode:
                    tech_info = _get_tecnico_account(user)
                    tech_code = tech_info.get("code") if tech_info else None
                    if tech_code and code == tech_code:
                        login(request, user)
                        welcome = tech_info.get("nombre") or user.get_full_name() or user.username
                        messages.success(request, f"Bienvenido, {welcome}. Tu agenda está lista.")
                        request.session.pop('login_2fa_user_id', None)
                        request.session.pop('login_2fa_code_id', None)
                        request.session.pop('login_2fa_last_sent_at', None)
                        request.session.pop('login_2fa_mode', None)
                        request.session.pop('login_2fa_tech_slug', None)
                        return redirect('perfil')
                    messages.error(request, "Código inválido.")
                else:
                    lc = (
                        LoginCode.objects
                        .filter(user=user, code=code, used=False)
                        .order_by('-created_at')
                        .first()
                    )
                    if not lc or not lc.is_valid():
                        messages.error(request, "Código inválido o expirado.")
                    else:
                        lc.used = True
                        lc.save(update_fields=["used"])
                        login(request, user)
                        messages.success(request, f"Bienvenido, {user.get_full_name() or user.username}.")
                        request.session.pop('login_2fa_user_id', None)
                        request.session.pop('login_2fa_code_id', None)
                        request.session.pop('login_2fa_last_sent_at', None)
                        request.session.pop('login_2fa_mode', None)
                        request.session.pop('login_2fa_tech_slug', None)
                        return redirect('index')
    else:
        form = Login2FACodeForm()

    debug_code = request.session.get('login_2fa_debug_code') if (settings.DEBUG and not is_admin_mode and not is_tech_mode) else None
    context = {
        "form": form,
        "minutes": 10,
        "resend_remaining": remaining,
        "debug_code": debug_code,
        "admin_mode": is_admin_mode,
        "tech_mode": is_tech_mode,
    }
    return render(request, 'menu/login_2fa_verify.html', context)


def login_2fa_approve(request, token: str):
    lc = (
        LoginCode.objects
        .filter(token=token, used=False)
        .order_by('-created_at')
        .first()
    )
    if not lc or not lc.is_valid():
        messages.error(request, "Enlace inválido o expirado.")
        return redirect('login')
    user = lc.user
    lc.used = True
    lc.save(update_fields=["used"])
    login(request, user)
    messages.success(request, f"Bienvenido, {user.get_full_name() or user.username}.")
    # Limpiar sesión si existía
    request.session.pop('login_2fa_user_id', None)
    request.session.pop('login_2fa_code_id', None)
    request.session.pop('login_2fa_mode', None)
    return redirect('index')

def logout_view(request):
    logout(request)
    messages.info(request, "sesión cerrada.")
    return redirect("login")

@login_required
def perfil_view(request):
    try:
        request.user.refresh_from_db()
    except Exception:
        pass
    tech_info = _get_tecnico_account(request.user)
    empresa_form_open = False
    company_form = CompanyForm(instance=request.user)
    if request.method == "POST" and request.POST.get("action") == "update_company":
        company_form = CompanyForm(request.POST, instance=request.user)
        if company_form.is_valid():
            company_form.save()
            messages.success(request, "Datos de empresa actualizados.")
            return redirect("perfil")
        empresa_form_open = True

    has_company = any(
        [
            getattr(request.user, "empresa_nombre", ""),
            getattr(request.user, "empresa_rut", ""),
            getattr(request.user, "empresa_encargado", ""),
            getattr(request.user, "empresa_encargado_rut", ""),
            getattr(request.user, "empresa_ubicacion", ""),
        ]
    )
    ctx = {
        "company_form": company_form,
        "empresa_form_open": empresa_form_open,
        "has_company": has_company,
    }
    if tech_info:
        visitas_qs = (
            VisitaTecnica.objects.filter(tecnico_slug=tech_info["slug"])
            .select_related("cotizacion", "cotizacion__usuario", "cotizacion__servicio")
            .order_by("fecha", "hora", "id")
        )
        visitas = list(visitas_qs)
        cotizaciones = []
        vistos = set()
        for v in visitas:
            if v.cotizacion_id and v.cotizacion_id not in vistos:
                vistos.add(v.cotizacion_id)
                cotizaciones.append(v.cotizacion)
        hoy = timezone.localdate()
        ctx.update({
            "tecnico": tech_info,
            "visitas": visitas,
            "cotizaciones_asignadas": cotizaciones,
            "stats": {
                "total_cotizaciones": len(cotizaciones),
                "visitas_programadas": len(visitas),
                "visitas_hoy": sum(1 for v in visitas if v.fecha == hoy),
                "visitas_proximas": sum(1 for v in visitas if v.fecha and v.fecha >= hoy),
            },
            "access_code": tech_info.get("code"),
        })
    return render(request, "menu/perfil.html", ctx)


@login_required
def perfil_editar(request):
    user = request.user
    profile_form = ProfileForm(instance=user)
    pass_form = PasswordByQuestionForm()
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'update_profile':
            profile_form = ProfileForm(request.POST, instance=user)
            if profile_form.is_valid():
                profile_form.save()
                messages.success(request, 'Perfil actualizado correctamente.')
                return redirect('perfil')
        elif action == 'change_password':
            pass_form = PasswordByQuestionForm(request.POST)
            if pass_form.is_valid():
                user.set_password(pass_form.cleaned_data['new_password1'])
                user.save()
                update_session_auth_hash(request, user)
                messages.success(request, 'Contrase\u00f1a actualizada.')
                return redirect('perfil')
    ctx = {
        'profile_form': profile_form,
        'pass_form': pass_form,
    }
    return render(request, 'menu/editar_perfil.html', ctx)


@login_required
def admin_dashboard(request):
    if not (request.user.is_staff or request.user.is_superuser):
        messages.warning(request, "No tienes permiso para acceder al panel de administración.")
        return redirect("index")

    stats = {
        "usuarios": User.objects.count(),
        "clientes": User.objects.filter(rol=User.Rol.CLIENTE).count(),
        "servicios": Servicio.objects.count(),
        "documentos": Documento.objects.count(),
        "cotizaciones": Cotizacion.objects.count(),
    }
    quick_links = [
        {"url": "documentos_admin", "label": "Documentos", "desc": "Sube, comparte, administra y revisa la biblioteca completa."},
        {"url": "servicios_admin_crud", "label": "Servicios", "desc": "Crea, edita o elimina servicios publicados."},
        {"url": "servicio_crear", "label": "Nuevo servicio", "desc": "Publica rápidamente un servicio destacado."},
        {"url": "cotizaciones_admin", "label": "Cotizaciones pendientes", "desc": "Gestiona las solicitudes en curso."},
        {"url": "cotizaciones_registro", "label": "Registro de cotizaciones", "desc": "Revisa las solicitudes aceptadas o rechazadas."},
        {"url": "gestion_insumos", "label": "Gestión de insumos", "desc": "Añade insumos y asócialos a un servicio."},
        {"url": "agenda_visitas", "label": "Agenda de visitas", "desc": "Coordina las visitas técnicas programadas."},
        {"url": "agenda_calendario", "label": "Crear agenda", "desc": "Calendario con disponibilidad y visitas de técnicos."},
        {"url": "tecnicos_panel", "label": "Técnicos", "desc": "Revisa la agenda por técnico."},
        {"url": "perfil_editar", "label": "Mi perfil", "desc": "Actualiza tus datos o credenciales de acceso."},
    ]
    return render(request, "menu/administrar.html", {"stats": stats, "quick_links": quick_links})


@login_required
def admin_dashboard_stats(request):
    if not (request.user.is_staff or request.user.is_superuser):
        return JsonResponse({"error": "forbidden"}, status=403)
    stats = {
        "usuarios": User.objects.count(),
        "clientes": User.objects.filter(rol=User.Rol.CLIENTE).count(),
        "servicios": Servicio.objects.count(),
        "documentos": Documento.objects.count(),
        "cotizaciones": Cotizacion.objects.count(),
        "cotizaciones_pendientes": Cotizacion.objects.filter(estado=Cotizacion.Estado.PENDIENTE).count(),
    }
    return JsonResponse(stats)


@login_required
def agenda_visitas(request):
    if not (request.user.is_staff or request.user.is_superuser):
        messages.warning(request, "Solo el personal autorizado puede acceder a la agenda.")
        return redirect("index")

    visitas = VisitaTecnica.objects.select_related("cotizacion").all().order_by("fecha", "hora", "id")
    servicios_lista = Servicio.objects.all().order_by("orden", "titulo")
    try:
        regiones_db = list(Region.objects.prefetch_related("comunas").all().order_by("nombre"))
    except Exception:
        regiones_db = []
    if regiones_db:
        regiones_list = [r.nombre for r in regiones_db]
        regiones_json = json.dumps({r.nombre: [c.nombre for c in r.comunas.all()] for r in regiones_db})
    else:
        regiones_list = [r for r, _ in CHILE_REGIONES]
        regiones_json = json.dumps(CHILE_REGIONES_DICT)
    if request.method == "POST":
        cliente = (request.POST.get("cliente") or "").strip()
        fecha_raw = request.POST.get("fecha") or ""
        hora_raw = (request.POST.get("hora") or "").strip()
        tecnico_id = (request.POST.get("tecnico") or "").strip()
        correo = (request.POST.get("correo") or "").strip()
        region = (request.POST.get("region") or "").strip()
        comuna = (request.POST.get("comuna") or "").strip()
        direccion = (request.POST.get("direccion") or request.POST.get("Direccion") or "").strip()
        notas = (request.POST.get("notas") or "").strip()
        servicio_nombre = (request.POST.get("servicio") or "").strip()
        tecnico_info = _find_tecnico_by_slug(tecnico_id)
        try:
            fecha_dt = datetime.strptime(fecha_raw, "%Y-%m-%d").date()
        except ValueError:
            fecha_dt = None
        try:
            hora_dt = datetime.strptime(hora_raw, "%H:%M").time() if hora_raw else None
        except ValueError:
            hora_dt = None
        if not (cliente and fecha_dt and tecnico_info):
            messages.error(request, "Completa los campos obligatorios y selecciona un tecnico válido.")
        elif _tecnico_tiene_conflicto(tecnico_info["slug"], fecha_dt, hora_dt):
            messages.error(request, "El técnico ya tiene una hora tomada dentro de 3 horas de ese horario.")
        else:
            cotizacion = _crear_cotizacion_para_visita_manual(
                cliente=cliente,
                correo=correo,
                servicio_nombre=servicio_nombre,
                direccion=direccion,
                region=region or None,
                comuna=comuna or None,
                notas=notas,
                fecha_dt=fecha_dt,
                hora_dt=hora_dt,
            )
            _agendar_visita(
                tecnico_info,
                cliente,
                fecha_dt,
                hora=hora_dt,
                direccion=direccion or "-",
                notas=notas,
                correo=correo or None,
                region=region or None,
                comuna=comuna or None,
                cotizacion=cotizacion,
            )
            _enviar_correo_visita_agendada(
                cliente=cliente,
                correo=correo or None,
                fecha_dt=fecha_dt,
                hora_dt=hora_dt,
                tecnico_info=tecnico_info,
                direccion=direccion,
                region=region,
                comuna=comuna,
                notas=notas,
            )
            messages.success(request, "Visita agendada correctamente.")
            return redirect("agenda_visitas")

    selected_region = request.POST.get("region") if request.method == "POST" else ""
    selected_comuna = request.POST.get("comuna") if request.method == "POST" else ""
    return render(
        request,
        "menu/agenda.html",
        {
            "visitas": visitas,
            "tecnicos": [{"slug": t.slug, "nombre": f"{t.nombre} {t.apellido or ''}".strip()} for t in Tecnico.objects.filter(activo=True)],
            "regiones": regiones_list,
            "selected_region": selected_region,
            "selected_comuna": selected_comuna,
            "regiones_json": regiones_json,
            "servicios_lista": servicios_lista,
        },
    )


@login_required
def agenda_calendario(request):
    if not (request.user.is_staff or request.user.is_superuser):
        messages.warning(request, "Solo el personal autorizado puede acceder al calendario.")
        return redirect("index")

    if request.method == "POST":
        cliente = (request.POST.get("cliente") or "").strip()
        fecha_raw = request.POST.get("fecha") or ""
        hora_raw = (request.POST.get("hora") or "").strip()
        tecnico_id = (request.POST.get("tecnico") or "").strip()
        correo = (request.POST.get("correo") or "").strip()
        region = (request.POST.get("region") or "").strip()
        comuna = (request.POST.get("comuna") or "").strip()
        direccion = (request.POST.get("direccion") or request.POST.get("Direccion") or "").strip()
        notas = (request.POST.get("notas") or "").strip()
        servicio_nombre = (request.POST.get("servicio") or "").strip()
        tecnico_info = _find_tecnico_by_slug(tecnico_id)
        try:
            fecha_dt = datetime.strptime(fecha_raw, "%Y-%m-%d").date()
        except ValueError:
            fecha_dt = None
        try:
            hora_dt = datetime.strptime(hora_raw, "%H:%M").time() if hora_raw else None
        except ValueError:
            hora_dt = None
        if not (cliente and fecha_dt and tecnico_info):
            messages.error(request, "Completa los campos obligatorios y selecciona un tecnico válido.")
            return redirect("agenda_calendario")
        if _tecnico_tiene_conflicto(tecnico_info["slug"], fecha_dt, hora_dt):
            messages.error(request, "El técnico ya tiene una hora tomada dentro de 3 horas de ese horario.")
            return redirect("agenda_calendario")
        cotizacion = _crear_cotizacion_para_visita_manual(
            cliente=cliente,
            correo=correo,
            servicio_nombre=servicio_nombre,
            direccion=direccion,
            region=region or None,
            comuna=comuna or None,
            notas=notas,
            fecha_dt=fecha_dt,
            hora_dt=hora_dt,
        )
        _agendar_visita(
            tecnico_info,
            cliente,
            fecha_dt,
            hora=hora_dt,
            direccion=direccion or "-",
            notas=notas,
            correo=correo or None,
            region=region or None,
            comuna=comuna or None,
            cotizacion=cotizacion,
        )
        _enviar_correo_visita_agendada(
            cliente=cliente,
            correo=correo or None,
            fecha_dt=fecha_dt,
            hora_dt=hora_dt,
            tecnico_info=tecnico_info,
            direccion=direccion,
            region=region,
            comuna=comuna,
            notas=notas,
        )
        messages.success(request, "Visita agendada correctamente.")
        return redirect("agenda_calendario")

    today = timezone.localdate()
    mes_param = (request.GET.get("mes") or "").strip()
    try:
        if mes_param:
            first_day = datetime.strptime(mes_param, "%Y-%m").date().replace(day=1)
        else:
            first_day = today.replace(day=1)
    except Exception:
        first_day = today.replace(day=1)
    _, last_day_num = calendar.monthrange(first_day.year, first_day.month)

    weeks = []
    week = []
    start_weekday = first_day.weekday()  # 0 lunes
    for _ in range(start_weekday):
        week.append(None)
    day = 1
    while day <= last_day_num:
        week.append(datetime(first_day.year, first_day.month, day).date())
        if len(week) == 7:
            weeks.append(week)
            week = []
        day += 1
    if week:
        while len(week) < 7:
            week.append(None)
        weeks.append(week)

    last_day = first_day.replace(day=last_day_num)
    visitas_qs = VisitaTecnica.objects.select_related("cotizacion").filter(
        fecha__gte=first_day, fecha__lte=last_day
    )
    tecnico_filtro = (request.GET.get("tecnico") or "").strip()
    if tecnico_filtro:
        visitas_qs = visitas_qs.filter(tecnico_slug=tecnico_filtro)
    visitas = visitas_qs.order_by("fecha", "hora")
    visitas_por_dia = {}
    for v in visitas:
        visitas_por_dia.setdefault(v.fecha, []).append(v)

    tecnicos_total = Tecnico.objects.filter(activo=True).count()
    tecnicos = list(Tecnico.objects.filter(activo=True).order_by("nombre"))
    servicios_lista = Servicio.objects.all().order_by("orden", "titulo")
    try:
        regiones_db = list(Region.objects.prefetch_related("comunas").all().order_by("nombre"))
    except Exception:
        regiones_db = []
    if regiones_db:
        regiones_list = [r.nombre for r in regiones_db]
        regiones_json = json.dumps({r.nombre: [c.nombre for c in r.comunas.all()] for r in regiones_db})
    else:
        regiones_list = [r for r, _ in CHILE_REGIONES]
        regiones_json = json.dumps(CHILE_REGIONES_DICT)

    return render(
        request,
        "menu/agenda_calendario.html",
        {
            "weeks": weeks,
        "today": today,
        "first_day": first_day,
        "prev_month": (first_day - timedelta(days=1)).replace(day=1),
        "next_month": (first_day + timedelta(days=32)).replace(day=1),
        "visitas_por_dia": visitas_por_dia,
        "tecnicos_total": tecnicos_total,
            "tecnicos": tecnicos,
            "servicios_lista": servicios_lista,
            "regiones": regiones_list,
            "regiones_json": regiones_json,
        },
    )


@login_required
def agenda_visita_editar(request, pk: int):
    if not (request.user.is_staff or request.user.is_superuser):
        messages.warning(request, "Solo el personal autorizado puede acceder a este módulo.")
        return redirect("index")
    visita = get_object_or_404(VisitaTecnica.objects.select_related("cotizacion"), pk=pk)
    if getattr(visita, "cotizacion", None) and visita.cotizacion.estado == Cotizacion.Estado.ACEPTADA:
        messages.warning(request, "No puedes editar una visita cuya cotizacion ya fue aceptada.")
        return redirect("agenda_visitas")
    servicios_lista = Servicio.objects.all().order_by("orden", "titulo")
    try:
        regiones_db = list(Region.objects.prefetch_related("comunas").all().order_by("nombre"))
    except Exception:
        regiones_db = []
    if regiones_db:
        regiones_list = [r.nombre for r in regiones_db]
        regiones_json = json.dumps({r.nombre: [c.nombre for c in r.comunas.all()] for r in regiones_db})
    else:
        regiones_list = [r for r, _ in CHILE_REGIONES]
        regiones_json = json.dumps(CHILE_REGIONES_DICT)
    if request.method == "POST":
        cliente = (request.POST.get("cliente") or "").strip()
        fecha_raw = request.POST.get("fecha") or ""
        hora_raw = (request.POST.get("hora") or "").strip()
        tecnico_id = (request.POST.get("tecnico") or "").strip()
        correo = (request.POST.get("correo") or "").strip()
        region = (request.POST.get("region") or "").strip()
        comuna = (request.POST.get("comuna") or "").strip()
        direccion = (request.POST.get("Direccion") or "").strip()
        notas = (request.POST.get("notas") or "").strip()
        tecnico_info = _find_tecnico_by_slug(tecnico_id)
        try:
            fecha_dt = datetime.strptime(fecha_raw, "%Y-%m-%d").date()
        except ValueError:
            fecha_dt = None
        try:
            hora_dt = datetime.strptime(hora_raw, "%H:%M").time() if hora_raw else None
        except ValueError:
            hora_dt = None
        if not (cliente and fecha_dt and tecnico_info):
            messages.error(request, "Completa los campos obligatorios y selecciona un tecnico válido.")
        elif _tecnico_tiene_conflicto(tecnico_info["slug"], fecha_dt, hora_dt, exclude_id=visita.pk):
            messages.error(request, "El técnico ya tiene una hora tomada dentro de 3 horas de ese horario.")
        else:
            visita.cliente = cliente
            visita.fecha = fecha_dt
            visita.hora = hora_dt
            visita.tecnico_slug = tecnico_info["slug"]
            visita.tecnico_nombre = tecnico_info["nombre"]
            visita.correo = correo or None
            visita.region = region or None
            visita.comuna = comuna or None
            visita.direccion = direccion or "-"
            visita.notas = notas or "-"
            visita.save(update_fields=["cliente", "fecha", "hora", "tecnico_slug", "tecnico_nombre", "correo", "region", "comuna", "direccion", "notas"])
            messages.success(request, "Visita actualizada.")
            return redirect("agenda_visitas")
        return render(
            request,
            "menu/agenda_editar.html",
            {
                "visita": visita,
                "tecnicos": [{"slug": t.slug, "nombre": f"{t.nombre} {t.apellido or ''}".strip()} for t in Tecnico.objects.filter(activo=True)],
                "regiones": CHILE_REGIONES,
                "regiones_json": json.dumps(CHILE_REGIONES_DICT),
            },
        )

    # GET o POST con errores: mostrar formulario de ediciï¿½n
    selected_region = visita.region or ""
    selected_comuna = visita.comuna or ""
    return render(
        request,
        "menu/agenda_editar.html",
        {
            "visita": visita,
            "tecnicos": [{"slug": t.slug, "nombre": f"{t.nombre} {t.apellido or ''}".strip()} for t in Tecnico.objects.filter(activo=True)],
            "regiones": regiones_list,
            "regiones_json": regiones_json,
            "selected_region": selected_region,
            "selected_comuna": selected_comuna,
            "servicios_lista": servicios_lista,
        },
    )

@login_required
def agenda_visita_eliminar(request, pk: int):
    if not (request.user.is_staff or request.user.is_superuser):
        messages.warning(request, "Solo el personal autorizado puede acceder a este módulo.")
        return redirect("index")
    visita = get_object_or_404(VisitaTecnica, pk=pk)
    if request.method == "POST":
        visita.delete()
        messages.success(request, "Visita eliminada.")
    return redirect("agenda_visitas")


@login_required
@login_required
@login_required
@login_required
def tecnicos_panel(request):
    is_admin = request.user.is_staff or request.user.is_superuser
    tech_info = _get_tecnico_account(request.user)
    if not (is_admin or tech_info):
        messages.warning(request, "Solo el personal autorizado puede acceder a este modulo.")
        return redirect("index")

    if is_admin and request.method == "POST":
        action = (request.POST.get("action") or "").strip().lower()
        if action == "crear_tecnico":
            nombre = (request.POST.get("nombre") or "").strip()
            apellido = (request.POST.get("apellido") or "").strip()
            correo = (request.POST.get("correo") or "").strip()
            rut = (request.POST.get("rut") or "").strip()
            telefono = (request.POST.get("telefono") or "").strip()
            servicio_slug = (request.POST.get("servicio") or "").strip()
            servicio = Servicio.objects.filter(slug=servicio_slug).first() if servicio_slug else None
            if not (nombre and correo and rut):
                messages.error(request, "Completa nombre, correo y RUT para crear el tecnico.")
            else:
                try:
                    rut_norm = _normalize_rut_strict(rut)
                except Exception:
                    messages.error(request, "Ingresa un RUT válido (ej: 12.345.678-9).")
                    return redirect("tecnicos_panel")
                telefono_norm = None
                if telefono:
                    try:
                        telefono_norm = _normalize_phone_strict(telefono)
                    except Exception:
                        messages.error(request, "Ingresa un teléfono válido (ej: +56 9 1234 5678).")
                        return redirect("tecnicos_panel")
                try:
                    # Evitar duplicados de tecnico por correo/RUT
                    if Tecnico.objects.filter(correo__iexact=correo).exists():
                        messages.error(request, "Ya existe un técnico con ese correo.")
                        return redirect("tecnicos_panel")
                    if Tecnico.objects.filter(rut__iexact=rut_norm).exists():
                        messages.error(request, "Ya existe un técnico con ese RUT.")
                        return redirect("tecnicos_panel")

                    # Crear o reutilizar usuario (no se exige que exista previamente)
                    user = User.objects.filter(email__iexact=correo).first()
                    password_raw = re.sub(r"[^0-9kK]", "", rut_norm)  # rut sin guion ni puntos
                    update_fields = ["first_name", "last_name", "rut", "telefono", "rol", "email", "username"]
                    if not user:
                        username = correo
                        if User.objects.filter(username__iexact=username).exists():
                            messages.error(request, "Ya existe un usuario con ese correo/username.")
                            return redirect("tecnicos_panel")
                        user = User.objects.create_user(username=username, email=correo, password=password_raw)
                    else:
                        # Actualiza password para asegurar acceso del técnico
                        user.set_password(password_raw)
                        user.username = correo
                        update_fields.append("password")
                    user.first_name = nombre
                    user.last_name = apellido or user.last_name
                    user.rut = rut_norm or user.rut
                    if telefono_norm:
                        user.telefono = telefono_norm
                    user.rol = User.Rol.TECNICO
                    user.save(update_fields=update_fields)

                    Tecnico.objects.create(
                        nombre=nombre,
                        apellido=apellido or None,
                        correo=correo,
                        rut=rut_norm,
                        telefono=telefono_norm,
                        servicio=servicio,
                        especialidad=servicio.titulo if servicio else None,
                    )
                    messages.success(request, "Tecnico creado correctamente.")
                    return redirect("tecnicos_panel")
                except Exception as exc:
                    messages.error(request, f"No se pudo crear el tecnico: {exc}")
        if action == "editar_tecnico":
            slug_edit = (request.POST.get("tecnico_slug") or "").strip()
            tec_obj = Tecnico.objects.filter(slug=slug_edit).first()
            if not tec_obj:
                messages.error(request, "Selecciona un tecnico válido para editar.")
            else:
                new_nombre = (request.POST.get("nombre") or "").strip() or tec_obj.nombre
                new_apellido = (request.POST.get("apellido") or "").strip() or tec_obj.apellido
                new_correo = (request.POST.get("correo") or "").strip() or tec_obj.correo
                new_rut = (request.POST.get("rut") or "").strip() or tec_obj.rut
                new_telefono = (request.POST.get("telefono") or "").strip() or tec_obj.telefono
                if new_rut and not _rut_es_valido(new_rut):
                    messages.error(request, "Ingresa un RUT válido (ej: 12.345.678-9).")
                elif new_telefono and not _telefono_es_valido(new_telefono):
                    messages.error(request, "Ingresa un teléfono válido (ej: +56 9 1234 5678).")
                else:
                    tec_obj.nombre = new_nombre
                    tec_obj.apellido = new_apellido
                    tec_obj.correo = new_correo
                    tec_obj.rut = new_rut
                    tec_obj.telefono = new_telefono
                    servicio_slug = (request.POST.get("servicio") or "").strip()
                    tec_obj.servicio = Servicio.objects.filter(slug=servicio_slug).first() if servicio_slug else None
                    tec_obj.especialidad = tec_obj.servicio.titulo if tec_obj.servicio else tec_obj.especialidad
                    tec_obj.save()
                    # También actualiza el usuario existente con el mismo correo para mantener permisos y datos
                    try:
                        user_match = User.objects.filter(email__iexact=tec_obj.correo).first()
                        if user_match:
                            user_match.first_name = tec_obj.nombre
                            user_match.last_name = tec_obj.apellido or user_match.last_name
                            user_match.username = tec_obj.correo
                            user_match.email = tec_obj.correo
                            if tec_obj.rut:
                                user_match.rut = tec_obj.rut
                            if tec_obj.telefono:
                                user_match.telefono = tec_obj.telefono
                            user_match.rol = User.Rol.TECNICO
                            user_match.save(update_fields=["first_name", "last_name", "rut", "telefono", "rol", "username", "email"])
                    except Exception:
                        pass
                    messages.success(request, "Técnico actualizado.")
                    return redirect("tecnicos_panel")
        if action == "eliminar_tecnico":
            slug_borrar = (request.POST.get("tecnico_slug") or "").strip()
            if not slug_borrar:
                messages.error(request, "Selecciona un tecnico para eliminar.")
            else:
                tec_obj = Tecnico.objects.filter(slug=slug_borrar).first()
                if not tec_obj:
                    messages.error(request, "No se encontró el técnico seleccionado.")
                else:
                    tec_obj.delete()
                    messages.success(request, f"Técnico '{tec_obj.nombre}' eliminado.")
                    return redirect("tecnicos_panel")

    tecnicos_db = list(Tecnico.objects.filter(activo=True).select_related("servicio"))
    if is_admin:
        default_slug = tecnicos_db[0].slug if tecnicos_db else None
        selected_slug = request.GET.get("tecnico") or default_slug
    else:
        selected_slug = tech_info["slug"] if tech_info else None

    def _to_entry(obj):
        if isinstance(obj, dict):
            return obj
        servicio = getattr(obj, "servicio", None)
        servicio_slug = servicio.slug if servicio else None
        servicio_titulo = servicio.titulo if servicio else None
        return {
            "slug": obj.slug,
            "nombre": f"{obj.nombre} {obj.apellido or ''}".strip(),
            "especialidad": obj.especialidad or (servicio_titulo or "Tecnico"),
            "servicio": servicio_titulo,
            "servicio_slug": servicio_slug,
            "rut": getattr(obj, "rut", "") or "",
            "telefono": getattr(obj, "telefono", "") or "",
            "correo": getattr(obj, "correo", "") or "",
            "apellido": obj.apellido or "",
            "nombre_raw": obj.nombre,
            "apellido_raw": obj.apellido or "",
        }

    tecnicos_list = [_to_entry(t) for t in tecnicos_db]
    servicio_filter = (request.GET.get("servicio") or "").strip()
    tecnicos_filtrados = tecnicos_list
    if servicio_filter:
        tecnicos_filtrados = [t for t in tecnicos_list if t.get("servicio_slug") == servicio_filter]

    selected = next(
        (t for t in tecnicos_filtrados if t.get("slug") == selected_slug),
        tecnicos_filtrados[0] if tecnicos_filtrados else (tecnicos_list[0] if tecnicos_list else None),
    )
    if not selected:
        selected = {
            "slug": "",
            "nombre": "Sin tecnicos",
            "especialidad": "",
            "servicio": None,
            "servicio_slug": None,
            "apellido": "",
            "apellido_raw": "",
            "nombre_raw": "",
            "rut": "",
            "telefono": "",
            "correo": "",
        }

    visitas_filtradas = VisitaTecnica.objects.filter(tecnico_slug=selected["slug"]).order_by("fecha", "hora", "id") if selected and selected.get("slug") else VisitaTecnica.objects.none()
    hoy = timezone.localdate()
    total_visitas = visitas_filtradas.count()
    visitas_hoy = visitas_filtradas.filter(fecha=hoy).count()
    visitas_proximas = visitas_filtradas.filter(fecha__gte=hoy).count()
    pendientes = visitas_filtradas.filter(cotizacion__estado=Cotizacion.Estado.PENDIENTE).count()
    aceptadas = visitas_filtradas.filter(cotizacion__estado=Cotizacion.Estado.ACEPTADA).count()
    proceso_pago = visitas_filtradas.filter(cotizacion__estado=Cotizacion.Estado.PROCESO_PAGO).count()
    completadas = visitas_filtradas.filter(cotizacion__estado=Cotizacion.Estado.COMPLETADA).count()
    finalizadas = 0
    servicios_publicos = Servicio.objects.all().order_by("orden", "titulo")

    return render(
        request,
        "menu/tecnicos.html",
        {
            "tecnicos": tecnicos_filtrados,
            "tecnicos_all": tecnicos_list,
            "selected": selected,
            "visitas": visitas_filtradas,
            "stats": {
                "total": total_visitas,
                "hoy": visitas_hoy,
                "proximas": visitas_proximas,
                "pendientes": pendientes,
                "aceptadas": aceptadas,
                "completadas": completadas,
                "proceso_pago": proceso_pago,
                "finalizadas": finalizadas,
            },
            "region_choices": [("", "Selecciona region")] + [(r, r) for r, _ in CHILE_REGIONES],
            "servicios": servicios_publicos,
            "servicio_filter": servicio_filter,
            "tech_messages": messages.get_messages(request),
            "is_admin": is_admin,
        },
    )


# ---------- cotizaciones ----------
# Flujo de cotizaciones y agenda de tecnicos
@login_required
def cotizacion_create(request):
    messages.info(request, "La creacion de nuevas cotizaciones desde el perfil ya no esta disponible. Revisa tus cotizaciones existentes.")
    return redirect("cotizacion_mis")

@login_required
def cotizacion_mis(request):
    cotizaciones = (
        Cotizacion.objects.filter(usuario=request.user)
        .prefetch_related("trabajos")
        .order_by("-creado_en")
    )
    for c in cotizaciones:
        try:
            trabajos_all = list(c.trabajos.all())
            c.tiene_trabajo = bool(trabajos_all)
            c.completada = c.estado == Cotizacion.Estado.COMPLETADA or any(
                t.estado == Trabajo.Estado.COMPLETADO for t in trabajos_all
            )
        except Exception:
            c.completada = False
            c.tiene_trabajo = False
    return render(request, "menu/cotizacion_mis.html", {"cotizaciones": cotizaciones})

@login_required
def cotizaciones_admin_list(request):
    if not (request.user.is_staff or request.user.is_superuser):
        messages.warning(request, "No tienes permiso para ver las cotizaciones.")
        return redirect("index")
    cotizaciones = (
        Cotizacion.objects.select_related("usuario", "servicio", "edificio")
        .filter(estado=Cotizacion.Estado.PENDIENTE)
        .order_by("-creado_en")
    )
    return render(
        request,
        "menu/cotizaciones_admin.html",
        {
            "cotizaciones": cotizaciones,
            "tecnicos": [{"slug": t.slug, "nombre": f"{t.nombre} {t.apellido or ''}".strip(), "especialidad": t.especialidad or (t.servicio.titulo if getattr(t, 'servicio', None) else "")} for t in Tecnico.objects.filter(activo=True)],
        },
    )


@login_required
def cotizacion_enviar(request, pk: int):
    if not (request.user.is_staff or request.user.is_superuser):
        messages.warning(request, "No tienes permiso para enviar cotizaciones.")
        return redirect("index")
    cot = get_object_or_404(Cotizacion.objects.select_related("usuario", "servicio"), pk=pk)
    if cot.estado != Cotizacion.Estado.PENDIENTE:
        messages.error(request, "Solo puedes enviar cotizaciones en estado pendiente.")
        return redirect("cotizaciones_admin")
    if request.method != "POST":
        return redirect("cotizaciones_admin")

    precio_raw = (request.POST.get("precio") or "").strip()
    tecnico_slug = (request.POST.get("tecnico") or "").strip()
    fecha_raw = (request.POST.get("fecha") or "").strip()
    hora_raw = (request.POST.get("hora") or "").strip()

    if not (precio_raw and tecnico_slug):
        messages.error(request, "Ingresa precio y selecciona un tecnico antes de enviar.")
        return redirect("cotizaciones_admin")
    try:
        precio = Decimal(precio_raw).quantize(Decimal("1"))
    except InvalidOperation:
        messages.error(request, "El precio ingresado no es válido.")
        return redirect("cotizaciones_admin")

    tecnico_info = _find_tecnico_by_slug(tecnico_slug)
    if not tecnico_info:
        messages.error(request, "Selecciona un tecnico válido.")
        return redirect("cotizaciones_admin")

    try:
        fecha_dt = datetime.strptime(fecha_raw, "%Y-%m-%d").date() if fecha_raw else None
    except ValueError:
        fecha_dt = None
    try:
        hora_dt = datetime.strptime(hora_raw, "%H:%M").time() if hora_raw else None
    except ValueError:
        hora_dt = None

    # Validar conflicto de agenda (si se envía fecha/hora)
    if fecha_dt and hora_dt and _tecnico_tiene_conflicto(tecnico_info["slug"], fecha_dt, hora_dt):
        messages.error(request, "El técnico ya tiene una hora tomada dentro de 3 horas de ese horario.")
        return redirect("cotizaciones_admin")

    # Actualizar o crear visita asociada con tecnico/fecha/hora
    visita = cot.visitas.order_by("fecha", "hora", "id").first()
    if not visita:
        visita = VisitaTecnica.objects.create(
            cotizacion=cot,
            tecnico_slug=tecnico_info["slug"],
            tecnico_nombre=tecnico_info["nombre"],
            cliente=cot.usuario.get_full_name() or cot.usuario.username,
            correo=cot.usuario.email,
            region=cot.region,
            comuna=cot.comuna,
            fecha=fecha_dt or timezone.localdate(),
            hora=hora_dt or time(10, 0),
            direccion=cot.lugar_servicio or "-",
            notas=cot.mensaje or "-",
        )
    else:
        visita.tecnico_slug = tecnico_info["slug"]
        visita.tecnico_nombre = tecnico_info["nombre"]
        visita.fecha = fecha_dt or visita.fecha
        visita.hora = hora_dt or visita.hora
        visita.correo = cot.usuario.email or visita.correo
        visita.save(update_fields=["tecnico_slug", "tecnico_nombre", "fecha", "hora", "correo"])

    cot.presupuesto_estimado = precio
    cot.estado = Cotizacion.Estado.ENVIADA
    cot.resuelto_en = None
    cot.motivo_rechazo = ""
    cot.save(update_fields=["presupuesto_estimado", "estado", "resuelto_en", "motivo_rechazo"])

    # Correo al cliente
    correo_usuario = (cot.usuario.email or visita.correo or "").strip()
    if correo_usuario:
        fecha_txt = visita.fecha.strftime("%d/%m/%Y") if visita and visita.fecha else ""
        hora_txt = visita.hora.strftime("%H:%M") if visita and visita.hora else ""
        tecnico_nombre = visita.tecnico_nombre if visita and visita.tecnico_nombre else tecnico_info["nombre"]
        Direccion_txt = visita.direccion if visita and getattr(visita, "direccion", None) else (cot.lugar_servicio or "-")
        costo_txt = _format_clp(cot.presupuesto_estimado or precio)
        body_lines = [
            f"Hola {cot.usuario.get_full_name() or cot.usuario.username},",
            "",
            "Ya revisamos tu solicitud y preparamos la Cotizacion para que la revises.",
            "",
            f"Valor estimado: ${costo_txt} CLP",
            "",
            "Visita programada:",
            f"- Fecha: {fecha_txt or 'Por definir'}",
            f"- Hora: {hora_txt or '10:00'} (horario 08:00 a 20:00)",
            f"- Tecnico asignado: {tecnico_nombre}",
            f"- Direccion: {Direccion_txt or '-'}",
            f"- Region/Comuna: {(cot.region or '-')}/{(cot.comuna or '-')}",
            "",
            "Resumen de tu solicitud:",
            f"- Servicio: {cot.servicio.titulo if cot.servicio else '-'}",
            f"- Asunto: {cot.asunto or '-'}",
            f"- Mensaje: {cot.mensaje or '-'}",
            "",
            "Ingresa a tu cuenta y ve a 'Mis cotizaciones' para aceptar o rechazar esta propuesta.",
        ]
        body = "\n".join(body_lines)
        ok_api = False
        try:
            ok_api = send_email(
                "Tu Cotizacion esta lista",
                [correo_usuario],
                text_body=_with_signature(body),
                from_email=settings.DEFAULT_FROM_EMAIL,
            )
        except Exception:
            ok_api = False
        if not ok_api:
            messages.warning(request, "No fue posible enviar el correo al cliente. Revisa la configuracion de email.")

    messages.success(request, "Cotizacion enviada al cliente para su aprobacion.")
    return redirect("cotizaciones_admin")

@login_required
def cotizaciones_registro(request):
    if not (request.user.is_staff or request.user.is_superuser):
        messages.warning(request, "No tienes permiso para ver el registro.")
        return redirect("index")
    cotizaciones = (
        Cotizacion.objects.select_related("usuario", "servicio", "edificio")
        .exclude(estado=Cotizacion.Estado.PENDIENTE)
        .order_by("-resuelto_en", "-creado_en")
    )
    return render(request, "menu/cotizaciones_registro.html", {"cotizaciones": cotizaciones})


@login_required
def gestion_insumos(request):
    if not (request.user.is_staff or request.user.is_superuser):
        messages.warning(request, "Solo el personal autorizado puede acceder a gestion de insumos.")
        return redirect("index")

    servicios_lista = Servicio.objects.all().order_by("orden", "titulo")
    insumos_lista = Insumo.objects.select_related("servicio").all().order_by("-creado_en", "nombre")

    if request.method == "POST":
        action = (request.POST.get("action") or "").strip()
        if action == "delete":
            ins_id = request.POST.get("insumo_id")
            if ins_id:
                Insumo.objects.filter(pk=ins_id).delete()
                messages.success(request, "Insumo eliminado.")
            return redirect("gestion_insumos")

        nombre = (request.POST.get("nombre") or "").strip()
        precio = (request.POST.get("precio") or "").strip()
        cantidad = (request.POST.get("cantidad") or "").strip()
        servicio_slug = (request.POST.get("servicio") or "").strip()
        insumo_id = request.POST.get("insumo_id")

        if not nombre or not precio or not cantidad:
            messages.error(request, "Completa nombre, precio y cantidad del insumo.")
            return redirect("gestion_insumos")

        servicio_txt = "-"
        srv = None
        if servicio_slug:
            srv = Servicio.objects.filter(slug=servicio_slug).first()
            if srv:
                servicio_txt = srv.titulo
        try:
            precio_val = Decimal(precio)
        except InvalidOperation:
            messages.error(request, "Precio inválido.")
            return redirect("gestion_insumos")
        try:
            cantidad_val = int(cantidad)
        except ValueError:
            messages.error(request, "Cantidad inválida.")
            return redirect("gestion_insumos")
        if cantidad_val <= 0:
            messages.error(request, "La cantidad debe ser mayor a 0.")
            return redirect("gestion_insumos")

        if insumo_id:
            Insumo.objects.filter(pk=insumo_id).update(
                nombre=nombre, precio=precio_val, cantidad=cantidad_val, servicio=srv
            )
            messages.success(
                request,
                f"Insumo actualizado: {nombre} (precio {precio}, cantidad {cantidad}, servicio {servicio_txt}).",
            )
        else:
            existente = Insumo.objects.filter(nombre=nombre, servicio=srv).first()
            if existente:
                existente.cantidad = (existente.cantidad or 0) + cantidad_val
                # Mantenemos el precio existente para evitar discrepancias
                existente.save(update_fields=["cantidad"])
                messages.success(
                    request,
                    f"Insumo actualizado: {nombre} (cantidad acumulada {existente.cantidad}, precio ${int(existente.precio):,}. Se mantiene el precio registrado, servicio {servicio_txt}).".replace(",", "."),
                )
            else:
                Insumo.objects.create(
                    nombre=nombre,
                    servicio=srv,
                    precio=precio_val,
                    cantidad=cantidad_val,
                )
                messages.success(
                    request,
                    f"Insumo guardado: {nombre} (precio {precio}, cantidad {cantidad}, servicio {servicio_txt}).",
                )
        return redirect("gestion_insumos")

    return render(
        request,
        "menu/gestion_insumos.html",
        {"servicios": servicios_lista, "insumos": insumos_lista},
    )


@login_required
def cotizacion_responder(request, pk: int):
    cot = get_object_or_404(Cotizacion, pk=pk)
    if not (request.user == cot.usuario or request.user.is_staff or request.user.is_superuser):
        messages.error(request, "No tienes permiso para actualizar esta Cotizacion.")
        return redirect("cotizacion_mis")
    if request.method != "POST":
        return redirect("cotizacion_mis")

    action = (request.POST.get("action") or "").lower()
    if cot.estado != Cotizacion.Estado.ENVIADA:
        messages.error(request, "Esta Cotizacion aºn no ha sido enviada para tu revisión.")
        return redirect("cotizacion_mis")
    if action == "aceptar":
        cot.estado = Cotizacion.Estado.ACEPTADA
        cot.motivo_rechazo = ""
        cot.resuelto_en = timezone.now()
        update_fields = ["estado", "motivo_rechazo", "resuelto_en"]
        if not cot.presupuesto_estimado:
            cot.presupuesto_estimado = FIXED_PRICE
            update_fields.append("presupuesto_estimado")
        cot.save(update_fields=update_fields)

        visita = cot.visitas.order_by("fecha", "hora", "id").first()
        if not visita:
            visita = _schedule_visit_for_cot(cot)

        correo = (cot.usuario.email or "").strip()
        if correo:
            fecha_visita = visita.fecha.strftime("%d/%m/%Y") if visita else "Por definir"
            hora_visita = visita.hora.strftime("%H:%M") if visita and visita.hora else "10:00"
            Direccion_visita = visita.direccion if visita else (cot.lugar_servicio or "-")
            tecnico_nombre = visita.tecnico_nombre if visita else "Nuestro tecnico asignado"
            costo_val = cot.presupuesto_estimado
            costo_txt = f"{int(costo_val):,}".replace(",", ".") if costo_val is not None else "-"
            cuerpo = (
                "Hola {nombre},\n\n"
                "Tu Cotizacion fue aceptada. Muchas gracias por confiar en nosotros.\n\n"
                "Resumen:\n"
                "- Asunto: {asunto}\n"
                "- Servicio: {servicio}\n"
                "- Ubicacion: {region}/{comuna}\n"
                "- Mensaje: {mensaje}\n"
                "- Costo estimado: ${costo}\n\n"
                "Visita estimada:\n"
                "- Fecha: {fecha_visita}\n"
                "- Hora: {hora_visita} (horario 08:00 a 20:00)\n"
                "- Tecnico asignado: {tecnico}\n"
                "- Direccion: {direccion}\n"
            ).format(
                nombre=cot.usuario.get_full_name() or cot.usuario.username,
                asunto=cot.asunto or "-",
                servicio=cot.servicio.titulo if cot.servicio else "-",
                region=cot.region or "-",
                comuna=cot.comuna or "-",
                mensaje=cot.mensaje or "-",
                costo=costo_txt,
                fecha_visita=fecha_visita,
                hora_visita=hora_visita,
                tecnico=tecnico_nombre,
                direccion=Direccion_visita,
            )
            try:
                send_email(
                    "Cotizacion aceptada",
                    [correo],
                    text_body=_with_signature(cuerpo),
                    from_email=settings.DEFAULT_FROM_EMAIL,
                )
            except Exception:
                pass

        messages.success(request, "Cotizacion aceptada.")
    elif action == "rechazar":
        cot.estado = Cotizacion.Estado.RECHAZADA
        cot.motivo_rechazo = "Rechazada por el cliente desde Mis cotizaciones"
        cot.resuelto_en = timezone.now()
        cot.save(update_fields=["estado", "motivo_rechazo", "resuelto_en"])

        correo = (cot.usuario.email or "").strip()
        if correo:
            cuerpo = (
                "Hola {nombre},\n\n"
                "Tu Cotizacion fue rechazada.\n\n"
                "Resumen:\n"
                "- Asunto: {asunto}\n"
                "- Servicio: {servicio}\n"
                "- Ubicacion: {region}/{comuna}\n"
                "- Mensaje: {mensaje}\n\n"
                "Motivo del rechazo:\n"
                "- {motivo}\n"
            ).format(
                nombre=cot.usuario.get_full_name() or cot.usuario.username,
                asunto=cot.asunto or "-",
                servicio=cot.servicio.titulo if cot.servicio else "-",
                region=cot.region or "-",
                comuna=cot.comuna or "-",
                mensaje=cot.mensaje or "-",
                motivo=cot.motivo_rechazo or "Motivo no especificado",
            )
            try:
                send_email(
                    "Cotizacion rechazada",
                    [correo],
                    text_body=_with_signature(cuerpo),
                    from_email=settings.DEFAULT_FROM_EMAIL,
                )
            except Exception:
                pass

        messages.info(request, "Cotizacion rechazada.")
    else:
        messages.error(request, "Accion no valida.")

    return redirect("cotizacion_mis")


@login_required
def cotizacion_rechazar(request, pk: int):
    if not (request.user.is_staff or request.user.is_superuser):
        messages.warning(request, "No tienes permiso para actualizar cotizaciones.")
        return redirect("cotizaciones_admin")
    cot = get_object_or_404(Cotizacion, pk=pk)
    if request.method == "POST":
        motivo = (request.POST.get("motivo") or "").strip()
        if not motivo:
            messages.error(request, "Debes indicar un motivo de rechazo.")
            return redirect("cotizaciones_admin")
        cot.estado = Cotizacion.Estado.RECHAZADA
        cot.motivo_rechazo = motivo
        cot.resuelto_en = timezone.now()
        cot.save(update_fields=["estado", "motivo_rechazo", "resuelto_en"])

        correo = (cot.usuario.email or "").strip()
        if correo:
            asunto = "Cotizacion rechazada"
            cuerpo = (
                "Hola {nombre},\n\n"
                "Tu solicitud '{asunto}' fue rechazada con el siguiente motivo:\n"
                "{motivo}\n\n"
                "Si necesitas más información contáctanos."
            ).format(
                nombre=cot.usuario.get_full_name() or cot.usuario.username,
                asunto=cot.asunto or cot.servicio or "cotizacion",
                motivo=motivo,
            )
            try:
                send_email(asunto, [correo], text_body=_with_signature(cuerpo), from_email=settings.DEFAULT_FROM_EMAIL)
            except Exception:
                pass
        messages.success(request, "Cotizacion rechazada.")
    return redirect("cotizaciones_admin")


@login_required
def cotizacion_aceptar(request, pk: int):
    if not (request.user.is_staff or request.user.is_superuser):
        messages.warning(request, "No tienes permiso para actualizar cotizaciones.")
        return redirect("cotizaciones_admin")
    cot = get_object_or_404(Cotizacion, pk=pk)
    if request.method != "POST":
        return redirect("cotizaciones_admin")

    precio_str = (request.POST.get("precio") or "").replace(",", ".").strip()
    precio_decimal = None
    if precio_str:
        try:
            precio_decimal = Decimal(precio_str)
        except (InvalidOperation, ValueError):
            messages.error(request, "Ingresa un precio válido antes de aceptar la Cotizacion.")
            return redirect("cotizaciones_admin")
    else:
        precio_decimal = FIXED_PRICE

    cot.estado = Cotizacion.Estado.ACEPTADA
    cot.motivo_rechazo = ""
    cot.resuelto_en = timezone.now()
    update_fields = ["estado", "motivo_rechazo", "resuelto_en"]
    if precio_decimal is not None:
        cot.presupuesto_estimado = precio_decimal
        update_fields.append("presupuesto_estimado")
    cot.save(update_fields=update_fields)

    visita = cot.visitas.order_by("fecha", "hora", "id").first()
    if not visita:
        visita = _schedule_visit_for_cot(cot)

    correo = (cot.usuario.email or "").strip()
    if correo:
        fecha_visita = visita.fecha.strftime("%d/%m/%Y") if visita else "Por definir"
        hora_visita = visita.hora.strftime("%H:%M") if visita and visita.hora else "10:00"
        Direccion_visita = visita.direccion if visita else (cot.lugar_servicio or "-")
        tecnico_nombre = visita.tecnico_nombre if visita else "Nuestro tecnico asignado"
        cuerpo_usuario = (
            "Hola {nombre},\n\n"
            "Tu Cotizacion fue aceptada.\n\n"
            "Resumen:\n"
            "- Asunto: {asunto}\n"
            "- Servicio: {servicio}\n"
            "- Ubicacion: {region}/{comuna}\n"
            "- Mensaje: {mensaje}\n\n"
            "Visita estimada:\n"
            "- Fecha: {fecha_visita}\n"
            "- Hora: {hora_visita} (nuestro horario es de 08:00 a 20:00)\n"
            "- Técnico asignado: {tecnico}\n"
            "- Direccion: {direccion}\n\n"
            "Saludos,\nFM Servicios Generales"
        ).format(
            nombre=cot.usuario.get_full_name() or "cliente",
            asunto=cot.asunto or "-",
            servicio=cot.servicio.titulo if cot.servicio else "-",
            region=cot.region or "-",
            comuna=cot.comuna or "-",
            mensaje=cot.mensaje or "-",
            fecha_visita=fecha_visita,
            hora_visita=hora_visita,
            tecnico=tecnico_nombre,
            direccion=Direccion_visita,
        )
        try:
            send_email(
                "Cotizacion aceptada",
                [correo],
                text_body=_with_signature(cuerpo_usuario),
                from_email=settings.DEFAULT_FROM_EMAIL,
            )
        except Exception:
            pass
    messages.success(request, "Cotizacion aceptada. Genera el informe para registrar el detalle.")
    return redirect("cotizacion_informe", pk=cot.pk)


@login_required
def cotizacion_informe(request, pk: int):
    is_admin = request.user.is_staff or request.user.is_superuser
    tech_info = _get_tecnico_account(request.user)
    if not (is_admin or tech_info):
        messages.warning(request, "No tienes permisos para generar este informe.")
        return redirect("cotizaciones_admin")
    cot = get_object_or_404(Cotizacion, pk=pk)
    if cot.estado != Cotizacion.Estado.ACEPTADA:
        messages.error(request, "Solo puedes generar informe para una Cotizacion aceptada.")
        return redirect("cotizaciones_admin")
    if tech_info:
        has_visit = cot.visitas.filter(tecnico_slug=tech_info["slug"]).exists()
        if not has_visit:
            messages.error(request, "No tienes visitas asignadas en esta Cotizacion.")
            return redirect("tecnicos_panel")
    if request.method == "POST":
        precio_raw = (request.POST.get("precio") or "").strip()
        insumos_raw = request.POST.get("insumos_json") or "[]"
        trabajos_raw = request.POST.get("trabajos_json") or "[]"
        try:
            insumos_list = json.loads(insumos_raw)
        except Exception:
            insumos_list = []
        try:
            trabajos_list = json.loads(trabajos_raw)
        except Exception:
            trabajos_list = []
        try:
            base_precio = Decimal(precio_raw or "0")
        except (InvalidOperation, ValueError):
            base_precio = Decimal("0")
        trabajos_total = sum(Decimal(str(i.get("price") or 0)) for i in trabajos_list)
        insumos_total = sum(Decimal(str(i.get("price") or 0)) for i in insumos_list)
        # Si se enviaron trabajos, usamos ese total; si no, ocupamos el base_precio.
        neto = (trabajos_total if trabajos_list else base_precio) + insumos_total
        iva = (neto * Decimal("0.19")).quantize(Decimal("1"))
        total = neto + iva

        # Persistir detalle para la factura y el panel
        try:
            cot.items.all().delete()
            if trabajos_list:
                for t in trabajos_list:
                    desc = (t.get("name") or "Trabajo").strip() or "Trabajo"
                    price = Decimal(str(t.get("price") or 0) or "0")
                    if price < 0:
                        price = Decimal("0")
                    CotizacionItem.objects.create(
                        cotizacion=cot, descripcion=f"Trabajo: {desc}", cantidad=Decimal("1"), precio_unit=price
                    )
            if insumos_list:
                for i in insumos_list:
                    desc = (i.get("name") or "Insumo").strip() or "Insumo"
                    price = Decimal(str(i.get("price") or 0) or "0")
                    if price < 0:
                        price = Decimal("0")
                    CotizacionItem.objects.create(
                        cotizacion=cot, descripcion=f"Insumo: {desc}", cantidad=Decimal("1"), precio_unit=price
                    )
            if not trabajos_list and not insumos_list and neto > 0:
                CotizacionItem.objects.create(
                    cotizacion=cot,
                    descripcion=cot.asunto or (cot.servicio.titulo if cot.servicio else "Servicio"),
                    cantidad=Decimal("1"),
                    precio_unit=neto,
                )
        except Exception as exc:  # pragma: no cover - registro de respaldo
            logger.exception("No se pudo guardar detalle de items para cotizacion %s: %s", cot.id, exc)

        # Crear o actualizar trabajo en estado en proceso de pago
        try:
            trabajo = Trabajo.objects.filter(cotizacion=cot).first()
            if not trabajo and cot.edificio and cot.servicio:
                trabajo = Trabajo.objects.create(
                    edificio=cot.edificio,
                    servicio=cot.servicio,
                    cotizacion=cot,
                    titulo=cot.asunto or (cot.servicio.titulo if cot.servicio else f"Trabajo Cotizacion #{cot.id}"),
                    descripcion=cot.mensaje or "",
                    estado=Trabajo.Estado.EN_PROCESO,
                    fecha_programada=timezone.localdate(),
                )
            elif trabajo:
                trabajo.estado = Trabajo.Estado.EN_PROCESO
                trabajo.save(update_fields=["estado"])
        except Exception:
            pass
        # Guardar total antes de crear preferencia MP
        try:
            cot.presupuesto_estimado = total
            cot.estado = Cotizacion.Estado.PROCESO_PAGO
            cot.resuelto_en = timezone.now()
            cot.save(update_fields=["presupuesto_estimado", "estado", "resuelto_en"])
        except Exception as exc:
            logger.exception("No se pudo actualizar cotizacion %s antes de preparar pago: %s", cot.id, exc)
        _enviar_correo_pago_autorizado(cot, total, request)
        messages.success(request, f"Informe generado. Total: ${_format_clp(total)}")
        return redirect("cotizaciones_admin")
    return render(
        request,
        "menu/cotizacion_informe.html",
        {
            "cot": cot,
            "precio": cot.presupuesto_estimado or FIXED_PRICE,
            "insumos_bd": [
                {
                    "id": ins.pk,
                    "name": ins.nombre,
                    "price": float(ins.precio),
                    "servicio": ins.servicio.slug if ins.servicio else "",
                    "servicio_nombre": ins.servicio.titulo if ins.servicio else "",
                }
                for ins in Insumo.objects.select_related("servicio").all().order_by("servicio__titulo", "nombre")
            ],
        },
    )



# ---------- Pagos (Transbank Webpay) ----------
def _tb_options():
    commerce_code = os.environ.get("TB_COMMERCE_CODE") or getattr(settings, "TB_COMMERCE_CODE", "")
    api_key = os.environ.get("TB_API_KEY") or getattr(settings, "TB_API_KEY", "")
    integration = (os.environ.get("TB_INTEGRATION_TYPE") or getattr(settings, "TB_INTEGRATION_TYPE", "TEST")).upper()
    integration_type = IntegrationType.LIVE if integration in {"LIVE", "PROD", "PRODUCTION"} else IntegrationType.TEST
    if not commerce_code or not api_key:
        commerce_code = IntegrationCommerceCodes.WEBPAY_PLUS
        api_key = IntegrationApiKeys.WEBPAY
        integration_type = IntegrationType.TEST
    return WebpayOptions(commerce_code, api_key, integration_type)


def _tb_create_transaction(cot, request, total_override=None):
    # Usa siempre el total autorizado (presupuesto_estimado incluye IVA). Solo cae a items netos si no existe.
    total = float(total_override if total_override is not None else (cot.presupuesto_estimado or cot.total_items or FIXED_PRICE))
    if total <= 0:
        total = 10.0
    buy_order = f"cot{cot.id}"
    session_id = f"user-{getattr(request.user, 'id', 'anon')}-{get_random_string(6)}"
    return_url = getattr(settings, "TB_RETURN_URL", None) or request.build_absolute_uri(reverse("tb_return"))
    tx = Transaction(_tb_options())
    resp = tx.create(buy_order=buy_order, session_id=session_id, amount=total, return_url=return_url)
    token = getattr(resp, "token", None) or (resp.get("token") if isinstance(resp, dict) else None)
    redirect_url = getattr(resp, "url", None) or (resp.get("url") if isinstance(resp, dict) else None)
    cot.tb_token = token
    cot.tb_buy_order = buy_order
    cot.tb_session_id = session_id
    cot.tb_status = "CREATED"
    cot.tb_response_code = None
    cot.tb_auth_code = None
    cot.tb_card_last4 = None
    cot.tb_redirect_url = redirect_url
    cot.estado = Cotizacion.Estado.PROCESO_PAGO
    cot.save(update_fields=["tb_token", "tb_buy_order", "tb_session_id", "tb_status", "tb_response_code", "tb_auth_code", "tb_card_last4", "tb_redirect_url", "estado"])
    return {"token": token, "url": redirect_url, "buy_order": buy_order, "amount": total}


def _tb_commit_transaction(token: str):
    tx = Transaction(_tb_options())
    return tx.commit(token)


def _store_invoice_document(cot: Cotizacion, pdf_bytes: bytes | None):
    """
    Guarda/actualiza la factura PDF como Documento y la sube a Supabase si está configurado.
    """
    if not pdf_bytes:
        return None
    titulo = f"Factura Cotizacion #{cot.id}"
    doc = Documento.objects.filter(titulo=titulo).order_by("-creado_en").first() or Documento(
        titulo=titulo, publico=False, subido_por=cot.usuario
    )
    if not doc.subido_por:
        doc.subido_por = cot.usuario
    doc.publico = False
    doc.categoria = Documento.Categoria.FACTURA
    doc.tags = _normalize_tags(f"{doc.tags or ''}, factura")
    doc.descripcion = (
        f"Factura generada automaticamente el {timezone.localtime().strftime('%d/%m/%Y %H:%M')} "
        f"(pago: {cot.tb_auth_code or cot.tb_status or cot.mp_payment_id or '-'})."
    )

    filename = f"factura_cotizacion_{cot.id}.pdf"
    if doc.archivo and getattr(doc.archivo, "name", None):
        try:
            doc.archivo.delete(save=False)
        except Exception:
            pass
    doc.archivo.save(filename, ContentFile(pdf_bytes), save=False)

    supa_res = _supabase_upload(
        pdf_bytes,
        bucket=getattr(settings, "SUPABASE_BUCKET_FACTURAS", None),
        path=_safe_storage_path(f"factura_{cot.id}", filename, prefix="facturas"),
        content_type="application/pdf",
    )
    if supa_res:
        doc.storage_url = supa_res.get("url") or doc.storage_url
        doc.storage_path = supa_res.get("path") or doc.storage_path
        doc.storage_bucket = supa_res.get("bucket") or getattr(settings, "SUPABASE_BUCKET_FACTURAS", None)
    doc.save()
    return doc














def _send_payment_receipt(cot: Cotizacion, provider: str = "Transbank"):
    correo = (cot.usuario.email or "").strip()
    if not correo:
        return
    # Mostrar el total autorizado (con IVA). Solo cae a neto si no existe total grabado.
    total = float(cot.presupuesto_estimado or cot.total_items or FIXED_PRICE)
    total_txt = f"${{int(total):,}}".replace(",", ".")
    estado_pago = cot.tb_status or cot.mp_payment_status or cot.estado
    referencia = cot.tb_auth_code or cot.tb_token or cot.mp_payment_id or "-"
    cuerpo = (
        "Hola {nombre},\n\n"
        f"Pago realizado con exito en {provider}. Recibimos tu pago correctamente.\n\n"
        "Detalle del pago:\n"
        "- Cotizacion: #{cot_id}\n"
        "- Monto: {monto}\n"
        "- Estado: {estado}\n"
        "- Referencia: {referencia}\n\n"
        "Adjuntamos tu factura en PDF.\n\n"
        "Gracias por confiar en FM Servicios Generales."
    ).format(
        nombre=cot.usuario.get_full_name() or cot.usuario.username,
        cot_id=cot.id,
        monto=total_txt,
        estado=estado_pago,
        referencia=referencia,
    )
    html_body = (
        f"<p>Hola {cot.usuario.get_full_name() or cot.usuario.username},</p>"
        "<p><strong>Pago realizado con exito.</strong> Recibimos tu pago correctamente.</p>"
        "<ul>"
        f"<li><strong>Cotizacion:</strong> #{cot.id}</li>"
        f"<li><strong>Monto:</strong> {total_txt}</li>"
        f"<li><strong>Estado:</strong> {estado_pago}</li>"
        f"<li><strong>Referencia:</strong> {referencia}</li>"
        "</ul>"
        "<p>Adjuntamos tu factura en PDF.</p>"
    )
    html_body = _with_signature(html_body)
    pdf_bytes = None
    try:
        pdf_bytes = _build_invoice_pdf_bytes(cot)
    except Exception:
        pdf_bytes = None
    if pdf_bytes:
        try:
            _store_invoice_document(cot, pdf_bytes)
        except Exception:
            pass
    try:
        if pdf_bytes:
            msg = EmailMultiAlternatives(
                f"Pago realizado con exito - Cotizacion #{cot.id}",
                _with_signature(cuerpo),
                settings.DEFAULT_FROM_EMAIL,
                [correo],
            )
            msg.attach(f"factura_cotizacion_{cot.id}.pdf", pdf_bytes, "application/pdf")
            msg.attach_alternative(html_body, "text/html")
            msg.send()
            return
    except Exception:
        pass
    try:
        send_email(
            f"Pago realizado con exito - Cotizacion #{cot.id}",
            [correo],
            text_body=_with_signature(cuerpo),
            html_body=html_body,
            from_email=settings.DEFAULT_FROM_EMAIL,
        )
    except Exception:
        pass

@csrf_exempt
def tb_return(request):
    token_ws = request.POST.get("token_ws") or request.GET.get("token_ws")
    tbk_buy_order = request.POST.get("TBK_ORDEN_COMPRA") or request.GET.get("TBK_ORDEN_COMPRA")
    target = "cotizacion_mis"
    cot = None
    if token_ws:
        cot = Cotizacion.objects.filter(tb_token=token_ws).first()
    if not cot and tbk_buy_order:
        cot = Cotizacion.objects.filter(tb_buy_order=tbk_buy_order).first()

    if not token_ws:
        if cot:
            cot.tb_status = "ABORTED"
            cot.save(update_fields=["tb_status"])
        messages.warning(request, "Pago cancelado en Transbank.")
        return redirect(target)

    try:
        resp = _tb_commit_transaction(token_ws)
    except Exception as exc:
        if cot:
            cot.tb_status = "ERROR"
            cot.save(update_fields=["tb_status"])
        messages.error(request, f"No se pudo confirmar el pago: {exc}")
        return redirect(target)

    status = getattr(resp, "status", None) or (resp.get("status") if isinstance(resp, dict) else None)
    response_code = getattr(resp, "response_code", None) or (resp.get("response_code") if isinstance(resp, dict) else None)
    authorization_code = getattr(resp, "authorization_code", None) or (resp.get("authorization_code") if isinstance(resp, dict) else None)
    buy_order = getattr(resp, "buy_order", None) or (resp.get("buy_order") if isinstance(resp, dict) else None)
    card_detail = getattr(resp, "card_detail", None) or (resp.get("card_detail") if isinstance(resp, dict) else None)

    if not cot and buy_order:
        cot = Cotizacion.objects.filter(tb_buy_order=buy_order).first()

    success = bool(status == "AUTHORIZED" and response_code == 0)
    if cot:
        last4 = None
        if isinstance(card_detail, dict):
            last4 = card_detail.get("card_number") or card_detail.get("last4") or None
        cot.tb_status = status or cot.tb_status
        cot.tb_response_code = response_code
        cot.tb_auth_code = authorization_code or cot.tb_auth_code
        cot.tb_card_last4 = last4
        if success:
            cot.estado = Cotizacion.Estado.COMPLETADA
            cot.resuelto_en = timezone.now()
        cot.save(update_fields=["tb_status", "tb_response_code", "tb_auth_code", "tb_card_last4", "estado", "resuelto_en"])
        if success:
            _send_payment_receipt(cot, provider="Transbank")
    if success:
        messages.success(request, "Pago aprobado en Transbank.")
    else:
        messages.warning(request, f"Estado de pago: {status or 'DESCONOCIDO'} (codigo {response_code}).")
    return redirect(target)


@login_required
def cotizacion_pagar(request, pk: int):
    cot = get_object_or_404(Cotizacion, pk=pk)
    is_owner = request.user == cot.usuario
    is_admin = request.user.is_staff or request.user.is_superuser
    if not (is_owner or is_admin):
        messages.warning(request, "No puedes pagar esta Cotizacion.")
        return redirect("cotizacion_mis")
    if cot.estado not in (Cotizacion.Estado.ACEPTADA, Cotizacion.Estado.PROCESO_PAGO, Cotizacion.Estado.COMPLETADA):
        messages.error(request, "Solo puedes pagar cotizaciones aceptadas o en proceso de pago.")
        return redirect("cotizacion_mis")
    trabajo = cot.trabajos.first()
    if not trabajo:
        try:
            if cot.edificio and cot.servicio:
                trabajo = Trabajo.objects.create(
                    edificio=cot.edificio,
                    servicio=cot.servicio,
                    cotizacion=cot,
                    titulo=cot.asunto or (cot.servicio.titulo if cot.servicio else f"Trabajo Cotizacion #{cot.id}"),
                    descripcion=cot.mensaje or "",
                    fecha_programada=timezone.localdate(),
                    estado=Trabajo.Estado.PLANIFICADO,
                )
        except Exception:
            trabajo = None
    tb_data = None
    try:
        tb_data = _tb_create_transaction(cot, request)
    except Exception as exc:
        messages.error(request, f"No se pudo iniciar el pago: {exc}")
    return render(
        request,
        "menu/cotizacion_pagar_confirm.html",
        {
            "cot": cot,
            "trabajo": trabajo,
            "tb_token": tb_data.get("token") if tb_data else None,
            "tb_url": tb_data.get("url") if tb_data else None,
            "tb_buy_order": tb_data.get("buy_order") if tb_data else None,
        },
    )


# ---------- Admin: Documentos ----------
# Gestion de documentos para staff
@login_required
def documentos_admin(request):
    if not (request.user.is_staff or request.user.is_superuser):
        messages.warning(request, "No tienes permiso para ver esta sección.")
        return redirect("index")

    if request.method == "POST":
        form = DocumentoForm(request.POST, request.FILES)
        if form.is_valid():
            doc = form.save(commit=False)
            doc.subido_por = request.user
            doc.publico = False
            doc.tags = _normalize_tags(form.cleaned_data.get("tags"))
            file_obj = request.FILES.get("archivo")
            supa_res = None
            if file_obj:
                filename = getattr(file_obj, "name", "") or "documento.pdf"
                supa_res = _supabase_upload(
                    file_obj,
                    bucket=getattr(settings, "SUPABASE_BUCKET_DOCUMENTOS", None),
                    path=_safe_storage_path(doc.titulo, filename, prefix="documentos"),
                    content_type=getattr(file_obj, "content_type", None),
                )
            if supa_res:
                doc.storage_url = supa_res.get("url")
                doc.storage_path = supa_res.get("path")
                doc.storage_bucket = supa_res.get("bucket") or getattr(settings, "SUPABASE_BUCKET_DOCUMENTOS", None)
                try:
                    file_obj.seek(0)
                except Exception:
                    pass
            elif file_obj:
                messages.warning(request, "No se pudo subir a Supabase; el archivo quedará solo en local.")
            doc.save()
            messages.success(request, "Documento subido correctamente.")
            return redirect("documentos_admin")
    else:
        form = DocumentoForm()

    docs = Documento.objects.all()
    filtro_cat = request.GET.get("categoria") or ""
    filtro_tag = (request.GET.get("tag") or "").strip()
    if filtro_cat:
        docs = docs.filter(categoria=filtro_cat)
    if filtro_tag:
        docs = docs.filter(tags__icontains=filtro_tag)
    docs = docs.order_by("-creado_en")
    return render(
        request,
        "menu/documentos_admin.html",
        {"form": form, "docs": docs, "filtro_cat": filtro_cat, "filtro_tag": filtro_tag, "categorias": Documento.Categoria},
    )


def documentos_list(request):
    if request.user.is_authenticated and (request.user.is_staff or request.user.is_superuser):
        docs = Documento.objects.all()
    else:
        docs = Documento.objects.filter(subido_por=request.user) if request.user.is_authenticated else Documento.objects.none()
    filtro_cat = request.GET.get("categoria") or ""
    filtro_tag = (request.GET.get("tag") or "").strip()
    if filtro_cat:
        docs = docs.filter(categoria=filtro_cat)
    if filtro_tag:
        docs = docs.filter(tags__icontains=filtro_tag)
    docs = docs.order_by("-creado_en")
    return render(
        request,
        "menu/documentos_list.html",
        {"docs": docs, "filtro_cat": filtro_cat, "filtro_tag": filtro_tag, "categorias": Documento.Categoria},
    )


@login_required
def documento_editar(request, pk: int):
    if not (request.user.is_staff or request.user.is_superuser):
        messages.warning(request, "No tienes permiso para editar documentos.")
        return redirect("documentos_list")
    doc = get_object_or_404(Documento, pk=pk)
    if request.method == 'POST':
        form = DocumentoEditForm(request.POST, instance=doc)
        if form.is_valid():
            form.save()
            messages.success(request, "Documento actualizado correctamente.")
            return redirect('documentos_list')
    else:
        form = DocumentoEditForm(instance=doc)
    return render(request, 'menu/documento_editar.html', {'form': form, 'doc': doc})


@login_required
def documento_eliminar(request, pk: int):
    if not (request.user.is_staff or request.user.is_superuser):
        messages.warning(request, "No tienes permiso para eliminar documentos.")
        return redirect("documentos_list")
    doc = get_object_or_404(Documento, pk=pk)
    if request.method == 'POST':
        titulo = doc.titulo
        if doc.storage_path:
            _supabase_delete(
                doc.storage_path,
                bucket=doc.storage_bucket or getattr(settings, "SUPABASE_BUCKET_DOCUMENTOS", None),
            )
        if doc.archivo:
            try:
                doc.archivo.delete(save=False)
            except Exception:
                pass
        doc.delete()
        messages.success(request, f"Documento '{titulo}' eliminado correctamente.")
        next_url = request.POST.get("next") or request.GET.get("next")
        if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
            return redirect(next_url)
        return redirect('documentos_list')
    # Por seguridad, redirigir si no es POST
    return redirect('documentos_list')


# ---------- Recuperación por Código ----------
# Recuperación de contraseña vía código
def password_code_request(request):
    if request.method == "POST":
        form = PasswordCodeRequestForm(request.POST)
        if form.is_valid():
            user = form.user  # puede ser None si el email no existe
            if user:
                # invalidar Códigos previos no usados
                PasswordResetCode.objects.filter(user=user, used=False).update(used=True)
                code = f"{secrets.randbelow(1_000_000):06d}"  # 6 dígitos
                expires_at = timezone.now() + timedelta(minutes=15)
                prc = PasswordResetCode.objects.create(user=user, code=code, expires_at=expires_at)

                # preparar correo
                context = {
                    "user": user,
                    "code": code,
                    "minutes": 15,
                    "site_name": "FM SERVICIOS GENERALES",
                }
                subject = render_to_string("registration/password_code_subject.txt", context).strip()
                text_body = render_to_string("registration/password_code_email.txt", context)
                html_body = render_to_string("registration/password_code_email.html", context)

                msg = EmailMultiAlternatives(subject, text_body, settings.DEFAULT_FROM_EMAIL, [user.email])
                msg.attach_alternative(html_body, "text/html")
                msg.send()

            messages.info(request, "Si el correo existe, enviamos un código de verificación.")
            return redirect("password_code_verify")
    else:
        form = PasswordCodeRequestForm()
    return render(request, "menu/password_code_request.html", {"form": form})


def password_code_verify(request):
    if request.method == "POST":
        form = PasswordCodeVerifyForm(request.POST)
        if form.is_valid():
            code = form.cleaned_data["code"].strip()
            # Buscar el Código más reciente aún válido y no usado
            prc = (
                PasswordResetCode.objects
                .filter(code=code, used=False)
                .order_by("-created_at")
                .first()
            )
            if not prc or not prc.is_valid():
                messages.error(request, "Código inválido o expirado.")
                return render(request, "menu/password_code_verify.html", {"form": form})

            user = prc.user
            user.set_password(form.cleaned_data["new_password1"])
            user.save()
            prc.used = True
            prc.save(update_fields=["used"])
            messages.success(request, "Tu contraseña fue actualizada. Inicia sesión.")
            return redirect("login")
        form = PasswordCodeVerifyForm()
    return render(request, "menu/password_code_verify.html", {"form": form})


# ---------- Recuperación por pregunta ----------
# Recuperación de contraseña vía pregunta secreta
def password_question_start(request):
    error = None
    if request.method == 'POST':
        ident = (request.POST.get('identifier') or '').strip()
        user = None
        if ident:
            try:
                user = User.objects.get(username__iexact=ident)
            except User.DoesNotExist:
                user = None
            except User.MultipleObjectsReturned:
                user = User.objects.filter(username__iexact=ident).order_by('date_joined','id').first()
            if not user:
                user = User.objects.filter(email__iexact=ident, is_active=True).order_by('date_joined','id').first()
        if user and user.security_question and user.security_answer_hash:
            request.session['recovery_user_id'] = user.id
            return redirect('password_question_answer')
        else:
            error = 'No es posible recuperar con pregunta para este usuario.'
    return render(request, 'menu/password_question_start.html', {'error': error})


def password_question_answer(request):
    uid = request.session.get('recovery_user_id')
    if not uid:
        return redirect('password_question_start')
    try:
        user = User.objects.get(id=uid)
    except User.DoesNotExist:
        return redirect('password_question_start')
    error = None
    if request.method == 'POST':
        answer = (request.POST.get('answer') or '').strip().lower()
        new1 = request.POST.get('new_password1')
        new2 = request.POST.get('new_password2')
        if not new1 or new1 != new2:
            error = 'Las contraseñas no coinciden.'
        elif user.security_answer_hash and check_password(answer, user.security_answer_hash):
            user.set_password(new1)
            user.save()
            request.session.pop('recovery_user_id', None)
            messages.success(request, 'Tu contraseña fue actualizada. Inicia sesión.')
            return redirect('login')
        else:
            error = 'Respuesta incorrecta.'
    return render(request, 'menu/password_question_answer.html', {'question': user.security_question, 'error': error})


# (2FA eliminado)
