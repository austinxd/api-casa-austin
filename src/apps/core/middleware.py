"""
Custom middleware for Casa Austin API.
"""


class HistoryUserWrapper:
    """
    Wrapper para el request que filtra el usuario para simple_history.

    Si el usuario no es CustomUser, retorna None para history_user.
    """
    def __init__(self, request):
        self._request = request
        self._history_user_checked = False
        self._history_user_value = None

    def __getattr__(self, name):
        if name == 'user':
            return self._get_filtered_user()
        return getattr(self._request, name)

    def _get_filtered_user(self):
        """Retorna el usuario solo si es CustomUser, sino None."""
        from apps.accounts.models import CustomUser

        original_user = getattr(self._request, 'user', None)
        if original_user and isinstance(original_user, CustomUser):
            return original_user
        # Retornar un objeto que simula un usuario anónimo para simple_history
        return None


def CustomHistoryRequestMiddleware(get_response):
    """
    Middleware personalizado para django-simple-history.

    Intercepta el request y filtra el usuario para que simple_history
    solo registre cambios con usuarios que son CustomUser.
    Cuando el usuario es Clients (u otro tipo), history_user será NULL.
    """
    from simple_history.models import HistoricalRecords

    def middleware(request):
        # Procesar la respuesta primero
        response = get_response(request)
        return response

    def set_history_context(request):
        """Configura el contexto de simple_history con el request filtrado."""
        from apps.accounts.models import CustomUser

        # Solo establecer el contexto si el usuario es CustomUser
        if hasattr(request, 'user') and isinstance(request.user, CustomUser):
            HistoricalRecords.context.request = request
        else:
            # Crear un request wrapper que retorna None para user
            HistoricalRecords.context.request = HistoryUserWrapper(request)

    def middleware_with_history(request):
        set_history_context(request)
        response = get_response(request)
        return response

    return middleware_with_history
