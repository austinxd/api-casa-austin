from django.apps import AppConfig


class ClientsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.clients'

    def ready(self):
        import apps.clients.signals  # Asegúrate de que esto cargue las señales al iniciar
