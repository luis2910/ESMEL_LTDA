from django.db import models
from django.contrib.auth.models import AbstractUser
from django.utils import timezone
from django.core.validators import MinValueValidator
from django.utils.text import slugify
from django.conf import settings


# ===== Base con timestamps =====
class TimeStampedModel(models.Model):
    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)
    class Meta:
        abstract = True

# ===== Usuario personalizado =====
class User(AbstractUser):
    email = models.EmailField("email address", unique=True)
    class Rol(models.TextChoices):
        ADMIN = "ADMIN", "Administrador"
        TECNICO = "TECNICO", "Técnico"
        CLIENTE = "CLIENTE", "Cliente"
    class TipoUsuario(models.TextChoices):
        PERSONA = "PERSONA", "Persona natural"
        EMPRESA = "EMPRESA", "Empresa"
    rol = models.CharField(max_length=10, choices=Rol.choices, default=Rol.CLIENTE)
    tipo_usuario = models.CharField(max_length=10, choices=TipoUsuario.choices, default=TipoUsuario.PERSONA)
    telefono = models.CharField(max_length=25, blank=True, null=True)
    rut = models.CharField(max_length=12, unique=True, blank=True, null=True)
    empresa_nombre = models.CharField(max_length=180, blank=True, null=True)
    empresa_rut = models.CharField(max_length=12, unique=True, blank=True, null=True)
    empresa_encargado = models.CharField(max_length=150, blank=True, null=True)
    empresa_encargado_rut = models.CharField(max_length=12, blank=True, null=True)
    empresa_ubicacion = models.CharField(max_length=200, blank=True, null=True)
    fecha_nacimiento = models.DateField(blank=True, null=True)
    acepta_boletin = models.BooleanField(default=False)
    acepta_privacidad_at = models.DateTimeField(blank=True, null=True)
    security_question = models.CharField(max_length=200, blank=True, null=True)
    security_answer_hash = models.CharField(max_length=256, blank=True, null=True)
    def __str__(self):
        return f"{self.get_full_name() or self.username} ({self.rol})"


# ===== Tecnicos =====
class Tecnico(TimeStampedModel):
    slug = models.SlugField(max_length=90, unique=True, blank=True, null=True)
    nombre = models.CharField(max_length=120)
    apellido = models.CharField(max_length=120, blank=True, null=True)
    correo = models.EmailField(unique=True)
    rut = models.CharField(max_length=20, unique=True)
    telefono = models.CharField(max_length=25, blank=True, null=True)
    servicio = models.ForeignKey("Servicio", on_delete=models.SET_NULL, null=True, blank=True, related_name="tecnicos")
    especialidad = models.CharField(max_length=150, blank=True, null=True)
    activo = models.BooleanField(default=True)

    class Meta:
        ordering = ["nombre", "apellido", "id"]
        indexes = [
            models.Index(fields=["slug"]),
            models.Index(fields=["correo"]),
            models.Index(fields=["rut"]),
        ]

    def save(self, *args, **kwargs):
        if not self.slug:
            base = f"{self.nombre or ''} {self.apellido or ''}".strip() or (self.correo or "")
            self.slug = slugify(base)[:80]
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.nombre} {self.apellido or ''}".strip() or self.correo

# ===== Regiones y Comunas =====
class Region(TimeStampedModel):
    nombre = models.CharField(max_length=120, unique=True)

    class Meta:
        ordering = ["nombre"]

    def __str__(self):
        return self.nombre


class Comuna(TimeStampedModel):
    nombre = models.CharField(max_length=120)
    region = models.ForeignKey(Region, on_delete=models.CASCADE, related_name="comunas")

    class Meta:
        ordering = ["region__nombre", "nombre"]
        unique_together = ("region", "nombre")
        indexes = [
            models.Index(fields=["region", "nombre"]),
        ]

    def __str__(self):
        return f"{self.nombre} ({self.region.nombre})"

