from django.apps import AppConfig

class FMConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'FM'
    label = 'FM'   # mantenemos el mismo label (tablas "FM_*")

