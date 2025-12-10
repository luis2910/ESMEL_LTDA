from django.contrib import admin
from .models import (
    User, Servicio, ServicioImagen, ServicioFAQ,
    Edificio, Cotizacion, CotizacionItem, Trabajo, ContactoWeb,
    Documento,
)

@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ("username", "first_name", "last_name", "email", "rol", "telefono")
    list_filter = ("rol", "acepta_boletin")
    search_fields = ("username", "first_name", "last_name", "email")

class ServicioImagenInline(admin.TabularInline):
    model = ServicioImagen
    extra = 1

class ServicioFAQInline(admin.TabularInline):
    model = ServicioFAQ
    extra = 1

@admin.register(Servicio)
class ServicioAdmin(admin.ModelAdmin):
    list_display = ("titulo", "slug", "publicado", "orden", "creado_en")
    list_filter = ("publicado",)
    search_fields = ("titulo", "resumen")
    prepopulated_fields = {"slug": ("titulo",)}
    inlines = [ServicioImagenInline, ServicioFAQInline]

@admin.register(Edificio)
class EdificioAdmin(admin.ModelAdmin):
    list_display = ("nombre", "comuna", "region", "lat", "lng", "creado_en")
    search_fields = ("nombre", "direccion", "comuna", "region")

class CotizacionItemInline(admin.TabularInline):
    model = CotizacionItem
    extra = 1

@admin.register(Cotizacion)
class CotizacionAdmin(admin.ModelAdmin):
    list_display = ("id", "usuario", "servicio", "estado", "presupuesto_estimado", "creado_en", "resuelto_en")
    list_filter = ("estado", "servicio")
    date_hierarchy = "creado_en"
    search_fields = ("asunto", "mensaje", "usuario__username", "usuario__email")
    inlines = [CotizacionItemInline]

@admin.register(Trabajo)
class TrabajoAdmin(admin.ModelAdmin):
    list_display = ("titulo", "edificio", "servicio", "estado", "fecha_programada")
    list_filter = ("estado", "servicio")
    date_hierarchy = "fecha_programada"
    search_fields = ("titulo", "descripcion", "edificio__nombre")

@admin.register(ContactoWeb)
class ContactoWebAdmin(admin.ModelAdmin):
    list_display = ("nombre", "apellido", "email", "tipo_servicio", "creado_en")
    search_fields = ("nombre", "apellido", "email", "asunto", "mensaje")

@admin.register(Documento)
class DocumentoAdmin(admin.ModelAdmin):
    list_display = ("titulo", "publico", "subido_por", "creado_en")
    list_filter = ("publico",)
    search_fields = ("titulo",)

