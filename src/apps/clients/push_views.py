from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from django.utils import timezone
import logging

from .authentication import ClientJWTAuthentication
from .models import PushToken, Clients
from .expo_push_service import ExpoPushService, NotificationTypes

logger = logging.getLogger(__name__)


class RegisterPushTokenView(APIView):
    """
    POST /api/v1/clients/push/register/
    
    Registra un token de dispositivo para recibir notificaciones push.
    Requiere autenticación JWT del cliente.
    
    Body:
    {
        "expo_token": "ExponentPushToken[xxx]",
        "device_type": "android",  # o "ios"
        "device_name": "Mi iPhone"  # opcional
    }
    """
    authentication_classes = [ClientJWTAuthentication]
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        expo_token = request.data.get('expo_token')
        device_type = request.data.get('device_type', 'android')
        device_name = request.data.get('device_name')
        
        if not expo_token:
            return Response(
                {"error": "expo_token es requerido"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        if not ExpoPushService.is_valid_expo_token(expo_token):
            return Response(
                {"error": "Formato de token inválido. Debe ser ExponentPushToken[xxx]"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        if device_type not in ['android', 'ios']:
            device_type = 'android'
        
        try:
            token, created = PushToken.register_token(
                client=request.user,
                expo_token=expo_token,
                device_type=device_type,
                device_name=device_name
            )
            
            return Response({
                "success": True,
                "message": "Token registrado exitosamente" if created else "Token actualizado",
                "created": created,
                "token_id": str(token.id)
            }, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)
            
        except Exception as e:
            logger.error(f"Error registering push token: {str(e)}")
            return Response(
                {"error": "Error al registrar el token"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class UnregisterPushTokenView(APIView):
    """
    DELETE /api/v1/clients/push/unregister/
    
    Elimina un token de dispositivo (logout o desactivar notificaciones).
    
    Body:
    {
        "expo_token": "ExponentPushToken[xxx]"
    }
    """
    authentication_classes = [ClientJWTAuthentication]
    permission_classes = [IsAuthenticated]
    
    def delete(self, request):
        expo_token = request.data.get('expo_token')
        
        if not expo_token:
            return Response(
                {"error": "expo_token es requerido"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            deleted_count, _ = PushToken.objects.filter(
                client=request.user,
                expo_token=expo_token
            ).delete()
            
            if deleted_count > 0:
                return Response({
                    "success": True,
                    "message": "Token eliminado exitosamente"
                }, status=status.HTTP_200_OK)
            else:
                return Response(
                    {"error": "Token no encontrado"},
                    status=status.HTTP_404_NOT_FOUND
                )
                
        except Exception as e:
            logger.error(f"Error unregistering push token: {str(e)}")
            return Response(
                {"error": "Error al eliminar el token"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class ClientPushTokensView(APIView):
    """
    GET /api/v1/clients/push/devices/
    
    Lista los dispositivos registrados del cliente.
    """
    authentication_classes = [ClientJWTAuthentication]
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        tokens = PushToken.objects.filter(
            client=request.user,
            deleted=False
        ).values(
            'id', 'device_type', 'device_name', 'is_active', 
            'last_used', 'created'
        )
        
        return Response({
            "devices": list(tokens),
            "count": len(tokens)
        })


class TestPushNotificationView(APIView):
    """
    POST /api/v1/clients/push/test/
    
    Envía una notificación de prueba al cliente autenticado.
    Útil para verificar que las notificaciones funcionan.
    """
    authentication_classes = [ClientJWTAuthentication]
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        client = request.user
        
        notification = NotificationTypes.custom(
            title="Prueba de Notificación",
            body=f"Hola {client.first_name}, las notificaciones funcionan correctamente.",
            data={"type": "test", "timestamp": str(timezone.now())}
        )
        
        result = ExpoPushService.send_to_client(
            client=client,
            title=notification["title"],
            body=notification["body"],
            data=notification["data"]
        )
        
        if result.get("success"):
            return Response({
                "success": True,
                "message": f"Notificación enviada a {result.get('sent', 0)} dispositivo(s)",
                "details": result
            })
        else:
            return Response({
                "success": False,
                "error": result.get("error", "Error desconocido"),
                "details": result
            }, status=status.HTTP_400_BAD_REQUEST)


class AdminSendNotificationView(APIView):
    """
    POST /api/v1/admin/push/send/
    
    Endpoint administrativo para enviar notificaciones.
    Requiere autenticación de admin/staff.
    
    Body:
    {
        "client_id": "uuid",  # o "all" para todos
        "title": "Título",
        "body": "Mensaje",
        "data": {}  # opcional
    }
    """
    permission_classes = [IsAdminUser]
    
    def post(self, request):
        client_id = request.data.get('client_id')
        title = request.data.get('title')
        body = request.data.get('body')
        data = request.data.get('data', {})
        
        if not title or not body:
            return Response(
                {"error": "title y body son requeridos"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        if client_id == "all":
            tokens = PushToken.objects.filter(
                is_active=True,
                deleted=False
            ).values_list('expo_token', flat=True)
            
            if not tokens:
                return Response(
                    {"error": "No hay dispositivos registrados"},
                    status=status.HTTP_404_NOT_FOUND
                )
            
            result = ExpoPushService.send_bulk_notifications(
                tokens=list(tokens),
                title=title,
                body=body,
                data=data
            )
        else:
            try:
                client = Clients.objects.get(id=client_id, deleted=False)
            except Clients.DoesNotExist:
                return Response(
                    {"error": "Cliente no encontrado"},
                    status=status.HTTP_404_NOT_FOUND
                )
            
            result = ExpoPushService.send_to_client(
                client=client,
                title=title,
                body=body,
                data=data
            )
        
        return Response({
            "success": result.get("success", False),
            "sent": result.get("sent", 0),
            "failed": result.get("failed", 0),
            "details": result
        })


class AdminPushStatsView(APIView):
    """
    GET /api/v1/admin/push/stats/
    
    Estadísticas de tokens push registrados.
    """
    permission_classes = [IsAdminUser]
    
    def get(self, request):
        from django.db.models import Count
        
        total = PushToken.objects.filter(deleted=False).count()
        active = PushToken.objects.filter(is_active=True, deleted=False).count()
        inactive = total - active
        
        by_device = PushToken.objects.filter(deleted=False).values('device_type').annotate(
            count=Count('id')
        )
        
        clients_with_tokens = PushToken.objects.filter(
            is_active=True, deleted=False
        ).values('client').distinct().count()
        
        return Response({
            "total_tokens": total,
            "active_tokens": active,
            "inactive_tokens": inactive,
            "by_device_type": {item['device_type']: item['count'] for item in by_device},
            "clients_with_push": clients_with_tokens
        })
