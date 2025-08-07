from django.apps import AppConfig


class ReservationConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.reservation'
    
    def ready(self):
        import apps.reservation.signals

    def ready(self):
        import apps.reservation.signals
        import apps.reservation.points_signals