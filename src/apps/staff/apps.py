
from django.apps import AppConfig


class StaffConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.staff'
    verbose_name = 'Gestión de Personal'
    
    def ready(self):
        import apps.staff.models  # Para cargar las señales