# ===== CMS: Servicios =====
class Servicio(TimeStampedModel):
    slug = models.SlugField(max_length=80, unique=True, null=True, blank=True, help_text="p.ej. calderas")
    titulo = models.CharField(max_length=120)
    resumen = models.TextField(blank=True, null=True)
    contenido_md = models.TextField(blank=True, null=True)
    publicado = models.BooleanField(default=True)
    orden = models.IntegerField(default=0)
    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.titulo)
        super().save(*args, **kwargs)
    class Meta:
        ordering = ["orden", "titulo"]
    def __str__(self):
        return self.titulo

def servicio_image_path(instance, filename):
    return f"servicios/{instance.servicio.slug}/{filename}"

class ServicioImagen(models.Model):
    servicio = models.ForeignKey(Servicio, on_delete=models.CASCADE, related_name="imagenes")
    imagen = models.ImageField(upload_to=servicio_image_path)
    alt = models.CharField(max_length=200, blank=True, null=True)
    es_portada = models.BooleanField(default=False)
    orden = models.IntegerField(default=0)
    class Meta:
        ordering = ["orden", "id"]

class ServicioFAQ(models.Model):
    servicio = models.ForeignKey(Servicio, on_delete=models.CASCADE, related_name="faqs")
    pregunta = models.CharField(max_length=200)
    respuesta_md = models.TextField()
    orden = models.IntegerField(default=0)
    class Meta:
        ordering = ["orden", "id"]

# ===== Edificios (para mapas/reporting) =====
class Edificio(TimeStampedModel):
    nombre = models.CharField(max_length=160)
    direccion = models.CharField(max_length=200, blank=True, null=True)
    comuna = models.CharField(max_length=120, blank=True, null=True)
    region = models.CharField(max_length=120, blank=True, null=True)
    lat = models.DecimalField(max_digits=9, decimal_places=6, blank=True, null=True)
    lng = models.DecimalField(max_digits=9, decimal_places=6, blank=True, null=True)
    notas = models.TextField(blank=True, null=True)
    class Meta:
        indexes = [
            models.Index(fields=["lat", "lng"]),
            models.Index(fields=["comuna"]),
        ]
    def __str__(self):
        return self.nombre

# ===== Cotizaciones =====
class Cotizacion(TimeStampedModel):
    class Estado(models.TextChoices):
        PENDIENTE = "PENDIENTE", "Pendiente"
        ENVIADA = "ENVIADA", "Enviada al cliente"
        ACEPTADA = "ACEPTADA", "Aceptada"
        RECHAZADA = "RECHAZADA", "Rechazada"
        PROCESO_PAGO = "PROCESO_PAGO", "Proceso de pago"
        COMPLETADA = "COMPLETADA", "Completada"
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="cotizaciones")
    edificio = models.ForeignKey(Edificio, on_delete=models.SET_NULL, null=True, blank=True, related_name="cotizaciones")
    servicio = models.ForeignKey(Servicio, on_delete=models.SET_NULL, null=True, blank=True, related_name="cotizaciones")
    asunto = models.CharField(max_length=200, blank=True, null=True)
    mensaje = models.TextField(blank=True, null=True)
    presupuesto_estimado = models.DecimalField(
        max_digits=14, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(0)]
    )
    lugar_servicio = models.CharField(max_length=150, blank=True, null=True)
    region = models.CharField(max_length=80, blank=True, null=True)
    comuna = models.CharField(max_length=80, blank=True, null=True)
    estado = models.CharField(max_length=15, choices=Estado.choices, default=Estado.PENDIENTE)
    resuelto_en = models.DateTimeField(blank=True, null=True)
    motivo_rechazo = models.TextField(blank=True, null=True)
    mp_preference_id = models.CharField(max_length=80, blank=True, null=True)
    mp_payment_id = models.CharField(max_length=80, blank=True, null=True)
    mp_payment_status = models.CharField(max_length=40, blank=True, null=True)
    mp_init_point = models.TextField(blank=True, null=True)
    tb_token = models.CharField(max_length=120, blank=True, null=True)
    tb_buy_order = models.CharField(max_length=80, blank=True, null=True)
    tb_session_id = models.CharField(max_length=80, blank=True, null=True)
    tb_status = models.CharField(max_length=30, blank=True, null=True)
    tb_auth_code = models.CharField(max_length=40, blank=True, null=True)
    tb_response_code = models.IntegerField(blank=True, null=True)
    tb_card_last4 = models.CharField(max_length=10, blank=True, null=True)
    tb_redirect_url = models.TextField(blank=True, null=True)
    class Meta:
        indexes = [
            models.Index(fields=["estado"]),
            models.Index(fields=["creado_en"]),
        ]
    @property
    def total_items(self):
        return sum([(i.cantidad or 0) * (i.precio_unit or 0) for i in self.items.all()]) or 0
    def marcar_aceptada(self):
        self.estado = Cotizacion.Estado.ACEPTADA
        self.resuelto_en = timezone.now()
        self.save()
    def marcar_rechazada(self):
        self.estado = Cotizacion.Estado.RECHAZADA
        self.resuelto_en = timezone.now()
        self.save()
    def __str__(self):
        return f"Cotización #{self.id} - {self.usuario}"

