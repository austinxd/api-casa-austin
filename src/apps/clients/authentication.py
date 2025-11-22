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

    def get_user(self, validated_token):
        """
        Override to get client instead of user.
        
        Looks for client_id or user_id claim in the token and returns
        the corresponding Client object.
        """
        try:
            client_id = validated_token.get('client_id')
            if not client_id:
                client_id = validated_token.get('user_id')

            if client_id:
                return Clients.objects.get(id=client_id, deleted=False)
        except Clients.DoesNotExist:
            pass
        return None
