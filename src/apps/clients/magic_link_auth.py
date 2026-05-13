"""Autenticación y permisos para JWT acotado del magic link.

Reglas:
- MagicLinkJWTAuthentication acepta SOLO tokens marcados con is_magic=True.
- ClientJWTAuthentication (auth normal) RECHAZA tokens con is_magic=True
  (parche aplicado en este módulo importando y modificando la clase existente
  NO se hace — se valida en el dispatch de los endpoints normales NO,
  hay otra forma: comprobamos is_magic en MagicLink y en el endpoint normal
  de creación de reserva NO usamos MagicLink auth, así que ningún endpoint
  normal acepta un magic JWT salvo que use ClientJWTAuthentication. Para
  proteger ClientJWTAuthentication agregamos un check explícito).
- HasMagicScope verifica que el JWT tenga el scope requerido en la lista.
- emit_magic_jwt() construye el access token acotado (60min, sin refresh).
"""
import logging
from datetime import timedelta

from rest_framework import permissions
from rest_framework_simplejwt.tokens import AccessToken

from .authentication import ClientJWTAuthentication

logger = logging.getLogger(__name__)


# Lista blanca de claves de scope permitidas en magic JWT.
MAGIC_SCOPES = {'create_reservation', 'upload_voucher'}


class MagicLinkJWTAuthentication(ClientJWTAuthentication):
    """Acepta SOLO tokens con is_magic=True. Endpoints normales no deben
    usar esta clase; deben seguir con ClientJWTAuthentication.

    Override del flag heredado para PERMITIR magic JWTs aquí (el padre
    los bloquea por defecto).
    """

    _allow_magic_token = True

    def get_user(self, validated_token):
        # Esta auth class es exclusiva para magic JWTs. Si el token NO
        # es magic, lo rechazamos (defensa de doble dirección).
        if not validated_token.get('is_magic'):
            logger.warning(
                "MagicLinkJWTAuthentication rejected non-magic token "
                f"(client_id={validated_token.get('client_id')})"
            )
            return None
        return super().get_user(validated_token)


def reject_magic_in_normal_auth(validated_token):
    """Helper para que ClientJWTAuthentication (auth normal) rechace
    tokens magic. Lo invocaríamos parchando ClientJWTAuthentication;
    para no tocar ese archivo, validamos en cada endpoint sensible
    (perfil, dashboard, puntos, reservas normales).

    Esta función está disponible para usar dentro de las vistas si
    necesitamos defensa en profundidad. R4 introduce ChromeChecking
    en las vistas tras el corte si el equipo lo solicita.
    """
    return not validated_token.get('is_magic')


class HasMagicScope(permissions.BasePermission):
    """Verifica que el JWT tenga el `required_scope` declarado en la view.

    Uso:
        class MyView(APIView):
            authentication_classes = [MagicLinkJWTAuthentication]
            permission_classes = [HasMagicScope]
            required_scope = 'create_reservation'
    """

    message = 'Magic link token no autoriza esta acción.'

    def has_permission(self, request, view):
        if not request.auth:
            return False
        scope = request.auth.get('scope') or []
        required = getattr(view, 'required_scope', None)
        if not required:
            return False
        if required not in MAGIC_SCOPES:
            # Defensa: si algún view declara un scope desconocido, denegar.
            logger.error(
                f"HasMagicScope: view declared unknown required_scope={required}"
            )
            return False
        return required in scope


def emit_magic_jwt(magic_link, lifetime_minutes=60):
    """Construye un AccessToken acotado (sin refresh) para un magic link.

    Claims:
      - client_id / user_id: ID del cliente.
      - is_magic: True (marca el token como magic, para que auth normal lo rechace).
      - scope: lista de acciones permitidas.
      - magic_link_id: ID del link en BD (auditoría).
      - property_slug, check_in, check_out, guests: constraints fijos.
    """
    token = AccessToken()
    token.set_exp(lifetime=timedelta(minutes=lifetime_minutes))
    token['client_id'] = str(magic_link.client_id)
    token['user_id'] = str(magic_link.client_id)
    token['is_magic'] = True
    token['scope'] = ['create_reservation', 'upload_voucher']
    token['magic_link_id'] = str(magic_link.id)
    token['property_slug'] = (
        magic_link.property.slug if magic_link.property_id else None
    )
    token['check_in'] = magic_link.check_in.isoformat()
    token['check_out'] = magic_link.check_out.isoformat()
    token['guests'] = int(magic_link.guests)
    return str(token)