class CotizacionItem(models.Model):
    cotizacion = models.ForeignKey(Cotizacion, on_delete=models.CASCADE, related_name="items")
    descripcion = models.CharField(max_length=250)
    cantidad = models.DecimalField(max_digits=10, decimal_places=2, default=1, validators=[MinValueValidator(0)])
    precio_unit = models.DecimalField(max_digits=14, decimal_places=2, default=0, validators=[MinValueValidator(0)])


class VisitaTecnica(TimeStampedModel):
    tecnico_slug = models.CharField(max_length=60)
    tecnico_nombre = models.CharField(max_length=120)
    cliente = models.CharField(max_length=150)
    correo = models.EmailField(blank=True, null=True)
    region = models.CharField(max_length=80, blank=True, null=True)
    comuna = models.CharField(max_length=80, blank=True, null=True)
    fecha = models.DateField()
    hora = models.TimeField(blank=True, null=True)
    direccion = models.CharField(max_length=200, blank=True, null=True)
    notas = models.TextField(blank=True, null=True)
    cotizacion = models.ForeignKey(Cotizacion, on_delete=models.SET_NULL, null=True, blank=True, related_name="visitas")

    class Meta:
        ordering = ["fecha", "hora", "id"]

    def __str__(self):
        return f"{self.tecnico_nombre} - {self.fecha}"

# ===== Trabajos (agenda/metricas) =====
class Trabajo(TimeStampedModel):
    class Estado(models.TextChoices):
        PLANIFICADO = "PLANIFICADO", "Planificado"
        EN_PROCESO = "EN_PROCESO", "En proceso"
        COMPLETADO = "COMPLETADO", "Completado"
        CANCELADO = "CANCELADO", "Cancelado"
    edificio = models.ForeignKey(Edificio, on_delete=models.CASCADE, related_name="trabajos")
    servicio = models.ForeignKey(Servicio, on_delete=models.RESTRICT, related_name="trabajos")
    cotizacion = models.ForeignKey(Cotizacion, on_delete=models.SET_NULL, null=True, blank=True, related_name="trabajos")
    titulo = models.CharField(max_length=200)
    descripcion = models.TextField(blank=True, null=True)
    estado = models.CharField(max_length=12, choices=Estado.choices, default=Estado.PLANIFICADO)
    fecha_programada = models.DateField(blank=True, null=True)
    hora_inicio = models.DateTimeField(blank=True, null=True)
    hora_fin = models.DateTimeField(blank=True, null=True)
    class Meta:
        indexes = [
            models.Index(fields=["estado"]),
            models.Index(fields=["edificio", "estado"]),
            models.Index(fields=["fecha_programada"]),
        ]
    def __str__(self):
        return f"{self.titulo} ({self.get_estado_display()})"

