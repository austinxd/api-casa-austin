from rest_framework_simplejwt.authentication import JWTAuthentication
from .models import Clients


class ClientJWTAuthentication(JWTAuthentication):
    """
    Custom JWT Authentication backend for Clients model.

    Overrides the default JWTAuthentication to authenticate against
    the Clients model (UUID primary key) instead of the CustomUser model
    (integer primary key).

    This prevents ValueError when JWT tokens contain client UUIDs but
    SimpleJWT tries to look them up in the CustomUser table.
    """

    # R4 → decisión actual: el cliente con magic JWT tiene los MISMOS
    # permisos que un cliente normal sobre SUS propios datos. Razonable
    # porque:
    #   - El link es one-shot (mark_consumed tras crear reserva).
    #   - El JWT solo expone los datos del cliente vinculado (client_id).
    #   - Los endpoints admin usan otra auth (IsAdminUser), no esta clase.
    # Mantenemos el flag por si en el futuro queremos restringir, pero por
    # ahora aceptamos magic tokens en endpoints normales del cliente.
    _allow_magic_token = True

    def get_user(self, validated_token):
        """
        Override to get client instead of user.

        Looks for client_id or user_id claim in the token and returns
        the corresponding Client object.

        Si _allow_magic_token=False, bloquea tokens con is_magic=True.
        Por defecto _allow_magic_token=True para que el flujo del link
        mágico (voucher upload, pago con tarjeta, ver reserva propia)
        funcione sin re-login.
        """
        if validated_token.get('is_magic') and not self._allow_magic_token:
            return None
        try:
            client_id = validated_token.get('client_id')
            if not client_id:
                client_id = validated_token.get('user_id')

            if client_id:
                return Clients.objects.get(id=client_id, deleted=False)
        except Clients.DoesNotExist:
            pass
        return None
