"""
Custom middleware for Casa Austin API.
"""

from simple_history.middleware import HistoryRequestMiddleware
from simple_history.signals import pre_create_historical_record


def filter_history_user(sender, **kwargs):
    """
    Signal handler para filtrar el history_user antes de crear el registro histórico.

    simple_history espera que history_user sea una instancia de AUTH_USER_MODEL
    (CustomUser), pero cuando los clientes se autentican via ClientJWTAuthentication,
    request.user es una instancia de Clients, lo que causa un error:
    "HistoricalReservation.history_user must be a CustomUser instance"

    Esta función verifica el tipo de usuario y lo establece a None si no es CustomUser.
    """
    from apps.accounts.models import CustomUser

    history_instance = kwargs.get('history_instance')
    if history_instance:
        history_user = getattr(history_instance, 'history_user', None)
        if history_user is not None and not isinstance(history_user, CustomUser):
            # Si el usuario no es CustomUser (ej: Clients), limpiar el campo
            history_instance.history_user = None


# Conectar el signal handler
pre_create_historical_record.connect(filter_history_user)


class CustomHistoryRequestMiddleware(HistoryRequestMiddleware):
    """
    Middleware personalizado para django-simple-history.

    Extiende el middleware original y usa el signal handler para filtrar
    usuarios que no son CustomUser antes de guardar el registro histórico.
    """
    pass  # El filtrado se hace en el signal handler filter_history_user