# ===== Formulario "Contáctanos" =====
class ContactoWeb(TimeStampedModel):
    nombre = models.CharField(max_length=80, blank=True, null=True)
    apellido = models.CharField(max_length=80, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)
    telefono = models.CharField(max_length=25, blank=True, null=True)
    asunto = models.CharField(max_length=200, blank=True, null=True)
    tipo_servicio = models.CharField(max_length=120, blank=True, null=True)
    lugar_servicio = models.CharField(max_length=150, blank=True, null=True)
    region = models.CharField(max_length=80, blank=True, null=True)
    comuna = models.CharField(max_length=80, blank=True, null=True)
    mensaje = models.TextField(blank=True, null=True)
    boletin = models.BooleanField(default=False)
    acepta_privacidad = models.BooleanField(default=False)
    class Meta:
        verbose_name = "Contacto Web"
        verbose_name_plural = "Contactos Web"


# ===== Documentos =====
def documento_upload_path(instance, filename):
    return f"documentos/{filename}"

class Documento(TimeStampedModel):
    class Categoria(models.TextChoices):
        FACTURA = "FACTURA", "Factura"
        CONTRATO = "CONTRATO", "Contrato"
        IDENTIDAD = "IDENTIDAD", "Identidad"
        PERMISO = "PERMISO", "Permiso"
        OTRO = "OTRO", "Otro"

    titulo = models.CharField(max_length=200)
    descripcion = models.TextField(blank=True, null=True)
    archivo = models.FileField(upload_to=documento_upload_path, blank=True, null=True)
    storage_url = models.URLField(blank=True, null=True)
    storage_path = models.CharField(max_length=255, blank=True, null=True)
    storage_bucket = models.CharField(max_length=120, blank=True, null=True)
    categoria = models.CharField(max_length=20, choices=Categoria.choices, default=Categoria.OTRO)
    tags = models.CharField(max_length=255, blank=True, null=True, help_text="Separar por comas")
    publico = models.BooleanField(default=True)
    subido_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="documentos_subidos",
    )

    class Meta:
        ordering = ["-creado_en", "titulo"]

    def __str__(self):
        return self.titulo

    @property
    def tags_list(self):
        raw = self.tags or ""
        return [t.strip() for t in raw.split(",") if t.strip()]

    @property
    def url(self):
        # Prioriza la URL en almacenamiento externo (Supabase) y luego archivo local
        if self.storage_url:
            return self.storage_url
        if self.archivo:
            try:
                return self.archivo.url
            except Exception:
                pass
        return None


# ===== Insumos =====
class Insumo(TimeStampedModel):
    nombre = models.CharField(max_length=200)
    precio = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(0)])
    cantidad = models.PositiveIntegerField(default=1, validators=[MinValueValidator(1)])
    servicio = models.ForeignKey("Servicio", on_delete=models.SET_NULL, null=True, blank=True, related_name="insumos")

    class Meta:
        ordering = ["-creado_en", "nombre"]

    def __str__(self):
        return f"{self.nombre} (x{self.cantidad})"


# ===== Recuperación por código =====
class PasswordResetCode(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="reset_codes")
    code = models.CharField(max_length=12, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    used = models.BooleanField(default=False)

    class Meta:
        indexes = [
            models.Index(fields=["code", "used"]),
            models.Index(fields=["expires_at"]),
        ]

    def is_valid(self):
        return (not self.used) and timezone.now() <= self.expires_at


# ===== 2FA por correo (inicio de sesión) =====
class LoginCode(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="login_codes")
    code = models.CharField(max_length=12, db_index=True)
    token = models.CharField(max_length=64, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    used = models.BooleanField(default=False)

    class Meta:
        indexes = [
            models.Index(fields=["code", "used"]),
            models.Index(fields=["token", "used"]),
            models.Index(fields=["expires_at"]),
        ]

    def is_valid(self):
        return (not self.used) and timezone.now() <= self.expires_at
