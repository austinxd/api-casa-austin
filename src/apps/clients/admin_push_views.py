from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework_simplejwt.authentication import JWTAuthentication
from django.db.models import Count, Q
import logging

from .models import AdminPushToken
from .expo_push_service import ExpoPushService

logger = logging.getLogger(__name__)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def register_admin_push_token(request):
    """
    Registra un token de notificaciones push para un administrador
    
    POST /api/v1/admin/push/register/
    Headers: Authorization: Bearer <jwt_token>
    Body:
    {
        "expo_token": "ExponentPushToken[xxxxxxxxxxxxxx]",
        "device_type": "ios",  // o "android"
        "device_name": "iPhone de Admin"  // opcional
    }
    """
    user = request.user
    expo_token = request.data.get('expo_token')
    device_type = request.data.get('device_type', 'android')
    device_name = request.data.get('device_name', None)
    
    if not expo_token:
        return Response(
            {'error': 'expo_token es requerido'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    if not expo_token.startswith('ExponentPushToken['):
        return Response(
            {'error': 'Token Expo inválido. Debe comenzar con "ExponentPushToken["'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    try:
        token, created = AdminPushToken.register_token(
            user=user,
            expo_token=expo_token,
            device_type=device_type,
            device_name=device_name
        )
        
        logger.info(f"✅ Token push registrado para admin {user.get_full_name()}: {expo_token[:20]}... ({'nuevo' if created else 'actualizado'})")
        
        return Response({
            'success': True,
            'message': 'Token registrado exitosamente' if created else 'Token actualizado',
            'token_id': str(token.id),
            'device_type': token.device_type,
            'created': created
        }, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)
        
    except Exception as e:
        logger.error(f"❌ Error al registrar token para {user.get_full_name()}: {str(e)}")
        return Response(
            {'error': f'Error al registrar token: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def unregister_admin_push_token(request):
    """
    Elimina un token de notificaciones push de un administrador
    
    DELETE /api/v1/admin/push/unregister/
    Headers: Authorization: Bearer <jwt_token>
    Body:
    {
        "expo_token": "ExponentPushToken[xxxxxxxxxxxxxx]"
    }
    """
    user = request.user
    expo_token = request.data.get('expo_token')
    
    if not expo_token:
        return Response(
            {'error': 'expo_token es requerido'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    try:
        token = AdminPushToken.objects.get(
            user=user,
            expo_token=expo_token,
            deleted=False
        )
        token.delete()
        
        logger.info(f"🗑️ Token push eliminado para admin {user.get_full_name()}: {expo_token[:20]}...")
        
        return Response({
            'success': True,
            'message': 'Token eliminado exitosamente'
        }, status=status.HTTP_200_OK)
        
    except AdminPushToken.DoesNotExist:
        return Response(
            {'error': 'Token no encontrado'},
            status=status.HTTP_404_NOT_FOUND
        )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def list_admin_push_devices(request):
    """
    Lista todos los dispositivos registrados del administrador
    
    GET /api/v1/admin/push/devices/
    Headers: Authorization: Bearer <jwt_token>
    """
    user = request.user
    
    tokens = AdminPushToken.objects.filter(
        user=user,
        deleted=False
    ).order_by('-created')
    
    devices = [{
        'id': str(token.id),
        'expo_token': token.expo_token,
        'device_type': token.device_type,
        'device_name': token.device_name,
        'is_active': token.is_active,
        'last_used': token.last_used,
        'failed_attempts': token.failed_attempts,
        'created': token.created
    } for token in tokens]
    
    return Response({
        'success': True,
        'devices': devices,
        'total': len(devices)
    }, status=status.HTTP_200_OK)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def test_admin_push_notification(request):
    """
    Envía una notificación push de prueba al administrador
    
    POST /api/v1/admin/push/test/
    Headers: Authorization: Bearer <jwt_token>
    """
    user = request.user
    
    tokens = AdminPushToken.get_active_tokens_for_user(user)
    
    if not tokens.exists():
        return Response({
            'success': False,
            'error': 'No tienes dispositivos registrados con tokens activos'
        }, status=status.HTTP_400_BAD_REQUEST)
    
    result = ExpoPushService.send_to_admins(
        title="Notificación de Prueba",
        body=f"Hola {user.first_name}, tu sistema de notificaciones push está funcionando correctamente.",
        data={
            'type': 'test',
            'timestamp': str(tokens.first().created)
        },
        user_filter=user
    )
    
    return Response(result, status=status.HTTP_200_OK)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def admin_push_stats(request):
    """
    Estadísticas de tokens push de administradores (solo para superusuarios)
    
    GET /api/v1/admin/push/stats/
    Headers: Authorization: Bearer <jwt_token>
    """
    user = request.user
    
    if not user.is_staff and not user.is_superuser:
        return Response(
            {'error': 'No tienes permisos para ver estas estadísticas'},
            status=status.HTTP_403_FORBIDDEN
        )
    
    stats = {
        'total_tokens': AdminPushToken.objects.filter(deleted=False).count(),
        'active_tokens': AdminPushToken.objects.filter(is_active=True, deleted=False).count(),
        'inactive_tokens': AdminPushToken.objects.filter(is_active=False, deleted=False).count(),
        'by_device_type': {
            'ios': AdminPushToken.objects.filter(device_type='ios', deleted=False).count(),
            'android': AdminPushToken.objects.filter(device_type='android', deleted=False).count()
        },
        'admins_with_tokens': AdminPushToken.objects.filter(deleted=False).values('user').distinct().count()
    }
    
    return Response({
        'success': True,
        'stats': stats
    }, status=status.HTTP_200_OK)
